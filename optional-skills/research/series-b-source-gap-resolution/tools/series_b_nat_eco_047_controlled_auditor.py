#!/usr/bin/env python3
"""Deterministic controlled auditor for nat_eco_047 dry-runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nat_eco_047_alias_source_guard import check_text
from series_b_nat_eco_047_result_schema import (
    CASE_ID,
    EXECUTION_FALSE_FLAGS,
    REQUIRED_AXES,
    REQUIRED_SECTIONS,
    REQUIRED_TERMS,
    require_result_enum,
)


AUDIT_TRACE_FILENAME = "nat_eco_047_controlled_audit_trace.json"
ALIAS_GUARD_FILENAME = "nat_eco_047_alias_source_guard_report.md"
CONTAMINATION_FILENAME = "nat_eco_047_contamination_check.md"
SUMMARY_FILENAME = "nat_eco_047_controlled_execution_summary.md"
RESULT_FILENAME = "nat_eco_047_controlled_execution_result.json"


class ControlledAuditError(ValueError):
    """Raised when the nat_eco_047 controlled auditor must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_json(path: str | Path, *, kind: str) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ControlledAuditError("BLOCKED_GUARD_VIOLATION", f"{kind} root must be an object")
    return payload


def _contains_any(text: str, variants: list[str]) -> bool:
    lower = text.lower()
    return any(variant.lower() in lower for variant in variants)


def _term_checks(text: str) -> dict[str, dict[str, Any]]:
    variants = {
        "atoll": ["atoll"],
        "coral reef": ["coral reef"],
        "fringing reef": ["fringing reef"],
        "barrier reef": ["barrier reef"],
        "lagoon": ["lagoon"],
        "reef flat": ["reef flat"],
        "reef development": ["reef development"],
        "volcanic subsidence": ["volcanic subsidence"],
        "Darwin coral reef theory": ["Darwin coral reef theory", "Darwin's coral reef theory"],
    }
    return {term: {"passed": _contains_any(text, variants[term]), "accepted_variants": variants[term]} for term in REQUIRED_TERMS}


def _section_checks(text: str) -> dict[str, bool]:
    return {
        section: re.search(rf"^##\s+{re.escape(section)}\s*$", text, re.MULTILINE) is not None
        for section in REQUIRED_SECTIONS
    }


def _axis_checks(packet: dict[str, Any]) -> dict[str, Any]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    axes = {str(axis) for chunk in chunks for axis in chunk.get("axis", [])}
    source_types = {str(chunk.get("source_type")) for chunk in chunks}
    local_locator_chunks = [
        chunk for chunk in chunks
        if chunk.get("source_type") == "local_professional_source_locator_context"
    ]
    result = {axis: axis in axes for axis in REQUIRED_AXES}
    result.update(
        {
            "source_types": sorted(source_types),
            "approved_chunk_count": len(chunks),
            "local_professional_locator_count": len(local_locator_chunks),
            "local_professional_source_not_primary_wiki_or_zim": all(
                "wiki_or_zim" not in chunk.get("axis", []) for chunk in local_locator_chunks
            ),
            "all_required_axes_passed": all(axis in axes for axis in REQUIRED_AXES),
        }
    )
    return result


def _binding_checks(packet: dict[str, Any], text: str) -> dict[str, Any]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    lowered = text.lower()
    statuses = {str(chunk.get("binding_status")) for chunk in chunks}
    caveat = (
        "entry / section / local-source-section bound" in lowered
        and "context_entry_bound" in lowered
        and "context_section_bound" in lowered
        and "local_source_section_bound" in lowered
    )
    passed = len(chunks) == 14 and statuses == {
        "CONTEXT_ENTRY_BOUND",
        "CONTEXT_SECTION_BOUND",
        "LOCAL_SOURCE_SECTION_BOUND",
    } and caveat
    return {
        "approved_chunk_count": len(chunks),
        "binding_statuses": sorted(statuses),
        "binding_caveat_in_text": caveat,
        "passed": passed,
    }


def _supplemental_locator_checks(packet: dict[str, Any], text: str) -> dict[str, Any]:
    lowered = text.lower()
    local_chunks = [
        chunk for chunk in packet.get("chunks", [])
        if isinstance(chunk, dict) and chunk.get("source_type") == "local_professional_source_locator_context"
    ]
    locator_only = (
        "local professional source is supplemental locator only" in lowered
        and "not primary wiki_or_zim evidence" in lowered
    )
    return {
        "local_professional_locator_chunk_count": len(local_chunks),
        "locator_only_caveat_in_text": locator_only,
        "local_professional_source_not_primary_wiki_or_zim": all(
            "wiki_or_zim" not in chunk.get("axis", []) for chunk in local_chunks
        ),
        "passed": len(local_chunks) == 1
        and locator_only
        and all("wiki_or_zim" not in chunk.get("axis", []) for chunk in local_chunks),
    }


def _source_binding(text: str, packet: dict[str, Any]) -> dict[str, Any]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    referenced = [
        chunk["chunk_id"]
        for chunk in chunks
        if isinstance(chunk.get("chunk_id"), str) and chunk["chunk_id"] in text
    ]
    return {
        "approved_chunk_count": len(chunks),
        "referenced_chunk_count": len(referenced),
        "passed": len(chunks) == 14 and len(referenced) == 14,
    }


def _policy_checks(packet: dict[str, Any], manifest: dict[str, Any]) -> dict[str, bool]:
    locks = packet.get("policy_locks")
    if not isinstance(locks, dict):
        return {"passed": False}
    return {
        "production_default_disabled": locks.get("production_default_loader_enabled") is False
        and manifest.get("production_default_loader_enabled") is False,
        "baseline_update_disabled": locks.get("official_baseline_update_enabled") is False
        and manifest.get("official_baseline_update_enabled") is False,
        "full_series_b_disabled": locks.get("full_series_b_enabled") is False
        and manifest.get("full_series_b_enabled") is False,
        "passed": locks.get("production_default_loader_enabled") is False
        and locks.get("official_baseline_update_enabled") is False
        and locks.get("full_series_b_enabled") is False
        and manifest.get("production_default_loader_enabled") is False
        and manifest.get("official_baseline_update_enabled") is False
        and manifest.get("full_series_b_enabled") is False,
    }


def _quality(
    text: str,
    terms: dict[str, dict[str, Any]],
    axes: dict[str, Any],
    sections: dict[str, bool],
    binding: dict[str, Any],
    supplemental: dict[str, Any],
    source_binding: dict[str, Any],
    policy: dict[str, bool],
) -> dict[str, Any]:
    paragraphs = [para for para in text.split("\n\n") if len(para.strip()) > 120]
    rich = (
        len(text) >= 3500
        and len(paragraphs) >= 8
        and all(check["passed"] for check in terms.values())
        and axes["all_required_axes_passed"]
        and all(sections.values())
        and bool(binding.get("passed"))
        and bool(supplemental.get("passed"))
        and bool(source_binding.get("passed"))
        and bool(policy.get("passed"))
    )
    return {
        "level": "rich" if rich else "usable" if len(text) >= 1800 else "thin",
        "passed_for_formal": rich,
        "text_length": len(text),
        "substantial_paragraph_count": len(paragraphs),
    }


def audit_nat_eco_047_dossier(
    *,
    case_id: str,
    raw_dossier_path: str | Path,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Audit nat_eco_047 controlled artifacts without production paths."""

    if case_id != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "case_id must be nat_eco_047")
    packet = _load_json(source_packet_path, kind="source packet")
    manifest = _load_json(handoff_manifest_path, kind="handoff manifest")
    if packet.get("case_id") != CASE_ID or manifest.get("case_id") != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "audit inputs must be nat_eco_047")

    raw_path = Path(raw_dossier_path).expanduser()
    text = raw_path.read_text(encoding="utf-8")
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)

    guard_violations = check_text(text)
    term_checks = _term_checks(text)
    section_checks = _section_checks(text)
    axis_checks = _axis_checks(packet)
    binding_checks = _binding_checks(packet, text)
    supplemental_checks = _supplemental_locator_checks(packet, text)
    source_binding = _source_binding(text, packet)
    policy_checks = _policy_checks(packet, manifest)
    quality = _quality(
        text,
        term_checks,
        axis_checks,
        section_checks,
        binding_checks,
        supplemental_checks,
        source_binding,
        policy_checks,
    )

    if guard_violations:
        result_enum = "BLOCKED_GUARD_VIOLATION"
    elif not policy_checks["production_default_disabled"]:
        result_enum = "BLOCKED_PRODUCTION_DEFAULT_RISK"
    elif not policy_checks["baseline_update_disabled"]:
        result_enum = "BLOCKED_BASELINE_UPDATE_RISK"
    elif not policy_checks["full_series_b_disabled"]:
        result_enum = "BLOCKED_FULL_SERIES_B_RISK"
    elif not binding_checks["passed"]:
        result_enum = "BLOCKED_BINDING_INSUFFICIENT"
    elif not supplemental_checks["passed"]:
        result_enum = "BLOCKED_CONTEXT_PRIMARY_EVIDENCE_REQUIRED"
    elif quality["passed_for_formal"]:
        result_enum = "PASS_CONTROLLED_REGRESSION"
    elif all(check["passed"] for check in term_checks.values()) and all(section_checks.values()):
        result_enum = "PARTIAL_SOURCE_GUARDED_PASS"
    else:
        result_enum = "FAIL_CONTROLLED_REGRESSION"
    require_result_enum(result_enum)

    passed = result_enum == "PASS_CONTROLLED_REGRESSION"
    partial = result_enum == "PARTIAL_SOURCE_GUARDED_PASS"
    blocked = result_enum.startswith("BLOCKED_")
    audit_trace = {
        "case_id": CASE_ID,
        "controlled_audit_output": True,
        "mock_audit_output": False,
        "audit_adapter_version": "nat_eco_047.controlled_auditor.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_dossier_path": str(raw_path),
        "source_packet_path": str(source_packet_path),
        "handoff_manifest_path": str(handoff_manifest_path),
        "term_checks": term_checks,
        "axis_checks": axis_checks,
        "section_checks": section_checks,
        "binding_checks": binding_checks,
        "supplemental_locator_checks": supplemental_checks,
        "source_binding_checks": source_binding,
        "policy_checks": policy_checks,
        "quality": quality,
        "guard_checks": {"passed": not guard_violations, "violations": guard_violations},
        "result_enum": result_enum,
        "stop_reasons": [] if passed else ["controlled audit did not meet formal pass gate"],
        "single_case_controlled_dryrun_evidence": True,
        **EXECUTION_FALSE_FLAGS,
    }
    result = {
        "case_id": CASE_ID,
        "result_enum": result_enum,
        "passed": passed,
        "partial": partial,
        "blocked": blocked,
        "controlled_audit_output": True,
        "mock_audit_output": False,
        "quality": quality,
        "term_coverage": term_checks,
        "axis_coverage": axis_checks,
        "section_coverage": section_checks,
        "binding_caveat_preserved": binding_checks["passed"],
        "supplemental_locator_caveat_preserved": supplemental_checks["passed"],
        "guard_result": audit_trace["guard_checks"],
        "artifact_paths": {},
        "single_case_controlled_dryrun_evidence": True,
        "official_series_b_baseline_update": False,
        **EXECUTION_FALSE_FLAGS,
    }
    paths = {
        AUDIT_TRACE_FILENAME: target / AUDIT_TRACE_FILENAME,
        ALIAS_GUARD_FILENAME: target / ALIAS_GUARD_FILENAME,
        CONTAMINATION_FILENAME: target / CONTAMINATION_FILENAME,
        SUMMARY_FILENAME: target / SUMMARY_FILENAME,
        RESULT_FILENAME: target / RESULT_FILENAME,
    }
    paths[AUDIT_TRACE_FILENAME].write_text(json.dumps(audit_trace, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths[ALIAS_GUARD_FILENAME].write_text(
        "# nat_eco_047 alias/source guard report\n\n"
        "case_id: nat_eco_047\n"
        "mock_audit_output: false\n"
        "accepted_source_families: wiki_or_zim; encyclopedia_context; local_professional_source_locator_context\n"
        "local_professional_source_usage: supplemental locator only\n"
        f"status: {'PASS' if not guard_violations else 'FAIL'}\n"
        f"violations: {guard_violations}\n",
        encoding="utf-8",
    )
    paths[CONTAMINATION_FILENAME].write_text(
        "# nat_eco_047 contamination check\n\n"
        "case_id: nat_eco_047\n"
        "mock_audit_output: false\n"
        f"status: {'PASS' if not guard_violations else 'FAIL'}\n"
        f"violations: {guard_violations}\n"
        "README_title_only_counted_as_evidence: false\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n",
        encoding="utf-8",
    )
    paths[SUMMARY_FILENAME].write_text(
        "# nat_eco_047 controlled execution summary\n\n"
        "case_id: nat_eco_047\n"
        "single_case_controlled_dryrun_evidence: true\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n"
        f"binding_caveat_preserved: {str(result['binding_caveat_preserved']).lower()}\n"
        f"supplemental_locator_caveat_preserved: {str(result['supplemental_locator_caveat_preserved']).lower()}\n"
        f"result_enum: {result_enum}\n"
        f"quality: {quality['level']}\n",
        encoding="utf-8",
    )
    result["artifact_paths"] = {name: str(path) for name, path in paths.items()}
    paths[RESULT_FILENAME].write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "CONTROLLED_AUDIT_OUTPUT_WRITTEN", "result": result, "artifact_paths": result["artifact_paths"]}
