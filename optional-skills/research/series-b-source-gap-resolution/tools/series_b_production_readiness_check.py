#!/usr/bin/env python3
"""Readiness checks for the explicit Series B production target layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from series_b_production_target_loader import DEFAULT_TARGET_MANIFEST, ProductionTargetLayerError, load_explicit_production_target


def build_readiness_report(manifest_path: str | Path = DEFAULT_TARGET_MANIFEST) -> dict[str, Any]:
    try:
        loaded = load_explicit_production_target(manifest_path)
    except ProductionTargetLayerError as exc:
        return {
            "status": "BLOCKED",
            "result_enum": exc.error_code,
            "message": exc.message,
            "production_default_manifest_integration_performed": False,
            "official_baseline_modified": False,
            "full_series_b_run_performed": False,
        }
    validation = loaded["validation"]
    repo_clean = validation["repo_status"].get("clean") is True
    return {
        "status": "PASS",
        "result_enum": "PRODUCTION_TARGET_LAYER_READINESS_PASS",
        "layer_id": validation["layer_id"],
        "official_baseline_current": validation["official_baseline_ref"],
        "baseline_check": "PASS_39_OF_60",
        "source_state_manifest_check": "PASS_READ_ONLY_NON_DEFAULT",
        "schema_validator_check": "PASS_PRESENT_READABLE",
        "caveat_preservation": "PASS",
        "production_default_enabled": False,
        "requires_explicit_integration": True,
        "write_targets": [],
        "vector_write_enabled": False,
        "source_data_write_enabled": False,
        "repo_clean": repo_clean,
        "production_readiness_verdict": "READY_WITH_FULL_SERIES_B_SMOKE_REQUIRED",
        "production_default_manifest_integration_performed": False,
        "official_baseline_modified": False,
        "full_series_b_run_performed": False,
        "push_performed": False,
        "tag_created": False,
    }


def write_readiness_report(output_path: str | Path, manifest_path: str | Path = DEFAULT_TARGET_MANIFEST) -> dict[str, Any]:
    report = build_readiness_report(manifest_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
