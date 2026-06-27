#!/usr/bin/env python3
"""Safe API tests for the adv_trap_059 controlled harness."""

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

from adv_trap_059_alias_source_guard import check_text
from series_b_adv_trap_059_controlled_auditor import audit
from series_b_adv_trap_059_source_grounded_builder import build
from series_b_generic_controlled_harness import CASE_CONFIGS, RESULT_ENUMS

CASE_ID = "adv_trap_059"
HANDOFF = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-adv-trap-059-formal-handoff-batch/outputs/adv_trap_059_controlled_handoff_manifest.json")
CHUNKS = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-adv-trap-059-formal-handoff-batch/outputs/adv_trap_059_approved_chunks_handoff.json")
RUNNER = TOOLS_DIR / "run_adv_trap_059_single_case_controlled.py"


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
        "BLOCKED_MALFORMED_TOKEN_RISK",
        "BLOCKED_BOOKING_LISTING_CONTAMINATION",
        "BLOCKED_PRODUCTION_DEFAULT_RISK",
        "BLOCKED_BASELINE_UPDATE_RISK",
        "BLOCKED_FULL_SERIES_B_RISK",
    ]:
        assert value in RESULT_ENUMS
    assert CASE_CONFIGS[CASE_ID].case_id == CASE_ID
    assert callable(build)
    assert callable(audit)
    assert "malformed_token_entity_overclaim" in check_text(f"{CASE_ID} Cappadociahôtel is a real hotel")
    assert "booking_listing_contamination" in check_text(f"{CASE_ID} booking evidence counts as conceptual evidence")
    assert "locator_only_overclaim" in check_text(f"{CASE_ID} locator-only sources count as conceptual evidence")
    assert "orientation_overclaim" in check_text(f"{CASE_ID} orientation is directly source-backed")
    assert "theme_tracks_overclaim" in check_text(f"{CASE_ID} theme_tracks fully supported")
    safe = (
        "adv_trap_059 malformed trap token must not be treated as a real hotel/place/entity. "
        "No booking, ticket, listing, restaurant, map, or price page may count as conceptual evidence. "
        "Orientation is not directly source-backed by the acquired files and must remain caveated. "
        "Theme_tracks is weak and must not be overclaimed. "
        "Cappadocia underground city Derinkuyu underground city ventilation shaft Kaymakli underground city ventilation."
    )
    assert check_text(safe) == []

    with tempfile.TemporaryDirectory(prefix="adv-trap-059-contracts-") as tmp_str:
        tmp = Path(tmp_str)
        completed, payload = _runner(_base_args(tmp / "dry"))
        assert completed.returncode == 0, payload
        completed, payload = _runner([
            "--case-id", "rel_space_035",
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
    print("adv_trap_059 safe API contracts tests PASS")
