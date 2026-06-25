#!/usr/bin/env python3
"""Tests for the non-writing official candidate scoring adapter."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from series_b_official_candidate_comparator import compare_candidate_to_frozen, validate_comparison_schema
from series_b_official_candidate_inputs import CONTROLLED_EVIDENCE_CASES, resolve_official_candidate_inputs
from series_b_official_candidate_no_write_guard import OfficialCandidateGuardError
from series_b_official_candidate_scoring_adapter import (
    assess_scoring_readiness,
    build_fixture_candidate_payload,
    run_scoring_adapter,
)


def _present(path: Path) -> dict[str, object]:
    return {"status": "present", "path": str(path), "sha256": "fixture-sha"}


def _ready_input_discovery(tmp: Path) -> dict[str, object]:
    dataset = tmp / "dataset.json"
    source_state = tmp / "source_state.json"
    scorer = tmp / "safe_scorer.py"
    builder = tmp / "builder.py"
    ledger = tmp / "frozen_ledger.json"
    for path in (dataset, source_state, scorer, builder, ledger):
        path.write_text("{}\n", encoding="utf-8")
    return {
        "status": "OFFICIAL_CANDIDATE_INPUTS_READY",
        "missing_inputs": [],
        "partial_inputs": [],
        "inputs": {
            "official_dataset_path": _present(dataset),
            "official_dataset_hash": {"status": "present", "sha256": "fixture-dataset"},
            "source_state_manifest_path": _present(source_state),
            "source_state_manifest_hash": {"status": "present", "sha256": "fixture-source"},
            "scoring_audit_path": _present(scorer),
            "scoring_audit_hash": {"status": "present", "sha256": "fixture-scorer"},
            "builder_path": _present(builder),
            "builder_hash": {"status": "present", "sha256": "fixture-builder"},
            "frozen_baseline_ledger_path": _present(ledger),
            "frozen_baseline_score": "31/60",
        },
    }


def test_canonical_inputs_ready_path_with_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outdir:
        input_discovery = _ready_input_discovery(Path(tmpdir))
        fixture = build_fixture_candidate_payload(passed_cases=CONTROLLED_EVIDENCE_CASES)
        payload = run_scoring_adapter(
            input_discovery=input_discovery,
            output_dir=outdir,
            repo_root=REPO_ROOT,
            no_official_write=True,
            no_production_default=True,
            no_push=True,
            no_tag=True,
            fixture_candidate_payload=fixture,
        )
    assert payload["result_enum"] == "OFFICIAL_CANDIDATE_EXECUTION_PASS"
    assert payload["candidate_score"] == "12/60"
    assert payload["official_baseline_update_performed"] is False
    assert "official_score" not in payload


def test_canonical_inputs_partial_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        input_discovery = resolve_official_candidate_inputs(
            repo_path=REPO_ROOT,
            branch="travel-series-b-validation",
            head="d0da4933ffd5d85596967a02c0bed5598d767918",
            output_dir=tmp,
        )
        readiness = assess_scoring_readiness(input_discovery)
    assert readiness["status"] in {
        "OFFICIAL_CANDIDATE_SCORING_ADAPTER_INPUTS_PARTIAL",
        "OFFICIAL_CANDIDATE_INPUTS_BLOCKED",
        "OFFICIAL_CANDIDATE_INPUTS_READY",
    }
    if readiness["status"] != "OFFICIAL_CANDIDATE_INPUTS_READY":
        assert readiness["ready"] is False


def test_execute_candidate_blocked_if_inputs_partial() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        input_discovery = resolve_official_candidate_inputs(
            repo_path=REPO_ROOT,
            branch="travel-series-b-validation",
            head="d0da4933ffd5d85596967a02c0bed5598d767918",
            output_dir=tmp,
        )
        payload = run_scoring_adapter(
            input_discovery=input_discovery,
            output_dir=tmp,
            repo_root=REPO_ROOT,
            no_official_write=True,
            no_production_default=True,
            no_push=True,
            no_tag=True,
        )
    assert payload["result_enum"] in {
        "OFFICIAL_CANDIDATE_SCORING_ADAPTER_INPUTS_PARTIAL",
        "OFFICIAL_CANDIDATE_INPUTS_BLOCKED",
        "OFFICIAL_CANDIDATE_SAFE_RUNNER_NOT_AVAILABLE",
    }
    if payload["result_enum"] != "OFFICIAL_CANDIDATE_SAFE_RUNNER_NOT_AVAILABLE":
        assert payload["candidate_score"] is None


def test_execute_candidate_blocked_if_output_dir_inside_repo() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        input_discovery = _ready_input_discovery(Path(tmpdir))
        try:
            run_scoring_adapter(
                input_discovery=input_discovery,
                output_dir=REPO_ROOT / "candidate-output",
                repo_root=REPO_ROOT,
                no_official_write=True,
                no_production_default=True,
                no_push=True,
                no_tag=True,
                fixture_candidate_payload=build_fixture_candidate_payload(passed_cases=[]),
            )
        except OfficialCandidateGuardError as exc:
            assert exc.error_code == "OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL"
        else:
            raise AssertionError("expected repo-internal output dir to fail")


def test_execute_candidate_blocked_if_production_or_baseline_enabled() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outdir:
        input_discovery = _ready_input_discovery(Path(tmpdir))
        for kwargs in ({"no_production_default": False, "no_official_write": True}, {"no_production_default": True, "no_official_write": False}):
            try:
                run_scoring_adapter(
                    input_discovery=input_discovery,
                    output_dir=outdir,
                    repo_root=REPO_ROOT,
                    no_push=True,
                    no_tag=True,
                    fixture_candidate_payload=build_fixture_candidate_payload(passed_cases=[]),
                    **kwargs,
                )
            except OfficialCandidateGuardError as exc:
                assert exc.error_code in {"OFFICIAL_CANDIDATE_PRODUCTION_DEFAULT_RISK", "OFFICIAL_CANDIDATE_BASELINE_WRITE_RISK"}
            else:
                raise AssertionError("expected guard failure")


def test_candidate_score_cannot_be_labeled_official() -> None:
    payload = build_fixture_candidate_payload(passed_cases=CONTROLLED_EVIDENCE_CASES)
    payload["official_score"] = "12/60"
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outdir:
        result = run_scoring_adapter(
            input_discovery=_ready_input_discovery(Path(tmpdir)),
            output_dir=outdir,
            repo_root=REPO_ROOT,
            no_official_write=True,
            no_production_default=True,
            no_push=True,
            no_tag=True,
            fixture_candidate_payload=payload,
        )
        saved = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert "official_score" not in saved
    assert saved["candidate_score"] == "12/60"


def test_comparator_can_compare_candidate_vs_frozen_baseline_using_fixture() -> None:
    fixture = build_fixture_candidate_payload(passed_cases=CONTROLLED_EVIDENCE_CASES)
    comparison = compare_candidate_to_frozen(fixture, frozen_baseline="31/60")
    assert validate_comparison_schema(comparison)["status"] == "VALID"
    assert comparison["candidate_vs_frozen_summary"] == "candidate 12/60 vs frozen 31/60: -19 pass-count delta"


def run_tests() -> None:
    test_canonical_inputs_ready_path_with_fixture()
    test_canonical_inputs_partial_path()
    test_execute_candidate_blocked_if_inputs_partial()
    test_execute_candidate_blocked_if_output_dir_inside_repo()
    test_execute_candidate_blocked_if_production_or_baseline_enabled()
    test_candidate_score_cannot_be_labeled_official()
    test_comparator_can_compare_candidate_vs_frozen_baseline_using_fixture()


if __name__ == "__main__":
    run_tests()
    print("series_b official candidate scoring adapter tests PASS")
