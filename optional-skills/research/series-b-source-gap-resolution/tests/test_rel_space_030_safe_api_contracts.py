#!/usr/bin/env python3
"""Contract tests for the rel_space_030 safe API layer."""

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

from rel_space_030_alias_source_guard import check_text
from series_b_rel_space_030_result_schema import REQUIRED_ARTIFACTS, REQUIRED_SECTIONS, REQUIRED_TERMS, RESULT_ENUMS


BASE = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-rel-space-030-formal-handoff-batch/outputs")
HANDOFF = BASE / "rel_space_030_controlled_handoff_manifest.json"
CHUNKS = BASE / "rel_space_030_approved_chunks_handoff.json"
RUNNER = TOOLS_DIR / "run_rel_space_030_single_case_controlled.py"


def _runner(args: list[str]) -> tuple[subprocess.CompletedProcess[str], dict]:
    completed = subprocess.run([sys.executable, "-B", str(RUNNER), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"runner stdout was not JSON: {completed.stdout}\nstderr: {completed.stderr}") from exc
    return completed, payload


def _base_args(output_dir: Path) -> list[str]:
    return [
        "--case-id", "rel_space_030",
        "--handoff-manifest", str(HANDOFF),
        "--approved-chunks", str(CHUNKS),
        "--output-dir", str(output_dir),
        "--no-production-default",
        "--no-baseline-update",
        "--no-full-series-b",
    ]


def run_tests() -> None:
    assert "PASS_CONTROLLED_REGRESSION" in RESULT_ENUMS
    assert "BLOCKED_MOUNT_MERU_PRIMARY_EVIDENCE_REQUIRED" in RESULT_ENUMS
    assert "BLOCKED_SACRED_GEOMETRY_EXACT_PHRASE_REQUIRED" in RESULT_ENUMS
    assert len(REQUIRED_ARTIFACTS) == 8
    assert {"spatial_structure", "ritual_space", "art_architecture", "historical_layers", "theme_tracks"} == set(REQUIRED_SECTIONS)
    assert "garbhagriha" in REQUIRED_TERMS
    assert "Mount Meru" in REQUIRED_TERMS

    assert check_text("garbhagriha Vastu Purusha Mandala shikhara") == []
    assert "listing_or_planning" in check_text("travel listing opening hours for a temple")
    assert "wrong_domain_science" in check_text("coral reef and garbhagriha")

    with tempfile.TemporaryDirectory(prefix="rel-space-030-contracts-") as tmp_str:
        tmp = Path(tmp_str)
        completed, payload = _runner(_base_args(tmp / "dry"))
        assert completed.returncode == 0
        assert payload["harness_status"] == "PASS_DRY_VALIDATION_ONLY"
        completed = subprocess.run([sys.executable, "-B", str(RUNNER), "--help"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        assert completed.returncode == 0
        assert "--execute-real-controlled-dry-run" in completed.stdout


if __name__ == "__main__":
    run_tests()
    print("rel_space_030 safe API contracts tests PASS")
