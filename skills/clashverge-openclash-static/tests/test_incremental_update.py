from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "incremental_update.py"
spec = importlib.util.spec_from_file_location("incremental_update", SCRIPT)
incremental = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["incremental_update"] = incremental
spec.loader.exec_module(incremental)


class FakeSkill:
    ConfigError = ValueError
    BUILTIN_TARGETS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE"}

    def __init__(self) -> None:
        self.restrict_calls = 0
        self.validation_calls = 0

    def static_proxy_objects(self, data):
        proxies = data.get("proxies")
        if not isinstance(proxies, list) or not proxies:
            raise self.ConfigError("empty proxies")
        names = []
        for proxy in proxies:
            if not isinstance(proxy, dict) or not isinstance(proxy.get("name"), str):
                raise self.ConfigError("invalid proxy")
            names.append(proxy["name"])
        if len(set(names)) != len(names):
            raise self.ConfigError("duplicate proxy names")
        return proxies

    @staticmethod
    def rule_target(rule):
        parts = [part.strip() for part in rule.split(",")]
        if parts and parts[0].upper() == "MATCH":
            return parts[1] if len(parts) > 1 else None
        return parts[-1] if len(parts) > 1 else None

    def restrict_ai_group_members(self, data):
        # The production helper is intentionally called, while the pure module
        # still enforces label filtering if a caller supplies a no-op policy hook.
        self.restrict_calls += 1

    @staticmethod
    def is_disney_region_name(name):
        return name in {"us", "new"}

    def validate_config(self, data):
        self.validation_calls += 1
        proxies = {proxy["name"] for proxy in data["proxies"]}
        groups = {group["name"] for group in data["proxy-groups"]}
        for group in data["proxy-groups"]:
            for ref in group["proxies"]:
                assert ref in proxies or ref in groups or ref in self.BUILTIN_TARGETS


def _groups(*, include_history: bool = True):
    groups = [
        {"name": "默认代理", "type": "select", "proxies": ["手动选择", "自动选择"]},
        {"name": "手动选择", "type": "select", "proxies": ["自动选择", "jp", "gone"]},
        {"name": "自动选择", "type": "fallback", "url": "https://health.invalid", "proxies": ["jp", "gone"]},
        {"name": "GPT专用", "type": "select", "proxies": ["GPT手动", "GPT候选"]},
        {"name": "GPT手动", "type": "select", "proxies": ["🇭🇰香港旧", "us", "stale-tail", "GPT候选"]},
        {"name": "GPT候选", "type": "fallback", "proxies": ["🇭🇰香港旧", "us"]},
        {"name": "Gemini专用", "type": "select", "proxies": ["Gemini手动", "Gemini候选"]},
        {"name": "Gemini手动", "type": "select", "proxies": ["🇭🇰香港旧", "us", "stale-tail", "Gemini候选"]},
        {"name": "Gemini候选", "type": "fallback", "proxies": ["🇭🇰香港旧", "us"]},
        {"name": "迪士尼", "type": "select", "proxies": ["迪士尼手动", "迪士尼候选"]},
        {"name": "迪士尼手动", "type": "select", "proxies": ["迪士尼候选", "us", "gone"]},
        {"name": "迪士尼候选", "type": "fallback", "proxies": ["us", "gone"]},
        {"name": "普通空组", "type": "select", "proxies": ["gone"]},
        {"name": "迪士尼历史LKG", "type": "fallback", "proxies": ["us"]},
    ]
    if include_history:
        groups.insert(5, {"name": "GPT历史LKG", "type": "fallback", "proxies": ["us"]})
        groups.insert(10, {"name": "Gemini历史LKG", "type": "fallback", "proxies": ["us"]})
        groups[2]["proxies"].append("GPT历史LKG")
    return groups


def _config(*, new: bool = False):
    proxies = [
        {"name": "jp", "type": "ss", "server": "jp.example", "port": 1},
        {"name": "🇭🇰香港旧", "type": "ss", "server": "hk.example", "port": 2},
        {"name": "us", "type": "ss", "server": "us-new.example" if new else "us.example", "port": 3},
        {"name": "gone", "type": "ss", "server": "gone.example", "port": 4},
    ]
    if new:
        proxies = [
            proxy for proxy in proxies if proxy["name"] != "gone"
        ] + [{"name": "new", "type": "ss", "server": "new.example", "port": 5}]
    return {
        "mode": "rule",
        "dns": {"enable": True, "nameserver": ["9.9.9.9"]},
        "proxies": proxies,
        "proxy-groups": _groups(),
        "rules": [
            "DOMAIN-SUFFIX,example.invalid,默认代理",
            "DOMAIN,removed.invalid,gone",
            "MATCH,默认代理",
        ],
    }


def test_plan_nodes_uses_exact_strings_and_separates_parameter_changes():
    skill = FakeSkill()
    old = {"proxies": [{"name": "Node", "server": "a"}, {"name": "gone"}]}
    new = {"proxies": [{"name": "Node", "server": "b"}, {"name": " node "}]}

    plan = incremental.plan_nodes(old, new, skill)

    assert plan["added_names"] == [" node "]
    assert plan["removed_names"] == ["gone"]
    assert plan["reused_names"] == ["Node"]
    assert plan["parameter_changed_names"] == ["Node"]
    assert plan["name_status"] == {
        "Node": "PARAMETERS_CHANGED_NOT_RETESTED",
        "gone": "REMOVED",
        " node ": "ADDED_PENDING_VERIFICATION",
    }
    assert plan["old_service_tests"] == 0


def test_build_candidate_replaces_objects_prunes_and_admits_only_disney_pass():
    skill = FakeSkill()
    old = _config()
    new = _config(new=True)

    candidate, report = incremental.build_candidate(
        old,
        new,
        skill,
        disney_pass_names=["new", "gone"],
    )

    assert candidate["proxies"] == new["proxies"]
    assert candidate["dns"] == old["dns"]
    groups = {group["name"]: group for group in candidate["proxy-groups"]}
    assert groups["默认代理"]["proxies"][0] == "自动选择"
    assert groups["手动选择"]["proxies"][-1] == "new"
    assert groups["自动选择"]["proxies"][-1] == "new"
    assert "gone" not in str(candidate)
    assert "普通空组" not in groups
    assert "GPT历史LKG" not in groups
    assert "Gemini历史LKG" not in groups
    assert "迪士尼历史LKG" in groups
    assert groups["GPT候选"]["proxies"] == ["us"]
    assert groups["Gemini候选"]["proxies"] == ["🇭🇰香港旧", "us"]
    current_names = [proxy["name"] for proxy in new["proxies"]]
    gpt_manual_names = [
        name for name in current_names if not incremental._is_hong_kong_label(name)
    ]
    assert groups["GPT手动"]["proxies"] == [
        *dict.fromkeys([*groups["GPT候选"]["proxies"], *gpt_manual_names]),
        "GPT候选",
    ]
    assert groups["Gemini手动"]["proxies"] == [
        *dict.fromkeys([*groups["Gemini候选"]["proxies"], *current_names]),
        "Gemini候选",
    ]
    assert groups["GPT专用"]["proxies"] == [
        "GPT手动", "GPT候选", "AI应急（未验证）"
    ]
    assert groups["Gemini专用"]["proxies"] == [
        "Gemini手动", "Gemini候选", "AI应急（未验证）"
    ]
    assert groups["AI应急（未验证）"]["proxies"] == [
        "jp", "🇭🇰香港旧", "us", "new"
    ]
    assert list(candidate["proxy-groups"])[-1]["name"] == "AI应急（未验证）"
    assert "AI应急（未验证）" not in groups["手动选择"]["proxies"]
    assert "AI应急（未验证）" not in groups["自动选择"]["proxies"]
    assert groups["迪士尼候选"]["proxies"] == ["us", "new"]
    assert groups["迪士尼手动"]["proxies"] == [
        "us", "new", "jp", "🇭🇰香港旧", "迪士尼候选"
    ]
    assert report["parameter_changed_names"] == ["us"]
    assert report["admitted_disney_names"] == ["new"]
    assert report["expected_carried_names"] == {
        "gpt": ["us"],
        "gemini": ["🇭🇰香港旧", "us"],
    }
    assert report["missing_carried_names"] == {
        "gpt": [],
        "gemini": [],
    }
    assert report["old_service_tests"] == 0
    assert skill.restrict_calls == 1
    assert skill.validation_calls == 1


def test_carried_candidates_survive_same_name_change_when_registry_misses():
    skill = FakeSkill()
    old = _config()
    new = _config(new=True)

    candidate, report = incremental.build_candidate(
        old,
        new,
        skill,
        disney_pass_names=["new"],
        registry_gpt_names=["registry-miss"],
        registry_gemini_names=["registry-miss"],
    )

    groups = {group["name"]: group for group in candidate["proxy-groups"]}
    assert groups["GPT候选"]["proxies"] == ["us"]
    assert groups["Gemini候选"]["proxies"] == ["🇭🇰香港旧", "us"]
    assert report["registry_reused_names"] == {
        "gpt": [],
        "gemini": [],
    }
    assert report["missing_carried_names"] == {
        "gpt": [],
        "gemini": [],
    }


def test_build_candidate_admits_snapshot_bound_ai_names_by_service_and_source_order():
    skill = FakeSkill()
    old = _config()
    new = _config(new=True)
    new["proxies"].extend(
        [
            {"name": "gpt-new", "type": "ss", "server": "gpt.example", "port": 6},
            {"name": "gemini-new", "type": "ss", "server": "gemini.example", "port": 7},
            {"name": "🇭🇰香港新增", "type": "ss", "server": "hk-new.example", "port": 8},
            {"name": "流媒体新增", "type": "ss", "server": "stream.example", "port": 9},
            {"name": "媒体流新增", "type": "ss", "server": "media.example", "port": 10},
        ]
    )

    candidate, report = incremental.build_candidate(
        old,
        new,
        skill,
        disney_pass_names=["new"],
        verified_gpt_names=[
            "媒体流新增",
            "流媒体新增",
            "🇭🇰香港新增",
            "gpt-new",
        ],
        verified_gemini_names=["gemini-new"],
    )

    groups = {group["name"]: group for group in candidate["proxy-groups"]}
    assert groups["GPT候选"]["proxies"] == ["us", "gpt-new", "媒体流新增"]
    current_names = [proxy["name"] for proxy in new["proxies"]]
    gpt_manual_names = [
        name for name in current_names if not incremental._is_hong_kong_label(name)
    ]
    assert groups["GPT手动"]["proxies"] == [
        *dict.fromkeys([*groups["GPT候选"]["proxies"], *gpt_manual_names]),
        "GPT候选",
    ]
    assert groups["Gemini候选"]["proxies"] == ["🇭🇰香港旧", "us", "gemini-new"]
    assert groups["Gemini手动"]["proxies"] == [
        *dict.fromkeys([*groups["Gemini候选"]["proxies"], *current_names]),
        "Gemini候选",
    ]
    assert report["admitted_gpt_names"] == ["gpt-new", "媒体流新增"]
    assert report["admitted_gemini_names"] == ["gemini-new"]


def test_build_candidate_reuses_registry_preferred_names_and_combines_fresh_results_in_source_order():
    skill = FakeSkill()
    old = _config()
    new = _config(new=True)
    new["proxies"][0]["name"] = "registry-renamed"
    new["proxies"].extend(
        [{"name": "fresh-gpt", "type": "ss", "server": "fresh.example", "port": 6}]
    )

    candidate, report = incremental.build_candidate(
        old,
        new,
        skill,
        disney_pass_names=["new"],
        registry_gpt_names=["registry-renamed", "removed", "same-name"],
        verified_gpt_names=["fresh-gpt"],
    )

    groups = {group["name"]: group for group in candidate["proxy-groups"]}
    assert groups["GPT候选"]["proxies"] == [
        "us",
        "registry-renamed",
        "fresh-gpt",
    ]
    assert report["registry_reused_names"] == {
        "gpt": ["registry-renamed"],
        "gemini": [],
    }


def test_hong_kong_registry_reuse_is_gpt_only_but_gemini_candidate_visible():
    skill = FakeSkill()
    old = _config()
    new = _config(new=True)
    new["proxies"].append(
        {
            "name": "🇭🇰香港验证",
            "type": "ss",
            "server": "hk-verified.example",
            "port": 6,
        }
    )

    candidate, _ = incremental.build_candidate(
        old,
        new,
        skill,
        disney_pass_names=["new"],
        registry_gpt_names=["🇭🇰香港验证"],
        registry_gemini_names=["🇭🇰香港验证"],
    )

    groups = {group["name"]: group for group in candidate["proxy-groups"]}
    assert "🇭🇰香港验证" not in groups["GPT候选"]["proxies"]
    assert "🇭🇰香港验证" not in groups["GPT手动"]["proxies"]
    assert "🇭🇰香港验证" in groups["Gemini候选"]["proxies"]
    assert "🇭🇰香港验证" in groups["Gemini手动"]["proxies"]


def test_emergency_regenerates_idempotently_and_keeps_new_hk_unknown_nodes_out_of_ai_pool():
    skill = FakeSkill()
    old = _config()
    new = _config(new=True)
    new["proxies"].extend(
        [
            {"name": "🇭🇰新增", "type": "ss", "server": "hk-new.example", "port": 6},
            {"name": "未知新增", "type": "ss", "server": "unknown.example", "port": 7},
        ]
    )
    old["proxy-groups"].append(
        {
            "name": "AI应急（未验证）",
            "type": "select",
            "proxies": ["jp", "gone", "stale-node"],
        }
    )

    candidate, _ = incremental.build_candidate(
        old, new, skill, disney_pass_names=["new"]
    )
    groups = {group["name"]: group for group in candidate["proxy-groups"]}
    assert groups["AI应急（未验证）"]["proxies"] == [
        "jp", "🇭🇰香港旧", "us", "new", "🇭🇰新增", "未知新增"
    ]
    assert "gone" not in groups["AI应急（未验证）"]["proxies"]
    assert "stale-node" not in groups["AI应急（未验证）"]["proxies"]
    assert groups["GPT候选"]["proxies"] == ["us"]
    assert groups["Gemini候选"]["proxies"] == ["🇭🇰香港旧", "us"]
    assert "🇭🇰新增" not in groups["GPT手动"]["proxies"]
    assert "🇭🇰新增" in groups["Gemini手动"]["proxies"]
    assert "未知新增" in groups["Gemini手动"]["proxies"]
    assert groups["手动选择"]["proxies"][-2:] == ["🇭🇰新增", "未知新增"]
    assert groups["自动选择"]["proxies"][-2:] == ["🇭🇰新增", "未知新增"]
    assert candidate["proxy-groups"][-1]["name"] == "AI应急（未验证）"

    repeated, _ = incremental.build_candidate(
        candidate, new, skill, disney_pass_names=["new"]
    )
    assert repeated["proxy-groups"] == candidate["proxy-groups"]


def test_measured_hk_exclusion_is_exact_and_empty_ai_pool_blocks():
    skill = FakeSkill()
    old = _config()
    new = _config(new=True)
    new["proxy-groups"][5]["proxies"] = ["us"]
    new["proxy-groups"][8]["proxies"] = ["us"]

    with pytest.raises(ValueError, match="BLOCKED_NO_CURRENT_SERVICE_CANDIDATES:GPT"):
        incremental.build_candidate(
            old,
            new,
            skill,
            measured_hk_names=["us"],
            disney_pass_names=["new"],
        )


def test_unknown_non_ai_reference_fails_closed():
    skill = FakeSkill()
    old = _config()
    old["proxy-groups"][2]["proxies"].append("unknown-tail")
    with pytest.raises(ValueError, match="INCREMENTAL_UNKNOWN_REFERENCE"):
        incremental.build_candidate(old, _config(new=True), skill, disney_pass_names=["new"])


def test_optional_groups_are_pruned_recursively_after_deleted_references():
    skill = FakeSkill()
    old = _config()
    old["proxy-groups"].extend(
        [
            {"name": "optional-wrapper", "type": "select", "proxies": ["optional-empty"]},
            {"name": "optional-empty", "type": "select", "proxies": ["gone"]},
        ]
    )

    candidate, _ = incremental.build_candidate(
        old, _config(new=True), skill, disney_pass_names=["new"]
    )

    names = {group["name"] for group in candidate["proxy-groups"]}
    assert "optional-wrapper" not in names
    assert "optional-empty" not in names


def test_local_ai_invariant_rejects_hong_kong_injected_by_policy_hook():
    class MutatingSkill(FakeSkill):
        def restrict_ai_group_members(self, data):
            super().restrict_ai_group_members(data)
            groups = {group["name"]: group for group in data["proxy-groups"]}
            groups["GPT候选"]["proxies"] = ["🇭🇰香港旧", "us"]

    with pytest.raises(ValueError, match="INCREMENTAL_AI_CANDIDATE_GROUP_INVALID:GPT"):
        incremental.build_candidate(
            _config(), _config(new=True), MutatingSkill(), disney_pass_names=["new"]
        )


def test_carried_gemini_name_removed_by_policy_hook_fails_closed():
    class MutatingSkill(FakeSkill):
        def restrict_ai_group_members(self, data):
            super().restrict_ai_group_members(data)
            groups = {group["name"]: group for group in data["proxy-groups"]}
            groups["Gemini候选"]["proxies"].remove("us")

    with pytest.raises(
        ValueError,
        match=r"INCREMENTAL_CARRIED_CANDIDATE_MISSING:GEMINI:us",
    ):
        incremental.build_candidate(
            _config(), _config(new=True), MutatingSkill(), disney_pass_names=["new"]
        )


def test_manual_ai_groups_keep_all_current_nodes_without_definitive_region_blocks():
    skill = FakeSkill()
    old = _config()
    new = _config(new=True)
    new["proxies"].append(
        {
            "name": "流媒体新增",
            "type": "ss",
            "server": "stream.example",
            "port": 6,
        }
    )

    candidate, _ = incremental.build_candidate(
        old,
        new,
        skill,
        disney_pass_names=["new"],
    )

    groups = {group["name"]: group for group in candidate["proxy-groups"]}
    current_names = [proxy["name"] for proxy in new["proxies"]]
    assert groups["GPT候选"]["proxies"] == ["us"]
    assert groups["Gemini候选"]["proxies"] == ["🇭🇰香港旧", "us"]
    gpt_manual_names = [
        name for name in current_names if not incremental._is_hong_kong_label(name)
    ]
    assert groups["GPT手动"]["proxies"] == [
        *dict.fromkeys([*groups["GPT候选"]["proxies"], *gpt_manual_names]),
        "GPT候选",
    ]
    assert groups["Gemini手动"]["proxies"] == [
        *dict.fromkeys([*groups["Gemini候选"]["proxies"], *current_names]),
        "Gemini候选",
    ]


def test_service_specific_manual_region_block_removes_only_that_service_node():
    skill = FakeSkill()
    old = _config()
    new = _config(new=True)

    candidate, report = incremental.build_candidate(
        old,
        new,
        skill,
        disney_pass_names=["new"],
        verified_gemini_names=["new"],
        blocked_gemini_names=["new"],
    )

    groups = {group["name"]: group for group in candidate["proxy-groups"]}
    current_names = [proxy["name"] for proxy in new["proxies"]]
    assert groups["Gemini候选"]["proxies"] == ["🇭🇰香港旧", "us"]
    gemini_allowed = [name for name in current_names if name != "new"]
    assert groups["Gemini手动"]["proxies"] == [
        *dict.fromkeys([*groups["Gemini候选"]["proxies"], *gemini_allowed]),
        "Gemini候选",
    ]
    assert groups["GPT候选"]["proxies"] == ["us"]
    gpt_manual_names = [
        name for name in current_names if not incremental._is_hong_kong_label(name)
    ]
    assert groups["GPT手动"]["proxies"] == [
        *dict.fromkeys([*groups["GPT候选"]["proxies"], *gpt_manual_names]),
        "GPT候选",
    ]
    assert report["manual_region_blocked_names"] == {
        "gpt": [],
        "gemini": ["new"],
    }


def test_blocked_carried_gemini_name_is_excluded_from_continuity_expectation():
    skill = FakeSkill()
    candidate, report = incremental.build_candidate(
        _config(),
        _config(new=True),
        skill,
        disney_pass_names=["new"],
        blocked_gemini_names=["us"],
    )

    groups = {group["name"]: group for group in candidate["proxy-groups"]}
    assert groups["Gemini候选"]["proxies"] == ["🇭🇰香港旧"]
    assert report["expected_carried_names"] == {
        "gpt": ["us"],
        "gemini": ["🇭🇰香港旧"],
    }
    assert report["missing_carried_names"] == {
        "gpt": [],
        "gemini": [],
    }
