from __future__ import annotations

import json

from tools.passive_intelligence_guard import (
    build_document_validation_warning,
    build_final_report_consistency_warnings,
    check_final_report_consistency,
    check_verification_freshness,
    classify_action_permission,
    classify_document_validation_requirements,
    classify_error_kind,
    classify_long_run_event,
    classify_pdf_validation_result,
    classify_remote_sync_safety,
    classify_skill_triggers,
    classify_watchdog_state,
    compute_retry_signature,
    get_stage_timeout_policy,
    initialize_status_ledger,
    inspect_pdf_binary_signatures,
    safe_document_validation_summary,
    safe_long_run_status_summary,
    summarize_document_validation_batch,
    update_status_ledger,
)
from tools.task_engine_runner import task_engine_runner


def test_skill_not_loaded_self_built_triggers_document_validation_before_freeform_scripting():
    triggers = classify_skill_triggers("Please OCR this PDF, render pages, and check 文件完整性 before scripting.")

    assert "document_validation" in triggers
    assert triggers[0] == "document_validation"


def test_skill_triggers_return_all_matches_in_deterministic_order():
    triggers = classify_skill_triggers("Codex patch repo, git status, browser screenshot, Run DECISION StageRecord")

    assert triggers == ["codex_handoff", "git_safety", "browser_execution", "stage_duty"]


def test_task_engine_passive_guard_debug_is_opt_in_and_reports_triggers():
    default = json.loads(
        task_engine_runner(query="Run DECISION StageRecord and Codex patch", mode="DECISION", action="contract")
    )
    debug = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord and Codex patch",
            mode="DECISION",
            action="contract",
            passive_guard_debug=True,
        )
    )

    assert "passive_intelligence_guard" not in default
    assert debug["passive_intelligence_guard"]["skill_triggers"] == ["codex_handoff", "stage_duty"]
    assert debug["passive_intelligence_guard"]["production_behavior_change"] is False


def test_passive_guard_mode_default_off_no_output_change():
    implicit = json.loads(
        task_engine_runner(query="Run DECISION StageRecord and Codex patch", mode="DECISION", action="contract")
    )
    explicit_off = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord and Codex patch",
            mode="DECISION",
            action="contract",
            passive_guard_mode="off",
        )
    )

    assert implicit == explicit_off
    assert "passive_intelligence_guard" not in explicit_off


def test_warn_mode_reports_final_report_contradiction_without_blocking():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="warn",
            passive_guard_ledger={"task_id": "t1", "project_id": "p1", "task_status": "running"},
            passive_guard_report_text="PASS. Completed.",
        )
    )

    guard = result["passive_intelligence_guard"]
    assert result["status"] == "ok"
    assert guard["mode"] == "warn"
    assert guard["final_report_consistency"]["warning_only"] is True
    assert guard["final_report_consistency"]["consistent"] is False
    assert guard["final_report_consistency"]["warnings"][0]["code"] == "PASSIVE_FINAL_REPORT_COMPLETION_CONFLICT"
    assert guard["final_report_consistency"]["warnings"][0]["ledger_field"] == "task_status"


def test_block_destructive_rejects_force_push():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="block_destructive",
            passive_guard_action={"command": "git push --force origin main"},
        )
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "passive_intelligence_guard"
    assert result["blocked_reason"] == "git_force_push_blocked"
    assert result["passive_intelligence_guard"]["action_permission"]["decision"] == "blocked"


def test_block_destructive_rejects_report_only_non_report_write():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="block_destructive",
            passive_guard_action={
                "task": {"report_only": True},
                "operation": "write",
                "path": "src/runtime.py",
                "artifact_type": "code",
            },
        )
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "report_only_non_report_write_blocked"


def test_block_destructive_rejects_dry_run_official_update():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="block_destructive",
            passive_guard_action={
                "task": {"dry_run": True},
                "operation": "write",
                "description": "official baseline update",
            },
        )
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "dry_run_official_update_blocked"


def test_block_destructive_surfaces_non_destructive_permission_without_blocking():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="block_destructive",
            passive_guard_action={"command": "git push fork research-decision-validation"},
        )
    )

    guard = result["passive_intelligence_guard"]
    assert result["status"] == "ok"
    assert guard["action_permission"]["decision"] == "user_authorization_required"
    assert guard["action_permission"]["reason"] == "git_remote_or_history_change_requires_user_authorization"
    assert guard["would_block_destructive"] is False


def test_verification_stale_warning_surfaces_in_warn_mode():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="warn",
            passive_guard_ledger={
                "task_id": "t1",
                "project_id": "p1",
                "verification_status": "stale",
                "latest_modification_event_id": 2,
                "latest_verification_event_id": 1,
            },
            passive_guard_report_text="Verified and ready.",
        )
    )

    warnings = result["passive_intelligence_guard"]["final_report_consistency"]["warnings"]
    assert warnings[0]["code"] == "PASSIVE_FINAL_REPORT_VERIFICATION_CONFLICT"
    assert warnings[0]["ledger_field"] == "verification_status"


def test_ledger_partial_subtask_prevents_completed_claim_warning():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="warn",
            passive_guard_ledger={
                "task_id": "t1",
                "project_id": "p1",
                "task_status": "partial",
                "subtask_statuses": {"phase_5": "partial"},
            },
            passive_guard_report_text="All phases complete. PASS.",
        )
    )

    warning_codes = {
        warning["code"] for warning in result["passive_intelligence_guard"]["final_report_consistency"]["warnings"]
    }
    assert "PASSIVE_FINAL_REPORT_COMPLETION_CONFLICT" in warning_codes
    assert "PASSIVE_FINAL_REPORT_SUBTASK_CONFLICT" in warning_codes


def test_debug_mode_surfaces_status_ledger_without_enforcement():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord and git push fork",
            mode="DECISION",
            action="dry-run",
            passive_guard_mode="debug",
        )
    )

    guard = result["passive_intelligence_guard"]
    assert result["status"] == "ok"
    assert guard["mode"] == "debug"
    assert guard["debug_only"] is True
    assert guard["status_ledger"]["dry_run"] is True
    assert "git_safety" in guard["skill_triggers"]


def test_code_modification_requires_codex():
    decision = classify_action_permission({"operation": "patch", "domain": "code", "description": "bug fix"})

    assert decision.decision == "codex_required"
    assert decision.required_owner == "codex"


def test_git_push_no_confirm_requires_user_authorization():
    decision = classify_action_permission({"command": "git push origin main"})

    assert decision.decision == "user_authorization_required"
    assert decision.required_owner == "user"
    assert decision.blocked_by_default is True


def test_git_force_push_blocked():
    decision = classify_action_permission({"command": "git push --force origin main"})

    assert decision.decision == "blocked"
    assert decision.required_owner == "user"


def test_report_only_attempts_write_is_blocked():
    decision = classify_action_permission(
        {
            "task": {"report_only": True},
            "operation": "write",
            "path": "src/runtime.py",
            "artifact_type": "code",
        }
    )

    assert decision.decision == "blocked"
    assert decision.reason == "report_only_non_report_write_blocked"


def test_dry_run_updates_official_is_invalid_ledger():
    ledger = initialize_status_ledger({"task_id": "t1", "project_id": "p1", "dry_run": True})
    ledger = update_status_ledger(ledger, {"event_id": 1, "official_updated": True})

    assert ledger.task_status == "blocked"
    assert "dry_run_cannot_update_official_state" in ledger.invariant_violations
    assert "official_update" in ledger.forbidden_actions


def test_verification_turn_level_confusion_rejects_old_verification_after_new_write():
    ledger = initialize_status_ledger(
        {
            "task_id": "t1",
            "project_id": "p1",
            "verification_status": "verified",
            "latest_verification_event_id": 1,
        }
    )
    ledger = update_status_ledger(ledger, {"event_id": 2, "event_type": "file_written", "path": "tools/a.py"})

    decision = check_verification_freshness(ledger)
    consistency = check_final_report_consistency(ledger, "All changes verified.")

    assert ledger.verification_status == "stale"
    assert decision.verified is False
    assert "verified_claim_conflicts_with_ledger" in "|".join(consistency.violations)


def test_new_write_followed_by_new_verification_accepts_fresh_verification():
    ledger = initialize_status_ledger({"task_id": "t1", "project_id": "p1"})
    ledger = update_status_ledger(ledger, {"event_id": 1, "event_type": "file_written", "path": "tools/a.py"})
    ledger = update_status_ledger(ledger, {"event_id": 2, "event_type": "verification", "success": True})

    decision = check_verification_freshness(ledger)

    assert ledger.verification_status == "verified"
    assert decision.verified is True


def test_no_write_previous_verification_still_valid():
    ledger = initialize_status_ledger(
        {
            "task_id": "t1",
            "project_id": "p1",
            "verification_status": "verified",
            "latest_verification_event_id": 1,
        }
    )

    decision = check_verification_freshness(ledger)

    assert decision.verified is True


def test_codex_handoff_phase_incomplete_rejects_all_phases_complete_report():
    ledger = initialize_status_ledger(
        {
            "task_id": "t1",
            "project_id": "p1",
            "task_status": "partial",
            "subtask_statuses": {"phase_5": "partial"},
        }
    )

    decision = check_final_report_consistency(ledger, "All phases complete. PASS.")

    assert decision.consistent is False
    assert "all_phases_complete_claim_conflicts_with_subtasks" in decision.violations
    assert "completion_claim_conflicts_with_task_status:partial" in decision.violations


def test_local_tag_remote_push_confusion_rejects_pushed_claim():
    ledger = initialize_status_ledger(
        {
            "task_id": "t1",
            "project_id": "p1",
            "task_status": "completed",
            "local_tag": "v1.0.0",
            "remote_pushed": False,
            "remote_tag": "",
        }
    )

    decision = check_final_report_consistency(ledger, "Created local tag v1.0.0 and pushed it.")

    assert decision.consistent is False
    assert "pushed_claim_conflicts_with_remote_pushed_false" in decision.violations
    assert "remote_tag_claim_conflicts_with_missing_remote_tag" in decision.violations


def test_waiting_reported_as_pass_rejected():
    ledger = initialize_status_ledger({"task_id": "t1", "project_id": "p1", "task_status": "running"})

    decision = check_final_report_consistency(ledger, "PASS. Done.")

    assert decision.consistent is False
    assert "completion_claim_conflicts_with_task_status:running" in decision.violations


def test_retry_no_blocked_after_same_error_three_times():
    decision = classify_watchdog_state(
        {
            "process_status": "running",
            "retry_count_same_error": 3,
            "last_error_signature": "schema validation error",
            "current_error_signature": "schema validation error",
        }
    )

    assert decision.should_block is True
    assert decision.blocked_reason == "same_error_repeated_3_times"


def test_watchdog_waits_within_silence_budget_and_inspects_after_budget():
    wait = classify_watchdog_state(
        {"process_status": "running", "silence_seconds": 10, "expected_silence_budget": 20}
    )
    inspect = classify_watchdog_state(
        {"process_status": "running", "silence_seconds": 21, "expected_silence_budget": 20}
    )

    assert wait.should_wait is True
    assert wait.should_inspect is False
    assert inspect.should_wait is False
    assert inspect.should_inspect is True


def test_watchdog_blocks_auth_permission_path_errors_without_retry():
    decision = classify_watchdog_state(
        {
            "process_status": "running",
            "retry_count_same_error": 1,
            "current_error_signature": "permission denied: path not found",
        }
    )

    assert decision.should_block is True
    assert decision.should_retry is False


def test_watchdog_timeout_with_partial_output_is_partial_not_completed():
    decision = classify_watchdog_state({"process_status": "timeout", "partial_output": "some stdout"})

    assert decision.status == "partial"
    assert decision.should_inspect is True
    assert decision.should_block is False


def test_browser_gui_headless_requires_openclaw():
    decision = classify_action_permission(
        {"operation": "execute", "description": "Browser GUI task attempts headless Chrome screenshot"}
    )

    assert decision.decision == "openclaw_required"
    assert decision.required_owner == "openclaw"


def test_memory_delete_without_confirm_requires_user_authorization():
    decision = classify_action_permission({"memory_operation": "delete", "description": "memory delete old entry"})

    assert decision.decision == "user_authorization_required"
    assert decision.required_owner == "user"


def test_report_only_production_change_is_invalid_ledger():
    ledger = initialize_status_ledger({"task_id": "t1", "project_id": "p1", "report_only": True})
    ledger = update_status_ledger(ledger, {"event_id": 1, "production_changed": True})

    assert ledger.task_status == "blocked"
    assert "report_only_cannot_change_production" in ledger.invariant_violations


def test_dry_run_report_cannot_claim_official_update():
    ledger = initialize_status_ledger({"task_id": "t1", "project_id": "p1", "dry_run": True})

    decision = check_final_report_consistency(ledger, "Official baseline updated.")

    assert decision.consistent is False
    assert "official_update_claim_conflicts_with_ledger_false" in decision.violations
    assert "official_update_claim_conflicts_with_dry_run" in decision.violations


def test_structured_final_report_warnings_include_phrase_field_and_safe_interpretation():
    ledger = initialize_status_ledger({"task_id": "t1", "project_id": "p1", "task_status": "running"})

    warnings = build_final_report_consistency_warnings(ledger, "PASS. Done.")

    assert warnings[0]["code"] == "PASSIVE_FINAL_REPORT_COMPLETION_CONFLICT"
    assert warnings[0]["ledger_field"] == "task_status"
    assert warnings[0]["offending_phrase"] in {"PASS", "Done"}
    assert "do not report completion" in warnings[0]["safe_interpretation"]


def test_remote_sync_origin_read_not_write_regression():
    decision = classify_remote_sync_safety(
        {
            "origin_read_ok": True,
            "origin_write_proven": False,
            "fork_write_proven": True,
            "ls_remote_success": True,
        }
    )

    assert decision.decision == "user_authorization_required"
    assert decision.recommended_remote == "fork"
    assert decision.branch_push_allowed is False
    assert "origin_read_ok_does_not_prove_origin_write" in decision.warnings
    assert "ls_remote_success_is_read_access_only" in decision.warnings


def test_remote_sync_fork_write_requires_explicit_authorization_then_allows():
    unauthorized = classify_remote_sync_safety(
        {
            "origin_read_ok": True,
            "origin_write_proven": False,
            "fork_write_proven": True,
        }
    )
    authorized = classify_remote_sync_safety(
        {
            "origin_read_ok": True,
            "origin_write_proven": False,
            "fork_write_proven": True,
            "authorized_remote": "fork",
            "branch_push_verified": True,
        }
    )

    assert unauthorized.decision == "user_authorization_required"
    assert unauthorized.branch_push_allowed is False
    assert authorized.decision == "allowed"
    assert authorized.branch_push_allowed is True
    assert authorized.tag_push_allowed is True


def test_remote_sync_local_tag_does_not_imply_remote_tag_and_tag_waits_for_branch():
    local_only = classify_remote_sync_safety(
        {
            "authorized_remote": "fork",
            "fork_write_proven": True,
            "local_tag_exists": True,
            "remote_tag_exists": False,
        }
    )
    tag_too_early = classify_remote_sync_safety(
        {
            "authorized_remote": "fork",
            "fork_write_proven": True,
            "tag_push_requested": True,
            "branch_push_verified": False,
        }
    )

    assert "local_tag_does_not_imply_remote_tag" in local_only.warnings
    assert tag_too_early.decision == "blocked"
    assert tag_too_early.reason == "tag_push_before_branch_push_verified"


def test_github_ssh_443_endpoint_regression():
    bad = classify_remote_sync_safety({"ssh_endpoint": "github.com:443"})
    good = classify_remote_sync_safety(
        {
            "ssh_endpoint": "ssh.github.com:443",
            "authorized_remote": "fork",
            "fork_write_proven": True,
        }
    )

    assert bad.decision == "blocked"
    assert bad.reason == "github_com_443_is_not_github_ssh_endpoint"
    assert good.decision == "allowed"


def test_remote_sync_no_fallback_without_explicit_authorization():
    decision = classify_remote_sync_safety({"fallback_from": "origin", "fallback_to": "fork"})

    assert decision.decision == "blocked"
    assert decision.reason == "remote_fallback_without_explicit_authorization"


def test_git_remote_sync_terms_trigger_git_safety():
    triggers = classify_skill_triggers(
        "origin read works but fork write access, upstream, remote tag, ssh.github.com, github.com:443, known_hosts"
    )

    assert triggers == ["git_safety"]


def test_parser_pass_only_does_not_allow_fully_valid_claim():
    decision = classify_pdf_validation_result(
        {
            "file_path": "report.pdf",
            "parser_readable": True,
            "checks_run": ["parser_readable"],
            "required_checks": ["binary_signature", "parser_readable", "render_check"],
        }
    )
    warning = build_document_validation_warning(decision, "PDF fully valid.")

    assert decision.status == "unknown"
    assert decision.safe_claim_level == "parser_readable"
    assert "binary_signature" in decision.checks_missing
    assert warning["code"] == "PASSIVE_DOCUMENT_VALIDATION_OVERCLAIM"


def test_missing_eof_marker_blocks_complete_pdf_claim():
    decision = classify_pdf_validation_result(
        {
            "parser_readable": True,
            "binary_signature": {
                "has_pdf_header": True,
                "has_eof_marker": False,
                "eof_marker_near_tail": False,
                "file_size_bytes": 120,
            },
            "required_checks": ["binary_signature", "parser_readable"],
        }
    )

    assert decision.status == "fail"
    assert decision.blocked_reason == "pdf_binary_signature_failed"


def test_preview_required_but_not_checked_limits_claim_level():
    plan = classify_document_validation_requirements("report.pdf", "macOS Preview compatible PDF")
    decision = classify_pdf_validation_result(
        {
            "plan": plan,
            "binary_signature_ok": True,
            "parser_readable": True,
            "render_check_ok": True,
            "checks_run": ["binary_signature", "parser_readable", "render_check"],
        }
    )

    assert "macos_preview_compatibility" in decision.checks_missing
    assert decision.status == "unknown"
    assert decision.safe_claim_level == "rendered"


def test_batch_summary_cannot_claim_all_valid_with_unknowns():
    valid = classify_pdf_validation_result(
        {
            "binary_signature_ok": True,
            "parser_readable": True,
            "render_check_ok": True,
            "required_checks": ["binary_signature", "parser_readable", "render_check"],
        }
    )
    unknown = classify_pdf_validation_result(
        {"parser_readable": True, "required_checks": ["binary_signature", "parser_readable"]}
    )

    summary = summarize_document_validation_batch([valid, unknown])

    assert summary["files_checked"] == 2
    assert summary["files_unknown_due_missing_checks"] == 1
    assert summary["all_valid_claim_allowed"] is False


def test_target_app_missing_check_reports_unknown_not_pass():
    decision = classify_pdf_validation_result(
        {
            "binary_signature_ok": True,
            "parser_readable": True,
            "required_checks": ["binary_signature", "parser_readable", "target_app_compatibility"],
        }
    )

    assert decision.status == "unknown"
    assert "target_app_compatibility" in decision.checks_missing


def test_valid_all_required_checks_allows_safe_pass():
    decision = classify_pdf_validation_result(
        {
            "binary_signature_ok": True,
            "parser_readable": True,
            "render_check_ok": True,
            "required_checks": ["binary_signature", "parser_readable", "render_check"],
        }
    )

    assert decision.status == "pass"
    assert decision.safe_claim_level == "rendered"
    assert "passed the required checks" in safe_document_validation_summary(decision)


def test_overclaim_phrase_detects_zero_corrupted_when_checks_missing():
    decision = classify_pdf_validation_result(
        {"parser_readable": True, "required_checks": ["binary_signature", "parser_readable"]}
    )

    warning = build_document_validation_warning(decision, "Batch complete: 0 corrupted.")

    assert warning["code"] == "PASSIVE_DOCUMENT_VALIDATION_OVERCLAIM"
    assert warning["offending_phrase"] == "0 corrupted"


def test_per_file_failure_prevents_aggregate_pass():
    failed = classify_pdf_validation_result(
        {
            "binary_signature_ok": False,
            "parser_readable": True,
            "required_checks": ["binary_signature", "parser_readable"],
        }
    )
    valid = classify_pdf_validation_result(
        {
            "binary_signature_ok": True,
            "parser_readable": True,
            "required_checks": ["binary_signature", "parser_readable"],
        }
    )

    summary = summarize_document_validation_batch([valid, failed])

    assert summary["files_failed"] == 1
    assert summary["all_valid_claim_allowed"] is False


def test_inspect_pdf_binary_signatures_detects_tail_eof(tmp_path):
    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n")

    result = inspect_pdf_binary_signatures(str(pdf))

    assert result.has_pdf_header is True
    assert result.has_eof_marker is True
    assert result.eof_marker_near_tail is True
    assert result.suspicious_truncation is False


def test_running_within_silence_budget_waits():
    decision = classify_long_run_event(
        {"process_status": "running", "stage_name": "codex_handoff", "silence_seconds": 30}
    )

    assert decision.should_wait is True
    assert decision.status == "running"


def test_running_beyond_silence_budget_inspects():
    decision = classify_long_run_event(
        {"process_status": "running", "stage_name": "gpt_bridge", "silence_seconds": 61}
    )

    assert decision.should_inspect is True
    assert decision.blocked_reason == "silence_budget_exceeded"


def test_timeout_with_partial_output_is_partial_not_completed_phase2a():
    decision = classify_long_run_event({"process_status": "timeout", "partial_output_present": True})

    assert decision.status == "partial"
    assert "do not report completed" in decision.next_safe_action


def test_repeated_same_error_blocks_after_limit():
    signature = compute_retry_signature("schema validation error", exit_code=1)
    decision = classify_long_run_event(
        {
            "process_status": "failed",
            "retry_count_same_error": 3,
            "retry_count_total": 3,
            "current_error_signature": signature,
        }
    )

    assert decision.should_block is True
    assert decision.blocked_reason == "same_error_repeated_3_times"


def test_auth_error_blocks_not_retry_phase2a():
    assert classify_error_kind("auth token expired") == "auth"
    decision = classify_long_run_event({"process_status": "running", "current_error_signature": "auth token expired"})

    assert decision.should_block is True
    assert decision.should_retry is False


def test_permission_error_blocks_not_retry_phase2a():
    decision = classify_long_run_event({"process_status": "running", "current_error_signature": "permission denied"})

    assert decision.should_block is True
    assert decision.should_retry is False


def test_unknown_stage_uses_conservative_policy():
    policy = get_stage_timeout_policy("unknown_stage_name")
    decision = classify_long_run_event(
        {
            "process_status": "running",
            "stage_name": "unknown_stage_name",
            "elapsed_seconds": policy.soft_timeout + 1,
            "silence_seconds": 0,
        }
    )

    assert policy.stage_name == "generic_subprocess"
    assert decision.should_wait is True
    assert decision.should_block is False


def test_codex_incomplete_phase_not_completed():
    decision = classify_long_run_event(
        {
            "process_status": "completed",
            "stage_name": "codex_handoff",
            "incomplete_phases": ["phase_5"],
        }
    )

    assert decision.should_block is True
    assert decision.blocked_reason == "completed_claim_with_incomplete_phases"


def test_waiting_status_cannot_report_pass_phase2a():
    decision = classify_long_run_event({"process_status": "waiting", "silence_seconds": 0})

    assert decision.status == "waiting"
    assert "do not report PASS" in safe_long_run_status_summary(decision)


def test_per_stage_policy_not_universal_120s():
    codex = get_stage_timeout_policy("codex_handoff")
    batch = get_stage_timeout_policy("batch_download")

    assert codex.expected_silence_budget != batch.expected_silence_budget
    assert codex.hard_timeout != batch.hard_timeout


def test_remote_ahead_diverged_blocks_not_force_push():
    decision = classify_long_run_event(
        {"process_status": "failed", "current_error_signature": "remote ahead and diverged; fetch first"}
    )

    assert decision.should_block is True
    assert decision.blocked_reason == "remote_diverged_error_requires_owner_action"


def test_warn_mode_reports_document_overclaim_without_blocking():
    result = json.loads(
        task_engine_runner(
            query="Validate PDF render Preview before claiming 0 corrupted.",
            mode="DECISION",
            action="contract",
            passive_guard_mode="warn",
            passive_guard_document_validation={
                "file_path": "report.pdf",
                "parser_readable": True,
                "required_checks": ["binary_signature", "parser_readable", "render_check"],
            },
            passive_guard_report_text="All valid, 0 corrupted.",
        )
    )

    guard = result["passive_intelligence_guard"]
    assert result["status"] == "ok"
    assert "document_validation" in guard["skill_triggers"]
    assert guard["document_validation"]["warning"]["code"] == "PASSIVE_DOCUMENT_VALIDATION_OVERCLAIM"


def test_warn_mode_reports_long_run_watchdog_without_blocking():
    result = json.loads(
        task_engine_runner(
            query="GPT Bridge subprocess is silent and waiting.",
            mode="DECISION",
            action="contract",
            passive_guard_mode="warn",
            passive_guard_watchdog_state={
                "process_status": "running",
                "stage_name": "gpt_bridge",
                "silence_seconds": 120,
            },
        )
    )

    watchdog = result["passive_intelligence_guard"]["long_run_watchdog"]
    assert result["status"] == "ok"
    assert watchdog["decision"]["should_inspect"] is True
    assert watchdog["warning_only"] is True
