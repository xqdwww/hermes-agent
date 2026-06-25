#!/usr/bin/env python3
"""Contract tests for the cross_route_052 safe API layer."""

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

from cross_route_052_alias_source_guard import check_text
from series_b_cross_route_052_result_schema import REQUIRED_ARTIFACTS, REQUIRED_SECTIONS, REQUIRED_TERMS, RESULT_ENUMS


HANDOFF = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/"
    "travel-series-b-cross-route-052-formal-handoff-batch/outputs/"
    "cross_route_052_controlled_handoff_manifest.json"
)
CHUNKS = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/"
    "travel-series-b-cross-route-052-formal-handoff-batch/outputs/"
    "cross_route_052_approved_chunks_handoff.json"
)
RUNNER = TOOLS_DIR / "run_cross_route_052_single_case_controlled.py"


def _runner(args: list[str]) -> tuple[subprocess.CompletedProcess[str], dict]:
    completed = subprocess.run(
        [sys.executable, "-B", str(RUNNER), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"runner stdout was not JSON: {completed.stdout}\nstderr: {completed.stderr}") from exc
    return completed, payload


def _base_args(output_dir: Path) -> list[str]:
    return [
        "--case-id",
        "cross_route_052",
        "--handoff-manifest",
        str(HANDOFF),
        "--approved-chunks",
        str(CHUNKS),
        "--output-dir",
        str(output_dir),
        "--no-production-default",
        "--no-baseline-update",
        "--no-full-series-b",
    ]


def run_tests() -> None:
    assert "PASS_CONTROLLED_REGRESSION" in RESULT_ENUMS
    assert "BLOCKED_HYDROLOGY_PRIMARY_EVIDENCE_REQUIRED" in RESULT_ENUMS
    assert len(REQUIRED_ARTIFACTS) == 8
    assert set(REQUIRED_SECTIONS) == {
        "historical_context",
        "art_architecture",
        "natural_processes",
        "regional_relations",
        "theme_tracks",
    }
    assert "hydrology" in REQUIRED_TERMS
    assert "cliff stability" in REQUIRED_TERMS

    assert check_text("Dunhuang Mogao Caves wall painting conservation hydrology") == []
    assert "listing_or_planning" in check_text("hotel ticket booking")
    assert "generic_china_travel_noise" in check_text("China travel guide day trip")
    assert "wrong_domain_science" in check_text("Clovis point flintknapping")
    assert "wrong_domain_science" in check_text("aeolian sand saltation")

    with tempfile.TemporaryDirectory(prefix="cross-route-052-contracts-") as tmp_str:
        tmp = Path(tmp_str)
        completed, payload = _runner(_base_args(tmp / "dry"))
        assert completed.returncode == 0, payload
        assert payload["harness_status"] == "PASS_DRY_VALIDATION_ONLY"
        assert payload["approved_primary_chunks_count"] == 11
        assert payload["approved_supplemental_chunks_count"] == 3
        assert payload["hydrology_caveat_preserved"] is True
        completed, payload = _runner(
            [
                "--case-id",
                "hist_arch_023",
                "--handoff-manifest",
                str(HANDOFF),
                "--approved-chunks",
                str(CHUNKS),
                "--output-dir",
                str(tmp / "bad-case"),
                "--no-production-default",
                "--no-baseline-update",
                "--no-full-series-b",
            ]
        )
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
    print("cross_route_052 safe API contracts tests PASS")
