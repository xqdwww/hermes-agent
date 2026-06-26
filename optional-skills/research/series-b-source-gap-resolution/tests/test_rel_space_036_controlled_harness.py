#!/usr/bin/env python3
"""Smoke and contract tests for the rel_space_036 controlled harness."""

from __future__ import annotations

import json, subprocess, sys, tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = SKILL_DIR / "tools"
for path in (str(SKILL_DIR), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from series_b_generic_controlled_harness import artifact_names, validate_artifact_contract

CASE_ID = "rel_space_036"
HANDOFF = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-rel-space-036-formal-handoff-batch/outputs/rel_space_036_controlled_handoff_manifest.json")
CHUNKS = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-rel-space-036-formal-handoff-batch/outputs/rel_space_036_approved_chunks_handoff.json")
RUNNER = TOOLS_DIR / "run_rel_space_036_single_case_controlled.py"

def _runner(args):
    completed = subprocess.run([sys.executable, "-B", str(RUNNER), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return completed, json.loads(completed.stdout)

def _base_args(out):
    return ["--case-id", CASE_ID, "--handoff-manifest", str(HANDOFF), "--approved-chunks", str(CHUNKS), "--output-dir", str(out), "--no-production-default", "--no-baseline-update", "--no-full-series-b"]

def run_tests():
    with tempfile.TemporaryDirectory(prefix="rel-space-036-harness-") as tmp_str:
        tmp=Path(tmp_str)
        completed,payload=_runner(_base_args(tmp/"dry"))
        assert completed.returncode == 0, payload
        assert payload["approved_chunks_count"] == 24
        completed,payload=_runner([*_base_args(tmp/"real"), "--execute-real-controlled-dry-run"])
        assert completed.returncode == 0, payload
        assert payload["result_enum"] == "PASS_CONTROLLED_REGRESSION"
        assert payload["term_coverage"]["Heaven"]["passed"] is True
        assert payload["term_coverage"]["altar"]["passed"] is True
        assert payload["axis_coverage"]["religion_book"] is True
        assert payload["axis_coverage"]["local_place"] is True
        assert payload["official_baseline_update_performed"] is False
        contract=validate_artifact_contract(tmp/"real", case_id=CASE_ID)
        assert contract["status"] == "PASS"
        for name in artifact_names(CASE_ID):
            assert (tmp/"real"/name).exists(), name

if __name__ == "__main__":
    run_tests()
    print("rel_space_036 controlled harness tests PASS")
