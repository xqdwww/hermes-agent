#!/usr/bin/env python3
"""Smoke and contract tests for the hist_arch_020 controlled harness."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = SKILL_DIR / "tools"
for path in (str(SKILL_DIR), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from series_b_generic_controlled_harness import artifact_names, validate_artifact_contract

CASE_ID = "hist_arch_020"
HANDOFF = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-hist-arch-020-formal-handoff-batch/outputs/hist_arch_020_controlled_handoff_manifest.json")
CHUNKS = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-hist-arch-020-formal-handoff-batch/outputs/hist_arch_020_approved_chunks_handoff.json")
RUNNER = TOOLS_DIR / "run_hist_arch_020_single_case_controlled.py"


def _runner(args: list[str]) -> tuple[subprocess.CompletedProcess[str], dict]:
    completed = subprocess.run([sys.executable, "-B", str(RUNNER), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"runner stdout was not JSON: {completed.stdout}\nstderr: {completed.stderr}") from exc
    return completed, payload


def _base_args(output_dir: Path) -> list[str]:
    return ["--case-id", CASE_ID, "--handoff-manifest", str(HANDOFF), "--approved-chunks", str(CHUNKS), "--output-dir", str(output_dir), "--no-production-default", "--no-baseline-update", "--no-full-series-b"]


def run_tests() -> None:
    with tempfile.TemporaryDirectory(prefix="hist-arch-020-harness-") as tmp_str:
        tmp = Path(tmp_str)
        completed, payload = _runner(_base_args(tmp / "dry"))
        assert completed.returncode == 0, payload
        assert payload["harness_status"] == "PASS_DRY_VALIDATION_ONLY"
        assert payload["approved_chunks_count"] == 18

        completed, payload = _runner([*_base_args(tmp / "real"), "--execute-real-controlled-dry-run"])
        assert completed.returncode == 0, payload
        assert payload["harness_status"] == "PASS_SINGLE_CASE_CONTROLLED_DRY_RUN"
        assert payload["result_enum"] == "PASS_CONTROLLED_REGRESSION"
        assert payload["quality"]["level"] == "rich"
        assert payload["term_coverage"]["Cerveteri"]["passed"] is True
        assert payload["term_coverage"]["Banditaccia"]["passed"] is True
        assert payload["term_coverage"]["tumulus"]["passed"] is True
        contract = validate_artifact_contract(tmp / "real", case_id=CASE_ID)
        assert contract["status"] == "PASS"
        for name in artifact_names(CASE_ID):
            assert (tmp / "real" / name).exists(), name


if __name__ == "__main__":
    run_tests()
    print("hist_arch_020 controlled harness tests PASS")
