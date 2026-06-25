#!/usr/bin/env python3
"""Shared constants for the cross_route_052 controlled harness."""

from __future__ import annotations


CASE_ID = "cross_route_052"

EXECUTION_FALSE_FLAGS = {
    "official_baseline_update_performed": False,
    "full_series_b_run_performed": False,
    "production_default_manifest_integration_performed": False,
    "case_repair_performed": False,
    "push_performed": False,
    "tag_created": False,
}

RESULT_ENUMS = {
    "PASS_CONTROLLED_REGRESSION",
    "FAIL_CONTROLLED_REGRESSION",
    "PARTIAL_SOURCE_GUARDED_PASS",
    "BLOCKED_BINDING_INSUFFICIENT",
    "BLOCKED_HYDROLOGY_PRIMARY_EVIDENCE_REQUIRED",
    "BLOCKED_GUARD_VIOLATION",
    "BLOCKED_PRODUCTION_DEFAULT_RISK",
    "BLOCKED_BASELINE_UPDATE_RISK",
    "BLOCKED_FULL_SERIES_B_RISK",
}

REQUIRED_ARTIFACTS = [
    "cross_route_052_controlled_manifest_used.json",
    "cross_route_052_controlled_raw_dossier.md",
    "cross_route_052_controlled_audit_trace.json",
    "cross_route_052_controlled_source_packet.json",
    "cross_route_052_alias_source_guard_report.md",
    "cross_route_052_contamination_check.md",
    "cross_route_052_controlled_execution_summary.md",
    "cross_route_052_controlled_execution_result.json",
]

REQUIRED_TERMS = [
    "Dunhuang",
    "Mogao Caves",
    "cave architecture",
    "Buddhist cave temple",
    "fresco",
    "wall painting",
    "microclimate",
    "oasis",
    "hydrology",
    "conglomerate",
    "cliff stability",
    "conservation",
    "Hexi Corridor",
]

REQUIRED_SECTIONS = [
    "historical_context",
    "art_architecture",
    "natural_processes",
    "regional_relations",
    "theme_tracks",
]

REQUIRED_AXES = [
    "art_architecture_book",
    "archaeology_history_source",
    "conservation_source",
    "geology_hydrology_source",
    "context_sources",
]

CAVEATED_AXES = ["wiki_or_zim"]


def require_result_enum(value: str) -> str:
    if value not in RESULT_ENUMS:
        allowed = ", ".join(sorted(RESULT_ENUMS))
        raise ValueError(f"unknown result enum {value!r}; expected one of: {allowed}")
    return value
