#!/usr/bin/env python3
"""Deterministic controlled auditor for hist_arch_023 dry-runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hist_arch_023_alias_source_guard import check_text
from series_b_hist_arch_023_result_schema import (
    CASE_ID,
    EXECUTION_FALSE_FLAGS,
    REQUIRED_AXES,
    REQUIRED_SECTIONS,
    require_result_enum,
)


AUDIT_TRACE_FILENAME = "hist_arch_023_controlled_audit_trace.json"
ALIAS_GUARD_FILENAME = "hist_arch_023_alias_source_guard_report.md"
CONTAMINATION_FILENAME = "hist_arch_023_contamination_check.md"
SUMMARY_FILENAME = "hist_arch_023_controlled_execution_summary.md"
RESULT_FILENAME = "hist_arch_023_controlled_execution_result.json"


class ControlledAuditError(ValueError):
    """Raised when the hist_arch_023 controlled auditor must fail closed."""

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
    checks = {
        "Clovis culture": ["clovis culture"],
        "Clovis point": ["clovis point"],
        "Clovis technology": ["clovis technology"],
        "lithic technology": ["lithic technology"],
        "lithic reduction": ["lithic reduction"],
        "flintknapping": ["flintknapping"],
        "pressure flaking": ["pressure flaking"],
        "percussion": ["percussion"],
        "biface": ["biface", "bifaces"],
        "flake": ["flake", "flakes"],
        "core": ["core", "cores"],
        "reduction sequence": ["reduction sequence"],
        "fracture mechanics": ["fracture mechanics"],
        "stone tool": ["stone tool"],
    }
    return {term: {"passed": _contains_any(text, variants), "accepted_variants": variants} for term, variants in checks.items()}


def _section_checks(text: str) -> dict[str, bool]:
    return {
        section: re.search(rf"^##\s+{re.escape(section)}\s*$", text, re.MULTILINE) is not None
        for section in REQUIRED_SECTIONS
    }


def _axis_checks(packet: dict[str, Any]) -> dict[str, Any]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    axes = {str(axis) for chunk in chunks for axis in chunk.get("axis", [])}
    context_chunks = packet.get("context_or_alias_guard_chunks", [])
    titles = {str(chunk.get("source_title")) for chunk in chunks}
    return {
        "archaeology_book": "archaeology_book" in axes,
        "lithic_technology_source": "lithic_technology_source" in axes,
        "materials_book": "materials_book" in axes,
        "fracture_mechanics_source": "fracture_mechanics_source" in axes and "Tsirk Fractures in Knapping" in titles,
        "context_sources": isinstance(context_chunks, list) and len(context_chunks) == 2,
        "wiki_or_zim": "CAVEATED_CONTEXT_AVAILABLE_NOT_PRIMARY_EVIDENCE",
        "all_required_professional_axes_passed": all(axis in axes for axis in REQUIRED_AXES if axis != "context_sources"),
    }


def _binding_checks(packet: dict[str, Any], text: str) -> dict[str, Any]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    lowered = text.lower()
    return {
        "primary_chunk_count": len(chunks),
        "all_chunks_weak_bound": all(chunk.get("binding_status") == "PAGE_BOUND_WEAK_EPUB_SECTION_BOUND" for chunk in chunks),
        "binding_caveat_in_text": "page_bound_weak_epub_section_bound" in lowered
        and "weak / partial binding caveat" in lowered
        and "not page-precise" in lowered,
        "context_not_primary_in_text": "context sources are background and alias guard only" in lowered,
        "passed": len(chunks) == 12
        and all(chunk.get("binding_status") == "PAGE_BOUND_WEAK_EPUB_SECTION_BOUND" for chunk in chunks)
        and "page_bound_weak_epub_section_bound" in lowered
        and "not page-precise" in lowered,
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
        "passed": len(chunks) == 12 and len(referenced) == 12,
    }


def _quality(
    text: str,
    terms: dict[str, dict[str, Any]],
    axes: dict[str, Any],
    sections: dict[str, bool],
    binding: dict[str, Any],
    source_binding: dict[str, Any],
) -> dict[str, Any]:
    paragraphs = [para for para in text.split("\n\n") if len(para.strip()) > 120]
    rich = (
        len(text) >= 3500
        and len(paragraphs) >= 8
        and all(check["passed"] for check in terms.values())
        and axes["all_required_professional_axes_passed"]
        and axes["context_sources"] is True
        and all(sections.values())
        and bool(binding.get("passed"))
        and bool(source_binding.get("passed"))
    )
    return {
        "level": "rich" if rich else "usable" if len(text) >= 1800 else "thin",
        "passed_for_formal": rich,
        "text_length": len(text),
        "substantial_paragraph_count": len(paragraphs),
    }


def audit_hist_arch_023_dossier(
    *,
    case_id: str,
    raw_dossier_path: str | Path,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Audit hist_arch_023 controlled artifacts without production paths."""

    if case_id != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "case_id must be hist_arch_023")
    packet = _load_json(source_packet_path, kind="source packet")
    manifest = _load_json(handoff_manifest_path, kind="handoff manifest")
    if packet.get("case_id") != CASE_ID or manifest.get("case_id") != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "audit inputs must be hist_arch_023")
    locks = packet.get("policy_locks")
    if not isinstance(locks, dict):
        raise ControlledAuditError("BLOCKED_GUARD_VIOLATION", "source packet lacks policy locks")
    if locks.get("production_default_loader_enabled") is not False:
        raise ControlledAuditError("BLOCKED_PRODUCTION_DEFAULT_RISK", "production default lock is unsafe")
    if locks.get("official_baseline_update_enabled") is not False:
        raise ControlledAuditError("BLOCKED_BASELINE_UPDATE_RISK", "baseline lock is unsafe")
    if locks.get("full_series_b_enabled") is not False:
        raise ControlledAuditError("BLOCKED_FULL_SERIES_B_RISK", "full Series B lock is unsafe")

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
    quality = _quality(text, term_checks, axis_checks, section_checks, binding_checks, source_binding)

    if guard_violations:
        result_enum = "BLOCKED_GUARD_VIOLATION"
    elif not binding_checks["passed"]:
        result_enum = "BLOCKED_BINDING_INSUFFICIENT"
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
        "audit_adapter_version": "hist_arch_023.controlled_auditor.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_dossier_path": str(raw_path),
        "source_packet_path": str(source_packet_path),
        "handoff_manifest_path": str(handoff_manifest_path),
        "term_checks": term_checks,
        "axis_checks": axis_checks,
        "section_checks": section_checks,
        "binding_checks": binding_checks,
        "source_binding_checks": source_binding,
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
        "# hist_arch_023 alias/source guard report\n\n"
        "case_id: hist_arch_023\n"
        "mock_audit_output: false\n"
        "accepted_primary_sources: Bradley Clovis Technology; Tsirk Fractures in Knapping\n"
        f"status: {'PASS' if not guard_violations else 'FAIL'}\n"
        f"violations: {guard_violations}\n",
        encoding="utf-8",
    )
    paths[CONTAMINATION_FILENAME].write_text(
        "# hist_arch_023 contamination check\n\n"
        "case_id: hist_arch_023\n"
        "mock_audit_output: false\n"
        f"status: {'PASS' if not guard_violations else 'FAIL'}\n"
        f"violations: {guard_violations}\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n",
        encoding="utf-8",
    )
    paths[SUMMARY_FILENAME].write_text(
        "# hist_arch_023 controlled execution summary\n\n"
        "case_id: hist_arch_023\n"
        "single_case_controlled_dryrun_evidence: true\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n"
        f"binding_caveat_preserved: {str(result['binding_caveat_preserved']).lower()}\n"
        f"result_enum: {result_enum}\n"
        f"quality: {quality['level']}\n",
        encoding="utf-8",
    )
    result["artifact_paths"] = {name: str(path) for name, path in paths.items()}
    paths[RESULT_FILENAME].write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "CONTROLLED_AUDIT_OUTPUT_WRITTEN", "result": result, "artifact_paths": result["artifact_paths"]}
