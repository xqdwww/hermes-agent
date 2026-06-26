#!/usr/bin/env python3
"""Tests for candidate-only Series B official scoring audit."""

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

from series_b_official_scoring_audit import (
    OfficialScoringAuditError,
    build_candidate_delta,
    load_controlled_evidence_matrix,
    run_candidate_scoring,
)


DATASET = OFFICIAL / "series_b_official_60case_dataset.json"
LEDGER = OFFICIAL / "series_b_frozen_baseline_ledger.json"
MATRIX = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/"
    "travel-series-b-12case-final-seal-audit/outputs/series_b_12case_final_case_matrix.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_controlled_matrix_must_remain_evidence_only() -> None:
    validation = load_controlled_evidence_matrix(MATRIX)
    assert validation["status"] == "PASS"
    assert validation["controlled_case_count"] == 12


def test_candidate_delta_is_candidate_only_and_not_official_score() -> None:
    payload = build_candidate_delta(
        dataset_path=DATASET,
        frozen_ledger_path=LEDGER,
        controlled_evidence_matrix_path=MATRIX,
    )
    assert payload["result_enum"] == "OFFICIAL_CANDIDATE_EXECUTION_PASS"
    assert payload["candidate_score"] == "39/60"
    assert payload["old_frozen_baseline"] == "31/60"
    assert payload["classification"] == "CANDIDATE_ONLY_NO_BASELINE_WRITE"
    assert "official_score" not in payload
    assert payload["official_baseline_update_performed"] is False
    assert payload["production_default_manifest_integration_performed"] is False


def test_candidate_scoring_writes_only_repo_external_candidate_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        payload = run_candidate_scoring(
            dataset_path=DATASET,
            frozen_ledger_path=LEDGER,
            controlled_evidence_matrix_path=MATRIX,
            output_dir=tmpdir,
            repo_root=REPO_ROOT,
            no_official_write=True,
            no_production_default=True,
            no_push=True,
            no_tag=True,
        )
        output_manifest = Path(payload["output_manifest_path"])
        assert output_manifest.exists()
        assert REPO_ROOT not in output_manifest.resolve().parents
        assert payload["guard"]["status"] == "PASS"
        assert payload["official_baseline_update_performed"] is False


def test_scoring_fails_closed_if_matrix_claims_official_score_improvement() -> None:
    matrix = _load(MATRIX)
    matrix["cases"][0]["official_score_improvement"] = True
    with tempfile.TemporaryDirectory() as tmpdir:
        bad = Path(tmpdir) / "bad_matrix.json"
        bad.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            load_controlled_evidence_matrix(bad)
        except OfficialScoringAuditError as exc:
            assert "official score improvement" in str(exc)
        else:
            raise AssertionError("official-score-improvement matrix was accepted")


def run_tests() -> None:
    test_controlled_matrix_must_remain_evidence_only()
    test_candidate_delta_is_candidate_only_and_not_official_score()
    test_candidate_scoring_writes_only_repo_external_candidate_artifacts()
    test_scoring_fails_closed_if_matrix_claims_official_score_improvement()


if __name__ == "__main__":
    run_tests()
    print("series_b official scoring audit tests PASS")
