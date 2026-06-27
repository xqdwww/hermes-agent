from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools.long_run_process_observer import (
    build_long_run_dashboard_summary,
    build_long_run_observer_policy,
    classify_long_run_observer_snapshot,
    collect_long_run_observer_snapshot,
    compute_error_signature_from_tail,
    maybe_probe_process_safely,
    read_log_tail_safely,
    reject_unsafe_observer_action,
)
from tools.task_engine_runner import task_engine_runner


def test_default_policy_does_not_observe(tmp_path):
    log_path = tmp_path / "run.log"
    log_path.write_text("still running\n", encoding="utf-8")
    policy = build_long_run_observer_policy()

    snapshot = collect_long_run_observer_snapshot(policy, pid=123, log_path=str(log_path))

    assert snapshot.process_snapshot.probe_attempted is False
    assert snapshot.log_snapshot.read_attempted is False
    assert snapshot.process_status == "unknown"


def test_missing_pid_and_log_returns_status_needed():
    policy = build_long_run_observer_policy(observe=True)
    snapshot = collect_long_run_observer_snapshot(policy)

    decision = classify_long_run_observer_snapshot(snapshot, policy)

    assert decision.status == "unknown"
    assert decision.should_inspect is True
    assert "LONG_RUN_OBSERVER_STATUS_NEEDED" in decision.warning_codes


def test_explicit_log_tail_read_is_bounded(tmp_path):
    log_path = tmp_path / "run.log"
    log_path.write_text("a" * 200, encoding="utf-8")

    snapshot = read_log_tail_safely(str(log_path), 32, allowed_roots=(str(tmp_path),))

    assert snapshot.read_attempted is True
    assert snapshot.bytes_read == 32
    assert len(snapshot.tail_excerpt) == 32


def test_large_log_tail_is_truncated(tmp_path):
    log_path = tmp_path / "large.log"
    log_path.write_text("prefix\n" + ("x" * 9000), encoding="utf-8")

    snapshot = read_log_tail_safely(str(log_path), 128, allowed_roots=(str(tmp_path),))

    assert snapshot.truncated is True
    assert snapshot.bytes_read == 128


def test_log_error_signature_is_stable():
    first = compute_error_signature_from_tail("line\nPermission denied for /tmp/a\n")
    second = compute_error_signature_from_tail("other\nPermission denied for /tmp/a\n")

    assert first == second
    assert first.startswith("permission:")


def test_process_probe_requires_explicit_pid():
    policy = build_long_run_observer_policy(observe=True, allow_process_probe=True)

    snapshot = maybe_probe_process_safely(None, policy)

    assert snapshot.probe_attempted is False
    assert snapshot.status_reason == "pid_not_supplied"


def test_process_inaccessible_returns_unknown_not_failed(monkeypatch):
    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="no access")

    monkeypatch.setattr("tools.long_run_process_observer.subprocess.run", fake_run)
    policy = build_long_run_observer_policy(observe=True, allow_process_probe=True)

    snapshot = maybe_probe_process_safely(999999, policy)

    assert snapshot.probe_attempted is True
    assert snapshot.process_status == "unknown"
    assert snapshot.status_reason == "process_not_found_or_inaccessible"


def test_running_no_fresh_output_warns_inspect_not_fail():
    policy = build_long_run_observer_policy(observe=True, expected_silence_budget=10)
    snapshot = collect_long_run_observer_snapshot(
        policy,
        supplied_state={"process_status": "running", "silence_seconds": 90, "elapsed_seconds": 120},
    )

    decision = classify_long_run_observer_snapshot(snapshot, policy)

    assert decision.status == "running"
    assert decision.should_inspect is True
    assert decision.should_block is False
    assert "LONG_RUN_OBSERVER_SILENCE_BUDGET_EXCEEDED" in decision.warning_codes


def test_timeout_with_partial_output_not_completed():
    policy = build_long_run_observer_policy(observe=True)
    snapshot = collect_long_run_observer_snapshot(
        policy,
        supplied_state={"process_status": "timeout", "partial_output_present": True},
    )

    decision = classify_long_run_observer_snapshot(snapshot, policy)

    assert decision.status == "partial"
    assert "PASS" in decision.prohibited_claims


def test_repeated_same_error_blocks():
    policy = build_long_run_observer_policy(observe=True)
    snapshot = collect_long_run_observer_snapshot(
        policy,
        supplied_state={
            "process_status": "running",
            "current_error_signature": "same failure",
            "last_error_signature": "same failure",
            "retry_count_same_error": 3,
        },
    )

    decision = classify_long_run_observer_snapshot(snapshot, policy)

    assert decision.should_block is True
    assert decision.status == "blocked"


def test_auth_error_blocks():
    policy = build_long_run_observer_policy(observe=True)
    snapshot = collect_long_run_observer_snapshot(
        policy,
        supplied_state={"process_status": "running", "current_error_signature": "auth token expired"},
    )

    decision = classify_long_run_observer_snapshot(snapshot, policy)

    assert decision.should_block is True
    assert "LONG_RUN_OBSERVER_OWNER_ACTION_REQUIRED" in decision.warning_codes


def test_permission_error_blocks():
    policy = build_long_run_observer_policy(observe=True)
    snapshot = collect_long_run_observer_snapshot(
        policy,
        supplied_state={"process_status": "running", "current_error_signature": "permission denied"},
    )

    decision = classify_long_run_observer_snapshot(snapshot, policy)

    assert decision.should_block is True


def test_waiting_running_cannot_claim_pass():
    policy = build_long_run_observer_policy(observe=True)
    snapshot = collect_long_run_observer_snapshot(policy, supplied_state={"process_status": "waiting"})

    decision = classify_long_run_observer_snapshot(snapshot, policy)

    assert "PASS" in decision.prohibited_claims
    assert "completed" in decision.prohibited_claims


def test_dashboard_includes_known_unknown_next_action():
    policy = build_long_run_observer_policy(observe=True)
    snapshot = collect_long_run_observer_snapshot(
        policy,
        supplied_state={"task_id": "t1", "process_status": "running", "phase": "phase_a"},
    )
    decision = classify_long_run_observer_snapshot(snapshot, policy)

    dashboard = build_long_run_dashboard_summary(snapshot, decision)

    assert dashboard["task_id"] == "t1"
    assert "phase" in dashboard["known_fields"]
    assert "log_path" in dashboard["unknown_fields"]
    assert dashboard["safe_next_action"]


def test_no_process_control_actions_allowed():
    assert reject_unsafe_observer_action("retry") == "process_control_not_allowed"
    assert reject_unsafe_observer_action("terminate") == "process_control_not_allowed"
    assert reject_unsafe_observer_action("inspect") is None


def test_no_shell_true_used(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_run(argv, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="123 S 00:01 0.0 1024 python worker\n", stderr="")

    monkeypatch.setattr("tools.long_run_process_observer.subprocess.run", fake_run)
    policy = build_long_run_observer_policy(observe=True, allow_process_probe=True)

    snapshot = maybe_probe_process_safely(123, policy)

    assert snapshot.process_status == "running"
    assert calls
    assert calls[0].get("shell") in {None, False}


def test_debug_mode_exposes_observer_dashboard(tmp_path):
    log_path = tmp_path / "run.log"
    log_path.write_text("working\n", encoding="utf-8")

    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord with Codex timeout monitoring",
            mode="DECISION",
            action="contract",
            passive_guard_mode="debug",
            passive_context={
                "long_run_process_observer": {
                    "observe": True,
                    "allow_log_read": True,
                    "log_path": str(log_path),
                    "allowed_log_roots": [str(tmp_path)],
                    "supplied_state": {"process_status": "running", "phase": "phase_a"},
                }
            },
        )
    )

    observer = result["passive_intelligence_guard"]["long_run_process_observer"]
    assert observer["dashboard"]["status"] == "running"
    assert observer["warning_only"] is True
    assert observer["process_control_enabled"] is False


def test_warn_mode_exposes_observer_warning():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord with Codex stuck timeout monitoring",
            mode="DECISION",
            action="contract",
            passive_guard_mode="warn",
            passive_context={
                "long_run_process_observer": {
                    "observe": True,
                    "supplied_state": {
                        "process_status": "timeout",
                        "partial_output_present": True,
                    },
                }
            },
        )
    )

    decision = result["passive_intelligence_guard"]["long_run_process_observer"]["decision"]
    assert decision["status"] == "partial"
    assert "LONG_RUN_OBSERVER_PARTIAL_OUTPUT" in decision["warning_codes"]
    assert result["status"] == "ok"


def test_default_task_engine_runner_output_unchanged(tmp_path):
    log_path = tmp_path / "run.log"
    log_path.write_text("working\n", encoding="utf-8")

    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_context={
                "long_run_process_observer": {
                    "observe": True,
                    "allow_log_read": True,
                    "log_path": str(log_path),
                    "allowed_log_roots": [str(tmp_path)],
                }
            },
        )
    )

    assert "passive_intelligence_guard" not in result


def test_block_destructive_not_expanded_by_observer_missing_status():
    result = json.loads(
        task_engine_runner(
            query="Run DECISION StageRecord",
            mode="DECISION",
            action="contract",
            passive_guard_mode="block_destructive",
            passive_context={"long_run_process_observer": {"observe": True}},
        )
    )

    assert result["status"] == "ok"
    guard = result["passive_intelligence_guard"]
    assert "long_run_process_observer" not in guard
