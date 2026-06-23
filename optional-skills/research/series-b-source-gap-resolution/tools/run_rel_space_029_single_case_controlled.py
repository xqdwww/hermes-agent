#!/usr/bin/env python3
"""Explicit-only rel_space_029 single-case controlled harness shell.

This runner validates handoff inputs and guard contracts. It does not generate
a dossier, does not run audit scoring, does not run full Series B, and does not
write official baseline files.
"""

from __future__ import annotations

import argparse
import json
import sys
from json import JSONDecodeError
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from rel_space_029_alias_source_guard import AliasSourceGuardError, validate_chunks
from series_b_approved_chunks_loader import (
    ApprovedChunksValidationError,
    load_approved_chunks,
    validate_chunks_against_manifest,
)
from series_b_controlled_artifact_exporter import (
    ArtifactContractError,
    validate_output_dir_policy,
    validate_required_artifact_names,
    write_dummy_artifacts,
)
from series_b_controlled_handoff_loader import HandoffValidationError, load_handoff_manifest
from series_b_controlled_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS, REQUIRED_ARTIFACTS
from series_b_real_artifact_contract import RealArtifactContractError, validate_real_mode_artifact_contract
from series_b_real_audit_adapter import AuditAdapterError, audit_rel_space_029_controlled_dossier
from series_b_real_dossier_builder_adapter import BuilderAdapterError, build_rel_space_029_controlled_raw_dossier
from series_b_real_source_packet_exporter import (
    SourcePacketExportError,
    export_rel_space_029_controlled_source_packet,
)


REPO_ROOT = Path(__file__).resolve().parents[4]


def _structured_error_payload(error_code: str, message: str) -> dict[str, object]:
    return {
        "status": "ERROR",
        "harness_status": "BLOCKED",
        "case_id": CASE_ID,
        "error_code": error_code,
        "message": message,
        "safe_to_retry": False,
        "result_enum": _result_enum_for_error(error_code),
        **EXECUTION_FALSE_FLAGS,
    }


def _result_enum_for_error(error_code: str) -> str:
    if error_code == "POLICY_LOCK_UNSAFE":
        return "BLOCKED_PRODUCTION_DEFAULT_RISK"
    if error_code == "OUTPUT_DIR_UNSAFE":
        return "BLOCKED_REPO_PATCH_REQUIRED"
    if error_code == "GUARD_VALIDATION_FAILED":
        return "BLOCKED_GUARD_VIOLATION"
    if error_code in {
        "BLOCKED_BUILDER_ENTRY_UNIMPLEMENTED",
        "BLOCKED_AUDIT_ENTRY_UNIMPLEMENTED",
        "BLOCKED_BUILDER_ENTRY_UNSAFE",
        "BLOCKED_AUDIT_ENTRY_UNSAFE",
        "BLOCKED_PRODUCTION_DEFAULT_RISK",
        "BLOCKED_BASELINE_UPDATE_RISK",
        "BLOCKED_FULL_SERIES_B_RISK",
        "BLOCKED_GUARD_VIOLATION",
    }:
        return error_code
    return "BLOCKED_REPO_PATCH_REQUIRED"


def _json_error(code: str, message: str) -> tuple[int, dict[str, object]]:
    return 2, _structured_error_payload(code, message)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate rel_space_029 single-case controlled harness inputs."
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--handoff-manifest", required=True)
    parser.add_argument("--approved-chunks", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--no-production-default", action="store_true", required=True)
    parser.add_argument("--no-baseline-update", action="store_true", required=True)
    parser.add_argument("--no-full-series-b", action="store_true", required=True)
    parser.add_argument(
        "--write-dummy-artifacts",
        action="store_true",
        help="Write dummy_test_artifact_only skeleton artifacts; never writes a real result.",
    )
    parser.add_argument(
        "--execute-real-controlled-dry-run",
        action="store_true",
        help="Layer-1 explicit real-mode skeleton; fails closed unless mock adapters are explicitly enabled.",
    )
    parser.add_argument(
        "--use-mock-builder",
        action="store_true",
        help="Test-only: write mock_builder_output instead of calling a real builder.",
    )
    parser.add_argument(
        "--use-mock-audit",
        action="store_true",
        help="Test-only: write mock_audit_output instead of calling a real audit scorer.",
    )
    return parser


def _validate_input_json_path(path: str, *, kind: str) -> tuple[bool, str]:
    input_path = Path(path).expanduser()
    if not input_path.exists():
        return False, f"{kind} path does not exist: {input_path}"
    try:
        with input_path.open("r", encoding="utf-8") as handle:
            json.load(handle)
    except JSONDecodeError as exc:
        return False, f"{kind} is malformed JSON: {exc}"
    except OSError as exc:
        return False, f"{kind} cannot be read: {exc}"
    return True, ""


def _handoff_error_code(message: str) -> str:
    lowered = message.lower()
    if "case_id" in lowered:
        return "CASE_ID_MISMATCH"
    if (
        "production_path_policy" in lowered
        or "production default" in lowered
        or "full series b" in lowered
        or "official baseline" in lowered
        or "case_scoped_only" in lowered
        or "formal_pass_gate" in lowered
        or "context source used as professional source" in lowered
        or "prototype evidence used as formal pass" in lowered
    ):
        return "POLICY_LOCK_UNSAFE"
    if "json" in lowered or "root must be a json object" in lowered:
        return "HANDOFF_MANIFEST_MALFORMED"
    return "HANDOFF_MANIFEST_MALFORMED"


def _approved_chunks_error_code(message: str) -> str:
    lowered = message.lower()
    if "case_id" in lowered:
        return "CASE_ID_MISMATCH"
    if "json" in lowered or "root must be a json object" in lowered:
        return "APPROVED_CHUNKS_MALFORMED"
    return "APPROVED_CHUNKS_MALFORMED"


def _write_manifest_used(output_dir: Path, manifest: dict[str, object]) -> str:
    path = output_dir / "rel_space_029_controlled_manifest_used.json"
    path.write_text(
        json.dumps(
            {
                "case_id": CASE_ID,
                "layer1_real_mode_skeleton": True,
                "mock_artifact": False,
                "manifest": manifest,
                **EXECUTION_FALSE_FLAGS,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return str(path)


def _write_blocked_real_mode_result(
    output_dir: Path,
    *,
    error_code: str,
    message: str,
    artifacts_written: list[str],
) -> dict[str, object]:
    result_enum = _result_enum_for_error(error_code)
    result = {
        "status": "ERROR",
        "harness_status": "BLOCKED",
        "case_id": CASE_ID,
        "error_code": error_code,
        "message": message,
        "safe_to_retry": False,
        "result_enum": result_enum,
        "passed": False,
        "partial": False,
        "blocked": True,
        "layer1_real_mode_skeleton": True,
        "artifacts_written": artifacts_written,
        **EXECUTION_FALSE_FLAGS,
    }
    summary_path = output_dir / "rel_space_029_controlled_execution_summary.md"
    result_path = output_dir / "rel_space_029_controlled_execution_result.json"
    summary_path.write_text(
        "# rel_space_029 controlled execution summary\n\n"
        "layer1_real_mode_skeleton: true\n\n"
        f"result_enum: {result_enum}\n\n"
        f"blocked_reason: {message}\n\n"
        "No real controlled regression, real dossier generation, audit scoring, "
        "full Series B, baseline update, or production default integration was performed.\n",
        encoding="utf-8",
    )
    result["artifacts_written"] = [*artifacts_written, str(summary_path), str(result_path)]
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _run_real_mode_skeleton(
    args: argparse.Namespace,
    *,
    output_dir: Path,
    manifest: dict[str, object],
) -> tuple[int, dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts_written = [_write_manifest_used(output_dir, manifest)]

    try:
        source_packet_result = export_rel_space_029_controlled_source_packet(
            case_id=args.case_id,
            approved_chunks_handoff_path=args.approved_chunks,
            controlled_handoff_manifest_path=args.handoff_manifest,
            output_dir=output_dir,
            no_production_default=args.no_production_default,
            no_baseline_update=args.no_baseline_update,
            no_full_series_b=args.no_full_series_b,
            repo_root=REPO_ROOT,
        )
        source_packet_path = source_packet_result["artifact_path"]
        artifacts_written.append(str(source_packet_path))
        builder_result = build_rel_space_029_controlled_raw_dossier(
            case_id=args.case_id,
            source_packet_path=source_packet_path,
            handoff_manifest_path=args.handoff_manifest,
            output_dir=output_dir,
            no_production_default=args.no_production_default,
            no_baseline_update=args.no_baseline_update,
            no_full_series_b=args.no_full_series_b,
            use_mock_builder=args.use_mock_builder,
            repo_root=REPO_ROOT,
        )
        raw_dossier_path = builder_result["artifact_path"]
        artifacts_written.append(str(raw_dossier_path))
        audit_result = audit_rel_space_029_controlled_dossier(
            case_id=args.case_id,
            raw_dossier_path=raw_dossier_path,
            source_packet_path=source_packet_path,
            handoff_manifest_path=args.handoff_manifest,
            output_dir=output_dir,
            no_production_default=args.no_production_default,
            no_baseline_update=args.no_baseline_update,
            no_full_series_b=args.no_full_series_b,
            use_mock_audit=args.use_mock_audit,
            repo_root=REPO_ROOT,
        )
        contract = validate_real_mode_artifact_contract(
            output_dir,
            allow_mock=args.use_mock_builder or args.use_mock_audit,
        )
    except SourcePacketExportError as exc:
        payload = _write_blocked_real_mode_result(
            output_dir,
            error_code=exc.error_code,
            message=str(exc),
            artifacts_written=artifacts_written,
        )
        return 2, payload
    except BuilderAdapterError as exc:
        payload = _write_blocked_real_mode_result(
            output_dir,
            error_code=exc.error_code,
            message=str(exc),
            artifacts_written=artifacts_written,
        )
        return 2, payload
    except AuditAdapterError as exc:
        payload = _write_blocked_real_mode_result(
            output_dir,
            error_code=exc.error_code,
            message=str(exc),
            artifacts_written=artifacts_written,
        )
        return 2, payload
    except RealArtifactContractError as exc:
        payload = _write_blocked_real_mode_result(
            output_dir,
            error_code="BLOCKED_AUDIT_ENTRY_UNSAFE",
            message=str(exc),
            artifacts_written=artifacts_written,
        )
        return 2, payload

    payload = {
        "harness_status": "PASS_LAYER1_REAL_MODE_SKELETON_MOCK_ONLY",
        "case_id": CASE_ID,
        "source_packet_exporter_status": source_packet_result["status"],
        "builder_adapter_status": builder_result["status"],
        "audit_adapter_status": audit_result["status"],
        "artifact_contract_status": contract["status"],
        "result_enum": audit_result["result"]["result_enum"],
        "passed": False,
        "mock_builder_output": bool(args.use_mock_builder),
        "mock_audit_output": bool(args.use_mock_audit),
        "note": "Layer-1 mock real-mode skeleton only; not a formal controlled regression pass.",
        **EXECUTION_FALSE_FLAGS,
    }
    return 0, payload


def run(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    if args.case_id != CASE_ID:
        return _json_error("CASE_ID_MISMATCH", "case id must be rel_space_029")
    if not args.no_production_default:
        return _json_error("POLICY_LOCK_UNSAFE", "--no-production-default is required")
    if not args.no_baseline_update:
        return _json_error("POLICY_LOCK_UNSAFE", "--no-baseline-update is required")
    if not args.no_full_series_b:
        return _json_error("POLICY_LOCK_UNSAFE", "--no-full-series-b is required")

    ok, message = _validate_input_json_path(args.handoff_manifest, kind="handoff manifest")
    if not ok:
        if "does not exist" in message:
            return _json_error("HANDOFF_MANIFEST_NOT_FOUND", message)
        return _json_error("HANDOFF_MANIFEST_MALFORMED", message)

    ok, message = _validate_input_json_path(args.approved_chunks, kind="approved chunks")
    if not ok:
        if "does not exist" in message:
            return _json_error("APPROVED_CHUNKS_NOT_FOUND", message)
        return _json_error("APPROVED_CHUNKS_MALFORMED", message)

    try:
        output_dir = validate_output_dir_policy(args.output_dir, repo_root=REPO_ROOT)
        manifest = load_handoff_manifest(args.handoff_manifest)
        chunks = load_approved_chunks(args.approved_chunks)
        validate_chunks_against_manifest(chunks, manifest)
        guard_report = validate_chunks(chunks)
        validate_required_artifact_names(REQUIRED_ARTIFACTS)
        artifacts: list[str] = []
        if args.execute_real_controlled_dry_run:
            return _run_real_mode_skeleton(args, output_dir=output_dir, manifest=manifest)
        if args.write_dummy_artifacts:
            artifacts = write_dummy_artifacts(output_dir, manifest, chunks, repo_root=REPO_ROOT)
    except HandoffValidationError as exc:
        return _json_error(_handoff_error_code(str(exc)), str(exc))
    except ApprovedChunksValidationError as exc:
        return _json_error(_approved_chunks_error_code(str(exc)), str(exc))
    except AliasSourceGuardError as exc:
        return _json_error("GUARD_VALIDATION_FAILED", str(exc))
    except ArtifactContractError as exc:
        return _json_error("OUTPUT_DIR_UNSAFE", str(exc))

    payload: dict[str, object] = {
        "harness_status": "PASS_DRY_VALIDATION_ONLY",
        "case_id": CASE_ID,
        "approved_chunks_count": len(chunks),
        "artifact_contract_ready": True,
        "dummy_artifacts_written": bool(artifacts),
        "artifacts_written": artifacts,
        "guard_status": guard_report["status"],
        "note": "No dossier generation, audit scoring, controlled regression, full Series B, baseline write, or production default retrieval was performed.",
        **EXECUTION_FALSE_FLAGS,
    }
    return 0, payload


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    code, payload = run(args)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
