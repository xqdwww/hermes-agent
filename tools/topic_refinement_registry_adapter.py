#!/usr/bin/env python3
"""Explicit-only registry adapter for Topic Refinement.

This module is intentionally standalone. It accepts only explicit
TOPIC_REFINEMENT requests, delegates to the sealed CLI/manual wrapper, and does
not register a runtime route, call an LLM, rerun the Research/Decision
pipeline, acquire evidence, or rewrite final_v1.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import topic_refinement_manual_task as manual_task
from tools import topic_refinement_output_validator as output_validator

TASK_MODE = "TOPIC_REFINEMENT"
ADAPTER_VERSION = "explicit-registry-adapter-r1"
ADAPTER_MODE = "explicit_only"
REGISTRY_DESCRIPTION = (
    "Use only when the user explicitly asks to continue/refine an existing "
    "Research/Decision topic and provides prior run artifacts or topic state. "
    "Do not use for new topics, full reruns, evidence acquisition, or "
    "automatic post-final retries."
)

PASS_STATUS = "PASS_EXPLICIT_TOPIC_REFINEMENT_ADAPTER"
BLOCKED_TASK_MODE_REQUIRED = "BLOCKED_TASK_MODE_REQUIRED"
BLOCKED_UNSUPPORTED_TASK_MODE = "BLOCKED_UNSUPPORTED_TASK_MODE"
BLOCKED_SAME_TOPIC_NOT_CONFIRMED = "BLOCKED_SAME_TOPIC_NOT_CONFIRMED"
BLOCKED_MISSING_TOPIC_ID = "BLOCKED_MISSING_TOPIC_ID"
BLOCKED_MISSING_USER_FEEDBACK = "BLOCKED_MISSING_USER_FEEDBACK"
BLOCKED_MISSING_RUN_CONTEXT = "BLOCKED_MISSING_RUN_CONTEXT"
BLOCKED_RUN_CONTEXT_MISSING = "BLOCKED_RUN_CONTEXT_MISSING"
BLOCKED_TOPIC_STATE_INVALID = "BLOCKED_TOPIC_STATE_INVALID"
BLOCKED_TOPIC_STATE_RUN_DIR_UNRESOLVED = "BLOCKED_TOPIC_STATE_RUN_DIR_UNRESOLVED"
BLOCKED_NEW_TOPIC_DETECTED = "BLOCKED_NEW_TOPIC_DETECTED"
BLOCKED_FULL_RERUN_REQUESTED = "BLOCKED_FULL_RERUN_REQUESTED"
BLOCKED_SOURCE_ACQUISITION_REQUESTED = "BLOCKED_SOURCE_ACQUISITION_REQUESTED"
BLOCKED_FULL_TEXT_VERIFICATION_REQUESTED = "BLOCKED_FULL_TEXT_VERIFICATION_REQUESTED"
BLOCKED_REPORT_OR_RUNTIME_TASK = "BLOCKED_REPORT_OR_RUNTIME_TASK"
BLOCKED_DRY_RUN_REQUIRED = "BLOCKED_DRY_RUN_REQUIRED"
BLOCKED_LLM_REFINEMENT_NOT_ALLOWED = "BLOCKED_LLM_REFINEMENT_NOT_ALLOWED"
BLOCKED_OUTPUT_ALREADY_EXISTS = "BLOCKED_OUTPUT_ALREADY_EXISTS"
BLOCKED_MANUAL_TASK_FAILED = "BLOCKED_MANUAL_TASK_FAILED"

QUALITY_READY = "TOPIC_REFINEMENT_EXPLICIT_ADAPTER_READY"
QUALITY_BLOCKED = "TOPIC_REFINEMENT_EXPLICIT_ADAPTER_BLOCKED"

NEW_TOPIC_SIGNALS = (
    "新问题",
    "换个话题",
    "另一个问题",
    "另一个行业",
    "全新的",
    "new topic",
    "different topic",
    "another topic",
    "unrelated",
    "ignore previous",
    "start over",
)

FULL_RERUN_SIGNALS = (
    "full rerun",
    "full pipeline rerun",
    "rerun the research/decision pipeline",
    "complete task engine pipeline",
    "run the complete task engine pipeline",
    "全部从头",
    "从头跑",
    "重新研究",
    "全量重跑",
)

SOURCE_ACQUISITION_SIGNALS = (
    "查最新资料",
    "更新所有证据",
    "acquire new sources",
    "source acquisition",
    "fetch new evidence",
    "retrieve new sources",
    "new evidence acquired",
)

FULL_TEXT_VERIFICATION_SIGNALS = (
    "perform full-text verification",
    "full-text verification request",
    "full text verification request",
    "full-text verification completed",
    "full_text_verified: true",
    "全文验证",
)

OTHER_TASK_SIGNALS = (
    "生成一个新报告",
    "new report",
    "general advice",
    "travel migration",
    "travel-specific migration",
    "final controller",
    "evidence packet",
    "blind-set",
    "blind set",
    "push/release",
    "push this",
    "release this",
    "merge/reset/stash",
    "runtime registry bugs",
    "task engine runtime",
    "修 environment",
    "environment blocker",
    "ddgs missing",
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


@dataclass(frozen=True)
class AdapterPaths:
    output_dir: Path
    manual_output_dir: Path
    adapter_result_json: Path
    adapter_result_md: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_repo_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return _repo_root() / path


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


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _is_negated(text: str, index: int) -> bool:
    window = text[max(0, index - 28) : index].lower()
    return any(prefix in window for prefix in NEGATION_PREFIXES)


def _find_unnegated(text: str, signals: tuple[str, ...]) -> str | None:
    lower = text.lower()
    for signal in signals:
        start = 0
        needle = signal.lower()
        while True:
            index = lower.find(needle, start)
            if index < 0:
                break
            if not _is_negated(lower, index):
                return signal
            start = index + len(needle)
    return None


def _combined_request_text(payload: dict[str, Any]) -> str:
    fields = [
        payload.get("prompt"),
        payload.get("user_prompt"),
        payload.get("user_request"),
        payload.get("user_feedback"),
        payload.get("task"),
        payload.get("description"),
    ]
    return "\n".join(str(field) for field in fields if field is not None)


def _base_result(payload: dict[str, Any], *, status: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "quality_verdict": QUALITY_READY if status == PASS_STATUS else QUALITY_BLOCKED,
        "adapter_version": ADAPTER_VERSION,
        "adapter_mode": ADAPTER_MODE,
        "registry_description": REGISTRY_DESCRIPTION,
        "generated_at_utc": _utc_now(),
        "task_mode": payload.get("task_mode"),
        "topic_id": payload.get("topic_id"),
        "reason": reason,
        "manual_task_result": None,
        "selected_failure_type": None,
        "selected_refinement_mode": None,
        "no_auto_invocation": True,
        "no_final_controller_hook": True,
        "no_automatic_post_final_execution": True,
        "no_post_final_auto_retry": True,
        "no_pipeline_rerun": True,
        "no_llm_called": True,
        "no_source_acquisition": True,
        "no_full_text_verification_claim": True,
        "validator_mandatory_if_candidate": True,
        "final_v1_append_only_preserved": True,
    }


def _blocked(payload: dict[str, Any], status: str, reason: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _base_result(payload, status=status, reason=reason)
    if extra:
        result.update(extra)
    return result


def _candidate_exists(payload: dict[str, Any]) -> bool:
    candidate_dir = _resolve_repo_path(payload.get("candidate_refinement_dir"))
    return bool(candidate_dir is not None and candidate_dir.exists() and candidate_dir.is_dir())


def _resolve_run_context(payload: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    run_dir = _resolve_repo_path(payload.get("run_dir"))
    if run_dir is not None:
        return run_dir, None

    topic_state_path = _resolve_repo_path(payload.get("topic_state_path"))
    if topic_state_path is None:
        return None, None
    if not topic_state_path.exists() or not topic_state_path.is_file():
        return None, _blocked(payload, BLOCKED_RUN_CONTEXT_MISSING, "topic_state_path does not exist")
    try:
        state = _read_json(topic_state_path)
    except json.JSONDecodeError:
        return None, _blocked(payload, BLOCKED_TOPIC_STATE_INVALID, "topic_state_path is not valid JSON")

    artifact_paths = state.get("artifact_paths") if isinstance(state.get("artifact_paths"), dict) else {}
    final_path_value = artifact_paths.get("final_v1") or state.get("current_final_version_path")
    final_path = _resolve_repo_path(final_path_value)
    if final_path is None or not final_path.exists():
        return None, _blocked(payload, BLOCKED_TOPIC_STATE_RUN_DIR_UNRESOLVED, "topic_state_path does not resolve to an existing final_v1")
    return final_path.parent, None


def _output_paths(output_dir: Path) -> AdapterPaths:
    return AdapterPaths(
        output_dir=output_dir,
        manual_output_dir=output_dir / "manual_task_output",
        adapter_result_json=output_dir / "adapter_result.json",
        adapter_result_md=output_dir / "adapter_result.md",
    )


def validate_registry_request(payload: dict) -> dict:
    """Validate explicit registry invocation without running the manual chain."""

    if not isinstance(payload, dict):
        return _blocked({}, BLOCKED_TASK_MODE_REQUIRED, "payload must be a JSON object")

    task_mode = payload.get("task_mode")
    if task_mode is None or str(task_mode).strip() == "":
        return _blocked(payload, BLOCKED_TASK_MODE_REQUIRED, "explicit task_mode=TOPIC_REFINEMENT is required")
    if task_mode != TASK_MODE:
        return _blocked(payload, BLOCKED_UNSUPPORTED_TASK_MODE, "only task_mode=TOPIC_REFINEMENT is accepted")

    if not _as_bool(payload.get("confirm_same_topic")):
        return _blocked(payload, BLOCKED_SAME_TOPIC_NOT_CONFIRMED, "confirm_same_topic=true is required")
    if not str(payload.get("topic_id") or "").strip():
        return _blocked(payload, BLOCKED_MISSING_TOPIC_ID, "topic_id is required")
    if not str(payload.get("user_feedback") or "").strip():
        return _blocked(payload, BLOCKED_MISSING_USER_FEEDBACK, "user_feedback is required")

    run_dir, run_context_block = _resolve_run_context(payload)
    if run_context_block is not None:
        return run_context_block
    if run_dir is None:
        return _blocked(payload, BLOCKED_MISSING_RUN_CONTEXT, "run_dir or topic_state_path is required")
    if not run_dir.exists() or not run_dir.is_dir():
        return _blocked(payload, BLOCKED_RUN_CONTEXT_MISSING, "run_dir does not exist or is not a directory")

    text = _combined_request_text(payload)
    signal = _find_unnegated(text, NEW_TOPIC_SIGNALS)
    if signal:
        return _blocked(payload, BLOCKED_NEW_TOPIC_DETECTED, f"request contains new-topic signal: {signal}")
    signal = _find_unnegated(text, FULL_RERUN_SIGNALS)
    if signal:
        return _blocked(payload, BLOCKED_FULL_RERUN_REQUESTED, f"request implies a full rerun: {signal}")
    signal = _find_unnegated(text, SOURCE_ACQUISITION_SIGNALS)
    if signal:
        return _blocked(payload, BLOCKED_SOURCE_ACQUISITION_REQUESTED, f"request implies source acquisition: {signal}")
    signal = _find_unnegated(text, FULL_TEXT_VERIFICATION_SIGNALS)
    if signal:
        return _blocked(payload, BLOCKED_FULL_TEXT_VERIFICATION_REQUESTED, f"request implies full-text verification: {signal}")
    signal = _find_unnegated(text, OTHER_TASK_SIGNALS)
    if signal:
        return _blocked(payload, BLOCKED_REPORT_OR_RUNTIME_TASK, f"request is outside explicit topic refinement scope: {signal}")

    if not _as_bool(payload.get("dry_run"), default=True):
        return _blocked(payload, BLOCKED_DRY_RUN_REQUIRED, "dry_run=false is not supported in this adapter stub")
    if _as_bool(payload.get("allow_source_acquisition"), default=False):
        return _blocked(payload, BLOCKED_SOURCE_ACQUISITION_REQUESTED, "source acquisition is not performed by this adapter stub")
    if _as_bool(payload.get("allow_full_text_verification"), default=False):
        return _blocked(payload, BLOCKED_FULL_TEXT_VERIFICATION_REQUESTED, "full-text verification is not performed by this adapter stub")
    if _as_bool(payload.get("allow_llm_refinement"), default=False) and not _candidate_exists(payload):
        return _blocked(
            payload,
            BLOCKED_LLM_REFINEMENT_NOT_ALLOWED,
            "allow_llm_refinement=true requires an existing candidate_refinement_dir for validator-gated review",
        )

    return {
        "status": "PASS_REGISTRY_REQUEST_VALIDATION",
        "quality_verdict": QUALITY_READY,
        "adapter_mode": ADAPTER_MODE,
        "task_mode": TASK_MODE,
        "run_dir": str(run_dir),
        "topic_id": str(payload.get("topic_id")).strip(),
        "no_auto_invocation": True,
        "no_final_controller_hook": True,
        "no_pipeline_rerun": True,
        "no_llm_called": True,
        "no_source_acquisition": True,
        "validator_mandatory_if_candidate": True,
    }


def _load_manual_payload(result: manual_task.ManualTaskResult) -> dict[str, Any] | None:
    if result.report_json_path is None or not result.report_json_path.exists():
        return None
    try:
        return _read_json(result.report_json_path)
    except (OSError, json.JSONDecodeError):
        return None


def _manual_consumed_candidate(manual_payload: dict[str, Any] | None, candidate_dir: Path | None) -> bool:
    if manual_payload is None or candidate_dir is None:
        return False
    manual_candidate = manual_payload.get("candidate_refinement_dir")
    if not manual_candidate:
        return False
    return Path(manual_candidate).resolve(strict=False) == candidate_dir.resolve(strict=False)


def _run_adapter_candidate_validator(
    *,
    routed_state_path: Path,
    candidate_dir: Path,
    output_dir: Path,
) -> tuple[output_validator.ValidatorResult, dict[str, Any] | None]:
    result = output_validator.validate_output(
        routed_state_path=routed_state_path,
        refinement_dir=candidate_dir,
        output_dir=output_dir,
    )
    if result.report_json_path is None or not result.report_json_path.exists():
        return result, None
    try:
        return result, _read_json(result.report_json_path)
    except (OSError, json.JSONDecodeError):
        return result, None


def run_topic_refinement_registry_adapter(payload: dict) -> dict:
    """Run explicit Topic Refinement by delegating to the manual CLI chain."""

    output_dir = _resolve_repo_path(payload.get("output_dir")) or _repo_root() / "outputs" / "topic_refinement_registry_adapter"
    paths = _output_paths(output_dir)

    validation = validate_registry_request(payload)
    if validation.get("status") != "PASS_REGISTRY_REQUEST_VALIDATION":
        if validation.get("status") != BLOCKED_OUTPUT_ALREADY_EXISTS and not (output_dir.exists() and any(output_dir.iterdir())):
            _write_json(paths.adapter_result_json, validation)
            _write_report_md(paths.adapter_result_md, "Topic Refinement Registry Adapter Result", validation)
        return validation

    if output_dir.exists() and any(output_dir.iterdir()):
        return _blocked(payload, BLOCKED_OUTPUT_ALREADY_EXISTS, "output_dir already exists and is not empty")

    run_dir = Path(validation["run_dir"])
    candidate_dir = _resolve_repo_path(payload.get("candidate_refinement_dir"))
    manual_result = manual_task.run_manual_task(
        run_dir=run_dir,
        topic_id=str(payload.get("topic_id")).strip(),
        user_feedback=str(payload.get("user_feedback")).strip(),
        output_dir=paths.manual_output_dir,
        confirm_same_topic=True,
        candidate_refinement_dir=candidate_dir,
        allow_source_acquisition=False,
        allow_full_text_verification=False,
        allow_llm_refinement=_as_bool(payload.get("allow_llm_refinement"), default=False),
        expected_branch=payload.get("expected_branch"),
        expected_head=payload.get("expected_head"),
        dry_run=True,
        task_mode=TASK_MODE,
    )
    manual_payload = _load_manual_payload(manual_result)
    status = PASS_STATUS if manual_result.exit_code == 0 else BLOCKED_MANUAL_TASK_FAILED
    result = _base_result(payload, status=status, reason=None if manual_result.exit_code == 0 else manual_result.status)
    result.update(
        {
            "quality_verdict": QUALITY_READY if manual_result.exit_code == 0 else QUALITY_BLOCKED,
            "run_dir": str(run_dir),
            "output_dir": str(output_dir),
            "manual_output_dir": str(paths.manual_output_dir),
            "manual_task_result": manual_payload
            or {
                "status": manual_result.status,
                "report_json_path": str(manual_result.report_json_path) if manual_result.report_json_path else None,
                "report_md_path": str(manual_result.report_md_path) if manual_result.report_md_path else None,
            },
            "selected_failure_type": (manual_payload or {}).get("selected_failure_type"),
            "selected_refinement_mode": (manual_payload or {}).get("selected_refinement_mode"),
            "manual_task_report_json": str(manual_result.report_json_path) if manual_result.report_json_path else None,
            "manual_task_report_md": str(manual_result.report_md_path) if manual_result.report_md_path else None,
            "manual_task_report_preserved": bool(manual_result.report_json_path and manual_result.report_json_path.exists()),
        }
    )
    if manual_payload:
        result["no_pipeline_rerun"] = bool(manual_payload.get("no_pipeline_rerun", True))
        result["no_llm_called"] = bool(manual_payload.get("no_llm_called", True))
        result["no_source_acquisition"] = bool(manual_payload.get("no_evidence_acquisition_performed", True))
        result["final_v1_append_only_preserved"] = bool((manual_payload.get("final_v1_overwrite_check") or {}).get("pass", True))

    if (
        candidate_dir is not None
        and candidate_dir.exists()
        and manual_result.exit_code == 0
        and not _manual_consumed_candidate(manual_payload, candidate_dir)
    ):
        routed_state_path = paths.manual_output_dir / "router_output" / "topic_refinement_state.routed.json"
        candidate_validator_result, candidate_validator_payload = _run_adapter_candidate_validator(
            routed_state_path=routed_state_path,
            candidate_dir=candidate_dir,
            output_dir=output_dir / "adapter_candidate_validator_output",
        )
        result["adapter_candidate_validator_result"] = candidate_validator_result.status
        result["adapter_candidate_validator_report"] = (
            str(candidate_validator_result.report_json_path) if candidate_validator_result.report_json_path else None
        )
        if candidate_validator_result.exit_code != 0:
            result.update(
                {
                    "status": BLOCKED_MANUAL_TASK_FAILED,
                    "quality_verdict": QUALITY_BLOCKED,
                    "reason": candidate_validator_result.status,
                    "manual_task_result": dict(manual_payload or {}),
                    "selected_failure_type": (manual_payload or {}).get("selected_failure_type"),
                    "selected_refinement_mode": (manual_payload or {}).get("selected_refinement_mode"),
                }
            )
            if result["manual_task_result"]:
                result["manual_task_result"]["validator_result"] = candidate_validator_result.status
                result["manual_task_result"]["adapter_candidate_validator_report"] = (
                    str(candidate_validator_result.report_json_path) if candidate_validator_result.report_json_path else None
                )
        elif candidate_validator_payload:
            result["adapter_candidate_validator_payload"] = candidate_validator_payload

    _write_json(paths.adapter_result_json, result)
    _write_report_md(paths.adapter_result_md, "Topic Refinement Registry Adapter Result", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explicit-only TOPIC_REFINEMENT registry adapter.")
    parser.add_argument("--request-json", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = _read_json(args.request_json)
    payload["output_dir"] = str(args.output_dir)
    result = run_topic_refinement_registry_adapter(payload)
    print(result["status"])
    return 0 if result["status"] == PASS_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
