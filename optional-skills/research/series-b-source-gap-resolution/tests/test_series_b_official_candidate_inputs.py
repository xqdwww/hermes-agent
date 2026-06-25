#!/usr/bin/env python3
"""Tests for Series B official candidate input discovery."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from series_b_official_candidate_inputs import (
    CONTROLLED_EVIDENCE_CASES,
    discover_existing_primitives,
    repo_status,
    resolve_official_candidate_inputs,
)
from series_b_official_candidate_no_write_guard import OfficialCandidateGuardError


def test_repo_clean_required() -> None:
    status = repo_status(REPO_ROOT)
    assert "clean" in status
    assert "dirty_lines" in status


def test_missing_inputs_are_structured_not_guessed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        payload = resolve_official_candidate_inputs(
            repo_path=REPO_ROOT,
            branch="travel-series-b-validation",
            head="9875797bcd69ecc4af3137ea996c8fff3793cdb3",
            output_dir=tmp,
        )
    assert payload["status"] in {"OFFICIAL_CANDIDATE_INPUTS_PARTIAL", "OFFICIAL_CANDIDATE_REPO_DIRTY_BLOCKED"}
    assert "official_dataset_path" in payload["missing_inputs"]
    assert "source_state_manifest_path" in payload["missing_inputs"]
    assert "scoring_audit_path" in payload["missing_inputs"]
    assert payload["inputs"]["official_dataset_path"]["path"] is None
    assert payload["inputs"]["source_state_manifest_path"]["path"] is None


def test_output_dir_must_be_repo_external() -> None:
    try:
        resolve_official_candidate_inputs(
            repo_path=REPO_ROOT,
            branch="travel-series-b-validation",
            head="9875797bcd69ecc4af3137ea996c8fff3793cdb3",
            output_dir=REPO_ROOT / "tmp_candidate_output",
        )
    except OfficialCandidateGuardError as exc:
        assert exc.error_code == "OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL"
    else:
        raise AssertionError("expected repo-internal output_dir to fail")


def test_prior_evidence_classification_not_promoted() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        payload = resolve_official_candidate_inputs(
            repo_path=REPO_ROOT,
            branch="travel-series-b-validation",
            head="9875797bcd69ecc4af3137ea996c8fff3793cdb3",
            output_dir=tmp,
        )
    assert payload["inputs"]["controlled_evidence_classification"] == "CONTROLLED_DRY_RUN_EVIDENCE_ONLY"
    assert payload["inputs"]["controlled_evidence_cases"] == CONTROLLED_EVIDENCE_CASES


def test_primitive_discovery_classifies_case_harnesses_as_case_scoped_only() -> None:
    payload = discover_existing_primitives(REPO_ROOT)
    assert any("run_cross_route_054_single_case_controlled.py" in item for item in payload["case_scoped_only"])
    assert "batch_runner.py" in payload["unsafe_write_capable"]


def run_tests() -> None:
    test_repo_clean_required()
    test_missing_inputs_are_structured_not_guessed()
    test_output_dir_must_be_repo_external()
    test_prior_evidence_classification_not_promoted()
    test_primitive_discovery_classifies_case_harnesses_as_case_scoped_only()


if __name__ == "__main__":
    run_tests()
    print("series_b official candidate inputs tests PASS")
