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
