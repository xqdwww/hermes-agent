"""Opt-in long-run process and log observer for passive-intelligence metadata."""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.passive_intelligence_guard import (
    classify_error_kind,
    classify_long_run_event,
    compute_retry_signature,
    get_stage_timeout_policy,
)


DEFAULT_MAX_LOG_BYTES = 8192
DEFAULT_OBSERVER_TIMEOUT_SECONDS = 2.0
TAIL_EXCERPT_CHARS = 4000


@dataclass(frozen=True)
class LongRunObserverPolicy:
    observe: bool = False
    allow_process_probe: bool = False
    allow_log_read: bool = False
    max_log_bytes: int = DEFAULT_MAX_LOG_BYTES
    timeout_seconds: float = DEFAULT_OBSERVER_TIMEOUT_SECONDS
    require_explicit_pid_or_log_path: bool = True
    allow_process_control: bool = False
    allowed_log_roots: tuple[str, ...] = ()
    owner_tool: str = ""
    stage_name: str = "generic_subprocess"
    expected_silence_budget: float | None = None
    retry_limit_same_error: int | None = None
    retry_limit_total: int | None = None


@dataclass(frozen=True)
class LongRunProcessSnapshot:
    pid: int | None = None
    pid_supplied: bool = False
    probe_attempted: bool = False
    process_exists: bool | None = None
    process_status: str = "unknown"
    command_excerpt: str = ""
    elapsed_seconds: float | None = None
    cpu_percent: float | None = None
    memory_mb: float | None = None
    status_reason: str = "pid_not_supplied"


@dataclass(frozen=True)
class LongRunLogSnapshot:
    log_path: str = ""
    log_supplied: bool = False
    read_attempted: bool = False
    bytes_read: int = 0
    truncated: bool = False
    last_output_at: float | None = None
    tail_excerpt: str = ""
    error_signature: str = ""
    partial_output_present: bool = False
    status_reason: str = "log_path_not_supplied"


@dataclass(frozen=True)
class LongRunStatusSnapshot:
    task_id: str = ""
    owner_tool: str = ""
    stage_name: str = "generic_subprocess"
    process_snapshot: LongRunProcessSnapshot = field(default_factory=LongRunProcessSnapshot)
    log_snapshot: LongRunLogSnapshot = field(default_factory=LongRunLogSnapshot)
    elapsed_seconds: float = 0
    silence_seconds: float = 0
    retry_count: int = 0
    retry_count_same_error: int = 0
    current_error_signature: str = ""
    prior_error_signature: str = ""
    phase: str = ""
    subtask_statuses: dict[str, str] = field(default_factory=dict)
    process_status: str = "unknown"
    partial_output_present: bool = False
    timed_out: bool = False


@dataclass(frozen=True)
class LongRunObserverDecision:
    status: str
    should_wait: bool
    should_inspect: bool
    should_retry: bool
    should_block: bool
    blocked_reason: str
    warning_codes: tuple[str, ...]
    safe_next_action: str
    prohibited_claims: tuple[str, ...]
    user_facing_summary: str


@dataclass(frozen=True)
class LongRunDashboardSummary:
    task_id: str
    owner_tool: str
    stage_name: str
    status: str
    known_fields: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    warning_codes: tuple[str, ...]
    safe_next_action: str
    process: dict[str, Any]
    log: dict[str, Any]


def build_long_run_observer_policy(
    *,
    owner_tool: str | None = None,
    stage_name: str | None = None,
    observe: bool = False,
    allow_process_probe: bool = False,
    allow_log_read: bool = False,
    max_log_bytes: int = DEFAULT_MAX_LOG_BYTES,
    timeout_seconds: float = DEFAULT_OBSERVER_TIMEOUT_SECONDS,
    require_explicit_pid_or_log_path: bool = True,
    allowed_log_roots: tuple[str, ...] | list[str] | None = None,
    expected_silence_budget: float | None = None,
    retry_limit_same_error: int | None = None,
    retry_limit_total: int | None = None,
) -> LongRunObserverPolicy:
    policy = get_stage_timeout_policy(stage_name or "generic_subprocess", owner_tool or "")
    return LongRunObserverPolicy(
        observe=bool(observe),
        allow_process_probe=bool(allow_process_probe),
        allow_log_read=bool(allow_log_read),
        max_log_bytes=max(1, int(max_log_bytes or DEFAULT_MAX_LOG_BYTES)),
        timeout_seconds=max(0.1, float(timeout_seconds or DEFAULT_OBSERVER_TIMEOUT_SECONDS)),
        require_explicit_pid_or_log_path=bool(require_explicit_pid_or_log_path),
        allow_process_control=False,
        allowed_log_roots=tuple(str(item) for item in (allowed_log_roots or ())),
        owner_tool=(owner_tool or policy.owner_tool or "").strip(),
        stage_name=(stage_name or policy.stage_name or "generic_subprocess").strip(),
        expected_silence_budget=expected_silence_budget,
        retry_limit_same_error=retry_limit_same_error,
        retry_limit_total=retry_limit_total,
    )


def collect_long_run_observer_snapshot(
    policy: LongRunObserverPolicy,
    *,
    pid: int | str | None = None,
    log_path: str | None = None,
    supplied_state: dict[str, Any] | None = None,
) -> LongRunStatusSnapshot:
    state = supplied_state if isinstance(supplied_state, dict) else {}
    process_snapshot = maybe_probe_process_safely(pid, policy)
    log_snapshot = read_log_tail_safely(log_path, policy.max_log_bytes, allowed_roots=policy.allowed_log_roots) if _should_read_log(policy, log_path) else _log_snapshot_skipped(log_path, policy)
    current_signature = str(
        state.get("current_error_signature")
        or state.get("error_signature")
        or log_snapshot.error_signature
        or ""
    )
    prior_signature = str(state.get("prior_error_signature") or state.get("last_error_signature") or "")
    retry_same = _int_value(state.get("retry_count_same_error"), 0)
    if retry_same == 0 and current_signature and prior_signature and current_signature == prior_signature:
        retry_same = 1
    process_status = str(
        state.get("process_status")
        or state.get("status")
        or process_snapshot.process_status
        or "unknown"
    ).casefold()
    partial_output = bool(state.get("partial_output_present") or state.get("partial_output") or log_snapshot.partial_output_present)
    return LongRunStatusSnapshot(
        task_id=str(state.get("task_id") or ""),
        owner_tool=str(state.get("owner_tool") or policy.owner_tool or ""),
        stage_name=str(state.get("stage_name") or state.get("stage") or policy.stage_name or "generic_subprocess"),
        process_snapshot=process_snapshot,
        log_snapshot=log_snapshot,
        elapsed_seconds=_float_value(state.get("elapsed_seconds"), process_snapshot.elapsed_seconds or 0),
        silence_seconds=_float_value(state.get("silence_seconds"), _silence_from_log_snapshot(log_snapshot)),
        retry_count=_int_value(state.get("retry_count_total") or state.get("retry_count"), 0),
        retry_count_same_error=retry_same,
        current_error_signature=current_signature,
        prior_error_signature=prior_signature,
        phase=str(state.get("phase") or ""),
        subtask_statuses=_coerce_subtask_statuses(state.get("subtask_statuses")),
        process_status=process_status,
        partial_output_present=partial_output,
        timed_out=bool(state.get("timed_out") or "timeout" in process_status),
    )


def classify_long_run_observer_snapshot(
    snapshot: LongRunStatusSnapshot,
    policy: LongRunObserverPolicy,
) -> LongRunObserverDecision:
    status_needed = _status_needed(snapshot, policy)
    state = {
        "task_id": snapshot.task_id,
        "owner_tool": snapshot.owner_tool,
        "stage_name": snapshot.stage_name,
        "process_status": snapshot.process_status,
        "elapsed_seconds": snapshot.elapsed_seconds,
        "silence_seconds": snapshot.silence_seconds,
        "expected_silence_budget": policy.expected_silence_budget,
        "retry_count_same_error": snapshot.retry_count_same_error,
        "retry_count_total": snapshot.retry_count,
        "last_error_signature": snapshot.prior_error_signature,
        "current_error_signature": snapshot.current_error_signature,
        "partial_output_present": snapshot.partial_output_present,
        "incomplete_phases": tuple(
            name for name, value in snapshot.subtask_statuses.items() if value in {"running", "waiting", "partial", "blocked", "failed"}
        ),
    }
    decision = classify_long_run_event(state)
    warning_codes: list[str] = []
    if status_needed:
        warning_codes.append("LONG_RUN_OBSERVER_STATUS_NEEDED")
    if decision.blocked_reason == "silence_budget_exceeded":
        warning_codes.append("LONG_RUN_OBSERVER_SILENCE_BUDGET_EXCEEDED")
    if decision.status == "partial":
        warning_codes.append("LONG_RUN_OBSERVER_PARTIAL_OUTPUT")
    if decision.should_block:
        warning_codes.append("LONG_RUN_OBSERVER_BLOCKED")
    if snapshot.current_error_signature and _error_kind_requires_owner(snapshot.current_error_signature):
        warning_codes.append("LONG_RUN_OBSERVER_OWNER_ACTION_REQUIRED")
    prohibited = ("PASS", "completed", "done", "success") if decision.status in {"running", "waiting", "partial", "blocked", "unknown"} else ()
    status = "unknown" if status_needed and decision.status in {"", "unknown"} else decision.status or "unknown"
    safe_next = _safe_next_action(status_needed, decision.next_safe_action, status)
    summary = safe_long_run_observer_claim(
        LongRunObserverDecision(
            status=status,
            should_wait=decision.should_wait,
            should_inspect=decision.should_inspect or status_needed,
            should_retry=False,
            should_block=decision.should_block,
            blocked_reason=decision.blocked_reason,
            warning_codes=tuple(dict.fromkeys(warning_codes)),
            safe_next_action=safe_next,
            prohibited_claims=prohibited,
            user_facing_summary="",
        )
    )
    return LongRunObserverDecision(
        status=status,
        should_wait=decision.should_wait,
        should_inspect=decision.should_inspect or status_needed,
        should_retry=False,
        should_block=decision.should_block,
        blocked_reason=decision.blocked_reason,
        warning_codes=tuple(dict.fromkeys(warning_codes)),
        safe_next_action=safe_next,
        prohibited_claims=prohibited,
        user_facing_summary=summary,
    )


def build_long_run_dashboard_summary(
    snapshot: LongRunStatusSnapshot,
    decision: LongRunObserverDecision,
) -> dict[str, Any]:
    known: list[str] = []
    unknown: list[str] = []
    for field_name, value in (
        ("phase", snapshot.phase),
        ("process_status", snapshot.process_status if snapshot.process_status != "unknown" else ""),
        ("elapsed_seconds", snapshot.elapsed_seconds if snapshot.elapsed_seconds > 0 else None),
        ("silence_seconds", snapshot.silence_seconds if snapshot.silence_seconds > 0 else None),
        ("retry_count", snapshot.retry_count if snapshot.retry_count > 0 else None),
        ("error_signature", snapshot.current_error_signature),
        ("log_path", snapshot.log_snapshot.log_path),
        ("pid", snapshot.process_snapshot.pid),
    ):
        (known if value not in {None, ""} else unknown).append(field_name)
    summary = LongRunDashboardSummary(
        task_id=snapshot.task_id,
        owner_tool=snapshot.owner_tool,
        stage_name=snapshot.stage_name,
        status=decision.status,
        known_fields=tuple(known),
        unknown_fields=tuple(unknown),
        warning_codes=decision.warning_codes,
        safe_next_action=decision.safe_next_action,
        process=asdict(snapshot.process_snapshot),
        log=asdict(snapshot.log_snapshot),
    )
    return asdict(summary)


def safe_long_run_observer_claim(decision: LongRunObserverDecision) -> str:
    if decision.should_block:
        return f"Blocked: {decision.blocked_reason or 'owner action required'}."
    if decision.status in {"running", "waiting"}:
        return "Still running or waiting; inspect only when the silence or timeout policy requires it."
    if decision.status == "partial":
        return "Partial output or timeout state; do not report completed."
    if decision.status == "unknown":
        return "Status unknown; collect explicit process, log, or supplied state before making completion claims."
    if decision.status == "completed":
        return "Completed only if supplied status and verification evidence support it."
    return decision.safe_next_action or "Inspect status before reporting completion."


def reject_unsafe_observer_action(action: str) -> str | None:
    normalized = (action or "").strip().casefold().replace("-", "_")
    blocked_actions = {
        "start",
        "stop",
        "restart",
        "pause",
        "resume",
        "retry",
        "terminate",
        "signal",
        "control",
    }
    if normalized in blocked_actions:
        return "process_control_not_allowed"
    return None


def read_log_tail_safely(
    path: str | None,
    max_bytes: int,
    *,
    allowed_roots: tuple[str, ...] | list[str] = (),
) -> LongRunLogSnapshot:
    if not path:
        return LongRunLogSnapshot()
    log_path = Path(path)
    safe_max = max(1, int(max_bytes or DEFAULT_MAX_LOG_BYTES))
    try:
        stat_result = log_path.lstat()
        if log_path.is_symlink() and not _path_allowed(log_path, allowed_roots):
            return LongRunLogSnapshot(
                log_path=str(log_path),
                log_supplied=True,
                read_attempted=False,
                status_reason="symlink_requires_allowed_root",
            )
        if allowed_roots and not _path_allowed(log_path, allowed_roots):
            return LongRunLogSnapshot(
                log_path=str(log_path),
                log_supplied=True,
                read_attempted=False,
                status_reason="log_path_outside_allowed_roots",
            )
        size = stat_result.st_size
        offset = max(0, size - safe_max)
        with log_path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(safe_max)
        text = data.decode("utf-8", errors="replace")
        signature = compute_error_signature_from_tail(text)
        return LongRunLogSnapshot(
            log_path=str(log_path),
            log_supplied=True,
            read_attempted=True,
            bytes_read=len(data),
            truncated=offset > 0 or len(text) > TAIL_EXCERPT_CHARS,
            last_output_at=stat_result.st_mtime,
            tail_excerpt=text[-TAIL_EXCERPT_CHARS:],
            error_signature=signature,
            partial_output_present=bool(text.strip()),
            status_reason="ok",
        )
    except OSError as exc:
        return LongRunLogSnapshot(
            log_path=str(log_path),
            log_supplied=True,
            read_attempted=True,
            status_reason=f"read_failed:{exc.__class__.__name__}",
        )


def compute_log_output_freshness(last_output_at: float | None, *, now: float | None = None) -> str:
    if last_output_at is None:
        return "unknown"
    age = max(0, float(now if now is not None else time.time()) - float(last_output_at))
    if age <= 60:
        return "fresh"
    if age <= 600:
        return "recent"
    return "stale"


def compute_error_signature_from_tail(tail_text: str | None) -> str:
    text = tail_text or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    error_lines = [
        line
        for line in lines
        if re.search(r"error|failed|denied|timeout|quota|auth|session|not found|traceback|exception", line, re.I)
    ]
    sample = error_lines[-1] if error_lines else (lines[-1] if lines else "")
    return compute_retry_signature(sample) if sample else ""


def maybe_probe_process_safely(pid: int | str | None, policy: LongRunObserverPolicy) -> LongRunProcessSnapshot:
    parsed_pid = _parse_pid(pid)
    if parsed_pid is None:
        return LongRunProcessSnapshot(pid=None, pid_supplied=False, status_reason="pid_not_supplied")
    if not (policy.observe and policy.allow_process_probe):
        return LongRunProcessSnapshot(pid=parsed_pid, pid_supplied=True, status_reason="process_probe_disabled")
    argv = ["ps", "-p", str(parsed_pid), "-o", "pid=,stat=,etime=,pcpu=,rss=,command="]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=policy.timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return LongRunProcessSnapshot(
            pid=parsed_pid,
            pid_supplied=True,
            probe_attempted=True,
            process_exists=None,
            process_status="unknown",
            status_reason=f"process_probe_failed:{exc.__class__.__name__}",
        )
    if completed.returncode != 0 or not completed.stdout.strip():
        return LongRunProcessSnapshot(
            pid=parsed_pid,
            pid_supplied=True,
            probe_attempted=True,
            process_exists=False,
            process_status="unknown",
            status_reason="process_not_found_or_inaccessible",
        )
    return _parse_ps_snapshot(parsed_pid, completed.stdout)


def _parse_ps_snapshot(pid: int, output: str) -> LongRunProcessSnapshot:
    line = output.strip().splitlines()[0] if output.strip() else ""
    parts = line.split(maxsplit=5)
    if len(parts) < 2:
        return LongRunProcessSnapshot(
            pid=pid,
            pid_supplied=True,
            probe_attempted=True,
            process_exists=True,
            process_status="unknown",
            status_reason="ps_output_unparseable",
        )
    stat = parts[1]
    status = _process_status_from_stat(stat)
    elapsed = _parse_elapsed_seconds(parts[2]) if len(parts) > 2 else None
    cpu = _optional_float(parts[3]) if len(parts) > 3 else None
    rss_kb = _optional_float(parts[4]) if len(parts) > 4 else None
    command = parts[5] if len(parts) > 5 else ""
    return LongRunProcessSnapshot(
        pid=pid,
        pid_supplied=True,
        probe_attempted=True,
        process_exists=True,
        process_status=status,
        command_excerpt=command[:240],
        elapsed_seconds=elapsed,
        cpu_percent=cpu,
        memory_mb=None if rss_kb is None else round(rss_kb / 1024, 3),
        status_reason="ok",
    )


def _parse_elapsed_seconds(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        day_text, text = text.split("-", 1)
        try:
            days = int(day_text)
        except ValueError:
            return None
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = (int(item) for item in parts)
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = (int(item) for item in parts)
        else:
            return None
    except ValueError:
        return None
    return float(days * 86400 + hours * 3600 + minutes * 60 + seconds)


def _process_status_from_stat(stat: str) -> str:
    marker = (stat or "").strip()[:1].upper()
    if marker == "Z":
        return "zombie"
    if marker in {"R", "S", "I", "D", "T", "W"}:
        return "running"
    return "unknown"


def _should_read_log(policy: LongRunObserverPolicy, log_path: str | None) -> bool:
    return bool(policy.observe and policy.allow_log_read and log_path)


def _log_snapshot_skipped(log_path: str | None, policy: LongRunObserverPolicy) -> LongRunLogSnapshot:
    if not log_path:
        return LongRunLogSnapshot()
    reason = "observation_disabled" if not policy.observe else "log_read_disabled"
    return LongRunLogSnapshot(log_path=str(log_path), log_supplied=True, status_reason=reason)


def _status_needed(snapshot: LongRunStatusSnapshot, policy: LongRunObserverPolicy) -> bool:
    if not policy.require_explicit_pid_or_log_path:
        return False
    has_process_status = snapshot.process_status not in {"", "unknown"}
    has_log_status = snapshot.log_snapshot.read_attempted or bool(snapshot.log_snapshot.tail_excerpt)
    has_supplied_status = has_process_status and snapshot.process_status not in {"unknown"}
    return not (snapshot.process_snapshot.pid_supplied or snapshot.log_snapshot.log_supplied or has_log_status or has_supplied_status)


def _safe_next_action(status_needed: bool, classifier_action: str, status: str) -> str:
    if status_needed:
        return "Provide explicit PID, bounded log path, or supplied status before making completion claims."
    if status in {"running", "waiting"}:
        return classifier_action or "Wait within budget or inspect after silence threshold."
    if status == "partial":
        return "Inspect partial output and report partial status."
    if status == "blocked":
        return "Surface the blocked reason to the owner."
    return classifier_action or "Inspect status before closure."


def _error_kind_requires_owner(signature: str) -> bool:
    return classify_error_kind(signature) in {"auth", "session", "quota", "permission", "path"}


def _silence_from_log_snapshot(log_snapshot: LongRunLogSnapshot) -> float:
    if log_snapshot.last_output_at is None:
        return 0
    return max(0, time.time() - float(log_snapshot.last_output_at))


def _path_allowed(path: Path, allowed_roots: tuple[str, ...] | list[str]) -> bool:
    if not allowed_roots:
        return False
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return False
    for root in allowed_roots:
        try:
            resolved.relative_to(Path(root).resolve(strict=False))
            return True
        except (OSError, ValueError):
            continue
    return False


def _coerce_subtask_statuses(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(item).casefold() for key, item in value.items()}
    if isinstance(value, list):
        statuses: dict[str, str] = {}
        for index, item in enumerate(value, start=1):
            if isinstance(item, dict):
                name = str(item.get("subtask_id") or item.get("name") or item.get("stage_name") or f"subtask_{index}")
                statuses[name] = str(item.get("status") or item.get("task_status") or "unknown").casefold()
        return statuses
    return {}


def _parse_pid(value: int | str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _float_value(value: Any, default: float) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "LongRunDashboardSummary",
    "LongRunLogSnapshot",
    "LongRunObserverDecision",
    "LongRunObserverPolicy",
    "LongRunProcessSnapshot",
    "LongRunStatusSnapshot",
    "build_long_run_dashboard_summary",
    "build_long_run_observer_policy",
    "classify_long_run_observer_snapshot",
    "collect_long_run_observer_snapshot",
    "compute_error_signature_from_tail",
    "compute_log_output_freshness",
    "maybe_probe_process_safely",
    "read_log_tail_safely",
    "reject_unsafe_observer_action",
    "safe_long_run_observer_claim",
]
