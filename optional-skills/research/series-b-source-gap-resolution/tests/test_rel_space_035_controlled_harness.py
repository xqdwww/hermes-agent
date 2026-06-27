#!/usr/bin/env python3
"""Smoke and contract tests for the rel_space_035 controlled harness."""

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
    with tempfile.TemporaryDirectory(prefix="rel-space-035-harness-") as tmp_str:
        tmp = Path(tmp_str)
        completed, payload = _runner(_base_args(tmp / "dry"))
        assert completed.returncode == 0, payload
        assert payload["approved_chunks_count"] == 4

        completed, payload = _runner([*_base_args(tmp / "real"), "--execute-real-controlled-dry-run"])
        assert completed.returncode == 0, payload
        assert payload["result_enum"] == "PASS_CONTROLLED_REGRESSION"
        assert payload["quality"]["level"] == "rich"
        assert payload["term_coverage"]["ballcourt"]["passed"] is True
        assert payload["term_coverage"]["rings"]["passed"] is True
        assert payload["term_coverage"]["ritual"]["passed"] is True
        assert payload["term_coverage"]["geometry"]["passed"] is True
        assert payload["axis_coverage"]["archaeology_book"] is True
        assert payload["axis_coverage"]["religion_book"] is True
        assert payload["axis_coverage"]["wiki_or_zim"] is True
        assert payload["section_coverage"]["spatial_structure"] is True
        assert payload["section_coverage"]["historical_layers"] is True
        assert payload["section_coverage"]["theme_tracks"] is True
        assert payload["guard_result"]["passed"] is True
        assert payload["official_baseline_update_performed"] is False

        result_path = tmp / "real" / "rel_space_035_controlled_execution_result.json"
        result = json.loads(result_path.read_text())
        caveat_text = " ".join(result["caveats_preserved"]).lower()
        assert "acoustics remains unsupported/caveated" in caveat_text
        assert "not extracted book-body evidence" in caveat_text
        assert "must not be overclaimed as professional book axes" in caveat_text

        raw = (tmp / "real" / "rel_space_035_controlled_raw_dossier.md").read_text()
        assert "not overclaimed as professional book evidence" in raw.lower()
        assert "production_default=false" in raw

        contract = validate_artifact_contract(tmp / "real", case_id=CASE_ID)
        assert contract["status"] == "PASS"
        for name in artifact_names(CASE_ID):
            assert (tmp / "real" / name).exists(), name


if __name__ == "__main__":
    run_tests()
    print("rel_space_035 controlled harness tests PASS")
