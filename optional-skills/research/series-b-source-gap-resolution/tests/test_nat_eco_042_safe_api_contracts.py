#!/usr/bin/env python3
"""Safe API tests for the nat_eco_042 controlled harness."""

from __future__ import annotations

import json, subprocess, sys, tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = SKILL_DIR / "tools"
for path in (str(SKILL_DIR), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from nat_eco_042_alias_source_guard import check_text
from series_b_generic_controlled_harness import CASE_CONFIGS, RESULT_ENUMS

CASE_ID = "nat_eco_042"
HANDOFF = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-nat-eco-042-formal-handoff-batch/outputs/nat_eco_042_controlled_handoff_manifest.json")
CHUNKS = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-nat-eco-042-formal-handoff-batch/outputs/nat_eco_042_approved_chunks_handoff.json")
RUNNER = TOOLS_DIR / "run_nat_eco_042_single_case_controlled.py"

def _runner(args):
    completed = subprocess.run([sys.executable, "-B", str(RUNNER), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return completed, json.loads(completed.stdout)

def _base_args(out):
    return ["--case-id", CASE_ID, "--handoff-manifest", str(HANDOFF), "--approved-chunks", str(CHUNKS), "--output-dir", str(out), "--no-production-default", "--no-baseline-update", "--no-full-series-b"]

def run_tests():
    assert "PASS_CONTROLLED_REGRESSION" in RESULT_ENUMS
    assert CASE_CONFIGS[CASE_ID].case_id == CASE_ID
    assert "listing_or_planning" in check_text(f"{CASE_ID} ticket booking")
    assert check_text(f"{CASE_ID} mangrove Avicennia pneumatophore vivipary intertidal") == []
    with tempfile.TemporaryDirectory(prefix="nat-eco-042-contracts-") as tmp_str:
        tmp=Path(tmp_str)
        completed,payload=_runner(_base_args(tmp/"dry"))
        assert completed.returncode == 0, payload
        completed,payload=_runner(["--case-id", "cross_route_053", "--handoff-manifest", str(HANDOFF), "--approved-chunks", str(CHUNKS), "--output-dir", str(tmp/"bad"), "--no-production-default", "--no-baseline-update", "--no-full-series-b"])
        assert completed.returncode == 2
        assert payload["error_code"] == "CASE_ID_MISMATCH"
        completed=subprocess.run([sys.executable, "-B", str(RUNNER), "--help"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        assert completed.returncode == 0
        assert "--execute-real-controlled-dry-run" in completed.stdout

if __name__ == "__main__":
    run_tests()
    print("nat_eco_042 safe API contracts tests PASS")
