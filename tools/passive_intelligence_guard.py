"""Pure deterministic guard helpers for Hermes passive intelligence phase 0."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
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


@dataclass(frozen=True)
class DocumentValidationPlan:
    file_path: str
    file_type: str
    intended_use: str
    required_checks: tuple[str, ...]
    optional_checks: tuple[str, ...]
    platform_specific_checks: tuple[str, ...]
    overclaim_prohibited_phrases: tuple[str, ...]


@dataclass(frozen=True)
class PdfSignatureResult:
    has_pdf_header: bool
    has_eof_marker: bool
    eof_marker_near_tail: bool
    file_size_bytes: int
    suspicious_truncation: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentValidationDecision:
    status: str
    parser_readable: bool | None
    binary_signature_ok: bool | None
    render_check_ok: bool | None
    macos_preview_compatible: bool | None
    target_app_compatible: bool | None
    checks_run: tuple[str, ...]
    checks_missing: tuple[str, ...]
    missing_check_reason: str
    blocked_reason: str
    safe_claim_level: str
    user_facing_summary: str


@dataclass(frozen=True)
class TimeoutPolicy:
    stage_name: str
    owner_tool: str
    expected_silence_budget: int
    soft_timeout: int
    hard_timeout: int
    inspect_after_silence: int
    retry_limit_same_error: int
    retry_limit_total: int
    allow_retry_error_kinds: tuple[str, ...]
    block_error_kinds: tuple[str, ...]


@dataclass(frozen=True)
class LongRunState:
    task_id: str
    owner_tool: str
    stage_name: str
    process_status: str
    elapsed_seconds: float = 0
    silence_seconds: float = 0
    expected_silence_budget: float | None = None
    hard_timeout: float | None = None
    retry_count_same_error: int = 0
    retry_count_total: int = 0
    last_error_signature: str = ""
    current_error_signature: str = ""
    partial_output_present: bool = False
    output_freshness: str = ""
    auth_state: str = ""
    quota_state: str = ""
    path_state: str = ""
    permission_state: str = ""
    incomplete_phases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationCommandPlan:
    check_name: str
    command_preview: str
    executes_by_default: bool
    destructive: bool
    platform: str
    required_for_claim_level: str
    fallback_if_unavailable: str


@dataclass(frozen=True)
class DocumentValidationObserverPlan:
    triggered: bool
    trigger_reasons: tuple[str, ...]
    files: tuple[str, ...]
    intended_use: str
    required_checks: tuple[str, ...]
    optional_checks: tuple[str, ...]
    platform_specific_checks: tuple[str, ...]
    command_plan: tuple[ValidationCommandPlan, ...]
    prohibited_claims: tuple[str, ...]
    safe_claim_ceiling: str
    next_safe_action: str
    warning_if_checks_missing: str


@dataclass(frozen=True)
class WatchdogPollPlan:
    inspect_after_silence: int
    soft_timeout: int
    hard_timeout: int
    retry_limit_same_error: int
    retry_limit_total: int
    required_status_fields: tuple[str, ...]
    safe_actions: tuple[str, ...]
    blocked_actions: tuple[str, ...]


@dataclass(frozen=True)
class LongRunObserverPlan:
    triggered: bool
    trigger_reasons: tuple[str, ...]
    owner_tool: str
    stage_name: str
    timeout_policy: TimeoutPolicy
    heartbeat_fields: tuple[str, ...]
    poll_plan: WatchdogPollPlan
    retry_policy: str
    blocked_conditions: tuple[str, ...]
    partial_output_policy: str
    prohibited_claims: tuple[str, ...]
    next_safe_action: str


@dataclass(frozen=True)
class PassiveRuntimeEvent:
    event_id: int
    event_type: str
    timestamp: str = ""
    source: str = ""
    task_id: str = ""
    phase: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    severity: str = "info"


@dataclass(frozen=True)
class FileAccessEvent:
    event_id: int
    path: str
    operation: str
    allowed_scope: bool = True
    report_only: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class VerificationEvent:
    event_id: int
    verification_type: str
    target_paths: tuple[str, ...] = ()
    result: str = ""
    verifies_after_event_id: int | None = None
    stale_if_before_event_id: int | None = None


@dataclass(frozen=True)
class SubtaskStatusEvent:
    event_id: int
    subtask_id: str
    status: str
    reason: str = ""
    accepted_partial: bool = False


@dataclass(frozen=True)
class ProcessStatusEvent:
    event_id: int
    owner_tool: str
    process_status: str
    elapsed_seconds: float = 0
    silence_seconds: float = 0
    partial_output_present: bool = False
    retry_count: int = 0
    error_signature: str = ""
    next_safe_action: str = ""


@dataclass(frozen=True)
class DocumentValidationEvent:
    event_id: int
    file_path: str
    checks_run: tuple[str, ...] = ()
    checks_missing: tuple[str, ...] = ()
    safe_claim_level: str = "binary_only"
    status: str = "unknown"
    target_app_compatible: bool | None = None


@dataclass(frozen=True)
class RemoteSyncEvent:
    event_id: int
    remote: str
    branch: str
    operation: str
    read_access: bool = False
    write_attempted: bool = False
    write_success: bool = False
    remote_head_before: str = ""
    remote_head_after: str = ""
    tag_pushed: bool = False
    tag_verified: bool = False


@dataclass(frozen=True)
class ReportClaimEvent:
    event_id: int
    claim_text: str
    claim_type: str = ""
    referenced_status: str = ""
    confidence: str = ""
    needs_ledger_check: bool = True


@dataclass(frozen=True)
class PassiveRuntimeLedger:
    task_id: str
    mode: str = "off"
    events_seen: int = 0
    latest_event_id: int = 0
    files_read: tuple[str, ...] = ()
    files_written: tuple[str, ...] = ()
    file_mutations: tuple[dict[str, Any], ...] = ()
    verification_status: str = "not_required"
    latest_modification_event_id: int | None = None
    latest_verification_event_id: int | None = None
    subtasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    overall_status: str = "pending"
    dry_run: bool = False
    report_only: bool = False
    production_changed: bool = False
    official_updated: bool = False
    remote_pushed: bool = False
    remote_tag_pushed: bool = False
    blocked_reason: str = ""
    partial_reasons: tuple[str, ...] = ()
    warnings: tuple[dict[str, str], ...] = ()
    forbidden_final_claims: tuple[str, ...] = ()
    next_safe_action: str = "Collect runtime events before reporting final status."
    document_claim_levels: dict[str, str] = field(default_factory=dict)
    document_statuses: dict[str, str] = field(default_factory=dict)
    remote_write_verified: bool = False
    remote_tag_verified: bool = False


@dataclass(frozen=True)
class PassiveLedgerDecision:
    status: str
    can_report_completed: bool
    can_report_pass: bool
    warnings: tuple[dict[str, str], ...]
    blocked_reason: str
    next_safe_action: str


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


def classify_document_validation_trigger(task_text: str) -> bool:
    text = (task_text or "").casefold()
    terms = (
        "pdf",
        "ocr",
        "render",
        "preview",
        "quicklook",
        "qlmanage",
        "pymupdf",
        "pdfinfo",
        "corrupted",
        "0 corrupted",
        "zero corrupted",
        "all valid",
        "verify all pdf",
        "文件完整性",
        "截断",
    )
    return any(term in text for term in terms)


def build_document_validation_observer_plan(
    task_text: str,
    files: list[str] | tuple[str, ...] | None = None,
    intended_use: str | None = None,
) -> DocumentValidationObserverPlan:
    text = task_text or ""
    lowered = text.casefold()
    explicit_files = tuple(str(item) for item in files or ())
    inferred_files = tuple(_infer_document_paths(text)) if not explicit_files else explicit_files
    intended = intended_use or _infer_document_intended_use(text)
    triggered = classify_document_validation_trigger(text) or bool(inferred_files)
    reasons = _document_trigger_reasons(text, inferred_files)
    batch = _is_batch_document_request(lowered, inferred_files)

    requirements = [
        classify_document_validation_requirements(path or "document.pdf", intended)
        for path in (inferred_files or ("document.pdf",))
    ]
    required_checks = _merge_tuple_values(*(item.required_checks for item in requirements))
    optional_checks = _merge_tuple_values(*(item.optional_checks for item in requirements))
    platform_checks = _merge_tuple_values(*(item.platform_specific_checks for item in requirements))
    if batch:
        required_checks = _append_unique(required_checks, "per_file_validation_ledger")
    if not inferred_files:
        required_checks = _append_unique(required_checks, "file_inventory")
    prohibited = _document_prohibited_claims(lowered, batch)
    safe_claim_ceiling = "parser_readable" if _parser_only_claim_context(lowered) else "binary_only"
    if not inferred_files:
        next_action = "Inventory the target files before claiming validation status."
    else:
        next_action = "Run only explicitly authorized validation checks and record per-file results before making claims."
    warning = "Missing required checks must be reported as unknown/warning, not pass."
    command_plan = tuple(
        command
        for path in (inferred_files or ("<inventory-required>",))
        for command in build_pdf_validation_command_plan(path, platform=_infer_platform(lowered), target_app=_infer_target_app(lowered))
    )
    return DocumentValidationObserverPlan(
        triggered=triggered,
        trigger_reasons=reasons,
        files=inferred_files,
        intended_use=intended,
        required_checks=required_checks,
        optional_checks=optional_checks,
        platform_specific_checks=platform_checks,
        command_plan=command_plan,
        prohibited_claims=prohibited,
        safe_claim_ceiling=safe_claim_ceiling,
        next_safe_action=next_action,
        warning_if_checks_missing=warning,
    )


def build_pdf_validation_command_plan(
    file_path: str,
    platform: str | None = None,
    target_app: str | None = None,
) -> list[ValidationCommandPlan]:
    path = file_path or "<file>"
    normalized_platform = (platform or "portable").strip().casefold() or "portable"
    target = (target_app or "").strip().casefold()
    plans = [
        ValidationCommandPlan(
            "binary_signature",
            f"inspect_pdf_binary_signatures({path!r})",
            False,
            False,
            "portable",
            "structurally_validated",
            "Report binary signature as unknown if the file cannot be read.",
        ),
        ValidationCommandPlan(
            "parser_readable",
            f"python -c \"import pymupdf; pymupdf.open({path!r}).close()\"",
            False,
            False,
            "portable",
            "parser_readable",
            "Do not claim full validity; parser-readable is the ceiling.",
        ),
        ValidationCommandPlan(
            "render_check",
            f"pdf-render-smoke --no-open-gui {path!r}",
            False,
            False,
            "portable",
            "rendered",
            "If renderer is unavailable, report render compatibility as unknown.",
        ),
    ]
    if normalized_platform in {"macos", "darwin"} or target in {"preview", "quicklook"}:
        plans.extend(
            [
                ValidationCommandPlan(
                    "macos_metadata_check",
                    f"mdls {path!r}",
                    False,
                    False,
                    "macos",
                    "target_app_validated",
                    "If mdls is unavailable, report macOS metadata compatibility as unknown.",
                ),
                ValidationCommandPlan(
                    "quicklook_thumbnail_check",
                    f"qlmanage -t -s 1 -o <tmpdir> {path!r}",
                    False,
                    False,
                    "macos",
                    "target_app_validated",
                    "If QuickLook tooling is unavailable, do not claim Preview compatibility.",
                ),
            ]
        )
    return plans


def summarize_document_validation_plan(plan: DocumentValidationObserverPlan) -> str:
    if not plan.triggered:
        return "No document validation observer plan is required."
    if not plan.files:
        return "Document validation is triggered, but file inventory is required before validation claims."
    return f"Document validation observer plan is warning-only; safe claim ceiling before checks: {plan.safe_claim_ceiling}."


def classify_long_run_trigger(task_text: str) -> bool:
    text = (task_text or "").casefold()
    terms = (
        "codex",
        "gpt bridge",
        "agy",
        "browser gui",
        "batch download",
        "subprocess",
        "timeout",
        "stuck",
        "silent",
        "no output",
        "waiting",
        "running",
        "long-running",
        "long running",
        "卡住",
        "等待",
        "没返回",
    )
    return any(term in text for term in terms)


def build_long_run_observer_plan(
    task_text: str,
    owner_tool: str | None = None,
    stage_name: str | None = None,
) -> LongRunObserverPlan:
    text = task_text or ""
    owner = _infer_owner_tool(text, owner_tool)
    stage = _infer_stage_name(text, stage_name, owner)
    triggered = classify_long_run_trigger(text) or bool(owner_tool or stage_name)
    reasons = _long_run_trigger_reasons(text, owner, stage)
    policy = get_stage_timeout_policy(stage, owner)
    poll_plan = build_watchdog_poll_plan(policy)
    return LongRunObserverPlan(
        triggered=triggered,
        trigger_reasons=reasons,
        owner_tool=owner,
        stage_name=stage,
        timeout_policy=policy,
        heartbeat_fields=(
            "phase",
            "started_at",
            "last_output_at",
            "elapsed",
            "silence_seconds",
            "process_status",
            "retry_count",
            "error_signature",
            "next_safe_action",
        ),
        poll_plan=poll_plan,
        retry_policy="Retry only transient network/timeout errors within per-stage policy; block repeated or owner-action errors.",
        blocked_conditions=(
            "auth_error",
            "session_error",
            "quota_error",
            "permission_error",
            "path_error",
            "remote_ahead_or_diverged",
            "same_error_repeated_limit",
        ),
        partial_output_policy="Timeout with partial output is partial, not completed.",
        prohibited_claims=("PASS", "completed", "done", "success"),
        next_safe_action="Observe status fields and classify wait/inspect/retry/block; do not start, kill, or retry processes from the observer plan.",
    )


def build_watchdog_poll_plan(policy: TimeoutPolicy) -> WatchdogPollPlan:
    return WatchdogPollPlan(
        inspect_after_silence=policy.inspect_after_silence,
        soft_timeout=policy.soft_timeout,
        hard_timeout=policy.hard_timeout,
        retry_limit_same_error=policy.retry_limit_same_error,
        retry_limit_total=policy.retry_limit_total,
        required_status_fields=(
            "phase",
            "started_at",
            "last_output_at",
            "elapsed",
            "silence_seconds",
            "process_status",
            "retry_count",
            "error_signature",
            "next_safe_action",
        ),
        safe_actions=("wait", "inspect", "mark_partial", "block_with_reason", "ask_owner"),
        blocked_actions=("kill_process", "blind_retry", "force_push", "serialize_running_as_pass"),
    )


def summarize_long_run_observer_plan(plan: LongRunObserverPlan) -> str:
    if not plan.triggered:
        return "No long-run observer plan is required."
    return (
        f"Long-run observer plan is warning-only for {plan.stage_name}; "
        f"inspect after {plan.poll_plan.inspect_after_silence}s silence and never report running/waiting/partial as PASS."
    )


def initialize_passive_runtime_ledger(task_id: str, mode: str = "off") -> PassiveRuntimeLedger:
    return PassiveRuntimeLedger(
        task_id=str(task_id or ""),
        mode=_coerce_passive_guard_mode(mode),
        overall_status="pending",
        verification_status="not_required",
        next_safe_action="Collect runtime events before reporting final status.",
    )


def apply_passive_runtime_event(
    ledger: PassiveRuntimeLedger,
    event: PassiveRuntimeEvent | dict[str, Any],
) -> PassiveRuntimeLedger:
    runtime_event = _coerce_passive_runtime_event(event)
    event_id = runtime_event.event_id if runtime_event.event_id > 0 else ledger.latest_event_id + 1
    runtime_event = replace(runtime_event, event_id=event_id)
    event_type = runtime_event.event_type.casefold().replace("-", "_")
    payload = dict(runtime_event.payload or {})

    files_read = list(ledger.files_read)
    files_written = list(ledger.files_written)
    file_mutations = list(ledger.file_mutations)
    subtasks = {key: dict(value) for key, value in ledger.subtasks.items()}
    warnings = list(ledger.warnings)
    forbidden = list(ledger.forbidden_final_claims)
    partial_reasons = list(ledger.partial_reasons)
    document_claim_levels = dict(ledger.document_claim_levels)
    document_statuses = dict(ledger.document_statuses)

    verification_status = ledger.verification_status
    latest_modification_event_id = ledger.latest_modification_event_id
    latest_verification_event_id = ledger.latest_verification_event_id
    overall_status = ledger.overall_status
    blocked_reason = ledger.blocked_reason
    next_safe_action = ledger.next_safe_action
    dry_run = ledger.dry_run or bool(payload.get("dry_run"))
    report_only = ledger.report_only or bool(payload.get("report_only"))
    production_changed = ledger.production_changed or bool(payload.get("production_changed"))
    official_updated = ledger.official_updated or bool(payload.get("official_updated"))
    remote_pushed = ledger.remote_pushed
    remote_tag_pushed = ledger.remote_tag_pushed
    remote_write_verified = ledger.remote_write_verified
    remote_tag_verified = ledger.remote_tag_verified

    def add_warning(code: str, safe_interpretation: str, *, ledger_field: str = "", offending_phrase: str = "") -> None:
        warnings.append(
            {
                "code": code,
                "ledger_field": ledger_field,
                "event_id": str(runtime_event.event_id),
                "offending_phrase": offending_phrase,
                "safe_interpretation": safe_interpretation,
            }
        )

    def add_forbidden(*claims: str) -> None:
        for claim in claims:
            if claim and claim not in forbidden:
                forbidden.append(claim)

    if event_type in {"file_access", "file", "file_read", "file_write", "file_mutation"}:
        operation = str(payload.get("operation") or "").casefold()
        if not operation and event_type.startswith("file_"):
            operation = event_type.removeprefix("file_")
        path = str(payload.get("path") or payload.get("file_path") or "")
        if operation == "read" and path:
            files_read = list(_append_unique(tuple(files_read), path))
        if operation in {"write", "delete", "move", "copy"}:
            if path:
                files_written = list(_append_unique(tuple(files_written), path))
            file_mutations.append({"event_id": runtime_event.event_id, "path": path, "operation": operation})
            latest_modification_event_id = runtime_event.event_id
            if latest_verification_event_id is not None:
                verification_status = "stale"
                add_warning(
                    "PASSIVE_RUNTIME_VERIFICATION_STALE",
                    "A file mutation after verification makes the prior verification stale.",
                    ledger_field="verification_status",
                )
            else:
                verification_status = "required"
            add_forbidden("verified", "no changes after verification")
            if report_only and not _runtime_report_artifact_path(path):
                production_changed = True
                blocked_reason = blocked_reason or "report_only_non_report_write"
                add_warning(
                    "PASSIVE_RUNTIME_REPORT_ONLY_WRITE_INVALID",
                    "Report-only tasks may only write report artifacts, not mutate source or production files.",
                    ledger_field="report_only",
                )
        if payload.get("allowed_scope") is False:
            blocked_reason = blocked_reason or "file_access_outside_allowed_scope"
            add_warning(
                "PASSIVE_RUNTIME_FILE_SCOPE_BLOCKED",
                "Stop and ask for explicit scope review before touching this file.",
                ledger_field="files_written",
            )

    elif event_type in {"verification", "verify", "verification_result"}:
        result = str(payload.get("result") or payload.get("status") or "").casefold()
        verifies_after = _optional_int(payload.get("verifies_after_event_id"))
        stale_if_before = _optional_int(payload.get("stale_if_before_event_id"))
        latest_verification_event_id = runtime_event.event_id
        required_after = latest_modification_event_id
        if stale_if_before is not None:
            required_after = max(required_after or 0, stale_if_before)
        verification_passed = result in {"pass", "passed", "ok", "verified", "success", "true"} or payload.get("verified") is True
        if verification_passed and (
            required_after is None
            or runtime_event.event_id > required_after
            or (verifies_after is not None and verifies_after >= required_after)
        ):
            verification_status = "verified"
        elif verification_passed:
            verification_status = "stale"
            add_warning(
                "PASSIVE_RUNTIME_VERIFICATION_STALE",
                "Verification must be newer than the latest relevant file mutation.",
                ledger_field="verification_status",
            )
        else:
            verification_status = "unverified"
            add_warning(
                "PASSIVE_RUNTIME_VERIFICATION_FAILED",
                "Do not claim verified until a successful verification event is recorded.",
                ledger_field="verification_status",
            )

    elif event_type in {"subtask_status", "subtask", "phase_status", "phase"}:
        subtask_id = str(payload.get("subtask_id") or payload.get("phase") or runtime_event.phase or "unknown")
        status = _coerce_status(payload.get("status") or payload.get("task_status") or "pending")
        accepted_partial = bool(payload.get("accepted_partial"))
        subtasks[subtask_id] = {
            "status": status,
            "reason": str(payload.get("reason") or ""),
            "accepted_partial": accepted_partial,
        }
        if status == "blocked":
            blocked_reason = blocked_reason or str(payload.get("reason") or f"{subtask_id}_blocked")
            add_forbidden("PASS", "completed", "all phases complete")
        elif status == "failed":
            add_forbidden("PASS", "completed", "all phases complete")
        elif status == "partial":
            if accepted_partial:
                add_warning(
                    "PASSIVE_RUNTIME_ACCEPTED_PARTIAL",
                    "Accepted partial work may be reported only with the partial acceptance caveat.",
                    ledger_field="subtasks",
                )
            else:
                partial_reasons = list(_append_unique(tuple(partial_reasons), f"{subtask_id}:partial"))
                add_forbidden("PASS", "completed", "all phases complete")

    elif event_type in {"process_status", "process", "watchdog", "long_run"}:
        state = dict(payload)
        state.setdefault("task_id", runtime_event.task_id or ledger.task_id)
        decision = classify_long_run_event(state)
        next_safe_action = decision.next_safe_action
        if decision.status in {"running", "waiting"}:
            overall_status = "running"
            add_forbidden("PASS", "completed")
        elif decision.status == "partial":
            overall_status = "partial"
            partial_reasons = list(_append_unique(tuple(partial_reasons), decision.blocked_reason or "long_run_partial"))
            add_forbidden("PASS", "completed")
            add_warning(
                "PASSIVE_RUNTIME_LONG_RUN_PARTIAL",
                safe_long_run_status_summary(decision),
                ledger_field="overall_status",
            )
        if decision.should_block:
            overall_status = "blocked"
            blocked_reason = blocked_reason or decision.blocked_reason or "long_run_blocked"
            add_forbidden("PASS", "completed")
        if decision.blocked_reason:
            add_warning(
                "PASSIVE_RUNTIME_LONG_RUN_STATUS",
                safe_long_run_status_summary(decision),
                ledger_field="overall_status",
            )

    elif event_type in {"document_validation", "document", "pdf_validation"}:
        file_path = str(payload.get("file_path") or payload.get("path") or "")
        decision = classify_pdf_validation_result(payload)
        if file_path:
            document_claim_levels[file_path] = decision.safe_claim_level
            document_statuses[file_path] = decision.status
        if decision.safe_claim_level in {"binary_only", "parser_readable"}:
            add_forbidden("PDF fully valid", "all valid", "0 corrupted", "target-app compatible", "Preview compatible")
        if decision.status in {"warning", "unknown"}:
            add_warning(
                "PASSIVE_RUNTIME_DOCUMENT_CHECKS_INCOMPLETE",
                decision.user_facing_summary,
                ledger_field="document_validation",
            )
        elif decision.status in {"fail", "blocked"}:
            blocked_reason = blocked_reason or decision.blocked_reason or "document_validation_failed"
            add_warning(
                "PASSIVE_RUNTIME_DOCUMENT_VALIDATION_BLOCKED",
                decision.user_facing_summary,
                ledger_field="document_validation",
            )

    elif event_type in {"remote_sync", "remote", "git_remote"}:
        operation = str(payload.get("operation") or "").casefold().replace("-", "_")
        read_access = bool(payload.get("read_access"))
        write_success = bool(payload.get("write_success"))
        verified = bool(payload.get("verified") or payload.get("branch_verified") or payload.get("write_verified"))
        tag_pushed = bool(payload.get("tag_pushed") or operation in {"tag_push", "push_tag"})
        tag_verified = bool(payload.get("tag_verified"))
        if read_access and not write_success:
            add_warning(
                "PASSIVE_RUNTIME_READ_ACCESS_IS_NOT_WRITE_ACCESS",
                "Remote read access, including ls-remote, does not prove push permission.",
                ledger_field="remote_pushed",
            )
            add_forbidden("pushed", "remote synced")
        if operation in {"branch_push", "push", "push_branch"}:
            if write_success and verified:
                remote_pushed = True
                remote_write_verified = True
            elif write_success:
                add_warning(
                    "PASSIVE_RUNTIME_REMOTE_PUSH_UNVERIFIED",
                    "A remote branch push must be fetched or otherwise verified before claiming synced.",
                    ledger_field="remote_pushed",
                )
                add_forbidden("pushed", "remote synced")
        if operation in {"local_tag", "tag"} and not tag_pushed:
            add_forbidden("remote tag synced", "tag pushed")
        if tag_pushed:
            if tag_verified:
                remote_tag_pushed = True
                remote_tag_verified = True
            else:
                add_warning(
                    "PASSIVE_RUNTIME_REMOTE_TAG_UNVERIFIED",
                    "A tag push must be verified on the remote before claiming tag sync.",
                    ledger_field="remote_tag_pushed",
                )
                add_forbidden("remote tag synced", "tag pushed")

    elif event_type in {"report_claim", "claim", "final_report_claim"}:
        claim_text = str(payload.get("claim_text") or payload.get("text") or "")
        claim_ledger = replace(ledger, warnings=())
        for warning in ledger_to_final_report_warnings(claim_ledger, claim_text):
            warnings.append(dict(warning))

    elif event_type in {"context_state", "runner_context"}:
        if payload.get("report_only") is not None:
            report_only = report_only or bool(payload.get("report_only"))
        if payload.get("dry_run") is not None:
            dry_run = dry_run or bool(payload.get("dry_run"))
        production_changed = production_changed or bool(payload.get("production_changed"))
        official_updated = official_updated or bool(payload.get("official_updated"))
        if report_only and production_changed:
            blocked_reason = blocked_reason or "report_only_production_change"
            add_warning(
                "PASSIVE_RUNTIME_REPORT_ONLY_PRODUCTION_CHANGE_INVALID",
                "Report-only context cannot be treated as production-changing work.",
                ledger_field="report_only",
            )
        if dry_run and official_updated:
            blocked_reason = blocked_reason or "dry_run_official_update"
            add_warning(
                "PASSIVE_RUNTIME_DRY_RUN_OFFICIAL_UPDATE_INVALID",
                "Dry-run context cannot update official state.",
                ledger_field="dry_run",
            )

    elif event_type in {"adapter_warning", "context_warning"}:
        warnings.append(
            {
                "code": str(payload.get("code") or "PASSIVE_RUNTIME_CONTEXT_WARNING"),
                "ledger_field": str(payload.get("ledger_field") or ""),
                "event_id": str(runtime_event.event_id),
                "offending_phrase": str(payload.get("offending_phrase") or ""),
                "safe_interpretation": str(payload.get("safe_interpretation") or "Treat missing context as unknown, not success."),
            }
        )

    if payload.get("task_status") or payload.get("overall_status"):
        overall_status = _coerce_status(payload.get("task_status") or payload.get("overall_status"))

    updated = PassiveRuntimeLedger(
        task_id=ledger.task_id or runtime_event.task_id,
        mode=ledger.mode,
        events_seen=ledger.events_seen + 1,
        latest_event_id=max(ledger.latest_event_id, runtime_event.event_id),
        files_read=tuple(files_read),
        files_written=tuple(files_written),
        file_mutations=tuple(file_mutations),
        verification_status=verification_status,
        latest_modification_event_id=latest_modification_event_id,
        latest_verification_event_id=latest_verification_event_id,
        subtasks=subtasks,
        overall_status=overall_status,
        dry_run=dry_run,
        report_only=report_only,
        production_changed=production_changed,
        official_updated=official_updated,
        remote_pushed=remote_pushed,
        remote_tag_pushed=remote_tag_pushed,
        blocked_reason=blocked_reason,
        partial_reasons=tuple(partial_reasons),
        warnings=tuple(warnings),
        forbidden_final_claims=tuple(forbidden),
        next_safe_action=next_safe_action,
        document_claim_levels=document_claim_levels,
        document_statuses=document_statuses,
        remote_write_verified=remote_write_verified,
        remote_tag_verified=remote_tag_verified,
    )
    return _apply_passive_runtime_invariants(updated)


def build_passive_runtime_ledger(
    events: list[PassiveRuntimeEvent | dict[str, Any]] | tuple[PassiveRuntimeEvent | dict[str, Any], ...],
    task_id: str = "",
    mode: str = "off",
) -> PassiveRuntimeLedger:
    ledger = initialize_passive_runtime_ledger(task_id, mode)
    for event in events or ():
        ledger = apply_passive_runtime_event(ledger, event)
    return ledger


def coerce_passive_runtime_ledger(
    value: PassiveRuntimeLedger | dict[str, Any] | None,
    *,
    task_id: str = "",
    mode: str = "off",
) -> PassiveRuntimeLedger:
    if isinstance(value, PassiveRuntimeLedger):
        return value
    ledger = initialize_passive_runtime_ledger(task_id, mode)
    if not isinstance(value, dict):
        return ledger
    data = dict(value)
    return _apply_passive_runtime_invariants(
        replace(
            ledger,
            events_seen=int(data.get("events_seen") or 0),
            latest_event_id=int(data.get("latest_event_id") or 0),
            files_read=tuple(str(item) for item in data.get("files_read") or ()),
            files_written=tuple(str(item) for item in data.get("files_written") or ()),
            file_mutations=tuple(dict(item) for item in data.get("file_mutations") or ()),
            verification_status=str(data.get("verification_status") or ledger.verification_status),
            latest_modification_event_id=_optional_int(data.get("latest_modification_event_id")),
            latest_verification_event_id=_optional_int(data.get("latest_verification_event_id")),
            subtasks={str(key): dict(val) for key, val in (data.get("subtasks") or {}).items()},
            overall_status=_coerce_status(data.get("overall_status") or ledger.overall_status),
            dry_run=bool(data.get("dry_run", ledger.dry_run)),
            report_only=bool(data.get("report_only", ledger.report_only)),
            production_changed=bool(data.get("production_changed", ledger.production_changed)),
            official_updated=bool(data.get("official_updated", ledger.official_updated)),
            remote_pushed=bool(data.get("remote_pushed", ledger.remote_pushed)),
            remote_tag_pushed=bool(data.get("remote_tag_pushed", ledger.remote_tag_pushed)),
            blocked_reason=str(data.get("blocked_reason") or ""),
            partial_reasons=tuple(str(item) for item in data.get("partial_reasons") or ()),
            warnings=tuple(dict(item) for item in data.get("warnings") or ()),
            forbidden_final_claims=tuple(str(item) for item in data.get("forbidden_final_claims") or ()),
            next_safe_action=str(data.get("next_safe_action") or ledger.next_safe_action),
            document_claim_levels={str(key): str(val) for key, val in (data.get("document_claim_levels") or {}).items()},
            document_statuses={str(key): str(val) for key, val in (data.get("document_statuses") or {}).items()},
            remote_write_verified=bool(data.get("remote_write_verified", ledger.remote_write_verified)),
            remote_tag_verified=bool(data.get("remote_tag_verified", ledger.remote_tag_verified)),
        )
    )


def summarize_passive_runtime_ledger(ledger: PassiveRuntimeLedger) -> dict[str, Any]:
    return {
        "task_id": ledger.task_id,
        "mode": ledger.mode,
        "events_seen": ledger.events_seen,
        "latest_event_id": ledger.latest_event_id,
        "overall_status": ledger.overall_status,
        "verification_status": ledger.verification_status,
        "files_read": list(ledger.files_read),
        "files_written": list(ledger.files_written),
        "file_mutation_count": len(ledger.file_mutations),
        "subtask_count": len(ledger.subtasks),
        "remote_pushed": ledger.remote_pushed,
        "remote_tag_pushed": ledger.remote_tag_pushed,
        "blocked_reason": ledger.blocked_reason,
        "partial_reasons": list(ledger.partial_reasons),
        "warning_count": len(ledger.warnings),
        "forbidden_final_claims": list(ledger.forbidden_final_claims),
        "next_safe_action": ledger.next_safe_action,
    }


def classify_ledger_completion_state(ledger: PassiveRuntimeLedger) -> PassiveLedgerDecision:
    warnings = tuple(ledger.warnings)
    blocked_reason = ledger.blocked_reason
    status = ledger.overall_status
    can_report_completed = status == "completed" and not blocked_reason and not ledger.partial_reasons
    can_report_pass = can_report_completed and ledger.verification_status not in {"stale", "unverified", "required"}
    if status in {"pending", "running", "partial", "blocked", "failed"}:
        can_report_completed = False
        can_report_pass = False
    return PassiveLedgerDecision(
        status=status,
        can_report_completed=can_report_completed,
        can_report_pass=can_report_pass,
        warnings=warnings,
        blocked_reason=blocked_reason,
        next_safe_action=ledger.next_safe_action,
    )


def ledger_to_final_report_warnings(
    ledger: PassiveRuntimeLedger,
    report_text: str | None = None,
) -> list[dict[str, str]]:
    warnings = [dict(item) for item in ledger.warnings]
    text = (report_text or "").casefold()
    if not text:
        return warnings

    def add(code: str, field_name: str, phrase: str, safe: str) -> None:
        warnings.append(
            {
                "code": code,
                "ledger_field": field_name,
                "event_id": str(ledger.latest_event_id),
                "offending_phrase": phrase,
                "safe_interpretation": safe,
            }
        )

    if _runtime_claims_completion(text) and ledger.overall_status != "completed":
        add(
            "PASSIVE_RUNTIME_COMPLETION_CONFLICT",
            "overall_status",
            _runtime_first_phrase(text, ("pass", "completed", "done")),
            f"Ledger status is {ledger.overall_status}; report that state instead of PASS/completed.",
        )
    if "verified" in text and ledger.verification_status in {"required", "stale", "unverified"}:
        add(
            "PASSIVE_RUNTIME_VERIFICATION_CONFLICT",
            "verification_status",
            "verified",
            f"Ledger verification_status is {ledger.verification_status}; do not claim verified.",
        )
    if any(term in text for term in ("pushed", "remote synced", "synced to remote")) and not ledger.remote_pushed:
        add(
            "PASSIVE_RUNTIME_REMOTE_PUSH_CONFLICT",
            "remote_pushed",
            "pushed",
            "Remote branch push must be verified before claiming remote sync.",
        )
    if any(term in text for term in ("tag pushed", "remote tag", "tag synced")) and not ledger.remote_tag_pushed:
        add(
            "PASSIVE_RUNTIME_REMOTE_TAG_CONFLICT",
            "remote_tag_pushed",
            "tag pushed",
            "Remote tag push must be verified separately from local tag creation.",
        )
    if any(term in text for term in ("all valid", "0 corrupted", "zero corrupted")):
        unsafe_docs = [
            path
            for path, status in ledger.document_statuses.items()
            if status in {"warning", "fail", "blocked", "unknown"}
        ]
        if unsafe_docs or any(level in {"binary_only", "parser_readable"} for level in ledger.document_claim_levels.values()):
            add(
                "PASSIVE_RUNTIME_DOCUMENT_AGGREGATE_CONFLICT",
                "document_statuses",
                _runtime_first_phrase(text, ("all valid", "0 corrupted", "zero corrupted")),
                "Batch document validity requires every file to pass every required check.",
            )
    if any(term in text for term in ("preview compatible", "target-app compatible", "target app compatible")):
        if any(level != "target_app_validated" for level in ledger.document_claim_levels.values()):
            add(
                "PASSIVE_RUNTIME_TARGET_APP_CLAIM_CONFLICT",
                "document_claim_levels",
                "target-app compatible",
                "Target-app compatibility requires an explicit target-app validation event.",
            )
    if ledger.report_only and any(term in text for term in ("wrote", "modified", "updated production", "production changed")):
        add(
            "PASSIVE_RUNTIME_REPORT_ONLY_WRITE_CONFLICT",
            "report_only",
            "wrote",
            "Report-only ledger state cannot be summarized as a non-report write.",
        )
    if ledger.dry_run and any(term in text for term in ("official updated", "baseline updated", "official baseline")):
        add(
            "PASSIVE_RUNTIME_DRY_RUN_OFFICIAL_CONFLICT",
            "dry_run",
            "official updated",
            "Dry-run ledger state cannot update official state.",
        )
    return warnings


def build_passive_events_from_runner_context(context: dict[str, Any]) -> list[PassiveRuntimeEvent]:
    data = context if isinstance(context, dict) else {}
    task_id = str(data.get("task_id") or "")
    events: list[PassiveRuntimeEvent] = []
    next_id = 1

    report_only = bool(data.get("report_only"))
    dry_run = bool(data.get("dry_run"))
    if any(key in data for key in ("report_only", "dry_run", "production_changed", "official_updated")):
        events.append(
            _runtime_event(
                next_id,
                "context_state",
                task_id,
                {
                    "report_only": report_only,
                    "dry_run": dry_run,
                    "production_changed": bool(data.get("production_changed")),
                    "official_updated": bool(data.get("official_updated")),
                },
            )
        )
        next_id += 1
    for path in _coerce_string_list(data.get("files_read")):
        events.append(_runtime_event(next_id, "file_access", task_id, {"operation": "read", "path": path}))
        next_id += 1
    for operation, key in (("write", "files_written"), ("delete", "files_deleted"), ("move", "files_moved"), ("copy", "files_copied")):
        for path in _coerce_string_list(data.get(key)):
            events.append(
                _runtime_event(
                    next_id,
                    "file_access",
                    task_id,
                    {
                        "operation": operation,
                        "path": path,
                        "report_only": report_only,
                        "dry_run": dry_run,
                    },
                )
            )
            next_id += 1

    if dry_run and bool(data.get("official_updated")):
        events.append(
            _runtime_event(
                next_id,
                "remote_sync",
                task_id,
                {"operation": "official_update", "dry_run": True, "official_updated": True},
            )
        )
        next_id += 1

    process_keys = {
        "process_status",
        "elapsed_seconds",
        "silence_seconds",
        "expected_silence_budget",
        "hard_timeout",
        "retry_count_same_error",
        "retry_count_total",
        "last_error_signature",
        "current_error_signature",
        "partial_output_present",
        "partial_output",
        "output_freshness",
        "auth_state",
        "quota_state",
        "path_state",
        "permission_state",
        "owner_tool",
        "stage_name",
    }
    if any(key in data for key in process_keys):
        events.append(
            _runtime_event(
                next_id,
                "process_status",
                task_id,
                {
                    "owner_tool": str(data.get("owner_tool") or ""),
                    "stage_name": str(data.get("stage_name") or ""),
                    "process_status": str(data.get("process_status") or data.get("status") or ""),
                    "elapsed_seconds": _optional_float(data.get("elapsed_seconds")),
                    "silence_seconds": _optional_float(data.get("silence_seconds")),
                    "expected_silence_budget": _optional_float(data.get("expected_silence_budget")),
                    "hard_timeout": _optional_float(data.get("hard_timeout")),
                    "retry_count_same_error": _optional_int(data.get("retry_count_same_error")) or 0,
                    "retry_count_total": _optional_int(data.get("retry_count_total")) or 0,
                    "last_error_signature": str(data.get("last_error_signature") or ""),
                    "current_error_signature": str(data.get("current_error_signature") or ""),
                    "partial_output_present": bool(data.get("partial_output_present") or data.get("partial_output")),
                    "output_freshness": str(data.get("output_freshness") or ""),
                    "auth_state": str(data.get("auth_state") or ""),
                    "quota_state": str(data.get("quota_state") or ""),
                    "path_state": str(data.get("path_state") or ""),
                    "permission_state": str(data.get("permission_state") or ""),
                },
            )
        )
        next_id += 1

    latest_write = _optional_int(data.get("latest_write_event_id") or data.get("latest_modification_event_id"))
    latest_verification = _optional_int(data.get("latest_verification_event_id"))
    if latest_write is not None and not any(event.event_id == latest_write for event in events):
        events.append(
            _runtime_event(
                latest_write,
                "file_access",
                task_id,
                {
                    "operation": "write",
                    "path": str(data.get("latest_write_path") or data.get("latest_modification_path") or "unknown"),
                    "report_only": report_only,
                    "dry_run": dry_run,
                },
            )
        )
    if latest_verification is not None:
        events.append(
            _runtime_event(
                latest_verification,
                "verification",
                task_id,
                {
                    "result": str(data.get("latest_verification_result") or "pass"),
                    "verifies_after_event_id": _optional_int(data.get("verifies_after_event_id")),
                    "stale_if_before_event_id": latest_write,
                },
            )
        )

    task_text = str(data.get("task_text") or data.get("query") or "")
    files = _coerce_string_list(data.get("files") or data.get("file_inventory"))
    if task_text and classify_document_validation_trigger(task_text) and not files:
        events.append(
            _runtime_event(
                _next_event_id(events),
                "document_validation",
                task_id,
                {
                    "status": "unknown",
                    "checks_missing": ["file_inventory"],
                    "safe_claim_level": "binary_only",
                },
            )
        )
    if task_text and classify_long_run_trigger(task_text) and not any(
        key in data for key in ("process_status", "last_output_at", "silence_seconds", "elapsed_seconds")
    ):
        events.append(
            _runtime_event(
                _next_event_id(events),
                "adapter_warning",
                task_id,
                {
                    "code": "PASSIVE_RUNTIME_WATCHDOG_STATUS_REQUIRED",
                    "ledger_field": "overall_status",
                    "safe_interpretation": "Collect process_status, last_output_at, elapsed, silence_seconds, retry_count, and next_safe_action before reporting completion.",
                },
            )
        )
    return _sort_runtime_events(events)


def build_passive_events_from_report_context(report_context: dict[str, Any]) -> list[PassiveRuntimeEvent]:
    data = report_context if isinstance(report_context, dict) else {}
    report_text = str(data.get("report_text") or data.get("final_report_text") or data.get("text") or "")
    task_id = str(data.get("task_id") or "")
    return [
        _runtime_event(event.event_id, "report_claim", task_id, asdict(event))
        for event in extract_report_claim_events(report_text, task_id=task_id)
    ]


def build_passive_events_from_validation_context(validation_context: dict[str, Any]) -> list[PassiveRuntimeEvent]:
    data = validation_context if isinstance(validation_context, dict) else {}
    task_id = str(data.get("task_id") or "")
    events: list[PassiveRuntimeEvent] = []
    latest_write = _optional_int(data.get("latest_write_event_id") or data.get("latest_modification_event_id"))
    latest_verification = _optional_int(data.get("latest_verification_event_id"))
    if latest_write is not None:
        events.append(
            _runtime_event(
                latest_write,
                "file_access",
                task_id,
                {"operation": "write", "path": str(data.get("latest_write_path") or "unknown")},
            )
        )
    if latest_verification is not None:
        events.append(
            _runtime_event(
                latest_verification,
                "verification",
                task_id,
                {
                    "result": str(data.get("verification_result") or data.get("result") or "pass"),
                    "verifies_after_event_id": _optional_int(data.get("verifies_after_event_id")),
                    "stale_if_before_event_id": latest_write,
                },
            )
        )
    for item in _coerce_dict_list(data.get("document_validation_results")):
        events.append(_runtime_event(_next_event_id(events), "document_validation", task_id, item))
    return _sort_runtime_events(events)


def build_passive_events_from_remote_sync_context(remote_context: dict[str, Any]) -> list[PassiveRuntimeEvent]:
    data = remote_context if isinstance(remote_context, dict) else {}
    task_id = str(data.get("task_id") or "")
    events: list[PassiveRuntimeEvent] = []
    if bool(data.get("ls_remote_success") or data.get("read_access")):
        events.append(
            _runtime_event(
                1,
                "remote_sync",
                task_id,
                {
                    "operation": "ls_remote",
                    "remote": str(data.get("remote") or ""),
                    "branch": str(data.get("branch") or ""),
                    "read_access": True,
                },
            )
        )
    if bool(data.get("write_attempted") or data.get("branch_push_attempted") or data.get("write_success")):
        events.append(
            _runtime_event(
                _next_event_id(events),
                "remote_sync",
                task_id,
                {
                    "operation": "branch_push",
                    "remote": str(data.get("remote") or ""),
                    "branch": str(data.get("branch") or ""),
                    "write_attempted": bool(data.get("write_attempted") or data.get("branch_push_attempted")),
                    "write_success": bool(data.get("write_success")),
                    "verified": bool(data.get("write_verified") or data.get("branch_verified")),
                    "remote_head_before": str(data.get("remote_head_before") or ""),
                    "remote_head_after": str(data.get("remote_head_after") or ""),
                },
            )
        )
    local_tag = str(data.get("local_tag") or "")
    remote_tag_verified = bool(data.get("remote_tag_verified") or data.get("tag_verified"))
    if local_tag and not remote_tag_verified:
        events.append(
            _runtime_event(
                _next_event_id(events),
                "remote_sync",
                task_id,
                {"operation": "local_tag", "tag": local_tag, "tag_verified": False},
            )
        )
    if bool(data.get("tag_pushed") or remote_tag_verified):
        events.append(
            _runtime_event(
                _next_event_id(events),
                "remote_sync",
                task_id,
                {
                    "operation": "tag_push",
                    "tag_pushed": bool(data.get("tag_pushed") or remote_tag_verified),
                    "tag_verified": remote_tag_verified,
                },
            )
        )
    if bool(data.get("official_updated")) or bool(data.get("dry_run")):
        events.append(
            _runtime_event(
                _next_event_id(events),
                "remote_sync",
                task_id,
                {
                    "operation": "official_update",
                    "dry_run": bool(data.get("dry_run")),
                    "official_updated": bool(data.get("official_updated")),
                },
            )
        )
    return _sort_runtime_events(events)


def build_passive_events_from_subtask_context(subtasks: dict[str, Any] | list[Any] | tuple[Any, ...]) -> list[PassiveRuntimeEvent]:
    events: list[PassiveRuntimeEvent] = []
    for item in _iter_subtask_items(subtasks):
        events.append(_runtime_event(len(events) + 1, "subtask_status", str(item.get("task_id") or ""), item))
    return events


def merge_supplied_and_derived_passive_events(
    supplied_events: Any,
    derived_events: Any,
) -> list[PassiveRuntimeEvent]:
    supplied = _normalize_runtime_event_sequence(supplied_events)
    derived = _normalize_runtime_event_sequence(derived_events)
    merged: list[PassiveRuntimeEvent] = []
    used_ids: set[int] = set()
    supplied_ids: set[int] = set()
    next_id = 1

    for event in supplied:
        event_id = event.event_id if event.event_id > 0 else next_id
        while event_id in used_ids:
            event_id += 1
        normalized = replace(event, event_id=event_id)
        merged.append(normalized)
        used_ids.add(event_id)
        supplied_ids.add(event_id)
        next_id = max(next_id, event_id + 1)

    for event in _sort_runtime_events(derived):
        event_id = event.event_id if event.event_id > 0 else next_id
        if event_id in supplied_ids:
            warning_id = _next_available_event_id(used_ids, next_id)
            warning = _runtime_event(
                warning_id,
                "adapter_warning",
                event.task_id,
                {
                    "code": "PASSIVE_RUNTIME_EVENT_ID_CONFLICT",
                    "ledger_field": "events_seen",
                    "safe_interpretation": "Supplied event id was preserved; derived event was re-numbered.",
                    "conflicting_event_id": event.event_id,
                },
            )
            merged.append(warning)
            used_ids.add(warning_id)
            next_id = max(next_id, warning_id + 1)
        if event_id in used_ids:
            event_id = _next_available_event_id(used_ids, next_id)
        normalized = replace(event, event_id=event_id)
        merged.append(normalized)
        used_ids.add(event_id)
        next_id = max(next_id, event_id + 1)
    return merged


def extract_report_claim_events(report_text: str, task_id: str | None = None) -> list[ReportClaimEvent]:
    text = report_text or ""
    lowered = text.casefold()
    claims: list[tuple[str, str, str]] = []
    for claim_type, pattern, phrase in (
        ("pass", r"\bpass\b", "PASS"),
        ("completed", r"\b(completed|complete|done|finished)\b", "completed"),
        ("verified", r"\bverified\b", "verified"),
        ("pushed", r"\b(pushed|remote synced|synced to remote)\b", "pushed"),
        ("tag_synced", r"\b(tag pushed|remote tag|tag synced)\b", "tag pushed"),
        ("official_updated", r"\b(official updated|baseline updated|official baseline)\b", "official updated"),
        ("production_changed", r"\b(production changed|updated production)\b", "production changed"),
        ("all_valid", r"\ball valid\b", "all valid"),
        ("zero_corrupted", r"\b(0 corrupted|zero corrupted)\b", "0 corrupted"),
        ("all_phases_complete", r"\ball phases complete\b", "all phases complete"),
    ):
        if re.search(pattern, lowered):
            claims.append((claim_type, phrase, phrase))
    return [
        ReportClaimEvent(
            event_id=index,
            claim_text=phrase,
            claim_type=claim_type,
            referenced_status="",
            confidence="conservative",
            needs_ledger_check=True,
        )
        for index, (claim_type, phrase, _claim) in enumerate(claims, start=1)
    ]


def classify_document_validation_requirements(file_path: str, intended_use: str | None = None) -> DocumentValidationPlan:
    intended = (intended_use or "").strip()
    lowered = intended.casefold()
    suffix = file_path.rsplit(".", 1)[-1].casefold() if "." in file_path else ""
    file_type = "pdf" if suffix == "pdf" or "pdf" in lowered else suffix or "unknown"
    required: list[str] = []
    optional: list[str] = []
    platform: list[str] = []
    if file_type == "pdf":
        required.extend(["binary_signature", "parser_readable"])
        optional.extend(["render_check", "target_app_compatibility"])
        if any(term in lowered for term in ("complete", "valid", "production", "share", "deliver", "user use")):
            required.append("render_check")
        if "preview" in lowered or "macos" in lowered or "quicklook" in lowered:
            required.append("macos_preview_compatibility")
            platform.extend(["qlmanage_preview", "mdls_metadata"])
        if "target app" in lowered:
            required.append("target_app_compatibility")
    else:
        required.append("file_exists")
        optional.append("target_app_compatibility")
    return DocumentValidationPlan(
        file_path=file_path,
        file_type=file_type,
        intended_use=intended,
        required_checks=tuple(dict.fromkeys(required)),
        optional_checks=tuple(dict.fromkeys(optional)),
        platform_specific_checks=tuple(dict.fromkeys(platform)),
        overclaim_prohibited_phrases=(
            "PDF fully valid",
            "fully valid PDF",
            "0 corrupted",
            "zero corrupted",
            "all valid",
            "Preview compatible",
            "target-app compatible",
        ),
    )


def inspect_pdf_binary_signatures(file_path: str) -> PdfSignatureResult:
    notes: list[str] = []
    try:
        with open(file_path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        return PdfSignatureResult(False, False, False, 0, True, (f"read_failed:{exc.__class__.__name__}",))
    size = len(data)
    has_header = data[:1024].lstrip().startswith(b"%PDF-")
    has_eof = b"%%EOF" in data
    eof_near_tail = b"%%EOF" in data[-2048:] if data else False
    if not has_header:
        notes.append("missing_pdf_header")
    if not has_eof:
        notes.append("missing_eof_marker")
    elif not eof_near_tail:
        notes.append("eof_marker_not_near_tail")
    suspicious = not has_header or not has_eof or not eof_near_tail or size == 0
    return PdfSignatureResult(has_header, has_eof, eof_near_tail, size, suspicious, tuple(notes))


def classify_pdf_validation_result(results: dict[str, Any]) -> DocumentValidationDecision:
    data = results if isinstance(results, dict) else {}
    plan = data.get("plan")
    if isinstance(plan, DocumentValidationPlan):
        required_checks = set(plan.required_checks)
    else:
        required_checks = set(str(item) for item in data.get("required_checks") or ())
    checks_run = tuple(str(item) for item in data.get("checks_run") or ())
    checks_missing = list(str(item) for item in data.get("checks_missing") or ())
    parser_readable = _optional_bool(data.get("parser_readable"))
    render_check_ok = _optional_bool(data.get("render_check_ok"))
    macos_preview_compatible = _optional_bool(data.get("macos_preview_compatible"))
    target_app_compatible = _optional_bool(data.get("target_app_compatible"))
    signature = _coerce_pdf_signature(data.get("binary_signature") or data)
    binary_signature_ok = _optional_bool(data.get("binary_signature_ok"))
    if binary_signature_ok is None and signature is not None:
        binary_signature_ok = signature.has_pdf_header and signature.has_eof_marker and signature.eof_marker_near_tail

    if "binary_signature" in required_checks and binary_signature_ok is not True:
        checks_missing = _append_missing(checks_missing, "binary_signature") if binary_signature_ok is None else checks_missing
    if "parser_readable" in required_checks and parser_readable is not True:
        checks_missing = _append_missing(checks_missing, "parser_readable") if parser_readable is None else checks_missing
    if "render_check" in required_checks and render_check_ok is not True:
        checks_missing = _append_missing(checks_missing, "render_check") if render_check_ok is None else checks_missing
    if "macos_preview_compatibility" in required_checks and macos_preview_compatible is not True:
        checks_missing = _append_missing(checks_missing, "macos_preview_compatibility") if macos_preview_compatible is None else checks_missing
    if "target_app_compatibility" in required_checks and target_app_compatible is not True:
        checks_missing = _append_missing(checks_missing, "target_app_compatibility") if target_app_compatible is None else checks_missing

    blocked_reason = ""
    status = "unknown"
    if binary_signature_ok is False:
        status = "fail"
        blocked_reason = "pdf_binary_signature_failed"
    elif parser_readable is False:
        status = "fail"
        blocked_reason = "pdf_parser_failed"
    elif render_check_ok is False:
        status = "fail"
        blocked_reason = "pdf_render_check_failed"
    elif macos_preview_compatible is False or target_app_compatible is False:
        status = "fail"
        blocked_reason = "target_application_check_failed"
    elif checks_missing:
        status = "unknown" if any(check in required_checks for check in checks_missing) else "warning"
    elif required_checks and _all_required_checks_pass(required_checks, binary_signature_ok, parser_readable, render_check_ok, macos_preview_compatible, target_app_compatible):
        status = "pass"
    elif parser_readable is True:
        status = "warning"

    safe_claim_level = _document_safe_claim_level(
        binary_signature_ok=binary_signature_ok,
        parser_readable=parser_readable,
        render_check_ok=render_check_ok,
        target_app_compatible=target_app_compatible,
        macos_preview_compatible=macos_preview_compatible,
    )
    missing_reason = str(data.get("missing_check_reason") or ("required_checks_missing" if checks_missing else ""))
    summary = _document_summary_text(status, safe_claim_level, checks_missing, blocked_reason)
    return DocumentValidationDecision(
        status=status,
        parser_readable=parser_readable,
        binary_signature_ok=binary_signature_ok,
        render_check_ok=render_check_ok,
        macos_preview_compatible=macos_preview_compatible,
        target_app_compatible=target_app_compatible,
        checks_run=tuple(dict.fromkeys(checks_run)),
        checks_missing=tuple(dict.fromkeys(checks_missing)),
        missing_check_reason=missing_reason,
        blocked_reason=blocked_reason,
        safe_claim_level=safe_claim_level,
        user_facing_summary=summary,
    )


def build_document_validation_warning(decision: DocumentValidationDecision, report_text: str = "") -> dict[str, Any]:
    phrase = _first_claim_phrase(
        report_text,
        ("PDF fully valid", "fully valid PDF", "0 corrupted", "zero corrupted", "all valid", "Preview compatible", "target-app compatible"),
    )
    code = "PASSIVE_DOCUMENT_VALIDATION_OVERCLAIM"
    if phrase and decision.status != "pass":
        code = "PASSIVE_DOCUMENT_VALIDATION_OVERCLAIM"
    elif decision.status == "fail":
        code = "PASSIVE_DOCUMENT_VALIDATION_FAILED"
    elif decision.status == "unknown":
        code = "PASSIVE_DOCUMENT_VALIDATION_UNKNOWN"
    elif not phrase and decision.status == "pass":
        code = "PASSIVE_DOCUMENT_VALIDATION_OK"
    return {
        "code": code,
        "status": decision.status,
        "offending_phrase": phrase,
        "safe_claim_level": decision.safe_claim_level,
        "checks_missing": list(decision.checks_missing),
        "safe_interpretation": safe_document_validation_summary(decision),
        "warning_only": True,
    }


def safe_document_validation_summary(decision: DocumentValidationDecision) -> str:
    return decision.user_facing_summary


def summarize_document_validation_batch(decisions: list[DocumentValidationDecision] | tuple[DocumentValidationDecision, ...]) -> dict[str, Any]:
    items = list(decisions or [])
    passed = [item for item in items if item.status == "pass"]
    warnings = [item for item in items if item.status == "warning"]
    failed = [item for item in items if item.status in {"fail", "blocked"}]
    unknown = [item for item in items if item.status == "unknown"]
    return {
        "files_checked": len(items),
        "files_passed_all_required_checks": len(passed),
        "files_with_warnings": len(warnings),
        "files_failed": len(failed),
        "files_unknown_due_missing_checks": len(unknown),
        "all_valid_claim_allowed": bool(items) and len(passed) == len(items),
    }


def classify_error_kind(error_text: str | None) -> str:
    text = (error_text or "").casefold()
    if any(term in text for term in ("permission denied", "access denied", "forbidden")):
        return "permission"
    if any(term in text for term in ("unauthorized", "auth", "login required")):
        return "auth"
    if "session" in text:
        return "session"
    if "quota" in text or "rate limit" in text:
        return "quota"
    if any(term in text for term in ("path not found", "no such file", "not a directory")):
        return "path"
    if any(term in text for term in ("remote ahead", "diverged", "non-fast-forward", "fetch first")):
        return "remote_diverged"
    if any(term in text for term in ("connection reset", "temporarily unavailable", "network", "dns", "502", "503", "504")):
        return "transient_network"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if any(term in text for term in ("validation", "schema", "assert")):
        return "validation"
    return "unknown"


def compute_retry_signature(error_text: str | None, exit_code: int | None = None) -> str:
    text = re.sub(r"\s+", " ", (error_text or "").strip().casefold())
    text = re.sub(r"0x[0-9a-f]+|\d{4,}", "<num>", text)
    first = text[:160]
    kind = classify_error_kind(first)
    code = "" if exit_code is None else f":exit_{exit_code}"
    return f"{kind}{code}:{first}"


def get_stage_timeout_policy(stage_name: str, owner_tool: str | None = None) -> TimeoutPolicy:
    stage = (stage_name or "generic_subprocess").strip().casefold().replace("-", "_")
    owner = (owner_tool or "").strip().casefold().replace("-", "_")
    key = stage or owner or "generic_subprocess"
    table: dict[str, tuple[int, int, int, int, int, int]] = {
        "codex_handoff": (120, 900, 1800, 120, 3, 5),
        "gpt_bridge": (60, 300, 900, 60, 3, 4),
        "agy": (90, 600, 1200, 90, 3, 4),
        "research_decision_intelligence_layer": (180, 1800, 3600, 180, 3, 4),
        "decision_external_calibration": (120, 1200, 2400, 120, 3, 4),
        "browser_gui": (90, 600, 1200, 90, 2, 3),
        "batch_download": (300, 1800, 7200, 300, 3, 6),
        "generic_subprocess": (75, 600, 1800, 75, 3, 4),
    }
    values = table.get(key) or table.get(owner) or table["generic_subprocess"]
    silence, soft, hard, inspect, same_limit, total_limit = values
    return TimeoutPolicy(
        stage_name=key if key in table else "generic_subprocess",
        owner_tool=owner,
        expected_silence_budget=silence,
        soft_timeout=soft,
        hard_timeout=hard,
        inspect_after_silence=inspect,
        retry_limit_same_error=same_limit,
        retry_limit_total=total_limit,
        allow_retry_error_kinds=("transient_network", "timeout"),
        block_error_kinds=("auth", "session", "quota", "permission", "path", "remote_diverged"),
    )


def classify_long_run_event(state: LongRunState | dict[str, Any]) -> WatchdogDecision:
    long_state = _coerce_long_run_state(state)
    policy = get_stage_timeout_policy(long_state.stage_name, long_state.owner_tool)
    process_status = long_state.process_status.casefold()
    signature = long_state.current_error_signature or long_state.last_error_signature
    error_kind = classify_error_kind(signature)
    silence_budget = long_state.expected_silence_budget if long_state.expected_silence_budget is not None else policy.expected_silence_budget
    hard_timeout = long_state.hard_timeout if long_state.hard_timeout is not None else policy.hard_timeout

    if _explicit_blocking_state(long_state) or error_kind in policy.block_error_kinds:
        return WatchdogDecision(False, True, False, True, f"{error_kind}_error_requires_owner_action", "Block and surface the owner action required.", "blocked")
    if "timeout" in process_status and long_state.partial_output_present:
        return WatchdogDecision(False, True, False, False, "timeout_with_partial_output", "Mark partial and inspect partial output; do not report completed.", "partial")
    if long_state.incomplete_phases and process_status in {"completed", "pass", "passed", "success"}:
        return WatchdogDecision(False, True, False, True, "completed_claim_with_incomplete_phases", "Report partial/incomplete phases instead of PASS.", "blocked")
    if long_state.retry_count_same_error >= policy.retry_limit_same_error:
        if error_kind in policy.allow_retry_error_kinds and long_state.retry_count_total < policy.retry_limit_total:
            return WatchdogDecision(False, False, True, False, "", "Retry once with backoff; block on another repeat.", "retry")
        return WatchdogDecision(False, True, False, True, "same_error_repeated_3_times", "Block and surface the repeated error signature.", "blocked")
    if long_state.retry_count_same_error >= 2:
        if error_kind in policy.allow_retry_error_kinds and long_state.retry_count_total < policy.retry_limit_total:
            return WatchdogDecision(False, False, True, False, "", "Retry transient error within policy budget.", "retry")
        return WatchdogDecision(False, True, False, False, "same_error_repeated_2_times", "Inspect repeated error before retrying.", "running")
    if process_status in {"running", "waiting"}:
        if long_state.elapsed_seconds >= hard_timeout:
            status = "partial" if long_state.partial_output_present else "blocked"
            return WatchdogDecision(False, True, False, not long_state.partial_output_present, "hard_timeout_exceeded", "Inspect before any retry or completion claim.", status)
        if long_state.silence_seconds <= silence_budget:
            return WatchdogDecision(True, False, False, False, "", "Wait within expected silence budget.", process_status)
        return WatchdogDecision(False, True, False, False, "silence_budget_exceeded", "Inspect process output and child process state.", process_status)
    if "timeout" in process_status:
        return WatchdogDecision(False, True, False, False, "timeout_without_success", "Inspect timeout details; do not report PASS.", "partial")
    if process_status in {"failed", "error", "cancelled"}:
        return WatchdogDecision(False, True, False, True, f"process_{process_status}", "Block and report the failure state.", "blocked")
    return WatchdogDecision(False, False, False, False, "", "No watchdog action required.", process_status or "unknown")


def update_long_run_ledger(ledger: StatusLedger, event: dict[str, Any]) -> StatusLedger:
    decision = classify_long_run_event(event.get("state") if isinstance(event.get("state"), dict) else event)
    payload: dict[str, Any] = {"event_type": "long_run", "task_status": decision.status}
    if decision.should_block:
        payload.update({"event_type": "blocked", "blocked_reason": decision.blocked_reason})
    elif decision.status == "partial":
        payload["task_status"] = "partial"
    return update_status_ledger(ledger, payload)


def safe_long_run_status_summary(decision: WatchdogDecision) -> str:
    if decision.status in {"running", "waiting"}:
        return "Still running or waiting; do not report PASS."
    if decision.status == "partial":
        return "Partial output or timeout state; inspect before claiming completion."
    if decision.should_block:
        return f"Blocked: {decision.blocked_reason or 'owner action required'}."
    if decision.should_retry:
        return "Retry allowed within policy budget."
    return decision.next_safe_action


def classify_watchdog_state(state: dict[str, Any]) -> WatchdogDecision:
    return classify_long_run_event(state)


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


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "pass", "passed", "ok"}:
            return True
        if normalized in {"false", "no", "0", "fail", "failed"}:
            return False
        return None
    return bool(value)


def _coerce_pdf_signature(value: Any) -> PdfSignatureResult | None:
    if isinstance(value, PdfSignatureResult):
        return value
    if not isinstance(value, dict):
        return None
    if not any(key in value for key in ("has_pdf_header", "has_eof_marker", "eof_marker_near_tail", "file_size_bytes")):
        return None
    has_header = bool(value.get("has_pdf_header"))
    has_eof = bool(value.get("has_eof_marker"))
    eof_tail = bool(value.get("eof_marker_near_tail"))
    size = int(value.get("file_size_bytes") or 0)
    suspicious = bool(value.get("suspicious_truncation", not (has_header and has_eof and eof_tail)))
    notes = tuple(str(item) for item in value.get("notes") or ())
    return PdfSignatureResult(has_header, has_eof, eof_tail, size, suspicious, notes)


def _append_missing(values: list[str], check: str) -> list[str]:
    if check not in values:
        values.append(check)
    return values


def _all_required_checks_pass(
    required_checks: set[str],
    binary_signature_ok: bool | None,
    parser_readable: bool | None,
    render_check_ok: bool | None,
    macos_preview_compatible: bool | None,
    target_app_compatible: bool | None,
) -> bool:
    state = {
        "binary_signature": binary_signature_ok,
        "parser_readable": parser_readable,
        "render_check": render_check_ok,
        "macos_preview_compatibility": macos_preview_compatible,
        "target_app_compatibility": target_app_compatible,
    }
    return all(state.get(check) is True for check in required_checks)


def _document_safe_claim_level(
    *,
    binary_signature_ok: bool | None,
    parser_readable: bool | None,
    render_check_ok: bool | None,
    target_app_compatible: bool | None,
    macos_preview_compatible: bool | None,
) -> str:
    if target_app_compatible is True or macos_preview_compatible is True:
        return "target_app_validated"
    if render_check_ok is True:
        return "rendered"
    if binary_signature_ok is True and parser_readable is True:
        return "structurally_validated"
    if parser_readable is True:
        return "parser_readable"
    return "binary_only" if binary_signature_ok is True else "binary_only"


def _document_summary_text(status: str, safe_claim_level: str, checks_missing: list[str], blocked_reason: str) -> str:
    if status == "pass":
        return f"Document passed the required checks; safe claim level: {safe_claim_level}."
    if status == "fail":
        return f"Document validation failed ({blocked_reason}); do not claim the file is fully valid."
    if checks_missing:
        missing = ", ".join(checks_missing)
        return f"Document validation is incomplete; missing checks: {missing}. Safe claim level: {safe_claim_level}."
    return f"Document validation produced warnings; safe claim level: {safe_claim_level}."


def _coerce_long_run_state(state: LongRunState | dict[str, Any]) -> LongRunState:
    if isinstance(state, LongRunState):
        return state
    data = state if isinstance(state, dict) else {}
    partial_output_present = bool(data.get("partial_output_present") or data.get("partial_output"))
    current_sig = str(data.get("current_error_signature") or "")
    last_sig = str(data.get("last_error_signature") or "")
    retry_same = int(data.get("retry_count_same_error") or 0)
    if retry_same == 0 and current_sig and last_sig and current_sig == last_sig:
        retry_same = 1
    incomplete = data.get("incomplete_phases") or data.get("partial_phases") or ()
    if isinstance(incomplete, str):
        incomplete = (incomplete,)
    return LongRunState(
        task_id=str(data.get("task_id") or ""),
        owner_tool=str(data.get("owner_tool") or ""),
        stage_name=str(data.get("stage_name") or data.get("stage") or "generic_subprocess"),
        process_status=str(data.get("process_status") or data.get("status") or ""),
        elapsed_seconds=float(data.get("elapsed_seconds") or 0),
        silence_seconds=float(data.get("silence_seconds") or 0),
        expected_silence_budget=_optional_float(data.get("expected_silence_budget")),
        hard_timeout=_optional_float(data.get("hard_timeout")),
        retry_count_same_error=retry_same,
        retry_count_total=int(data.get("retry_count_total") or 0),
        last_error_signature=last_sig,
        current_error_signature=current_sig,
        partial_output_present=partial_output_present,
        output_freshness=str(data.get("output_freshness") or ""),
        auth_state=str(data.get("auth_state") or ""),
        quota_state=str(data.get("quota_state") or ""),
        path_state=str(data.get("path_state") or ""),
        permission_state=str(data.get("permission_state") or ""),
        incomplete_phases=tuple(str(item) for item in incomplete),
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _explicit_blocking_state(state: LongRunState) -> bool:
    blocked_values = {"missing", "invalid", "denied", "expired", "blocked", "exhausted", "not_found"}
    return any(
        value.strip().casefold() in blocked_values
        for value in (state.auth_state, state.quota_state, state.path_state, state.permission_state)
        if value
    )


def _infer_document_paths(text: str) -> list[str]:
    candidates = re.findall(r"(?<![\w/.-])(?:[A-Za-z0-9_./-]+?\.(?:pdf|PDF))(?![\w.-])", text or "")
    cleaned: list[str] = []
    for candidate in candidates:
        value = candidate.strip().strip("`'\".,;:()[]{}")
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _infer_document_intended_use(text: str) -> str:
    lowered = (text or "").casefold()
    parts: list[str] = []
    if "preview" in lowered or "quicklook" in lowered or "macos" in lowered:
        parts.append("macOS Preview compatibility")
    if "0 corrupted" in lowered or "zero corrupted" in lowered or "all valid" in lowered or "verify all" in lowered:
        parts.append("complete batch validation")
    if "render" in lowered:
        parts.append("render validation")
    return "; ".join(parts)


def _document_trigger_reasons(text: str, files: tuple[str, ...]) -> tuple[str, ...]:
    lowered = (text or "").casefold()
    reasons: list[str] = []
    if files:
        reasons.append("document_files_detected")
    for term, reason in (
        ("pdf", "pdf_task"),
        ("ocr", "ocr_task"),
        ("render", "render_check_requested"),
        ("preview", "target_app_preview_requested"),
        ("qlmanage", "quicklook_check_requested"),
        ("pymupdf", "parser_check_mentioned"),
        ("0 corrupted", "zero_corrupted_claim_risk"),
        ("zero corrupted", "zero_corrupted_claim_risk"),
        ("all valid", "all_valid_claim_risk"),
        ("verify all", "batch_validation_requested"),
        ("文件完整性", "document_integrity_requested"),
        ("截断", "truncation_risk_requested"),
    ):
        if term in lowered:
            reasons.append(reason)
    return tuple(dict.fromkeys(reasons))


def _is_batch_document_request(lowered_text: str, files: tuple[str, ...]) -> bool:
    return len(files) > 1 or any(term in lowered_text for term in ("all pdf", "all valid", "0 corrupted", "zero corrupted", "batch", "verify all"))


def _infer_platform(lowered_text: str) -> str:
    if "macos" in lowered_text or "preview" in lowered_text or "quicklook" in lowered_text or "qlmanage" in lowered_text:
        return "macos"
    return "portable"


def _infer_target_app(lowered_text: str) -> str:
    if "preview" in lowered_text:
        return "preview"
    if "quicklook" in lowered_text or "qlmanage" in lowered_text:
        return "quicklook"
    return ""


def _document_prohibited_claims(lowered_text: str, batch: bool) -> tuple[str, ...]:
    claims = ["PDF fully valid", "fully valid PDF", "0 corrupted", "zero corrupted", "all valid"]
    if "preview" in lowered_text or "quicklook" in lowered_text:
        claims.extend(["Preview compatible", "target-app compatible"])
    if batch:
        claims.extend(["all files valid", "batch fully valid"])
    return tuple(dict.fromkeys(claims))


def _parser_only_claim_context(lowered_text: str) -> bool:
    parser_terms = ("pymupdf", "parser", "parser-readable", "parser readable")
    full_check_terms = ("render", "preview", "quicklook", "binary signature", "eof", "target app")
    return any(term in lowered_text for term in parser_terms) and not any(term in lowered_text for term in full_check_terms)


def _merge_tuple_values(*groups: tuple[str, ...]) -> tuple[str, ...]:
    result: tuple[str, ...] = ()
    for group in groups:
        for item in group:
            result = _append_unique(result, item)
    return result


def _infer_owner_tool(text: str, owner_tool: str | None) -> str:
    if owner_tool:
        return owner_tool.strip().casefold().replace("-", "_")
    lowered = (text or "").casefold()
    if "codex" in lowered:
        return "codex_handoff"
    if "gpt bridge" in lowered:
        return "gpt_bridge"
    if "agy" in lowered:
        return "agy"
    if "browser gui" in lowered or "openclaw" in lowered:
        return "browser_gui"
    if "batch download" in lowered or "download" in lowered:
        return "batch_download"
    if "subprocess" in lowered:
        return "generic_subprocess"
    return "generic_subprocess"


def _infer_stage_name(text: str, stage_name: str | None, owner: str) -> str:
    if stage_name:
        return stage_name.strip().casefold().replace("-", "_")
    lowered = (text or "").casefold()
    if "external_calibration" in lowered or "external calibration" in lowered:
        return "decision_external_calibration"
    if "intelligence_layer" in lowered or "intelligence layer" in lowered:
        return "research_decision_intelligence_layer"
    return owner or "generic_subprocess"


def _long_run_trigger_reasons(text: str, owner: str, stage: str) -> tuple[str, ...]:
    lowered = (text or "").casefold()
    reasons: list[str] = []
    if owner and owner != "generic_subprocess":
        reasons.append(f"owner_tool:{owner}")
    if stage and stage != owner:
        reasons.append(f"stage:{stage}")
    for term, reason in (
        ("timeout", "timeout_mentioned"),
        ("stuck", "stuck_mentioned"),
        ("silent", "silence_mentioned"),
        ("no output", "no_output_mentioned"),
        ("waiting", "waiting_mentioned"),
        ("running", "running_mentioned"),
        ("subprocess", "subprocess_mentioned"),
        ("卡住", "stuck_mentioned"),
        ("等待", "waiting_mentioned"),
        ("没返回", "no_output_mentioned"),
    ):
        if term in lowered:
            reasons.append(reason)
    return tuple(dict.fromkeys(reasons))


def _coerce_passive_guard_mode(mode: str) -> str:
    normalized = (mode or "off").strip().casefold().replace("-", "_")
    if normalized not in {"off", "debug", "warn", "block_destructive"}:
        return "off"
    return normalized


def _runtime_event(event_id: int, event_type: str, task_id: str, payload: dict[str, Any]) -> PassiveRuntimeEvent:
    return PassiveRuntimeEvent(
        event_id=event_id,
        event_type=event_type,
        task_id=task_id,
        payload=dict(payload),
    )


def _coerce_string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(item) for item in value.values() if item is not None and str(item)]
    try:
        return [str(item) for item in value if item is not None and str(item)]
    except TypeError:
        return [str(value)]


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, dict):
        return [dict(value)]
    result: list[dict[str, Any]] = []
    try:
        iterator = iter(value)
    except TypeError:
        return []
    for item in iterator:
        if isinstance(item, dict):
            result.append(dict(item))
    return result


def _iter_subtask_items(subtasks: dict[str, Any] | list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    if isinstance(subtasks, dict):
        items: list[dict[str, Any]] = []
        for key, value in subtasks.items():
            data = dict(value) if isinstance(value, dict) else {"status": value}
            data.setdefault("subtask_id", str(key))
            items.append(data)
        return items
    result: list[dict[str, Any]] = []
    if isinstance(subtasks, (list, tuple)):
        for index, item in enumerate(subtasks, start=1):
            data = dict(item) if isinstance(item, dict) else {"status": item}
            data.setdefault("subtask_id", str(data.get("id") or data.get("phase") or f"subtask_{index}"))
            result.append(data)
    return result


def _normalize_runtime_event_sequence(value: Any) -> list[PassiveRuntimeEvent]:
    if value is None:
        return []
    if isinstance(value, (PassiveRuntimeEvent, FileAccessEvent, VerificationEvent, SubtaskStatusEvent, ProcessStatusEvent, DocumentValidationEvent, RemoteSyncEvent, ReportClaimEvent)):
        return [_coerce_passive_runtime_event(value)]
    if isinstance(value, dict):
        return [_coerce_passive_runtime_event(value)]
    events: list[PassiveRuntimeEvent] = []
    try:
        iterator = iter(value)
    except TypeError:
        return []
    for item in iterator:
        events.append(_coerce_passive_runtime_event(item))
    return events


def _sort_runtime_events(events: list[PassiveRuntimeEvent]) -> list[PassiveRuntimeEvent]:
    return sorted(
        events,
        key=lambda event: (
            event.event_id if event.event_id > 0 else 10**9,
            event.event_type,
            repr(sorted(event.payload.items())),
        ),
    )


def _next_event_id(events: list[PassiveRuntimeEvent]) -> int:
    return max((event.event_id for event in events), default=0) + 1


def _next_available_event_id(used_ids: set[int], start: int) -> int:
    candidate = max(start, 1)
    while candidate in used_ids:
        candidate += 1
    return candidate


def _coerce_passive_runtime_event(event: PassiveRuntimeEvent | dict[str, Any]) -> PassiveRuntimeEvent:
    if isinstance(event, PassiveRuntimeEvent):
        return event
    original = event
    data = asdict(event) if hasattr(event, "__dataclass_fields__") else dict(event or {})
    payload = dict(data.get("payload") or {})
    base_fields = {"event_id", "event_type", "type", "timestamp", "source", "task_id", "phase", "payload", "severity"}
    for key, value in data.items():
        if key not in base_fields:
            payload.setdefault(key, value)
    event_type = str(data.get("event_type") or data.get("type") or "")
    if not event_type:
        event_type = _infer_passive_runtime_event_type(original)
    return PassiveRuntimeEvent(
        event_id=int(data.get("event_id") or 0),
        event_type=event_type,
        timestamp=str(data.get("timestamp") or ""),
        source=str(data.get("source") or ""),
        task_id=str(data.get("task_id") or payload.get("task_id") or ""),
        phase=str(data.get("phase") or payload.get("phase") or ""),
        payload=payload,
        severity=str(data.get("severity") or "info"),
    )


def _infer_passive_runtime_event_type(event: Any) -> str:
    if isinstance(event, FileAccessEvent):
        return "file_access"
    if isinstance(event, VerificationEvent):
        return "verification"
    if isinstance(event, SubtaskStatusEvent):
        return "subtask_status"
    if isinstance(event, ProcessStatusEvent):
        return "process_status"
    if isinstance(event, DocumentValidationEvent):
        return "document_validation"
    if isinstance(event, RemoteSyncEvent):
        return "remote_sync"
    if isinstance(event, ReportClaimEvent):
        return "report_claim"
    return "unknown"


def _apply_passive_runtime_invariants(ledger: PassiveRuntimeLedger) -> PassiveRuntimeLedger:
    warnings = list(ledger.warnings)
    forbidden = list(ledger.forbidden_final_claims)
    partial_reasons = list(ledger.partial_reasons)
    status = ledger.overall_status
    blocked_reason = ledger.blocked_reason

    def add_warning(code: str, field_name: str, safe: str) -> None:
        warnings.append(
            {
                "code": code,
                "ledger_field": field_name,
                "event_id": str(ledger.latest_event_id),
                "offending_phrase": "",
                "safe_interpretation": safe,
            }
        )

    def add_forbidden(*claims: str) -> None:
        for claim in claims:
            if claim and claim not in forbidden:
                forbidden.append(claim)

    verification_status = ledger.verification_status
    if (
        ledger.latest_modification_event_id is not None
        and ledger.latest_verification_event_id is not None
        and ledger.latest_verification_event_id <= ledger.latest_modification_event_id
        and verification_status == "verified"
    ):
        verification_status = "stale"
        add_warning(
            "PASSIVE_RUNTIME_VERIFICATION_STALE",
            "verification_status",
            "Verification before the latest mutation cannot satisfy current state.",
        )
        add_forbidden("verified")

    if ledger.report_only and ledger.production_changed:
        status = "blocked"
        blocked_reason = blocked_reason or "report_only_production_change"
        add_warning(
            "PASSIVE_RUNTIME_REPORT_ONLY_PRODUCTION_CHANGE_INVALID",
            "report_only",
            "Report-only tasks cannot be represented as production-changing work.",
        )
        add_forbidden("production changed", "write performed")
    if ledger.dry_run and ledger.official_updated:
        status = "blocked"
        blocked_reason = blocked_reason or "dry_run_official_update"
        add_warning(
            "PASSIVE_RUNTIME_DRY_RUN_OFFICIAL_UPDATE_INVALID",
            "dry_run",
            "Dry-run tasks cannot update official or baseline state.",
        )
        add_forbidden("official updated", "baseline updated")

    effective_subtask_statuses: list[str] = []
    for subtask_id, subtask in ledger.subtasks.items():
        subtask_status = _coerce_status(subtask.get("status"))
        accepted_partial = bool(subtask.get("accepted_partial"))
        if subtask_status == "partial" and accepted_partial:
            effective_subtask_statuses.append("completed")
            continue
        effective_subtask_statuses.append(subtask_status)
        if subtask_status == "partial":
            partial_reasons = list(_append_unique(tuple(partial_reasons), f"{subtask_id}:partial"))
            add_forbidden("PASS", "completed", "all phases complete")
    if any(item == "blocked" for item in effective_subtask_statuses):
        status = "blocked"
        blocked_reason = blocked_reason or "subtask_blocked"
        add_forbidden("PASS", "completed", "all phases complete")
    elif any(item == "failed" for item in effective_subtask_statuses):
        status = "failed"
        add_forbidden("PASS", "completed", "all phases complete")
    elif any(item == "partial" for item in effective_subtask_statuses):
        status = "partial"
        add_forbidden("PASS", "completed", "all phases complete")
    elif effective_subtask_statuses and all(item == "completed" for item in effective_subtask_statuses):
        if status in {"pending", "running"}:
            status = "completed"
    elif any(item == "running" for item in effective_subtask_statuses):
        status = "running"
        add_forbidden("PASS", "completed")

    if status in {"pending", "running", "partial", "blocked", "failed"}:
        add_forbidden("PASS", "completed")
    if status in {"running", "partial"} and not ledger.next_safe_action:
        next_safe_action = "Inspect latest runtime events before reporting final status."
    else:
        next_safe_action = ledger.next_safe_action

    return replace(
        ledger,
        verification_status=verification_status,
        overall_status=status,
        blocked_reason=blocked_reason,
        partial_reasons=tuple(partial_reasons),
        warnings=tuple(warnings),
        forbidden_final_claims=tuple(forbidden),
        next_safe_action=next_safe_action,
    )


def _runtime_report_artifact_path(path: str) -> bool:
    normalized = (path or "").casefold()
    return normalized.startswith("outputs/") or "/outputs/" in normalized or "report" in normalized


def _runtime_claims_completion(text: str) -> bool:
    return bool(re.search(r"\b(pass|completed|done)\b", text or ""))


def _runtime_first_phrase(text: str, phrases: tuple[str, ...]) -> str:
    lowered = text or ""
    for phrase in phrases:
        if phrase in lowered:
            return phrase
    return phrases[0] if phrases else ""


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ConsistencyDecision",
    "DocumentValidationEvent",
    "DocumentValidationDecision",
    "DocumentValidationObserverPlan",
    "DocumentValidationPlan",
    "FileAccessEvent",
    "LongRunState",
    "LongRunObserverPlan",
    "PassiveLedgerDecision",
    "PassiveRuntimeEvent",
    "PassiveRuntimeLedger",
    "PermissionDecision",
    "PdfSignatureResult",
    "ProcessStatusEvent",
    "RemoteSyncDecision",
    "RemoteSyncEvent",
    "ReportClaimEvent",
    "SKILL_TRIGGER_RULES",
    "StatusLedger",
    "SubtaskStatusEvent",
    "TimeoutPolicy",
    "ValidationCommandPlan",
    "VerificationEvent",
    "VerificationDecision",
    "WatchdogDecision",
    "WatchdogPollPlan",
    "apply_passive_runtime_event",
    "build_passive_events_from_report_context",
    "build_passive_events_from_remote_sync_context",
    "build_passive_events_from_runner_context",
    "build_passive_events_from_subtask_context",
    "build_passive_events_from_validation_context",
    "build_passive_runtime_ledger",
    "build_document_validation_observer_plan",
    "build_document_validation_warning",
    "build_long_run_observer_plan",
    "build_pdf_validation_command_plan",
    "build_watchdog_poll_plan",
    "build_final_report_consistency_warnings",
    "check_final_report_consistency",
    "check_verification_freshness",
    "classify_action_permission",
    "classify_document_validation_trigger",
    "classify_document_validation_requirements",
    "classify_error_kind",
    "classify_long_run_event",
    "classify_long_run_trigger",
    "classify_ledger_completion_state",
    "classify_pdf_validation_result",
    "classify_remote_sync_safety",
    "classify_skill_triggers",
    "classify_watchdog_state",
    "coerce_passive_runtime_ledger",
    "compute_retry_signature",
    "extract_report_claim_events",
    "get_stage_timeout_policy",
    "initialize_passive_runtime_ledger",
    "initialize_status_ledger",
    "inspect_pdf_binary_signatures",
    "ledger_to_final_report_warnings",
    "merge_supplied_and_derived_passive_events",
    "safe_document_validation_summary",
    "safe_long_run_status_summary",
    "summarize_passive_runtime_ledger",
    "summarize_document_validation_plan",
    "summarize_document_validation_batch",
    "summarize_long_run_observer_plan",
    "update_long_run_ledger",
    "update_status_ledger",
]
