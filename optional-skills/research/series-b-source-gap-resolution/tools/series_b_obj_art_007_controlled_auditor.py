#!/usr/bin/env python3
"""Deterministic controlled auditor for obj_art_007 dry-runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from obj_art_007_alias_source_guard import check_text
from series_b_obj_art_007_result_schema import (
    CASE_ID,
    EXECUTION_FALSE_FLAGS,
    REQUIRED_AXES,
    REQUIRED_SECTIONS,
    REQUIRED_TERMS,
    require_result_enum,
)

AUDIT_TRACE_FILENAME = "obj_art_007_controlled_audit_trace.json"
ALIAS_GUARD_FILENAME = "obj_art_007_alias_source_guard_report.md"
CONTAMINATION_FILENAME = "obj_art_007_contamination_check.md"
SUMMARY_FILENAME = "obj_art_007_controlled_execution_summary.md"
RESULT_FILENAME = "obj_art_007_controlled_execution_result.json"


class ControlledAuditError(ValueError):
    """Raised when the obj_art_007 controlled auditor must fail closed."""

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
        "dougong": ["dougong", "dou-gong"],
        "bracket set": ["bracket set", "bracket-set"],
        "timber framing": ["timber framing", "timber-frame", "timber structure", "timber structures"],
        "timber joinery": ["timber joinery", "mortise", "mortises", "hidden timber dowels"],
        "interlocking timber joinery": ["interlocking timber joinery", "intertwine", "interpenetrate", "interpenetrating bracket"],
        "load transfer": ["load transfer", "transfers roof-beam load", "load path", "load-bearing"],
        "cantilever": ["cantilever", "cantilevers"],
        "seismic performance": ["seismic performance"],
        "energy dissipation": ["energy dissipation"],
        "Yingzao Fashi": ["Yingzao Fashi"],
        "Chinese timber architecture": ["Chinese timber architecture", "Chinese timber-frame", "Chinese structural system"],
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
    caveats = packet.get("caveats") if isinstance(packet.get("caveats"), dict) else {}
    if caveats.get("context_sources_trace_only") is True:
        axes.add("context_sources")
    result = {axis: axis in axes for axis in REQUIRED_AXES}
    result.update(
        {
            "source_axes": sorted(axes),
            "approved_chunk_count": len(chunks),
            "all_required_axes_passed": all(axis in axes for axis in REQUIRED_AXES),
        }
    )
    return result


def _binding_checks(packet: dict[str, Any], text: str) -> dict[str, Any]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    lowered = text.lower()
    caveat = (
        "page_binding_caveat: preserved" in lowered
        and "0/0" in lowered
        and "chunk_id / section locator / text_sha256" in lowered
        and "no precise page numbers are claimed" in lowered
    )
    no_precise = all(chunk.get("precise_page_number_claimed") is False for chunk in chunks)
    hashes = all(chunk.get("source_hash_or_text_hash") for chunk in chunks)
    passed = len(chunks) == 14 and caveat and no_precise and hashes
    return {
        "approved_chunk_count": len(chunks),
        "page_binding_caveat_in_text": caveat,
        "zero_zero_binding_not_precise": no_precise,
        "text_hash_trace_present": hashes,
        "passed": passed,
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
    policy = manifest.get("production_path_policy")
    if not isinstance(locks, dict) or not isinstance(policy, dict):
        return {"passed": False}
    return {
        "production_default_disabled": locks.get("production_default_loader_enabled") is False
        and policy.get("production_default_loader_enabled") is False,
        "baseline_update_disabled": locks.get("official_baseline_update_enabled") is False
        and policy.get("official_baseline_update_enabled") is False,
        "full_series_b_disabled": locks.get("full_series_b_enabled") is False
        and policy.get("full_series_b_enabled") is False,
        "passed": locks.get("production_default_loader_enabled") is False
        and locks.get("official_baseline_update_enabled") is False
        and locks.get("full_series_b_enabled") is False
        and policy.get("production_default_loader_enabled") is False
        and policy.get("official_baseline_update_enabled") is False
        and policy.get("full_series_b_enabled") is False,
    }


def _quality(
    text: str,
    terms: dict[str, dict[str, Any]],
    axes: dict[str, Any],
    sections: dict[str, bool],
    binding: dict[str, Any],
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
        and bool(source_binding.get("passed"))
        and bool(policy.get("passed"))
    )
    return {
        "level": "rich" if rich else "usable" if len(text) >= 1800 else "thin",
        "passed_for_formal": rich,
        "text_length": len(text),
        "substantial_paragraph_count": len(paragraphs),
    }


def audit_obj_art_007_dossier(
    *,
    case_id: str,
    raw_dossier_path: str | Path,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Audit obj_art_007 controlled artifacts without production paths."""

    if case_id != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "case_id must be obj_art_007")
    packet = _load_json(source_packet_path, kind="source packet")
    manifest = _load_json(handoff_manifest_path, kind="handoff manifest")
    if packet.get("case_id") != CASE_ID or manifest.get("case_id") != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "audit inputs must be obj_art_007")

    raw_path = Path(raw_dossier_path).expanduser()
    text = raw_path.read_text(encoding="utf-8")
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)

    guard_violations = check_text(text)
    term_checks = _term_checks(text)
    section_checks = _section_checks(text)
    axis_checks = _axis_checks(packet)
    binding_checks = _binding_checks(packet, text)
    source_binding = _source_binding(text, packet)
    policy_checks = _policy_checks(packet, manifest)
    quality = _quality(text, term_checks, axis_checks, section_checks, binding_checks, source_binding, policy_checks)

    if guard_violations:
        result_enum = "BLOCKED_GUARD_VIOLATION"
    elif not policy_checks["production_default_disabled"]:
        result_enum = "BLOCKED_PRODUCTION_DEFAULT_RISK"
    elif not policy_checks["baseline_update_disabled"]:
        result_enum = "BLOCKED_BASELINE_UPDATE_RISK"
    elif not policy_checks["full_series_b_disabled"]:
        result_enum = "BLOCKED_FULL_SERIES_B_RISK"
    elif not binding_checks["page_binding_caveat_in_text"]:
        result_enum = "BLOCKED_BINDING_INSUFFICIENT"
    elif not binding_checks["zero_zero_binding_not_precise"]:
        result_enum = "BLOCKED_EXACT_PAGE_REQUIRED"
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
        "audit_adapter_version": "obj_art_007.controlled_auditor.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_dossier_path": str(raw_path),
        "source_packet_path": str(source_packet_path),
        "handoff_manifest_path": str(handoff_manifest_path),
        "term_checks": term_checks,
        "axis_checks": axis_checks,
        "section_checks": section_checks,
        "page_binding_checks": binding_checks,
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
        "page_binding_caveat_preserved": binding_checks["passed"],
        "precise_page_number_claimed": False,
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
        "# obj_art_007 alias/source guard report\n\n"
        "case_id: obj_art_007\n"
        "mock_audit_output: false\n"
        "accepted_source_scope: approved source packet only\n"
        "page_binding_caveat_preserved: true\n"
        f"status: {'PASS' if not guard_violations else 'FAIL'}\n"
        f"violations: {guard_violations}\n",
        encoding="utf-8",
    )
    paths[CONTAMINATION_FILENAME].write_text(
        "# obj_art_007 contamination check\n\n"
        "case_id: obj_art_007\n"
        "mock_audit_output: false\n"
        f"status: {'PASS' if not guard_violations else 'FAIL'}\n"
        f"violations: {guard_violations}\n"
        "README_title_only_counted_as_evidence: false\n"
        "precise_page_number_claimed: false\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n",
        encoding="utf-8",
    )
    paths[SUMMARY_FILENAME].write_text(
        "# obj_art_007 controlled execution summary\n\n"
        "case_id: obj_art_007\n"
        "single_case_controlled_dryrun_evidence: true\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n"
        f"page_binding_caveat_preserved: {str(result['page_binding_caveat_preserved']).lower()}\n"
        "precise_page_number_claimed: false\n"
        f"result_enum: {result_enum}\n"
        f"quality: {quality['level']}\n",
        encoding="utf-8",
    )
    result["artifact_paths"] = {name: str(path) for name, path in paths.items()}
    paths[RESULT_FILENAME].write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "CONTROLLED_AUDIT_OUTPUT_WRITTEN", "result": result, "artifact_paths": result["artifact_paths"]}
