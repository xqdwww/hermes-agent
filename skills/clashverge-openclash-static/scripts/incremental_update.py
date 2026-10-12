#!/usr/bin/env python3
"""Pure planning and candidate-building helpers for incremental updates.

The controller owns source snapshots, router I/O, probe execution, and upload
coordination.  This module deliberately only compares two already-loaded
configurations and constructs the next candidate from them.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Iterable, Mapping, Sequence


class IncrementalUpdateError(RuntimeError):
    """Raised when an incremental candidate cannot be built safely."""


ConfigError = IncrementalUpdateError

_BUILTIN_TARGETS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE"}
_HISTORY_GROUPS = {"GPT历史LKG", "Gemini历史LKG"}
_EMERGENCY_GROUP_NAME = "AI应急（未验证）"
_SERVICE_GROUPS = {
    "gpt": ("GPT候选", "GPT手动", "GPT专用"),
    "gemini": ("Gemini候选", "Gemini手动", "Gemini专用"),
    "disney": ("迪士尼候选", "迪士尼手动", "迪士尼"),
}
_MANAGED_GROUPS = {
    "默认代理",
    "手动选择",
    "自动选择",
    *(group for groups in _SERVICE_GROUPS.values() for group in groups),
}
_HK_LABEL_RE = re.compile(
    r"香港|🇭🇰|hong[\s_-]*kong|(?<![A-Za-z])hk(?![A-Za-z])", re.IGNORECASE
)


def _raise(skill: Any, message: str) -> None:
    error_type = getattr(skill, "ConfigError", IncrementalUpdateError)
    raise error_type(message)


def _as_name(value: Any, *, skill: Any, context: str) -> str:
    if not isinstance(value, str) or not value or not value.strip():
        _raise(skill, f"INCREMENTAL_INVALID_NAME:{context}")
    return value


def _proxy_map(
    data: Mapping[str, Any], *, skill: Any, context: str
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return ordered static proxies and an exact-name map.

    ``static_proxy_objects`` is the source of truth for duplicate and malformed
    proxy validation.  The additional map check makes the exact-string policy
    explicit and avoids any normalization or identity rebinding.
    """

    try:
        raw = skill.static_proxy_objects(deepcopy(dict(data)))
    except Exception as exc:
        if isinstance(exc, getattr(skill, "ConfigError", ())):
            raise
        _raise(skill, f"INCREMENTAL_PROXY_VALIDATION_FAILED:{exc}")
    proxies = [deepcopy(proxy) for proxy in raw]
    by_name: dict[str, dict[str, Any]] = {}
    for index, proxy in enumerate(proxies):
        if not isinstance(proxy, dict):
            _raise(skill, f"INCREMENTAL_INVALID_PROXY:{context}:{index}")
        name = _as_name(proxy.get("name"), skill=skill, context=f"{context}:{index}")
        if name in by_name:
            _raise(skill, f"INCREMENTAL_DUPLICATE_NAME:{name}")
        by_name[name] = proxy
    if not proxies:
        _raise(skill, f"INCREMENTAL_EMPTY_SOURCE:{context}")
    return proxies, by_name


def plan_nodes(
    old_data: Mapping[str, Any],
    new_data: Mapping[str, Any],
    skill: Any,
) -> dict[str, Any]:
    """Classify nodes using exact display-name strings only.

    A common name is retained as a policy carry regardless of whether its
    connection object changed.  The controller may therefore replace the
    complete object for every common name while testing only names that are
    genuinely new.
    """

    old_proxies, old_by_name = _proxy_map(old_data, skill=skill, context="baseline")
    new_proxies, new_by_name = _proxy_map(new_data, skill=skill, context="snapshot")
    old_names = [str(proxy["name"]) for proxy in old_proxies]
    new_names = [str(proxy["name"]) for proxy in new_proxies]
    old_set = set(old_names)
    new_set = set(new_names)

    added = [name for name in new_names if name not in old_set]
    removed = [name for name in old_names if name not in new_set]
    reused = [name for name in old_names if name in new_set]
    parameter_changed = [
        name for name in reused if old_by_name[name] != new_by_name[name]
    ]
    statuses = {
        name: (
            "PARAMETERS_CHANGED_NOT_RETESTED"
            if name in set(parameter_changed)
            else "NAME_REUSED_NOT_RETESTED"
        )
        for name in reused
    }
    statuses.update({name: "REMOVED" for name in removed})
    statuses.update({name: "ADDED_PENDING_VERIFICATION" for name in added})
    return {
        "added_names": added,
        "removed_names": removed,
        "reused_names": reused,
        "parameter_changed_names": parameter_changed,
        "name_status": statuses,
        "old_service_tests": 0,
    }


def _group_map(data: Mapping[str, Any], *, skill: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    groups = data.get("proxy-groups")
    if not isinstance(groups, list):
        _raise(skill, "INCREMENTAL_GROUPS_NOT_LIST")
    copied: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            _raise(skill, f"INCREMENTAL_INVALID_GROUP:{index}")
        name = _as_name(group.get("name"), skill=skill, context=f"group:{index}")
        if name in by_name:
            _raise(skill, f"INCREMENTAL_DUPLICATE_GROUP:{name}")
        refs = group.get("proxies")
        if not isinstance(refs, list):
            _raise(skill, f"INCREMENTAL_GROUP_PROXIES_NOT_LIST:{name}")
        copied_group = deepcopy(group)
        copied.append(copied_group)
        by_name[name] = copied_group
    return copied, by_name


def _rule_target(rule: str, skill: Any) -> str | None:
    helper = getattr(skill, "rule_target", None)
    if helper is not None:
        return helper(rule)
    parts = [part.strip() for part in rule.split(",")]
    if not parts:
        return None
    if parts[0].upper() == "MATCH":
        return parts[1] if len(parts) > 1 else None
    if parts[-1].lower() == "no-resolve":
        return parts[-2] if len(parts) >= 3 else None
    return parts[-1] if len(parts) >= 2 else None


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _is_hong_kong_label(name: str) -> bool:
    return bool(_HK_LABEL_RE.search(name))


def eligible_ai_rrc_names(added_names: Iterable[str]) -> list[str]:
    """Return added names that could enter service-specific AI screening."""

    return [
        name
        for name in added_names
        if isinstance(name, str)
        and "流媒体" not in name
    ]


def _filtered_concrete(
    refs: Sequence[Any],
    *,
    old_names: set[str],
    current_names: set[str],
    excluded_names: set[str],
) -> list[str]:
    """Keep only baseline concrete names, with exact-name exclusions."""

    return _ordered_unique(
        str(ref)
        for ref in refs
        if isinstance(ref, str)
        and ref in old_names
        and ref in current_names
        and ref not in excluded_names
    )


def _require_service_groups(
    groups: Mapping[str, dict[str, Any]], *, service: str, skill: Any
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate_name, manual_name, dedicated_name = _SERVICE_GROUPS[service]
    missing = [
        name
        for name in (candidate_name, manual_name, dedicated_name)
        if name not in groups
    ]
    if missing:
        _raise(skill, "INCREMENTAL_REQUIRED_GROUP_MISSING:" + ",".join(missing))
    return groups[candidate_name], groups[manual_name], groups[dedicated_name]


def _prepare_ai_groups(
    *,
    groups: Mapping[str, dict[str, Any]],
    service: str,
    old_names: set[str],
    current_names: set[str],
    current_order: Sequence[str],
    added_names: Sequence[str],
    registry_names: Iterable[str],
    verified_names: Iterable[str],
    measured_hk_names: set[str],
    blocked_names: set[str],
    skill: Any,
) -> list[str]:
    candidate, manual, dedicated = _require_service_groups(
        groups, service=service, skill=skill
    )
    candidate_refs = _filtered_concrete(
        candidate["proxies"],
        old_names=old_names,
        current_names=current_names,
        excluded_names=measured_hk_names | blocked_names,
    )
    if service == "gpt":
        candidate_refs = [
            name for name in candidate_refs if not _is_hong_kong_label(name)
        ]
    registry_set = {
        name
        for name in (registry_names or ())
        if isinstance(name, str)
        and name in current_names
        and name not in measured_hk_names
        and name not in blocked_names
        and not (service == "gpt" and _is_hong_kong_label(name))
    }
    verified_set = {
        name for name in (verified_names or ()) if isinstance(name, str)
    }
    admitted = _ordered_unique(
        name
        for name in added_names
        if name in verified_set
        and name in current_names
        and name not in measured_hk_names
        and name not in blocked_names
        and not (service == "gpt" and _is_hong_kong_label(name))
        and "流媒体" not in name
    )
    # Registry reuse and fresh actual-use admissions are both ordered by the
    # current source snapshot.  Registry entries are already identity-bound by
    # the runner; this function only applies service policy and current-name
    # checks.
    current_verified = [
        name
        for name in current_order
        if name in registry_set or name in set(admitted)
    ]
    candidate_refs = _ordered_unique([*candidate_refs, *current_verified])
    # The candidate pool is the only automatic admission source.  Manual
    # concrete entries remain historical policy unless a current-snapshot,
    # actual-use result explicitly admits a new name.
    if not candidate_refs:
        _raise(
            skill,
            "BLOCKED_NO_CURRENT_SERVICE_CANDIDATES:"
            + service.upper(),
        )
    candidate["proxies"] = candidate_refs
    manual_concrete = _ordered_unique(
        name
        for name in current_order
        if name in current_names
        and name not in blocked_names
        and not (service == "gpt" and _is_hong_kong_label(name))
    )
    manual["proxies"] = [*manual_concrete, _SERVICE_GROUPS[service][0]]
    dedicated["proxies"] = [
        _SERVICE_GROUPS[service][1],
        _SERVICE_GROUPS[service][0],
        _EMERGENCY_GROUP_NAME,
    ]
    return admitted


def _prepare_disney_group(
    *,
    groups: Mapping[str, dict[str, Any]],
    old_names: set[str],
    current_names: set[str],
    added_names: Sequence[str],
    disney_pass_names: Iterable[str],
    skill: Any,
) -> list[str]:
    candidate, manual, dedicated = _require_service_groups(
        groups, service="disney", skill=skill
    )
    baseline_candidate = _filtered_concrete(
        candidate["proxies"],
        old_names=old_names,
        current_names=current_names,
        excluded_names=set(),
    )
    baseline_manual = _filtered_concrete(
        manual["proxies"],
        old_names=old_names,
        current_names=current_names,
        excluded_names=set(),
    )
    added_set = set(added_names)
    passed = _ordered_unique(
        name
        for name in disney_pass_names
        if isinstance(name, str) and name in added_set and name in current_names
    )
    pool = _ordered_unique([*baseline_candidate, *passed])
    if not pool:
        _raise(skill, "BLOCKED_NO_CURRENT_SERVICE_CANDIDATES:DISNEY")
    manual_concrete = _ordered_unique([*baseline_manual, *passed])
    candidate["proxies"] = pool
    manual["proxies"] = [*manual_concrete, "迪士尼候选"]
    dedicated["proxies"] = ["迪士尼手动", "迪士尼候选"]
    return passed


def _prepare_general_groups(
    *,
    groups: Mapping[str, dict[str, Any]],
    old_names: set[str],
    current_names: set[str],
    added_names: Sequence[str],
    skill: Any,
) -> None:
    """Prune deleted direct nodes and append new nodes to general selectors."""

    group_names = set(groups)
    builtins = set(getattr(skill, "BUILTIN_TARGETS", _BUILTIN_TARGETS))
    ai_group_names = {
        group
        for names in _SERVICE_GROUPS.values()
        for group in names
    }
    for group_name, group in groups.items():
        if group_name in ai_group_names:
            continue
        cleaned: list[str] = []
        for ref in group["proxies"]:
            if not isinstance(ref, str):
                _raise(skill, f"INCREMENTAL_NONSTRING_REFERENCE:{group_name}")
            if ref in _HISTORY_GROUPS:
                continue
            if ref in current_names or ref in group_names or ref in builtins:
                cleaned.append(ref)
            elif ref in old_names:
                # A deleted direct node is removed from every ordinary group.
                continue
            else:
                _raise(skill, f"INCREMENTAL_UNKNOWN_REFERENCE:{group_name}:{ref}")
        if group_name in {"手动选择", "自动选择"}:
            cleaned.extend(name for name in added_names if name not in cleaned)
        group["proxies"] = _ordered_unique(cleaned)


def _prepare_emergency_group(
    *,
    groups: list[dict[str, Any]],
    source_names: Sequence[str],
    skill: Any,
) -> None:
    """Regenerate the manual emergency selector from the fresh source order."""

    node_names = _ordered_unique(source_names)
    if not node_names:
        _raise(skill, "INCREMENTAL_EMERGENCY_GROUP_EMPTY")
    group_names = {str(group.get("name")) for group in groups}
    collisions = set(node_names) & (group_names | _BUILTIN_TARGETS)
    if collisions:
        _raise(
            skill,
            "INCREMENTAL_EMERGENCY_NODE_COLLISION:" + ",".join(sorted(collisions)),
        )
    groups[:] = [
        group for group in groups if group.get("name") != _EMERGENCY_GROUP_NAME
    ]
    groups.append(
        {
            "name": _EMERGENCY_GROUP_NAME,
            "type": "select",
            "proxies": node_names,
        }
    )


def _clean_rules(
    output: dict[str, Any],
    *,
    old_names: set[str],
    current_names: set[str],
    group_names: set[str],
    skill: Any,
) -> None:
    rules = output.get("rules")
    if not isinstance(rules, list):
        _raise(skill, "INCREMENTAL_RULES_NOT_LIST")
    builtins = set(getattr(skill, "BUILTIN_TARGETS", _BUILTIN_TARGETS))
    cleaned: list[str] = []
    for rule in rules:
        if not isinstance(rule, str):
            _raise(skill, "INCREMENTAL_NONSTRING_RULE")
        target = _rule_target(rule, skill)
        if target in _HISTORY_GROUPS:
            continue
        if target in old_names and target not in current_names:
            continue
        if target and target not in current_names and target not in group_names and target not in builtins:
            _raise(skill, f"INCREMENTAL_UNKNOWN_RULE_REFERENCE:{target}")
        cleaned.append(rule)
    output["rules"] = cleaned


def _prune_groups(
    output: dict[str, Any],
    *,
    old_names: set[str],
    current_names: set[str],
    skill: Any,
) -> None:
    """Remove history groups and empty nonessential groups to a fixed point."""

    groups = output["proxy-groups"]
    history = _HISTORY_GROUPS
    groups[:] = [group for group in groups if group["name"] not in history]
    by_name = {group["name"]: group for group in groups}
    group_names = set(by_name)
    builtins = set(getattr(skill, "BUILTIN_TARGETS", _BUILTIN_TARGETS))

    # Groups required by the public managed structure or by a rule are never
    # silently removed.  References from those groups make their dependencies
    # required as well, giving recursive fail-closed semantics.
    required = {
        name for name in group_names if name in _MANAGED_GROUPS
    }
    for rule in output.get("rules", []):
        if isinstance(rule, str):
            target = _rule_target(rule, skill)
            if target in group_names:
                required.add(target)
    changed = True
    while changed:
        changed = False
        for name in list(required):
            group = by_name.get(name)
            if not group:
                continue
            for ref in group.get("proxies", []):
                if isinstance(ref, str) and ref in group_names and ref not in required:
                    required.add(ref)
                    changed = True

    while True:
        group_names = set(by_name)
        empty_names: set[str] = set()
        for group in groups:
            name = str(group["name"])
            refs: list[str] = []
            # Removed groups are pruned as references disappear.  Any remaining
            # unknown reference is a hard error rather than an invented target.
            for ref in group.get("proxies", []):
                if not isinstance(ref, str):
                    _raise(skill, f"INCREMENTAL_NONSTRING_REFERENCE:{name}")
                if ref in current_names or ref in group_names or ref in builtins:
                    refs.append(ref)
                elif ref in old_names:
                    # A deleted direct node is removed from every group.
                    continue
                else:
                    _raise(skill, f"INCREMENTAL_UNKNOWN_REFERENCE:{name}:{ref}")
            group["proxies"] = _ordered_unique(refs)
            if not group["proxies"]:
                empty_names.add(name)

        if not empty_names:
            break
        required_empty = empty_names & required
        if required_empty:
            _raise(
                skill,
                "BLOCKED_REQUIRED_GROUP_EMPTY:" + sorted(required_empty)[0],
            )

        # Remove all newly empty optional groups together.  References to a
        # group removed in this pass must be dropped before the next pass so a
        # parent can become empty and be pruned recursively as well.
        for name in empty_names:
            group = by_name.pop(name)
            groups.remove(group)
        for group in groups:
            group["proxies"] = _ordered_unique(
                ref
                for ref in group.get("proxies", [])
                if ref not in empty_names or ref in current_names
            )

    remaining_names = {group["name"] for group in groups}
    for group in groups:
        for ref in group.get("proxies", []):
            if ref not in current_names and ref not in remaining_names and ref not in builtins:
                _raise(skill, f"INCREMENTAL_UNKNOWN_REFERENCE:{group['name']}:{ref}")


def _call_restrict_ai_groups(output: dict[str, Any], skill: Any) -> None:
    helper = getattr(skill, "restrict_ai_group_members", None)
    if helper is None:
        return
    helper(output)


def build_candidate(
    old_data: Mapping[str, Any],
    new_data: Mapping[str, Any],
    skill: Any,
    *,
    disney_pass_names: Iterable[str] = (),
    measured_hk_names: Iterable[str] = (),
    verified_gpt_names: Iterable[str] = (),
    verified_gemini_names: Iterable[str] = (),
    registry_gpt_names: Iterable[str] = (),
    registry_gemini_names: Iterable[str] = (),
    blocked_gpt_names: Iterable[str] = (),
    blocked_gemini_names: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a candidate while carrying policy by exact display name.

    Only added names admitted by ``disney_pass_names`` enter the Disney pool.
    GPT/Gemini pools are carried from the baseline candidate groups and admit
    only names explicitly supplied as current-snapshot actual-use results.
    Manual region blocks are service-specific exact names from definitive,
    current-snapshot functional failures.
    """

    plan = plan_nodes(old_data, new_data, skill)
    old_proxies, old_by_name = _proxy_map(old_data, skill=skill, context="baseline")
    new_proxies, new_by_name = _proxy_map(new_data, skill=skill, context="snapshot")
    old_names = set(old_by_name)
    current_names = set(new_by_name)
    current_order = [str(proxy["name"]) for proxy in new_proxies]
    added_names = list(plan["added_names"])
    registry_gpt_names = _ordered_unique(
        name for name in (registry_gpt_names or ()) if isinstance(name, str)
    )
    registry_gemini_names = _ordered_unique(
        name for name in (registry_gemini_names or ()) if isinstance(name, str)
    )

    groups, group_by_name = _group_map(old_data, skill=skill)
    output = deepcopy(dict(old_data))
    output["proxies"] = deepcopy(new_proxies)
    output["proxy-groups"] = groups

    # History groups are deliberately dropped before any selector is rebuilt.
    output["proxy-groups"] = [
        group
        for group in output["proxy-groups"]
        if group["name"] not in _HISTORY_GROUPS
        and group["name"] != _EMERGENCY_GROUP_NAME
    ]
    group_by_name = {group["name"]: group for group in output["proxy-groups"]}

    measured_hk_ordered = _ordered_unique(
        name
        for name in measured_hk_names
        if isinstance(name, str) and name in current_names
    )
    measured_hk = set(measured_hk_ordered)
    blocked_ordered = {
        "gpt": _ordered_unique(
            name
            for name in blocked_gpt_names
            if isinstance(name, str) and name in current_names
        ),
        "gemini": _ordered_unique(
            name
            for name in blocked_gemini_names
            if isinstance(name, str) and name in current_names
        ),
    }
    blocked_by_service = {
        service: set(names) for service, names in blocked_ordered.items()
    }
    admitted_gpt = _prepare_ai_groups(
        groups=group_by_name,
        service="gpt",
        old_names=old_names,
        current_names=current_names,
        current_order=current_order,
        added_names=added_names,
        registry_names=registry_gpt_names,
        verified_names=verified_gpt_names,
        measured_hk_names=measured_hk,
        blocked_names=blocked_by_service["gpt"],
        skill=skill,
    )
    admitted_gemini = _prepare_ai_groups(
        groups=group_by_name,
        service="gemini",
        old_names=old_names,
        current_names=current_names,
        current_order=current_order,
        added_names=added_names,
        registry_names=registry_gemini_names,
        verified_names=verified_gemini_names,
        measured_hk_names=measured_hk,
        blocked_names=blocked_by_service["gemini"],
        skill=skill,
    )
    accepted_disney = _prepare_disney_group(
        groups=group_by_name,
        old_names=old_names,
        current_names=current_names,
        added_names=added_names,
        disney_pass_names=disney_pass_names,
        skill=skill,
    )

    _prepare_general_groups(
        groups=group_by_name,
        old_names=old_names,
        current_names=current_names,
        added_names=added_names,
        skill=skill,
    )
    # Add a temporary current-source emergency group so references from the
    # dedicated selectors validate during pruning.  It is regenerated again
    # after the policy hook to cover no-op test doubles and stale snapshots.
    _prepare_emergency_group(
        groups=output["proxy-groups"],
        source_names=[str(proxy["name"]) for proxy in new_proxies],
        skill=skill,
    )
    group_by_name = {group["name"]: group for group in output["proxy-groups"]}
    _clean_rules(
        output,
        old_names=old_names,
        current_names=current_names,
        group_names=set(group_by_name),
        skill=skill,
    )
    _prune_groups(
        output,
        old_names=old_names,
        current_names=current_names,
        skill=skill,
    )

    # The shared policy helper applies the conservative label rule and keeps
    # dedicated AI groups limited to manual/candidate selectors.  The pools
    # above contain only explicitly admitted additions or carried candidates.
    _call_restrict_ai_groups(output, skill)
    _prepare_emergency_group(
        groups=output["proxy-groups"],
        source_names=[str(proxy["name"]) for proxy in new_proxies],
        skill=skill,
    )

    # A no-op or test double policy helper must not weaken the local invariant.
    final_groups = {group["name"]: group for group in output["proxy-groups"]}
    for service in ("gpt", "gemini"):
        candidate_name, manual_name, dedicated_name = _SERVICE_GROUPS[service]
        candidate = final_groups.get(candidate_name)
        manual = final_groups.get(manual_name)
        dedicated = final_groups.get(dedicated_name)
        if not candidate or not candidate.get("proxies"):
            _raise(skill, "BLOCKED_NO_CURRENT_SERVICE_CANDIDATES:" + service.upper())
        candidate_refs = candidate.get("proxies")
        if not isinstance(candidate_refs, list) or any(
            not isinstance(name, str) for name in candidate_refs
        ):
            _raise(skill, "INCREMENTAL_AI_CANDIDATE_GROUP_INVALID:" + service.upper())
        candidate_names = list(candidate_refs)
        if candidate_names != _ordered_unique(candidate_names):
            _raise(skill, "INCREMENTAL_AI_CANDIDATE_GROUP_INVALID:" + service.upper())
        admitted_names = {
            "gpt": set(admitted_gpt),
            "gemini": set(admitted_gemini),
        }[service]
        registry_names = {
            "gpt": set(registry_gpt_names),
            "gemini": set(registry_gemini_names),
        }[service]
        if any(
            name in added_names
            and (
                (name not in admitted_names and name not in registry_names)
                or name in measured_hk
            )
            for name in candidate_names
        ):
            _raise(skill, "INCREMENTAL_NEW_AI_ADMISSION_FORBIDDEN:" + service.upper())
        if any(
            name not in current_names
            or (
                name not in old_names
                and name not in admitted_names
                and name not in registry_names
            )
            or (service == "gpt" and _is_hong_kong_label(name))
            for name in candidate_names
        ):
            _raise(skill, "INCREMENTAL_AI_CANDIDATE_GROUP_INVALID:" + service.upper())
        if manual is None or dedicated is None:
            _raise(skill, "INCREMENTAL_REQUIRED_GROUP_MISSING:" + service.upper())
        expected_manual_names = _ordered_unique(
            name
            for name in current_order
            if name in current_names
            and name not in blocked_by_service[service]
            and not (service == "gpt" and _is_hong_kong_label(name))
        )
        if manual.get("proxies") != [*expected_manual_names, candidate_name]:
            _raise(skill, "INCREMENTAL_AI_MANUAL_GROUP_INVALID:" + service.upper())
        if dedicated.get("proxies") != [
            manual_name,
            candidate_name,
            _EMERGENCY_GROUP_NAME,
        ]:
            _raise(skill, "INCREMENTAL_AI_DEDICATED_GROUP_INVALID:" + service.upper())

    emergency_groups = [
        group
        for group in output["proxy-groups"]
        if group.get("name") == _EMERGENCY_GROUP_NAME
    ]
    expected_emergency_names = [str(proxy["name"]) for proxy in new_proxies]
    if len(emergency_groups) != 1 or emergency_groups[0].get("type") != "select":
        _raise(skill, "INCREMENTAL_EMERGENCY_GROUP_INVALID")
    if emergency_groups[0].get("proxies") != expected_emergency_names:
        _raise(skill, "INCREMENTAL_EMERGENCY_GROUP_INVALID")
    if output["proxy-groups"][-1] is not emergency_groups[0]:
        _raise(skill, "INCREMENTAL_EMERGENCY_GROUP_NOT_TAIL")
    if any(
        name in _BUILTIN_TARGETS or name in {group["name"] for group in output["proxy-groups"]}
        for name in expected_emergency_names
    ):
        _raise(skill, "INCREMENTAL_EMERGENCY_GROUP_INVALID")

    # Validate the actual candidate object after all pruning and policy passes.
    validate = getattr(skill, "validate_config", None)
    if validate is not None:
        validate(output)

    group_counts = {
        str(group["name"]): len(group.get("proxies", []))
        for group in output.get("proxy-groups", [])
    }
    report = {
        **plan,
        "admitted_disney_names": list(accepted_disney),
        "admitted_gpt_names": list(admitted_gpt),
        "admitted_gemini_names": list(admitted_gemini),
        "admitted_ai_names": {
            "gpt": list(admitted_gpt),
            "gemini": list(admitted_gemini),
        },
        "registry_reused_names": {
            "gpt": [
                name
                for name in current_order
                if name in set(registry_gpt_names)
                and name in set(
                    final_groups["GPT候选"].get("proxies", [])
                )
            ],
            "gemini": [
                name
                for name in current_order
                if name in set(registry_gemini_names)
                and name in set(
                    final_groups["Gemini候选"].get("proxies", [])
                )
            ],
        },
        "ai_new_names_admitted": {
            "gpt": list(admitted_gpt),
            "gemini": list(admitted_gemini),
        },
        "measured_hk_names": [
            name for name in measured_hk_ordered if name in old_names
        ],
        "manual_region_blocked_names": {
            service: list(names) for service, names in blocked_ordered.items()
        },
        "old_service_tests": 0,
        "admission_explanations": {
            "same_name": "NAME_REUSED_NOT_RETESTED is carried historical policy, not fresh actual-use proof.",
            "parameter_changed": "PARAMETERS_CHANGED_NOT_RETESTED replaces the complete proxy object without service retest.",
            "added": "ADDED_PENDING_VERIFICATION is never promoted to GPT/Gemini from screening; only explicit actual-use proof can admit it.",
            "disney": "Only full PASS_SUPPORTED_REGION results supplied by the controller enter Disney.",
            "hong_kong": "Labels and exact-identity measured HK exclusions are policy filters, not exit-IP proof.",
        },
        "group_counts": group_counts,
    }
    return output, report


__all__ = [
    "ConfigError",
    "IncrementalUpdateError",
    "build_candidate",
    "eligible_ai_rrc_names",
    "plan_nodes",
]
