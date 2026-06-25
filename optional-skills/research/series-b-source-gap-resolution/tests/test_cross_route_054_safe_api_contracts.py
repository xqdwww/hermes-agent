#!/usr/bin/env python3
"""Contract tests for cross_route_054 safe API layer."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from cross_route_054_alias_source_guard import CrossRoute054GuardError, validate_chunks
from series_b_cross_route_054_result_schema import require_result_enum
from series_b_cross_route_054_source_packet_exporter import SourcePacketExportError, export_cross_route_054_controlled_source_packet

HANDOFF = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-cross-route-054-formal-handoff-batch/outputs/cross_route_054_controlled_handoff_manifest.json")
CHUNKS = Path("/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-cross-route-054-formal-handoff-batch/outputs/cross_route_054_approved_chunks_handoff.json")


def test_result_enums_include_required_values() -> None:
    for value in ["PASS_CONTROLLED_REGRESSION", "BLOCKED_ECOLOGY_AXIS_INSUFFICIENT", "BLOCKED_ROUTE_LISTING_CONTAMINATION"]:
        assert require_result_enum(value) == value


def test_source_packet_rejects_wrong_case() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            export_cross_route_054_controlled_source_packet(case_id="obj_art_007", approved_chunks_handoff_path=CHUNKS, controlled_handoff_manifest_path=HANDOFF, output_dir=tmp, no_production_default=True, no_baseline_update=True, no_full_series_b=True, repo_root=REPO_ROOT)
        except SourcePacketExportError as exc:
            assert exc.error_code == "CASE_ID_MISMATCH"
        else:
            raise AssertionError("expected CASE_ID_MISMATCH")


def test_source_packet_rejects_missing_policy_flag() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            export_cross_route_054_controlled_source_packet(case_id="cross_route_054", approved_chunks_handoff_path=CHUNKS, controlled_handoff_manifest_path=HANDOFF, output_dir=tmp, no_production_default=False, no_baseline_update=True, no_full_series_b=True, repo_root=REPO_ROOT)
        except SourcePacketExportError as exc:
            assert exc.error_code == "BLOCKED_PRODUCTION_DEFAULT_RISK"
        else:
            raise AssertionError("expected BLOCKED_PRODUCTION_DEFAULT_RISK")


def test_guard_rejects_listing_noise() -> None:
    payload = json.loads(CHUNKS.read_text(encoding="utf-8"))
    chunk = dict(payload["approved_chunks"][0])
    chunk["source_backed_text"] = "Book this hotel ticket itinerary for Oman."
    try:
        validate_chunks([chunk])
    except CrossRoute054GuardError as exc:
        assert exc.error_code == "BLOCKED_ROUTE_LISTING_CONTAMINATION"
    else:
        raise AssertionError("expected guard error")


def run_tests() -> None:
    test_result_enums_include_required_values()
    test_source_packet_rejects_wrong_case()
    test_source_packet_rejects_missing_policy_flag()
    test_guard_rejects_listing_noise()


if __name__ == "__main__":
    run_tests()
    print("cross_route_054 safe API contracts tests PASS")
