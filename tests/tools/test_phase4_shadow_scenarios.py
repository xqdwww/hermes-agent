from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.long_run_process_observer import (
    build_long_run_observer_policy,
    classify_long_run_observer_snapshot,
    collect_long_run_observer_snapshot,
    read_log_tail_safely,
)
from tools.pdf_validation_adapter import (
    PdfValidationCommand,
    PdfValidationExecutionPolicy,
    build_pdf_validation_adapter_plan,
    reject_unsafe_pdf_validation_command,
    run_pdf_validation_adapter,
)
from tools.passive_intelligence_guard import inspect_pdf_binary_signatures
from tools.task_engine_runner import task_engine_runner


def _tiny_pdf(path: Path, *, eof: bool = True) -> Path:
    suffix = b"\n%%EOF\n" if eof else b"\n"
    path.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<<>>" + suffix)
    return path


def _runner_result(
    *,
    query: str = "Run DECISION StageRecord",
    mode: str = "DECISION",
    action: str = "contract",
    guard_mode: str = "warn",
    passive_context: dict | None = None,
    passive_guard_report_text: str | None = None,
    passive_guard_document_validation: dict | None = None,
    passive_guard_action: dict | None = None,
) -> dict:
    return json.loads(
        task_engine_runner(
            query=query,
            mode=mode,
            action=action,
            passive_guard_mode=guard_mode,
            passive_context=passive_context,
            passive_guard_report_text=passive_guard_report_text,
            passive_guard_document_validation=passive_guard_document_validation,
            passive_guard_action=passive_guard_action,
        )
    )


def _runtime_warnings(result: dict) -> list[dict]:
    return result.get("passive_intelligence_guard", {}).get("runtime_ledger", {}).get("warnings", [])


def _runtime_warning_codes(result: dict) -> set[str]:
    return {item.get("code", "") for item in _runtime_warnings(result)}


def _hard_block_codes(result: dict) -> set[str]:
    decision = result.get("passive_intelligence_guard", {}).get("runtime_ledger", {}).get("hard_block_decision", {})
    return {item.get("code", "") for item in decision.get("hard_blocks", [])}


def test_shadow_synthetic_valid_minimal_pdf_plan_only(tmp_path):
    pdf = _tiny_pdf(tmp_path / "valid.pdf")
    context = {"validation": {"pdf_validation": {"file_path": str(pdf), "target_app": "Preview"}}}

    off = _runner_result(query="Validate the supplied PDF.", guard_mode="off", passive_context=context)
    debug = _runner_result(query="Validate the supplied PDF.", guard_mode="debug", passive_context=context)
    warn = _runner_result(query="Validate the supplied PDF.", guard_mode="warn", passive_context=context)

    assert "passive_intelligence_guard" not in off
    assert debug["passive_intelligence_guard"]["pdf_validation_adapter"]["executes_native_tools"] is False
    assert warn["passive_intelligence_guard"]["pdf_validation_adapter"]["warnings"][0]["code"] == "PASSIVE_PDF_NATIVE_VALIDATION_NOT_EXECUTED"


def test_shadow_parser_only_claims_preview_compatibility_warns_not_blocks():
    context = {
        "validation": {
            "documents": [
                {
                    "file_path": "report.pdf",
                    "checks_run": ["parser_readable"],
                    "checks_missing": ["target_app_compatibility"],
                    "safe_claim_level": "parser_readable",
                    "status": "warning",
                }
            ]
        }
    }

    warn = _runner_result(
        query="Validate this PDF for Preview.",
        guard_mode="warn",
        passive_context=context,
        passive_guard_report_text="The PDF is Preview compatible.",
    )
    block = _runner_result(
        query="Validate this PDF for Preview.",
        guard_mode="block_destructive",
        passive_context=context,
        passive_guard_report_text="The PDF is Preview compatible.",
    )

    assert "PASSIVE_RUNTIME_TARGET_APP_CLAIM_CONFLICT" in _runtime_warning_codes(warn)
    assert warn["status"] == "ok"
    assert block["status"] == "ok"


def test_shadow_parser_only_claims_zero_corrupted_batch_warns_and_blocks():
    context = {
        "validation": {
            "documents": [
                {
                    "file_path": "a.pdf",
                    "checks_run": ["parser_readable"],
                    "checks_missing": ["target_app_compatibility"],
                    "safe_claim_level": "parser_readable",
                    "status": "warning",
                }
            ]
        }
    }

    warn = _runner_result(
        query="Verify all PDFs and ensure 0 corrupted.",
        guard_mode="warn",
        passive_context=context,
        passive_guard_report_text="All PDFs valid, 0 corrupted.",
    )
    block = _runner_result(
        query="Verify all PDFs and ensure 0 corrupted.",
        guard_mode="block_destructive",
        passive_context=context,
        passive_guard_report_text="All PDFs valid, 0 corrupted.",
    )

    assert "PASSIVE_RUNTIME_DOCUMENT_AGGREGATE_CONFLICT" in _runtime_warning_codes(warn)
    assert "PARSER_ONLY_PDF_CLAIM_ALL_VALID" in _hard_block_codes(block)
    assert block["status"] == "blocked"


def test_shadow_missing_eof_claims_full_validity_warns(tmp_path):
    pdf = _tiny_pdf(tmp_path / "truncated.pdf", eof=False)
    signature = inspect_pdf_binary_signatures(str(pdf))

    result = _runner_result(
        query="Validate truncated PDF.",
        guard_mode="warn",
        passive_guard_document_validation={
            "file_path": str(pdf),
            "intended_use": "complete valid PDF for user use",
            "binary_signature_ok": signature.has_pdf_header and signature.eof_marker_near_tail,
            "parser_readable": True,
            "report_text": "PDF fully valid.",
        },
    )

    metadata = result["passive_intelligence_guard"]["document_validation"]
    assert metadata["decision"]["status"] in {"fail", "blocked", "unknown"}
    assert metadata["warning"]["code"] != "PASSIVE_DOCUMENT_VALIDATION_OK"


def test_shadow_qlmanage_preview_command_rejected():
    command = PdfValidationCommand("quicklook_preview", ("qlmanage", "-p", "report.pdf"), opens_gui=True)

    assert reject_unsafe_pdf_validation_command(command) in {
        "gui_open_forbidden",
        "qlmanage_preview_gui_forbidden",
    }


def test_shadow_safe_thumbnail_plan_no_execution(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    safe_root = tmp_path / "thumbs"
    policy = PdfValidationExecutionPolicy(execute=True, allow_qlmanage_thumbnail=True, allowed_output_root=str(safe_root))

    plan = build_pdf_validation_adapter_plan(str(pdf), target_app="Preview", policy=policy)
    thumbnail = next(command for command in plan.command_plan if command.check_name == "quicklook_thumbnail_check")

    assert reject_unsafe_pdf_validation_command(thumbnail) is None
    assert plan.executes_by_default is False


def test_shadow_missing_optional_qpdf_pdfinfo_mdls_is_unknown_not_pass(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    plan = build_pdf_validation_adapter_plan(str(pdf))

    decision = run_pdf_validation_adapter(
        plan,
        PdfValidationExecutionPolicy(execute=True),
        command_runner=lambda argv, **kwargs: pytest.fail("unavailable tools must not execute"),
        tool_availability={"file": False, "qpdf": False, "pdfinfo": False, "mdls": False, "qlmanage": False, "command_paths": {}},
    )

    assert decision.status == "unknown"
    assert decision.status != "pass"


def test_shadow_synthetic_tmp_pdf_opt_in_execution_smoke_without_native_tools(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    plan = build_pdf_validation_adapter_plan(str(pdf))

    decision = run_pdf_validation_adapter(
        plan,
        PdfValidationExecutionPolicy(execute=True, allow_native_tools=False),
        command_runner=lambda argv, **kwargs: pytest.fail("native tools disabled"),
        tool_availability={"file": False, "qpdf": False, "pdfinfo": False, "mdls": False, "qlmanage": False, "command_paths": {}},
    )

    assert decision.binary_signature_ok is True
    assert decision.safe_claim_level == "binary_signature_checked"


def test_shadow_no_pid_no_log_status_needed():
    result = _runner_result(
        query="Run DECISION StageRecord with Codex timeout monitoring",
        guard_mode="warn",
        passive_context={"long_run_process_observer": {"observe": True}},
    )

    decision = result["passive_intelligence_guard"]["long_run_process_observer"]["decision"]
    assert decision["status"] == "unknown"
    assert "LONG_RUN_OBSERVER_STATUS_NEEDED" in decision["warning_codes"]


def test_shadow_explicit_log_tail_bounded(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("start\n" + ("x" * 4096), encoding="utf-8")

    snapshot = read_log_tail_safely(str(log), 64, allowed_roots=(str(tmp_path),))

    assert snapshot.bytes_read == 64
    assert snapshot.truncated is True


def test_shadow_running_no_fresh_output_inspects_not_fails():
    result = _runner_result(
        query="Run DECISION StageRecord with Codex timeout monitoring",
        guard_mode="warn",
        passive_context={
            "long_run_process_observer": {
                "observe": True,
                "expected_silence_budget": 10,
                "supplied_state": {"process_status": "running", "silence_seconds": 120, "elapsed_seconds": 180},
            }
        },
    )

    decision = result["passive_intelligence_guard"]["long_run_process_observer"]["decision"]
    assert decision["status"] == "running"
    assert decision["should_inspect"] is True
    assert decision["should_block"] is False


def test_shadow_timeout_with_partial_output_is_partial_not_completed():
    result = _runner_result(
        query="Codex timeout with partial output.",
        guard_mode="warn",
        passive_context={"long_run_process_observer": {"observe": True, "supplied_state": {"process_status": "timeout", "partial_output_present": True}}},
    )

    decision = result["passive_intelligence_guard"]["long_run_process_observer"]["decision"]
    assert decision["status"] == "partial"
    assert "completed" in decision["prohibited_claims"]


def test_shadow_repeated_same_error_blocks():
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


def test_shadow_auth_or_permission_error_blocks():
    policy = build_long_run_observer_policy(observe=True)
    auth_snapshot = collect_long_run_observer_snapshot(policy, supplied_state={"process_status": "running", "current_error_signature": "auth token expired"})
    perm_snapshot = collect_long_run_observer_snapshot(policy, supplied_state={"process_status": "running", "current_error_signature": "permission denied"})

    assert classify_long_run_observer_snapshot(auth_snapshot, policy).should_block is True
    assert classify_long_run_observer_snapshot(perm_snapshot, policy).should_block is True


def test_shadow_process_inaccessible_is_unknown_not_failed(monkeypatch):
    def fake_run(argv, **kwargs):
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "not accessible"})()

    monkeypatch.setattr("tools.long_run_process_observer.subprocess.run", fake_run)
    result = _runner_result(
        query="Run DECISION StageRecord with process observer.",
        guard_mode="debug",
        passive_context={"long_run_process_observer": {"observe": True, "allow_process_probe": True, "pid": 999999}},
    )

    snapshot = result["passive_intelligence_guard"]["long_run_process_observer"]["snapshot"]["process_snapshot"]
    assert snapshot["process_status"] == "unknown"
    assert snapshot["status_reason"] == "process_not_found_or_inaccessible"


def test_shadow_completed_claim_while_running_warns_and_blocks():
    context = {"runner": {"process_status": "running"}}

    warn = _runner_result(
        query="Codex is still running.",
        guard_mode="warn",
        passive_context=context,
        passive_guard_report_text="PASS completed.",
    )
    block = _runner_result(
        query="Codex is still running.",
        guard_mode="block_destructive",
        passive_context=context,
        passive_guard_report_text="PASS completed.",
    )

    assert "PASSIVE_RUNTIME_COMPLETION_CONFLICT" in _runtime_warning_codes(warn)
    assert "PARTIAL_OR_BLOCKED_CLAIM_COMPLETED" in _hard_block_codes(block)


def test_shadow_codex_partial_output_claimed_done_blocks():
    result = _runner_result(
        query="Codex produced partial output.",
        guard_mode="block_destructive",
        passive_context={"runner": {"process_status": "timeout", "partial_output_present": True}},
        passive_guard_report_text="Done. PASS.",
    )

    assert "TIMEOUT_PARTIAL_CLAIM_COMPLETED" in _hard_block_codes(result)


def test_shadow_missing_last_output_for_long_task_warns_not_blocks():
    warn = _runner_result(query="Codex is stuck with no output; inspect status.", guard_mode="warn")
    block = _runner_result(query="Codex is stuck with no output; inspect status.", guard_mode="block_destructive")

    assert "PASSIVE_RUNTIME_WATCHDOG_STATUS_REQUIRED" in _runtime_warning_codes(warn)
    assert block["status"] == "ok"


def test_shadow_read_access_claims_write_success_warns_and_blocks():
    context = {"remote": {"remote": "origin", "branch": "research-decision-validation", "read_access": True}}

    warn = _runner_result(guard_mode="warn", passive_context=context, passive_guard_report_text="Branch pushed and synced.")
    block = _runner_result(guard_mode="block_destructive", passive_context=context, passive_guard_report_text="Branch pushed and synced.")

    assert "PASSIVE_RUNTIME_REMOTE_PUSH_CONFLICT" in _runtime_warning_codes(warn)
    assert "REMOTE_READ_CLAIM_PUSHED" in _hard_block_codes(block)


def test_shadow_local_tag_claims_remote_tag_warns_and_blocks():
    context = {"remote": {"remote": "fork", "operation": "tag", "local_tag": "v1", "tag_verified": False}}

    warn = _runner_result(guard_mode="warn", passive_context=context, passive_guard_report_text="Remote tag pushed.")
    block = _runner_result(guard_mode="block_destructive", passive_context=context, passive_guard_report_text="Remote tag pushed.")

    assert "PASSIVE_RUNTIME_REMOTE_TAG_CONFLICT" in _runtime_warning_codes(warn)
    assert "LOCAL_TAG_CLAIM_REMOTE_TAG" in _hard_block_codes(block)


@pytest.mark.parametrize(
    "context",
    [
        {"validation": {"pdf_validation": {"file_path": "report.pdf", "target_app": "Preview"}}},
        {"long_run_process_observer": {"observe": True}},
        {"remote": {"read_access": True}},
    ],
)
def test_shadow_off_mode_silent_all_scenarios(context):
    result = _runner_result(guard_mode="off", passive_context=context)

    assert "passive_intelligence_guard" not in result


def test_shadow_warn_mode_advisory_only_all_scenarios():
    result = _runner_result(
        guard_mode="warn",
        passive_context={"runner": {"files_written": ["tools/source.py"]}},
    )

    assert result["status"] == "ok"
    assert result["passive_intelligence_guard"]["runtime_ledger"]["hard_block_decision"]["should_block"] is False


def test_shadow_debug_mode_metadata_only_all_scenarios():
    result = _runner_result(
        guard_mode="debug",
        passive_context={"runner": {"files_written": ["tools/source.py"]}},
    )

    assert result["status"] == "ok"
    assert result["passive_intelligence_guard"]["runtime_ledger"]["hard_block_decision"]["should_block"] is False


def test_shadow_block_destructive_blocks_only_selected_cases():
    selected = _runner_result(
        guard_mode="block_destructive",
        passive_context={"runner": {"files_written": ["tools/source.py"]}},
    )
    unselected = _runner_result(
        query="Codex is stuck with no output; inspect status.",
        guard_mode="block_destructive",
    )

    assert selected["status"] == "blocked"
    assert unselected["status"] == "ok"


def test_shadow_ordinary_codex_prompt_generation_not_blocked():
    result = _runner_result(
        query="Generate a Codex prompt with current situation and next action.",
        guard_mode="block_destructive",
        passive_guard_action={"type": "explain", "intent": "generate Codex prompt"},
    )

    assert result["status"] == "ok"


def test_shadow_outputs_report_write_not_blocked():
    result = _runner_result(
        guard_mode="block_destructive",
        passive_context={"runner": {"files_written": ["outputs/report.md"]}},
    )

    assert result["status"] == "ok"


def test_shadow_ordinary_fork_push_not_blocked():
    result = _runner_result(
        query="Push validated branch to fork.",
        guard_mode="block_destructive",
        passive_guard_action={"type": "git", "command": "git push fork research-decision-validation"},
    )

    assert result["status"] == "ok"
