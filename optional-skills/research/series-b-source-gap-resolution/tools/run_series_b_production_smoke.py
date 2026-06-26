#!/usr/bin/env python3
"""Non-mutating Series B production target smoke helper."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_production_readiness_check import build_readiness_report
from series_b_production_target_loader import DEFAULT_TARGET_MANIFEST, ProductionTargetLayerError, load_explicit_production_target, sha256_file

REPO_ROOT = Path(__file__).resolve().parents[4]
RESULT_PASS = "PRODUCTION_SMOKE_DRY_RUN_PASS"
RESULT_BLOCKED = "PRODUCTION_SMOKE_DRY_RUN_BLOCKED"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _repo_status() -> dict[str, Any]:
    status = subprocess.run(["git", "status", "--short", "--branch", "-uall"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    diff = subprocess.run(["git", "diff", "--name-only"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    cached = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    dirty_lines = [line for line in status.stdout.splitlines() if not line.startswith("##")]
    return {
        "status_short_branch": status.stdout.strip(),
        "tracked_diff": [line for line in diff.stdout.splitlines() if line.strip()],
        "staged_diff": [line for line in cached.stdout.splitlines() if line.strip()],
        "dirty_lines": dirty_lines,
        "clean": status.returncode == 0 and not dirty_lines and not diff.stdout.strip() and not cached.stdout.strip(),
    }


def _validate_output_dir(path: str | Path) -> Path:
    target = Path(path).expanduser().resolve(strict=False)
    if _is_relative_to(target, REPO_ROOT):
        raise ProductionTargetLayerError("PRODUCTION_SMOKE_OUTPUT_DIR_INSIDE_REPO", "smoke output_dir must be outside the travel repo")
    lowered = str(target).lower()
    forbidden = ("production_default", "production-vector", "production_vector", "source_raw", "official_baseline_current.json")
    if any(marker in lowered for marker in forbidden):
        raise ProductionTargetLayerError("PRODUCTION_SMOKE_OUTPUT_DIR_WRITE_RISK", f"smoke output_dir contains write-risk marker: {target}")
    return target


def _sensitive_hashes(resolved_paths: dict[str, str]) -> dict[str, str]:
    keys = [
        "official_baseline_file",
        "official_baseline_ledger_file",
        "official_dataset_file",
        "source_state_manifest_file",
        "schema_file",
        "validator_file",
    ]
    return {key: sha256_file(resolved_paths[key]) for key in keys if key in resolved_paths and Path(resolved_paths[key]).is_file()}


def _dry_run_one_case(resolved_paths: dict[str, str]) -> dict[str, Any]:
    dataset_path = Path(resolved_paths["official_dataset_file"])
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = dataset.get("cases") or []
    sample = cases[0] if cases else {}
    return {
        "status": "PASS",
        "mode": "metadata_only_no_dossier_generation",
        "case_id": sample.get("case_id"),
        "dataset_path": str(dataset_path),
        "dataset_case_count": dataset.get("case_count"),
        "dossier_generated": False,
        "retrieval_executed": False,
        "production_default_written": False,
    }


def run_smoke(
    *,
    manifest_path: str | Path,
    output_dir: str | Path,
    check_baseline: bool,
    check_manifest: bool,
    check_loader: bool,
    dry_run_one_case: bool,
    check_no_mutation: bool,
    no_production_default_write: bool,
    no_vector_write: bool,
    no_source_write: bool,
) -> tuple[int, dict[str, Any]]:
    try:
        if not no_production_default_write:
            raise ProductionTargetLayerError("PRODUCTION_SMOKE_DEFAULT_WRITE_RISK", "--no-production-default-write is required")
        if not no_vector_write:
            raise ProductionTargetLayerError("PRODUCTION_SMOKE_VECTOR_WRITE_RISK", "--no-vector-write is required")
        if not no_source_write:
            raise ProductionTargetLayerError("PRODUCTION_SMOKE_SOURCE_WRITE_RISK", "--no-source-write is required")
        target_output = _validate_output_dir(output_dir)
        target_output.mkdir(parents=True, exist_ok=True)
        before_status = _repo_status()
        loaded = load_explicit_production_target(manifest_path)
        validation = loaded["validation"]
        before_hashes = _sensitive_hashes(validation["resolved_paths"])
        checks: dict[str, Any] = {}
        if check_manifest:
            checks["manifest"] = {"status": "PASS", "layer_id": validation["layer_id"], "manifest_path": validation["manifest_path"]}
        if check_loader:
            checks["loader"] = {"status": "PASS", "resolved_config_read_only": True, "write_targets": validation["write_targets"]}
        if check_baseline:
            checks["baseline"] = {"status": "PASS", "official_baseline_current": validation["official_baseline_ref"]}
        if dry_run_one_case:
            checks["dry_run_one_case"] = _dry_run_one_case(validation["resolved_paths"])
        readiness = build_readiness_report(manifest_path)
        after_hashes = _sensitive_hashes(validation["resolved_paths"])
        after_status = _repo_status()
        no_mutation = before_hashes == after_hashes and before_status == after_status
        if check_no_mutation and not no_mutation:
            raise ProductionTargetLayerError("PRODUCTION_SMOKE_NO_MUTATION_FAIL", "pre/post repo status or sensitive hashes changed")
        payload = {
            "status": "PASS",
            "result_enum": RESULT_PASS,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "manifest_path": validation["manifest_path"],
            "output_dir": str(target_output),
            "checks": checks,
            "readiness": readiness,
            "no_mutation_check": "PASS" if no_mutation else "FAIL",
            "pre_hashes": before_hashes,
            "post_hashes": after_hashes,
            "pre_repo_status": before_status,
            "post_repo_status": after_status,
            "production_default_manifest_integration_performed": False,
            "official_baseline_modified": False,
            "full_series_b_run_performed": False,
            "push_performed": False,
            "tag_created": False,
        }
        (target_output / "series_b_production_smoke_dry_run.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (target_output / "series_b_production_smoke_dry_run.md").write_text(
            "# Series B Production Smoke Dry Run\n\n"
            f"result: `{payload['result_enum']}`\n\n"
            f"official_baseline_current: `{validation['official_baseline_ref']}`\n\n"
            f"no_mutation_check: `{payload['no_mutation_check']}`\n\n"
            "production_default_manifest_integration_performed: false\n"
            "official_baseline_modified: false\n"
            "full_series_b_run_performed: false\n",
            encoding="utf-8",
        )
        return 0, payload
    except ProductionTargetLayerError as exc:
        payload = {
            "status": "BLOCKED",
            "result_enum": exc.error_code if exc.error_code else RESULT_BLOCKED,
            "message": exc.message,
            "production_default_manifest_integration_performed": False,
            "official_baseline_modified": False,
            "full_series_b_run_performed": False,
            "push_performed": False,
            "tag_created": False,
        }
        try:
            target_output = _validate_output_dir(output_dir)
            target_output.mkdir(parents=True, exist_ok=True)
            (target_output / "series_b_production_smoke_dry_run.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except Exception:
            pass
        return 2, payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Non-mutating smoke helper for explicit Series B production target layer.")
    parser.add_argument("--target-manifest", default=str(DEFAULT_TARGET_MANIFEST))
    parser.add_argument("--check-baseline", action="store_true")
    parser.add_argument("--check-manifest", action="store_true")
    parser.add_argument("--check-loader", action="store_true")
    parser.add_argument("--dry-run-one-case", action="store_true")
    parser.add_argument("--check-no-mutation", action="store_true")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--no-production-default-write", action="store_true")
    parser.add_argument("--no-vector-write", action="store_true")
    parser.add_argument("--no-source-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    status, payload = run_smoke(
        manifest_path=args.target_manifest,
        output_dir=args.output_dir,
        check_baseline=args.check_baseline,
        check_manifest=args.check_manifest,
        check_loader=args.check_loader,
        dry_run_one_case=args.dry_run_one_case,
        check_no_mutation=args.check_no_mutation,
        no_production_default_write=args.no_production_default_write,
        no_vector_write=args.no_vector_write,
        no_source_write=args.no_source_write,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
