#!/usr/bin/env python3
"""Tests for the non-mutating Series B production smoke helper."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
RUNNER = TOOLS / "run_series_b_production_smoke.py"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_series_b_production_smoke import run_smoke


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-B", str(RUNNER), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _guard_args(tmp: str) -> list[str]:
    return ["--no-vector-write", "--no-source-write", "--output-dir", tmp]


def test_smoke_helper_help() -> None:
    proc = _run(["--help"])
    assert proc.returncode == 0
    assert "--check-baseline" in proc.stdout
    assert "--check-no-mutation" in proc.stdout


def test_smoke_helper_refuses_repo_internal_output_dir() -> None:
    proc = _run(["--check-baseline", *_guard_args(str(REPO_ROOT / "smoke-output"))])
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["result_enum"] == "PRODUCTION_SMOKE_OUTPUT_DIR_INSIDE_REPO"


def test_smoke_helper_requires_vector_source_no_write_flags() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--check-baseline", "--output-dir", tmp])
        assert proc.returncode != 0
        payload = json.loads(proc.stdout)
        assert payload["result_enum"] == "PRODUCTION_SMOKE_VECTOR_WRITE_RISK"


def test_smoke_helper_no_mutation_mode_works() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        status, payload = run_smoke(
            manifest_path=TOOLS.parent / "production/series_b_production_target_manifest.json",
            output_dir=tmp,
            check_baseline=True,
            check_manifest=True,
            check_loader=True,
            dry_run_one_case=True,
            check_no_mutation=True,
            no_production_default_write=False,
            no_vector_write=True,
            no_source_write=True,
        )
        assert status == 0, payload
        assert payload["result_enum"] == "PRODUCTION_SMOKE_TEST_PASS"
        assert payload["no_mutation_check"] == "PASS"
        assert payload["production_target_layer_integrated"] is True
        assert payload["production_default_scope"] == "explicit_series_b_target_only"
        assert payload["production_default_manifest_integration_performed"] is False
        assert payload["official_baseline_modified"] is False
        assert payload["source_vector_mutation_performed"] is False
        assert payload["checks"]["baseline"]["official_baseline_current"] == "39/60"
        assert payload["checks"]["dry_run_one_case"]["dossier_generated"] is False


def test_cli_smoke_writes_repo_external_artifact() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run([
            "--check-baseline",
            "--check-manifest",
            "--check-loader",
            "--dry-run-one-case",
            "--check-no-mutation",
            *_guard_args(tmp),
        ])
        assert proc.returncode == 0, proc.stderr + proc.stdout
        payload = json.loads(proc.stdout)
        assert payload["result_enum"] == "PRODUCTION_SMOKE_TEST_PASS"
        assert (Path(tmp) / "series_b_production_smoke_test.json").exists()


def run_tests() -> None:
    test_smoke_helper_help()
    test_smoke_helper_refuses_repo_internal_output_dir()
    test_smoke_helper_requires_vector_source_no_write_flags()
    test_smoke_helper_no_mutation_mode_works()
    test_cli_smoke_writes_repo_external_artifact()


if __name__ == "__main__":
    run_tests()
    print("series_b production smoke tests PASS")
