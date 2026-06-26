#!/usr/bin/env python3
"""Tests for dedicated full non-destructive Series B sanity runner."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
RUNNER = TOOLS / "run_series_b_full_non_destructive_sanity.py"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from series_b_full_sanity_runner import run_full_sanity


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-B", str(RUNNER), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _guard_args(tmp: str) -> list[str]:
    return ["--no-source-write", "--no-vector-write", "--no-official-baseline-write", "--no-push", "--no-tag", "--output-dir", tmp]


def test_cli_help() -> None:
    proc = _run(["--help"])
    assert proc.returncode == 0
    assert "--check-60case-dataset" in proc.stdout
    assert "--dry-run-60case-plan" in proc.stdout
    assert "--no-official-baseline-write" in proc.stdout


def test_runner_refuses_repo_internal_output_dir() -> None:
    proc = _run(["--check-baseline", *_guard_args(str(REPO_ROOT / "sanity-output"))])
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["result_enum"] == "FULL_SANITY_OUTPUT_DIR_INSIDE_REPO"


def test_runner_requires_no_write_flags() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--check-baseline", "--output-dir", tmp])
        assert proc.returncode != 0
        payload = json.loads(proc.stdout)
        assert payload["result_enum"] == "FULL_SANITY_SOURCE_WRITE_RISK"


def test_full_non_destructive_sanity_passes_with_all_checks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        status, payload = run_full_sanity(
            output_dir=tmp,
            check_baseline_flag=True,
            check_production_target_flag=True,
            check_60case_dataset_flag=True,
            check_12case_trace_flag=True,
            dry_run_one_case_flag=True,
            dry_run_60case_plan_flag=True,
            check_no_mutation_flag=True,
            no_source_write=True,
            no_vector_write=True,
            no_official_baseline_write=True,
            no_push=True,
            no_tag=True,
            require_clean_repo=False,
        )
        assert status == 0, payload
        assert payload["result_enum"] == "FULL_NON_DESTRUCTIVE_SANITY_PASS"
        assert payload["official_baseline_current"] == "50/60"
        assert payload["dataset_60case_check"] == "PASS"
        assert payload["trace_12case_check"] == "PASS"
        assert payload["one_case_dry_run"] == "PASS"
        assert payload["plan_60case_traversal"] == "PASS"
        assert payload["mutation_guard_result"] == "FULL_NON_DESTRUCTIVE_MUTATION_GUARD_PASS"
        assert payload["source_vector_mutation_performed"] is False
        assert payload["push_performed"] is False
        assert payload["tag_created"] is False
        assert (Path(tmp) / "series_b_full_nondestructive_60case_plan.json").exists()


def test_cli_writes_repo_external_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run([
            "--check-baseline",
            "--check-production-target",
            "--check-60case-dataset",
            "--check-12case-trace",
            "--dry-run-one-case",
            "--dry-run-60case-plan",
            "--check-no-mutation",
            *_guard_args(tmp),
        ])
        payload = json.loads(proc.stdout)
        if proc.returncode == 0:
            assert payload["result_enum"] == "FULL_NON_DESTRUCTIVE_SANITY_PASS"
            assert (Path(tmp) / "series_b_full_nondestructive_sanity_run.json").exists()
        else:
            assert payload["result_enum"] == "FULL_SANITY_REPO_DIRTY_PRE"
            assert payload["official_baseline_modified"] is False


def run_tests() -> None:
    test_cli_help()
    test_runner_refuses_repo_internal_output_dir()
    test_runner_requires_no_write_flags()
    test_full_non_destructive_sanity_passes_with_all_checks()
    test_cli_writes_repo_external_artifacts()


if __name__ == "__main__":
    run_tests()
    print("series_b full non-destructive sanity tests PASS")
