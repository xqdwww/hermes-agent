#!/usr/bin/env python3
"""Standalone smoke tests for the rel_space_029 explicit harness shell."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = SKILL_DIR / "tools"
REPO_ROOT = Path(__file__).resolve().parents[4]
for path in (str(SKILL_DIR), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from rel_space_029_alias_source_guard import AliasSourceGuardError, check_text, validate_chunks
from series_b_approved_chunks_loader import (
    ApprovedChunksValidationError,
    load_approved_chunks,
    validate_chunks_against_manifest,
)
from series_b_controlled_artifact_exporter import (
    ArtifactContractError,
    validate_output_dir_policy,
    validate_required_artifact_names,
    write_dummy_artifacts,
)
from series_b_controlled_handoff_loader import HandoffValidationError, load_handoff_manifest
from series_b_controlled_result_schema import REQUIRED_ARTIFACTS
from validate_series_b_source_manifest_vnext import run_self_test

HANDOFF = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-23/"
    "travel-series-b-rel-space-029-controlled-planning-handoff/outputs/"
    "rel_space_029_controlled_handoff_manifest.json"
)
CHUNKS = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-23/"
    "travel-series-b-rel-space-029-controlled-planning-handoff/outputs/"
    "rel_space_029_approved_chunks_handoff.json"
)
RUNNER = TOOLS_DIR / "run_rel_space_029_single_case_controlled.py"


def _write_json(tmp: Path, name: str, payload: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _assert_raises(exc_type: type[Exception], func, *args, **kwargs) -> None:
    try:
        func(*args, **kwargs)
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__}")


def _runner(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_tests() -> None:
    ok, report = run_self_test()
    assert ok, report

    manifest = load_handoff_manifest(HANDOFF)
    chunks = load_approved_chunks(CHUNKS)
    validate_chunks_against_manifest(chunks, manifest)
    validate_chunks(chunks)
    validate_required_artifact_names(REQUIRED_ARTIFACTS)

    with tempfile.TemporaryDirectory(prefix="rel-space-029-harness-test-") as tmp_str:
        tmp = Path(tmp_str)

        bad_case_manifest = copy.deepcopy(manifest)
        bad_case_manifest["case_id"] = "obj_art_003"
        _assert_raises(
            HandoffValidationError,
            load_handoff_manifest,
            _write_json(tmp, "bad_case_manifest.json", bad_case_manifest),
        )

        for field in (
            "production_default_loader_enabled",
            "official_baseline_update_enabled",
            "full_series_b_enabled",
        ):
            unsafe = copy.deepcopy(manifest)
            unsafe["production_path_policy"][field] = True
            _assert_raises(
                HandoffValidationError,
                load_handoff_manifest,
                _write_json(tmp, f"unsafe_{field}.json", unsafe),
            )

        chunk_payload = json.loads(CHUNKS.read_text(encoding="utf-8"))
        bad_chunks = copy.deepcopy(chunk_payload)
        bad_chunks["case_id"] = "obj_art_003"
        _assert_raises(
            ApprovedChunksValidationError,
            load_approved_chunks,
            _write_json(tmp, "bad_case_chunks.json", bad_chunks),
        )

        bad_review = copy.deepcopy(chunk_payload)
        bad_review["approved_chunks"][0]["reviewer_decision"] = "CANDIDATE_ONLY"
        _assert_raises(
            ApprovedChunksValidationError,
            load_approved_chunks,
            _write_json(tmp, "bad_review_chunks.json", bad_review),
        )

        for marker, text in {
            "wrong_context_bema": "The Christian bema stands before the church apse.",
            "title_only": "title-only evidence: bema platform",
            "query_echo": "query: bema synagogue",
            "image_filename": "bema_platform.jpg",
            "listing_noise": "Opening hours and tickets for the synagogue platform.",
        }.items():
            assert check_text(text), marker

        assert not check_text("The bimah is a Torah reading platform within the synagogue.")
        assert check_text("A reading platform is mentioned without sacred context.")

        bad_guard = copy.deepcopy(chunks)
        bad_guard[0]["is_title_only"] = True
        _assert_raises(AliasSourceGuardError, validate_chunks, bad_guard)

        _assert_raises(ArtifactContractError, validate_output_dir_policy, REPO_ROOT, repo_root=REPO_ROOT)
        dummy_dir = tmp / "dummy-artifacts"
        written = write_dummy_artifacts(dummy_dir, manifest, chunks, repo_root=REPO_ROOT)
        assert len(written) == len(REQUIRED_ARTIFACTS)
        result = json.loads((dummy_dir / "rel_space_029_controlled_execution_result.json").read_text())
        assert result["dummy_test_artifact_only"] is True
        assert result["result_enum"] != "PASS_CONTROLLED_REGRESSION"
        assert result["controlled_regression_execution_performed"] is False

        base_args = [
            "--case-id",
            "rel_space_029",
            "--handoff-manifest",
            str(HANDOFF),
            "--approved-chunks",
            str(CHUNKS),
            "--output-dir",
            str(tmp / "runner-out"),
            "--no-production-default",
            "--no-baseline-update",
            "--no-full-series-b",
        ]
        assert _runner(base_args).returncode == 0
        assert _runner(base_args[2:]).returncode != 0
        assert _runner([arg for arg in base_args if arg != "--no-production-default"]).returncode != 0
        assert _runner([arg for arg in base_args if arg != "--no-baseline-update"]).returncode != 0
        assert _runner([arg for arg in base_args if arg != "--no-full-series-b"]).returncode != 0

    print("rel_space_029 harness smoke tests PASS")


if __name__ == "__main__":
    run_tests()
