#!/usr/bin/env python3
"""Deterministic controlled auditor for rel_space_029 dry-runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rel_space_029_alias_source_guard import check_text
from series_b_controlled_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


AUDIT_TRACE_FILENAME = "rel_space_029_controlled_audit_trace.json"
ALIAS_GUARD_FILENAME = "rel_space_029_alias_source_guard_report.md"
CONTAMINATION_FILENAME = "rel_space_029_contamination_check.md"
SUMMARY_FILENAME = "rel_space_029_controlled_execution_summary.md"
RESULT_FILENAME = "rel_space_029_controlled_execution_result.json"


class ControlledAuditError(ValueError):
    """Raised when the controlled auditor must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_json_object(path: str | Path, *, kind: str) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ControlledAuditError("BLOCKED_AUDIT_ENTRY_UNSAFE", f"{kind} root must be a JSON object")
    return payload


def _contains_any(text: str, variants: list[str]) -> bool:
    lowered = text.lower()
    return any(variant.lower() in lowered for variant in variants)


def _required_term_checks(text: str) -> dict[str, dict[str, Any]]:
    checks = {
        "synagogue": ["synagogue"],
        "Torah": ["Torah"],
        "Torah ark / Aron ha-Kodesh": ["Torah ark", "Aron ha-Kodesh", "Aron Kodesh"],
        "bimah / Torah reading platform": ["bimah", "Torah reading platform"],
        "orientation": ["orientation"],
    }
    return {
        term: {"passed": _contains_any(text, variants), "accepted_variants": variants}
        for term, variants in checks.items()
    }


def _section_checks(text: str) -> dict[str, bool]:
    return {
        section: re.search(rf"^##\s+{re.escape(section)}\s*$", text, re.MULTILINE) is not None
        for section in ("spatial_structure", "historical_layers", "theme_tracks")
    }


def _axis_checks(packet: dict[str, Any]) -> dict[str, bool]:
    axes = {str(chunk.get("axis")) for chunk in packet.get("chunks", []) if isinstance(chunk, dict)}
    return {
        "religion_book": "religion_book" in axes,
        "history_book": "history_book" in axes,
        "art_architecture_book_or_archaeology_book": bool({"art_architecture_book", "archaeology_book"} & axes),
    }


def _source_binding_checks(text: str, packet: dict[str, Any]) -> dict[str, Any]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    referenced = [
        chunk["chunk_id"]
        for chunk in chunks
        if isinstance(chunk.get("chunk_id"), str) and chunk["chunk_id"] in text
    ]
    axes = sorted({str(chunk.get("axis")) for chunk in chunks if chunk.get("axis")})
    return {
        "approved_chunk_count": len(chunks),
        "referenced_chunk_count": len(referenced),
        "axes_in_packet": axes,
        "all_chunks_page_bound": all(chunk.get("page_bound") is True for chunk in chunks),
        "all_chunks_source_backed": all(chunk.get("source_backed_text_exists") is True for chunk in chunks),
        "passed": len(chunks) >= 5 and len(referenced) >= 5,
    }


def _planning_noise(text: str) -> list[str]:
    patterns = {
        "phone": r"\bphone\b|\btelephone\b",
        "map": r"\bmap\b|\bmaps\b",
        "booking": r"\bbooking\b|\breservation\b",
        "opening hours": r"\bopening hours\b|\bhours\b",
        "hotel": r"\bhotel\b",
        "restaurant": r"\brestaurant\b",
        "ticket": r"\bticket\b",
        "transport": r"\btransport\b|\bbus route\b",
        "listing": r"\blisting\b|\blistings\b",
        "planning": r"\bplanning\b",
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, text, re.IGNORECASE)]


def _quality_check(text: str, packet: dict[str, Any], term_checks: dict[str, dict[str, Any]], axis_checks: dict[str, bool], section_checks: dict[str, bool], source_binding: dict[str, Any]) -> dict[str, Any]:
    paragraphs = [para for para in text.split("\n\n") if len(para.strip()) > 120]
    rich = (
        len(text) >= 2500
        and len(paragraphs) >= 5
        and all(check["passed"] for check in term_checks.values())
        and all(axis_checks.values())
        and all(section_checks.values())
        and bool(source_binding.get("passed"))
        and len(packet.get("chunks", [])) >= 10
    )
    return {
        "level": "rich" if rich else "usable" if len(text) >= 1200 else "thin",
        "passed_for_formal": rich,
        "text_length": len(text),
        "substantial_paragraph_count": len(paragraphs),
    }


def audit_controlled_dossier(
    *,
    case_id: str,
    raw_dossier_path: str | Path,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Audit rel_space_029 controlled dry-run artifacts without production paths."""

    if case_id != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "case_id must be rel_space_029")
    packet = _load_json_object(source_packet_path, kind="source packet")
    if packet.get("case_id") != CASE_ID:
        raise ControlledAuditError("CASE_ID_MISMATCH", "source packet case_id must be rel_space_029")
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

    alias_violations = check_text(text)
    planning_violations = _planning_noise(text)
    term_checks = _required_term_checks(text)
    section_checks = _section_checks(text)
    axes = _axis_checks(packet)
    source_binding = _source_binding_checks(text, packet)
    quality = _quality_check(text, packet, term_checks, axes, section_checks, source_binding)
    guard_passed = not alias_violations and not planning_violations
    if not guard_passed:
        result_enum = "BLOCKED_GUARD_VIOLATION"
    elif quality["passed_for_formal"]:
        result_enum = "PASS_CONTROLLED_REGRESSION"
    elif all(check["passed"] for check in term_checks.values()) and all(axes.values()) and all(section_checks.values()):
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
        "audit_adapter_version": "rel_space_029.controlled_auditor.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_dossier_path": str(raw_path),
        "source_packet_path": str(source_packet_path),
        "handoff_manifest_path": str(handoff_manifest_path),
        "term_checks": term_checks,
        "axis_checks": axes,
        "section_checks": section_checks,
        "source_binding_checks": source_binding,
        "quality": quality,
        "guard_checks": {
            "passed": guard_passed,
            "alias_source_violations": alias_violations,
            "planning_noise_violations": planning_violations,
        },
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
        "axis_coverage": axes,
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
        "# rel_space_029 alias/source guard report\n\n"
        "case_id: rel_space_029\n"
        "mock_audit_output: false\n"
        f"status: {'PASS' if not alias_violations else 'FAIL'}\n\n"
        f"alias_source_violations: {alias_violations}\n",
        encoding="utf-8",
    )
    paths[CONTAMINATION_FILENAME].write_text(
        "# rel_space_029 contamination check\n\n"
        "case_id: rel_space_029\n"
        "mock_audit_output: false\n"
        f"status: {'PASS' if guard_passed else 'FAIL'}\n"
        f"alias_source_violations: {alias_violations}\n"
        f"planning_noise_violations: {planning_violations}\n"
        "official_baseline_update_performed: false\n"
        "full_series_b_run_performed: false\n"
        "production_default_manifest_integration_performed: false\n",
        encoding="utf-8",
    )
    paths[SUMMARY_FILENAME].write_text(
        "# rel_space_029 controlled execution summary\n\n"
        "case_id: rel_space_029\n"
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
