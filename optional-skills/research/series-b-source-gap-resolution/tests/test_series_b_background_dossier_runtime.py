#!/usr/bin/env python3
"""Tests for the explicit Series B background dossier runtime."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
PRODUCTION_TARGET = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/production/series_b_production_target_manifest.json"
RUNNER = TOOLS / "run_series_b_background_dossier.py"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from series_b_background_dossier_runtime import run_background_dossier


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-B", str(RUNNER), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _safe_flags(tmp: str) -> list[str]:
    return [
        "--production-target",
        str(PRODUCTION_TARGET),
        "--background-dossier-only",
        "--no-itinerary",
        "--no-source-write",
        "--no-vector-write",
        "--no-official-baseline-write",
        "--output-dir",
        tmp,
    ]


def test_cli_help() -> None:
    proc = _run(["--help"])
    assert proc.returncode == 0
    assert "--production-target" in proc.stdout
    assert "--background-dossier-only" in proc.stdout
    assert "--execute" in proc.stdout


def test_explicit_production_target_required() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--query", "东京亲子背景", "--execute", "--output-dir", tmp, "--background-dossier-only", "--no-itinerary", "--no-source-write", "--no-vector-write", "--no-official-baseline-write"])
        assert proc.returncode != 0
        assert "production-target" in proc.stderr


def test_repo_internal_output_dir_rejected() -> None:
    proc = _run(["--query", "东京亲子背景", "--execute", *_safe_flags(str(REPO_ROOT / "runtime-output"))])
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["result_enum"] == "SERIES_B_BACKGROUND_DOSSIER_OUTPUT_DIR_INSIDE_REPO"


def test_no_write_flags_required() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--query", "东京亲子背景", "--execute", "--production-target", str(PRODUCTION_TARGET), "--background-dossier-only", "--no-itinerary", "--output-dir", tmp])
        assert proc.returncode != 0
        payload = json.loads(proc.stdout)
        assert payload["result_enum"] == "SERIES_B_BACKGROUND_DOSSIER_SOURCE_WRITE_RISK"


def test_background_only_and_no_itinerary_required() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--query", "东京亲子背景", "--execute", "--production-target", str(PRODUCTION_TARGET), "--no-source-write", "--no-vector-write", "--no-official-baseline-write", "--output-dir", tmp])
        assert proc.returncode != 0
        payload = json.loads(proc.stdout)
        assert payload["result_enum"] == "SERIES_B_BACKGROUND_DOSSIER_BACKGROUND_ONLY_REQUIRED"


def test_dry_run_plan_only_works() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        status, payload = run_background_dossier(
            query="为东京亲子旅行生成背景知识",
            production_target=PRODUCTION_TARGET,
            output_dir=tmp,
            no_source_write=True,
            no_vector_write=True,
            no_official_baseline_write=True,
            background_dossier_only=True,
            no_itinerary=True,
            dry_run_plan_only=True,
            execute=False,
        )
        assert status == 0, payload
        assert payload["result_enum"] == "SERIES_B_BACKGROUND_DOSSIER_DRY_RUN_PLAN_PASS"
        assert payload["production_target_id"] == "series_b_production_target_v1"
        assert payload["official_baseline_current"] == "60/60"
        assert (Path(tmp) / "series_b_background_dossier_plan.json").exists()


def test_execute_generates_background_dossier() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        status, payload = run_background_dossier(
            query="为北疆自驾旅行生成一个背景知识 dossier，重点覆盖自然地理、民族文化、历史层次、区域关系、食物和主题线索。",
            production_target=PRODUCTION_TARGET,
            output_dir=tmp,
            no_source_write=True,
            no_vector_write=True,
            no_official_baseline_write=True,
            background_dossier_only=True,
            no_itinerary=True,
            dry_run_plan_only=False,
            execute=True,
        )
        assert status == 0, payload
        assert payload["result_enum"] == "SERIES_B_BACKGROUND_DOSSIER_EXECUTION_PASS"
        assert payload["production_target_loaded"] is True
        assert payload["official_baseline_current"] == "60/60"
        assert payload["guard"]["itinerary_listing_contamination"] is False
        dossier = Path(tmp) / "series_b_background_dossier.md"
        assert dossier.exists()
        text = dossier.read_text()
        for heading in ["## Culture", "## History", "## Nature And Geography", "## Regional Relations", "## Food Culture", "## Theme Tracks"]:
            assert heading in text
        assert "hotel" not in text.lower()
        assert "booking" not in text.lower()
        assert payload["official_baseline_modified"] is False
        assert payload["source_vector_mutation_performed"] is False


def run_tests() -> None:
    test_cli_help()
    test_explicit_production_target_required()
    test_repo_internal_output_dir_rejected()
    test_no_write_flags_required()
    test_background_only_and_no_itinerary_required()
    test_dry_run_plan_only_works()
    test_execute_generates_background_dossier()


if __name__ == "__main__":
    run_tests()
    print("series_b background dossier runtime tests PASS")
