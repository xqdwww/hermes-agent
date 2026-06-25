#!/usr/bin/env python3
"""Shared constants for the cross_route_054 controlled harness."""

from __future__ import annotations

CASE_ID = "cross_route_054"

EXECUTION_FALSE_FLAGS = {
    "official_baseline_update_performed": False,
    "full_series_b_run_performed": False,
    "production_default_manifest_integration_performed": False,
    "controlled_regression_execution_performed": False,
    "case_repair_performed": False,
    "push_performed": False,
    "tag_created": False,
}

RESULT_ENUMS = {
    "PASS_CONTROLLED_REGRESSION",
    "FAIL_CONTROLLED_REGRESSION",
    "PARTIAL_SOURCE_GUARDED_PASS",
    "BLOCKED_BINDING_INSUFFICIENT",
    "BLOCKED_ECOLOGY_AXIS_INSUFFICIENT",
    "BLOCKED_ROUTE_LISTING_CONTAMINATION",
    "BLOCKED_GUARD_VIOLATION",
    "BLOCKED_PRODUCTION_DEFAULT_RISK",
    "BLOCKED_BASELINE_UPDATE_RISK",
    "BLOCKED_FULL_SERIES_B_RISK",
}

REQUIRED_ARTIFACTS = [
    "cross_route_054_controlled_manifest_used.json",
    "cross_route_054_controlled_raw_dossier.md",
    "cross_route_054_controlled_audit_trace.json",
    "cross_route_054_controlled_source_packet.json",
    "cross_route_054_alias_source_guard_report.md",
    "cross_route_054_contamination_check.md",
    "cross_route_054_controlled_execution_summary.md",
    "cross_route_054_controlled_execution_result.json",
]

REQUIRED_TERMS = [
    "Dhofar",
    "Oman",
    "frankincense",
    "incense trade",
    "frankincense production",
    "Boswellia sacra",
    "frankincense tree",
    "Wadi Dawkah",
    "Wadi Dawka",
    "Land of Frankincense",
    "khareef",
    "kharif",
    "monsoon",
    "monsoon ecology",
    "vegetation",
    "scrubland ecology",
    "Khor Rori",
    "Sumhuram",
    "Al-Baleed",
    "maritime / route context",
]

REQUIRED_SECTIONS = [
    "historical_context",
    "natural_processes",
    "regional_relations",
    "theme_tracks",
]

REQUIRED_AXES = [
    "history_book",
    "trade_route_source",
    "nature_book",
    "ecology_source",
    "archaeology_history_source",
    "wiki_or_zim",
    "context_sources",
]

EXPECTED_FORMAL_READY_DECISION = "CROSS_ROUTE_054_FORMAL_READY_APPROVED_WITH_CAVEAT"
APPROVED_REVIEWER_DECISION = "FORMAL_READY_APPROVED"


def require_result_enum(value: str) -> str:
    if value not in RESULT_ENUMS:
        allowed = ", ".join(sorted(RESULT_ENUMS))
        raise ValueError(f"unknown result enum {value!r}; expected one of: {allowed}")
    return value
