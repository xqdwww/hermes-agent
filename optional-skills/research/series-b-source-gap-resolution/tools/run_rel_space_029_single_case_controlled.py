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


def _blocked_payload(result_enum: str, error: str) -> dict[str, object]:
    return {
        "harness_status": "BLOCKED",
        "case_id": CASE_ID,
        "result_enum": result_enum,
        "error": error,
        **EXECUTION_FALSE_FLAGS,
    }


def run(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    if args.case_id != CASE_ID:
        return 2, _blocked_payload("BLOCKED_REPO_PATCH_REQUIRED", "case id must be rel_space_029")
    if not args.no_production_default:
        return 2, _blocked_payload(
            "BLOCKED_PRODUCTION_DEFAULT_RISK", "--no-production-default is required"
        )
    if not args.no_baseline_update:
        return 2, _blocked_payload(
            "BLOCKED_BASELINE_UPDATE_RISK", "--no-baseline-update is required"
        )
    if not args.no_full_series_b:
        return 2, _blocked_payload("BLOCKED_FULL_SERIES_B_RISK", "--no-full-series-b is required")

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
        return 2, _blocked_payload("BLOCKED_REPO_PATCH_REQUIRED", str(exc))
    except ApprovedChunksValidationError as exc:
        return 2, _blocked_payload("BLOCKED_REPO_PATCH_REQUIRED", str(exc))
    except AliasSourceGuardError as exc:
        return 2, _blocked_payload("BLOCKED_GUARD_VIOLATION", str(exc))
    except ArtifactContractError as exc:
        return 2, _blocked_payload("BLOCKED_REPO_PATCH_REQUIRED", str(exc))

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
