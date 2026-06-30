"""Deterministic full-text source handoff integration helper.

This module intentionally does not search for sources, retrieve full text, call
an LLM, verify claims, synthesize final answers, or integrate with the
production Research/Decision runtime. It only validates and renders a structured
handoff manifest between Stage A source registries and Stage B Evidence Packet
v2 packet generation.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REQUIRED_HANDOFF_FIELDS: tuple[str, ...] = (
    "source_id",
    "case_id",
    "registry_path",
    "url_or_local_ref",
    "retrieval_status",
    "full_text_available",
    "full_text_accessed",
    "excerpt_ref_id",
    "excerpt_or_span",
    "excerpt_summary",
    "section_locator",
    "access_date",
    "source_hash_or_locator",
    "allowed_claim_categories",
    "prohibited_claim_categories",
    "full_text_verified_allowed",
    "high_risk_allowed",
    "caveats",
    "handoff_ready",
)

READY_FOR_STAGEB_PACKET_INPUT = "READY_FOR_STAGEB_PACKET_INPUT"
READY_WITH_LIMITATIONS = "READY_WITH_LIMITATIONS"
HOLD_FOR_SOURCE_HANDOFF = "HOLD_FOR_SOURCE_HANDOFF"
BLOCKED = "BLOCKED"

FULLTEXT_COMPATIBLE_RETRIEVAL_STATUSES: set[str] = {
    "source_accessible",
    "full_text_accessed",
    "doc_only_matched",
}
SNIPPET_OR_METADATA_STATUSES: set[str] = {
    "snippet",
    "snippet_only",
    "search_result",
    "search_result_snippet",
    "metadata_only",
}
HIGH_AUTHORITY_TIERS: set[str] = {
    "primary",
    "regulatory",
    "official",
    "peer_reviewed",
    "high_authority",
}
PRIMARY_OR_REGULATORY_TIERS: set[str] = {"primary", "regulatory"}
VENDOR_BLOG_CONSULTING_TIERS: set[str] = {"vendor", "blog", "consulting"}
VENDOR_BLOG_CONSULTING_MARKERS: tuple[str, ...] = (
    "vendor",
    "blog",
    "consulting",
    "practitioner",
    "marketing",
)
NONE_VALUES: set[str] = {"", "none", "n/a", "na", "unknown", "no", "no bias"}
MAX_EXCERPT_CHARS = 1200


@dataclass(frozen=True)
class HandoffValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]
    source_count: int
    handoff_ready_count: int
    full_text_verified_allowed_count: int
    high_risk_allowed_count: int
    missing_excerpt_ref_count: int
    snippet_block_count: int
    bias_caveat_required_count: int
    readiness: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_json(path: str | Path) -> dict[str, Any] | list[Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, (dict, list)):
        raise ValueError("JSON payload must be an object or list.")
    return payload


def build_source_handoff_manifest(stageA_case_dir: str | Path) -> dict[str, Any]:
    case_dir = Path(stageA_case_dir)
    registry_path = case_dir / "source_registry.json"
    if not registry_path.exists():
        raise FileNotFoundError(f"missing source_registry.json in {case_dir}")
    registry = load_json(registry_path)
    entries = _registry_entries(registry)
    if entries is None:
        raise ValueError("source_registry.json must be a list or object containing source_registry/sources/accepted_sources/entries")

    workflow_review_path = case_dir / "source_registry_workflow_review.json"
    workflow_review: dict[str, Any] | None = None
    if workflow_review_path.exists():
        loaded_review = load_json(workflow_review_path)
        if isinstance(loaded_review, dict):
            workflow_review = loaded_review

    items: list[dict[str, Any]] = []
    registry_source_ids: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_id = _as_text(entry.get("source_id"))
        if source_id:
            registry_source_ids.append(source_id)
        retrieval_status = _as_text(entry.get("retrieval_status"))
        full_text_available = entry.get("full_text_available") is True
        full_text_accessed = entry.get("full_text_accessed") is True
        excerpt_or_span = _as_text(entry.get("captured_excerpt_or_span"))
        source_ref = _as_text(entry.get("full_text_hash_or_excerpt_ref"))
        section_locator = source_ref if source_ref else ""
        source_type = _as_text(entry.get("source_type"))
        authority_tier = _as_text(entry.get("authority_tier"))
        authority_category = _authority_category(authority_tier, source_type)
        allowed_categories = _as_text_list(entry.get("usable_for_claim_categories"))
        prohibited_categories = _as_text_list(entry.get("not_usable_for"))
        caveats = _build_caveats(entry)
        full_text_verified_allowed = _full_text_allowed_from_registry(
            retrieval_status=retrieval_status,
            full_text_available=full_text_available,
            full_text_accessed=full_text_accessed,
            excerpt_or_span=excerpt_or_span,
            section_locator=section_locator,
            source_ref=source_ref,
        )
        high_risk_allowed = (
            authority_category in HIGH_AUTHORITY_TIERS
            and not _is_vendor_blog_consulting(source_type, authority_category)
            and (full_text_verified_allowed or bool(section_locator))
        )
        handoff_ready = bool(
            source_id
            and _as_text(entry.get("url_or_local_ref"))
            and _as_text(entry.get("access_date"))
            and allowed_categories
            and caveats
        )
        items.append(
            {
                "source_id": source_id,
                "case_id": _as_text(entry.get("case_id")),
                "registry_path": str(registry_path),
                "url_or_local_ref": _as_text(entry.get("url_or_local_ref")),
                "retrieval_status": retrieval_status,
                "full_text_available": full_text_available,
                "full_text_accessed": full_text_accessed,
                "excerpt_ref_id": source_ref,
                "excerpt_or_span": excerpt_or_span,
                "excerpt_summary": _as_text(entry.get("captured_excerpt_summary")),
                "section_locator": section_locator,
                "access_date": _as_text(entry.get("access_date")),
                "source_hash_or_locator": source_ref,
                "allowed_claim_categories": allowed_categories,
                "prohibited_claim_categories": prohibited_categories,
                "full_text_verified_allowed": full_text_verified_allowed,
                "high_risk_allowed": high_risk_allowed,
                "caveats": caveats,
                "handoff_ready": handoff_ready,
                "source_type": source_type,
                "authority_tier": authority_tier,
                "authority_category": authority_category,
                "potential_bias": _as_text(entry.get("potential_bias")),
                "source_limitations": _as_text(entry.get("source_limitations")),
                "next_stage_verification_notes": _as_text(entry.get("next_stage_verification_notes")),
            }
        )

    manifest = {
        "metadata": {
            "stage": "fulltext_source_handoff",
            "stageA_case_dir": str(case_dir),
            "source_registry_path": str(registry_path),
            "source_registry_workflow_review_path": str(workflow_review_path) if workflow_review_path.exists() else "",
            "network_used_in_this_helper": False,
            "llm_used_in_this_helper": False,
            "source_acquisition_used_in_this_helper": False,
        },
        "registry_source_ids": registry_source_ids,
        "workflow_review_readiness": _extract_workflow_readiness(workflow_review),
        "handoff_items": items,
    }
    validation = validate_fulltext_handoff_manifest(manifest)
    manifest["validation_summary"] = validation.to_dict()
    return manifest


def validate_fulltext_handoff_manifest(manifest: dict[str, Any]) -> HandoffValidationResult:
    manifest_copy = copy.deepcopy(manifest)
    items = _manifest_items(manifest_copy)
    errors: list[str] = []
    warnings: list[str] = []
    if items is None:
        return HandoffValidationResult(
            ok=False,
            errors=["manifest:expected_object_with_handoff_items"],
            warnings=[],
            source_count=0,
            handoff_ready_count=0,
            full_text_verified_allowed_count=0,
            high_risk_allowed_count=0,
            missing_excerpt_ref_count=0,
            snippet_block_count=0,
            bias_caveat_required_count=0,
            readiness=BLOCKED,
        )

    registry_source_ids = set(_as_text_list(manifest_copy.get("registry_source_ids")))
    seen_source_ids: set[str] = set()
    source_count = len(items)
    handoff_ready_count = 0
    full_text_verified_allowed_count = 0
    high_risk_allowed_count = 0
    missing_excerpt_ref_count = 0
    snippet_block_count = 0
    bias_caveat_required_count = 0

    for idx, item in enumerate(items):
        path = f"handoff_items[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{path}:not_object")
            continue

        for field in REQUIRED_HANDOFF_FIELDS:
            if field not in item:
                errors.append(f"{path}:missing_field:{field}")

        source_id = _as_text(item.get("source_id"))
        if source_id:
            if source_id in seen_source_ids:
                errors.append(f"{path}:duplicate_source_id:{source_id}")
            seen_source_ids.add(source_id)
            if registry_source_ids and source_id not in registry_source_ids:
                errors.append(f"{path}:source_absent_from_registry:{source_id}")

        retrieval_status = _as_text(item.get("retrieval_status"))
        source_type = _as_text(item.get("source_type"))
        authority_category = _authority_category(_as_text(item.get("authority_tier") or item.get("authority_category")), source_type)
        full_text_available = item.get("full_text_available") is True
        full_text_accessed = item.get("full_text_accessed") is True
        full_text_verified_allowed = item.get("full_text_verified_allowed") is True
        high_risk_allowed = item.get("high_risk_allowed") is True
        handoff_ready = item.get("handoff_ready") is True
        excerpt_ref_id = _as_text(item.get("excerpt_ref_id"))
        excerpt_or_span = _as_text(item.get("excerpt_or_span"))
        excerpt_summary = _as_text(item.get("excerpt_summary"))
        section_locator = _as_text(item.get("section_locator"))
        source_hash_or_locator = _as_text(item.get("source_hash_or_locator"))
        allowed_categories = _as_text_list(item.get("allowed_claim_categories"))
        prohibited_categories = _as_text_list(item.get("prohibited_claim_categories"))
        caveats = _as_text_list(item.get("caveats"))

        if handoff_ready:
            handoff_ready_count += 1
        if full_text_verified_allowed:
            full_text_verified_allowed_count += 1
        if high_risk_allowed:
            high_risk_allowed_count += 1
        if not excerpt_ref_id:
            missing_excerpt_ref_count += 1
        if _is_snippet_or_metadata_status(retrieval_status):
            snippet_block_count += 1
        if _is_vendor_blog_consulting(source_type, authority_category):
            bias_caveat_required_count += 1

        if "full_text_available" in item and not isinstance(item.get("full_text_available"), bool):
            errors.append(f"{path}.full_text_available:expected_bool")
        if "full_text_accessed" in item and not isinstance(item.get("full_text_accessed"), bool):
            errors.append(f"{path}.full_text_accessed:expected_bool")
        if "full_text_verified_allowed" in item and not isinstance(item.get("full_text_verified_allowed"), bool):
            errors.append(f"{path}.full_text_verified_allowed:expected_bool")
        if "high_risk_allowed" in item and not isinstance(item.get("high_risk_allowed"), bool):
            errors.append(f"{path}.high_risk_allowed:expected_bool")
        if "handoff_ready" in item and not isinstance(item.get("handoff_ready"), bool):
            errors.append(f"{path}.handoff_ready:expected_bool")

        if full_text_verified_allowed:
            errors.extend(
                _full_text_verified_allowed_errors(
                    path=path,
                    retrieval_status=retrieval_status,
                    full_text_available=full_text_available,
                    full_text_accessed=full_text_accessed,
                    excerpt_or_span=excerpt_or_span,
                    section_locator=section_locator,
                    source_hash_or_locator=source_hash_or_locator,
                    excerpt_ref_id=excerpt_ref_id,
                    excerpt_summary=excerpt_summary,
                )
            )

        if handoff_ready:
            for field in ("source_id", "url_or_local_ref", "access_date"):
                if _is_empty(item.get(field)):
                    errors.append(f"{path}:handoff_ready_requires:{field}")
            if not allowed_categories:
                errors.append(f"{path}:handoff_ready_requires_allowed_claim_categories")
            if not caveats:
                errors.append(f"{path}:handoff_ready_requires_caveats")

        if _is_snippet_or_metadata_status(retrieval_status):
            if full_text_verified_allowed:
                errors.append(f"{path}:snippet_or_metadata_cannot_full_text_verified_allowed")
            if high_risk_allowed:
                errors.append(f"{path}:snippet_or_metadata_cannot_high_risk_allowed")

        if high_risk_allowed:
            if authority_category not in HIGH_AUTHORITY_TIERS:
                errors.append(f"{path}:high_risk_allowed_requires_authoritative_tier:{authority_category}")
            if not full_text_verified_allowed and not section_locator:
                errors.append(f"{path}:high_risk_allowed_requires_full_text_or_authoritative_locator")
            if authority_category not in PRIMARY_OR_REGULATORY_TIERS and not caveats:
                errors.append(f"{path}:high_risk_allowed_requires_applicability_caveat")

        if _is_vendor_blog_consulting(source_type, authority_category):
            if not caveats or _all_none_like(caveats):
                errors.append(f"{path}:vendor_blog_consulting_requires_bias_caveat")
            if high_risk_allowed:
                errors.append(f"{path}:vendor_blog_consulting_cannot_high_risk_allowed")

        if not excerpt_ref_id:
            if full_text_verified_allowed:
                errors.append(f"{path}:full_text_verified_allowed_requires_excerpt_ref_id")
            elif handoff_ready:
                warnings.append(f"{path}:handoff_ready_missing_excerpt_ref_id")

        if not prohibited_categories:
            warnings.append(f"{path}:prohibited_claim_categories_should_be_explicit")
        if len(excerpt_or_span) > MAX_EXCERPT_CHARS:
            warnings.append(f"{path}:excerpt_or_span_exceeds_{MAX_EXCERPT_CHARS}_chars")

    readiness = _readiness(
        errors=errors,
        warnings=warnings,
        source_count=source_count,
        handoff_ready_count=handoff_ready_count,
    )
    return HandoffValidationResult(
        ok=not errors,
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
        source_count=source_count,
        handoff_ready_count=handoff_ready_count,
        full_text_verified_allowed_count=full_text_verified_allowed_count,
        high_risk_allowed_count=high_risk_allowed_count,
        missing_excerpt_ref_count=missing_excerpt_ref_count,
        snippet_block_count=snippet_block_count,
        bias_caveat_required_count=bias_caveat_required_count,
        readiness=readiness,
    )


def verify_excerpt_refs_exist(registry: dict[str, Any] | list[Any], manifest: dict[str, Any]) -> HandoffValidationResult:
    registry_copy = copy.deepcopy(registry)
    manifest_copy = copy.deepcopy(manifest)
    entries = _registry_entries(registry_copy)
    validation = validate_fulltext_handoff_manifest(manifest_copy)
    errors = list(validation.errors)
    warnings = list(validation.warnings)
    if entries is None:
        errors.append("registry:expected_list_or_object_with_source_registry")
    else:
        registry_by_id = {str(entry.get("source_id")): entry for entry in entries if isinstance(entry, dict) and entry.get("source_id")}
        for idx, item in enumerate(_manifest_items(manifest_copy) or []):
            if not isinstance(item, dict):
                continue
            path = f"handoff_items[{idx}]"
            source_id = _as_text(item.get("source_id"))
            source = registry_by_id.get(source_id)
            if source is None:
                errors.append(f"{path}:source_absent_from_registry:{source_id}")
                continue
            if item.get("full_text_verified_allowed") is True:
                registry_excerpt = _as_text(source.get("captured_excerpt_or_span"))
                registry_ref = _as_text(source.get("full_text_hash_or_excerpt_ref"))
                if not registry_excerpt and not registry_ref:
                    errors.append(f"{path}:registry_missing_excerpt_or_ref_for_full_text_verified_allowed:{source_id}")
    readiness = _readiness(
        errors=errors,
        warnings=warnings,
        source_count=validation.source_count,
        handoff_ready_count=validation.handoff_ready_count,
    )
    return HandoffValidationResult(
        ok=not errors,
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
        source_count=validation.source_count,
        handoff_ready_count=validation.handoff_ready_count,
        full_text_verified_allowed_count=validation.full_text_verified_allowed_count,
        high_risk_allowed_count=validation.high_risk_allowed_count,
        missing_excerpt_ref_count=validation.missing_excerpt_ref_count,
        snippet_block_count=validation.snippet_block_count,
        bias_caveat_required_count=validation.bias_caveat_required_count,
        readiness=readiness,
    )


def link_source_registry_to_evidence_packet_inputs(registry: dict[str, Any] | list[Any], manifest: dict[str, Any]) -> dict[str, Any]:
    registry_copy = copy.deepcopy(registry)
    manifest_copy = copy.deepcopy(manifest)
    entries = _registry_entries(registry_copy)
    if entries is None:
        raise ValueError("registry must be a list or object containing source_registry/sources/accepted_sources/entries")
    registry_ids = {_as_text(entry.get("source_id")) for entry in entries if isinstance(entry, dict)}
    linked: list[dict[str, Any]] = []
    for item in _manifest_items(manifest_copy) or []:
        if not isinstance(item, dict):
            continue
        source_id = _as_text(item.get("source_id"))
        if registry_ids and source_id not in registry_ids:
            continue
        linked.append(
            {
                "source_id": source_id,
                "case_id": _as_text(item.get("case_id")),
                "retrieval_status": _as_text(item.get("retrieval_status")),
                "allowed_claim_categories": _as_text_list(item.get("allowed_claim_categories")),
                "prohibited_claim_categories": _as_text_list(item.get("prohibited_claim_categories")),
                "caveats": _as_text_list(item.get("caveats")),
                "full_text_verified_allowed": item.get("full_text_verified_allowed") is True,
                "high_risk_allowed": item.get("high_risk_allowed") is True,
                "handoff_ready": item.get("handoff_ready") is True,
                "excerpt_ref_id": _as_text(item.get("excerpt_ref_id")),
                "section_locator": _as_text(item.get("section_locator")),
            }
        )
    return {
        "source_handoff_for_packet_v2": linked,
        "blocked_stageb_upgrade_source_ids": [item["source_id"] for item in linked if not item["handoff_ready"]],
        "full_text_verified_disallowed_source_ids": [item["source_id"] for item in linked if not item["full_text_verified_allowed"]],
        "high_risk_disallowed_source_ids": [item["source_id"] for item in linked if not item["high_risk_allowed"]],
        "source_registry_count": len(entries),
        "handoff_count": len(linked),
        "claim_support_levels_set": False,
        "claim_verification_results_set": False,
    }


def render_fulltext_handoff_review(
    manifest: dict[str, Any],
    validation: HandoffValidationResult | None = None,
) -> str:
    validation = validation or validate_fulltext_handoff_manifest(manifest)
    items = _manifest_items(manifest) or []
    lines = [
        "# Full-Text Source Handoff Review",
        "",
        "## Summary",
        "",
        f"- ok: {_bool_text(validation.ok)}",
        f"- readiness: {validation.readiness}",
        f"- source_count: {validation.source_count}",
        "",
        "## Validation Result",
        "",
        f"- errors_count: {len(validation.errors)}",
        f"- warnings_count: {len(validation.warnings)}",
        "",
        "## Counts",
        "",
        f"- handoff_ready_count: {validation.handoff_ready_count}",
        f"- full_text_verified_allowed_count: {validation.full_text_verified_allowed_count}",
        f"- high_risk_allowed_count: {validation.high_risk_allowed_count}",
        f"- missing_excerpt_ref_count: {validation.missing_excerpt_ref_count}",
        f"- snippet_block_count: {validation.snippet_block_count}",
        f"- bias_caveat_required_count: {validation.bias_caveat_required_count}",
        "",
        "## Errors",
        "",
    ]
    lines.extend(_render_list(validation.errors))
    lines.extend(["", "## Warnings", ""])
    lines.extend(_render_list(validation.warnings))
    lines.extend(
        [
            "",
            "## Full-Text Verification Allowance",
            "",
            f"- full_text_verified_allowed_count: {validation.full_text_verified_allowed_count}",
            f"- max_excerpt_chars: {MAX_EXCERPT_CHARS}",
            "",
            "## High-Risk Allowance",
            "",
            f"- high_risk_allowed_count: {validation.high_risk_allowed_count}",
            "",
            "## Snippet / Metadata Blocks",
            "",
            f"- snippet_block_count: {validation.snippet_block_count}",
            "",
            "## Bias Caveat Carry-Forward",
            "",
            f"- bias_caveat_required_count: {validation.bias_caveat_required_count}",
            "",
            "## Source-Level Handoff Notes",
            "",
        ]
    )
    if not items:
        lines.append("- none")
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            lines.append(f"### handoff_item_{idx}")
            lines.append("")
            lines.append(f"- value: {_format_value(item)}")
            lines.append("")
            continue
        source_id = _as_text(item.get("source_id")) or f"source_{idx}"
        lines.append(f"### {source_id}")
        lines.append("")
        lines.append(f"- case_id: {_as_text(item.get('case_id'))}")
        lines.append(f"- retrieval_status: {_as_text(item.get('retrieval_status'))}")
        lines.append(f"- authority_tier: {_as_text(item.get('authority_tier'))}")
        lines.append(f"- authority_category: {_authority_category(_as_text(item.get('authority_tier') or item.get('authority_category')), _as_text(item.get('source_type')))}")
        lines.append(f"- handoff_ready: {_bool_text(item.get('handoff_ready') is True)}")
        lines.append(f"- full_text_verified_allowed: {_bool_text(item.get('full_text_verified_allowed') is True)}")
        lines.append(f"- high_risk_allowed: {_bool_text(item.get('high_risk_allowed') is True)}")
        lines.append(f"- allowed_claim_categories: {_format_value(_as_text_list(item.get('allowed_claim_categories')))}")
        lines.append(f"- prohibited_claim_categories: {_format_value(_as_text_list(item.get('prohibited_claim_categories')))}")
        lines.append(f"- caveats: {_format_value(_as_text_list(item.get('caveats')))}")
        lines.append("")
    lines.extend(
        [
            "## Next-Stage Readiness",
            "",
            f"- readiness: {validation.readiness}",
            "- note: This helper validates source handoff only; it does not verify claim correctness or assign support levels.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_handoff_outputs(manifest: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest_copy = copy.deepcopy(manifest)
    validation = validate_fulltext_handoff_manifest(manifest_copy)
    review = render_fulltext_handoff_review(manifest_copy, validation)
    manifest_path = out / "handoff_manifest.json"
    validation_path = out / "handoff_validation.json"
    review_path = out / "handoff_review.md"
    manifest_path.write_text(json.dumps(manifest_copy, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    validation_path.write_text(json.dumps(validation.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    review_path.write_text(review, encoding="utf-8")
    return {
        "manifest_json": str(manifest_path),
        "validation_json": str(validation_path),
        "review_markdown": str(review_path),
        "validation": validation.to_dict(),
    }


def _registry_entries(registry: Any) -> list[Any] | None:
    if isinstance(registry, list):
        return registry
    if not isinstance(registry, dict):
        return None
    if "source_id" in registry:
        return [registry]
    for key in ("source_registry", "sources", "accepted_sources", "entries"):
        value = registry.get(key)
        if isinstance(value, list):
            return value
    return None


def _manifest_items(manifest: Any) -> list[Any] | None:
    if not isinstance(manifest, dict):
        return None
    for key in ("handoff_items", "source_handoff", "sources", "items"):
        value = manifest.get(key)
        if isinstance(value, list):
            return value
    return None


def _full_text_allowed_from_registry(
    *,
    retrieval_status: str,
    full_text_available: bool,
    full_text_accessed: bool,
    excerpt_or_span: str,
    section_locator: str,
    source_ref: str,
) -> bool:
    if _is_snippet_or_metadata_status(retrieval_status):
        return False
    return bool(
        full_text_available
        and full_text_accessed
        and retrieval_status in FULLTEXT_COMPATIBLE_RETRIEVAL_STATUSES
        and (excerpt_or_span or section_locator)
        and source_ref
    )


def _full_text_verified_allowed_errors(
    *,
    path: str,
    retrieval_status: str,
    full_text_available: bool,
    full_text_accessed: bool,
    excerpt_or_span: str,
    section_locator: str,
    source_hash_or_locator: str,
    excerpt_ref_id: str,
    excerpt_summary: str,
) -> list[str]:
    errors: list[str] = []
    if not full_text_accessed:
        errors.append(f"{path}:full_text_verified_allowed_requires_full_text_accessed")
    if not full_text_available:
        errors.append(f"{path}:full_text_verified_allowed_requires_full_text_available")
    if not excerpt_or_span and not section_locator:
        errors.append(f"{path}:full_text_verified_allowed_requires_excerpt_or_section_locator")
    if not source_hash_or_locator and not excerpt_ref_id:
        errors.append(f"{path}:full_text_verified_allowed_requires_source_hash_or_excerpt_ref")
    if not excerpt_summary:
        errors.append(f"{path}:full_text_verified_allowed_requires_excerpt_summary")
    if _is_snippet_or_metadata_status(retrieval_status):
        errors.append(f"{path}:full_text_verified_allowed_invalid_retrieval_status:{retrieval_status}")
    return errors


def _readiness(*, errors: list[str], warnings: list[str], source_count: int, handoff_ready_count: int) -> str:
    if errors:
        return BLOCKED
    if source_count == 0:
        return HOLD_FOR_SOURCE_HANDOFF
    if warnings or handoff_ready_count < source_count:
        return READY_WITH_LIMITATIONS
    return READY_FOR_STAGEB_PACKET_INPUT


def _extract_workflow_readiness(workflow_review: dict[str, Any] | None) -> str:
    if not workflow_review:
        return ""
    validation = workflow_review.get("validation")
    if isinstance(validation, dict):
        return _as_text(validation.get("readiness"))
    return _as_text(workflow_review.get("readiness"))


def _build_caveats(source: dict[str, Any]) -> list[str]:
    caveats: list[str] = []
    for key in ("potential_bias", "source_limitations", "next_stage_verification_notes"):
        value = _as_text(source.get(key))
        if value and value.lower() not in NONE_VALUES and value not in caveats:
            caveats.append(value)
    return caveats


def _authority_category(authority_tier: str, source_type: str = "") -> str:
    text = f"{authority_tier} {source_type}".lower()
    tier = authority_tier.lower()
    if tier in HIGH_AUTHORITY_TIERS or tier in VENDOR_BLOG_CONSULTING_TIERS:
        return tier
    if "regulatory" in text or "supervisory" in text or "supervision" in text:
        return "regulatory"
    if "official" in text or "government" in text or "federal" in text:
        return "official"
    if "peer_reviewed" in text or "academic" in text or "journal" in text:
        return "peer_reviewed"
    if "primary" in text:
        return "primary"
    if "benchmark" in text:
        return "industry_benchmark"
    if "vendor" in text:
        return "vendor"
    if "consult" in text:
        return "consulting"
    if "blog" in text:
        return "blog"
    if "high" in text and "authority" in text:
        return "high_authority"
    if "reputable" in text or "secondary" in text:
        return "reputable_secondary"
    return tier or "unknown"


def _is_vendor_blog_consulting(source_type: str, authority_category: str) -> bool:
    text = f"{source_type} {authority_category}".lower()
    return authority_category in VENDOR_BLOG_CONSULTING_TIERS or any(marker in text for marker in VENDOR_BLOG_CONSULTING_MARKERS)


def _is_snippet_or_metadata_status(retrieval_status: str) -> bool:
    return retrieval_status.lower() in SNIPPET_OR_METADATA_STATUSES


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_as_text(item) for item in value if _as_text(item)]
    if isinstance(value, tuple):
        return [_as_text(item) for item in value if _as_text(item)]
    text = _as_text(value)
    return [text] if text else []


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _all_none_like(values: list[str]) -> bool:
    if not values:
        return True
    return all(value.lower() in NONE_VALUES for value in values)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _render_list(values: list[str]) -> list[str]:
    if not values:
        return ["- none"]
    return [f"- {value}" for value in values]


def _print_validation_summary(validation: HandoffValidationResult) -> None:
    print(f"ok: {_bool_text(validation.ok)}")
    print(f"readiness: {validation.readiness}")
    print(f"source_count: {validation.source_count}")
    print(f"errors_count: {len(validation.errors)}")
    print(f"warnings_count: {len(validation.warnings)}")
    if validation.errors:
        print("errors:")
        for error in validation.errors:
            print(f"- {error}")
    if validation.warnings:
        print("warnings:")
        for warning in validation.warnings:
            print(f"- {warning}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate deterministic full-text source handoff manifests.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build-manifest", help="Build a handoff manifest from a Stage A case directory.")
    build_parser.add_argument("--stageA-case-dir", required=True)
    build_parser.add_argument("--output", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a handoff manifest JSON file.")
    validate_parser.add_argument("--input", required=True)

    review_parser = subparsers.add_parser("review", help="Render a Markdown review for a handoff manifest JSON file.")
    review_parser.add_argument("--input", required=True)
    review_parser.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    if args.command == "build-manifest":
        manifest = build_source_handoff_manifest(args.stageA_case_dir)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        validation = validate_fulltext_handoff_manifest(manifest)
        _print_validation_summary(validation)
        return 0 if validation.ok else 1

    if args.command == "validate":
        manifest = load_json(args.input)
        if not isinstance(manifest, dict):
            print("input manifest must be a JSON object")
            return 1
        validation = validate_fulltext_handoff_manifest(manifest)
        _print_validation_summary(validation)
        return 0 if validation.ok else 1

    if args.command == "review":
        manifest = load_json(args.input)
        if not isinstance(manifest, dict):
            print("input manifest must be a JSON object")
            return 1
        validation = validate_fulltext_handoff_manifest(manifest)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_fulltext_handoff_review(manifest, validation), encoding="utf-8")
        output.with_suffix(".json").write_text(json.dumps(validation.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        _print_validation_summary(validation)
        return 0 if validation.ok else 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
