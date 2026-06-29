#!/usr/bin/env python3
"""Dry-run validator for candidate Topic Refinement outputs.

This utility checks a routed state and candidate refinement directory. It does
not generate a revised final, call an LLM, rerun a pipeline, perform evidence
acquisition, or register any runtime task mode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PASS_STATUS = "PASS_REFINEMENT_OUTPUT_VALIDATION"
VALIDATOR_VERSION = "slice3.0"
REPORT_FILENAME = "refinement_output_validation_report.json"

BLOCKED_ROUTED_STATE_MISSING = "BLOCKED_ROUTED_STATE_MISSING"
BLOCKED_INVALID_ROUTED_STATE = "BLOCKED_INVALID_ROUTED_STATE"
BLOCKED_REFINEMENT_DIR_MISSING = "BLOCKED_REFINEMENT_DIR_MISSING"
BLOCKED_OUTPUT_ALREADY_EXISTS = "BLOCKED_OUTPUT_ALREADY_EXISTS"
BLOCKED_FINAL_V1_OVERWRITTEN = "BLOCKED_FINAL_V1_OVERWRITTEN"
BLOCKED_REVISED_FINAL_NOT_ALLOWED = "BLOCKED_REVISED_FINAL_NOT_ALLOWED"
BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT = "BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT"
BLOCKED_FALSE_FULL_TEXT_VERIFICATION_CLAIM = "BLOCKED_FALSE_FULL_TEXT_VERIFICATION_CLAIM"
BLOCKED_CONFIDENCE_UPGRADE_WITHOUT_NEW_EVIDENCE = "BLOCKED_CONFIDENCE_UPGRADE_WITHOUT_NEW_EVIDENCE"
BLOCKED_EVIDENCE_ACQUISITION_CLAIM = "BLOCKED_EVIDENCE_ACQUISITION_CLAIM"
BLOCKED_FULL_RERUN_CLAIM = "BLOCKED_FULL_RERUN_CLAIM"
BLOCKED_RUNTIME_INTEGRATION_CLAIM = "BLOCKED_RUNTIME_INTEGRATION_CLAIM"

ALLOWED_MODES = {
    "environment_triage",
    "targeted_evidence_acquisition",
    "final_absorption_pass",
    "section_rewrite",
    "user_feedback_refinement",
    None,
}
REVISED_FILES = ("revised_final_v2.md", "refined_sections_v2.md")
STOP_FILES = ("refinement_stop_or_source_need.md", "no_actionable_refinement_report.md")
BOUNDARY_WORDS = ("caveat", "limitation", "uncertainty", "conditional", "plausible", "speculative")
SOURCE_NEED_WORDS = ("source_need", "full-text verification", "needed sources", "verification required")
FULL_TEXT_FALSE_PATTERNS = (
    "full_text_verified: true",
    "full-text verification completed",
    "full text verification completed",
    "full-text verified",
)
EVIDENCE_ACQUISITION_PATTERNS = (
    "evidence acquisition completed",
    "source acquisition completed",
    "new evidence acquired",
    "full text retrieved",
)
FULL_RERUN_PATTERNS = (
    "full rerun completed",
    "pipeline rerun completed",
    "reran pipeline",
    "full pipeline rerun",
    "full rerun",
)
RUNTIME_INTEGRATION_PATTERNS = (
    "runtime integration completed",
    "runtime integration is complete",
    "task mode registered",
    "registered task mode",
    "pipeline wiring updated",
    "automatic invocation completed",
)
CONFIDENCE_UPGRADE_RE = re.compile(r"\b(confidence upgraded|confidence increased|now confirmed|is confirmed|confirmed|proven)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ValidatorResult:
    status: str
    exit_code: int
    output_dir: Path | None = None
    report_json_path: Path | None = None
    report_md_path: Path | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _is_output_dir_allowed(output_dir: Path) -> bool:
    resolved = output_dir.resolve(strict=False)
    repo_outputs = (_repo_root() / "outputs").resolve(strict=False)
    if _is_relative_to(resolved, repo_outputs):
        return True
    temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
    if _is_relative_to(resolved, temp_root):
        return True
    return _is_relative_to(resolved, Path("/private/tmp").resolve(strict=False)) or _is_relative_to(
        resolved, Path("/private/var").resolve(strict=False)
    )


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _resolve_repo_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return _repo_root() / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_report_md(path: Path, title: str, payload: dict[str, Any]) -> None:
    lines = [f"# {title}", ""]
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            lines.extend([f"## {key}", "", "```json", json.dumps(value, indent=2, ensure_ascii=False), "```", ""])
        else:
            lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _blocked(status: str, output_dir: Path, reason: str, *, routed_state_path: Path | None = None) -> ValidatorResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "generated_at_utc": _utc_now(),
        "routed_state_path": str(routed_state_path) if routed_state_path is not None else None,
        "output_dir": str(output_dir),
        "reason": reason,
        "pass_or_fail": "fail",
        "no_runtime_integration_check": False if status == BLOCKED_RUNTIME_INTEGRATION_CLAIM else True,
        "no_llm_called": True,
        "no_pipeline_rerun": False if status == BLOCKED_FULL_RERUN_CLAIM else True,
    }
    json_path = output_dir / "refinement_output_validation_blocked_report.json"
    md_path = output_dir / "refinement_output_validation_blocked_report.md"
    _write_json(json_path, payload)
    _write_report_md(md_path, "Topic Refinement Output Validation Blocked Report", payload)
    return ValidatorResult(status, 2, output_dir, json_path, md_path)


def _load_state(routed_state_path: Path, output_dir: Path) -> tuple[dict[str, Any] | None, ValidatorResult | None]:
    if (output_dir / REPORT_FILENAME).exists() or (output_dir / "refinement_output_validation_blocked_report.json").exists():
        return None, _blocked(BLOCKED_OUTPUT_ALREADY_EXISTS, output_dir, "validator output already exists", routed_state_path=routed_state_path)
    if not routed_state_path.exists():
        return None, _blocked(BLOCKED_ROUTED_STATE_MISSING, output_dir, "routed state file missing", routed_state_path=routed_state_path)
    try:
        state = json.loads(routed_state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, _blocked(BLOCKED_INVALID_ROUTED_STATE, output_dir, "routed state is invalid JSON", routed_state_path=routed_state_path)
    if state.get("state_type") != "topic_refinement_state_routed":
        return None, _blocked(BLOCKED_INVALID_ROUTED_STATE, output_dir, "state_type must be topic_refinement_state_routed", routed_state_path=routed_state_path)
    mode = state.get("selected_refinement_mode")
    if mode not in ALLOWED_MODES:
        return None, _blocked(BLOCKED_INVALID_ROUTED_STATE, output_dir, "selected_refinement_mode is not allowed", routed_state_path=routed_state_path)
    if state.get("selected_failure_type") is None and state.get("next_action") != "stop_no_actionable_refinement":
        return None, _blocked(BLOCKED_INVALID_ROUTED_STATE, output_dir, "selected_failure_type required unless stop_no_actionable_refinement", routed_state_path=routed_state_path)
    if not (state.get("no_runtime_integration") is True and state.get("no_llm_called") is True and state.get("no_pipeline_rerun") is True):
        return None, _blocked(BLOCKED_INVALID_ROUTED_STATE, output_dir, "runtime dry-run flags must be true", routed_state_path=routed_state_path)
    if not (state.get("no_final_rewritten") is True and state.get("no_evidence_acquisition_performed") is True):
        return None, _blocked(BLOCKED_INVALID_ROUTED_STATE, output_dir, "router must not rewrite final or acquire evidence", routed_state_path=routed_state_path)
    final_entry = _final_v1_entry(state)
    current_final = _resolve_repo_path(state.get("current_final_version_path"))
    final_path = _resolve_repo_path(final_entry.get("path") if final_entry else None)
    if final_entry is None or current_final is None or final_path is None or not current_final.exists() or not final_path.exists():
        return None, _blocked(BLOCKED_INVALID_ROUTED_STATE, output_dir, "final_v1 is missing", routed_state_path=routed_state_path)
    return state, None


def _final_v1_entry(state: dict[str, Any]) -> dict[str, Any] | None:
    versions = state.get("final_versions")
    if isinstance(versions, dict):
        entry = versions.get("final_v1")
        return entry if isinstance(entry, dict) else None
    if isinstance(versions, list):
        for entry in versions:
            if isinstance(entry, dict) and entry.get("version") == "final_v1":
                return entry
    return None


def _candidate_files(refinement_dir: Path) -> list[Path]:
    return sorted([p for p in refinement_dir.rglob("*") if p.is_file()], key=lambda p: p.as_posix())


def _read_candidate_text(files: list[Path]) -> str:
    parts = []
    for path in files:
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def _has_file(refinement_dir: Path, name: str) -> bool:
    return (refinement_dir / name).exists()


def _has_any_file(refinement_dir: Path, names: tuple[str, ...]) -> bool:
    return any(_has_file(refinement_dir, name) for name in names)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(token.lower() in lower for token in tokens)


def _new_evidence_declared(text: str) -> bool:
    lower = text.lower()
    return any(token in lower for token in ("new_evidence: yes", "new evidence: yes", "new_evidence: true", "new evidence: true"))


def _final_hash_check(state: dict[str, Any]) -> dict[str, Any]:
    final_entry = _final_v1_entry(state)
    final_path = _resolve_repo_path(final_entry.get("path") if final_entry else None)
    expected = None
    if isinstance(final_entry, dict):
        expected = final_entry.get("sha256")
    if expected is None:
        expected = (state.get("artifact_hashes") or {}).get("final_v1")
    actual = _sha256(final_path) if final_path is not None and final_path.exists() else None
    return {"path": str(final_path) if final_path else None, "expected_sha256": expected, "actual_sha256": actual, "pass": expected is None or expected == actual}


def _validate_common_claims(text: str, refinement_dir: Path, state: dict[str, Any], output_dir: Path, routed_state_path: Path) -> ValidatorResult | None:
    if _contains_any(text, RUNTIME_INTEGRATION_PATTERNS):
        return _blocked(BLOCKED_RUNTIME_INTEGRATION_CLAIM, output_dir, "candidate claims runtime integration", routed_state_path=routed_state_path)
    if _contains_any(text, FULL_RERUN_PATTERNS):
        return _blocked(BLOCKED_FULL_RERUN_CLAIM, output_dir, "candidate claims full rerun or pipeline rerun", routed_state_path=routed_state_path)
    if _has_file(refinement_dir, "evidence_acquisition_result.md") or _contains_any(text, EVIDENCE_ACQUISITION_PATTERNS):
        return _blocked(BLOCKED_EVIDENCE_ACQUISITION_CLAIM, output_dir, "candidate claims evidence acquisition", routed_state_path=routed_state_path)
    if _contains_any(text, FULL_TEXT_FALSE_PATTERNS):
        return _blocked(BLOCKED_FALSE_FULL_TEXT_VERIFICATION_CLAIM, output_dir, "candidate claims full-text verification", routed_state_path=routed_state_path)
    if CONFIDENCE_UPGRADE_RE.search(text) and not _new_evidence_declared(text):
        return _blocked(BLOCKED_CONFIDENCE_UPGRADE_WITHOUT_NEW_EVIDENCE, output_dir, "candidate upgrades confidence without new evidence", routed_state_path=routed_state_path)
    hash_check = _final_hash_check(state)
    if not hash_check["pass"]:
        return _blocked(BLOCKED_FINAL_V1_OVERWRITTEN, output_dir, "final_v1 hash changed", routed_state_path=routed_state_path)
    return None


def _validate_mode(state: dict[str, Any], refinement_dir: Path, text: str, output_dir: Path, routed_state_path: Path) -> ValidatorResult | None:
    mode = state.get("selected_refinement_mode")
    next_action = state.get("next_action")
    has_revised = _has_any_file(refinement_dir, REVISED_FILES)
    has_traceability = _has_file(refinement_dir, "changed_unchanged_traceability.md")
    has_stop = _has_file(refinement_dir, "refinement_stop_or_source_need.md")
    lower = text.lower()

    if mode == "environment_triage":
        if has_revised:
            return _blocked(BLOCKED_REVISED_FINAL_NOT_ALLOWED, output_dir, "environment triage cannot include answer rewrite", routed_state_path=routed_state_path)
        if not (_has_file(refinement_dir, "environment_triage_report.md") or has_stop):
            return _blocked(BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT, output_dir, "environment triage report required", routed_state_path=routed_state_path)
        return None

    if mode == "targeted_evidence_acquisition":
        if next_action == "source_need_or_full_text_verification":
            if has_revised:
                return _blocked(BLOCKED_REVISED_FINAL_NOT_ALLOWED, output_dir, "source-need stop cannot include revised final", routed_state_path=routed_state_path)
            if not has_stop:
                return _blocked(BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT, output_dir, "refinement_stop_or_source_need.md required", routed_state_path=routed_state_path)
            if not _contains_any(text, SOURCE_NEED_WORDS):
                return _blocked(BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT, output_dir, "source need or verification language required", routed_state_path=routed_state_path)
        elif next_action == "ready_for_authorized_source_acquisition_dry_run":
            if has_revised:
                return _blocked(BLOCKED_REVISED_FINAL_NOT_ALLOWED, output_dir, "authorized source-acquisition dry run still cannot include revised final", routed_state_path=routed_state_path)
            if not (_has_file(refinement_dir, "source_acquisition_plan.md") or has_stop):
                return _blocked(BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT, output_dir, "source acquisition plan or stop report required", routed_state_path=routed_state_path)
        return None

    if mode == "final_absorption_pass":
        if not has_revised or not has_traceability:
            return _blocked(BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT, output_dir, "revised/refined output and traceability required", routed_state_path=routed_state_path)
        needs_boundary = bool(state.get("preserved_caveats") or state.get("unresolved_evidence_gaps"))
        if needs_boundary and not _contains_any(text, BOUNDARY_WORDS):
            return _blocked(BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT, output_dir, "boundary language required when caveats/gaps exist", routed_state_path=routed_state_path)
        return None

    if mode in {"section_rewrite", "user_feedback_refinement"}:
        if not has_revised or not has_traceability:
            return _blocked(BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT, output_dir, "rewrite output and traceability required", routed_state_path=routed_state_path)
        traceability = (refinement_dir / "changed_unchanged_traceability.md").read_text(encoding="utf-8", errors="replace").lower()
        if "changed_sections" not in traceability or "what_was_not_changed" not in traceability:
            return _blocked(BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT, output_dir, "traceability must include changed_sections and what_was_not_changed", routed_state_path=routed_state_path)
        if bool(state.get("preserved_caveats") or state.get("unresolved_evidence_gaps")) and "caveat" not in lower:
            return _blocked(BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT, output_dir, "caveat boundary must be preserved", routed_state_path=routed_state_path)
        return None

    if mode is None or next_action == "stop_no_actionable_refinement":
        if _has_file(refinement_dir, "revised_final_v2.md"):
            return _blocked(BLOCKED_REVISED_FINAL_NOT_ALLOWED, output_dir, "no-action route cannot include revised final", routed_state_path=routed_state_path)
        if not (has_stop or _has_file(refinement_dir, "no_actionable_refinement_report.md")):
            return _blocked(BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT, output_dir, "stop/no-action report required", routed_state_path=routed_state_path)
        return None

    return _blocked(BLOCKED_INVALID_ROUTED_STATE, output_dir, "unsupported validation mode", routed_state_path=routed_state_path)


def validate_output(*, routed_state_path: Path, refinement_dir: Path, output_dir: Path, strict: bool = True) -> ValidatorResult:
    del strict
    if not _is_output_dir_allowed(output_dir):
        output_dir = output_dir if output_dir.is_absolute() else Path(tempfile.gettempdir()) / "topic_refinement_validator_invalid_output"
        return _blocked(BLOCKED_OUTPUT_ALREADY_EXISTS, output_dir, "output_dir must be under outputs/ or temp", routed_state_path=routed_state_path)
    state, blocked = _load_state(routed_state_path, output_dir)
    if blocked is not None:
        return blocked
    assert state is not None
    if not refinement_dir.exists() or not refinement_dir.is_dir():
        return _blocked(BLOCKED_REFINEMENT_DIR_MISSING, output_dir, "candidate refinement dir missing", routed_state_path=routed_state_path)
    candidate_files = _candidate_files(refinement_dir)
    text = _read_candidate_text(candidate_files)
    common_blocked = _validate_common_claims(text, refinement_dir, state, output_dir, routed_state_path)
    if common_blocked is not None:
        return common_blocked
    mode_blocked = _validate_mode(state, refinement_dir, text, output_dir, routed_state_path)
    if mode_blocked is not None:
        return mode_blocked

    output_dir.mkdir(parents=True, exist_ok=True)
    hash_check = _final_hash_check(state)
    report = {
        "status": PASS_STATUS,
        "validator_version": VALIDATOR_VERSION,
        "generated_at_utc": _utc_now(),
        "selected_failure_type": state.get("selected_failure_type"),
        "selected_refinement_mode": state.get("selected_refinement_mode"),
        "validation_mode": state.get("selected_refinement_mode") or state.get("next_action"),
        "candidate_files_reviewed": [str(path) for path in candidate_files],
        "final_v1_overwrite_check": hash_check,
        "append_only_check": {"pass": True, "final_v1_path_preserved": hash_check.get("path")},
        "changed_unchanged_traceability_check": {"pass": _has_file(refinement_dir, "changed_unchanged_traceability.md") or state.get("selected_refinement_mode") in {"environment_triage", "targeted_evidence_acquisition", None}},
        "confidence_boundary_check": {"pass": not (CONFIDENCE_UPGRADE_RE.search(text) and not _new_evidence_declared(text))},
        "caveat_preservation_check": {"pass": True, "required": bool(state.get("preserved_caveats") or state.get("unresolved_evidence_gaps"))},
        "no_false_full_text_verification_check": {"pass": not _contains_any(text, FULL_TEXT_FALSE_PATTERNS)},
        "no_evidence_acquisition_performed_check": {"pass": not (_has_file(refinement_dir, "evidence_acquisition_result.md") or _contains_any(text, EVIDENCE_ACQUISITION_PATTERNS))},
        "no_full_rerun_check": {"pass": not _contains_any(text, FULL_RERUN_PATTERNS)},
        "no_runtime_integration_check": {"pass": not _contains_any(text, RUNTIME_INTEGRATION_PATTERNS)},
        "pass_or_fail": "pass",
        "next_action": "validator_passed_ready_for_operator_review",
    }
    report_json = output_dir / REPORT_FILENAME
    report_md = output_dir / "refinement_output_validation_report.md"
    _write_json(report_json, report)
    _write_report_md(report_md, "Topic Refinement Output Validation Report", report)
    return ValidatorResult(PASS_STATUS, 0, output_dir, report_json, report_md)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run validator for Topic Refinement candidate outputs.")
    parser.add_argument("--routed-state", required=True, type=Path)
    parser.add_argument("--refinement-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--strict", type=_parse_bool, default=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_output(
        routed_state_path=args.routed_state,
        refinement_dir=args.refinement_dir,
        output_dir=args.output_dir,
        strict=args.strict,
    )
    print(result.status)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
