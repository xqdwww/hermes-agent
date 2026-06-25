#!/usr/bin/env python3
"""Smoke and contract tests for the hist_arch_023 controlled harness."""

from __future__ import annotations

import copy
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

from series_b_hist_arch_023_artifact_contract import validate_hist_arch_023_artifact_contract
from series_b_hist_arch_023_result_schema import REQUIRED_ARTIFACTS
from series_b_hist_arch_023_source_packet_exporter import (
    SourcePacketExportError,
    export_hist_arch_023_controlled_source_packet,
)


HANDOFF = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/"
    "travel-series-b-hist-arch-023-formal-handoff-batch/outputs/"
    "hist_arch_023_controlled_handoff_manifest.json"
)
CHUNKS = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/"
    "travel-series-b-hist-arch-023-formal-handoff-batch/outputs/"
    "hist_arch_023_approved_chunks_handoff.json"
)
RUNNER = TOOLS_DIR / "run_hist_arch_023_single_case_controlled.py"
REPO_ROOT = Path(__file__).resolve().parents[4]


def _write_json(tmp: Path, name: str, payload: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _runner_json(args: list[str]) -> tuple[subprocess.CompletedProcess[str], dict]:
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
        "hist_arch_023",
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


def _assert_error(code: str, func, *args, **kwargs) -> None:
    try:
        func(*args, **kwargs)
    except SourcePacketExportError as exc:
        assert exc.error_code == code, exc.error_code
        return
    raise AssertionError(f"expected SourcePacketExportError {code}")


def run_tests() -> None:
    with tempfile.TemporaryDirectory(prefix="hist-arch-023-harness-") as tmp_str:
        tmp = Path(tmp_str)

        exported = export_hist_arch_023_controlled_source_packet(
            case_id="hist_arch_023",
            approved_chunks_handoff_path=CHUNKS,
            controlled_handoff_manifest_path=HANDOFF,
            output_dir=tmp / "packet",
            no_production_default=True,
            no_baseline_update=True,
            no_full_series_b=True,
            repo_root=REPO_ROOT,
        )
        packet = json.loads(Path(exported["artifact_path"]).read_text(encoding="utf-8"))
        assert exported["status"] == "SOURCE_PACKET_EXPORTED"
        assert packet["case_id"] == "hist_arch_023"
        assert packet["caveats"]["binding_caveat_preserved"] is True
        assert len(packet["chunks"]) == 12
        assert len(packet["context_or_alias_guard_chunks"]) == 2
        assert all(chunk["binding_status"] == "PAGE_BOUND_WEAK_EPUB_SECTION_BOUND" for chunk in packet["chunks"])

        completed, payload = _runner_json(_base_args(tmp / "dry"))
        assert completed.returncode == 0, payload
        assert payload["harness_status"] == "PASS_DRY_VALIDATION_ONLY"

        completed, payload = _runner_json([*_base_args(tmp / "real"), "--execute-real-controlled-dry-run"])
        assert completed.returncode == 0, payload
        assert payload["harness_status"] == "PASS_SINGLE_CASE_CONTROLLED_DRY_RUN"
        assert payload["result_enum"] == "PASS_CONTROLLED_REGRESSION"
        assert payload["quality"]["level"] == "rich"
        assert payload["binding_caveat_preserved"] is True
        assert payload["term_coverage"]["Clovis point"]["passed"] is True
        assert payload["term_coverage"]["fracture mechanics"]["passed"] is True
        contract = validate_hist_arch_023_artifact_contract(tmp / "real")
        assert contract["status"] == "PASS"
        for name in REQUIRED_ARTIFACTS:
            assert (tmp / "real" / name).exists(), name

        bad_chunks = copy.deepcopy(json.loads(CHUNKS.read_text(encoding="utf-8")))
        bad_chunks["approved_primary_chunks"][0]["title_only"] = True
        _assert_error(
            "SOURCE_PACKET_CONTAMINATION_DETECTED",
            export_hist_arch_023_controlled_source_packet,
            case_id="hist_arch_023",
            approved_chunks_handoff_path=_write_json(tmp, "bad_title.json", bad_chunks),
            controlled_handoff_manifest_path=HANDOFF,
            output_dir=tmp / "bad-title",
            no_production_default=True,
            no_baseline_update=True,
            no_full_series_b=True,
            repo_root=REPO_ROOT,
        )

        bad_chunks = copy.deepcopy(json.loads(CHUNKS.read_text(encoding="utf-8")))
        bad_chunks["approved_primary_chunks"][0]["binding_status"] = "PAGE_PRECISE"
        _assert_error(
            "SOURCE_PACKET_CONTAMINATION_DETECTED",
            export_hist_arch_023_controlled_source_packet,
            case_id="hist_arch_023",
            approved_chunks_handoff_path=_write_json(tmp, "bad_binding.json", bad_chunks),
            controlled_handoff_manifest_path=HANDOFF,
            output_dir=tmp / "bad-binding",
            no_production_default=True,
            no_baseline_update=True,
            no_full_series_b=True,
            repo_root=REPO_ROOT,
        )


if __name__ == "__main__":
    run_tests()
    print("hist_arch_023 controlled harness tests PASS")
