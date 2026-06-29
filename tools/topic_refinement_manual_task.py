#!/usr/bin/env python3
"""CLI-only manual wrapper for Topic Refinement.

This utility orchestrates the Topic Refinement dry-run slices. It does not
register a task mode, call an LLM, rerun the Research/Decision pipeline,
perform evidence acquisition, or rewrite final_v1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import topic_refinement_artifact_loader as artifact_loader
from tools import topic_refinement_mode_router as mode_router
from tools import topic_refinement_output_validator as output_validator

TASK_MODE = "TOPIC_REFINEMENT"
MANUAL_TASK_VERSION = "slice4.0"

PASS_MANUAL_TASK_HANDOFF_READY = "PASS_MANUAL_TASK_HANDOFF_READY"
PASS_MANUAL_TASK_CANDIDATE_VALIDATED = "PASS_MANUAL_TASK_CANDIDATE_VALIDATED"
PASS_MANUAL_TASK_STOPPED_SOURCE_NEED = "PASS_MANUAL_TASK_STOPPED_SOURCE_NEED"
PASS_MANUAL_TASK_STOPPED_ENVIRONMENT_TRIAGE = "PASS_MANUAL_TASK_STOPPED_ENVIRONMENT_TRIAGE"
PASS_MANUAL_TASK_STOPPED_NO_ACTION = "PASS_MANUAL_TASK_STOPPED_NO_ACTION"

BLOCKED_SAME_TOPIC_NOT_CONFIRMED = "BLOCKED_SAME_TOPIC_NOT_CONFIRMED"
BLOCKED_NEW_TOPIC_DETECTED = "BLOCKED_NEW_TOPIC_DETECTED"
BLOCKED_RUN_DIR_MISSING = "BLOCKED_RUN_DIR_MISSING"
BLOCKED_INVALID_TOPIC_ID = "BLOCKED_INVALID_TOPIC_ID"
BLOCKED_INVALID_USER_FEEDBACK = "BLOCKED_INVALID_USER_FEEDBACK"
BLOCKED_OUTPUT_ALREADY_EXISTS = "BLOCKED_OUTPUT_ALREADY_EXISTS"
BLOCKED_EXPECTED_BRANCH_MISMATCH = "BLOCKED_EXPECTED_BRANCH_MISMATCH"
BLOCKED_EXPECTED_HEAD_MISMATCH = "BLOCKED_EXPECTED_HEAD_MISMATCH"
BLOCKED_LOADER_FAILED = "BLOCKED_LOADER_FAILED"
BLOCKED_ROUTER_FAILED = "BLOCKED_ROUTER_FAILED"
BLOCKED_VALIDATOR_FAILED = "BLOCKED_VALIDATOR_FAILED"
BLOCKED_DRY_RUN_REQUIRED = "BLOCKED_DRY_RUN_REQUIRED"
BLOCKED_RUNTIME_INTEGRATION_NOT_ALLOWED = "BLOCKED_RUNTIME_INTEGRATION_NOT_ALLOWED"

QUALITY_READY = "TOPIC_REFINEMENT_MANUAL_TASK_READY_FOR_OPERATOR_USE"
QUALITY_STOPPED = "TOPIC_REFINEMENT_STOPPED_BY_DESIGN"
QUALITY_VALIDATED = "TOPIC_REFINEMENT_CANDIDATE_VALIDATED"
QUALITY_REPAIR = "TOPIC_REFINEMENT_NEEDS_REPAIR"

REWRITE_CAPABLE_MODES = {"final_absorption_pass", "section_rewrite", "user_feedback_refinement"}

NEW_TOPIC_SIGNALS = (
    "换个话题",
    "新问题",
    "另一个问题",
    "unrelated",
    "different topic",
    "new topic",
    "ignore previous",
    "不看前面",
    "重新开始",
)

CONTINUATION_SIGNALS = (
    "继续这个话题",
    "只补",
    "重写第",
    "不够具体",
    "做实",
    "refine",
    "same topic",
    "continue",
    "more specific",
    "revise section",
)


@dataclass(frozen=True)
class ManualTaskResult:
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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_repo_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return _repo_root() / path


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(token.lower() in lower for token in tokens)


def _same_topic_warning(user_feedback: str) -> str | None:
    if _contains_any(user_feedback, CONTINUATION_SIGNALS):
        return None
    return "same_topic_confirmed_without_continuation_phrase"


def _current_branch() -> str:
    return subprocess.check_output(["git", "branch", "--show-current"], cwd=_repo_root(), text=True).strip()


def _current_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_repo_root(), text=True).strip()


def _base_payload(
    *,
    status: str,
    topic_id: str,
    run_dir: Path,
    output_dir: Path,
    user_feedback: str,
    quality_verdict: str = QUALITY_REPAIR,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "quality_verdict": quality_verdict,
        "manual_task_version": MANUAL_TASK_VERSION,
        "generated_at_utc": _utc_now(),
        "task_mode": TASK_MODE,
        "topic_id": topic_id.strip(),
        "run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "user_feedback": user_feedback,
        "reason": reason,
        "no_llm_called": True,
        "no_pipeline_rerun": True,
        "no_runtime_integration": True,
        "no_task_engine_registry_integration": True,
        "no_evidence_acquisition_performed": True,
    }


def _blocked(
    status: str,
    *,
    run_dir: Path,
    output_dir: Path,
    topic_id: str,
    user_feedback: str,
    reason: str,
    extra: dict[str, Any] | None = None,
    write_report: bool = True,
) -> ManualTaskResult:
    payload = _base_payload(
        status=status,
        topic_id=topic_id,
        run_dir=run_dir,
        output_dir=output_dir,
        user_feedback=user_feedback,
        reason=reason,
    )
    if extra:
        payload.update(extra)
    payload.setdefault("recommended_next_step", "Fix the blocked condition and rerun the CLI-only manual task wrapper.")
    if write_report:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "manual_task_blocked_report.json"
        md_path = output_dir / "manual_task_blocked_report.md"
        _write_json(json_path, payload)
        _write_report_md(md_path, "Topic Refinement Manual Task Blocked Report", payload)
        return ManualTaskResult(status, 2, output_dir, json_path, md_path)
    return ManualTaskResult(status, 2, None, None, None)


def _final_v1_entry(state: dict[str, Any]) -> dict[str, Any] | None:
    versions = state.get("final_versions")
    if isinstance(versions, list):
        for entry in versions:
            if isinstance(entry, dict) and entry.get("version") == "final_v1":
                return entry
    if isinstance(versions, dict):
        entry = versions.get("final_v1")
        return entry if isinstance(entry, dict) else None
    return None


def _final_v1_hash_check(state: dict[str, Any]) -> dict[str, Any]:
    entry = _final_v1_entry(state)
    final_path = _resolve_repo_path(entry.get("path") if entry else state.get("current_final_version_path"))
    expected = None
    if isinstance(entry, dict):
        expected = entry.get("sha256")
    if expected is None:
        expected = (state.get("artifact_hashes") or {}).get("final_v1")
    actual = _sha256(final_path) if final_path is not None else None
    return {
        "path": str(final_path) if final_path else None,
        "expected_sha256": expected,
        "actual_sha256": actual,
        "pass": expected is None or expected == actual,
    }


def _load_optional_report(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError):
        return None


def _write_source_need_candidate(candidate_dir: Path, routed: dict[str, Any]) -> Path:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    path = candidate_dir / "refinement_stop_or_source_need.md"
    text = f"""# Refinement Stop / Source Need

selected_refinement_mode: targeted_evidence_acquisition
next_action: {routed.get('next_action')}

## Boundary Decision

The current artifacts are insufficient for a more certain answer. The routed state requires source_need / full-text verification before any confidence upgrade or stronger conclusion.

## Verification Required

Full-text verification required before stronger claims can be written. Needed sources should be identified in a separate authorized workflow.

## What Was Not Done

- new_evidence: none.
- Full-text verification was not performed.
- No revised final was generated.
- final_v1 remains unchanged.
- Existing caveats are preserved.
"""
    path.write_text(text, encoding="utf-8")
    return path


def _write_source_plan_candidate(candidate_dir: Path, routed: dict[str, Any]) -> Path:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    path = candidate_dir / "source_acquisition_plan.md"
    text = f"""# Source Need Plan

selected_refinement_mode: targeted_evidence_acquisition
next_action: {routed.get('next_action')}

This is a dry-run plan only. Needed sources and full-text verification should be listed before any stronger conclusion is written.

- new_evidence: none.
- No full-text verification was performed.
- final_v1 remains unchanged.
- Existing caveats are preserved.
"""
    path.write_text(text, encoding="utf-8")
    return path


def _write_environment_candidate(candidate_dir: Path, routed: dict[str, Any]) -> Path:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    path = candidate_dir / "environment_triage_report.md"
    text = f"""# Environment Triage Required

selected_refinement_mode: environment_triage
next_action: {routed.get('next_action')}

Answer rewrite is not allowed until the environment or runtime blocker is resolved. final_v1 remains unchanged.
"""
    path.write_text(text, encoding="utf-8")
    return path


def _write_no_action_candidate(candidate_dir: Path, routed: dict[str, Any]) -> Path:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    path = candidate_dir / "no_actionable_refinement_report.md"
    text = f"""# No Actionable Refinement

selected_refinement_mode: null
next_action: {routed.get('next_action')}

No deterministic same-topic refinement signal was found. No revised final was generated and final_v1 remains unchanged.
"""
    path.write_text(text, encoding="utf-8")
    return path


def _write_handoff_prompt(output_dir: Path, initial: dict[str, Any], routed: dict[str, Any], user_feedback: str, allowed_scope: str) -> Path:
    path = output_dir / "refinement_handoff_prompt.md"
    final_entry = _final_v1_entry(routed) or {}
    lines = [
        "# Topic Refinement Handoff Prompt",
        "",
        "Use this prompt only for a manual candidate refinement. The candidate must be validated before it is usable.",
        "",
        f"topic_id: {routed.get('topic_id')}",
        f"original_question: {routed.get('original_question')}",
        f"final_v1_path: {final_entry.get('path') or routed.get('current_final_version_path')}",
        f"routed_state_path: {routed.get('input_state_path')}",
        f"selected_failure_type: {routed.get('selected_failure_type')}",
        f"selected_refinement_mode: {routed.get('selected_refinement_mode')}",
        f"user_feedback: {user_feedback}",
        f"allowed_scope: {allowed_scope}",
        "",
        "## preserved_caveats",
        "",
        json.dumps(routed.get("preserved_caveats", []), indent=2, ensure_ascii=False),
        "",
        "## unresolved_evidence_gaps",
        "",
        json.dumps(routed.get("unresolved_evidence_gaps", []), indent=2, ensure_ascii=False),
        "",
        f"confidence_boundary: {routed.get('confidence_boundary')}",
        "",
        "## Hard Rules",
        "",
        "- no full rerun",
        "- no new evidence unless authorized",
        "- no confidence increase without new evidence",
        "- preserve caveats",
        "- do not overwrite final_v1",
        "- write candidate output to candidate_refinement_dir",
        "- must include changed_unchanged_traceability.md",
        "- must pass output validator before usable",
        "- do not claim full-text verification unless it was actually performed",
        "",
        "## Expected Candidate Output",
        "",
        "Write only `revised_final_v2.md` or `refined_sections_v2.md` plus `changed_unchanged_traceability.md` in the candidate directory. Do not modify artifacts in the source run directory.",
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _write_final_state(output_dir: Path, initial: dict[str, Any], routed: dict[str, Any], report: dict[str, Any]) -> Path:
    state = dict(routed)
    history = list(state.get("refinement_history") or [])
    history.append(
        {
            "event": "manual_task_wrapper",
            "status": report.get("status"),
            "selected_failure_type": report.get("selected_failure_type"),
            "selected_refinement_mode": report.get("selected_refinement_mode"),
            "validator_result": report.get("validator_result"),
            "generated_at_utc": report.get("generated_at_utc"),
        }
    )
    state.update(
        {
            "state_type": "topic_refinement_state_manual_task_final",
            "manual_task_version": MANUAL_TASK_VERSION,
            "manual_task_report_path": str(output_dir / "manual_task_report.json"),
            "refinement_history": history,
            "append_only_state": True,
            "no_runtime_integration": True,
            "no_llm_called": True,
            "no_pipeline_rerun": True,
            "no_evidence_acquisition_performed": True,
        }
    )
    path = output_dir / "topic_refinement_state.final.json"
    _write_json(path, state)
    return path


def _success_report(
    *,
    status: str,
    quality_verdict: str,
    run_dir: Path,
    output_dir: Path,
    topic_id: str,
    user_feedback: str,
    loader_result: artifact_loader.LoadResult,
    router_result: mode_router.RouterResult,
    initial: dict[str, Any],
    routed: dict[str, Any],
    validator_result: output_validator.ValidatorResult | None = None,
    validator_report: dict[str, Any] | None = None,
    handoff_prompt: Path | None = None,
    generated_candidate_output: Path | None = None,
    same_topic_warning: str | None = None,
) -> ManualTaskResult:
    hash_check = validator_report.get("final_v1_overwrite_check") if validator_report else _final_v1_hash_check(routed)
    payload = _base_payload(
        status=status,
        quality_verdict=quality_verdict,
        topic_id=topic_id,
        run_dir=run_dir,
        output_dir=output_dir,
        user_feedback=user_feedback,
    )
    payload.update(
        {
            "loader_result": loader_result.status,
            "router_result": router_result.status,
            "validator_result": validator_result.status if validator_result else None,
            "selected_failure_type": routed.get("selected_failure_type"),
            "selected_refinement_mode": routed.get("selected_refinement_mode"),
            "stop_reason": routed.get("stop_reason"),
            "next_action": routed.get("next_action"),
            "same_topic_warning": same_topic_warning,
            "generated_handoff_prompt": str(handoff_prompt) if handoff_prompt else None,
            "generated_candidate_output": str(generated_candidate_output) if generated_candidate_output else None,
            "candidate_refinement_dir": str(generated_candidate_output) if generated_candidate_output else None,
            "usable_candidate": status == PASS_MANUAL_TASK_CANDIDATE_VALIDATED,
            "final_v1_overwrite_check": hash_check,
            "no_default_full_rerun": True,
            "append_only_state": True,
            "recommended_next_step": _recommended_next_step(status, routed),
        }
    )
    final_state_path = _write_final_state(output_dir, initial, routed, payload)
    payload["topic_refinement_state_final_path"] = str(final_state_path)
    json_path = output_dir / "manual_task_report.json"
    md_path = output_dir / "manual_task_report.md"
    _write_json(json_path, payload)
    _write_report_md(md_path, "Topic Refinement Manual Task Report", payload)
    return ManualTaskResult(status, 0, output_dir, json_path, md_path)


def _recommended_next_step(status: str, routed: dict[str, Any]) -> str:
    if status == PASS_MANUAL_TASK_HANDOFF_READY:
        return "Use the handoff prompt to create a candidate refinement, then rerun this wrapper with candidate_refinement_dir for validation."
    if status == PASS_MANUAL_TASK_CANDIDATE_VALIDATED:
        return "Operator may review the validated candidate; final_v1 remains preserved."
    if status == PASS_MANUAL_TASK_STOPPED_SOURCE_NEED:
        return "Authorize separate source/full-text verification before attempting a stronger answer."
    if status == PASS_MANUAL_TASK_STOPPED_ENVIRONMENT_TRIAGE:
        return "Resolve the environment/runtime blocker before answer refinement."
    if status == PASS_MANUAL_TASK_STOPPED_NO_ACTION:
        return "Ask the user for more specific same-topic feedback or stop."
    return f"Review next_action={routed.get('next_action')}."


def run_manual_task(
    *,
    run_dir: Path,
    topic_id: str,
    user_feedback: str,
    output_dir: Path,
    confirm_same_topic: bool = False,
    candidate_refinement_dir: Path | None = None,
    allow_source_acquisition: bool = False,
    allow_full_text_verification: bool = False,
    allow_llm_refinement: bool = False,
    expected_branch: str | None = None,
    expected_head: str | None = None,
    dry_run: bool = True,
    strict: bool = True,
    task_mode: str = TASK_MODE,
    allowed_refinement_scope: str = "bounded_refinement",
) -> ManualTaskResult:
    del strict
    if task_mode != TASK_MODE:
        return _blocked(
            BLOCKED_RUNTIME_INTEGRATION_NOT_ALLOWED,
            run_dir=run_dir,
            output_dir=output_dir,
            topic_id=topic_id,
            user_feedback=user_feedback,
            reason="task_mode must be TOPIC_REFINEMENT for this CLI-only wrapper",
            write_report=_is_output_dir_allowed(output_dir),
        )
    if not dry_run:
        return _blocked(
            BLOCKED_DRY_RUN_REQUIRED,
            run_dir=run_dir,
            output_dir=output_dir,
            topic_id=topic_id,
            user_feedback=user_feedback,
            reason="dry_run=true is required in initial Slice 4",
            write_report=_is_output_dir_allowed(output_dir),
        )
    if not topic_id.strip():
        return _blocked(BLOCKED_INVALID_TOPIC_ID, run_dir=run_dir, output_dir=output_dir, topic_id=topic_id, user_feedback=user_feedback, reason="topic_id is empty", write_report=_is_output_dir_allowed(output_dir))
    if not user_feedback.strip():
        return _blocked(BLOCKED_INVALID_USER_FEEDBACK, run_dir=run_dir, output_dir=output_dir, topic_id=topic_id, user_feedback=user_feedback, reason="user_feedback is empty", write_report=_is_output_dir_allowed(output_dir))
    if not confirm_same_topic:
        return _blocked(BLOCKED_SAME_TOPIC_NOT_CONFIRMED, run_dir=run_dir, output_dir=output_dir, topic_id=topic_id, user_feedback=user_feedback, reason="confirm_same_topic=true is required", write_report=_is_output_dir_allowed(output_dir))
    if _contains_any(user_feedback, NEW_TOPIC_SIGNALS):
        return _blocked(BLOCKED_NEW_TOPIC_DETECTED, run_dir=run_dir, output_dir=output_dir, topic_id=topic_id, user_feedback=user_feedback, reason="user_feedback contains new-topic signal", write_report=_is_output_dir_allowed(output_dir))
    if expected_branch is not None and _current_branch() != expected_branch:
        return _blocked(BLOCKED_EXPECTED_BRANCH_MISMATCH, run_dir=run_dir, output_dir=output_dir, topic_id=topic_id, user_feedback=user_feedback, reason=f"expected_branch={expected_branch} actual_branch={_current_branch()}", write_report=_is_output_dir_allowed(output_dir))
    if expected_head is not None and _current_head() != expected_head:
        return _blocked(BLOCKED_EXPECTED_HEAD_MISMATCH, run_dir=run_dir, output_dir=output_dir, topic_id=topic_id, user_feedback=user_feedback, reason=f"expected_head={expected_head} actual_head={_current_head()}", write_report=_is_output_dir_allowed(output_dir))
    if not _is_output_dir_allowed(output_dir):
        return _blocked(BLOCKED_OUTPUT_ALREADY_EXISTS, run_dir=run_dir, output_dir=output_dir, topic_id=topic_id, user_feedback=user_feedback, reason="output_dir must be under outputs/ or temp", write_report=False)
    if output_dir.exists() and any(output_dir.iterdir()):
        return _blocked(BLOCKED_OUTPUT_ALREADY_EXISTS, run_dir=run_dir, output_dir=output_dir, topic_id=topic_id, user_feedback=user_feedback, reason="output_dir already exists and is not empty")
    if not run_dir.exists() or not run_dir.is_dir():
        return _blocked(BLOCKED_RUN_DIR_MISSING, run_dir=run_dir, output_dir=output_dir, topic_id=topic_id, user_feedback=user_feedback, reason="run_dir does not exist or is not a directory")

    output_dir.mkdir(parents=True, exist_ok=True)
    same_topic_warning = _same_topic_warning(user_feedback)

    loader_output = output_dir / "loader_output"
    loader_result = artifact_loader.load_artifacts(
        run_dir=run_dir,
        topic_id=topic_id,
        user_feedback=user_feedback,
        output_dir=loader_output,
        allow_source_acquisition=allow_source_acquisition,
        allow_full_text_verification=allow_full_text_verification,
    )
    if loader_result.exit_code != 0 or loader_result.state_path is None:
        return _blocked(
            BLOCKED_LOADER_FAILED,
            run_dir=run_dir,
            output_dir=output_dir,
            topic_id=topic_id,
            user_feedback=user_feedback,
            reason=f"loader failed with status {loader_result.status}",
            extra={"loader_result": loader_result.status, "loader_report": str(loader_result.report_json_path) if loader_result.report_json_path else None},
        )
    initial = _read_json(loader_result.state_path)

    router_output = output_dir / "router_output"
    router_result = mode_router.route_file(state_path=loader_result.state_path, output_dir=router_output)
    if router_result.exit_code != 0 or router_result.routed_state_path is None:
        return _blocked(
            BLOCKED_ROUTER_FAILED,
            run_dir=run_dir,
            output_dir=output_dir,
            topic_id=topic_id,
            user_feedback=user_feedback,
            reason=f"router failed with status {router_result.status}",
            extra={"loader_result": loader_result.status, "router_result": router_result.status, "router_report": str(router_result.report_json_path) if router_result.report_json_path else None},
        )
    routed = _read_json(router_result.routed_state_path)
    mode = routed.get("selected_refinement_mode")
    next_action = routed.get("next_action")

    validator_result: output_validator.ValidatorResult | None = None
    validator_report: dict[str, Any] | None = None
    handoff_prompt: Path | None = None
    generated_candidate_output: Path | None = None
    candidate_dir_for_validation: Path | None = candidate_refinement_dir
    status: str
    quality: str

    if mode == "environment_triage":
        candidate_dir_for_validation = output_dir / "candidate_output"
        generated_candidate_output = candidate_dir_for_validation
        _write_environment_candidate(candidate_dir_for_validation, routed)
        validator_result, validator_report = _run_validator(router_result.routed_state_path, candidate_dir_for_validation, output_dir / "validator_output")
        status = PASS_MANUAL_TASK_STOPPED_ENVIRONMENT_TRIAGE
        quality = QUALITY_STOPPED
    elif mode == "targeted_evidence_acquisition" and next_action == "source_need_or_full_text_verification":
        candidate_dir_for_validation = output_dir / "candidate_output"
        generated_candidate_output = candidate_dir_for_validation
        _write_source_need_candidate(candidate_dir_for_validation, routed)
        validator_result, validator_report = _run_validator(router_result.routed_state_path, candidate_dir_for_validation, output_dir / "validator_output")
        status = PASS_MANUAL_TASK_STOPPED_SOURCE_NEED
        quality = QUALITY_STOPPED
    elif mode == "targeted_evidence_acquisition" and next_action == "ready_for_authorized_source_acquisition_dry_run":
        candidate_dir_for_validation = output_dir / "candidate_output"
        generated_candidate_output = candidate_dir_for_validation
        _write_source_plan_candidate(candidate_dir_for_validation, routed)
        validator_result, validator_report = _run_validator(router_result.routed_state_path, candidate_dir_for_validation, output_dir / "validator_output")
        status = PASS_MANUAL_TASK_STOPPED_SOURCE_NEED
        quality = QUALITY_STOPPED
    elif mode in REWRITE_CAPABLE_MODES:
        handoff_prompt = _write_handoff_prompt(output_dir, initial, routed, user_feedback, allowed_refinement_scope)
        status = PASS_MANUAL_TASK_HANDOFF_READY
        quality = QUALITY_READY
        if allow_llm_refinement and candidate_refinement_dir is None:
            # Slice 4 does not call an LLM. The flag only permits a separately
            # generated candidate to be validated when a candidate dir is given.
            pass
        if candidate_refinement_dir is not None:
            validator_result, validator_report = _run_validator(router_result.routed_state_path, candidate_refinement_dir, output_dir / "validator_output")
            status = PASS_MANUAL_TASK_CANDIDATE_VALIDATED
            quality = QUALITY_VALIDATED
            generated_candidate_output = candidate_refinement_dir
    elif mode is None or next_action == "stop_no_actionable_refinement":
        candidate_dir_for_validation = output_dir / "candidate_output"
        generated_candidate_output = candidate_dir_for_validation
        _write_no_action_candidate(candidate_dir_for_validation, routed)
        validator_result, validator_report = _run_validator(router_result.routed_state_path, candidate_dir_for_validation, output_dir / "validator_output")
        status = PASS_MANUAL_TASK_STOPPED_NO_ACTION
        quality = QUALITY_STOPPED
    else:
        return _blocked(
            BLOCKED_ROUTER_FAILED,
            run_dir=run_dir,
            output_dir=output_dir,
            topic_id=topic_id,
            user_feedback=user_feedback,
            reason=f"unsupported router mode/action: {mode}/{next_action}",
            extra={"loader_result": loader_result.status, "router_result": router_result.status},
        )

    if validator_result is not None and validator_result.exit_code != 0:
        return _blocked(
            BLOCKED_VALIDATOR_FAILED,
            run_dir=run_dir,
            output_dir=output_dir,
            topic_id=topic_id,
            user_feedback=user_feedback,
            reason=f"validator failed with status {validator_result.status}",
            extra={
                "loader_result": loader_result.status,
                "router_result": router_result.status,
                "validator_result": validator_result.status,
                "validator_report": str(validator_result.report_json_path) if validator_result.report_json_path else None,
                "selected_failure_type": routed.get("selected_failure_type"),
                "selected_refinement_mode": routed.get("selected_refinement_mode"),
            },
        )

    return _success_report(
        status=status,
        quality_verdict=quality,
        run_dir=run_dir,
        output_dir=output_dir,
        topic_id=topic_id,
        user_feedback=user_feedback,
        loader_result=loader_result,
        router_result=router_result,
        initial=initial,
        routed=routed,
        validator_result=validator_result,
        validator_report=validator_report,
        handoff_prompt=handoff_prompt,
        generated_candidate_output=generated_candidate_output,
        same_topic_warning=same_topic_warning,
    )


def _run_validator(routed_state_path: Path, candidate_dir: Path, output_dir: Path) -> tuple[output_validator.ValidatorResult, dict[str, Any] | None]:
    result = output_validator.validate_output(
        routed_state_path=routed_state_path,
        refinement_dir=candidate_dir,
        output_dir=output_dir,
    )
    report = _load_optional_report(result.report_json_path)
    return result, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI-only manual Topic Refinement wrapper.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--topic-id", required=True)
    parser.add_argument("--user-feedback", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--confirm-same-topic", type=_parse_bool, default=False)
    parser.add_argument("--candidate-refinement-dir", type=Path, default=None)
    parser.add_argument("--allow-source-acquisition", type=_parse_bool, default=False)
    parser.add_argument("--allow-full-text-verification", type=_parse_bool, default=False)
    parser.add_argument("--allow-llm-refinement", type=_parse_bool, default=False)
    parser.add_argument("--expected-branch", default=None)
    parser.add_argument("--expected-head", default=None)
    parser.add_argument("--dry-run", type=_parse_bool, default=True)
    parser.add_argument("--strict", type=_parse_bool, default=True)
    parser.add_argument("--task-mode", default=TASK_MODE)
    parser.add_argument("--allowed-refinement-scope", default="bounded_refinement")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_manual_task(
        run_dir=args.run_dir,
        topic_id=args.topic_id,
        user_feedback=args.user_feedback,
        output_dir=args.output_dir,
        confirm_same_topic=args.confirm_same_topic,
        candidate_refinement_dir=args.candidate_refinement_dir,
        allow_source_acquisition=args.allow_source_acquisition,
        allow_full_text_verification=args.allow_full_text_verification,
        allow_llm_refinement=args.allow_llm_refinement,
        expected_branch=args.expected_branch,
        expected_head=args.expected_head,
        dry_run=args.dry_run,
        strict=args.strict,
        task_mode=args.task_mode,
        allowed_refinement_scope=args.allowed_refinement_scope,
    )
    print(result.status)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
