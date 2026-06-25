#!/usr/bin/env python3
"""Contract tests for the nat_eco_047 safe API layer."""

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

from nat_eco_047_alias_source_guard import check_text
from series_b_nat_eco_047_result_schema import REQUIRED_ARTIFACTS, REQUIRED_SECTIONS, REQUIRED_TERMS, RESULT_ENUMS


HANDOFF = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/"
    "travel-series-b-nat-eco-047-formal-handoff-batch/outputs/"
    "nat_eco_047_controlled_handoff_manifest.json"
)
CHUNKS = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/"
    "travel-series-b-nat-eco-047-formal-handoff-batch/outputs/"
    "nat_eco_047_approved_chunks_handoff.json"
)
RUNNER = TOOLS_DIR / "run_nat_eco_047_single_case_controlled.py"


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
        "nat_eco_047",
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
    assert "BLOCKED_CONTEXT_PRIMARY_EVIDENCE_REQUIRED" in RESULT_ENUMS
    assert len(REQUIRED_ARTIFACTS) == 8
    assert set(REQUIRED_SECTIONS) == {
        "natural_processes",
        "landform_mechanics",
        "regional_relations",
        "theme_tracks",
    }
    assert "atoll" in REQUIRED_TERMS
    assert "reef flat" in REQUIRED_TERMS
    assert "Darwin coral reef theory" in REQUIRED_TERMS

    assert check_text("atoll coral reef lagoon reef flat Darwin coral reef theory") == []
    assert "listing_or_planning" in check_text("hotel ticket booking")
    assert "generic_tropical_tourism" in check_text("beach vacation honeymoon package")
    assert "wrong_domain_darwin" in check_text("Darwin biography and natural selection")
    assert "wrong_domain_science" in check_text("Clovis point flintknapping")

    with tempfile.TemporaryDirectory(prefix="nat-eco-047-contracts-") as tmp_str:
        tmp = Path(tmp_str)
        completed, payload = _runner(_base_args(tmp / "dry"))
        assert completed.returncode == 0, payload
        assert payload["harness_status"] == "PASS_DRY_VALIDATION_ONLY"
        assert payload["approved_chunks_count"] == 14
        assert payload["supplemental_locator_caveat_preserved"] is True
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
    print("nat_eco_047 safe API contracts tests PASS")
