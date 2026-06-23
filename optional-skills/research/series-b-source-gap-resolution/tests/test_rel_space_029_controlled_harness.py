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


def _runner_json(args: list[str]) -> tuple[subprocess.CompletedProcess[str], dict]:
    completed = _runner(args)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"runner stdout was not JSON: {completed.stdout}") from exc
    return completed, payload


def _assert_runner_error(args: list[str], error_code: str) -> None:
    completed, payload = _runner_json(args)
    assert completed.returncode != 0
    assert completed.stderr == ""
    assert payload["status"] == "ERROR"
    assert payload["case_id"] == "rel_space_029"
    assert payload["error_code"] == error_code
    assert payload["safe_to_retry"] is False
    assert payload["official_baseline_update_performed"] is False
    assert payload["full_series_b_run_performed"] is False
    assert payload["production_default_manifest_integration_performed"] is False
    assert payload["controlled_regression_execution_performed"] is False
    assert payload["case_repair_performed"] is False


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
        _assert_runner_error(base_args[:1] + ["obj_art_003"] + base_args[2:], "CASE_ID_MISMATCH")
        assert _runner([arg for arg in base_args if arg != "--no-production-default"]).returncode != 0
        assert _runner([arg for arg in base_args if arg != "--no-baseline-update"]).returncode != 0
        assert _runner([arg for arg in base_args if arg != "--no-full-series-b"]).returncode != 0

        _assert_runner_error(
            base_args[: base_args.index("--handoff-manifest") + 1]
            + [str(tmp / "missing_handoff.json")]
            + base_args[base_args.index("--approved-chunks") :],
            "HANDOFF_MANIFEST_NOT_FOUND",
        )
        _assert_runner_error(
            base_args[: base_args.index("--approved-chunks") + 1]
            + [str(tmp / "missing_chunks.json")]
            + base_args[base_args.index("--output-dir") :],
            "APPROVED_CHUNKS_NOT_FOUND",
        )

        malformed_manifest = tmp / "malformed_manifest.json"
        malformed_manifest.write_text("{not json", encoding="utf-8")
        _assert_runner_error(
            base_args[: base_args.index("--handoff-manifest") + 1]
            + [str(malformed_manifest)]
            + base_args[base_args.index("--approved-chunks") :],
            "HANDOFF_MANIFEST_MALFORMED",
        )

        malformed_chunks = tmp / "malformed_chunks.json"
        malformed_chunks.write_text("{not json", encoding="utf-8")
        _assert_runner_error(
            base_args[: base_args.index("--approved-chunks") + 1]
            + [str(malformed_chunks)]
            + base_args[base_args.index("--output-dir") :],
            "APPROVED_CHUNKS_MALFORMED",
        )

        _assert_runner_error(
            base_args[: base_args.index("--output-dir") + 1]
            + [str(REPO_ROOT / "tmp-runner-output")]
            + base_args[base_args.index("--no-production-default") :],
            "OUTPUT_DIR_UNSAFE",
        )

        unsafe_policy_manifest = copy.deepcopy(manifest)
        unsafe_policy_manifest["production_path_policy"]["production_default_loader_enabled"] = True
        _assert_runner_error(
            base_args[: base_args.index("--handoff-manifest") + 1]
            + [str(_write_json(tmp, "unsafe_policy_manifest.json", unsafe_policy_manifest))]
            + base_args[base_args.index("--approved-chunks") :],
            "POLICY_LOCK_UNSAFE",
        )

        mismatched_chunks = copy.deepcopy(chunk_payload)
        mismatched_chunks["case_id"] = "obj_art_003"
        _assert_runner_error(
            base_args[: base_args.index("--approved-chunks") + 1]
            + [str(_write_json(tmp, "mismatched_chunks.json", mismatched_chunks))]
            + base_args[base_args.index("--output-dir") :],
            "CASE_ID_MISMATCH",
        )

    print("rel_space_029 harness smoke tests PASS")


if __name__ == "__main__":
    run_tests()
