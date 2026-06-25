#!/usr/bin/env python3
"""Tests for Series B official candidate no-write guard."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from series_b_official_candidate_no_write_guard import OfficialCandidateGuardError, validate_no_write_policy


def _valid_kwargs(tmp: str) -> dict[str, object]:
    return {
        "official_baseline_write_enabled": False,
        "production_default_enabled": False,
        "push_enabled": False,
        "tag_enabled": False,
        "candidate_mode": True,
        "output_dir": tmp,
        "repo_root": REPO_ROOT,
        "write_targets": [tmp],
        "command": "python run_series_b_official_candidate.py --dry-run-plan-only --no-official-write",
    }


def test_no_write_guard_passes_for_repo_external_output() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        payload = validate_no_write_policy(**_valid_kwargs(tmp))
    assert payload["status"] == "PASS"
    assert payload["official_baseline_write_enabled"] is False


def test_baseline_write_disabled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kwargs = _valid_kwargs(tmp)
        kwargs["official_baseline_write_enabled"] = True
        try:
            validate_no_write_policy(**kwargs)
        except OfficialCandidateGuardError as exc:
            assert exc.error_code == "OFFICIAL_CANDIDATE_BASELINE_WRITE_RISK"
        else:
            raise AssertionError("expected baseline write risk")


def test_production_default_disabled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kwargs = _valid_kwargs(tmp)
        kwargs["production_default_enabled"] = True
        try:
            validate_no_write_policy(**kwargs)
        except OfficialCandidateGuardError as exc:
            assert exc.error_code == "OFFICIAL_CANDIDATE_PRODUCTION_DEFAULT_RISK"
        else:
            raise AssertionError("expected production default risk")


def test_push_tag_disabled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kwargs = _valid_kwargs(tmp)
        kwargs["push_enabled"] = True
        try:
            validate_no_write_policy(**kwargs)
        except OfficialCandidateGuardError as exc:
            assert exc.error_code == "OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL"
        else:
            raise AssertionError("expected push risk")


def test_unknown_write_capable_command_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kwargs = _valid_kwargs(tmp)
        kwargs["command"] = "python runner.py --write-baseline"
        try:
            validate_no_write_policy(**kwargs)
        except OfficialCandidateGuardError as exc:
            assert exc.error_code == "OFFICIAL_CANDIDATE_NO_WRITE_GUARD_FAIL"
        else:
            raise AssertionError("expected destructive command risk")


def run_tests() -> None:
    test_no_write_guard_passes_for_repo_external_output()
    test_baseline_write_disabled()
    test_production_default_disabled()
    test_push_tag_disabled()
    test_unknown_write_capable_command_blocked()


if __name__ == "__main__":
    run_tests()
    print("series_b official candidate no-write guard tests PASS")
