#!/usr/bin/env python3
"""Layer-1 contract tests for rel_space_029 safe API skeleton."""

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

from series_b_controlled_result_schema import REQUIRED_ARTIFACTS
from series_b_real_artifact_contract import validate_real_mode_artifact_contract
from series_b_real_audit_adapter import AuditAdapterError, audit_rel_space_029_controlled_dossier
from series_b_real_dossier_builder_adapter import (
    BuilderAdapterError,
    build_rel_space_029_controlled_raw_dossier,
)
from series_b_real_source_packet_exporter import (
    SourcePacketExportError,
    export_rel_space_029_controlled_source_packet,
)

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
        raise AssertionError(f"runner stdout was not JSON: {completed.stdout}") from exc
    return completed, payload


def _base_args(output_dir: Path) -> list[str]:
    return [
        "--case-id",
        "rel_space_029",
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


def _export_packet(output_dir: Path, chunks_path: Path = CHUNKS) -> dict:
    return export_rel_space_029_controlled_source_packet(
        case_id="rel_space_029",
        approved_chunks_handoff_path=chunks_path,
        controlled_handoff_manifest_path=HANDOFF,
        output_dir=output_dir,
        no_production_default=True,
        no_baseline_update=True,
        no_full_series_b=True,
        repo_root=REPO_ROOT,
    )


def _assert_error(exc_type: type[Exception], code: str, func, *args, **kwargs) -> None:
    try:
        func(*args, **kwargs)
    except exc_type as exc:
        assert getattr(exc, "error_code", None) == code
        return
    raise AssertionError(f"expected {exc_type.__name__} {code}")


def run_tests() -> None:
    with tempfile.TemporaryDirectory(prefix="rel-space-029-safe-api-") as tmp_str:
        tmp = Path(tmp_str)

        exported = _export_packet(tmp / "packet")
        packet_path = Path(exported["artifact_path"])
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        assert exported["status"] == "SOURCE_PACKET_EXPORTED"
        assert packet["case_id"] == "rel_space_029"
        assert packet["mock_source_packet"] is False
        assert len(packet["chunks"]) == 10
        assert all(chunk["source_backed_text_locator"] for chunk in packet["chunks"])
        assert all(chunk["reviewer_decision"] == "FORMAL_READY_APPROVED" for chunk in packet["chunks"])
        assert packet["official_baseline_update_performed"] is False
        assert packet["full_series_b_run_performed"] is False
        assert packet["production_default_manifest_integration_performed"] is False

        chunk_payload = json.loads(CHUNKS.read_text(encoding="utf-8"))
        bad_missing_text = copy.deepcopy(chunk_payload)
        bad_missing_text["approved_chunks"][0]["source_backed_text_exists"] = False
        _assert_error(
            SourcePacketExportError,
            "APPROVED_CHUNKS_MALFORMED",
            _export_packet,
            tmp / "bad-missing-text",
            _write_json(tmp, "bad_missing_text.json", bad_missing_text),
        )

        bad_listing = copy.deepcopy(chunk_payload)
        bad_listing["approved_chunks"][0]["is_listing_or_travel_planning"] = True
        _assert_error(
            SourcePacketExportError,
            "SOURCE_PACKET_CONTAMINATION_DETECTED",
            _export_packet,
            tmp / "bad-listing",
            _write_json(tmp, "bad_listing.json", bad_listing),
        )

        bad_bema = copy.deepcopy(chunk_payload)
        bad_bema["approved_chunks"][0]["is_wrong_context_bema"] = True
        _assert_error(
            SourcePacketExportError,
            "SOURCE_PACKET_CONTAMINATION_DETECTED",
            _export_packet,
            tmp / "bad-bema",
            _write_json(tmp, "bad_bema.json", bad_bema),
        )

        _assert_error(
            BuilderAdapterError,
            "BLOCKED_BUILDER_ENTRY_UNIMPLEMENTED",
            build_rel_space_029_controlled_raw_dossier,
            case_id="rel_space_029",
            source_packet_path=packet_path,
            handoff_manifest_path=HANDOFF,
            output_dir=tmp / "builder-blocked",
            no_production_default=True,
            no_baseline_update=True,
            no_full_series_b=True,
            repo_root=REPO_ROOT,
        )

        mock_run_dir = tmp / "mock-run"
        mock_exported = _export_packet(mock_run_dir)
        mock_packet_path = Path(mock_exported["artifact_path"])
        builder_result = build_rel_space_029_controlled_raw_dossier(
            case_id="rel_space_029",
            source_packet_path=mock_packet_path,
            handoff_manifest_path=HANDOFF,
            output_dir=mock_run_dir,
            no_production_default=True,
            no_baseline_update=True,
            no_full_series_b=True,
            use_mock_builder=True,
            repo_root=REPO_ROOT,
        )
        assert builder_result["mock_builder_output"] is True
        _assert_error(
            AuditAdapterError,
            "BLOCKED_AUDIT_ENTRY_UNIMPLEMENTED",
            audit_rel_space_029_controlled_dossier,
            case_id="rel_space_029",
            raw_dossier_path=builder_result["artifact_path"],
            source_packet_path=packet_path,
            handoff_manifest_path=HANDOFF,
            output_dir=tmp / "audit-blocked",
            no_production_default=True,
            no_baseline_update=True,
            no_full_series_b=True,
            repo_root=REPO_ROOT,
        )

        audit_result = audit_rel_space_029_controlled_dossier(
            case_id="rel_space_029",
            raw_dossier_path=builder_result["artifact_path"],
            source_packet_path=mock_packet_path,
            handoff_manifest_path=HANDOFF,
            output_dir=mock_run_dir,
            no_production_default=True,
            no_baseline_update=True,
            no_full_series_b=True,
            use_mock_audit=True,
            repo_root=REPO_ROOT,
        )
        assert audit_result["result"]["mock_audit_output"] is True
        assert audit_result["result"]["result_enum"] != "PASS_CONTROLLED_REGRESSION"

        manifest_used = mock_run_dir / "rel_space_029_controlled_manifest_used.json"
        manifest_used.write_text(
            json.dumps({"case_id": "rel_space_029", "layer1_test": True}, indent=2),
            encoding="utf-8",
        )
        contract = validate_real_mode_artifact_contract(mock_run_dir, allow_mock=True)
        assert contract["status"] == "PASS"
        assert len(contract["artifacts"]) == len(REQUIRED_ARTIFACTS)

        dry_dir = tmp / "dry-run"
        completed, payload = _runner_json([*_base_args(dry_dir), "--use-mock-builder", "--use-mock-audit"])
        assert completed.returncode == 0
        assert payload["harness_status"] == "PASS_DRY_VALIDATION_ONLY"
        assert not (dry_dir / "rel_space_029_controlled_raw_dossier.md").exists()

        blocked_dir = tmp / "real-blocked"
        completed, payload = _runner_json([*_base_args(blocked_dir), "--execute-real-controlled-dry-run"])
        assert completed.returncode != 0
        assert payload["error_code"] == "BLOCKED_BUILDER_ENTRY_UNIMPLEMENTED"
        assert payload["result_enum"] != "PASS_CONTROLLED_REGRESSION"
        assert (blocked_dir / "rel_space_029_controlled_source_packet.json").exists()
        assert (blocked_dir / "rel_space_029_controlled_execution_result.json").exists()

        completed, payload = _runner_json(
            [
                *_base_args(tmp / "bad-case"),
                "--case-id",
                "obj_art_003",
                "--execute-real-controlled-dry-run",
            ]
        )
        assert completed.returncode != 0
        assert payload["error_code"] == "CASE_ID_MISMATCH"

        mock_dir = tmp / "runner-mock"
        completed, payload = _runner_json(
            [
                *_base_args(mock_dir),
                "--execute-real-controlled-dry-run",
                "--use-mock-builder",
                "--use-mock-audit",
            ]
        )
        assert completed.returncode == 0
        assert payload["harness_status"] == "PASS_LAYER1_REAL_MODE_SKELETON_MOCK_ONLY"
        assert payload["result_enum"] != "PASS_CONTROLLED_REGRESSION"
        assert payload["official_baseline_update_performed"] is False
        assert payload["full_series_b_run_performed"] is False
        assert payload["production_default_manifest_integration_performed"] is False
        validate_real_mode_artifact_contract(mock_dir, allow_mock=True)

    print("rel_space_029 safe API layer 1 contract tests PASS")


if __name__ == "__main__":
    run_tests()
