#!/usr/bin/env python3
"""Input discovery for non-writing Series B official candidate runs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_official_candidate_no_write_guard import validate_output_dir


RESULT_ENUMS = {
    "OFFICIAL_CANDIDATE_INPUTS_READY",
    "OFFICIAL_CANDIDATE_INPUTS_PARTIAL",
    "OFFICIAL_CANDIDATE_INPUTS_BLOCKED",
    "OFFICIAL_CANDIDATE_DISCOVER_ONLY_PASS",
    "OFFICIAL_CANDIDATE_VERIFY_INPUTS_PASS",
    "OFFICIAL_CANDIDATE_DRY_RUN_PLAN_PASS",
    "SAFE_CANDIDATE_EXECUTION_NOT_IMPLEMENTED",
    "OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL",
    "OFFICIAL_CANDIDATE_REPO_DIRTY_BLOCKED",
    "OFFICIAL_CANDIDATE_PRODUCTION_DEFAULT_RISK",
    "OFFICIAL_CANDIDATE_BASELINE_WRITE_RISK",
}

CONTROLLED_EVIDENCE_CASES = [
    "nat_eco_039",
    "obj_art_010",
    "hist_arch_024",
    "rel_space_029",
    "obj_art_003",
    "nat_eco_041",
    "hist_arch_023",
    "cross_route_052",
    "nat_eco_047",
    "rel_space_030",
    "obj_art_007",
    "cross_route_054",
]

REPRO_PACKAGE_DIR = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-official-reproducibility-package/outputs"
)
FINAL_SEAL_DIR = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-12case-final-seal-audit/outputs"
)
ROLLUP_12_DIR = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-12case-controlled-evidence-rollup/outputs"
)
LEGACY_BASE = Path("/Users/xqdwww/Documents/Codex/2026-06-22/post-lineage-series-b-controlled-re/outputs")
DATASET_HASH_TRACE = "9fdf5bd38b3ceedc802e74ce9f3a03336e82bde1c3f8a878321a9864fe93436e"
BUILDER_HASH_TRACE = "2a5fb9284d1897a51881de4f6929876fc2e9e57218c3658ab008576c036aa61b"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def file_identity(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "missing", "path": None, "sha256": None}
    target = Path(path)
    if not target.exists() or not target.is_file():
        return {"status": "missing", "path": str(target), "sha256": None}
    return {
        "status": "present",
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "sha256": sha256_file(target),
    }


def repo_status(repo_path: str | Path) -> dict[str, Any]:
    repo = Path(repo_path)
    status = subprocess.run(
        ["git", "status", "--short", "--branch", "-uall"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    diff = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    cached = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    dirty_lines = [line for line in status.stdout.splitlines() if not line.startswith("##")]
    return {
        "status_returncode": status.returncode,
        "status_short_branch": status.stdout.strip(),
        "tracked_diff": [line for line in diff.stdout.splitlines() if line.strip()],
        "staged_diff": [line for line in cached.stdout.splitlines() if line.strip()],
        "dirty_lines": dirty_lines,
        "clean": status.returncode == 0 and not dirty_lines and not diff.stdout.strip() and not cached.stdout.strip(),
    }


def _present(path: Path, role: str) -> dict[str, Any]:
    identity = file_identity(path)
    identity["role"] = role
    return identity


def discover_existing_primitives(repo_path: str | Path) -> dict[str, Any]:
    repo = Path(repo_path)
    optional_root = repo / "optional-skills/research/series-b-source-gap-resolution"
    case_runners = sorted(str(path.relative_to(repo)) for path in (optional_root / "tools").glob("run_*_single_case_controlled.py"))
    controlled_helpers = sorted(
        str(path.relative_to(repo))
        for path in (optional_root / "tools").glob("series_b_*")
        if path.suffix == ".py" and "official_candidate" not in path.name
    )
    return {
        "safe_to_reuse_readonly": [
            str((optional_root / "controlled-regression-cases.json").relative_to(repo)),
            str((optional_root / "CONTROLLED_REGRESSION_HANDOFF.md").relative_to(repo)),
            str((optional_root / "SERIES_B_SOURCE_MANIFEST_VNEXT_SCHEMA.md").relative_to(repo)),
        ],
        "case_scoped_only": case_runners + controlled_helpers,
        "unsafe_write_capable": ["batch_runner.py", "mini_swe_runner.py", "tools/task_engine_runner.py", "tools/research_pipeline_runner.py"],
        "production_default_related": [
            "optional-skills/research/series-b-source-gap-resolution/series_b_source_manifest_vnext_schema.json",
            "optional-skills/research/series-b-source-gap-resolution/APPROVED_SOURCE_MANIFEST_SCHEMA.md",
        ],
        "unknown_do_not_call": ["agent/background_review.py", "tools/task_engine_executors.py"],
    }


def resolve_official_candidate_inputs(
    *,
    repo_path: str | Path,
    branch: str,
    head: str,
    output_dir: str | Path,
    require_clean_repo: bool = True,
) -> dict[str, Any]:
    repo = Path(repo_path).expanduser().resolve(strict=False)
    target_output = validate_output_dir(output_dir, repo_root=repo)
    runner_path = Path(__file__).resolve().parent / "run_series_b_official_candidate.py"
    comparator_path = Path(__file__).resolve().parent / "series_b_official_candidate_comparator.py"
    no_write_guard_path = Path(__file__).resolve().parent / "series_b_official_candidate_no_write_guard.py"
    current_status = repo_status(repo)

    package = load_json(REPRO_PACKAGE_DIR / "series_b_official_reproducibility_package.json")
    seal = load_json(FINAL_SEAL_DIR / "series_b_12case_final_seal_audit.json")
    rollup = load_json(ROLLUP_12_DIR / "series_b_12case_controlled_evidence_rollup.json")
    closeout = load_json(LEGACY_BASE / "series_b_final_closeout_no_baseline_update/series_b_final_closeout.json")

    inputs = {
        "candidate_run_id": f"series_b_official_candidate_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "repo_path": str(repo),
        "branch": branch,
        "head": head,
        "repo_status": current_status,
        "official_dataset_path": {"status": "missing", "path": None, "sha256": None},
        "official_dataset_hash": {
            "status": "partial",
            "sha256": closeout.get("phase3e_run_b", {}).get("dataset_hash") or DATASET_HASH_TRACE,
            "note": "hash trace exists, but canonical official dataset path is not available",
        },
        "source_state_manifest_path": {"status": "missing", "path": None, "sha256": None},
        "source_state_manifest_hash": {"status": "missing", "sha256": None},
        "scoring_audit_path": {"status": "missing", "path": None, "sha256": None},
        "scoring_audit_hash": {"status": "missing", "sha256": None},
        "builder_path": {"status": "partial", "path": None, "sha256": BUILDER_HASH_TRACE},
        "builder_hash": {"status": "partial", "sha256": BUILDER_HASH_TRACE},
        "runner_path": file_identity(runner_path),
        "runner_hash": {"status": "present" if runner_path.exists() else "missing", "sha256": sha256_file(runner_path) if runner_path.exists() else None},
        "comparator_path": file_identity(comparator_path),
        "no_write_guard_path": file_identity(no_write_guard_path),
        "frozen_baseline_ledger_path": _present(
            LEGACY_BASE / "series_b_query_bundle_controlled/query_bundle_final_metrics.json",
            "frozen_31_60_trace",
        ),
        "frozen_baseline_score": "31/60",
        "twelve_case_controlled_evidence_rollup_path": _present(
            ROLLUP_12_DIR / "series_b_12case_controlled_evidence_rollup.json",
            "controlled_evidence_rollup",
        ),
        "final_seal_audit_path": _present(FINAL_SEAL_DIR / "series_b_12case_final_seal_audit.json", "final_seal_audit"),
        "candidate_output_directory": {"status": "present", "path": str(target_output)},
        "controlled_evidence_case_count": 12,
        "controlled_evidence_cases": CONTROLLED_EVIDENCE_CASES,
        "controlled_evidence_classification": package.get("final_classification") or rollup.get("all_evidence_classification"),
        "final_seal_status": seal.get("series_b_12case_final_seal_audit_status"),
        "rollup_status": rollup.get("rollup_status"),
    }

    missing_required = [
        key
        for key in (
            "official_dataset_path",
            "source_state_manifest_path",
            "scoring_audit_path",
        )
        if inputs[key]["status"] == "missing"
    ]
    partial_required = [
        key
        for key in (
            "official_dataset_hash",
            "builder_path",
            "builder_hash",
            "frozen_baseline_ledger_path",
        )
        if inputs[key]["status"] == "partial"
    ]
    if require_clean_repo and not current_status["clean"]:
        result_enum = "OFFICIAL_CANDIDATE_REPO_DIRTY_BLOCKED"
    elif missing_required:
        result_enum = "OFFICIAL_CANDIDATE_INPUTS_PARTIAL"
    elif partial_required:
        result_enum = "OFFICIAL_CANDIDATE_INPUTS_PARTIAL"
    else:
        result_enum = "OFFICIAL_CANDIDATE_INPUTS_READY"

    return {
        "status": result_enum,
        "result_enum": result_enum,
        "inputs": inputs,
        "missing_inputs": missing_required,
        "partial_inputs": partial_required,
        "official_candidate_execution_ready": result_enum == "OFFICIAL_CANDIDATE_INPUTS_READY",
        "official_baseline_update_performed": False,
        "full_series_b_run_performed": False,
        "production_default_manifest_integration_performed": False,
    }
