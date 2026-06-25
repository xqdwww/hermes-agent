#!/usr/bin/env python3
"""Tests for official candidate input registry support."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
RUNNER = TOOLS / "run_series_b_official_candidate.py"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from series_b_official_candidate_input_registry import load_input_registry, resolve_inputs_from_registry


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()


def _write_registry(tmp: Path, *, candidate_substitute: bool) -> Path:
    dataset = tmp / "dataset.json"
    source_state = tmp / "source_state.json"
    scorer = tmp / "scorer.py"
    builder = tmp / "builder.py"
    runner = tmp / "runner.py"
    ledger = tmp / "ledger.json"
    schema = tmp / "schema.py"
    for path in (dataset, source_state, scorer, builder, runner, ledger, schema):
        path.write_text("{}\n", encoding="utf-8")
    inputs = []
    for role, path in (
        ("official_dataset_path", dataset),
        ("source_state_manifest_path", source_state),
        ("scoring_audit_path", scorer),
        ("builder_path", builder),
        ("runner_path", runner),
        ("frozen_baseline_ledger_path", ledger),
        ("frozen_ledger_comparison_schema", schema),
    ):
        inputs.append(
            {
                "input_role": role,
                "path": str(path),
                "source_of_truth": "fixture",
                "hash": _sha(path),
                "exists": True,
                "readable": True,
                "official_vs_candidate_substitute": "candidate_substitute" if candidate_substitute else "official",
                "candidate_substitute_only": candidate_substitute,
                "safe_for_candidate_run": True,
                "write_target": False,
                "notes": "fixture",
            }
        )
    registry = {
        "schema_version": "series_b_official_candidate_input_registry.v1",
        "registry_status": "PARTIAL" if candidate_substitute else "READY",
        "inputs": inputs,
        "policy": {
            "controlled_evidence_rollup_used_as_official_dataset": False,
            "case_scoped_harness_used_as_official_scorer": False,
        },
    }
    path = tmp / "registry.json"
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "series_b_official_candidate_input_hash_manifest.v1",
        "registry_path": str(path),
        "registry_sha256": _sha(path),
    }
    (tmp / "series_b_official_candidate_input_hash_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_registry_hash_verified() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = _write_registry(Path(tmpdir), candidate_substitute=False)
        payload = load_input_registry(registry)
    assert payload["registry_hash_verification"]["status"] == "PASS"


def test_candidate_substitute_registry_is_not_ready() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outdir:
        registry = _write_registry(Path(tmpdir), candidate_substitute=True)
        payload = resolve_inputs_from_registry(
            registry_path=registry,
            repo_path=REPO_ROOT,
            branch="travel-series-b-validation",
            head="fixture",
            output_dir=outdir,
            require_clean_repo=False,
        )
    assert payload["status"] == "OFFICIAL_CANDIDATE_INPUTS_PARTIAL"
    assert "official_dataset_path" in payload["partial_inputs"]
    assert payload["official_candidate_execution_ready"] is False


def test_ready_registry_fixture_can_be_ready_without_repo_clean_requirement() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outdir:
        registry = _write_registry(Path(tmpdir), candidate_substitute=False)
        payload = resolve_inputs_from_registry(
            registry_path=registry,
            repo_path=REPO_ROOT,
            branch="travel-series-b-validation",
            head="fixture",
            output_dir=outdir,
            require_clean_repo=False,
        )
    assert payload["status"] == "OFFICIAL_CANDIDATE_INPUTS_READY"


def test_runner_accepts_input_registry_and_remains_no_write() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outdir:
        registry = _write_registry(Path(tmpdir), candidate_substitute=True)
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(RUNNER),
                "--verify-inputs-only",
                "--input-registry",
                str(registry),
                "--no-official-write",
                "--no-production-default",
                "--no-push",
                "--no-tag",
                "--output-dir",
                outdir,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["result_enum"] == "OFFICIAL_CANDIDATE_VERIFY_INPUTS_PASS"
    assert payload["official_baseline_update_performed"] is False


def run_tests() -> None:
    test_registry_hash_verified()
    test_candidate_substitute_registry_is_not_ready()
    test_ready_registry_fixture_can_be_ready_without_repo_clean_requirement()
    test_runner_accepts_input_registry_and_remains_no_write()


if __name__ == "__main__":
    run_tests()
    print("series_b official candidate input registry tests PASS")
