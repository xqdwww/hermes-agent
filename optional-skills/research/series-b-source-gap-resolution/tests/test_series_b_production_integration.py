#!/usr/bin/env python3
"""Integration contract tests for the explicit Series B production path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
PRODUCTION = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/production"
OFFICIAL = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/official"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from series_b_production_target_loader import load_explicit_production_target


def test_explicit_integration_artifact_is_series_b_scoped_only() -> None:
    payload = json.loads((PRODUCTION / "series_b_production_integration.json").read_text(encoding="utf-8"))
    assert payload["classification"] == "EXPLICIT_SERIES_B_PRODUCTION_INTEGRATION_PATH"
    assert payload["explicit_production_integration_enabled"] is True
    assert payload["production_default_scope"] == "explicit_series_b_target_only"
    assert payload["global_default_enabled"] is False
    assert payload["production_default_manifest_modified"] is False
    assert payload["write_targets"] == []


def test_explicit_integration_does_not_modify_official_baseline_artifacts() -> None:
    baseline = json.loads((OFFICIAL / "series_b_official_baseline_current.json").read_text(encoding="utf-8"))
    ledger = json.loads((OFFICIAL / "series_b_official_baseline_ledger.json").read_text(encoding="utf-8"))
    assert baseline["official_score"] == "58/60"
    assert baseline["prior_score"] == "56/60"
    assert baseline["production_default_integrated"] is False
    assert "31/60" in json.dumps(ledger)
    assert "39/60" in json.dumps(ledger)
    assert "44/60" in json.dumps(ledger)
    assert "50/60" in json.dumps(ledger)
    assert "55/60" in json.dumps(ledger)
    assert baseline["controlled_evidence_count"] == 31


def test_loader_exposes_integrated_read_only_config() -> None:
    loaded = load_explicit_production_target()
    validation = loaded["validation"]
    assert validation["production_target_layer_integrated"] is True
    assert validation["global_default_enabled"] is False
    assert validation["write_targets"] == []
    assert validation["vector_write_enabled"] is False
    assert validation["source_data_write_enabled"] is False
    assert validation["official_baseline_write_enabled"] is False


def run_tests() -> None:
    test_explicit_integration_artifact_is_series_b_scoped_only()
    test_explicit_integration_does_not_modify_official_baseline_artifacts()
    test_loader_exposes_integrated_read_only_config()


if __name__ == "__main__":
    run_tests()
    print("series_b production integration tests PASS")
