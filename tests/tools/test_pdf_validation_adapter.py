from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.pdf_validation_adapter import (
    PdfValidationCommand,
    PdfValidationCommandResult,
    PdfValidationExecutionPolicy,
    build_pdf_validation_adapter_plan,
    classify_pdf_command_results,
    reject_unsafe_pdf_validation_command,
    run_pdf_validation_adapter,
)
from tools.task_engine_runner import task_engine_runner


def _tiny_pdf(path: Path, *, eof: bool = True) -> Path:
    suffix = b"\n%%EOF\n" if eof else b"\n"
    path.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<<>>" + suffix)
    return path


def _availability(*names: str) -> dict[str, object]:
    return {
        "file": "file" in names,
        "qpdf": "qpdf" in names,
        "pdfinfo": "pdfinfo" in names,
        "mdls": "mdls" in names,
        "qlmanage": "qlmanage" in names,
        "command_paths": {name: name for name in names},
    }


def _passing_runner(calls: list[tuple[list[str], dict[str, object]]]):
    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    return runner


def _result(check_name: str, status: str = "pass") -> PdfValidationCommandResult:
    return PdfValidationCommandResult(
        check_name=check_name,
        command_argv=(check_name,),
        executed=True,
        available=True,
        exit_code=0 if status == "pass" else 1,
        stdout_excerpt="ok" if status == "pass" else "",
        stderr_excerpt="" if status == "pass" else "failed",
        timed_out=False,
        output_paths=(),
        status=status,
        notes=(),
    )


def test_default_plan_does_not_execute_commands(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    calls: list[tuple[list[str], dict[str, object]]] = []
    plan = build_pdf_validation_adapter_plan(str(pdf))

    decision = run_pdf_validation_adapter(
        plan,
        PdfValidationExecutionPolicy(execute=False),
        command_runner=_passing_runner(calls),
        tool_availability=_availability("file", "qpdf", "pdfinfo"),
    )

    assert plan.executes_by_default is False
    assert plan.allowed_to_execute is False
    assert calls == []
    assert decision.status == "unknown"


def test_explicit_execute_required_for_native_checks(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    plan = build_pdf_validation_adapter_plan(str(pdf))
    calls: list[tuple[list[str], dict[str, object]]] = []

    run_pdf_validation_adapter(
        plan,
        PdfValidationExecutionPolicy(execute=True),
        command_runner=_passing_runner(calls),
        tool_availability=_availability("file", "qpdf", "pdfinfo"),
    )

    assert [call[0][0] for call in calls] == ["file", "qpdf", "pdfinfo"]


def test_rejects_qlmanage_preview_gui_command():
    command = PdfValidationCommand("quicklook_preview", ("qlmanage", "-p", "report.pdf"), opens_gui=True)

    assert reject_unsafe_pdf_validation_command(command) in {
        "gui_open_forbidden",
        "qlmanage_preview_gui_forbidden",
    }


def test_rejects_open_preview_command():
    command = PdfValidationCommand("preview_open", ("open", "-a", "Preview", "report.pdf"), opens_gui=True)

    assert reject_unsafe_pdf_validation_command(command) in {"gui_open_forbidden", "gui_open_command_forbidden"}


def test_qlmanage_thumbnail_command_requires_safe_output_dir(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    unsafe_plan = build_pdf_validation_adapter_plan(
        str(pdf),
        target_app="Preview",
        policy=PdfValidationExecutionPolicy(execute=True, allow_qlmanage_thumbnail=True),
    )
    unsafe = next(command for command in unsafe_plan.command_plan if command.check_name == "quicklook_thumbnail_check")

    safe_root = tmp_path / "adapter-output"
    safe_plan = build_pdf_validation_adapter_plan(
        str(pdf),
        target_app="Preview",
        policy=PdfValidationExecutionPolicy(
            execute=True,
            allow_qlmanage_thumbnail=True,
            allowed_output_root=str(safe_root),
        ),
    )
    safe = next(command for command in safe_plan.command_plan if command.check_name == "quicklook_thumbnail_check")

    assert reject_unsafe_pdf_validation_command(unsafe) == "qlmanage_thumbnail_requires_output_dir"
    assert reject_unsafe_pdf_validation_command(safe) is None


def test_missing_optional_tool_yields_skipped_not_pass(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    plan = build_pdf_validation_adapter_plan(str(pdf))

    decision = run_pdf_validation_adapter(
        plan,
        PdfValidationExecutionPolicy(execute=True),
        command_runner=lambda argv, **kwargs: pytest.fail("unavailable tools must not execute"),
        tool_availability=_availability(),
    )

    assert decision.status == "unknown"
    assert "parser_readable" in decision.checks_skipped
    assert decision.safe_claim_level == "binary_signature_checked"


def test_command_timeout_yields_unknown_or_warning_not_pass(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    plan = build_pdf_validation_adapter_plan(str(pdf))

    def timeout_runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    decision = run_pdf_validation_adapter(
        plan,
        PdfValidationExecutionPolicy(execute=True),
        command_runner=timeout_runner,
        tool_availability=_availability("file", "qpdf", "pdfinfo"),
    )

    assert decision.status in {"unknown", "warning"}
    assert decision.status != "pass"
    assert "pdfinfo_metadata_check" in decision.checks_unknown


def test_eof_missing_blocks_full_valid_claim(tmp_path):
    pdf = _tiny_pdf(tmp_path / "truncated.pdf", eof=False)
    plan = build_pdf_validation_adapter_plan(str(pdf))

    decision = run_pdf_validation_adapter(
        plan,
        PdfValidationExecutionPolicy(execute=True, allow_native_tools=False),
        command_runner=lambda argv, **kwargs: pytest.fail("native tools disabled"),
        tool_availability=_availability(),
    )

    assert decision.status == "fail"
    assert decision.binary_signature_ok is False
    assert "PDF fully valid" in decision.prohibited_claims
    assert "0 corrupted" in decision.prohibited_claims


def test_suspicious_truncation_blocks_full_valid_claim(tmp_path):
    pdf = _tiny_pdf(tmp_path / "suspicious.pdf")

    decision = classify_pdf_command_results(
        str(pdf),
        {
            "has_pdf_header": True,
            "has_eof_marker": True,
            "eof_marker_near_tail": True,
            "suspicious_truncation": True,
            "file_size_bytes": 10,
        },
        (_result("pdfinfo_metadata_check"),),
    )

    assert decision.status == "fail"
    assert decision.binary_signature_ok is False
    assert "all valid" in decision.prohibited_claims


def test_parser_only_result_cannot_claim_preview_compatible(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")

    decision = classify_pdf_command_results(
        str(pdf),
        {"has_pdf_header": True, "has_eof_marker": True, "eof_marker_near_tail": True, "file_size_bytes": 10},
        (_result("pdfinfo_metadata_check"),),
        intended_use="Preview compatibility",
        target_app="Preview",
    )

    assert decision.safe_claim_level == "parser_readable"
    assert decision.target_app_check_ok is None
    assert "Preview compatible" in decision.prohibited_claims


def test_target_app_preview_requires_preview_or_quicklook_check(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")

    decision = classify_pdf_command_results(
        str(pdf),
        {"has_pdf_header": True, "has_eof_marker": True, "eof_marker_near_tail": True, "file_size_bytes": 10},
        (_result("qpdf_structural_check"), _result("pdfinfo_metadata_check")),
        target_app="Preview",
    )

    assert decision.status == "unknown"
    assert decision.safe_claim_level == "structurally_validated"
    assert decision.target_app_check_ok is None
    assert "macos_preview_compatibility" in decision.checks_skipped


def test_successful_structural_and_thumbnail_checks_raise_claim_level_without_claiming_ocr(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    out = tmp_path / "adapter-output"
    plan = build_pdf_validation_adapter_plan(
        str(pdf),
        target_app="Preview",
        policy=PdfValidationExecutionPolicy(
            execute=True,
            allow_qlmanage_thumbnail=True,
            allowed_output_root=str(out),
        ),
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    decision = run_pdf_validation_adapter(
        plan,
        PdfValidationExecutionPolicy(
            execute=True,
            allow_qlmanage_thumbnail=True,
            allowed_output_root=str(out),
        ),
        command_runner=_passing_runner(calls),
        tool_availability=_availability("file", "qpdf", "pdfinfo", "mdls", "qlmanage"),
    )

    assert decision.status == "pass"
    assert decision.safe_claim_level == "target_app_validated"
    assert "Preview compatible" not in decision.prohibited_claims
    assert "OCR completed" in decision.prohibited_claims


def test_command_runner_uses_argv_no_shell(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    plan = build_pdf_validation_adapter_plan(str(pdf))
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        assert isinstance(argv, list)
        assert "shell" not in kwargs
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    run_pdf_validation_adapter(
        plan,
        PdfValidationExecutionPolicy(execute=True),
        command_runner=runner,
        tool_availability=_availability("file", "qpdf", "pdfinfo"),
    )

    assert calls


def test_input_pdf_is_not_modified(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    before = pdf.read_bytes()
    before_mtime = pdf.stat().st_mtime_ns
    plan = build_pdf_validation_adapter_plan(str(pdf))

    run_pdf_validation_adapter(
        plan,
        PdfValidationExecutionPolicy(execute=True),
        command_runner=_passing_runner([]),
        tool_availability=_availability("pdfinfo"),
    )

    assert pdf.read_bytes() == before
    assert pdf.stat().st_mtime_ns == before_mtime


def test_output_written_only_to_temp_or_output_dir(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    out = tmp_path / "safe-output"
    policy = PdfValidationExecutionPolicy(execute=True, allow_qlmanage_thumbnail=True, allowed_output_root=str(out))
    plan = build_pdf_validation_adapter_plan(str(pdf), target_app="Preview", policy=policy)
    calls: list[tuple[list[str], dict[str, object]]] = []

    run_pdf_validation_adapter(
        plan,
        policy,
        command_runner=_passing_runner(calls),
        tool_availability=_availability("qlmanage"),
    )

    qlmanage_call = next(argv for argv, _kwargs in calls if argv[0] == "qlmanage")
    output_dir = Path(qlmanage_call[qlmanage_call.index("-o") + 1])
    output_dir.resolve(strict=False).relative_to(out.resolve(strict=False))


def test_adapter_requires_explicit_file_path(tmp_path):
    with pytest.raises(ValueError):
        build_pdf_validation_adapter_plan("")
    with pytest.raises(ValueError):
        build_pdf_validation_adapter_plan(str(tmp_path / "*.pdf"))


def test_default_task_engine_runner_output_unchanged(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    result = json.loads(
        task_engine_runner(
            query="Validate the supplied PDF.",
            mode="DECISION",
            action="contract",
            passive_context={"validation": {"pdf_validation": {"file_path": str(pdf), "target_app": "Preview"}}},
        )
    )

    assert "passive_intelligence_guard" not in result


def test_debug_mode_includes_pdf_adapter_plan_for_explicit_file_path(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    result = json.loads(
        task_engine_runner(
            query="Validate the supplied PDF.",
            mode="DECISION",
            action="contract",
            passive_guard_mode="debug",
            passive_context={"validation": {"pdf_validation": {"file_path": str(pdf), "target_app": "Preview"}}},
        )
    )

    adapter = result["passive_intelligence_guard"]["pdf_validation_adapter"]
    assert adapter["executes_native_tools"] is False
    assert adapter["plan"]["executes_by_default"] is False
    assert adapter["plan"]["file_path"] == str(pdf)


def test_warn_mode_reports_native_pdf_validation_available_not_executed(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    result = json.loads(
        task_engine_runner(
            query="Validate the supplied PDF.",
            mode="DECISION",
            action="contract",
            passive_guard_mode="warn",
            passive_context={"validation": {"pdf_validation": {"file_path": str(pdf), "target_app": "Preview"}}},
        )
    )

    warnings = result["passive_intelligence_guard"]["pdf_validation_adapter"]["warnings"]
    assert any(item["code"] == "PASSIVE_PDF_NATIVE_VALIDATION_NOT_EXECUTED" for item in warnings)


def test_block_destructive_does_not_block_merely_missing_native_pdf_validation(tmp_path):
    pdf = _tiny_pdf(tmp_path / "report.pdf")
    result = json.loads(
        task_engine_runner(
            query="Validate the supplied PDF.",
            mode="DECISION",
            action="contract",
            passive_guard_mode="block_destructive",
            passive_context={"validation": {"pdf_validation": {"file_path": str(pdf), "target_app": "Preview"}}},
        )
    )

    assert result["status"] == "ok"
    assert "pdf_validation_adapter" not in result["passive_intelligence_guard"]
