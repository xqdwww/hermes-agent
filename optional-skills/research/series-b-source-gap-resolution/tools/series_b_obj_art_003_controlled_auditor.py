#!/usr/bin/env python3
"""Deterministic controlled auditor for obj_art_003 dry-runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from obj_art_003_alias_source_guard import check_text
from series_b_obj_art_003_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


AUDIT_TRACE_FILENAME = "obj_art_003_controlled_audit_trace.json"
ALIAS_GUARD_FILENAME = "obj_art_003_alias_source_guard_report.md"
CONTAMINATION_FILENAME = "obj_art_003_contamination_check.md"
SUMMARY_FILENAME = "obj_art_003_controlled_execution_summary.md"
RESULT_FILENAME = "obj_art_003_controlled_execution_result.json"


class ControlledAuditError(ValueError):
    """Raised when the obj_art_003 controlled auditor must fail closed."""

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
        "Roman concrete": ["Roman concrete"],
        "opus caementicium": ["opus caementicium"],
        "pozzolana": ["pozzolana", "pozzolanic ash", "pozzolanic"],
        "hydraulic setting / hydraulic lime": ["hydraulic setting", "hydraulic lime", "hydraulic"],
        "mortar": ["mortar"],
        "marine concrete": ["marine concrete", "maritime concrete"],
        "durability": ["durability", "durable", "long-term strength"],
    }
    return {term: {"passed": _contains_any(text, variants), "accepted_variants": variants} for term, variants in checks.items()}


def _section_checks(text: str) -> dict[str, bool]:
    return {
        section: re.search(rf"^##\s+{re.escape(section)}\s*$", text, re.MULTILINE) is not None
        for section in ("materials_mechanics", "historical_context", "art_architecture")
    }


def _axis_checks(packet: dict[str, Any]) -> dict[str, bool]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    axes = {str(chunk.get("axis")) for chunk in chunks}
    sections = {str(section) for chunk in chunks for section in chunk.get("supports_sections", [])}
    trace_confirmed = packet.get("case_rule_trace_decision") == "ARCHAEOLOGY_AXIS_NOT_HARD_REQUIRED_CONFIRMED"
    return {
        "materials_book": "materials_book" in axes,
        "engineering_book": "engineering_book" in axes,
        "architecture_book": "art_architecture" in sections,
        "archaeology_book_required": False,
        "archaeology_book_requirement_satisfied": trace_confirmed,
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
        "all_chunks_page_bound": all(chunk.get("page_bound") is True for chunk in chunks),
        "all_chunks_source_backed": all(chunk.get("source_backed_text_exists") is True for chunk in chunks),
        "passed": len(chunks) >= 10 and len(referenced) >= 10,
    }


def _quality(text: str, packet: dict[str, Any], terms: dict[str, dict[str, Any]], axes: dict[str, bool], sections: dict[str, bool], binding: dict[str, Any]) -> dict[str, Any]:
    paragraphs = [para for para in text.split("\n\n") if len(para.strip()) > 120]
    rich = (
        len(text) >= 3000
        and len(paragraphs) >= 6
        and all(check["passed"] for check in terms.values())
        and axes["materials_book"]
        and axes["engineering_book"]
        and axes["architecture_book"]
        and axes["archaeology_book_requirement_satisfied"]
        and all(sections.values())
        and bool(binding.get("passed"))
        and len(packet.get("chunks", [])) >= 10
    )
    return {
        "level": "rich" if rich else "usable" if len(text) >= 1500 else "thin",
        "passed_for_formal": rich,
        "text_length": len(text),
        "substantial_paragraph_count": len(paragraphs),
    }


def audit_obj_art_003_dossier(
    *,
    case_id: str,
    raw_dossier_path: str | Path,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Audit obj_art_003 controlled artifacts without production paths."""

    if case_id != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "case_id must be obj_art_003")
    packet = _load_json(source_packet_path, kind="source packet")
    manifest = _load_json(handoff_manifest_path, kind="handoff manifest")
    if packet.get("case_id") != CASE_ID or manifest.get("case_id") != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "audit inputs must be obj_art_003")
    if packet.get("case_rule_trace_decision") != "ARCHAEOLOGY_AXIS_NOT_HARD_REQUIRED_CONFIRMED":
        raise ControlledAuditError("BLOCKED_CASE_RULE_TRACE_UNCLEAR", "case-rule trace is not confirmed")
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
    source_binding = _source_binding(text, packet)
    quality = _quality(text, packet, term_checks, axis_checks, section_checks, source_binding)

    if guard_violations:
        result_enum = "BLOCKED_GUARD_VIOLATION"
    elif not axis_checks["archaeology_book_requirement_satisfied"]:
        result_enum = "BLOCKED_CASE_RULE_TRACE_UNCLEAR"
    elif quality["passed_for_formal"]:
        result_enum = "PASS_CONTROLLED_REGRESSION"
    elif all(check["passed"] for check in term_checks.values()) and all(section_checks.values()):
        result_enum = "PARTIAL_SOURCE_GUARDED_PASS"
    else:
        result_enum = "FAIL_CONTROLLED_REGRESSION"

    passed = result_enum == "PASS_CONTROLLED_REGRESSION"
    partial = result_enum == "PARTIAL_SOURCE_GUARDED_PASS"
    blocked = result_enum.startswith("BLOCKED_")
    audit_trace = {
        "case_id": CASE_ID,
        "controlled_audit_output": True,
        "mock_audit_output": False,
        "audit_adapter_version": "obj_art_003.controlled_auditor.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_dossier_path": str(raw_path),
        "source_packet_path": str(source_packet_path),
        "handoff_manifest_path": str(handoff_manifest_path),
        "term_checks": term_checks,
        "axis_checks": axis_checks,
        "section_checks": section_checks,
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
        "# obj_art_003 alias/source guard report\n\n"
        "case_id: obj_art_003\n"
        "mock_audit_output: false\n"
        f"status: {'PASS' if not guard_violations else 'FAIL'}\n"
        f"violations: {guard_violations}\n",
        encoding="utf-8",
    )
    paths[CONTAMINATION_FILENAME].write_text(
        "# obj_art_003 contamination check\n\n"
        "case_id: obj_art_003\n"
        "mock_audit_output: false\n"
        f"status: {'PASS' if not guard_violations else 'FAIL'}\n"
        f"violations: {guard_violations}\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n",
        encoding="utf-8",
    )
    paths[SUMMARY_FILENAME].write_text(
        "# obj_art_003 controlled execution summary\n\n"
        "case_id: obj_art_003\n"
        "single_case_controlled_dryrun_evidence: true\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n"
        f"result_enum: {result_enum}\n"
        f"quality: {quality['level']}\n",
        encoding="utf-8",
    )
    result["artifact_paths"] = {name: str(path) for name, path in paths.items()}
    paths[RESULT_FILENAME].write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "CONTROLLED_AUDIT_OUTPUT_WRITTEN", "result": result, "artifact_paths": result["artifact_paths"]}
