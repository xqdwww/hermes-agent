#!/usr/bin/env python3
"""Deterministic post-final advisory detector for Topic Refinement.

This standalone utility reads existing Research/Decision artifacts and emits an
advisory report. It does not call an LLM, invoke the explicit registry adapter,
rerun the pipeline, acquire evidence, generate a candidate, adopt a candidate,
or rewrite final_v1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DETECTOR_VERSION = "r3a.0"
MODEL_OR_DETECTOR_USED = "deterministic"

REPORT_JSON = "post_final_advisory_report.json"
REPORT_MD = "post_final_advisory_report.md"
BLOCKED_JSON = "post_final_advisory_blocked_report.json"
BLOCKED_MD = "post_final_advisory_blocked_report.md"

STATUS_TOPIC_REFINEMENT = "TOPIC_REFINEMENT_SUGGESTED"
STATUS_SOURCE_NEED = "SOURCE_NEED_SUGGESTED"
STATUS_ENVIRONMENT = "ENVIRONMENT_TRIAGE_SUGGESTED"
STATUS_NO_REFINEMENT = "NO_REFINEMENT_SUGGESTED"
STATUS_NEW_TOPIC = "NEW_TOPIC_OR_FULL_RERUN_RECOMMENDED"
STATUS_INSUFFICIENT = "INSUFFICIENT_ARTIFACTS_TO_ADVISE"

VERDICT_CONFIRM_REFINEMENT = "ASK_USER_TO_CONFIRM_TOPIC_REFINEMENT"
VERDICT_AUTHORIZE_SOURCE = "ASK_USER_TO_AUTHORIZE_SOURCE_OR_FULL_TEXT_VERIFICATION"
VERDICT_FIX_ENVIRONMENT = "ASK_USER_TO_FIX_ENVIRONMENT"
VERDICT_DO_NOT_REFINE = "DO_NOT_REFINE"
VERDICT_START_NEW_TASK = "START_NEW_TASK_INSTEAD"
VERDICT_BLOCKED_CONTEXT = "BLOCKED_INSUFFICIENT_CONTEXT"

ALLOWED_ADVISORY_STATUSES = {
    STATUS_TOPIC_REFINEMENT,
    STATUS_SOURCE_NEED,
    STATUS_ENVIRONMENT,
    STATUS_NO_REFINEMENT,
    STATUS_NEW_TOPIC,
    STATUS_INSUFFICIENT,
}

ALLOWED_ADVISORY_VERDICTS = {
    VERDICT_CONFIRM_REFINEMENT,
    VERDICT_AUTHORIZE_SOURCE,
    VERDICT_FIX_ENVIRONMENT,
    VERDICT_DO_NOT_REFINE,
    VERDICT_START_NEW_TASK,
    VERDICT_BLOCKED_CONTEXT,
}

BLOCKED_RUN_DIR_MISSING = "BLOCKED_RUN_DIR_MISSING"
BLOCKED_OUTPUT_ALREADY_EXISTS = "BLOCKED_OUTPUT_ALREADY_EXISTS"
BLOCKED_MISSING_FINAL_V1 = "BLOCKED_MISSING_FINAL_V1"
BLOCKED_MISSING_QUALITY_REVIEW = "BLOCKED_MISSING_QUALITY_REVIEW"
BLOCKED_INVALID_TOPIC_ID = "BLOCKED_INVALID_TOPIC_ID"
BLOCKED_ARTIFACT_PATH_ESCAPE = "BLOCKED_ARTIFACT_PATH_ESCAPE"
BLOCKED_INVALID_TOPIC_STATE = "BLOCKED_INVALID_TOPIC_STATE"
BLOCKED_TOPIC_STATE_RUN_DIR_MISMATCH = "BLOCKED_TOPIC_STATE_RUN_DIR_MISMATCH"

FINAL_V1_NAMES = ("final_controller_report.md", "final.md", "final_answer.md")
QUALITY_REVIEW_NAMES = ("case_quality_review.md", "final_quality_gate.md", "quality_review.md")
ARTIFACT_SPECS = {
    "final_v1": FINAL_V1_NAMES,
    "quality_review": QUALITY_REVIEW_NAMES,
    "convergence_report": ("convergence_report.md",),
    "calibration_report": ("calibration_report.md",),
    "research_evidence_packet": ("research_evidence_packet.md",),
    "original_user_question": ("original_user_question.txt",),
    "runner_result": ("runner_result.json",),
    "failure_report": ("failure_report.md",),
}

ENVIRONMENT_PATTERNS = {
    "executor_resource_exhausted": "executor_resource_exhausted",
    "blocked_executor_unavailable": "blocked_executor_unavailable",
    "ddgs missing": "DDGS missing",
    "modulenotfounderror": "ModuleNotFoundError",
    "omlx": "OMLX",
    "service unhealthy": "service unhealthy",
    "environment blocker": "environment blocker",
}

SOURCE_NEED_PATTERNS = {
    "full-text verification": "full-text verification",
    "full text verification": "full-text verification",
    "snippet-backed": "snippet-backed",
    "snippet backed": "snippet-backed",
    "snippet": "snippet",
    "weak evidence": "weak evidence",
    "thin evidence": "thin evidence",
    "evidence gap": "evidence gap",
    "evidence_gap": "evidence gap",
    "unsupported": "unsupported",
    "speculative": "speculative",
    "candidate-source": "candidate-source",
    "candidate source": "candidate-source",
    "source need": "source need",
    "source_need": "source need",
}

QUALITY_PATTERNS = {
    "final too generic": "final too generic",
    "too generic": "final too generic",
    "low specificity": "low specificity",
    "low_specificity": "low specificity",
    "template": "template",
    "templated": "template",
    "missing obligation": "missing obligation",
    "missing_obligation": "missing obligation",
    "missing section": "missing section",
    "convergence not absorbed": "convergence not absorbed",
    "convergence_to_final_specificity_loss": "convergence not absorbed",
    "calibration not absorbed": "calibration not absorbed",
    "calibration_absorption_gap": "calibration not absorbed",
    "weak priority": "weak priority",
    "priority weak": "weak priority",
    "weak ranking": "weak ranking",
    "generic top": "generic top-N",
    "generic top-n": "generic top-N",
    "caveat not absorbed": "caveat not absorbed",
    "hidden caveat": "caveat not absorbed",
    "evidence caveat hidden": "caveat not absorbed",
    "overclaim": "overclaim",
    "over-claim": "overclaim",
    "candidate validation needed": "candidate validation needed",
    "candidate refinement": "candidate validation needed",
}

INSUFFICIENT_PATTERNS = {
    "insufficient artifacts": "insufficient artifacts",
    "insufficient context": "insufficient context",
    "not enough artifacts": "insufficient artifacts",
    "missing recommended artifacts": "missing recommended artifacts",
}

SAME_TOPIC_DEEPER_PATTERNS = (
    "继续这个话题",
    "同一个话题",
    "同一个 run",
    "只补这个 topic",
    "把第",
    "做实",
    "更具体",
    "same topic",
    "continue this topic",
    "deeper same topic",
    "more specific",
)

NEW_TOPIC_PATTERNS = (
    "换个话题",
    "新问题",
    "另一个问题",
    "ignore previous",
    "不看前面",
    "重新开始",
    "different topic",
    "new topic",
    "another topic",
)

FULL_RERUN_PATTERNS = (
    "full rerun",
    "full pipeline rerun",
    "rerun the pipeline",
    "重新研究",
    "全量重跑",
    "从头跑",
    "start over",
)

SOURCE_REQUEST_PATTERNS = (
    "source acquisition",
    "acquire new sources",
    "fetch new evidence",
    "查最新资料",
    "查新资料",
    "重新查资料",
    "source request",
)

FULL_TEXT_REQUEST_PATTERNS = (
    "full-text verification request",
    "full text verification request",
    "perform full-text verification",
    "perform full text verification",
    "全文验证",
)

ENVIRONMENT_REQUEST_PATTERNS = (
    "修 environment",
    "environment-only",
    "environment only",
    "fix environment",
    "ddgs missing",
    "module not found",
    "modulenotfounderror",
    "service unhealthy",
)

NON_REFINEMENT_TASK_PATTERNS = (
    "push/release",
    "push this",
    "release this",
    "final controller repair",
    "repair final controller",
    "evidence packet repair",
    "repair evidence packet",
    "general advice",
    "travel migration",
    "unrelated domain",
    "migration task",
)

NEGATION_PREFIXES = (
    "不要",
    "不",
    "不得",
    "无需",
    "别",
    "禁止",
    "no ",
    "not ",
    "do not ",
    "don't ",
    "without ",
    "avoid ",
)

DISALLOWED_NEXT_STEPS = [
    "automatic TOPIC_REFINEMENT execution",
    "automatic LLM candidate generation",
    "automatic source acquisition",
    "automatic full-text verification claim",
    "automatic pipeline rerun",
    "automatic candidate adoption",
    "overwriting final_v1",
    "using advisory confidence as validation",
]


@dataclass(frozen=True)
class AdvisoryResult:
    status: str
    exit_code: int
    output_dir: Path
    report_json_path: Path
    report_md_path: Path
    payload: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return _repo_root() / path


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _read_text(path: Path | None, max_chars: int = 250_000) -> str:
    if path is None:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[:max_chars]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_report_md(path: Path, title: str, payload: dict[str, Any]) -> None:
    lines = [f"# {title}", ""]
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            lines.extend([f"## {key}", "", "```json", json.dumps(value, indent=2, ensure_ascii=False), "```", ""])
        else:
            lines.append(f"- {key}: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_rel_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _find_first(run_dir: Path, names: Iterable[str]) -> tuple[Path | None, bool]:
    resolved_run_dir = run_dir.resolve()
    for name in names:
        matches = sorted(
            run_dir.rglob(name),
            key=lambda candidate: (len(candidate.relative_to(run_dir).parts), candidate.as_posix()),
        )
        for match in matches:
            if not _is_relative_to(match.resolve(), resolved_run_dir):
                return match, True
            return match, False
    return None, False


def discover_artifacts(run_dir: Path) -> tuple[dict[str, Path | None], str | None]:
    artifacts: dict[str, Path | None] = {}
    for key, names in ARTIFACT_SPECS.items():
        found, escaped = _find_first(run_dir, names)
        artifacts[key] = found
        if escaped:
            return artifacts, key
    states: list[Path] = []
    for candidate in sorted(run_dir.rglob("topic_refinement_state*.json"), key=lambda path: path.as_posix()):
        if not _is_relative_to(candidate.resolve(), run_dir.resolve()):
            artifacts["topic_refinement_states"] = candidate
            return artifacts, "topic_refinement_states"
        states.append(candidate)
    artifacts["topic_refinement_states"] = states  # type: ignore[assignment]
    return artifacts, None


def _artifact_paths_payload(run_dir: Path, artifacts: dict[str, Path | None]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in artifacts.items():
        if isinstance(value, list):
            payload[key] = [_safe_rel_path(path, run_dir) for path in value]
        elif value is None:
            payload[key] = None
        else:
            payload[key] = _safe_rel_path(value, run_dir)
    return payload


def _artifact_hashes(artifacts: dict[str, Path | None]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for key, value in artifacts.items():
        if isinstance(value, Path):
            digest = _sha256(value)
            if digest is not None:
                hashes[key] = digest
    return hashes


def _texts(artifacts: dict[str, Path | None], keys: Iterable[str]) -> dict[str, str]:
    return {key: _read_text(artifacts.get(key)) for key in keys if isinstance(artifacts.get(key), Path)}


def _scan_patterns(texts: Iterable[str], patterns: dict[str, str]) -> list[str]:
    joined = "\n".join(texts).lower()
    signals: list[str] = []
    for pattern, label in patterns.items():
        if _find_unnegated(joined, (pattern,)) is not None and label not in signals:
            signals.append(label)
    return signals


def _is_negated(text: str, index: int) -> bool:
    window = text[max(0, index - 28) : index].lower()
    return any(prefix in window for prefix in NEGATION_PREFIXES)


def _find_unnegated(text: str, patterns: Iterable[str]) -> str | None:
    lower = text.lower()
    for pattern in patterns:
        needle = pattern.lower()
        start = 0
        while True:
            index = lower.find(needle, start)
            if index < 0:
                break
            if not _is_negated(lower, index):
                return pattern
            start = index + len(needle)
    return None


def _feedback_signals(user_feedback: str) -> dict[str, str | None]:
    return {
        "new_topic": _find_unnegated(user_feedback, NEW_TOPIC_PATTERNS),
        "full_rerun": _find_unnegated(user_feedback, FULL_RERUN_PATTERNS),
        "source_request": _find_unnegated(user_feedback, SOURCE_REQUEST_PATTERNS),
        "full_text_request": _find_unnegated(user_feedback, FULL_TEXT_REQUEST_PATTERNS),
        "environment_request": _find_unnegated(user_feedback, ENVIRONMENT_REQUEST_PATTERNS),
        "non_refinement_task": _find_unnegated(user_feedback, NON_REFINEMENT_TASK_PATTERNS),
        "same_topic_deeper": _find_unnegated(user_feedback, SAME_TOPIC_DEEPER_PATTERNS),
    }


def _blocked(
    status: str,
    output_dir: Path,
    reason: str,
    *,
    run_dir: Path | None = None,
    topic_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> AdvisoryResult:
    payload: dict[str, Any] = {
        "status": status,
        "detector_version": DETECTOR_VERSION,
        "generated_at_utc": _utc_now(),
        "run_dir": str(run_dir) if run_dir is not None else None,
        "topic_id": topic_id,
        "reason": reason,
        "no_llm_called": True,
        "no_adapter_called": True,
        "no_pipeline_rerun": True,
        "no_candidate_generated": True,
        "no_final_rewritten": True,
    }
    if extra:
        payload.update(extra)
    json_path = output_dir / BLOCKED_JSON
    md_path = output_dir / BLOCKED_MD
    _write_json(json_path, payload)
    _write_report_md(md_path, "Topic Refinement Post-Final Advisory Blocked Report", payload)
    return AdvisoryResult(status=status, exit_code=2, output_dir=output_dir, report_json_path=json_path, report_md_path=md_path, payload=payload)


def _topic_state_mismatch(topic_state: dict[str, Any], run_dir: Path, topic_id: str) -> str | None:
    state_topic_id = topic_state.get("topic_id")
    if isinstance(state_topic_id, str) and state_topic_id.strip() and state_topic_id.strip() != topic_id:
        return "topic_id mismatch"

    state_run_dir = topic_state.get("run_dir")
    if isinstance(state_run_dir, str) and state_run_dir.strip():
        resolved_state_run = _resolve_path(state_run_dir).resolve(strict=False)
        if resolved_state_run != run_dir.resolve(strict=False):
            return "run_dir mismatch"

    artifact_paths = topic_state.get("artifact_paths")
    if isinstance(artifact_paths, dict):
        for key, raw_path in artifact_paths.items():
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            path = _resolve_path(raw_path).resolve(strict=False)
            if not _is_relative_to(path, run_dir.resolve(strict=False)):
                return f"artifact_paths.{key} outside run_dir"
    return None


def _validate_inputs(
    *,
    run_dir: Path,
    output_dir: Path,
    topic_id: str,
    topic_state: Path | None,
) -> tuple[dict[str, Path | None] | None, AdvisoryResult | None, dict[str, Any] | None]:
    if not topic_id.strip():
        return None, _blocked(BLOCKED_INVALID_TOPIC_ID, output_dir, "topic_id must be non-empty", run_dir=run_dir, topic_id=topic_id), None
    if not run_dir.exists() or not run_dir.is_dir():
        return None, _blocked(BLOCKED_RUN_DIR_MISSING, output_dir, "run_dir does not exist or is not a directory", run_dir=run_dir, topic_id=topic_id), None
    if (output_dir / REPORT_JSON).exists():
        return None, _blocked(BLOCKED_OUTPUT_ALREADY_EXISTS, output_dir, f"{REPORT_JSON} already exists", run_dir=run_dir, topic_id=topic_id), None

    topic_state_payload = None
    if topic_state is not None:
        if not topic_state.exists() or not topic_state.is_file():
            return None, _blocked(BLOCKED_INVALID_TOPIC_STATE, output_dir, "topic_state path is missing", run_dir=run_dir, topic_id=topic_id), None
        topic_state_payload = _read_json(topic_state)
        if topic_state_payload is None:
            return None, _blocked(BLOCKED_INVALID_TOPIC_STATE, output_dir, "topic_state is not a JSON object", run_dir=run_dir, topic_id=topic_id), None
        mismatch = _topic_state_mismatch(topic_state_payload, run_dir, topic_id.strip())
        if mismatch:
            return (
                None,
                _blocked(
                    BLOCKED_TOPIC_STATE_RUN_DIR_MISMATCH,
                    output_dir,
                    mismatch,
                    run_dir=run_dir,
                    topic_id=topic_id,
                    extra={"topic_state_path": str(topic_state)},
                ),
                None,
            )

    artifacts, escaped_key = discover_artifacts(run_dir)
    if escaped_key is not None:
        return None, _blocked(BLOCKED_ARTIFACT_PATH_ESCAPE, output_dir, f"{escaped_key} resolves outside run_dir", run_dir=run_dir, topic_id=topic_id), topic_state_payload
    if artifacts.get("final_v1") is None:
        return None, _blocked(BLOCKED_MISSING_FINAL_V1, output_dir, "final_v1 artifact is required", run_dir=run_dir, topic_id=topic_id), topic_state_payload
    if artifacts.get("quality_review") is None:
        return None, _blocked(BLOCKED_MISSING_QUALITY_REVIEW, output_dir, "quality_review artifact is required", run_dir=run_dir, topic_id=topic_id), topic_state_payload
    return artifacts, None, topic_state_payload


def _selected_refinement_mode(quality_signals: list[str], feedback_signals: dict[str, str | None]) -> str | None:
    signal_set = set(quality_signals)
    if {"convergence not absorbed", "calibration not absorbed"} & signal_set:
        return "final_absorption_pass"
    if feedback_signals.get("same_topic_deeper"):
        return "user_feedback_refinement"
    if signal_set & {
        "final too generic",
        "low specificity",
        "template",
        "missing obligation",
        "missing section",
        "weak priority",
        "weak ranking",
        "generic top-N",
        "caveat not absorbed",
        "overclaim",
        "candidate validation needed",
    }:
        return "section_rewrite"
    return None


def _quality_from_feedback(feedback_signals: dict[str, str | None]) -> list[str]:
    if feedback_signals.get("same_topic_deeper"):
        return ["same-topic deeper user feedback"]
    return []


def _build_payload(
    *,
    run_dir: Path,
    output_dir: Path,
    topic_id: str,
    user_feedback: str,
    strict: bool,
    artifacts: dict[str, Path | None],
    advisory_status: str,
    advisory_verdict: str,
    detected_hard_boundaries: list[str],
    detected_semantic_quality_issues: list[str],
    suggested_next_action: str,
    suggested_failure_type: str | None,
    suggested_refinement_mode: str | None,
    source_need: bool,
    environment_triage_needed: bool,
    reason_summary: str,
    evidence_boundary_summary: str,
    calibration_boundary_summary: str,
    semantic_depth_summary: str,
    detector_confidence: str,
    false_positive_risk: str,
    false_negative_risk: str,
) -> dict[str, Any]:
    assert advisory_status in ALLOWED_ADVISORY_STATUSES
    assert advisory_verdict in ALLOWED_ADVISORY_VERDICTS
    return {
        "advisory_status": advisory_status,
        "advisory_verdict": advisory_verdict,
        "topic_id": topic_id.strip(),
        "run_dir": str(run_dir),
        "artifact_paths": _artifact_paths_payload(run_dir, artifacts),
        "artifact_hashes": _artifact_hashes(artifacts),
        "detected_hard_boundaries": detected_hard_boundaries,
        "detected_semantic_quality_issues": detected_semantic_quality_issues,
        "suggested_next_action": suggested_next_action,
        "suggested_failure_type": suggested_failure_type,
        "suggested_refinement_mode": suggested_refinement_mode,
        "source_need": source_need,
        "environment_triage_needed": environment_triage_needed,
        "confidence_upgrade_allowed": False,
        "requires_user_confirmation": True,
        "auto_execution": False,
        "auto_adoption": False,
        "allowed_next_step": _allowed_next_step(advisory_status),
        "disallowed_next_steps": DISALLOWED_NEXT_STEPS,
        "reason_summary": reason_summary,
        "evidence_boundary_summary": evidence_boundary_summary,
        "calibration_boundary_summary": calibration_boundary_summary,
        "semantic_depth_summary": semantic_depth_summary,
        "model_or_detector_used": MODEL_OR_DETECTOR_USED,
        "detector_version": DETECTOR_VERSION,
        "detector_confidence": detector_confidence,
        "false_positive_risk": false_positive_risk,
        "false_negative_risk": false_negative_risk,
        "generated_at_utc": _utc_now(),
        "strict": strict,
        "user_feedback": user_feedback,
        "no_llm_called": True,
        "no_adapter_called": True,
        "no_pipeline_rerun": True,
        "no_candidate_generated": True,
        "no_final_rewritten": True,
    }


def _allowed_next_step(advisory_status: str) -> str:
    if advisory_status == STATUS_TOPIC_REFINEMENT:
        return "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"
    if advisory_status == STATUS_SOURCE_NEED:
        return "ask_user_to_authorize_source_or_full_text_verification"
    if advisory_status == STATUS_ENVIRONMENT:
        return "ask_user_to_fix_environment"
    if advisory_status == STATUS_NEW_TOPIC:
        return "start_new_task"
    if advisory_status == STATUS_INSUFFICIENT:
        return "request_missing_artifacts"
    return "stop"


def analyze_post_final_advisory(
    *,
    run_dir: Path | str,
    topic_id: str,
    output_dir: Path | str,
    topic_state: Path | str | None = None,
    user_feedback: str = "",
    strict: bool = True,
    write_reports: bool = True,
) -> AdvisoryResult:
    resolved_run_dir = _resolve_path(run_dir).resolve(strict=False)
    resolved_output_dir = _resolve_path(output_dir).resolve(strict=False)
    resolved_topic_state = _resolve_path(topic_state).resolve(strict=False) if topic_state is not None else None

    artifacts, blocked, _topic_state_payload = _validate_inputs(
        run_dir=resolved_run_dir,
        output_dir=resolved_output_dir,
        topic_id=topic_id,
        topic_state=resolved_topic_state,
    )
    if blocked is not None:
        return blocked
    assert artifacts is not None

    text_keys = (
        "final_v1",
        "quality_review",
        "convergence_report",
        "calibration_report",
        "research_evidence_packet",
        "runner_result",
        "failure_report",
    )
    texts = _texts(artifacts, text_keys)
    feedback = user_feedback or ""
    feedback_scan = _feedback_signals(feedback)

    environment_signals = _scan_patterns(texts.values(), ENVIRONMENT_PATTERNS)
    source_signals = _scan_patterns(texts.values(), SOURCE_NEED_PATTERNS)
    quality_signals = _scan_patterns(texts.values(), QUALITY_PATTERNS)
    insufficient_signals = _scan_patterns(texts.values(), INSUFFICIENT_PATTERNS)

    if feedback_scan.get("environment_request"):
        environment_signals.append(f"user_feedback:{feedback_scan['environment_request']}")
    if feedback_scan.get("source_request"):
        source_signals.append(f"user_feedback:{feedback_scan['source_request']}")
    if feedback_scan.get("full_text_request"):
        source_signals.append(f"user_feedback:{feedback_scan['full_text_request']}")
    quality_signals.extend(_quality_from_feedback(feedback_scan))

    if feedback_scan.get("new_topic") or feedback_scan.get("full_rerun") or feedback_scan.get("non_refinement_task"):
        boundary = feedback_scan.get("new_topic") or feedback_scan.get("full_rerun") or feedback_scan.get("non_refinement_task")
        payload = _build_payload(
            run_dir=resolved_run_dir,
            output_dir=resolved_output_dir,
            topic_id=topic_id,
            user_feedback=feedback,
            strict=strict,
            artifacts=artifacts,
            advisory_status=STATUS_NEW_TOPIC,
            advisory_verdict=VERDICT_START_NEW_TASK,
            detected_hard_boundaries=[f"user_feedback:{boundary}"],
            detected_semantic_quality_issues=[],
            suggested_next_action="start_new_task",
            suggested_failure_type="new_topic_or_full_rerun",
            suggested_refinement_mode=None,
            source_need=False,
            environment_triage_needed=False,
            reason_summary="User feedback indicates a new task, full rerun, or non-refinement work.",
            evidence_boundary_summary="No evidence boundary is overridden.",
            calibration_boundary_summary="No calibration boundary is overridden.",
            semantic_depth_summary="No same-topic semantic refinement is advised.",
            detector_confidence="high",
            false_positive_risk="low",
            false_negative_risk="medium",
        )
    elif environment_signals:
        payload = _build_payload(
            run_dir=resolved_run_dir,
            output_dir=resolved_output_dir,
            topic_id=topic_id,
            user_feedback=feedback,
            strict=strict,
            artifacts=artifacts,
            advisory_status=STATUS_ENVIRONMENT,
            advisory_verdict=VERDICT_FIX_ENVIRONMENT,
            detected_hard_boundaries=environment_signals,
            detected_semantic_quality_issues=quality_signals,
            suggested_next_action="environment_triage",
            suggested_failure_type="executor_or_environment_blocker",
            suggested_refinement_mode="environment_triage",
            source_need=False,
            environment_triage_needed=True,
            reason_summary="Environment/runtime signals outrank rewrite suggestions.",
            evidence_boundary_summary="Evidence state is not changed.",
            calibration_boundary_summary="Calibration state is not changed.",
            semantic_depth_summary="Semantic rewrite is not advised until environment blockers are resolved.",
            detector_confidence="high",
            false_positive_risk="low",
            false_negative_risk="medium",
        )
    elif source_signals:
        payload = _build_payload(
            run_dir=resolved_run_dir,
            output_dir=resolved_output_dir,
            topic_id=topic_id,
            user_feedback=feedback,
            strict=strict,
            artifacts=artifacts,
            advisory_status=STATUS_SOURCE_NEED,
            advisory_verdict=VERDICT_AUTHORIZE_SOURCE,
            detected_hard_boundaries=source_signals,
            detected_semantic_quality_issues=quality_signals,
            suggested_next_action="source_need_or_full_text_verification",
            suggested_failure_type="evidence_boundary_or_source_need",
            suggested_refinement_mode="targeted_evidence_acquisition",
            source_need=True,
            environment_triage_needed=False,
            reason_summary="Evidence/full-text boundary signals outrank rewrite suggestions.",
            evidence_boundary_summary="Confidence upgrade is not allowed without separately authorized evidence work.",
            calibration_boundary_summary="Unsupported/speculative signals are preserved.",
            semantic_depth_summary="Rewrite is not advised because evidence boundary dominates.",
            detector_confidence="high",
            false_positive_risk="low",
            false_negative_risk="medium",
        )
    elif quality_signals:
        mode = _selected_refinement_mode(quality_signals, feedback_scan)
        payload = _build_payload(
            run_dir=resolved_run_dir,
            output_dir=resolved_output_dir,
            topic_id=topic_id,
            user_feedback=feedback,
            strict=strict,
            artifacts=artifacts,
            advisory_status=STATUS_TOPIC_REFINEMENT,
            advisory_verdict=VERDICT_CONFIRM_REFINEMENT,
            detected_hard_boundaries=[],
            detected_semantic_quality_issues=quality_signals,
            suggested_next_action="explicit_TOPIC_REFINEMENT_after_user_confirmation",
            suggested_failure_type="final_quality_refinement_needed",
            suggested_refinement_mode=mode,
            source_need=False,
            environment_triage_needed=False,
            reason_summary="Deterministic quality signals suggest same-topic refinement may be useful.",
            evidence_boundary_summary="No source_need signal detected by deterministic scan.",
            calibration_boundary_summary="Calibration boundaries must still be preserved by any later candidate.",
            semantic_depth_summary="Detected shallow or unabsorbed final-quality signals.",
            detector_confidence="medium",
            false_positive_risk="medium",
            false_negative_risk="medium",
        )
    elif insufficient_signals:
        payload = _build_payload(
            run_dir=resolved_run_dir,
            output_dir=resolved_output_dir,
            topic_id=topic_id,
            user_feedback=feedback,
            strict=strict,
            artifacts=artifacts,
            advisory_status=STATUS_INSUFFICIENT,
            advisory_verdict=VERDICT_BLOCKED_CONTEXT,
            detected_hard_boundaries=insufficient_signals,
            detected_semantic_quality_issues=[],
            suggested_next_action="request_missing_artifacts",
            suggested_failure_type="insufficient_context",
            suggested_refinement_mode=None,
            source_need=False,
            environment_triage_needed=False,
            reason_summary="Artifacts exist but local signals say the advisory context is insufficient.",
            evidence_boundary_summary="No evidence boundary is overridden.",
            calibration_boundary_summary="No calibration boundary is overridden.",
            semantic_depth_summary="Semantic depth cannot be advised from current artifacts.",
            detector_confidence="medium",
            false_positive_risk="low",
            false_negative_risk="medium",
        )
    else:
        payload = _build_payload(
            run_dir=resolved_run_dir,
            output_dir=resolved_output_dir,
            topic_id=topic_id,
            user_feedback=feedback,
            strict=strict,
            artifacts=artifacts,
            advisory_status=STATUS_NO_REFINEMENT,
            advisory_verdict=VERDICT_DO_NOT_REFINE,
            detected_hard_boundaries=[],
            detected_semantic_quality_issues=[],
            suggested_next_action="none",
            suggested_failure_type=None,
            suggested_refinement_mode=None,
            source_need=False,
            environment_triage_needed=False,
            reason_summary="No deterministic hard-boundary or quality-refinement signal was detected.",
            evidence_boundary_summary="No source_need signal detected.",
            calibration_boundary_summary="No calibration boundary signal detected.",
            semantic_depth_summary="No deterministic semantic-depth issue detected.",
            detector_confidence="medium",
            false_positive_risk="low",
            false_negative_risk="medium",
        )

    json_path = resolved_output_dir / REPORT_JSON
    md_path = resolved_output_dir / REPORT_MD
    if write_reports:
        _write_json(json_path, payload)
        _write_report_md(md_path, "Topic Refinement Post-Final Advisory Report", payload)
    return AdvisoryResult(status=payload["advisory_status"], exit_code=0, output_dir=resolved_output_dir, report_json_path=json_path, report_md_path=md_path, payload=payload)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a deterministic post-final Topic Refinement advisory report.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--topic-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--topic-state")
    parser.add_argument("--user-feedback", default="")
    parser.add_argument("--strict", type=_parse_bool, default=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = analyze_post_final_advisory(
        run_dir=args.run_dir,
        topic_id=args.topic_id,
        output_dir=args.output_dir,
        topic_state=args.topic_state,
        user_feedback=args.user_feedback,
        strict=args.strict,
    )
    sys.stdout.write(json.dumps(result.payload, ensure_ascii=False) + "\n")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
