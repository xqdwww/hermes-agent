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
    validate_production_target_manifest,
)


def _load_manifest() -> dict:
    return json.loads(DEFAULT_TARGET_MANIFEST.read_text(encoding="utf-8"))




def test_target_layer_loads_explicitly_and_is_not_default() -> None:
    loaded = load_explicit_production_target(DEFAULT_TARGET_MANIFEST)
    validation = loaded["validation"]
    assert validation["status"] == "PASS"
    assert validation["layer_id"] == "series_b_production_target_v1"
    assert validation["production_default_enabled"] is False
    assert validation["requires_explicit_integration"] is True


def test_write_targets_empty_and_source_vector_writes_disabled() -> None:
    validation = validate_production_target_manifest(DEFAULT_TARGET_MANIFEST)
    assert validation["write_targets"] == []
    assert validation["vector_write_enabled"] is False
    assert validation["source_data_write_enabled"] is False
    assert validation["official_baseline_write_enabled"] is False


def test_official_baseline_39_and_prior_31_retained() -> None:
    validation = validate_production_target_manifest(DEFAULT_TARGET_MANIFEST)
    baseline = json.loads(Path(validation["resolved_paths"]["official_baseline_file"]).read_text(encoding="utf-8"))
    assert baseline["official_score"] == "39/60"
    assert baseline["prior_score"] == "31/60"
    assert baseline["production_default_integrated"] is False


def test_caveat_cases_preserved() -> None:
    validation = validate_production_target_manifest(DEFAULT_TARGET_MANIFEST)
    required = {"obj_art_003", "obj_art_007", "nat_eco_039", "obj_art_010", "hist_arch_024"}
    assert required.issubset(set(validation["caveat_cases"]))


def test_loader_rejects_malformed_default_enabled_target() -> None:
    manifest = _load_manifest()
    manifest["production_default_enabled"] = True
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            validate_production_target_manifest(path)
        except ProductionTargetLayerError as exc:
            assert exc.error_code == "PRODUCTION_TARGET_LAYER_DEFAULT_RISK"
        else:
            raise AssertionError("production_default_enabled=true target was accepted")


def test_readiness_checker_reports_non_integrated_ready_state() -> None:
    report = build_readiness_report(DEFAULT_TARGET_MANIFEST)
    assert report["status"] == "PASS"
    assert report["production_default_enabled"] is False
    assert report["production_default_manifest_integration_performed"] is False
    assert report["production_readiness_verdict"] == "READY_WITH_FULL_SERIES_B_SMOKE_REQUIRED"


def run_tests() -> None:
    test_target_layer_loads_explicitly_and_is_not_default()
    test_write_targets_empty_and_source_vector_writes_disabled()
    test_official_baseline_39_and_prior_31_retained()
    test_caveat_cases_preserved()
    test_loader_rejects_malformed_default_enabled_target()
    test_readiness_checker_reports_non_integrated_ready_state()


if __name__ == "__main__":
    run_tests()
    print("series_b production target loader tests PASS")
