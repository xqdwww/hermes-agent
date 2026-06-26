"""Pure deterministic guard helpers for Hermes passive intelligence phase 0."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any


TASK_STATUSES = {"pending", "running", "completed", "partial", "blocked", "failed"}
VERIFICATION_STATUSES = {"not_required", "required", "verified", "unverified", "stale"}

SKILL_TRIGGER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("codex_handoff", ("Codex", "patch", "repo", "pytest", "refactor", "bug fix", "修改代码", "写测试")),
    ("wait_watchdog", ("waiting", "timeout", "silent", "no output", "stuck", "卡住", "等待", "没返回", "AGY", "GPT Bridge", "subprocess")),
    (
        "git_safety",
        (
            "git status", "commit", "tag", "push", "branch", "HEAD", "worktree", "merge",
            "origin", "fork", "upstream", "git push", "remote tag", "write access",
            "ssh.github.com", "github.com:443", "known_hosts", "force push",
        ),
    ),
    ("browser_execution", ("OpenClaw", "browser", "Chrome Canary", "GUI", "login", "download", "screenshot", "浏览器", "下载")),
    ("document_validation", ("PDF", "OCR", "render", "Preview", "qlmanage", "pymupdf", "文件完整性", "截断")),
    ("travel_evidence", ("Travel", "Series B", "source acquisition", "OCR", "vectorization", "evidence packet", "旅行知识库")),
    ("stage_duty", ("Run DECISION", "Run RESEARCH_DECISION", "external_calibration", "final_controller", "StageRecord")),
)


@dataclass(frozen=True)
class PermissionDecision:
    decision: str
    reason: str
    required_owner: str
    blocked_by_default: bool
    safe_next_action: str


@dataclass(frozen=True)
class StatusLedger:
    task_id: str
    project_id: str
    task_status: str = "pending"
    subtask_statuses: dict[str, str] = field(default_factory=dict)
    current_phase: str = ""
    files_read: tuple[str, ...] = ()
    files_written: tuple[str, ...] = ()
    verification_status: str = "not_required"
    dry_run: bool = False
    report_only: bool = False
    local_pass: bool = False
    remote_pushed: bool = False
    remote_confirmed: bool = False
    local_tag: str = ""
    remote_tag: str = ""
    official_updated: bool = False
    production_changed: bool = False
    blocked_reason: str = ""
    next_allowed_action: str = ""
    forbidden_actions: tuple[str, ...] = ()
    updated_at: str = ""
    accepted_partial: bool = False
    event_counter: int = 0
    latest_modification_event_id: int | None = None
    latest_verification_event_id: int | None = None
    latest_modification_at: str = ""
    latest_verification_at: str = ""
    invariant_violations: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationDecision:
    verified: bool
    reason: str
    verification_status: str
    latest_modification_event_id: int | None
    latest_verification_event_id: int | None
    safe_next_action: str


@dataclass(frozen=True)
class ConsistencyDecision:
    consistent: bool
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    safe_next_action: str = ""


@dataclass(frozen=True)
class WatchdogDecision:
    should_wait: bool
    should_inspect: bool
    should_retry: bool
    should_block: bool
    blocked_reason: str
    next_safe_action: str
    status: str = "running"


@dataclass(frozen=True)
class RemoteSyncDecision:
    decision: str
    reason: str
    recommended_remote: str
    branch_push_allowed: bool
    tag_push_allowed: bool
    blocked_by_default: bool
    safe_next_action: str
    warnings: tuple[str, ...] = ()


def classify_skill_triggers(user_request: str) -> list[str]:
    haystack = (user_request or "").casefold()
    return [
        name
        for name, triggers in SKILL_TRIGGER_RULES
        if any(_trigger_matches(haystack, trigger) for trigger in triggers)
    ]


def classify_action_permission(action: dict[str, Any]) -> PermissionDecision:
    data = action if isinstance(action, dict) else {}
    text = _action_text(data)
    dry_run = _bool_context(data, "dry_run")
    report_only = _bool_context(data, "report_only")

    if _is_git_force_push(text):
        return _decision("blocked", "git_force_push_blocked", "user", True, "Do not force push; ask the user for an explicit recovery plan.")
    if report_only and _is_write_action(data, text) and not _is_report_artifact(data):
        return _decision("blocked", "report_only_non_report_write_blocked", "hermes", True, "Keep the task report-only or ask the user to authorize a scope change.")
    if dry_run and _is_official_update(data, text):
        return _decision("blocked", "dry_run_official_update_blocked", "hermes", True, "Keep official state unchanged; rerun without dry_run only after user authorization.")
    if _is_browser_gui_action(text):
        return _decision("openclaw_required", "browser_gui_execution_requires_openclaw", "openclaw", True, "Hand off to OpenClaw with explicit GUI/browser authorization.")
    user_authorization_reason = _user_authorization_reason(data, text)
    if user_authorization_reason:
        return _decision("user_authorization_required", user_authorization_reason, "user", True, "Ask the user to authorize this exact action before proceeding.")
    if _requires_codex(data, text):
        return _decision("codex_required", "code_change_requires_codex", "codex", True, "Create a Codex handoff or execute the code change through Codex.")
    if _is_allowed_hermes_action(text):
        return _decision("allowed", "read_only_or_report_action_allowed", "hermes", False, "Proceed locally without mutating external or production state.")
    return _decision("allowed", "no_guard_rule_matched", "hermes", False, "Proceed, preserving ledger and verification requirements.")


def initialize_status_ledger(task: dict[str, Any]) -> StatusLedger:
    data = task if isinstance(task, dict) else {}
    ledger = StatusLedger(
        task_id=str(data.get("task_id") or data.get("id") or ""),
        project_id=str(data.get("project_id") or data.get("project") or ""),
        task_status=_coerce_status(data.get("task_status") or data.get("status") or "pending"),
        subtask_statuses=_coerce_subtasks(data.get("subtask_statuses") or {}),
        current_phase=str(data.get("current_phase") or ""),
        files_read=tuple(str(item) for item in data.get("files_read") or ()),
        files_written=tuple(str(item) for item in data.get("files_written") or ()),
        verification_status=_coerce_verification(data.get("verification_status") or "not_required"),
        dry_run=bool(data.get("dry_run", False)),
        report_only=bool(data.get("report_only", False)),
        local_pass=bool(data.get("local_pass", False)),
        remote_pushed=bool(data.get("remote_pushed", False)),
        remote_confirmed=bool(data.get("remote_confirmed", False)),
        local_tag=str(data.get("local_tag") or ""),
        remote_tag=str(data.get("remote_tag") or ""),
        official_updated=bool(data.get("official_updated", False)),
        production_changed=bool(data.get("production_changed", False)),
        blocked_reason=str(data.get("blocked_reason") or ""),
        next_allowed_action=str(data.get("next_allowed_action") or ""),
        forbidden_actions=tuple(str(item) for item in data.get("forbidden_actions") or ()),
        updated_at=str(data.get("updated_at") or ""),
        accepted_partial=bool(data.get("accepted_partial", False)),
        event_counter=int(data.get("event_counter") or 0),
        latest_modification_event_id=_optional_int(data.get("latest_modification_event_id")),
        latest_verification_event_id=_optional_int(data.get("latest_verification_event_id")),
        latest_modification_at=str(data.get("latest_modification_at") or ""),
        latest_verification_at=str(data.get("latest_verification_at") or ""),
    )
    return _apply_invariants(ledger)


def update_status_ledger(ledger: StatusLedger, event: dict[str, Any]) -> StatusLedger:
    data = event if isinstance(event, dict) else {}
    event_id = _event_id(ledger, data)
    event_type = str(data.get("event_type") or data.get("type") or "").casefold().replace("-", "_")
    updated_at = str(data.get("updated_at") or data.get("timestamp") or data.get("time") or ledger.updated_at)
    next_ledger = replace(ledger, event_counter=max(ledger.event_counter, event_id), updated_at=updated_at)

    if data.get("current_phase") is not None:
        next_ledger = replace(next_ledger, current_phase=str(data.get("current_phase") or ""))
    if data.get("task_status") is not None or data.get("status") is not None:
        next_ledger = replace(next_ledger, task_status=_coerce_status(data.get("task_status") or data.get("status")))
    if data.get("dry_run") is not None:
        next_ledger = replace(next_ledger, dry_run=bool(data.get("dry_run")))
    if data.get("report_only") is not None:
        next_ledger = replace(next_ledger, report_only=bool(data.get("report_only")))
    if event_type in {"file_read", "read"} or data.get("file_read"):
        next_ledger = replace(next_ledger, files_read=_append_unique(next_ledger.files_read, _event_path(data)))
    if _is_modification_event(data, event_type):
        next_ledger = replace(
            next_ledger,
            files_written=_append_unique(next_ledger.files_written, _event_path(data)),
            verification_status="stale" if next_ledger.verification_status == "verified" else "required",
            latest_modification_event_id=event_id,
            latest_modification_at=updated_at,
        )
    if event_type in {"verification", "verify", "test", "tests"} or data.get("verification") is not None:
        success = bool(data.get("success", data.get("passed", True)))
        status = "unverified"
        if success:
            status = "verified" if next_ledger.latest_modification_event_id is None or event_id > next_ledger.latest_modification_event_id else "stale"
        next_ledger = replace(
            next_ledger,
            verification_status=status,
            latest_verification_event_id=event_id,
            latest_verification_at=updated_at,
            local_pass=bool(data.get("local_pass", next_ledger.local_pass or success)),
        )
    if event_type in {"subtask", "subtask_status"} or data.get("subtask_id") or data.get("subtask_statuses"):
        statuses = dict(next_ledger.subtask_statuses)
        statuses.update(_coerce_subtasks(data.get("subtask_statuses") or {}))
        subtask_id = data.get("subtask_id") or data.get("name")
        if subtask_id:
            statuses[str(subtask_id)] = _coerce_status(data.get("status") or data.get("task_status") or "running")
        next_ledger = replace(next_ledger, subtask_statuses=statuses)

    for field_name in ("local_pass", "remote_pushed", "remote_confirmed", "official_updated", "production_changed", "accepted_partial"):
        if data.get(field_name) is not None:
            next_ledger = replace(next_ledger, **{field_name: bool(data.get(field_name))})
    for field_name in ("local_tag", "remote_tag", "blocked_reason", "next_allowed_action"):
        if data.get(field_name) is not None:
            next_ledger = replace(next_ledger, **{field_name: str(data.get(field_name) or "")})
    if data.get("forbidden_actions"):
        next_ledger = replace(next_ledger, forbidden_actions=_append_many(next_ledger.forbidden_actions, data.get("forbidden_actions") or ()))
    if event_type == "blocked" or data.get("blocked_reason"):
        next_ledger = replace(next_ledger, task_status="blocked", blocked_reason=str(data.get("blocked_reason") or next_ledger.blocked_reason or "blocked"))
    if event_type == "failed":
        next_ledger = replace(next_ledger, task_status="failed")
    return _apply_invariants(next_ledger)


def check_verification_freshness(ledger: StatusLedger) -> VerificationDecision:
    if ledger.verification_status == "not_required":
        return VerificationDecision(True, "verification_not_required", ledger.verification_status, ledger.latest_modification_event_id, ledger.latest_verification_event_id, "Proceed without verification claim inflation.")
    if ledger.verification_status != "verified":
        return VerificationDecision(False, f"verification_status_{ledger.verification_status}", ledger.verification_status, ledger.latest_modification_event_id, ledger.latest_verification_event_id, "Run verification after the latest modification.")
    if ledger.latest_modification_event_id is not None and (
        ledger.latest_verification_event_id is None or ledger.latest_verification_event_id <= ledger.latest_modification_event_id
    ):
        return VerificationDecision(False, "verification_older_than_latest_modification", "stale", ledger.latest_modification_event_id, ledger.latest_verification_event_id, "Rerun verification after the latest file modification.")
    return VerificationDecision(True, "verification_fresh", ledger.verification_status, ledger.latest_modification_event_id, ledger.latest_verification_event_id, "Report verified only with the fresh verification event.")


def check_final_report_consistency(ledger: StatusLedger, report_text: str) -> ConsistencyDecision:
    text = (report_text or "").casefold()
    violations = list(ledger.invariant_violations)
    freshness = check_verification_freshness(ledger)
    if _claims_completion(text) and ledger.task_status in {"pending", "running", "partial", "blocked", "failed"}:
        violations.append(f"completion_claim_conflicts_with_task_status:{ledger.task_status}")
    if _claims_verified(text) and not freshness.verified:
        violations.append(f"verified_claim_conflicts_with_ledger:{freshness.reason}")
    if _claims_pushed(text) and not ledger.remote_pushed:
        violations.append("pushed_claim_conflicts_with_remote_pushed_false")
    if (_claims_remote_tag(text) or (ledger.local_tag and _claims_pushed(text))) and not ledger.remote_tag:
        violations.append("remote_tag_claim_conflicts_with_missing_remote_tag")
    if _claims_official_update(text) and not ledger.official_updated:
        violations.append("official_update_claim_conflicts_with_ledger_false")
    if _claims_production_ready(text) and (not ledger.production_changed or ledger.blocked_reason):
        violations.append("production_ready_claim_conflicts_with_ledger")
    if _claims_all_phases_complete(text) and any(status != "completed" for status in ledger.subtask_statuses.values()):
        violations.append("all_phases_complete_claim_conflicts_with_subtasks")
    if ledger.report_only and _claims_write_performed(text):
        violations.append("write_claim_conflicts_with_report_only")
    if ledger.dry_run and _claims_official_update(text):
        violations.append("official_update_claim_conflicts_with_dry_run")
    unique = tuple(dict.fromkeys(violations))
    return ConsistencyDecision(not unique, unique, (), "Revise final report to match ledger state." if unique else "Report may be emitted.")


def build_final_report_consistency_warnings(ledger: StatusLedger, report_text: str) -> tuple[dict[str, str], ...]:
    decision = check_final_report_consistency(ledger, report_text)
    return tuple(_warning_for_violation(violation, ledger, report_text or "") for violation in decision.violations)


def classify_remote_sync_safety(state: dict[str, Any]) -> RemoteSyncDecision:
    data = state if isinstance(state, dict) else {}
    warnings: list[str] = []
    authorized_remote = str(data.get("authorized_remote") or "").strip()
    candidate_remote = str(data.get("candidate_remote") or data.get("remote") or "").strip()
    origin_read_ok = bool(data.get("origin_read_ok") or data.get("origin_ls_remote_ok"))
    origin_write_proven = bool(data.get("origin_write_proven"))
    fork_write_proven = bool(data.get("fork_write_proven"))
    branch_push_verified = bool(data.get("branch_push_verified"))
    local_tag_exists = bool(data.get("local_tag_exists") or data.get("local_tag"))
    remote_tag_exists = bool(data.get("remote_tag_exists") or data.get("remote_tag"))
    ssh_endpoint = str(data.get("ssh_endpoint") or data.get("git_ssh_endpoint") or "")
    fallback_from = str(data.get("fallback_from") or "")
    fallback_to = str(data.get("fallback_to") or "")
    explicit_fallback_authorized = bool(data.get("explicit_fallback_authorized"))
    remote_branch_state = str(data.get("remote_branch_state") or "").strip().casefold()

    if data.get("ls_remote_success"):
        warnings.append("ls_remote_success_is_read_access_only")
    if origin_read_ok and not origin_write_proven:
        warnings.append("origin_read_ok_does_not_prove_origin_write")
    if local_tag_exists and not remote_tag_exists:
        warnings.append("local_tag_does_not_imply_remote_tag")

    if "github.com:443" in ssh_endpoint and "ssh.github.com:443" not in ssh_endpoint:
        return RemoteSyncDecision(
            "blocked",
            "github_com_443_is_not_github_ssh_endpoint",
            "",
            False,
            False,
            True,
            "Use ssh.github.com:443, or a direct ssh://git@ssh.github.com:443/OWNER/REPO.git URL, after host key handling is verified.",
            tuple(dict.fromkeys(warnings)),
        )
    if fallback_from and fallback_to and fallback_from != fallback_to and not explicit_fallback_authorized:
        return RemoteSyncDecision(
            "blocked",
            "remote_fallback_without_explicit_authorization",
            fallback_from,
            False,
            False,
            True,
            "Stop and ask the user to authorize the exact remote target before retrying.",
            tuple(dict.fromkeys(warnings)),
        )
    if data.get("tag_push_requested") and not branch_push_verified:
        return RemoteSyncDecision(
            "blocked",
            "tag_push_before_branch_push_verified",
            candidate_remote or authorized_remote,
            False,
            False,
            True,
            "Verify the selected remote branch before pushing any tag.",
            tuple(dict.fromkeys(warnings)),
        )
    if remote_branch_state in {"ahead", "diverged"}:
        return RemoteSyncDecision(
            "blocked",
            f"remote_branch_{remote_branch_state}",
            candidate_remote or authorized_remote,
            False,
            False,
            True,
            "Do not push; inspect and resolve remote branch relationship first.",
            tuple(dict.fromkeys(warnings)),
        )

    recommended_remote = ""
    if fork_write_proven and not origin_write_proven:
        recommended_remote = "fork"
    elif origin_write_proven:
        recommended_remote = "origin"
    elif candidate_remote:
        recommended_remote = candidate_remote

    if recommended_remote == "fork" and authorized_remote != "fork":
        return RemoteSyncDecision(
            "user_authorization_required",
            "fork_write_proven_but_explicit_authorization_required",
            "fork",
            False,
            False,
            True,
            "Ask the user to authorize fork as the exact remote target before pushing.",
            tuple(dict.fromkeys(warnings)),
        )
    if candidate_remote == "origin" and not origin_write_proven:
        return RemoteSyncDecision(
            "user_authorization_required",
            "origin_write_not_proven",
            recommended_remote,
            False,
            False,
            True,
            "Do not push origin until origin write access is proven or explicitly authorized with that risk.",
            tuple(dict.fromkeys(warnings)),
        )

    branch_allowed = bool(authorized_remote and authorized_remote == recommended_remote)
    tag_allowed = bool(branch_allowed and branch_push_verified)
    return RemoteSyncDecision(
        "allowed" if branch_allowed else "user_authorization_required",
        "remote_sync_target_authorized" if branch_allowed else "remote_sync_target_requires_authorization",
        recommended_remote,
        branch_allowed,
        tag_allowed,
        not branch_allowed,
        "Push only the authorized remote/branch, then verify before tag push." if branch_allowed else "Ask for explicit remote authorization before pushing.",
        tuple(dict.fromkeys(warnings)),
    )


def classify_watchdog_state(state: dict[str, Any]) -> WatchdogDecision:
    data = state if isinstance(state, dict) else {}
    process_status = str(data.get("process_status") or data.get("status") or "").casefold()
    silence_seconds = float(data.get("silence_seconds") or 0)
    silence_budget = float(data.get("expected_silence_budget") or 0)
    retry_same = int(data.get("retry_count_same_error") or 0)
    current_sig = str(data.get("current_error_signature") or "")
    last_sig = str(data.get("last_error_signature") or "")
    signature = current_sig or last_sig
    repeated_same = retry_same if retry_same or (current_sig and last_sig and current_sig == last_sig) else 0

    if _fatal_error(signature):
        return WatchdogDecision(False, True, False, True, "fatal_error_requires_owner_action", "Stop retrying and resolve auth/session/quota/permission/path state.", "blocked")
    if "timeout" in process_status and data.get("partial_output"):
        return WatchdogDecision(False, True, False, False, "timeout_with_partial_output", "Mark partial and inspect partial output.", "partial")
    if repeated_same >= 3:
        return WatchdogDecision(False, True, False, True, "same_error_repeated_3_times", "Block and surface the repeated error signature.", "blocked")
    if repeated_same >= 2:
        if _transient_network(signature):
            return WatchdogDecision(False, False, True, False, "", "Retry once with backoff; block on another repeat.", "retry")
        return WatchdogDecision(False, True, False, True, "same_error_repeated_2_times", "Block unless a human marks the error transient.", "blocked")
    if process_status in {"running", "waiting"}:
        if silence_seconds <= silence_budget:
            return WatchdogDecision(True, False, False, False, "", "Wait within expected silence budget.", "running")
        return WatchdogDecision(False, True, False, False, "silence_budget_exceeded", "Inspect process output and child process state.", "running")
    if "timeout" in process_status:
        return WatchdogDecision(False, True, False, False, "timeout_without_success", "Inspect timeout details; do not report PASS.", "partial")
    if process_status in {"failed", "error", "cancelled"}:
        return WatchdogDecision(False, True, False, True, f"process_{process_status}", "Block and report the failure state.", "blocked")
    return WatchdogDecision(False, False, False, False, "", "No watchdog action required.", process_status or "unknown")


def _decision(decision: str, reason: str, owner: str, blocked: bool, safe_next_action: str) -> PermissionDecision:
    return PermissionDecision(decision, reason, owner, blocked, safe_next_action)


def _trigger_matches(haystack: str, trigger: str) -> bool:
    needle = trigger.casefold()
    if any(ord(char) > 127 for char in needle):
        return needle in haystack
    return bool(re.search(r"(?<![a-z0-9_])" + re.escape(needle) + r"(?![a-z0-9_])", haystack))


def _action_text(action: dict[str, Any]) -> str:
    parts: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple, set)):
            for child in value:
                visit(child)

    visit(action)
    return " ".join(parts).casefold()


def _bool_context(action: dict[str, Any], key: str) -> bool:
    if key in action:
        return bool(action[key])
    for name in ("task", "context"):
        value = action.get(name)
        if isinstance(value, dict) and key in value:
            return bool(value[key])
    return False


def _is_git_force_push(text: str) -> bool:
    return "git" in text and "push" in text and bool(re.search(r"--force(?:-with-lease)?|\s-f(?:\s|$)", text))


def _is_browser_gui_action(text: str) -> bool:
    browser_terms = ("browser", "chrome canary", "openclaw", "gui", "login", "download", "screenshot", "浏览器", "下载")
    return any(term in text for term in browser_terms) and (
        "headless" in text or any(term in text for term in ("gui", "login", "download", "screenshot", "chrome canary", "openclaw", "browser"))
    )


def _user_authorization_reason(action: dict[str, Any], text: str) -> str:
    if any(term in text for term in ("production promotion", "promote production", "official baseline update", "official update", "baseline update")):
        return "official_or_production_update_requires_user_authorization"
    if any(term in text for term in ("memory delete", "delete memory", "memory replacement", "replace memory")):
        return "memory_mutation_requires_user_authorization"
    if any(term in text for term in ("file delete", "delete file", "remove file", "move file", "copy file")):
        return "file_mutation_requires_user_authorization"
    if any(term in text for term in ("git push", "git tag", "git merge", "branch delete", "delete branch")):
        return "git_remote_or_history_change_requires_user_authorization"
    if action.get("operation") in {"delete", "move"} and action.get("path"):
        return "file_mutation_requires_user_authorization"
    if action.get("operation") == "copy" and not (action.get("target") or action.get("destination")):
        return "file_mutation_requires_user_authorization"
    if action.get("memory_operation") in {"delete", "replace"}:
        return "memory_mutation_requires_user_authorization"
    return ""


def _requires_codex(action: dict[str, Any], text: str) -> bool:
    terms = ("code modification", "modify code", "edit code", "bug fix", "refactor", "write test", "test writing", "pytest", "patch", "修改代码", "写测试")
    return any(term in text for term in terms) or (
        action.get("domain") == "code" and action.get("operation") in {"write", "modify", "edit", "patch", "refactor", "test"}
    )


def _is_allowed_hermes_action(text: str) -> bool:
    return any(term in text for term in ("explain", "triage", "summarize", "audit", "codex prompt", "read", "search", "inspect", "status"))


def _is_write_action(action: dict[str, Any], text: str) -> bool:
    op = str(action.get("operation") or action.get("type") or "").casefold()
    return op in {"write", "modify", "edit", "patch", "create", "save"} or any(term in text for term in ("write", "modify", "edit", "patch", "create", "save", "update file", "non-report write"))


def _is_report_artifact(action: dict[str, Any]) -> bool:
    kind = str(action.get("artifact_type") or action.get("kind") or "").casefold()
    path = str(action.get("path") or action.get("target") or action.get("destination") or "").casefold()
    return kind in {"report", "final_report", "audit_report"} or bool(path and ("report" in path or path.endswith((".md", ".txt"))))


def _is_official_update(action: dict[str, Any], text: str) -> bool:
    return bool(action.get("official_updated")) or any(term in text for term in ("official update", "official baseline update", "baseline update", "production promotion", "promote production"))


def _coerce_status(value: Any) -> str:
    status = str(value or "pending").strip().casefold().replace("-", "_")
    status = {"waiting": "running", "in_progress": "running", "pass": "completed", "passed": "completed"}.get(status, status)
    return status if status in TASK_STATUSES else "pending"


def _coerce_verification(value: Any) -> str:
    status = str(value or "not_required").strip().casefold().replace("-", "_")
    return status if status in VERIFICATION_STATUSES else "unverified"


def _coerce_subtasks(value: Any) -> dict[str, str]:
    return {str(key): _coerce_status(status) for key, status in value.items()} if isinstance(value, dict) else {}


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_id(ledger: StatusLedger, event: dict[str, Any]) -> int:
    explicit = _optional_int(event.get("event_id") or event.get("id"))
    return explicit if explicit is not None else ledger.event_counter + 1


def _event_path(event: dict[str, Any]) -> str:
    return str(event.get("path") or event.get("file") or event.get("target") or "")


def _append_unique(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    return values if not value or value in values else (*values, value)


def _append_many(values: tuple[str, ...], additions: Any) -> tuple[str, ...]:
    result = values
    for item in additions:
        result = _append_unique(result, str(item))
    return result


def _is_modification_event(event: dict[str, Any], event_type: str) -> bool:
    if event_type in {"file_written", "file_write", "write", "modify", "file_modified", "patch_applied"}:
        return True
    if event.get("file_written") or event.get("file_modified"):
        return True
    return str(event.get("operation") or "").casefold() in {"write", "modify", "edit", "patch", "create", "save"}


def _apply_invariants(ledger: StatusLedger) -> StatusLedger:
    violations: list[str] = []
    task_status = ledger.task_status
    blocked_reason = ledger.blocked_reason
    next_allowed_action = ledger.next_allowed_action
    forbidden_actions = list(ledger.forbidden_actions)

    incomplete = {name: status for name, status in ledger.subtask_statuses.items() if status in {"pending", "running", "partial", "blocked", "failed"}}
    if incomplete and task_status == "completed" and not ledger.accepted_partial:
        violations.append("completed_with_incomplete_or_partial_subtasks")
        task_status = "blocked" if "blocked" in incomplete.values() else "failed" if "failed" in incomplete.values() else "partial"
    if ledger.dry_run and ledger.official_updated:
        violations.append("dry_run_cannot_update_official_state")
        task_status = "blocked"
        blocked_reason = blocked_reason or "dry_run_cannot_update_official_state"
        forbidden_actions.append("official_update")
    if ledger.report_only and ledger.production_changed:
        violations.append("report_only_cannot_change_production")
        task_status = "blocked"
        blocked_reason = blocked_reason or "report_only_cannot_change_production"
        forbidden_actions.append("production_change")
    if task_status == "blocked" and not next_allowed_action:
        next_allowed_action = "resolve_blocked_reason_before_reporting_pass"

    return replace(
        ledger,
        task_status=task_status,
        blocked_reason=blocked_reason,
        next_allowed_action=next_allowed_action,
        forbidden_actions=tuple(dict.fromkeys(forbidden_actions)),
        invariant_violations=tuple(dict.fromkeys((*ledger.invariant_violations, *violations))),
    )


def _warning_for_violation(violation: str, ledger: StatusLedger, report_text: str) -> dict[str, str]:
    if violation.startswith("completion_claim_conflicts_with_task_status"):
        return _report_warning(
            "PASSIVE_FINAL_REPORT_COMPLETION_CONFLICT",
            "task_status",
            _first_claim_phrase(report_text, ("PASS", "passed", "completed", "complete", "done", "finished", "已完成")),
            f"Task status is {ledger.task_status}; do not report completion unless the ledger is completed.",
            violation,
        )
    if violation.startswith("verified_claim_conflicts_with_ledger"):
        return _report_warning(
            "PASSIVE_FINAL_REPORT_VERIFICATION_CONFLICT",
            "verification_status",
            _first_claim_phrase(report_text, ("verified", "verification passed", "validated", "验证通过")),
            f"Verification status is {ledger.verification_status}; run fresh verification before claiming verified.",
            violation,
        )
    if violation == "pushed_claim_conflicts_with_remote_pushed_false":
        return _report_warning(
            "PASSIVE_FINAL_REPORT_PUSH_CONFLICT",
            "remote_pushed",
            _first_claim_phrase(report_text, ("pushed", "remote pushed", "push complete", "已推送")),
            "Remote push is not recorded; treat the work as local only until remote push is verified.",
            violation,
        )
    if violation == "remote_tag_claim_conflicts_with_missing_remote_tag":
        return _report_warning(
            "PASSIVE_FINAL_REPORT_REMOTE_TAG_CONFLICT",
            "remote_tag",
            _first_claim_phrase(report_text, ("remote tag", "tag pushed", "pushed tag", "pushed")),
            "A local tag does not imply a remote tag; verify the remote tag before claiming it.",
            violation,
        )
    if violation == "official_update_claim_conflicts_with_ledger_false":
        return _report_warning(
            "PASSIVE_FINAL_REPORT_OFFICIAL_UPDATE_CONFLICT",
            "official_updated",
            _first_claim_phrase(report_text, ("official baseline updated", "official updated", "baseline updated", "official state updated")),
            "Official state is not recorded as updated; report this as report-only/local unless verified otherwise.",
            violation,
        )
    if violation == "production_ready_claim_conflicts_with_ledger":
        return _report_warning(
            "PASSIVE_FINAL_REPORT_PRODUCTION_READY_CONFLICT",
            "production_changed",
            _first_claim_phrase(report_text, ("production ready", "ready for production", "production-ready", "可生产")),
            "Production change is not recorded or the ledger is blocked; do not claim production readiness.",
            violation,
        )
    if violation == "all_phases_complete_claim_conflicts_with_subtasks":
        return _report_warning(
            "PASSIVE_FINAL_REPORT_SUBTASK_CONFLICT",
            "subtask_statuses",
            _first_claim_phrase(report_text, ("all phases complete", "all stages complete", "all subtasks complete", "所有阶段完成")),
            "One or more subtasks are not completed; report partial/incomplete status.",
            violation,
        )
    if violation == "write_claim_conflicts_with_report_only":
        return _report_warning(
            "PASSIVE_FINAL_REPORT_REPORT_ONLY_WRITE_CONFLICT",
            "report_only",
            _first_claim_phrase(report_text, ("wrote", "written", "modified", "created", "changed", "patched", "updated file", "files written")),
            "The task is report-only; do not claim non-report writes.",
            violation,
        )
    if violation == "official_update_claim_conflicts_with_dry_run":
        return _report_warning(
            "PASSIVE_FINAL_REPORT_DRY_RUN_OFFICIAL_CONFLICT",
            "dry_run",
            _first_claim_phrase(report_text, ("official baseline updated", "official updated", "baseline updated", "official state updated")),
            "Dry-run tasks cannot update official state.",
            violation,
        )
    return _report_warning(
        "PASSIVE_FINAL_REPORT_LEDGER_INVARIANT_CONFLICT",
        "invariant_violations",
        "",
        "Revise the report to match the status ledger invariant.",
        violation,
    )


def _report_warning(code: str, ledger_field: str, offending_phrase: str, safe_interpretation: str, violation: str) -> dict[str, str]:
    return {
        "code": code,
        "ledger_field": ledger_field,
        "offending_phrase": offending_phrase,
        "safe_interpretation": safe_interpretation,
        "violation": violation,
    }


def _first_claim_phrase(text: str, phrases: tuple[str, ...]) -> str:
    lowered = text.casefold()
    for phrase in phrases:
        if phrase.casefold() in lowered:
            return phrase
    return ""


def _claims_completion(text: str) -> bool:
    return bool(re.search(r"\b(pass|passed|completed|complete|done|finished)\b", text)) or "已完成" in text


def _claims_verified(text: str) -> bool:
    return bool(re.search(r"\b(verified|verification passed|validated)\b", text)) or "验证通过" in text


def _claims_pushed(text: str) -> bool:
    return bool(re.search(r"\b(pushed|remote pushed|push complete)\b", text)) or "已推送" in text


def _claims_remote_tag(text: str) -> bool:
    return bool(re.search(r"\b(remote tag|tag pushed|pushed tag)\b", text))


def _claims_official_update(text: str) -> bool:
    return any(term in text for term in ("official baseline updated", "official updated", "baseline updated", "official state updated"))


def _claims_production_ready(text: str) -> bool:
    return any(term in text for term in ("production ready", "ready for production", "production-ready", "可生产"))


def _claims_all_phases_complete(text: str) -> bool:
    return any(term in text for term in ("all phases complete", "all stages complete", "all subtasks complete", "所有阶段完成"))


def _claims_write_performed(text: str) -> bool:
    return bool(re.search(r"\b(wrote|written|modified|created|changed|patched|updated file|files written)\b", text))


def _fatal_error(signature: str) -> bool:
    return any(term in signature.casefold() for term in ("auth", "session", "quota", "permission", "forbidden", "unauthorized", "path not found", "no such file", "access denied"))


def _transient_network(signature: str) -> bool:
    return any(term in signature.casefold() for term in ("network", "timeout", "temporarily unavailable", "connection reset", "econnreset", "dns", "502", "503", "504"))


__all__ = [
    "ConsistencyDecision",
    "PermissionDecision",
    "RemoteSyncDecision",
    "SKILL_TRIGGER_RULES",
    "StatusLedger",
    "VerificationDecision",
    "WatchdogDecision",
    "build_final_report_consistency_warnings",
    "check_final_report_consistency",
    "check_verification_freshness",
    "classify_action_permission",
    "classify_remote_sync_safety",
    "classify_skill_triggers",
    "classify_watchdog_state",
    "initialize_status_ledger",
    "update_status_ledger",
]
