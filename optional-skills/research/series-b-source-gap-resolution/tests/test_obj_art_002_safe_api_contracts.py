#!/usr/bin/env python3
"""Safe API tests for the obj_art_002 controlled harness."""

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

from obj_art_002_alias_source_guard import check_text
from series_b_generic_controlled_harness import CASE_CONFIGS, RESULT_ENUMS

CASE_ID = "obj_art_002"
HANDOFF = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-obj-art-002-formal-handoff-batch/outputs/obj_art_002_controlled_handoff_manifest.json")
CHUNKS = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-obj-art-002-formal-handoff-batch/outputs/obj_art_002_approved_chunks_handoff.json")
RUNNER = TOOLS_DIR / "run_obj_art_002_single_case_controlled.py"


def _runner(args: list[str]) -> tuple[subprocess.CompletedProcess[str], dict]:
    completed = subprocess.run([sys.executable, "-B", str(RUNNER), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return completed, json.loads(completed.stdout)


def _base_args(output_dir: Path) -> list[str]:
    return ["--case-id", CASE_ID, "--handoff-manifest", str(HANDOFF), "--approved-chunks", str(CHUNKS), "--output-dir", str(output_dir), "--no-production-default", "--no-baseline-update", "--no-full-series-b"]


def run_tests() -> None:
    assert "PASS_CONTROLLED_REGRESSION" in RESULT_ENUMS
    assert CASE_CONFIGS[CASE_ID].case_id == CASE_ID
    assert "listing_or_planning" in check_text(f"{CASE_ID} ticket booking")
    assert check_text(f"{CASE_ID} Jian ware Tenmoku glaze iron firing oil_spot") == []
    with tempfile.TemporaryDirectory(prefix="obj-art-002-contracts-") as tmp_str:
        tmp = Path(tmp_str)
        completed, payload = _runner(_base_args(tmp / "dry"))
        assert completed.returncode == 0, payload
        completed, payload = _runner(["--case-id", "cross_route_053", "--handoff-manifest", str(HANDOFF), "--approved-chunks", str(CHUNKS), "--output-dir", str(tmp / "bad"), "--no-production-default", "--no-baseline-update", "--no-full-series-b"])
        assert completed.returncode == 2
        assert payload["error_code"] == "CASE_ID_MISMATCH"
        completed = subprocess.run([sys.executable, "-B", str(RUNNER), "--help"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        assert completed.returncode == 0
        assert "--execute-real-controlled-dry-run" in completed.stdout


if __name__ == "__main__":
    run_tests()
    print("obj_art_002 safe API contracts tests PASS")
