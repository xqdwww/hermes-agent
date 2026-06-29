#!/usr/bin/env python3
"""Report-only post-final Topic Refinement advisory wrapper.

R3E-1 is a manual CLI wrapper around the deterministic R3A detector. It reads
existing run artifacts and emits an operator-facing advisory report. It does not
call the TOPIC_REFINEMENT registry adapter, the manual task wrapper, any LLM,
network/API clients, or the Research/Decision pipeline, and it does not generate
or adopt candidates or rewrite final_v1.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import topic_refinement_post_final_advisory_detector as detector

WRAPPER_VERSION = "r3e1.0"
REPORT_JSON = "post_final_topic_refinement_advisory.json"
REPORT_MD = "post_final_topic_refinement_advisory.md"
BLOCKED_JSON = "post_final_topic_refinement_advisory_blocked.json"
BLOCKED_MD = "post_final_topic_refinement_advisory_blocked.md"
DETECTOR_OUTPUT_DIR = "detector_output"

PASS_REPORT_ONLY_ADVISORY_GENERATED = "PASS_REPORT_ONLY_ADVISORY_GENERATED"
PASS_REPORT_ONLY_NO_REFINEMENT_ADVISED = "PASS_REPORT_ONLY_NO_REFINEMENT_ADVISED"
PASS_REPORT_ONLY_SOURCE_NEED_ADVISED = "PASS_REPORT_ONLY_SOURCE_NEED_ADVISED"
PASS_REPORT_ONLY_ENVIRONMENT_TRIAGE_ADVISED = "PASS_REPORT_ONLY_ENVIRONMENT_TRIAGE_ADVISED"
PASS_REPORT_ONLY_NEW_TASK_ADVISED = "PASS_REPORT_ONLY_NEW_TASK_ADVISED"
BLOCKED_DETECTOR_FAILED = "BLOCKED_DETECTOR_FAILED"
BLOCKED_INVALID_INPUT = "BLOCKED_INVALID_INPUT"
BLOCKED_OUTPUT_ALREADY_EXISTS = "BLOCKED_OUTPUT_ALREADY_EXISTS"

REPORT_ONLY_ADVISORY_READY_FOR_USER_CONFIRMATION = "REPORT_ONLY_ADVISORY_READY_FOR_USER_CONFIRMATION"
REPORT_ONLY_STOP_SOURCE_OR_ENVIRONMENT = "REPORT_ONLY_STOP_SOURCE_OR_ENVIRONMENT"
REPORT_ONLY_NO_ACTION_RECOMMENDED = "REPORT_ONLY_NO_ACTION_RECOMMENDED"
REPORT_ONLY_START_NEW_TASK_INSTEAD = "REPORT_ONLY_START_NEW_TASK_INSTEAD"
REPORT_ONLY_NEEDS_REPAIR = "REPORT_ONLY_NEEDS_REPAIR"

BLOCKED_RUN_DIR_MISSING = "BLOCKED_RUN_DIR_MISSING"
BLOCKED_INVALID_TOPIC_ID = "BLOCKED_INVALID_TOPIC_ID"
BLOCKED_MISSING_REQUIRED_ARTIFACTS = "BLOCKED_MISSING_REQUIRED_ARTIFACTS"
BLOCKED_INVALID_TOPIC_STATE = "BLOCKED_INVALID_TOPIC_STATE"

ALLOWED_STATUSES = {
    PASS_REPORT_ONLY_ADVISORY_GENERATED,
    PASS_REPORT_ONLY_NO_REFINEMENT_ADVISED,
    PASS_REPORT_ONLY_SOURCE_NEED_ADVISED,
    PASS_REPORT_ONLY_ENVIRONMENT_TRIAGE_ADVISED,
    PASS_REPORT_ONLY_NEW_TASK_ADVISED,
    BLOCKED_DETECTOR_FAILED,
    BLOCKED_INVALID_INPUT,
    BLOCKED_OUTPUT_ALREADY_EXISTS,
}

ALLOWED_QUALITY_VERDICTS = {
    REPORT_ONLY_ADVISORY_READY_FOR_USER_CONFIRMATION,
    REPORT_ONLY_STOP_SOURCE_OR_ENVIRONMENT,
    REPORT_ONLY_NO_ACTION_RECOMMENDED,
    REPORT_ONLY_START_NEW_TASK_INSTEAD,
    REPORT_ONLY_NEEDS_REPAIR,
}

ALLOWED_BLOCKED_STATUSES = {
    BLOCKED_RUN_DIR_MISSING,
    BLOCKED_INVALID_TOPIC_ID,
    BLOCKED_OUTPUT_ALREADY_EXISTS,
    BLOCKED_DETECTOR_FAILED,
    BLOCKED_MISSING_REQUIRED_ARTIFACTS,
    BLOCKED_INVALID_TOPIC_STATE,
}

CONFIRM_REFINEMENT_QUESTION = "是否基于该 run 显式进入 TOPIC_REFINEMENT？确认只表示允许生成/验证 candidate，不表示自动采纳。"
SOURCE_NEED_QUESTION = "当前需要 source acquisition / full-text verification 授权，不能仅凭现有 artifacts 提升置信度。"
ENVIRONMENT_QUESTION = "当前建议先修复 environment/runtime blocker，再决定是否继续同话题 refinement。"
NEW_TASK_QUESTION = "当前输入更像新任务或 full rerun；请显式启动新任务，而不是进入 TOPIC_REFINEMENT。"
NO_ACTION_QUESTION = "当前没有明确同话题 refinement 建议；无需确认。"
INSUFFICIENT_QUESTION = "当前 artifacts 不足，不能可靠判断是否进入 TOPIC_REFINEMENT。"


@dataclass(frozen=True)
class ReportOnlyResult:
    status: str
    exit_code: int
    output_dir: Path
    report_json_path: Path
    report_md_path: Path
    payload: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_bool(value: str) -> bool:
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"expected true/false, got {value!r}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_md(path: Path, title: str, payload: dict[str, Any]) -> None:
    lines = [f"# {title}", ""]
    lines.extend(
        [
            f"- status: {payload.get('status')}",
            f"- quality_verdict: {payload.get('quality_verdict')}",
            f"- advisory_display_status: {payload.get('advisory_display_status')}",
            f"- suggested_next_action: {payload.get('suggested_next_action')}",
            f"- user_confirmation_required: {payload.get('user_confirmation_required')}",
            "",
            "## Operator Guidance",
            "",
            str(payload.get("operator_guidance") or ""),
            "",
            "## User Confirmation Boundary",
            "",
            str(payload.get("user_confirmation_question") or ""),
            "",
            "User confirmation does not mean adoption. It only permits explicit candidate generation or validation, and any candidate still requires validator pass plus a separate user adoption decision.",
            "",
            "## Safety Guarantees",
            "",
            "- no automatic execution",
            "- no TOPIC_REFINEMENT adapter call",
            "- no manual task wrapper call",
            "- no LLM call",
            "- no pipeline rerun",
            "- no candidate generation",
            "- no final rewrite",
            "",
            "## Explicit Follow-Up Command Template",
            "",
            "```bash",
            str(payload.get("recommended_followup_command") or "# no follow-up command recommended"),
            "```",
            "",
            "This command is a template only and was not executed by this report-only wrapper.",
            "",
            "## Boundary Summaries",
            "",
            f"- evidence_boundary_summary: {payload.get('evidence_boundary_summary')}",
            f"- calibration_boundary_summary: {payload.get('calibration_boundary_summary')}",
            "",
            "## Disallowed Interpretations",
            "",
        ]
    )
    for item in payload.get("disallowed_interpretations", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Remaining Risks", ""])
    for item in payload.get("remaining_risks", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Detector Result", "", "```json", json.dumps(payload.get("detector_result", {}), indent=2, ensure_ascii=False), "```", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _blocked_md(path: Path, payload: dict[str, Any]) -> None:
    lines = ["# Post-Final Topic Refinement Advisory Blocked", ""]
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            lines.extend([f"## {key}", "", "```json", json.dumps(value, indent=2, ensure_ascii=False), "```", ""])
        else:
            lines.append(f"- {key}: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _blocked(output_dir: Path, status: str, reason: str, *, run_dir: Path | None = None, topic_id: str | None = None, detector_payload: dict[str, Any] | None = None) -> ReportOnlyResult:
    assert status in ALLOWED_BLOCKED_STATUSES
    payload: dict[str, Any] = {
        "status": status,
        "quality_verdict": REPORT_ONLY_NEEDS_REPAIR,
        "wrapper_version": WRAPPER_VERSION,
        "generated_at_utc": _utc_now(),
        "topic_id": topic_id,
        "run_dir": str(run_dir) if run_dir is not None else None,
        "reason": reason,
        "detector_result": detector_payload or {},
        "auto_execution": False,
        "auto_adoption": False,
        "no_adapter_called": True,
        "no_manual_task_called": True,
        "no_llm_called": True,
        "no_pipeline_rerun": True,
        "no_candidate_generated": True,
        "no_final_rewritten": True,
    }
    json_path = output_dir / BLOCKED_JSON
    md_path = output_dir / BLOCKED_MD
    _write_json(json_path, payload)
    _blocked_md(md_path, payload)
    return ReportOnlyResult(status=status, exit_code=2, output_dir=output_dir, report_json_path=json_path, report_md_path=md_path, payload=payload)


def _output_collision(output_dir: Path) -> bool:
    detector_dir = output_dir / DETECTOR_OUTPUT_DIR
    paths = [
        output_dir / REPORT_JSON,
        output_dir / REPORT_MD,
        output_dir / BLOCKED_JSON,
        output_dir / BLOCKED_MD,
        detector_dir / detector.REPORT_JSON,
        detector_dir / detector.REPORT_MD,
        detector_dir / detector.BLOCKED_JSON,
        detector_dir / detector.BLOCKED_MD,
    ]
    return any(path.exists() for path in paths)


def _map_detector_blocked_status(detector_status: str | None) -> str:
    if detector_status == detector.BLOCKED_RUN_DIR_MISSING:
        return BLOCKED_RUN_DIR_MISSING
    if detector_status == detector.BLOCKED_INVALID_TOPIC_ID:
        return BLOCKED_INVALID_TOPIC_ID
    if detector_status in {detector.BLOCKED_MISSING_FINAL_V1, detector.BLOCKED_MISSING_QUALITY_REVIEW}:
        return BLOCKED_MISSING_REQUIRED_ARTIFACTS
    if detector_status in {detector.BLOCKED_INVALID_TOPIC_STATE, detector.BLOCKED_TOPIC_STATE_RUN_DIR_MISMATCH}:
        return BLOCKED_INVALID_TOPIC_STATE
    if detector_status == detector.BLOCKED_OUTPUT_ALREADY_EXISTS:
        return BLOCKED_OUTPUT_ALREADY_EXISTS
    return BLOCKED_DETECTOR_FAILED


def _status_mapping(detector_payload: dict[str, Any]) -> tuple[str, str, str, bool, str, str]:
    advisory_status = detector_payload.get("advisory_status")
    if advisory_status == detector.STATUS_TOPIC_REFINEMENT:
        return (
            PASS_REPORT_ONLY_ADVISORY_GENERATED,
            REPORT_ONLY_ADVISORY_READY_FOR_USER_CONFIRMATION,
            "TOPIC_REFINEMENT can be considered only after explicit user confirmation.",
            True,
            CONFIRM_REFINEMENT_QUESTION,
            "ask_user_to_confirm_explicit_TOPIC_REFINEMENT",
        )
    if advisory_status == detector.STATUS_SOURCE_NEED:
        return (
            PASS_REPORT_ONLY_SOURCE_NEED_ADVISED,
            REPORT_ONLY_STOP_SOURCE_OR_ENVIRONMENT,
            "Stop for source acquisition / full-text verification authorization; do not rewrite from current artifacts.",
            True,
            SOURCE_NEED_QUESTION,
            "ask_user_to_authorize_source_or_full_text_verification",
        )
    if advisory_status == detector.STATUS_ENVIRONMENT:
        return (
            PASS_REPORT_ONLY_ENVIRONMENT_TRIAGE_ADVISED,
            REPORT_ONLY_STOP_SOURCE_OR_ENVIRONMENT,
            "Stop for environment triage before any same-topic refinement.",
            True,
            ENVIRONMENT_QUESTION,
            "ask_user_to_fix_environment",
        )
    if advisory_status == detector.STATUS_NO_REFINEMENT:
        return (
            PASS_REPORT_ONLY_NO_REFINEMENT_ADVISED,
            REPORT_ONLY_NO_ACTION_RECOMMENDED,
            "No deterministic post-final topic refinement signal was found.",
            False,
            NO_ACTION_QUESTION,
            "none",
        )
    if advisory_status == detector.STATUS_NEW_TOPIC:
        return (
            PASS_REPORT_ONLY_NEW_TASK_ADVISED,
            REPORT_ONLY_START_NEW_TASK_INSTEAD,
            "Start a new task or explicitly request a full rerun; do not use TOPIC_REFINEMENT for topic drift.",
            False,
            NEW_TASK_QUESTION,
            "start_new_task",
        )
    if advisory_status == detector.STATUS_INSUFFICIENT:
        return (
            BLOCKED_INVALID_INPUT,
            REPORT_ONLY_NEEDS_REPAIR,
            "Artifacts are insufficient to advise on topic refinement.",
            False,
            INSUFFICIENT_QUESTION,
            "request_missing_artifacts",
        )
    return (
        BLOCKED_DETECTOR_FAILED,
        REPORT_ONLY_NEEDS_REPAIR,
        "Detector returned an unknown advisory status.",
        False,
        INSUFFICIENT_QUESTION,
        "repair_detector_or_input",
    )


def _recommended_followup_command(status: str, run_dir: Path, topic_id: str, output_dir: Path) -> str:
    if status != PASS_REPORT_ONLY_ADVISORY_GENERATED:
        return "# No TOPIC_REFINEMENT command is recommended for this advisory status."
    request_path = output_dir / "explicit_topic_refinement_request.json"
    adapter_out = output_dir / "explicit_topic_refinement_adapter_output"
    return (
        "# First create an explicit request JSON with task_mode=TOPIC_REFINEMENT, confirm_same_topic=true, "
        "user_feedback, run_dir/topic_id, and dry_run=true.\n"
        f"python tools/topic_refinement_registry_adapter.py --request-json {request_path} --output-dir {adapter_out}"
    )


def _allowed_user_responses(status: str) -> list[str]:
    if status == PASS_REPORT_ONLY_ADVISORY_GENERATED:
        return [
            "Confirm explicit TOPIC_REFINEMENT candidate generation/validation for this same topic.",
            "Decline refinement and keep final_v1 unchanged.",
            "Ask for more context before authorizing any candidate work.",
        ]
    if status == PASS_REPORT_ONLY_SOURCE_NEED_ADVISED:
        return [
            "Authorize source acquisition or full-text verification as a separate task.",
            "Keep the current confidence boundary and do not refine.",
        ]
    if status == PASS_REPORT_ONLY_ENVIRONMENT_TRIAGE_ADVISED:
        return ["Fix the environment/runtime blocker first.", "Pause without refinement."]
    if status == PASS_REPORT_ONLY_NEW_TASK_ADVISED:
        return ["Start a new task.", "Explicitly request a full rerun as a separate action."]
    return ["No action.", "Provide additional artifacts and rerun the report-only wrapper."]


def _disallowed_interpretations() -> list[str]:
    return [
        "This report does not execute TOPIC_REFINEMENT.",
        "This report does not call the registry adapter or manual task wrapper.",
        "This report does not call an LLM or semantic evaluator.",
        "This report does not generate a candidate or revised final.",
        "This report does not adopt a candidate or overwrite final_v1.",
        "This report does not prove full-text verification, evidence acquisition, or semantic correctness.",
        "User confirmation to generate or validate a candidate is not candidate adoption.",
    ]


def _remaining_risks(detector_payload: dict[str, Any]) -> list[str]:
    risks = [
        "The detector is deterministic and can miss implicit semantic shallowness.",
        "The report is advisory only and must not be treated as semantic correctness proof.",
        "Any later candidate must pass validator checks and still needs explicit user adoption.",
    ]
    if detector_payload.get("source_need"):
        risks.append("Confidence cannot be upgraded from current artifacts; separate source/full-text authorization is required.")
    if detector_payload.get("environment_triage_needed"):
        risks.append("Environment blockers must be fixed before judging rewrite quality.")
    return risks


def _payload_from_detector(detector_payload: dict[str, Any], *, run_dir: Path, topic_id: str, output_dir: Path) -> dict[str, Any]:
    status, quality_verdict, display_status, confirm_required, question, next_action = _status_mapping(detector_payload)
    assert status in ALLOWED_STATUSES
    assert quality_verdict in ALLOWED_QUALITY_VERDICTS
    return {
        "status": status,
        "quality_verdict": quality_verdict,
        "wrapper_version": WRAPPER_VERSION,
        "generated_at_utc": _utc_now(),
        "topic_id": topic_id,
        "run_dir": str(run_dir),
        "detector_status": detector_payload.get("status", detector_payload.get("advisory_status")),
        "detector_advisory_status": detector_payload.get("advisory_status"),
        "detector_advisory_verdict": detector_payload.get("advisory_verdict"),
        "advisory_display_status": display_status,
        "suggested_next_action": next_action,
        "suggested_refinement_mode": detector_payload.get("suggested_refinement_mode"),
        "user_confirmation_required": confirm_required,
        "user_confirmation_question": question,
        "auto_execution": False,
        "auto_adoption": False,
        "no_adapter_called": True,
        "no_manual_task_called": True,
        "no_llm_called": True,
        "no_pipeline_rerun": True,
        "no_candidate_generated": True,
        "no_final_rewritten": True,
        "allowed_user_responses": _allowed_user_responses(status),
        "disallowed_interpretations": _disallowed_interpretations(),
        "recommended_followup_command": _recommended_followup_command(status, run_dir, topic_id, output_dir),
        "evidence_boundary_summary": detector_payload.get("evidence_boundary_summary"),
        "calibration_boundary_summary": detector_payload.get("calibration_boundary_summary"),
        "operator_guidance": display_status,
        "remaining_risks": _remaining_risks(detector_payload),
        "detector_output_dir": str(output_dir / DETECTOR_OUTPUT_DIR),
        "detector_result": detector_payload,
    }


def generate_post_final_topic_refinement_advisory_report(
    *,
    run_dir: str | Path,
    topic_id: str,
    output_dir: str | Path,
    user_feedback: str = "",
    topic_state: str | Path | None = None,
    strict: bool = True,
) -> ReportOnlyResult:
    resolved_run_dir = Path(run_dir).expanduser().resolve(strict=False)
    resolved_output_dir = Path(output_dir).expanduser().resolve(strict=False)
    resolved_topic_state = Path(topic_state).expanduser().resolve(strict=False) if topic_state is not None else None

    if _output_collision(resolved_output_dir):
        return _blocked(resolved_output_dir, BLOCKED_OUTPUT_ALREADY_EXISTS, "report-only advisory output already exists", run_dir=resolved_run_dir, topic_id=topic_id)
    if not resolved_run_dir.exists() or not resolved_run_dir.is_dir():
        return _blocked(resolved_output_dir, BLOCKED_RUN_DIR_MISSING, "run_dir is missing or is not a directory", run_dir=resolved_run_dir, topic_id=topic_id)
    if not str(topic_id or "").strip():
        return _blocked(resolved_output_dir, BLOCKED_INVALID_TOPIC_ID, "topic_id is required", run_dir=resolved_run_dir, topic_id=topic_id)

    detector_output = resolved_output_dir / DETECTOR_OUTPUT_DIR
    detector_result = detector.analyze_post_final_advisory(
        run_dir=resolved_run_dir,
        topic_id=topic_id,
        output_dir=detector_output,
        topic_state=resolved_topic_state,
        user_feedback=user_feedback,
        strict=strict,
        write_reports=True,
    )
    if detector_result.exit_code != 0:
        blocked_status = _map_detector_blocked_status(detector_result.payload.get("status"))
        return _blocked(
            resolved_output_dir,
            blocked_status,
            "deterministic advisory detector blocked or failed",
            run_dir=resolved_run_dir,
            topic_id=topic_id,
            detector_payload=detector_result.payload,
        )

    payload = _payload_from_detector(detector_result.payload, run_dir=resolved_run_dir, topic_id=topic_id, output_dir=resolved_output_dir)
    json_path = resolved_output_dir / REPORT_JSON
    md_path = resolved_output_dir / REPORT_MD
    _write_json(json_path, payload)
    _write_md(md_path, "Post-Final Topic Refinement Advisory", payload)
    exit_code = 0 if not payload["status"].startswith("BLOCKED_") else 2
    return ReportOnlyResult(status=payload["status"], exit_code=exit_code, output_dir=resolved_output_dir, report_json_path=json_path, report_md_path=md_path, payload=payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a report-only post-final Topic Refinement advisory.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--topic-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--user-feedback", default="")
    parser.add_argument("--topic-state")
    parser.add_argument("--strict", type=_parse_bool, default=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = generate_post_final_topic_refinement_advisory_report(
        run_dir=args.run_dir,
        topic_id=args.topic_id,
        output_dir=args.output_dir,
        user_feedback=args.user_feedback,
        topic_state=args.topic_state,
        strict=args.strict,
    )
    sys.stdout.write(json.dumps(result.payload, ensure_ascii=False) + "\n")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
