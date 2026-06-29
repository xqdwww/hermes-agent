#!/usr/bin/env python3
"""Deterministic dry-run router for Topic Refinement Loop state.

This utility reads a Slice 1 initial state and writes a routed state. It does
not call an LLM, rerun a pipeline, perform evidence acquisition, rewrite a
final, or register any runtime task mode.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROUTER_VERSION = "slice2.0"
ROUTED_STATE_FILENAME = "topic_refinement_state.routed.json"
PASS_STATUS = "PASS_MODE_ROUTER_DRY_RUN"

BLOCKED_STATE_FILE_MISSING = "BLOCKED_STATE_FILE_MISSING"
BLOCKED_INVALID_JSON = "BLOCKED_INVALID_JSON"
BLOCKED_INVALID_STATE_TYPE = "BLOCKED_INVALID_STATE_TYPE"
BLOCKED_INVALID_NEXT_ACTION = "BLOCKED_INVALID_NEXT_ACTION"
BLOCKED_ALREADY_ROUTED = "BLOCKED_ALREADY_ROUTED"
BLOCKED_MISSING_REQUIRED_FIELD = "BLOCKED_MISSING_REQUIRED_FIELD"
BLOCKED_FINAL_V1_MISSING = "BLOCKED_FINAL_V1_MISSING"
BLOCKED_RUNTIME_FLAG_MISMATCH = "BLOCKED_RUNTIME_FLAG_MISMATCH"
BLOCKED_OUTPUT_ALREADY_EXISTS = "BLOCKED_OUTPUT_ALREADY_EXISTS"
BLOCKED_INVALID_OUTPUT_DIR = "BLOCKED_INVALID_OUTPUT_DIR"

REQUIRED_FIELDS = (
    "schema_version",
    "state_type",
    "topic_id",
    "original_question",
    "current_final_version",
    "current_final_version_path",
    "artifact_paths",
    "user_feedback",
    "detected_quality_signals",
    "detected_evidence_boundary_signals",
    "detected_calibration_boundary_signals",
    "detected_environment_signals",
    "authorization",
    "preserved_caveats",
    "unresolved_evidence_gaps",
    "final_versions",
    "refinement_history",
    "next_action",
    "no_runtime_integration",
    "no_llm_called",
    "no_pipeline_rerun",
)

ENVIRONMENT_TOKENS = (
    "executor_resource_exhausted",
    "blocked_executor_unavailable",
    "ddgs missing",
    "modulenotfounderror",
    "omlx",
    "service unhealthy",
    "environment blocker",
    "evidence_judge resource",
)

CERTAINTY_REQUEST_TOKENS = (
    "更确定",
    "更强",
    "强结论",
    "更明确",
    "有结论",
    "写得更确定",
    "more certain",
    "stronger conclusion",
    "stronger claim",
    "confidence upgraded",
    "confidence increased",
    "confirmed",
    "proven",
)

DEEPER_FEEDBACK_TOKENS = (
    "不够具体",
    "做实",
    "继续这个话题",
    "重写第",
    "只补",
    "deeper",
    "more specific",
)

EVIDENCE_STOP_SIGNALS = {"full-text verification", "snippet", "weak evidence", "evidence gap", "unsupported"}
CALIBRATION_SIGNALS = {"overclaim", "confidence down", "speculative", "caveat", "plausible", "unsupported"}
QUALITY_SIGNALS = {"convergence not absorbed", "final too generic", "template", "low specificity"}
ALLOWED_MODES = {
    "environment_triage",
    "targeted_evidence_acquisition",
    "final_absorption_pass",
    "section_rewrite",
    "user_feedback_refinement",
}


@dataclass(frozen=True)
class RouterResult:
    status: str
    exit_code: int
    output_dir: Path | None = None
    routed_state_path: Path | None = None
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


def _blocked(
    status: str,
    output_dir: Path,
    reason: str,
    *,
    input_state_path: Path | None = None,
    write_report: bool = True,
) -> RouterResult:
    payload = {
        "status": status,
        "generated_at_utc": _utc_now(),
        "input_state_path": str(input_state_path) if input_state_path is not None else None,
        "output_dir": str(output_dir),
        "reason": reason,
        "selected_failure_type": None,
        "selected_refinement_mode": None,
        "no_llm_called": True,
        "no_pipeline_rerun": True,
        "no_final_rewritten": True,
        "no_evidence_acquisition_performed": True,
    }
    if write_report:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "mode_router_blocked_report.json"
        md_path = output_dir / "mode_router_blocked_report.md"
        _write_json(json_path, payload)
        _write_report_md(md_path, "Topic Refinement Mode Router Blocked Report", payload)
        return RouterResult(status=status, exit_code=2, output_dir=output_dir, report_json_path=json_path, report_md_path=md_path)
    sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return RouterResult(status=status, exit_code=2)


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_flatten(item) for pair in value.items() for item in pair)
    if isinstance(value, list):
        return "\n".join(_flatten(item) for item in value)
    return str(value)


def _lower_set(values: Any) -> set[str]:
    return {item.strip().lower() for item in _flatten(values).splitlines() if item.strip()}


def _contains_any(text: str, tokens: tuple[str, ...] | set[str]) -> bool:
    lower = text.lower()
    return any(token.lower() in lower for token in tokens)


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


def _validate_state(state_path: Path, output_dir: Path) -> tuple[dict[str, Any] | None, RouterResult | None]:
    if not _is_output_dir_allowed(output_dir):
        return None, _blocked(BLOCKED_INVALID_OUTPUT_DIR, output_dir, "output_dir must be under outputs/ or a temp directory", input_state_path=state_path, write_report=False)
    if (output_dir / ROUTED_STATE_FILENAME).exists():
        return None, _blocked(BLOCKED_OUTPUT_ALREADY_EXISTS, output_dir, f"{ROUTED_STATE_FILENAME} already exists", input_state_path=state_path)
    if not state_path.exists():
        return None, _blocked(BLOCKED_STATE_FILE_MISSING, output_dir, "state file missing", input_state_path=state_path)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, _blocked(BLOCKED_INVALID_JSON, output_dir, "state file is not valid JSON", input_state_path=state_path)
    if state.get("state_type") != "topic_refinement_state_initial":
        return None, _blocked(BLOCKED_INVALID_STATE_TYPE, output_dir, "state_type must be topic_refinement_state_initial", input_state_path=state_path)
    missing = [field for field in REQUIRED_FIELDS if field not in state]
    if missing:
        return None, _blocked(BLOCKED_MISSING_REQUIRED_FIELD, output_dir, f"missing required fields: {missing}", input_state_path=state_path)
    if state.get("next_action") != "needs_mode_router":
        return None, _blocked(BLOCKED_INVALID_NEXT_ACTION, output_dir, "next_action must be needs_mode_router", input_state_path=state_path)
    if state.get("selected_failure_type") is not None or state.get("selected_refinement_mode") is not None:
        return None, _blocked(BLOCKED_ALREADY_ROUTED, output_dir, "state already contains routing selection", input_state_path=state_path)
    if not (state.get("no_runtime_integration") is True and state.get("no_llm_called") is True and state.get("no_pipeline_rerun") is True):
        return None, _blocked(BLOCKED_RUNTIME_FLAG_MISMATCH, output_dir, "runtime/LLM/pipeline dry-run flags must all be true", input_state_path=state_path)
    current_final = _resolve_repo_path(state.get("current_final_version_path"))
    final_entry = _final_v1_entry(state)
    final_v1_path = _resolve_repo_path(final_entry.get("path") if final_entry else None)
    if current_final is None or not current_final.exists() or final_v1_path is None or not final_v1_path.exists():
        return None, _blocked(BLOCKED_FINAL_V1_MISSING, output_dir, "current final_v1 path is missing", input_state_path=state_path)
    return state, None


def route_state(state: dict[str, Any], input_state_path: Path) -> dict[str, Any]:
    quality = _lower_set(state.get("detected_quality_signals"))
    evidence = _lower_set(state.get("detected_evidence_boundary_signals"))
    calibration = _lower_set(state.get("detected_calibration_boundary_signals"))
    env_text = _flatten(state.get("detected_environment_signals"))
    user_feedback = str(state.get("user_feedback", ""))
    combined_text = "\n".join([
        _flatten(state.get("detected_environment_signals")),
        _flatten(state.get("detected_evidence_boundary_signals")),
        _flatten(state.get("detected_calibration_boundary_signals")),
        _flatten(state.get("detected_quality_signals")),
        _flatten(state.get("preserved_caveats")),
        _flatten(state.get("unresolved_evidence_gaps")),
        user_feedback,
    ])
    authorization = state.get("authorization") if isinstance(state.get("authorization"), dict) else {}
    authorized = bool(authorization.get("allow_source_acquisition") or authorization.get("allow_full_text_verification"))

    selected_failure_type = None
    selected_refinement_mode = None
    routing_priority = 5
    stop_reason = "no_actionable_refinement_signal"
    next_action = "stop_no_actionable_refinement"
    reason = "No deterministic refinement signal found."
    warnings: list[str] = []

    if state.get("detected_environment_signals") or _contains_any(env_text, ENVIRONMENT_TOKENS) or _contains_any(combined_text, ENVIRONMENT_TOKENS):
        selected_failure_type = "executor_or_environment_blocker"
        selected_refinement_mode = "environment_triage"
        routing_priority = 0
        stop_reason = "environment_or_runtime_blocker_detected"
        next_action = "environment_triage_required"
        reason = "Priority 0: environment/runtime blocker signal outranks answer-quality refinement."
    else:
        evidence_boundary = bool(evidence & EVIDENCE_STOP_SIGNALS) or _contains_any(combined_text, tuple(EVIDENCE_STOP_SIGNALS))
        certainty_request = _contains_any(user_feedback, CERTAINTY_REQUEST_TOKENS)
        unsupported_or_speculative = "unsupported" in evidence or "speculative" in evidence or "unsupported" in calibration or "speculative" in calibration
        if evidence_boundary and (certainty_request or unsupported_or_speculative):
            selected_failure_type = (
                "evidence_gap_needs_full_text_verification"
                if ({"full-text verification", "snippet", "evidence gap"} & evidence or _contains_any(combined_text, ("full-text verification", "snippet", "evidence gap")))
                else "thin_evidence_must_remain_conditional"
            )
            selected_refinement_mode = "targeted_evidence_acquisition"
            routing_priority = 1
            stop_reason = "source_or_full_text_verification_required"
            next_action = "ready_for_authorized_source_acquisition_dry_run" if authorized else "source_need_or_full_text_verification"
            reason = "Priority 1: evidence/full-text boundary blocks confidence upgrade or stronger conclusion."
            warnings.append("confidence_upgrade_not_allowed_without_new_evidence")
        elif calibration & CALIBRATION_SIGNALS:
            selected_failure_type = "calibration_absorption_gap"
            selected_refinement_mode = "final_absorption_pass"
            routing_priority = 2
            stop_reason = None
            next_action = "ready_for_final_absorption_pass"
            reason = "Priority 2: calibration boundary should be absorbed before generic rewrite."
        elif quality & QUALITY_SIGNALS:
            if "convergence not absorbed" in quality:
                selected_failure_type = "convergence_to_final_specificity_loss"
            elif "template" in quality:
                selected_failure_type = "final_template_fallback"
            else:
                selected_failure_type = "low_domain_specificity"
            selected_refinement_mode = "final_absorption_pass" if ("convergence not absorbed" in quality or calibration) else "section_rewrite"
            routing_priority = 3
            stop_reason = None
            next_action = "ready_for_refinement"
            reason = "Priority 3: quality signals require targeted rewrite/absorption, not full rerun."
        elif _contains_any(user_feedback, DEEPER_FEEDBACK_TOKENS):
            selected_failure_type = "user_feedback_requests_deeper_specificity"
            selected_refinement_mode = "user_feedback_refinement"
            routing_priority = 4
            stop_reason = None
            next_action = "ready_for_user_feedback_refinement"
            reason = "Priority 4: same-topic user feedback requests deeper specificity."

    routed = dict(state)
    routed.update(
        {
            "state_type": "topic_refinement_state_routed",
            "routed_at_utc": _utc_now(),
            "router_version": ROUTER_VERSION,
            "input_state_path": str(input_state_path),
            "selected_failure_type": selected_failure_type,
            "selected_refinement_mode": selected_refinement_mode,
            "selection_tie_breaker_reason": reason,
            "routing_priority": routing_priority,
            "stop_reason": stop_reason,
            "next_action": next_action,
            "confidence_boundary": state.get("confidence_boundary") or "Confidence cannot increase without new evidence or stronger artifact support.",
            "routing_warnings": warnings,
            "no_runtime_integration": True,
            "no_llm_called": True,
            "no_pipeline_rerun": True,
            "no_final_rewritten": True,
            "no_evidence_acquisition_performed": True,
        }
    )
    return routed


def route_file(*, state_path: Path, output_dir: Path, strict: bool = True) -> RouterResult:
    del strict
    state, blocked = _validate_state(state_path, output_dir)
    if blocked is not None:
        return blocked
    assert state is not None
    output_dir.mkdir(parents=True, exist_ok=True)
    routed = route_state(state, state_path)
    routed_path = output_dir / ROUTED_STATE_FILENAME
    _write_json(routed_path, routed)
    report = {
        "status": PASS_STATUS,
        "generated_at_utc": _utc_now(),
        "topic_id": routed.get("topic_id"),
        "input_state_path": str(state_path),
        "output_state_path": str(routed_path),
        "selected_failure_type": routed.get("selected_failure_type"),
        "selected_refinement_mode": routed.get("selected_refinement_mode"),
        "routing_priority": routed.get("routing_priority"),
        "selection_tie_breaker_reason": routed.get("selection_tie_breaker_reason"),
        "stop_reason": routed.get("stop_reason"),
        "next_action": routed.get("next_action"),
        "authorization_summary": routed.get("authorization", {}),
        "no_llm_called": True,
        "no_pipeline_rerun": True,
        "no_final_rewritten": True,
        "no_evidence_acquisition_performed": True,
    }
    report_json = output_dir / "mode_router_report.json"
    report_md = output_dir / "mode_router_report.md"
    _write_json(report_json, report)
    _write_report_md(report_md, "Topic Refinement Mode Router Report", report)
    return RouterResult(PASS_STATUS, 0, output_dir, routed_path, report_json, report_md)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run router for Topic Refinement Loop initial state.")
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--strict", type=_parse_bool, default=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = route_file(state_path=args.state, output_dir=args.output_dir, strict=args.strict)
    print(result.status)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
