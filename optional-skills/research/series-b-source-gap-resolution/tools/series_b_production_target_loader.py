#!/usr/bin/env python3
"""Explicit Series B production target loader."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
SERIES_B_ROOT = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution"
DEFAULT_TARGET_MANIFEST = SERIES_B_ROOT / "production/series_b_production_target_manifest.json"
EXPECTED_LAYER_ID = "series_b_production_target_v1"
EXPECTED_SCHEMA_VERSION = "series_b_production_target_manifest.v1"
EXPECTED_CLASSIFICATION = "EXPLICIT_NON_DEFAULT_PRODUCTION_TARGET_LAYER"
EXPECTED_INTEGRATION_SCHEMA = "series_b_production_integration.v1"
EXPECTED_INTEGRATION_CLASSIFICATION = "EXPLICIT_SERIES_B_PRODUCTION_INTEGRATION_PATH"
EXPECTED_BASELINE = "39/60"
EXPECTED_SCOPE = "explicit_series_b_target_only"
REQUIRED_CAVEAT_CASES = {"obj_art_003", "obj_art_007", "nat_eco_039", "obj_art_010", "hist_arch_024"}


class ProductionTargetLayerError(ValueError):
    """Raised when the explicit production target layer is unsafe or invalid."""

    def __init__(self, error_code: str, message: str):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.message = message


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_INVALID_JSON", f"JSON root must be object: {target}")
    return payload


def _resolve_layer_path(raw: str | Path, *, manifest_path: Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve(strict=False)


def _repo_status(repo_path: str | Path = REPO_ROOT) -> dict[str, Any]:
    repo = Path(repo_path)
    status = subprocess.run(
        ["git", "status", "--short", "--branch", "-uall"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    diff = subprocess.run(["git", "diff", "--name-only"], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    cached = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    dirty_lines = [line for line in status.stdout.splitlines() if not line.startswith("##")]
    return {
        "status_short_branch": status.stdout.strip(),
        "tracked_diff": [line for line in diff.stdout.splitlines() if line.strip()],
        "staged_diff": [line for line in cached.stdout.splitlines() if line.strip()],
        "dirty_lines": dirty_lines,
        "clean": status.returncode == 0 and not dirty_lines and not diff.stdout.strip() and not cached.stdout.strip(),
    }


def _assert_false(payload: dict[str, Any], key: str, error_code: str) -> None:
    if payload.get(key) is not False:
        raise ProductionTargetLayerError(error_code, f"{key} must be false")


def _assert_true(payload: dict[str, Any], key: str, error_code: str) -> None:
    if payload.get(key) is not True:
        raise ProductionTargetLayerError(error_code, f"{key} must be true")


def _validate_no_write_policy(payload: dict[str, Any], *, context: str) -> None:
    _assert_false(payload, "vector_write_enabled", f"{context}_VECTOR_WRITE_RISK")
    _assert_false(payload, "source_data_write_enabled", f"{context}_SOURCE_WRITE_RISK")
    _assert_false(payload, "official_baseline_write_enabled", f"{context}_BASELINE_WRITE_RISK")
    if payload.get("write_targets") != []:
        raise ProductionTargetLayerError(f"{context}_WRITE_TARGET_RISK", "write_targets must be empty")


def validate_production_integration_manifest(integration_path: str | Path, *, target_manifest_path: str | Path) -> dict[str, Any]:
    path = Path(integration_path).expanduser().resolve(strict=False)
    if not path.exists() or not path.is_file():
        raise ProductionTargetLayerError("PRODUCTION_INTEGRATION_MANIFEST_MISSING", f"integration manifest missing: {path}")
    payload = load_json(path)
    if payload.get("schema_version") != EXPECTED_INTEGRATION_SCHEMA:
        raise ProductionTargetLayerError("PRODUCTION_INTEGRATION_SCHEMA_INVALID", "unsupported integration manifest schema")
    if payload.get("classification") != EXPECTED_INTEGRATION_CLASSIFICATION:
        raise ProductionTargetLayerError("PRODUCTION_INTEGRATION_CLASSIFICATION_INVALID", "unexpected integration classification")
    if payload.get("target_layer_id") != EXPECTED_LAYER_ID:
        raise ProductionTargetLayerError("PRODUCTION_INTEGRATION_TARGET_INVALID", "integration target_layer_id mismatch")
    _assert_true(payload, "explicit_production_integration_enabled", "PRODUCTION_INTEGRATION_NOT_ENABLED")
    if payload.get("production_default_scope") != EXPECTED_SCOPE:
        raise ProductionTargetLayerError("PRODUCTION_INTEGRATION_SCOPE_INVALID", "production default scope must be explicit_series_b_target_only")
    _assert_false(payload, "global_default_enabled", "PRODUCTION_INTEGRATION_GLOBAL_DEFAULT_RISK")
    _assert_false(payload, "production_default_enabled", "PRODUCTION_INTEGRATION_GLOBAL_DEFAULT_RISK")
    _assert_false(payload, "production_default_manifest_modified", "PRODUCTION_INTEGRATION_DEFAULT_MANIFEST_WRITE_RISK")
    _assert_false(payload, "production_vector_index_write_enabled", "PRODUCTION_INTEGRATION_VECTOR_WRITE_RISK")
    _assert_false(payload, "push_enabled", "PRODUCTION_INTEGRATION_PUSH_RISK")
    _assert_false(payload, "tag_enabled", "PRODUCTION_INTEGRATION_TAG_RISK")
    _assert_false(payload, "release_enabled", "PRODUCTION_INTEGRATION_RELEASE_RISK")
    _validate_no_write_policy(payload, context="PRODUCTION_INTEGRATION")
    if payload.get("official_baseline_ref") != EXPECTED_BASELINE:
        raise ProductionTargetLayerError("PRODUCTION_INTEGRATION_BASELINE_INVALID", "integration must reference 39/60 baseline")
    caveats = set(payload.get("caveat_cases") or [])
    if not REQUIRED_CAVEAT_CASES.issubset(caveats):
        raise ProductionTargetLayerError("PRODUCTION_INTEGRATION_CAVEAT_MISSING", "integration manifest missing required caveat cases")
    raw_target = payload.get("target_manifest_file")
    if not raw_target:
        raise ProductionTargetLayerError("PRODUCTION_INTEGRATION_TARGET_MISSING", "missing target_manifest_file")
    target_ref = _resolve_layer_path(raw_target, manifest_path=path)
    if target_ref != Path(target_manifest_path).expanduser().resolve(strict=False):
        raise ProductionTargetLayerError("PRODUCTION_INTEGRATION_TARGET_INVALID", "target_manifest_file does not match loaded target")
    return {
        "status": "PASS",
        "integration_manifest_path": str(path),
        "integration_manifest_sha256": sha256_file(path),
        "integration_id": payload.get("integration_id"),
        "explicit_production_integration_enabled": True,
        "production_target_layer_integrated": True,
        "production_default_scope": EXPECTED_SCOPE,
        "global_default_enabled": False,
        "production_default_manifest_modified": False,
        "write_targets": [],
        "vector_write_enabled": False,
        "source_data_write_enabled": False,
        "official_baseline_write_enabled": False,
        "release_ready": payload.get("release_ready") is True,
    }


def validate_production_target_manifest(manifest_path: str | Path = DEFAULT_TARGET_MANIFEST) -> dict[str, Any]:
    target = Path(manifest_path).expanduser().resolve(strict=False)
    if not target.exists() or not target.is_file():
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_NOT_FOUND", f"target manifest missing: {target}")
    manifest = load_json(target)
    if manifest.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_SCHEMA_INVALID", "unsupported production target schema")
    if manifest.get("layer_id") != EXPECTED_LAYER_ID:
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_ID_INVALID", "unexpected layer_id")
    if manifest.get("classification") != EXPECTED_CLASSIFICATION:
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_CLASSIFICATION_INVALID", "unexpected classification")
    if manifest.get("official_baseline_ref") != EXPECTED_BASELINE:
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_BASELINE_INVALID", "official baseline ref must be 39/60")

    _assert_false(manifest, "production_default_enabled", "PRODUCTION_TARGET_LAYER_DEFAULT_RISK")
    _assert_false(manifest, "global_default_enabled", "PRODUCTION_TARGET_LAYER_GLOBAL_DEFAULT_RISK")
    _assert_true(manifest, "requires_explicit_integration", "PRODUCTION_TARGET_LAYER_EXPLICIT_GATE_REQUIRED")
    _assert_false(manifest, "production_release_ready", "PRODUCTION_TARGET_LAYER_RELEASE_RISK")
    _assert_true(manifest, "release_requires_separate_authorization", "PRODUCTION_TARGET_LAYER_RELEASE_AUTH_REQUIRED")
    _assert_true(manifest, "explicit_production_integration_enabled", "PRODUCTION_TARGET_LAYER_INTEGRATION_NOT_ENABLED")
    if manifest.get("production_default_scope") != EXPECTED_SCOPE:
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_SCOPE_INVALID", "production default scope must be explicit_series_b_target_only")
    _validate_no_write_policy(manifest, context="PRODUCTION_TARGET_LAYER")
    _assert_true(manifest, "smoke_test_required", "PRODUCTION_TARGET_LAYER_SMOKE_REQUIRED")
    _assert_true(manifest, "full_series_b_required_before_release", "PRODUCTION_TARGET_LAYER_FULL_SERIES_B_GATE_REQUIRED")
    _assert_true(manifest, "push_tag_required_separate_authorization", "PRODUCTION_TARGET_LAYER_PUSH_TAG_GATE_REQUIRED")

    caveats = set(manifest.get("caveat_cases") or [])
    missing_caveats = sorted(REQUIRED_CAVEAT_CASES - caveats)
    if missing_caveats:
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_CAVEAT_MISSING", f"missing caveat cases: {missing_caveats}")

    resolved: dict[str, str] = {}
    for key in (
        "official_baseline_file",
        "official_baseline_ledger_file",
        "official_dataset_file",
        "source_state_manifest_file",
        "schema_file",
        "validator_file",
        "integration_manifest_file",
    ):
        raw = manifest.get(key)
        if not raw:
            raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_REFERENCE_MISSING", f"missing {key}")
        path = _resolve_layer_path(raw, manifest_path=target)
        if not path.exists():
            raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_REFERENCE_MISSING", f"referenced file missing: {key}={path}")
        resolved[key] = str(path)

    baseline = load_json(resolved["official_baseline_file"])
    if baseline.get("official_score") != "39/60" or baseline.get("case_count") != 60:
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_BASELINE_INVALID", "official baseline current must be 39/60 over 60 cases")
    if baseline.get("prior_score") != "31/60":
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_PRIOR_TRACE_MISSING", "official baseline current must retain prior 31/60 trace")
    if baseline.get("production_default_integrated") is not False:
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_DEFAULT_RISK", "baseline must not be marked production-default integrated")
    if not REQUIRED_CAVEAT_CASES.issubset(set(baseline.get("caveat_cases") or [])):
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_CAVEAT_MISSING", "baseline current missing required caveat cases")

    ledger = load_json(resolved["official_baseline_ledger_file"])
    ledger_entries = ledger.get("ledger_entries") or []
    if "31/60" not in json.dumps(ledger_entries) and ledger.get("prior_score") != "31/60":
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_PRIOR_TRACE_MISSING", "ledger must retain prior 31/60 trace")

    source_state = load_json(resolved["source_state_manifest_file"])
    if source_state.get("official_write_enabled") is not False or source_state.get("production_default_enabled") is not False:
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_SOURCE_STATE_WRITE_RISK", "source-state manifest must remain no-write and non-default")

    dataset = load_json(resolved["official_dataset_file"])
    if dataset.get("classification") != "CANONICAL_OFFICIAL_DATASET_V1" or dataset.get("case_count") != 60:
        raise ProductionTargetLayerError("PRODUCTION_TARGET_LAYER_DATASET_INVALID", "official dataset must be canonical 60-case dataset")

    integration = validate_production_integration_manifest(resolved["integration_manifest_file"], target_manifest_path=target)
    resolved_hashes = {key: sha256_file(value) for key, value in resolved.items() if Path(value).is_file()}
    return {
        "status": "PASS",
        "result_enum": "PRODUCTION_TARGET_LAYER_VALID",
        "manifest_path": str(target),
        "manifest_sha256": sha256_file(target),
        "layer_id": manifest["layer_id"],
        "official_baseline_ref": manifest["official_baseline_ref"],
        "production_default_enabled": False,
        "global_default_enabled": False,
        "requires_explicit_integration": True,
        "explicit_production_integration_enabled": True,
        "production_target_layer_integrated": True,
        "production_default_scope": EXPECTED_SCOPE,
        "write_targets": [],
        "vector_write_enabled": False,
        "source_data_write_enabled": False,
        "official_baseline_write_enabled": False,
        "release_ready": False,
        "caveat_cases": sorted(caveats),
        "resolved_paths": resolved,
        "resolved_hashes": resolved_hashes,
        "integration": integration,
        "repo_status": _repo_status(),
    }


def load_explicit_production_target(manifest_path: str | Path = DEFAULT_TARGET_MANIFEST) -> dict[str, Any]:
    """Load and validate the explicit Series B production target layer."""

    validation = validate_production_target_manifest(manifest_path)
    manifest = load_json(validation["manifest_path"])
    integration = load_json(validation["resolved_paths"]["integration_manifest_file"])
    return {"manifest": manifest, "integration": integration, "validation": validation}
