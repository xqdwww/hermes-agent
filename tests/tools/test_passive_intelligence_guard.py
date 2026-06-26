from __future__ import annotations

import json

from tools.passive_intelligence_guard import (
    check_final_report_consistency,
    check_verification_freshness,
    classify_action_permission,
    classify_skill_triggers,
    classify_watchdog_state,
    initialize_status_ledger,
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
