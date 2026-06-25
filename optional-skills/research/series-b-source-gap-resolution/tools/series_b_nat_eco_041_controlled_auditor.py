#!/usr/bin/env python3
"""Deterministic controlled auditor for nat_eco_041 dry-runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nat_eco_041_alias_source_guard import check_text
from series_b_nat_eco_041_result_schema import (
    CASE_ID,
    EXECUTION_FALSE_FLAGS,
    REQUIRED_CONTEXT_AXES,
    REQUIRED_PROFESSIONAL_AXES,
    REQUIRED_SECTIONS,
    REQUIRED_TERMS,
    require_result_enum,
)


AUDIT_TRACE_FILENAME = "nat_eco_041_controlled_audit_trace.json"
ALIAS_GUARD_FILENAME = "nat_eco_041_alias_source_guard_report.md"
CONTAMINATION_FILENAME = "nat_eco_041_contamination_check.md"
SUMMARY_FILENAME = "nat_eco_041_controlled_execution_summary.md"
RESULT_FILENAME = "nat_eco_041_controlled_execution_result.json"


class ControlledAuditError(ValueError):
    """Raised when the nat_eco_041 controlled auditor must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_json(path: str | Path, *, kind: str) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ControlledAuditError("BLOCKED_AUDIT_ENTRY_UNSAFE", f"{kind} root must be an object")
    return payload


def _contains_any(text: str, variants: list[str]) -> bool:
    lower = text.lower()
    return any(variant.lower() in lower for variant in variants)


def _term_checks(text: str) -> dict[str, dict[str, Any]]:
    checks = {
        "saltation": ["saltation"],
        "aeolian processes": ["aeolian processes", "aeolian process"],
        "sand dune": ["sand dune", "sand dunes"],
        "sediment transport": ["sediment transport"],
        "wind erosion": ["wind erosion"],
        "creep": ["creep"],
        "suspension": ["suspension"],
        "ripples": ["ripples", "ripple"],
        "aeolian sediment transport": ["aeolian sediment transport"],
        "sand transport": ["sand transport"],
    }
    return {term: {"passed": _contains_any(text, variants), "accepted_variants": variants} for term, variants in checks.items()}


def _section_checks(text: str) -> dict[str, bool]:
    return {
        section: re.search(rf"^##\s+{re.escape(section)}\s*$", text, re.MULTILINE) is not None
        for section in REQUIRED_SECTIONS
    }


def _axis_checks(packet: dict[str, Any]) -> dict[str, bool]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    axes = {str(axis) for chunk in chunks for axis in chunk.get("axis", [])}
    return {
        "geomorphology_book": "geomorphology_book" in axes,
        "earth_science_book": "earth_science_book" in axes,
        "geology_book": "geology_book" in axes,
        "geography_book": "geography_book" in axes,
        "nature_book": "nature_book" in axes,
        "wiki_or_zim": "wiki_or_zim" in axes,
        "professional_axis_satisfied": any(axis in axes for axis in REQUIRED_PROFESSIONAL_AXES),
        "context_axis_satisfied": any(axis in axes for axis in REQUIRED_CONTEXT_AXES),
    }


def _binding_checks(packet: dict[str, Any], text: str) -> dict[str, Any]:
    professional = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict) and chunk.get("chunk_group") == "professional"]
    context = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict) and chunk.get("chunk_group") == "context"]
    text_lower = text.lower()
    professional_caveat = "partial_section_locator_used" in text_lower
    context_caveat = "context_entry_bound" in text_lower and "context_section_bound" in text_lower
    dune_caveat = "dune migration" in text_lower and "marginal" in text_lower and "not strong exact" in text_lower
    overcredit = any(
        phrase in text_lower
        for phrase in (
            "dune migration: strong exact",
            "dune migration is strong exact",
            "strong exact dune migration",
        )
    )
    return {
        "professional_chunk_count": len(professional),
        "context_chunk_count": len(context),
        "all_professional_partial_locator": all(chunk.get("binding_status") == "PARTIAL_SECTION_LOCATOR_USED" for chunk in professional),
        "all_context_entry_or_section_bound": all(
            chunk.get("binding_status") in {"CONTEXT_ENTRY_BOUND", "CONTEXT_SECTION_BOUND"} for chunk in context
        ),
        "professional_binding_caveat_preserved": professional_caveat,
        "context_binding_caveat_preserved": context_caveat,
        "dune_migration_caveat_preserved": dune_caveat,
        "dune_migration_overcredited": overcredit,
        "passed": len(professional) == 13
        and len(context) == 28
        and professional_caveat
        and context_caveat
        and dune_caveat
        and not overcredit,
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
        "passed": len(chunks) == 41 and len(referenced) >= 30,
    }


def _quality(
    text: str,
    terms: dict[str, dict[str, Any]],
    axes: dict[str, bool],
    sections: dict[str, bool],
    binding: dict[str, Any],
    source_binding: dict[str, Any],
) -> dict[str, Any]:
    paragraphs = [para for para in text.split("\n\n") if len(para.strip()) > 120]
    rich = (
        len(text) >= 3500
        and len(paragraphs) >= 8
        and all(check["passed"] for check in terms.values())
        and axes["professional_axis_satisfied"]
        and axes["context_axis_satisfied"]
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


def audit_nat_eco_041_dossier(
    *,
    case_id: str,
    raw_dossier_path: str | Path,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Audit nat_eco_041 controlled artifacts without production paths."""

    if case_id != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "case_id must be nat_eco_041")
    packet = _load_json(source_packet_path, kind="source packet")
    manifest = _load_json(handoff_manifest_path, kind="handoff manifest")
    if packet.get("case_id") != CASE_ID or manifest.get("case_id") != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "audit inputs must be nat_eco_041")
    locks = packet.get("policy_locks")
    if not isinstance(locks, dict):
        raise ControlledAuditError("BLOCKED_AUDIT_ENTRY_UNSAFE", "source packet lacks policy locks")
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
    elif binding_checks["dune_migration_overcredited"]:
        result_enum = "BLOCKED_DUNE_MIGRATION_EXACT_TERM_REQUIRED"
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
        "audit_adapter_version": "nat_eco_041.controlled_auditor.v1",
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
        "binding_caveat_preserved": binding_checks["professional_binding_caveat_preserved"]
        and binding_checks["context_binding_caveat_preserved"],
        "dune_migration_caveat_preserved": binding_checks["dune_migration_caveat_preserved"],
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
        "# nat_eco_041 alias/source guard report\n\n"
        "case_id: nat_eco_041\n"
        "mock_audit_output: false\n"
        f"status: {'PASS' if not guard_violations else 'FAIL'}\n"
        f"violations: {guard_violations}\n",
        encoding="utf-8",
    )
    paths[CONTAMINATION_FILENAME].write_text(
        "# nat_eco_041 contamination check\n\n"
        "case_id: nat_eco_041\n"
        "mock_audit_output: false\n"
        f"status: {'PASS' if not guard_violations else 'FAIL'}\n"
        f"violations: {guard_violations}\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n",
        encoding="utf-8",
    )
    paths[SUMMARY_FILENAME].write_text(
        "# nat_eco_041 controlled execution summary\n\n"
        "case_id: nat_eco_041\n"
        "single_case_controlled_dryrun_evidence: true\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n"
        f"binding_caveat_preserved: {str(result['binding_caveat_preserved']).lower()}\n"
        f"dune_migration_caveat_preserved: {str(result['dune_migration_caveat_preserved']).lower()}\n"
        f"result_enum: {result_enum}\n"
        f"quality: {quality['level']}\n",
        encoding="utf-8",
    )
    result["artifact_paths"] = {name: str(path) for name, path in paths.items()}
    paths[RESULT_FILENAME].write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "CONTROLLED_AUDIT_OUTPUT_WRITTEN", "result": result, "artifact_paths": result["artifact_paths"]}
