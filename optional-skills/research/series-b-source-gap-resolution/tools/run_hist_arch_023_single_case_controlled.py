#!/usr/bin/env python3
"""Explicit-only hist_arch_023 single-case controlled harness."""

from __future__ import annotations

import argparse
import json
import sys
from json import JSONDecodeError
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from hist_arch_023_alias_source_guard import HistArch023GuardError, validate_chunks
from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_hist_arch_023_artifact_contract import (
    HistArch023ArtifactContractError,
    validate_hist_arch_023_artifact_contract,
)
from series_b_hist_arch_023_controlled_auditor import ControlledAuditError, audit_hist_arch_023_dossier
from series_b_hist_arch_023_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS
from series_b_hist_arch_023_source_grounded_builder import SourceGroundedBuilderError, build_hist_arch_023_dossier
from series_b_hist_arch_023_source_packet_exporter import (
    SourcePacketExportError,
    export_hist_arch_023_controlled_source_packet,
    validate_hist_arch_023_handoff_inputs,
)


REPO_ROOT = Path(__file__).resolve().parents[4]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or execute hist_arch_023 single-case controlled dry-run.")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--handoff-manifest", required=True)
    parser.add_argument("--approved-chunks", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--no-production-default", action="store_true", required=True)
    parser.add_argument("--no-baseline-update", action="store_true", required=True)
    parser.add_argument("--no-full-series-b", action="store_true", required=True)
    parser.add_argument("--execute-real-controlled-dry-run", action="store_true")
    return parser


def _result_enum_for_error(code: str) -> str:
    if code in {
        "BLOCKED_BINDING_INSUFFICIENT",
        "BLOCKED_GUARD_VIOLATION",
        "BLOCKED_PRODUCTION_DEFAULT_RISK",
        "BLOCKED_BASELINE_UPDATE_RISK",
        "BLOCKED_FULL_SERIES_B_RISK",
    }:
        return code
    if "PRODUCTION" in code:
        return "BLOCKED_PRODUCTION_DEFAULT_RISK"
    if "BASELINE" in code:
        return "BLOCKED_BASELINE_UPDATE_RISK"
    if "FULL_SERIES" in code:
        return "BLOCKED_FULL_SERIES_B_RISK"
    if "BINDING" in code or "LOCATOR" in code:
        return "BLOCKED_BINDING_INSUFFICIENT"
    if "GUARD" in code or "CONTAMINATION" in code or "CASE_ID" in code:
        return "BLOCKED_GUARD_VIOLATION"
    return "FAIL_CONTROLLED_REGRESSION"


def _error_payload(code: str, message: str) -> dict[str, object]:
    return {
        "status": "ERROR",
        "harness_status": "BLOCKED",
        "case_id": CASE_ID,
        "error_code": code,
        "message": message,
        "result_enum": _result_enum_for_error(code),
        "safe_to_retry": False,
        **EXECUTION_FALSE_FLAGS,
    }


def _json_error(code: str, message: str) -> tuple[int, dict[str, object]]:
    return 2, _error_payload(code, message)


def _load_json(path: str, *, kind: str) -> tuple[dict[str, object] | None, str | None]:
    target = Path(path).expanduser()
    if not target.exists():
        return None, f"{kind} path does not exist: {target}"
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        return None, f"{kind} is malformed JSON: {exc}"
    except OSError as exc:
        return None, f"{kind} cannot be read: {exc}"
    if not isinstance(payload, dict):
        return None, f"{kind} root must be a JSON object"
    return payload, None


def _validate_inputs(args: argparse.Namespace) -> tuple[dict[str, object], dict[str, object], Path]:
    if args.case_id != CASE_ID:
        raise ValueError("CASE_ID_MISMATCH: case id must be hist_arch_023")
    if not args.no_production_default:
        raise ValueError("BLOCKED_PRODUCTION_DEFAULT_RISK: --no-production-default is required")
    if not args.no_baseline_update:
        raise ValueError("BLOCKED_BASELINE_UPDATE_RISK: --no-baseline-update is required")
    if not args.no_full_series_b:
        raise ValueError("BLOCKED_FULL_SERIES_B_RISK: --no-full-series-b is required")
    output_dir = validate_output_dir_policy(args.output_dir, repo_root=REPO_ROOT)
    manifest, error = _load_json(args.handoff_manifest, kind="handoff manifest")
    if error:
        raise ValueError(f"HANDOFF_MANIFEST_MALFORMED: {error}")
    chunks_payload, error = _load_json(args.approved_chunks, kind="approved chunks")
    if error:
        raise ValueError(f"APPROVED_CHUNKS_MALFORMED: {error}")
    assert manifest is not None and chunks_payload is not None
    chunks, _context = validate_hist_arch_023_handoff_inputs(
        manifest=manifest,
        chunks_payload=chunks_payload,
        no_production_default=args.no_production_default,
        no_baseline_update=args.no_baseline_update,
        no_full_series_b=args.no_full_series_b,
    )
    validate_chunks(chunks)
    return manifest, chunks_payload, output_dir


def _write_manifest_used(output_dir: Path, manifest: dict[str, object]) -> str:
    path = output_dir / "hist_arch_023_controlled_manifest_used.json"
    path.write_text(
        json.dumps(
            {
                "case_id": CASE_ID,
                "controlled_real_mode": True,
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


def _execute(args: argparse.Namespace, *, manifest: dict[str, object], output_dir: Path) -> tuple[int, dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = [_write_manifest_used(output_dir, manifest)]
    try:
        source_packet = export_hist_arch_023_controlled_source_packet(
            case_id=args.case_id,
            approved_chunks_handoff_path=args.approved_chunks,
            controlled_handoff_manifest_path=args.handoff_manifest,
            output_dir=output_dir,
            no_production_default=args.no_production_default,
            no_baseline_update=args.no_baseline_update,
            no_full_series_b=args.no_full_series_b,
            repo_root=REPO_ROOT,
        )
        source_packet_path = source_packet["artifact_path"]
        artifacts.append(str(source_packet_path))
        builder = build_hist_arch_023_dossier(
            case_id=args.case_id,
            source_packet_path=source_packet_path,
            handoff_manifest_path=args.handoff_manifest,
            output_dir=output_dir,
        )
        raw_dossier_path = builder["artifact_path"]
        artifacts.append(str(raw_dossier_path))
        audit = audit_hist_arch_023_dossier(
            case_id=args.case_id,
            raw_dossier_path=raw_dossier_path,
            source_packet_path=source_packet_path,
            handoff_manifest_path=args.handoff_manifest,
            output_dir=output_dir,
        )
        contract = validate_hist_arch_023_artifact_contract(output_dir)
    except (SourcePacketExportError, SourceGroundedBuilderError, ControlledAuditError) as exc:
        return 2, _error_payload(getattr(exc, "error_code", "FAIL_CONTROLLED_REGRESSION"), str(exc))
    except HistArch023ArtifactContractError as exc:
        return 2, _error_payload("BLOCKED_GUARD_VIOLATION", str(exc))

    result = audit["result"]
    result_enum = result["result_enum"]
    if result_enum == "PASS_CONTROLLED_REGRESSION":
        harness_status = "PASS_SINGLE_CASE_CONTROLLED_DRY_RUN"
    elif result_enum == "PARTIAL_SOURCE_GUARDED_PASS":
        harness_status = "PARTIAL_SINGLE_CASE_CONTROLLED_DRY_RUN"
    elif str(result_enum).startswith("BLOCKED_"):
        harness_status = "BLOCKED_SINGLE_CASE_CONTROLLED_DRY_RUN"
    else:
        harness_status = "FAIL_SINGLE_CASE_CONTROLLED_DRY_RUN"
    payload = {
        "harness_status": harness_status,
        "case_id": CASE_ID,
        "source_packet_exporter_status": source_packet["status"],
        "builder_status": builder["status"],
        "audit_status": audit["status"],
        "artifact_contract_status": contract["status"],
        "result_enum": result_enum,
        "passed": result.get("passed") is True,
        "quality": result.get("quality"),
        "term_coverage": result.get("term_coverage"),
        "axis_coverage": result.get("axis_coverage"),
        "section_coverage": result.get("section_coverage"),
        "binding_caveat_preserved": result.get("binding_caveat_preserved"),
        "guard_result": result.get("guard_result"),
        "artifacts_written": artifacts,
        "single_case_controlled_dryrun_evidence": True,
        "note": "Single-case controlled dry-run evidence only; not an official Series B baseline improvement.",
        **EXECUTION_FALSE_FLAGS,
    }
    return (2 if str(result_enum).startswith("BLOCKED_") else 0), payload


def run(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    try:
        manifest, chunks_payload, output_dir = _validate_inputs(args)
    except ArtifactContractError as exc:
        return _json_error("OUTPUT_DIR_UNSAFE", str(exc))
    except (HistArch023GuardError, SourcePacketExportError) as exc:
        return _json_error(getattr(exc, "error_code", "BLOCKED_GUARD_VIOLATION"), str(exc))
    except ValueError as exc:
        message = str(exc)
        if ":" in message:
            code, detail = message.split(":", 1)
            return _json_error(code.strip(), detail.strip())
        return _json_error("FAIL_CONTROLLED_REGRESSION", message)
    if args.execute_real_controlled_dry_run:
        return _execute(args, manifest=manifest, output_dir=output_dir)
    return 0, {
        "harness_status": "PASS_DRY_VALIDATION_ONLY",
        "case_id": CASE_ID,
        "approved_primary_chunks_count": len(chunks_payload.get("approved_primary_chunks", [])),
        "context_or_alias_guard_chunks_count": len(chunks_payload.get("context_or_alias_guard_chunks", [])),
        "binding_caveat_preserved": True,
        "artifact_contract_ready": True,
        "note": "No controlled dry-run execution, full Series B, baseline write, or production default integration was performed.",
        **EXECUTION_FALSE_FLAGS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    code, payload = run(args)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
