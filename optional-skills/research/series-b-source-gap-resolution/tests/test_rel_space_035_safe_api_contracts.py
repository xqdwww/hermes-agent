#!/usr/bin/env python3
"""Safe API tests for the rel_space_035 controlled harness."""

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

from rel_space_035_alias_source_guard import check_text
from series_b_generic_controlled_harness import CASE_CONFIGS, RESULT_ENUMS
from series_b_rel_space_035_controlled_auditor import audit
from series_b_rel_space_035_source_grounded_builder import build

CASE_ID = "rel_space_035"
HANDOFF = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-rel-space-035-formal-handoff-batch/outputs/rel_space_035_controlled_handoff_manifest.json")
CHUNKS = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-rel-space-035-formal-handoff-batch/outputs/rel_space_035_approved_chunks_handoff.json")
RUNNER = TOOLS_DIR / "run_rel_space_035_single_case_controlled.py"


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
        "BLOCKED_PRODUCTION_DEFAULT_RISK",
        "BLOCKED_BASELINE_UPDATE_RISK",
        "BLOCKED_FULL_SERIES_B_RISK",
    ]:
        assert value in RESULT_ENUMS
    assert CASE_CONFIGS[CASE_ID].case_id == CASE_ID
    assert callable(build)
    assert callable(audit)
    assert "unsupported_acoustics_overclaim" in check_text(f"{CASE_ID} acoustic design is confirmed")
    assert "professional_book_axis_overclaim" in check_text(f"{CASE_ID} Wikipedia is professional book evidence")
    assert "source_axis_overclaim" in check_text(f"{CASE_ID} travel locator source counts as conceptual evidence")
    assert "listing_or_planning" in check_text(f"{CASE_ID} hotel booking ticket itinerary")
    assert check_text(
        "rel_space_035 ballcourt rings ritual geometry Acoustics remains unsupported/caveated; "
        "Internet Archive record is not extracted book-body evidence; context sources are not overclaimed as professional book evidence."
    ) == []

    with tempfile.TemporaryDirectory(prefix="rel-space-035-contracts-") as tmp_str:
        tmp = Path(tmp_str)
        completed, payload = _runner(_base_args(tmp / "dry"))
        assert completed.returncode == 0, payload
        completed, payload = _runner([
            "--case-id", "rel_space_034",
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
    print("rel_space_035 safe API contracts tests PASS")
