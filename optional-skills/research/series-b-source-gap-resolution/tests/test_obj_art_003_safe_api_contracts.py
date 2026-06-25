#!/usr/bin/env python3
"""Lightweight contract checks for the existing obj_art_003 controlled harness."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = SKILL_DIR / "tools"
for path in (str(SKILL_DIR), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from series_b_obj_art_003_result_schema import REQUIRED_ARTIFACTS, REQUIRED_AXES, REQUIRED_SECTIONS, REQUIRED_TERMS


RUNNER = TOOLS_DIR / "run_obj_art_003_single_case_controlled.py"


def run_tests() -> None:
    assert len(REQUIRED_ARTIFACTS) == 8
    assert "obj_art_003_controlled_execution_result.json" in REQUIRED_ARTIFACTS
    assert "materials_book" in REQUIRED_AXES
    assert "engineering_book" in REQUIRED_AXES
    assert "architecture_book" in REQUIRED_AXES
    assert {"materials_mechanics", "historical_context", "art_architecture"} == set(REQUIRED_SECTIONS)
    assert "Roman concrete" in REQUIRED_TERMS
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
    print("obj_art_003 safe API contracts tests PASS")
