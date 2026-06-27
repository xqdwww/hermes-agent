"""Opt-in PDF validation adapter for passive-intelligence metadata."""

from __future__ import annotations

import importlib.util
import os
import platform as platform_module
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from tools.passive_intelligence_guard import (
    PdfSignatureResult,
    classify_document_validation_requirements,
    inspect_pdf_binary_signatures,
)


COMMAND_STATUS_VALUES = {"pass", "warning", "fail", "skipped", "unknown"}
DECISION_STATUS_VALUES = {"pass", "warning", "fail", "blocked", "unknown"}
DEFAULT_TIMEOUT_SECONDS = 5
_OUTPUT_SUBDIR = "pdf_validation_adapter"


@dataclass(frozen=True)
class PdfValidationExecutionPolicy:
    execute: bool = False
    allow_native_tools: bool = True
    allow_qlmanage_thumbnail: bool = False
    allow_gui_open: bool = False
    allow_ocr: bool = False
    allowed_output_root: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_file_size_bytes: int | None = None
    require_explicit_file_paths: bool = True


@dataclass(frozen=True)
class PdfValidationCommand:
    check_name: str
    command_argv: tuple[str, ...]
    writes_output: bool = False
    output_dir_required: bool = False
    opens_gui: bool = False
    destructive: bool = False
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    platform: str = "portable"
    required_for_claim_level: str = "parser_readable"
    skip_if_unavailable: bool = True
    reason: str = ""


@dataclass(frozen=True)
class PdfValidationAdapterPlan:
    file_path: str
    intended_use: str
    target_app: str
    required_checks: tuple[str, ...]
    optional_checks: tuple[str, ...]
    command_plan: tuple[PdfValidationCommand, ...]
    executes_by_default: bool = False
    allowed_to_execute: bool = False
    safe_claim_ceiling_before_execution: str = "unvalidated"
    prohibited_claims_before_execution: tuple[str, ...] = ()


@dataclass(frozen=True)
class PdfValidationToolAvailability:
    file: bool = False
    qpdf: bool = False
    pdfinfo: bool = False
    mdls: bool = False
    qlmanage: bool = False
    pymupdf: bool = False
    pypdf: bool = False
    command_paths: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PdfValidationCommandResult:
    check_name: str
    command_argv: tuple[str, ...]
    executed: bool
    available: bool
    exit_code: int | None
    stdout_excerpt: str
    stderr_excerpt: str
    timed_out: bool
    output_paths: tuple[str, ...]
    status: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PdfValidationAdapterDecision:
    file_path: str
    status: str
    binary_signature_ok: bool | None
    parser_readable: bool | None
    structural_check_ok: bool | None
    render_or_thumbnail_check_ok: bool | None
    metadata_check_ok: bool | None
    target_app_check_ok: bool | None
    checks_run: tuple[str, ...]
    checks_skipped: tuple[str, ...]
    checks_failed: tuple[str, ...]
    checks_unknown: tuple[str, ...]
    safe_claim_level: str
    prohibited_claims: tuple[str, ...]
    user_facing_summary: str


CommandRunner = Callable[..., Any]


def build_pdf_validation_adapter_plan(
    file_path: str,
    intended_use: str | None = None,
    target_app: str | None = None,
    policy: PdfValidationExecutionPolicy | None = None,
) -> PdfValidationAdapterPlan:
    effective_policy = policy or PdfValidationExecutionPolicy()
    normalized_path = _require_explicit_pdf_path(file_path, effective_policy)
    intended = (intended_use or "").strip()
    target = (target_app or _infer_target_app(intended)).strip()
    requirement_text = " ".join(item for item in (intended, target) if item)
    requirements = classify_document_validation_requirements(normalized_path, requirement_text)
    command_plan = tuple(_build_native_command_plan(normalized_path, target, effective_policy))
    enabled_rejections = [
        _reject_command_for_policy(command, effective_policy)
        for command in command_plan
        if _command_enabled_by_policy(command, effective_policy)
    ]
    allowed_to_execute = effective_policy.execute and all(reason is None for reason in enabled_rejections)
    return PdfValidationAdapterPlan(
        file_path=normalized_path,
        intended_use=intended,
        target_app=target,
        required_checks=requirements.required_checks,
        optional_checks=requirements.optional_checks,
        command_plan=command_plan,
        executes_by_default=False,
        allowed_to_execute=allowed_to_execute,
        safe_claim_ceiling_before_execution="unvalidated",
        prohibited_claims_before_execution=_prohibited_claims_before_execution(target),
    )


def detect_pdf_validation_tools() -> PdfValidationToolAvailability:
    command_names = ("file", "qpdf", "pdfinfo", "mdls", "qlmanage")
    command_paths = {name: path for name in command_names if (path := shutil.which(name))}
    return PdfValidationToolAvailability(
        file="file" in command_paths,
        qpdf="qpdf" in command_paths,
        pdfinfo="pdfinfo" in command_paths,
        mdls="mdls" in command_paths,
        qlmanage="qlmanage" in command_paths,
        pymupdf=_module_available("pymupdf") or _module_available("fitz"),
        pypdf=_module_available("pypdf") or _module_available("PyPDF2"),
        command_paths=command_paths,
    )


def run_pdf_validation_adapter(
    plan: PdfValidationAdapterPlan,
    policy: PdfValidationExecutionPolicy | None = None,
    *,
    command_runner: CommandRunner | None = None,
    tool_availability: PdfValidationToolAvailability | dict[str, Any] | None = None,
) -> PdfValidationAdapterDecision:
    effective_policy = policy or PdfValidationExecutionPolicy()
    availability = _coerce_tool_availability(tool_availability) if tool_availability is not None else detect_pdf_validation_tools()
    if not effective_policy.execute:
        skipped = tuple(
            _command_result_skipped(command, available=_is_command_available(command, availability), note="execution_disabled")
            for command in plan.command_plan
        )
        return classify_pdf_command_results(plan.file_path, None, skipped, plan.intended_use, plan.target_app)

    file_path = _require_explicit_pdf_path(plan.file_path, effective_policy)
    if effective_policy.max_file_size_bytes is not None:
        try:
            if Path(file_path).stat().st_size > effective_policy.max_file_size_bytes:
                return _blocked_decision(
                    file_path,
                    "file_exceeds_max_file_size",
                    _prohibited_claims_before_execution(plan.target_app),
                )
        except OSError as exc:
            return _blocked_decision(file_path, f"stat_failed:{exc.__class__.__name__}", _prohibited_claims_before_execution(plan.target_app))

    binary_result = inspect_pdf_binary_signatures(file_path)
    runner = command_runner or subprocess.run
    command_results: list[PdfValidationCommandResult] = []
    for command in plan.command_plan:
        if not effective_policy.allow_native_tools:
            command_results.append(_command_result_skipped(command, available=False, note="native_tools_disabled"))
            continue
        if command.check_name == "quicklook_thumbnail_check" and not effective_policy.allow_qlmanage_thumbnail:
            command_results.append(_command_result_skipped(command, available=_is_command_available(command, availability), note="qlmanage_thumbnail_disabled"))
            continue
        rejection = _reject_command_for_policy(command, effective_policy)
        if rejection is not None:
            command_results.append(_command_result_rejected(command, rejection))
            continue
        available = _is_command_available(command, availability)
        if not available:
            status = "skipped" if command.skip_if_unavailable else "unknown"
            command_results.append(
                PdfValidationCommandResult(
                    check_name=command.check_name,
                    command_argv=command.command_argv,
                    executed=False,
                    available=False,
                    exit_code=None,
                    stdout_excerpt="",
                    stderr_excerpt="",
                    timed_out=False,
                    output_paths=(),
                    status=status,
                    notes=("tool_unavailable",),
                )
            )
            continue
        if command.writes_output:
            output_dir = _command_output_dir(command)
            if output_dir:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
        command_results.append(_run_pdf_validation_command(command, runner))
    return classify_pdf_command_results(file_path, binary_result, tuple(command_results), plan.intended_use, plan.target_app)


def classify_pdf_command_results(
    file_path: str,
    binary_result: PdfSignatureResult | dict[str, Any] | None,
    command_results: tuple[PdfValidationCommandResult, ...] | list[PdfValidationCommandResult],
    intended_use: str | None = None,
    target_app: str | None = None,
) -> PdfValidationAdapterDecision:
    target = (target_app or _infer_target_app(intended_use or "")).strip()
    requirement_text = " ".join(item for item in ((intended_use or "").strip(), target) if item)
    requirements = classify_document_validation_requirements(file_path, requirement_text)
    results = tuple(command_results or ())
    binary_signature_ok = _binary_signature_ok(binary_result)
    parser_readable = _check_state(results, {"pdfinfo_metadata_check"})
    structural_check_ok = _check_state(results, {"qpdf_structural_check"})
    metadata_check_ok = _check_state(results, {"pdfinfo_metadata_check", "mdls_metadata_check"})
    render_or_thumbnail_check_ok = _check_state(results, {"quicklook_thumbnail_check"})
    target_app_check_ok = _target_app_state(target, render_or_thumbnail_check_ok)
    checks_run = tuple(result.check_name for result in results if result.executed)
    checks_skipped = tuple(result.check_name for result in results if result.status == "skipped")
    checks_failed = tuple(result.check_name for result in results if result.status == "fail")
    checks_unknown = tuple(result.check_name for result in results if result.status in {"unknown", "warning"})
    required_missing = _missing_required_checks(
        requirements.required_checks,
        binary_signature_ok=binary_signature_ok,
        parser_readable=parser_readable,
        render_or_thumbnail_check_ok=render_or_thumbnail_check_ok,
        target_app_check_ok=target_app_check_ok,
    )
    if binary_signature_ok is False or checks_failed:
        status = "fail"
    elif required_missing:
        status = "unknown"
    elif requirements.required_checks:
        status = "pass"
    elif checks_unknown or checks_skipped:
        status = "warning"
    else:
        status = "unknown"
    safe_claim_level = _safe_claim_level(
        binary_signature_ok=binary_signature_ok,
        parser_readable=parser_readable,
        structural_check_ok=structural_check_ok,
        render_or_thumbnail_check_ok=render_or_thumbnail_check_ok,
        target_app_check_ok=target_app_check_ok,
    )
    prohibited_claims = _prohibited_claims_for_decision(status, target, target_app_check_ok)
    return PdfValidationAdapterDecision(
        file_path=file_path,
        status=status,
        binary_signature_ok=binary_signature_ok,
        parser_readable=parser_readable,
        structural_check_ok=structural_check_ok,
        render_or_thumbnail_check_ok=render_or_thumbnail_check_ok,
        metadata_check_ok=metadata_check_ok,
        target_app_check_ok=target_app_check_ok,
        checks_run=tuple(dict.fromkeys(checks_run)),
        checks_skipped=tuple(dict.fromkeys((*checks_skipped, *required_missing))),
        checks_failed=tuple(dict.fromkeys(checks_failed)),
        checks_unknown=tuple(dict.fromkeys(checks_unknown)),
        safe_claim_level=safe_claim_level,
        prohibited_claims=prohibited_claims,
        user_facing_summary=_decision_summary(status, safe_claim_level, required_missing, checks_failed),
    )


def safe_pdf_validation_claim(decision: PdfValidationAdapterDecision) -> str:
    return decision.user_facing_summary


def reject_unsafe_pdf_validation_command(command: PdfValidationCommand) -> str | None:
    argv = tuple(command.command_argv or ())
    if not argv:
        return "missing_command_argv"
    base = Path(argv[0]).name.casefold()
    lowered_args = tuple(str(arg).casefold() for arg in argv)
    if command.destructive:
        return "destructive_command_forbidden"
    if command.opens_gui:
        return "gui_open_forbidden"
    if base in {"open", "osascript"}:
        return "gui_open_command_forbidden"
    if base in {"ocrmypdf", "tesseract", "marker", "marker_single"} or any("ocr" in arg for arg in lowered_args):
        return "ocr_command_forbidden"
    if base in {"curl", "wget", "ssh", "scp", "rsync"}:
        return "network_command_forbidden"
    if _contains_shell_control(argv):
        return "shell_control_tokens_forbidden"
    if base == "qlmanage":
        if "-p" in lowered_args:
            return "qlmanage_preview_gui_forbidden"
        if "-t" not in lowered_args:
            return "qlmanage_only_thumbnail_allowed"
        if command.writes_output and "-o" not in lowered_args:
            return "qlmanage_thumbnail_requires_output_dir"
        return None
    if base == "qpdf":
        if "--check" not in lowered_args:
            return "qpdf_only_check_allowed"
        forbidden = {"--replace-input", "--linearize", "--empty", "--pages"}
        if any(arg in forbidden for arg in lowered_args):
            return "qpdf_mutation_or_rewrite_forbidden"
        return None
    if base in {"file", "pdfinfo", "mdls"}:
        if command.writes_output:
            return "unexpected_output_writing_command"
        return None
    return "command_not_allowlisted"


def _build_native_command_plan(
    file_path: str,
    target_app: str,
    policy: PdfValidationExecutionPolicy,
) -> list[PdfValidationCommand]:
    timeout = max(1, int(policy.timeout_seconds or DEFAULT_TIMEOUT_SECONDS))
    commands = [
        PdfValidationCommand(
            check_name="file_type_check",
            command_argv=("file", "--brief", "--mime-type", file_path),
            timeout_seconds=timeout,
            platform="portable",
            required_for_claim_level="binary_only",
            reason="Confirm the path looks like a PDF without parsing or rendering it.",
        ),
        PdfValidationCommand(
            check_name="qpdf_structural_check",
            command_argv=("qpdf", "--check", file_path),
            timeout_seconds=timeout,
            platform="portable",
            required_for_claim_level="structurally_validated",
            reason="Run qpdf structural checks if qpdf is installed.",
        ),
        PdfValidationCommand(
            check_name="pdfinfo_metadata_check",
            command_argv=("pdfinfo", file_path),
            timeout_seconds=timeout,
            platform="portable",
            required_for_claim_level="parser_readable",
            reason="Run pdfinfo as a parser/metadata check if available.",
        ),
    ]
    if _target_is_macos_preview_or_quicklook(target_app) or platform_module.system().casefold() == "darwin":
        commands.append(
            PdfValidationCommand(
                check_name="mdls_metadata_check",
                command_argv=("mdls", file_path),
                timeout_seconds=timeout,
                platform="macos",
                required_for_claim_level="metadata_checked",
                reason="Run macOS metadata inspection if mdls is installed.",
            )
        )
    if _target_is_macos_preview_or_quicklook(target_app):
        output_dir = _thumbnail_output_dir(policy)
        argv = ("qlmanage", "-t", "-s", "1", "-o", output_dir, file_path) if output_dir else ("qlmanage", "-t", "-s", "1", file_path)
        commands.append(
            PdfValidationCommand(
                check_name="quicklook_thumbnail_check",
                command_argv=argv,
                writes_output=True,
                output_dir_required=True,
                timeout_seconds=timeout,
                platform="macos",
                required_for_claim_level="target_app_validated",
                reason="Generate a QuickLook thumbnail only when explicitly enabled and routed to a safe output directory.",
            )
        )
    return commands


def _run_pdf_validation_command(command: PdfValidationCommand, runner: CommandRunner) -> PdfValidationCommandResult:
    try:
        completed = runner(
            list(command.command_argv),
            capture_output=True,
            text=True,
            timeout=command.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return PdfValidationCommandResult(
            check_name=command.check_name,
            command_argv=command.command_argv,
            executed=True,
            available=True,
            exit_code=None,
            stdout_excerpt=_excerpt(getattr(exc, "stdout", "") or ""),
            stderr_excerpt=_excerpt(getattr(exc, "stderr", "") or ""),
            timed_out=True,
            output_paths=_command_output_paths(command),
            status="unknown",
            notes=("command_timed_out",),
        )
    except OSError as exc:
        return PdfValidationCommandResult(
            check_name=command.check_name,
            command_argv=command.command_argv,
            executed=False,
            available=False,
            exit_code=None,
            stdout_excerpt="",
            stderr_excerpt=_excerpt(str(exc)),
            timed_out=False,
            output_paths=(),
            status="unknown",
            notes=(f"os_error:{exc.__class__.__name__}",),
        )
    exit_code = int(getattr(completed, "returncode", 1))
    return PdfValidationCommandResult(
        check_name=command.check_name,
        command_argv=command.command_argv,
        executed=True,
        available=True,
        exit_code=exit_code,
        stdout_excerpt=_excerpt(getattr(completed, "stdout", "") or ""),
        stderr_excerpt=_excerpt(getattr(completed, "stderr", "") or ""),
        timed_out=False,
        output_paths=_command_output_paths(command),
        status="pass" if exit_code == 0 else "fail",
        notes=(),
    )


def _reject_command_for_policy(command: PdfValidationCommand, policy: PdfValidationExecutionPolicy) -> str | None:
    rejection = reject_unsafe_pdf_validation_command(command)
    if rejection is not None:
        return rejection
    if command.opens_gui and not policy.allow_gui_open:
        return "gui_open_disabled"
    if "ocr" in command.check_name.casefold() and not policy.allow_ocr:
        return "ocr_disabled"
    if command.writes_output:
        output_dir = _command_output_dir(command)
        if not output_dir:
            return "output_dir_required"
        allowed_root = policy.allowed_output_root
        if not allowed_root:
            return "allowed_output_root_required"
        if not _is_relative_to(Path(output_dir), Path(allowed_root)):
            return "output_dir_outside_allowed_root"
    return None


def _command_enabled_by_policy(command: PdfValidationCommand, policy: PdfValidationExecutionPolicy) -> bool:
    if command.check_name == "quicklook_thumbnail_check" and not policy.allow_qlmanage_thumbnail:
        return False
    if not policy.allow_native_tools:
        return False
    return True


def _is_command_available(command: PdfValidationCommand, availability: PdfValidationToolAvailability) -> bool:
    if not command.command_argv:
        return False
    name = Path(command.command_argv[0]).name
    return bool(availability.command_paths.get(name) or getattr(availability, name, False))


def _coerce_tool_availability(value: PdfValidationToolAvailability | dict[str, Any]) -> PdfValidationToolAvailability:
    if isinstance(value, PdfValidationToolAvailability):
        return value
    data = dict(value or {})
    command_paths = dict(data.get("command_paths") or {})
    for name in ("file", "qpdf", "pdfinfo", "mdls", "qlmanage"):
        if data.get(name) and name not in command_paths:
            command_paths[name] = name
    return PdfValidationToolAvailability(
        file=bool(data.get("file")),
        qpdf=bool(data.get("qpdf")),
        pdfinfo=bool(data.get("pdfinfo")),
        mdls=bool(data.get("mdls")),
        qlmanage=bool(data.get("qlmanage")),
        pymupdf=bool(data.get("pymupdf")),
        pypdf=bool(data.get("pypdf")),
        command_paths=command_paths,
    )


def _command_result_skipped(command: PdfValidationCommand, *, available: bool, note: str) -> PdfValidationCommandResult:
    return PdfValidationCommandResult(
        check_name=command.check_name,
        command_argv=command.command_argv,
        executed=False,
        available=available,
        exit_code=None,
        stdout_excerpt="",
        stderr_excerpt="",
        timed_out=False,
        output_paths=(),
        status="skipped",
        notes=(note,),
    )


def _command_result_rejected(command: PdfValidationCommand, reason: str) -> PdfValidationCommandResult:
    return PdfValidationCommandResult(
        check_name=command.check_name,
        command_argv=command.command_argv,
        executed=False,
        available=True,
        exit_code=None,
        stdout_excerpt="",
        stderr_excerpt="",
        timed_out=False,
        output_paths=(),
        status="fail",
        notes=(f"rejected:{reason}",),
    )


def _blocked_decision(file_path: str, reason: str, prohibited_claims: tuple[str, ...]) -> PdfValidationAdapterDecision:
    return PdfValidationAdapterDecision(
        file_path=file_path,
        status="blocked",
        binary_signature_ok=None,
        parser_readable=None,
        structural_check_ok=None,
        render_or_thumbnail_check_ok=None,
        metadata_check_ok=None,
        target_app_check_ok=None,
        checks_run=(),
        checks_skipped=(),
        checks_failed=(),
        checks_unknown=(reason,),
        safe_claim_level="unvalidated",
        prohibited_claims=prohibited_claims,
        user_facing_summary=f"PDF validation did not run: {reason}.",
    )


def _binary_signature_ok(binary_result: PdfSignatureResult | dict[str, Any] | None) -> bool | None:
    if binary_result is None:
        return None
    if isinstance(binary_result, PdfSignatureResult):
        return (
            binary_result.has_pdf_header
            and binary_result.has_eof_marker
            and binary_result.eof_marker_near_tail
            and not binary_result.suspicious_truncation
        )
    if isinstance(binary_result, dict):
        if "binary_signature_ok" in binary_result:
            return _optional_bool(binary_result.get("binary_signature_ok"))
        keys = {"has_pdf_header", "has_eof_marker", "eof_marker_near_tail"}
        if keys <= set(binary_result):
            return (
                bool(binary_result.get("has_pdf_header"))
                and bool(binary_result.get("has_eof_marker"))
                and bool(binary_result.get("eof_marker_near_tail"))
                and not bool(binary_result.get("suspicious_truncation"))
            )
    return None


def _check_state(results: tuple[PdfValidationCommandResult, ...], names: set[str]) -> bool | None:
    relevant = [result for result in results if result.check_name in names and result.executed]
    if any(result.status == "fail" for result in relevant):
        return False
    if any(result.status == "pass" for result in relevant):
        return True
    if any(result.status in {"unknown", "warning"} for result in relevant):
        return None
    return None


def _target_app_state(target_app: str, render_or_thumbnail_check_ok: bool | None) -> bool | None:
    if _target_is_macos_preview_or_quicklook(target_app):
        return render_or_thumbnail_check_ok
    return None


def _missing_required_checks(
    required_checks: tuple[str, ...],
    *,
    binary_signature_ok: bool | None,
    parser_readable: bool | None,
    render_or_thumbnail_check_ok: bool | None,
    target_app_check_ok: bool | None,
) -> tuple[str, ...]:
    missing: list[str] = []
    for check in required_checks:
        if check == "binary_signature" and binary_signature_ok is not True:
            missing.append(check)
        elif check == "parser_readable" and parser_readable is not True:
            missing.append(check)
        elif check == "render_check" and render_or_thumbnail_check_ok is not True:
            missing.append(check)
        elif check in {"macos_preview_compatibility", "target_app_compatibility"} and target_app_check_ok is not True:
            missing.append(check)
    return tuple(dict.fromkeys(missing))


def _safe_claim_level(
    *,
    binary_signature_ok: bool | None,
    parser_readable: bool | None,
    structural_check_ok: bool | None,
    render_or_thumbnail_check_ok: bool | None,
    target_app_check_ok: bool | None,
) -> str:
    if target_app_check_ok is True:
        return "target_app_validated"
    if render_or_thumbnail_check_ok is True:
        return "rendered"
    if structural_check_ok is True and parser_readable is True:
        return "structurally_validated"
    if structural_check_ok is True:
        return "structurally_checked"
    if parser_readable is True:
        return "parser_readable"
    if binary_signature_ok is True:
        return "binary_signature_checked"
    return "unvalidated"


def _prohibited_claims_before_execution(target_app: str) -> tuple[str, ...]:
    claims = ["PDF fully valid", "fully valid PDF", "all valid", "0 corrupted", "zero corrupted", "OCR completed"]
    if _target_is_macos_preview_or_quicklook(target_app):
        claims.extend(["Preview compatible", "QuickLook compatible", "target-app compatible"])
    return tuple(dict.fromkeys(claims))


def _prohibited_claims_for_decision(status: str, target_app: str, target_app_check_ok: bool | None) -> tuple[str, ...]:
    claims = ["OCR completed"]
    if status != "pass":
        claims.extend(["PDF fully valid", "fully valid PDF", "all valid", "0 corrupted", "zero corrupted"])
    if _target_is_macos_preview_or_quicklook(target_app) and target_app_check_ok is not True:
        claims.extend(["Preview compatible", "QuickLook compatible", "target-app compatible"])
    return tuple(dict.fromkeys(claims))


def _decision_summary(status: str, safe_claim_level: str, missing: tuple[str, ...], failed: tuple[str, ...]) -> str:
    if status == "pass":
        return f"PDF validation passed required checks; safe claim level: {safe_claim_level}."
    if failed:
        return f"PDF validation failed checks: {', '.join(failed)}; safe claim level: {safe_claim_level}."
    if missing:
        return f"PDF validation incomplete; missing checks: {', '.join(missing)}. Safe claim level: {safe_claim_level}."
    return f"PDF validation status is {status}; safe claim level: {safe_claim_level}."


def _require_explicit_pdf_path(file_path: str, policy: PdfValidationExecutionPolicy) -> str:
    path = str(file_path or "").strip()
    if not policy.require_explicit_file_paths:
        return path
    if not path:
        raise ValueError("pdf_validation_adapter_requires_explicit_file_path")
    if path in {".", ".."} or path.endswith((os.sep, "/")):
        raise ValueError("pdf_validation_adapter_requires_file_path_not_directory")
    if any(char in path for char in "*?[]"):
        raise ValueError("pdf_validation_adapter_rejects_glob_or_batch_path")
    if "://" in path:
        raise ValueError("pdf_validation_adapter_requires_local_file_path")
    return path


def _infer_target_app(text: str) -> str:
    lowered = (text or "").casefold()
    if "preview" in lowered:
        return "Preview"
    if "quicklook" in lowered or "quick look" in lowered:
        return "QuickLook"
    return ""


def _target_is_macos_preview_or_quicklook(target_app: str) -> bool:
    target = (target_app or "").casefold()
    return "preview" in target or "quicklook" in target or "quick look" in target


def _thumbnail_output_dir(policy: PdfValidationExecutionPolicy) -> str:
    if not policy.allowed_output_root:
        return ""
    root = Path(policy.allowed_output_root).expanduser().resolve(strict=False)
    return str(root / _OUTPUT_SUBDIR)


def _command_output_dir(command: PdfValidationCommand) -> str:
    argv = tuple(command.command_argv or ())
    lowered = [str(item).casefold() for item in argv]
    if "-o" not in lowered:
        return ""
    index = lowered.index("-o")
    if index + 1 >= len(argv):
        return ""
    return str(argv[index + 1])


def _command_output_paths(command: PdfValidationCommand) -> tuple[str, ...]:
    output_dir = _command_output_dir(command)
    return (output_dir,) if output_dir else ()


def _is_relative_to(path: Path, root: Path) -> bool:
    resolved_path = path.expanduser().resolve(strict=False)
    resolved_root = root.expanduser().resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
        return True
    except ValueError:
        return False


def _contains_shell_control(argv: tuple[str, ...]) -> bool:
    controls = {";", "&&", "||", "|", "`"}
    return any(str(arg) in controls for arg in argv)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "pass", "passed", "ok"}:
            return True
        if normalized in {"false", "no", "0", "fail", "failed"}:
            return False
    return bool(value)


def _excerpt(value: Any, limit: int = 500) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
    return text[:limit]


__all__ = [
    "PdfValidationAdapterDecision",
    "PdfValidationAdapterPlan",
    "PdfValidationCommand",
    "PdfValidationCommandResult",
    "PdfValidationExecutionPolicy",
    "PdfValidationToolAvailability",
    "build_pdf_validation_adapter_plan",
    "classify_pdf_command_results",
    "detect_pdf_validation_tools",
    "reject_unsafe_pdf_validation_command",
    "run_pdf_validation_adapter",
    "safe_pdf_validation_claim",
]
