#!/usr/bin/env python3
"""rel_space_029 audit adapter.

The default path calls the deterministic, case-scoped controlled auditor. Tests
may opt into a mock audit path that writes complete mock artifacts.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from rel_space_029_alias_source_guard import check_text
from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_controlled_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS
from series_b_rel_space_029_controlled_auditor import ControlledAuditError, audit_controlled_dossier


AUDIT_TRACE_FILENAME = "rel_space_029_controlled_audit_trace.json"
ALIAS_GUARD_FILENAME = "rel_space_029_alias_source_guard_report.md"
CONTAMINATION_FILENAME = "rel_space_029_contamination_check.md"
SUMMARY_FILENAME = "rel_space_029_controlled_execution_summary.md"
RESULT_FILENAME = "rel_space_029_controlled_execution_result.json"


class AuditAdapterError(ValueError):
    """Raised when the audit adapter blocks execution."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_json_object(path: str | Path, *, kind: str) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise AuditAdapterError("BLOCKED_AUDIT_ENTRY_UNSAFE", f"{kind} root must be a JSON object")
    return payload


def _term_status(text: str, terms: list[str]) -> dict[str, bool]:
    lowered = text.lower()
    return {term: all(part.strip().lower() in lowered for part in term.split("/")) for term in terms}


def audit_rel_space_029_controlled_dossier(
    *,
    case_id: str,
    raw_dossier_path: str | Path,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
    use_mock_audit: bool = False,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Audit a raw dossier with the controlled auditor or explicit test mock."""

    if case_id != CASE_ID:
        raise AuditAdapterError("CASE_ID_MISMATCH", "case_id must be rel_space_029")
    if no_production_default is not True:
        raise AuditAdapterError("BLOCKED_PRODUCTION_DEFAULT_RISK", "no_production_default must be true")
    if no_baseline_update is not True:
        raise AuditAdapterError("BLOCKED_BASELINE_UPDATE_RISK", "no_baseline_update must be true")
    if no_full_series_b is not True:
        raise AuditAdapterError("BLOCKED_FULL_SERIES_B_RISK", "no_full_series_b must be true")

    try:
        target_dir = validate_output_dir_policy(output_dir, repo_root=repo_root)
    except ArtifactContractError as exc:
        raise AuditAdapterError("OUTPUT_DIR_UNSAFE", str(exc)) from exc
    if not use_mock_audit:
        try:
            return audit_controlled_dossier(
                case_id=case_id,
                raw_dossier_path=raw_dossier_path,
                source_packet_path=source_packet_path,
                handoff_manifest_path=handoff_manifest_path,
                output_dir=target_dir,
            )
        except ControlledAuditError as exc:
            raise AuditAdapterError(exc.error_code, str(exc)) from exc

    packet = _load_json_object(source_packet_path, kind="source packet")
    if packet.get("case_id") != CASE_ID:
        raise AuditAdapterError("CASE_ID_MISMATCH", "source packet case_id must be rel_space_029")
    raw_path = Path(raw_dossier_path).expanduser()
    dossier_text = raw_path.read_text(encoding="utf-8")
    violations = check_text(dossier_text)

    required_terms = [
        "synagogue",
        "Torah",
        "Torah ark",
        "bimah",
        "Torah reading platform",
        "orientation",
    ]
    required_sections = ["spatial_structure", "historical_layers", "theme_tracks"]
    term_checks = _term_status(dossier_text, required_terms)
    section_checks = {section: f"## {section}" in dossier_text for section in required_sections}
    axis_checks = {
        "religion_book": any(chunk.get("axis") == "religion_book" for chunk in packet.get("chunks", [])),
        "history_book": any(chunk.get("axis") == "history_book" for chunk in packet.get("chunks", [])),
        "art_architecture_book_or_archaeology_book": any(
            chunk.get("axis") in {"art_architecture_book", "archaeology_book"}
            for chunk in packet.get("chunks", [])
        ),
    }
    guard_passed = not violations
    result_enum = "PARTIAL_SOURCE_GUARDED_PASS" if guard_passed else "BLOCKED_GUARD_VIOLATION"
    target_dir.mkdir(parents=True, exist_ok=True)

    audit_trace = {
        "case_id": CASE_ID,
        "mock_audit_output": True,
        "mock_builder_output_observed": "mock_builder_output: true" in dossier_text,
        "audit_adapter_version": "layer1.fail_closed_mock.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_dossier_path": str(raw_path),
        "source_packet_path": str(source_packet_path),
        "handoff_manifest_path": str(handoff_manifest_path),
        "term_checks": term_checks,
        "axis_checks": axis_checks,
        "section_checks": section_checks,
        "quality": "mock_rich_not_formal",
        "quality_pass_for_formal": False,
        "guard_checks": {"passed": guard_passed, "violations": violations},
        "result_enum": result_enum,
        "stop_reasons": ["mock audit output cannot be formal controlled pass"],
        **EXECUTION_FALSE_FLAGS,
    }
    result = {
        "case_id": CASE_ID,
        "mock_audit_output": True,
        "result_enum": result_enum,
        "passed": False,
        "partial": guard_passed,
        "blocked": not guard_passed,
        "quality": "mock_rich_not_formal",
        "term_coverage": term_checks,
        "axis_coverage": axis_checks,
        "section_coverage": section_checks,
        "guard_result": audit_trace["guard_checks"],
        "artifact_paths": {},
        **EXECUTION_FALSE_FLAGS,
    }

    paths = {
        AUDIT_TRACE_FILENAME: target_dir / AUDIT_TRACE_FILENAME,
        ALIAS_GUARD_FILENAME: target_dir / ALIAS_GUARD_FILENAME,
        CONTAMINATION_FILENAME: target_dir / CONTAMINATION_FILENAME,
        SUMMARY_FILENAME: target_dir / SUMMARY_FILENAME,
        RESULT_FILENAME: target_dir / RESULT_FILENAME,
    }
    paths[AUDIT_TRACE_FILENAME].write_text(json.dumps(audit_trace, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths[ALIAS_GUARD_FILENAME].write_text(
        "# rel_space_029 alias/source guard report\n\n"
        "mock_audit_output: true\n\n"
        f"status: {'PASS' if guard_passed else 'FAIL'}\n\n"
        f"violations: {violations}\n",
        encoding="utf-8",
    )
    paths[CONTAMINATION_FILENAME].write_text(
        "# rel_space_029 contamination check\n\n"
        "mock_audit_output: true\n\n"
        f"listing_or_travel_planning_leakage: {'false' if guard_passed else 'true'}\n"
        f"violations: {violations}\n",
        encoding="utf-8",
    )
    paths[SUMMARY_FILENAME].write_text(
        "# rel_space_029 controlled execution summary\n\n"
        "mock_audit_output: true\n\n"
        f"result_enum: {result_enum}\n\n"
        "This is not a formal controlled regression pass.\n",
        encoding="utf-8",
    )
    result["artifact_paths"] = {name: str(path) for name, path in paths.items()}
    paths[RESULT_FILENAME].write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "MOCK_AUDIT_OUTPUT_WRITTEN", "result": result, "artifact_paths": result["artifact_paths"]}
