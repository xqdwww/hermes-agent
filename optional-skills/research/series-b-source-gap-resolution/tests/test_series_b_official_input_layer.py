#!/usr/bin/env python3
"""Tests for the canonical Series B official input layer."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
OFFICIAL = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/official"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from series_b_official_input_layer import (
    OfficialInputLayerError,
    validate_frozen_ledger,
    validate_official_dataset,
    validate_source_state_manifest,
)


DATASET = OFFICIAL / "series_b_official_60case_dataset.json"
LEDGER = OFFICIAL / "series_b_frozen_baseline_ledger.json"
SOURCE_STATE = OFFICIAL / "series_b_source_state_manifest.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_canonical_dataset_has_exactly_60_cases_and_source_trace() -> None:
    validation = validate_official_dataset(DATASET)
    payload = _load(DATASET)
    assert validation["status"] == "PASS"
    assert validation["case_count"] == 60
    assert payload["classification"] == "CANONICAL_OFFICIAL_DATASET_V1"
    assert payload["controlled_evidence_rollup_used_as_dataset"] is False
    assert all(row.get("source_trace") for row in payload["cases"])


def test_controlled_evidence_rollup_cannot_be_dataset() -> None:
    payload = _load(DATASET)
    payload["controlled_evidence_rollup_used_as_dataset"] = True
    with tempfile.TemporaryDirectory() as tmpdir:
        bad = Path(tmpdir) / "bad_dataset.json"
        bad.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            validate_official_dataset(bad)
        except OfficialInputLayerError as exc:
            assert "controlled evidence rollup" in str(exc)
        else:
            raise AssertionError("controlled evidence rollup dataset was accepted")


def test_frozen_ledger_preserves_31_of_60_and_matches_dataset_cases() -> None:
    dataset_validation = validate_official_dataset(DATASET)
    ledger_validation = validate_frozen_ledger(LEDGER, dataset_validation["case_ids"])
    assert ledger_validation["status"] == "PASS"
    assert ledger_validation["official_baseline_score"] == "31/60"
    assert ledger_validation["passed_cases"] == 31
    assert ledger_validation["failed_cases"] == 29


def test_source_state_manifest_is_no_write_and_hash_checked() -> None:
    validation = validate_source_state_manifest(SOURCE_STATE)
    payload = _load(SOURCE_STATE)
    assert validation["status"] == "PASS"
    assert payload["official_write_enabled"] is False
    assert payload["production_default_enabled"] is False
    assert all(item.get("write_target") is False for item in payload["inputs"])


def run_tests() -> None:
    test_canonical_dataset_has_exactly_60_cases_and_source_trace()
    test_controlled_evidence_rollup_cannot_be_dataset()
    test_frozen_ledger_preserves_31_of_60_and_matches_dataset_cases()
    test_source_state_manifest_is_no_write_and_hash_checked()


if __name__ == "__main__":
    run_tests()
    print("series_b official input layer tests PASS")
