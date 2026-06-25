#!/usr/bin/env python3
"""Contract tests for the non-writing Series B official candidate runner."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
RUNNER = TOOLS / "run_series_b_official_candidate.py"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from series_b_official_candidate_comparator import build_empty_comparison, validate_comparison_schema


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(RUNNER), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _guard_args(tmp: str) -> list[str]:
    return ["--no-official-write", "--no-production-default", "--no-push", "--no-tag", "--output-dir", tmp]


def test_runner_help() -> None:
    proc = _run(["--help"])
    assert proc.returncode == 0
    assert "--discover-only" in proc.stdout
    assert "--execute-candidate" in proc.stdout


def test_discover_only_writes_repo_external_artifact() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--discover-only", *_guard_args(tmp)])
        assert proc.returncode == 0, proc.stderr + proc.stdout
        payload = json.loads(proc.stdout)
        assert payload["result_enum"] == "OFFICIAL_CANDIDATE_DISCOVER_ONLY_PASS"
        assert payload["official_baseline_update_performed"] is False
        assert (Path(tmp) / "series_b_official_candidate_discover_only.json").exists()


def test_verify_inputs_only_reports_partial_inputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--verify-inputs-only", *_guard_args(tmp)])
        assert proc.returncode == 0, proc.stderr + proc.stdout
        payload = json.loads(proc.stdout)
        assert payload["result_enum"] == "OFFICIAL_CANDIDATE_VERIFY_INPUTS_PASS"
        assert payload["inputs_status"] in {"OFFICIAL_CANDIDATE_INPUTS_PARTIAL", "OFFICIAL_CANDIDATE_REPO_DIRTY_BLOCKED"}
        if payload["inputs_status"] == "OFFICIAL_CANDIDATE_INPUTS_PARTIAL":
            assert "official_dataset_path" in payload["missing_inputs"]


def test_dry_run_plan_only_writes_plan_without_execution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--dry-run-plan-only", *_guard_args(tmp)])
        assert proc.returncode == 0, proc.stderr + proc.stdout
        payload = json.loads(proc.stdout)
        assert payload["result_enum"] == "OFFICIAL_CANDIDATE_DRY_RUN_PLAN_PASS"
        assert payload["candidate_execution_plan"]["execute_candidate_available"] in {False, True}
        assert payload["controlled_regression_execution_performed"] is False
        assert (Path(tmp) / "series_b_official_candidate_dry_run_plan.json").exists()


def test_execute_candidate_blocks_when_inputs_partial_or_repo_dirty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--execute-candidate", *_guard_args(tmp)])
        assert proc.returncode != 0
        payload = json.loads(proc.stdout)
        assert payload["result_enum"] in {
            "OFFICIAL_CANDIDATE_SCORING_ADAPTER_INPUTS_PARTIAL",
            "OFFICIAL_CANDIDATE_INPUTS_BLOCKED",
            "OFFICIAL_CANDIDATE_SAFE_RUNNER_NOT_AVAILABLE",
        }
        assert payload["official_baseline_update_performed"] is False
        assert payload.get("candidate_score") is None
        assert "official_score" not in payload


def test_execute_candidate_blocks_inside_repo_output() -> None:
    proc = _run(["--execute-candidate", *_guard_args(str(REPO_ROOT / "candidate-output"))])
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["result_enum"] == "OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL"


def test_comparator_schema_valid() -> None:
    payload = build_empty_comparison(reason="unit test")
    assert validate_comparison_schema(payload)["status"] == "VALID"
    assert payload["case_deltas"][0]["controlled_evidence_classification"] == "CONTROLLED_DRY_RUN_EVIDENCE_ONLY"


def run_tests() -> None:
    test_runner_help()
    test_discover_only_writes_repo_external_artifact()
    test_verify_inputs_only_reports_partial_inputs()
    test_dry_run_plan_only_writes_plan_without_execution()
    test_execute_candidate_blocks_when_inputs_partial_or_repo_dirty()
    test_execute_candidate_blocks_inside_repo_output()
    test_comparator_schema_valid()


if __name__ == "__main__":
    run_tests()
    print("series_b official candidate runner contracts tests PASS")
