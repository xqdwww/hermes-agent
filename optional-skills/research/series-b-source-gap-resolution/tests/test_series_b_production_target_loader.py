#!/usr/bin/env python3
"""Tests for the explicit Series B production target loader."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
PRODUCTION = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/production"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from series_b_production_readiness_check import build_readiness_report
from series_b_production_target_loader import (
    DEFAULT_TARGET_MANIFEST,
    ProductionTargetLayerError,
    load_explicit_production_target,
    validate_production_integration_manifest,
    validate_production_target_manifest,
)


def _load_manifest() -> dict:
    return json.loads(DEFAULT_TARGET_MANIFEST.read_text(encoding="utf-8"))


def test_target_layer_loads_explicitly_and_is_integrated_without_global_default() -> None:
    loaded = load_explicit_production_target(DEFAULT_TARGET_MANIFEST)
    validation = loaded["validation"]
    assert validation["status"] == "PASS"
    assert validation["layer_id"] == "series_b_production_target_v1"
    assert validation["production_target_layer_integrated"] is True
    assert validation["explicit_production_integration_enabled"] is True
    assert validation["production_default_scope"] == "explicit_series_b_target_only"
    assert validation["production_default_enabled"] is False
    assert validation["global_default_enabled"] is False


def test_write_targets_empty_and_source_vector_writes_disabled() -> None:
    validation = validate_production_target_manifest(DEFAULT_TARGET_MANIFEST)
    assert validation["write_targets"] == []
    assert validation["vector_write_enabled"] is False
    assert validation["source_data_write_enabled"] is False
    assert validation["official_baseline_write_enabled"] is False


def test_official_baseline_50_and_prior_traces_retained() -> None:
    validation = validate_production_target_manifest(DEFAULT_TARGET_MANIFEST)
    baseline = json.loads(Path(validation["resolved_paths"]["official_baseline_file"]).read_text(encoding="utf-8"))
    assert baseline["official_score"] == "50/60"
    assert baseline["prior_score"] == "44/60"
    assert baseline["production_default_integrated"] is False
    assert baseline["controlled_evidence_count"] == 23


def test_caveat_cases_preserved() -> None:
    validation = validate_production_target_manifest(DEFAULT_TARGET_MANIFEST)
    required = {
        "obj_art_003",
        "obj_art_007",
        "nat_eco_039",
        "obj_art_010",
        "hist_arch_024",
        "nat_eco_046",
        "nat_eco_043",
        "obj_art_005",
        "obj_art_011",
        "hist_arch_025",
        "rel_space_036",
    }
    assert required.issubset(set(validation["caveat_cases"]))


def test_loader_rejects_malformed_global_default_target() -> None:
    manifest = _load_manifest()
    manifest["global_default_enabled"] = True
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            validate_production_target_manifest(path)
        except ProductionTargetLayerError as exc:
            assert exc.error_code == "PRODUCTION_TARGET_LAYER_GLOBAL_DEFAULT_RISK"
        else:
            raise AssertionError("global_default_enabled=true target was accepted")


def test_integration_manifest_rejects_write_targets() -> None:
    validation = validate_production_target_manifest(DEFAULT_TARGET_MANIFEST)
    integration = json.loads(Path(validation["resolved_paths"]["integration_manifest_file"]).read_text(encoding="utf-8"))
    integration["write_targets"] = ["production/default.json"]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "integration.json"
        path.write_text(json.dumps(integration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            validate_production_integration_manifest(path, target_manifest_path=DEFAULT_TARGET_MANIFEST)
        except ProductionTargetLayerError as exc:
            assert exc.error_code == "PRODUCTION_INTEGRATION_WRITE_TARGET_RISK"
        else:
            raise AssertionError("integration write_targets were accepted")


def test_readiness_checker_reports_integrated_not_released_state() -> None:
    report = build_readiness_report(DEFAULT_TARGET_MANIFEST)
    assert report["status"] == "PASS"
    assert report["production_target_layer_integrated"] is True
    assert report["production_default_scope"] == "explicit_series_b_target_only"
    assert report["production_default_enabled"] is False
    assert report["production_default_manifest_integration_performed"] is False
    assert report["production_readiness_verdict"] == "READY_WITH_FULL_SERIES_B_SMOKE_REQUIRED"


def run_tests() -> None:
    test_target_layer_loads_explicitly_and_is_integrated_without_global_default()
    test_write_targets_empty_and_source_vector_writes_disabled()
    test_official_baseline_50_and_prior_traces_retained()
    test_caveat_cases_preserved()
    test_loader_rejects_malformed_global_default_target()
    test_integration_manifest_rejects_write_targets()
    test_readiness_checker_reports_integrated_not_released_state()


if __name__ == "__main__":
    run_tests()
    print("series_b production target loader tests PASS")
