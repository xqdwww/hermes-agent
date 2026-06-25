#!/usr/bin/env python3
"""Read-only input registry support for Series B official candidate runs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from series_b_official_candidate_no_write_guard import validate_output_dir


REGISTRY_SCHEMA_VERSION = "series_b_official_candidate_input_registry.v1"
HASH_MANIFEST_NAME = "series_b_official_candidate_input_hash_manifest.json"
REQUIRED_CANONICAL_ROLES = (
    "official_dataset_path",
    "source_state_manifest_path",
    "scoring_audit_path",
    "builder_path",
    "runner_path",
    "frozen_baseline_ledger_path",
    "frozen_ledger_comparison_schema",
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_status(repo_path: str | Path) -> dict[str, Any]:
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


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"registry JSON root must be an object: {target}")
    return payload


def _registry_hash_verification(registry_path: Path) -> dict[str, Any]:
    computed = sha256_file(registry_path)
    manifest_path = registry_path.parent / HASH_MANIFEST_NAME
    if not manifest_path.exists():
        return {
            "status": "REGISTRY_HASH_MANIFEST_MISSING",
            "registry_sha256": computed,
            "hash_manifest_path": str(manifest_path),
        }
    manifest = _load_json(manifest_path)
    expected = manifest.get("registry_sha256")
    return {
        "status": "PASS" if expected == computed else "REGISTRY_HASH_MISMATCH",
        "registry_sha256": computed,
        "expected_registry_sha256": expected,
        "hash_manifest_path": str(manifest_path),
    }


def _input_status(entry: dict[str, Any]) -> str:
    if entry.get("candidate_substitute_only") is True:
        return "partial"
    if entry.get("exists") is not True or entry.get("readable") is not True:
        return "missing"
    if entry.get("write_target") is True:
        return "blocked"
    if entry.get("safe_for_candidate_run") is not True:
        return "partial"
    return "present"


def _entry_to_input(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": _input_status(entry),
        "path": entry.get("path"),
        "sha256": entry.get("hash"),
        "source_of_truth": entry.get("source_of_truth"),
        "candidate_substitute_only": entry.get("candidate_substitute_only") is True,
        "official_vs_candidate_substitute": entry.get("official_vs_candidate_substitute"),
        "safe_for_candidate_run": entry.get("safe_for_candidate_run") is True,
        "notes": entry.get("notes"),
    }


def load_input_registry(path: str | Path) -> dict[str, Any]:
    registry_path = Path(path).expanduser().resolve(strict=False)
    if not registry_path.exists() or not registry_path.is_file():
        raise ValueError(f"input registry does not exist: {registry_path}")
    registry = _load_json(registry_path)
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ValueError(f"unsupported input registry schema: {registry.get('schema_version')}")
    registry["registry_path"] = str(registry_path)
    registry["registry_hash_verification"] = _registry_hash_verification(registry_path)
    return registry


def resolve_inputs_from_registry(
    *,
    registry_path: str | Path,
    repo_path: str | Path,
    branch: str,
    head: str,
    output_dir: str | Path,
    require_clean_repo: bool = True,
) -> dict[str, Any]:
    repo = Path(repo_path).expanduser().resolve(strict=False)
    target_output = validate_output_dir(output_dir, repo_root=repo)
    registry = load_input_registry(registry_path)
    current_status = _repo_status(repo)
    entries = {item.get("input_role"): item for item in registry.get("inputs", []) if isinstance(item, dict)}
    inputs: dict[str, Any] = {
        "candidate_run_id": registry.get("candidate_run_id") or "series_b_official_candidate_registry",
        "repo_path": str(repo),
        "branch": branch,
        "head": head,
        "repo_status": current_status,
        "candidate_output_directory": {"status": "present", "path": str(target_output)},
        "input_registry_path": {
            "status": "present",
            "path": registry["registry_path"],
            "sha256": registry["registry_hash_verification"].get("registry_sha256"),
        },
        "registry_hash_verification": registry["registry_hash_verification"],
    }
    for role, entry in entries.items():
        inputs[str(role)] = _entry_to_input(entry)

    missing = []
    partial = []
    blocked = []
    for role in REQUIRED_CANONICAL_ROLES:
        status = inputs.get(role, {"status": "missing"}).get("status")
        if status == "missing":
            missing.append(role)
        elif status == "partial":
            partial.append(role)
        elif status == "blocked":
            blocked.append(role)
    if registry["registry_hash_verification"]["status"] != "PASS":
        blocked.append("input_registry_hash")

    if require_clean_repo and not current_status["clean"]:
        result_enum = "OFFICIAL_CANDIDATE_REPO_DIRTY_BLOCKED"
    elif blocked:
        result_enum = "OFFICIAL_CANDIDATE_INPUTS_BLOCKED"
    elif missing or partial:
        result_enum = "OFFICIAL_CANDIDATE_INPUTS_PARTIAL"
    else:
        result_enum = "OFFICIAL_CANDIDATE_INPUTS_READY"

    return {
        "status": result_enum,
        "result_enum": result_enum,
        "inputs": inputs,
        "missing_inputs": sorted(set(missing)),
        "partial_inputs": sorted(set(partial)),
        "blocked_inputs": sorted(set(blocked)),
        "candidate_substitute_only_inputs": sorted(
            item.get("input_role")
            for item in registry.get("inputs", [])
            if isinstance(item, dict) and item.get("candidate_substitute_only") is True
        ),
        "official_candidate_execution_ready": result_enum == "OFFICIAL_CANDIDATE_INPUTS_READY",
        "canonical_input_discovery": {
            "controlled_evidence_rollup_used_as_official_dataset": registry.get("policy", {}).get(
                "controlled_evidence_rollup_used_as_official_dataset"
            )
            is True,
            "case_scoped_harness_used_as_official_scorer": registry.get("policy", {}).get(
                "case_scoped_harness_used_as_official_scorer"
            )
            is True,
            "registry_status": registry.get("registry_status"),
        },
        "official_baseline_update_performed": False,
        "full_series_b_run_performed": False,
        "production_default_manifest_integration_performed": False,
    }
