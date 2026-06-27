#!/usr/bin/env python3
"""Safe API tests for the obj_art_008 controlled harness."""

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

from obj_art_008_alias_source_guard import check_text
from series_b_generic_controlled_harness import CASE_CONFIGS, RESULT_ENUMS
from series_b_obj_art_008_controlled_auditor import audit
from series_b_obj_art_008_source_grounded_builder import build

CASE_ID = "obj_art_008"
HANDOFF = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-obj-art-008-formal-handoff-batch/outputs/obj_art_008_controlled_handoff_manifest.json")
CHUNKS = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-obj-art-008-formal-handoff-batch/outputs/obj_art_008_approved_chunks_handoff.json")
RUNNER = TOOLS_DIR / "run_obj_art_008_single_case_controlled.py"


def _runner(args: list[str]):
    completed = subprocess.run(
        [sys.executable, "-B", str(RUNNER), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed, json.loads(completed.stdout)


def _base_args(out: Path) -> list[str]:
    return [
        "--case-id", CASE_ID,
        "--handoff-manifest", str(HANDOFF),
        "--approved-chunks", str(CHUNKS),
        "--output-dir", str(out),
        "--no-production-default",
        "--no-baseline-update",
        "--no-full-series-b",
    ]


def run_tests() -> None:
    for value in [
        "PASS_CONTROLLED_REGRESSION",
        "FAIL_CONTROLLED_REGRESSION",
        "PARTIAL_SOURCE_GUARDED_PASS",
        "BLOCKED_BINDING_INSUFFICIENT",
        "BLOCKED_GUARD_VIOLATION",
        "BLOCKED_ALIAS_AMBIGUITY",
        "BLOCKED_WRONG_CONTEXT_RISK",
        "BLOCKED_PRODUCTION_DEFAULT_RISK",
        "BLOCKED_BASELINE_UPDATE_RISK",
        "BLOCKED_FULL_SERIES_B_RISK",
    ]:
        assert value in RESULT_ENUMS
    assert CASE_CONFIGS[CASE_ID].case_id == CASE_ID
    assert callable(build)
    assert callable(audit)
    assert "alias_ambiguity_overclaim" in check_text(f"{CASE_ID} Mingan is a real architectural term")
    assert "wrong_context_overclaim" in check_text(f"{CASE_ID} Chinese Mingan proves the object")
    assert "generic_screen_overclaim" in check_text(f"{CASE_ID} generic decorative screen proves the required object")
    assert "rejected_source_counted" in check_text(f"{CASE_ID} wikipedia_historic_cairo.md counted")
    assert "source_axis_overclaim" in check_text(f"{CASE_ID} wikipedia api proves professional book body")
    safe = (
        "obj_art_008 alias confirmed with caveat. Mingan is a dataset alias token, not a real architectural term. "
        "The source-backed target is mashrabiya and mashrabiyya in Cairo: wooden lattice screen, wood carving, "
        "lattice, thermal regulation, ventilation, geometry, and privacy screening. "
        "Wrong object, wrong period, and wrong culture overclaims remain blocked."
    )
    assert check_text(safe) == []

    with tempfile.TemporaryDirectory(prefix="obj-art-008-contracts-") as tmp_str:
        tmp = Path(tmp_str)
        completed, payload = _runner(_base_args(tmp / "dry"))
        assert completed.returncode == 0, payload
        completed, payload = _runner([
            "--case-id", "adv_trap_059",
            "--handoff-manifest", str(HANDOFF),
            "--approved-chunks", str(CHUNKS),
            "--output-dir", str(tmp / "bad"),
            "--no-production-default",
            "--no-baseline-update",
            "--no-full-series-b",
        ])
        assert completed.returncode == 2
        assert payload["error_code"] == "CASE_ID_MISMATCH"
        completed = subprocess.run(
            [sys.executable, "-B", str(RUNNER), "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert completed.returncode == 0
        assert "--execute-real-controlled-dry-run" in completed.stdout


if __name__ == "__main__":
    run_tests()
    print("obj_art_008 safe API contracts tests PASS")
