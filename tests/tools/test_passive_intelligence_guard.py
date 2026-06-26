from __future__ import annotations

import json

from tools.passive_intelligence_guard import (
    build_document_validation_observer_plan,
    build_document_validation_warning,
    build_final_report_consistency_warnings,
    build_long_run_observer_plan,
    build_passive_runtime_ledger,
    build_pdf_validation_command_plan,
    build_watchdog_poll_plan,
    check_final_report_consistency,
    check_verification_freshness,
    classify_action_permission,
    classify_document_validation_requirements,
    classify_document_validation_trigger,
    classify_error_kind,
    classify_ledger_completion_state,
    classify_long_run_event,
    classify_long_run_trigger,
    classify_pdf_validation_result,
    classify_remote_sync_safety,
    classify_skill_triggers,
    classify_watchdog_state,
    compute_retry_signature,
    get_stage_timeout_policy,
    initialize_passive_runtime_ledger,
    initialize_status_ledger,
    inspect_pdf_binary_signatures,
    ledger_to_final_report_warnings,
    safe_document_validation_summary,
    safe_long_run_status_summary,
    summarize_document_validation_plan,
    summarize_document_validation_batch,
    summarize_long_run_observer_plan,
    summarize_passive_runtime_ledger,
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


def test_document_task_builds_plan_without_executing_commands():
    plan = build_document_validation_observer_plan("Validate report.pdf render before saying it is valid.")

    assert plan.triggered is True
    assert plan.files == ("report.pdf",)
    assert plan.command_plan
    assert all(command.executes_by_default is False for command in plan.command_plan)
    assert all(command.destructive is False for command in plan.command_plan)
    assert "run only explicitly authorized validation checks" in plan.next_safe_action.casefold()


def test_preview_intended_use_requires_target_app_check():
    plan = build_document_validation_observer_plan(
        "Check report.pdf works in macOS Preview.",
        intended_use="macOS Preview compatibility",
    )

    assert "macos_preview_compatibility" in plan.required_checks
    assert "qlmanage_preview" in plan.platform_specific_checks
    assert any(command.platform == "macos" for command in plan.command_plan)


def test_verify_all_pdfs_adds_per_file_ledger_requirement():
    plan = build_document_validation_observer_plan("Verify all PDFs a.pdf b.pdf and report all valid.")

    assert plan.files == ("a.pdf", "b.pdf")
    assert "per_file_validation_ledger" in plan.required_checks
    assert "all files valid" in plan.prohibited_claims


def test_zero_corrupted_claim_is_prohibited_without_full_checks():
    plan = build_document_validation_observer_plan("Verify PDFs and report 0 corrupted.")

    assert "0 corrupted" in plan.prohibited_claims
    assert plan.warning_if_checks_missing == "Missing required checks must be reported as unknown/warning, not pass."


def test_parser_only_safe_claim_ceiling_is_parser_readable():
    plan = build_document_validation_observer_plan("PyMuPDF parser passed for report.pdf.")

    assert plan.safe_claim_ceiling == "parser_readable"


def test_unknown_files_requires_inventory_before_validation():
    plan = build_document_validation_observer_plan("Verify all PDFs are not corrupted.")

    assert plan.triggered is True
    assert plan.files == ()
    assert "file_inventory" in plan.required_checks
    assert "file inventory is required" in summarize_document_validation_plan(plan).casefold()


def test_pdf_validation_command_plan_is_non_executing_preview_only():
    command_plan = build_pdf_validation_command_plan("report.pdf", platform="macos", target_app="Preview")

    assert command_plan
    assert all(command.executes_by_default is False for command in command_plan)
    assert all(command.destructive is False for command in command_plan)
    assert any("qlmanage" in command.command_preview for command in command_plan)


def test_document_validation_trigger_detects_overclaim_terms():
    assert classify_document_validation_trigger("Need 0 corrupted PDFs and Preview validation") is True


def test_codex_task_triggers_watchdog_plan():
    plan = build_long_run_observer_plan("Codex handoff is running silently.")

    assert plan.triggered is True
    assert plan.owner_tool == "codex_handoff"
    assert plan.stage_name == "codex_handoff"


def test_timeout_task_triggers_watchdog_plan():
    assert classify_long_run_trigger("Process timeout with no output") is True
    plan = build_long_run_observer_plan("Process timeout with no output")

    assert plan.triggered is True
    assert "timeout_mentioned" in plan.trigger_reasons


def test_watchdog_plan_requires_phase_last_output_retry_fields():
    plan = build_long_run_observer_plan("GPT Bridge subprocess no output", owner_tool="gpt_bridge")
    required = set(plan.poll_plan.required_status_fields)

    assert {"phase", "last_output_at", "retry_count", "error_signature", "next_safe_action"} <= required
    assert tuple(plan.heartbeat_fields) == plan.poll_plan.required_status_fields


def test_running_waiting_partial_cannot_claim_pass():
    plan = build_long_run_observer_plan("Subprocess is waiting and partial output exists.")

    assert "PASS" in plan.prohibited_claims
    assert "serialize_running_as_pass" in plan.poll_plan.blocked_actions


def test_owner_tool_stage_uses_timeout_policy():
    plan = build_long_run_observer_plan(
        "Decision external calibration is silent.",
        owner_tool="agy",
        stage_name="decision_external_calibration",
    )

    assert plan.timeout_policy.stage_name == "decision_external_calibration"
    assert plan.poll_plan.hard_timeout == get_stage_timeout_policy("decision_external_calibration", "agy").hard_timeout


def test_unknown_stage_uses_conservative_observer_policy():
    plan = build_long_run_observer_plan("Unknown subprocess is running.", stage_name="unknown_stage")

    assert plan.timeout_policy.stage_name == "generic_subprocess"
    assert plan.poll_plan.hard_timeout == get_stage_timeout_policy("generic_subprocess").hard_timeout


def test_watchdog_poll_plan_has_safe_and_blocked_actions():
    poll_plan = build_watchdog_poll_plan(get_stage_timeout_policy("codex_handoff"))

    assert "wait" in poll_plan.safe_actions
    assert "blind_retry" in poll_plan.blocked_actions
    assert "force_push" in poll_plan.blocked_actions


def test_long_run_observer_summary_is_warning_only_language():
    plan = build_long_run_observer_plan("AGY timeout with no output")

    assert "warning-only" in summarize_long_run_observer_plan(plan)


def test_default_mode_no_observer_metadata():
    default = json.loads(
        task_engine_runner(
            query="Validate report.pdf and monitor Codex timeout.",
            mode="DECISION",
            action="contract",
        )
    )

    assert "passive_intelligence_guard" not in default


def test_debug_mode_includes_observer_plans():
    result = json.loads(
        task_engine_runner(
            query="Validate report.pdf in Preview and monitor Codex timeout.",
            mode="DECISION",
            action="contract",
            passive_guard_mode="debug",
        )
    )

    observers = result["passive_intelligence_guard"]["observer_plans"]
    assert "document_validation" in observers
    assert "long_run_watchdog" in observers
    assert observers["document_validation"]["plan"]["command_plan"][0]["executes_by_default"] is False


def test_warn_mode_surfaces_observer_warnings_without_blocking():
    result = json.loads(
        task_engine_runner(
            query="Verify all PDFs and report 0 corrupted while Codex is waiting with no output but PASS.",
            mode="DECISION",
            action="contract",
            passive_guard_mode="warn",
        )
    )

    guard = result["passive_intelligence_guard"]
    assert result["status"] == "ok"
    assert guard["observer_plans"]["document_validation"]["warnings"]
    assert guard["observer_plans"]["long_run_watchdog"]["warnings"]


def test_block_destructive_mode_still_blocks_force_push_only_without_observer_expansion():
    result = json.loads(
        task_engine_runner(
            query="Validate report.pdf and monitor Codex timeout.",
            mode="DECISION",
            action="contract",
            passive_guard_mode="block_destructive",
            passive_guard_action={"command": "git push --force origin main"},
        )
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "git_force_push_blocked"
    assert "observer_plans" not in result["passive_intelligence_guard"]


def test_no_events_ledger_is_pending_not_pass():
    ledger = initialize_passive_runtime_ledger("task-1", "debug")
    decision = classify_ledger_completion_state(ledger)

    assert ledger.overall_status == "pending"
    assert decision.can_report_pass is False
    assert summarize_passive_runtime_ledger(ledger)["events_seen"] == 0


def test_file_write_makes_prior_verification_stale():
    ledger = build_passive_runtime_ledger(
        [
            {"event_id": 1, "event_type": "verification", "result": "pass"},
            {"event_id": 2, "event_type": "file_access", "operation": "write", "path": "tools/example.py"},
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.verification_status == "stale"
    assert ledger.latest_modification_event_id == 2


def test_verification_after_write_restores_verified_state():
    ledger = build_passive_runtime_ledger(
        [
            {"event_id": 1, "event_type": "file_access", "operation": "write", "path": "tools/example.py"},
            {
                "event_id": 2,
                "event_type": "verification",
                "result": "pass",
                "verifies_after_event_id": 1,
            },
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.verification_status == "verified"
    assert ledger.latest_verification_event_id == 2


def test_partial_subtask_prevents_completed():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "subtask_status",
                "subtask_id": "phase_5",
                "status": "partial",
            },
            {"event_id": 2, "event_type": "subtask_status", "subtask_id": "phase_6", "status": "completed"},
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.overall_status == "partial"
    assert classify_ledger_completion_state(ledger).can_report_completed is False


def test_accepted_partial_allows_completed_with_warning():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "subtask_status",
                "subtask_id": "phase_5",
                "status": "partial",
                "accepted_partial": True,
            }
        ],
        task_id="task-1",
        mode="warn",
    )

    decision = classify_ledger_completion_state(ledger)
    assert ledger.overall_status == "completed"
    assert decision.can_report_completed is True
    assert any(item["code"] == "PASSIVE_RUNTIME_ACCEPTED_PARTIAL" for item in ledger.warnings)


def test_blocked_subtask_prevents_pass():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "subtask_status",
                "subtask_id": "phase_7",
                "status": "blocked",
                "reason": "auth_missing",
            }
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.overall_status == "blocked"
    assert classify_ledger_completion_state(ledger).can_report_pass is False


def test_report_only_production_change_invalid():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "file_access",
                "operation": "write",
                "path": "tools/source.py",
                "report_only": True,
            }
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.report_only is True
    assert ledger.production_changed is True
    assert ledger.overall_status == "blocked"


def test_dry_run_official_update_invalid():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "remote_sync",
                "operation": "official_update",
                "dry_run": True,
                "official_updated": True,
            }
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.dry_run is True
    assert ledger.official_updated is True
    assert ledger.overall_status == "blocked"


def test_ls_remote_read_event_does_not_set_write_success():
    ledger = build_passive_runtime_ledger(
        [{"event_id": 1, "event_type": "remote_sync", "operation": "ls_remote", "read_access": True}],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.remote_pushed is False
    assert any(item["code"] == "PASSIVE_RUNTIME_READ_ACCESS_IS_NOT_WRITE_ACCESS" for item in ledger.warnings)


def test_branch_push_without_verify_not_synced():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "remote_sync",
                "operation": "branch_push",
                "write_success": True,
            }
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.remote_pushed is False
    assert "remote synced" in ledger.forbidden_final_claims


def test_branch_push_with_verify_sets_remote_pushed():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "remote_sync",
                "operation": "branch_push",
                "write_success": True,
                "verified": True,
            }
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.remote_pushed is True
    assert ledger.remote_write_verified is True


def test_local_tag_without_remote_tag_not_synced():
    ledger = build_passive_runtime_ledger(
        [{"event_id": 1, "event_type": "remote_sync", "operation": "local_tag"}],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.remote_tag_pushed is False
    assert "remote tag synced" in ledger.forbidden_final_claims


def test_tag_push_without_verify_not_synced():
    ledger = build_passive_runtime_ledger(
        [{"event_id": 1, "event_type": "remote_sync", "operation": "tag_push", "tag_pushed": True}],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.remote_tag_pushed is False
    assert any(item["code"] == "PASSIVE_RUNTIME_REMOTE_TAG_UNVERIFIED" for item in ledger.warnings)


def test_tag_push_with_verify_sets_remote_tag_pushed():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "remote_sync",
                "operation": "tag_push",
                "tag_pushed": True,
                "tag_verified": True,
            }
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.remote_tag_pushed is True
    assert ledger.remote_tag_verified is True


def test_parser_readable_document_event_limits_claim_level():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "document_validation",
                "file_path": "report.pdf",
                "parser_readable": True,
                "checks_run": ["parser_readable"],
            }
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.document_claim_levels["report.pdf"] == "parser_readable"
    assert "PDF fully valid" in ledger.forbidden_final_claims


def test_target_app_missing_check_blocks_target_app_claim():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "document_validation",
                "file_path": "report.pdf",
                "parser_readable": True,
                "required_checks": ["parser_readable", "target_app_compatibility"],
                "checks_run": ["parser_readable"],
            }
        ],
        task_id="task-1",
        mode="warn",
    )
    warnings = ledger_to_final_report_warnings(ledger, "Preview compatible.")

    assert ledger.document_claim_levels["report.pdf"] != "target_app_validated"
    assert any(item["code"] == "PASSIVE_RUNTIME_TARGET_APP_CLAIM_CONFLICT" for item in warnings)


def test_batch_unknown_file_blocks_all_valid_claim():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "document_validation",
                "file_path": "a.pdf",
                "parser_readable": True,
                "binary_signature_ok": True,
                "render_check_ok": True,
                "target_app_compatible": True,
                "required_checks": ["parser_readable"],
            },
            {"event_id": 2, "event_type": "document_validation", "file_path": "b.pdf"},
        ],
        task_id="task-1",
        mode="warn",
    )
    warnings = ledger_to_final_report_warnings(ledger, "All valid, 0 corrupted.")

    assert any(item["code"] == "PASSIVE_RUNTIME_DOCUMENT_AGGREGATE_CONFLICT" for item in warnings)


def test_running_process_cannot_report_pass():
    ledger = build_passive_runtime_ledger(
        [{"event_id": 1, "event_type": "process_status", "process_status": "running"}],
        task_id="task-1",
        mode="warn",
    )
    warnings = ledger_to_final_report_warnings(ledger, "PASS.")

    assert ledger.overall_status == "running"
    assert any(item["code"] == "PASSIVE_RUNTIME_COMPLETION_CONFLICT" for item in warnings)


def test_timeout_partial_output_sets_partial():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "process_status",
                "process_status": "timeout",
                "partial_output_present": True,
            }
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.overall_status == "partial"
    assert classify_ledger_completion_state(ledger).can_report_completed is False


def test_repeated_permission_error_sets_blocked():
    ledger = build_passive_runtime_ledger(
        [
            {
                "event_id": 1,
                "event_type": "process_status",
                "process_status": "running",
                "current_error_signature": "permission denied",
                "retry_count_same_error": 3,
            }
        ],
        task_id="task-1",
        mode="warn",
    )

    assert ledger.overall_status == "blocked"
    assert "permission" in ledger.blocked_reason


def test_default_mode_no_ledger_metadata():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_runtime_events=[
                {"event_id": 1, "event_type": "file_access", "operation": "write", "path": "tools/source.py"}
            ],
        )
    )

    assert "passive_intelligence_guard" not in result


def test_debug_mode_includes_ledger_metadata_when_events_supplied():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="debug",
            passive_runtime_events=[
                {"event_id": 1, "event_type": "file_access", "operation": "write", "path": "tools/source.py"}
            ],
        )
    )

    runtime = result["passive_intelligence_guard"]["runtime_ledger"]
    assert runtime["summary"]["events_seen"] == 1
    assert runtime["ledger"]["verification_status"] == "required"


def test_warn_mode_includes_ledger_warnings_without_blocking():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="warn",
            passive_guard_report_text="PASS.",
            passive_runtime_events=[{"event_id": 1, "event_type": "process_status", "process_status": "running"}],
        )
    )

    runtime = result["passive_intelligence_guard"]["runtime_ledger"]
    assert result["status"] == "ok"
    assert runtime["warning_only"] is True
    assert any(item["code"] == "PASSIVE_RUNTIME_COMPLETION_CONFLICT" for item in runtime["warnings"])


def test_block_destructive_mode_still_only_blocks_destructive_rules():
    warning_only = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="block_destructive",
            passive_runtime_events=[{"event_id": 1, "event_type": "process_status", "process_status": "running"}],
        )
    )
    blocked = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="block_destructive",
            passive_guard_action={"command": "git push --force origin main"},
            passive_runtime_events=[{"event_id": 1, "event_type": "process_status", "process_status": "running"}],
        )
    )

    assert warning_only["status"] == "ok"
    assert warning_only["passive_intelligence_guard"]["runtime_ledger"]["blocks_expanded"] is False
    assert blocked["status"] == "blocked"
    assert blocked["blocked_reason"] == "git_force_push_blocked"
