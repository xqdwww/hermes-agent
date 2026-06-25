#!/usr/bin/env python3
"""Smoke tests for cross_route_054 controlled harness."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
RUNNER = TOOLS / "run_cross_route_054_single_case_controlled.py"
HANDOFF = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-cross-route-054-formal-handoff-batch/outputs/cross_route_054_controlled_handoff_manifest.json")
CHUNKS = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-cross-route-054-formal-handoff-batch/outputs/cross_route_054_approved_chunks_handoff.json")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-B", str(RUNNER), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def test_runner_help() -> None:
    proc = _run(["--help"])
    assert proc.returncode == 0, proc.stderr
    assert "--execute-real-controlled-dry-run" in proc.stdout


def test_dry_validation_passes_without_execution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--case-id", "cross_route_054", "--handoff-manifest", str(HANDOFF), "--approved-chunks", str(CHUNKS), "--output-dir", tmp, "--no-production-default", "--no-baseline-update", "--no-full-series-b"])
        assert proc.returncode == 0, proc.stderr + proc.stdout
        payload = json.loads(proc.stdout)
        assert payload["harness_status"] == "PASS_DRY_VALIDATION_ONLY"
        assert payload["controlled_regression_execution_performed"] is False
        assert not list(Path(tmp).glob("cross_route_054_controlled_execution_result.json"))


def test_real_controlled_dryrun_exports_artifacts_and_passes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(["--case-id", "cross_route_054", "--handoff-manifest", str(HANDOFF), "--approved-chunks", str(CHUNKS), "--output-dir", tmp, "--no-production-default", "--no-baseline-update", "--no-full-series-b", "--execute-real-controlled-dry-run"])
        assert proc.returncode == 0, proc.stderr + proc.stdout
        payload = json.loads(proc.stdout)
        assert payload["result_enum"] == "PASS_CONTROLLED_REGRESSION"
        assert payload["route_listing_guard_preserved"] is True
        assert payload["ecology_nature_support_preserved"] is True
        assert payload["official_baseline_update_performed"] is False
        required = [
            "cross_route_054_controlled_manifest_used.json",
            "cross_route_054_controlled_raw_dossier.md",
            "cross_route_054_controlled_audit_trace.json",
            "cross_route_054_controlled_source_packet.json",
            "cross_route_054_alias_source_guard_report.md",
            "cross_route_054_contamination_check.md",
            "cross_route_054_controlled_execution_summary.md",
            "cross_route_054_controlled_execution_result.json",
        ]
        for name in required:
            assert (Path(tmp) / name).exists(), name


def run_tests() -> None:
    test_runner_help()
    test_dry_validation_passes_without_execution()
    test_real_controlled_dryrun_exports_artifacts_and_passes()


if __name__ == "__main__":
    run_tests()
    print("cross_route_054 controlled harness tests PASS")
