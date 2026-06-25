#!/usr/bin/env python3
"""Shared constants for the nat_eco_041 controlled harness."""

from __future__ import annotations


CASE_ID = "nat_eco_041"

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
    "BLOCKED_DUNE_MIGRATION_EXACT_TERM_REQUIRED",
    "BLOCKED_GUARD_VIOLATION",
    "BLOCKED_PRODUCTION_DEFAULT_RISK",
    "BLOCKED_BASELINE_UPDATE_RISK",
    "BLOCKED_FULL_SERIES_B_RISK",
}

REQUIRED_ARTIFACTS = [
    "nat_eco_041_controlled_manifest_used.json",
    "nat_eco_041_controlled_raw_dossier.md",
    "nat_eco_041_controlled_audit_trace.json",
    "nat_eco_041_controlled_source_packet.json",
    "nat_eco_041_alias_source_guard_report.md",
    "nat_eco_041_contamination_check.md",
    "nat_eco_041_controlled_execution_summary.md",
    "nat_eco_041_controlled_execution_result.json",
]

REQUIRED_TERMS = [
    "saltation",
    "aeolian processes",
    "sand dune",
    "sediment transport",
    "wind erosion",
    "creep",
    "suspension",
    "ripples",
    "aeolian sediment transport",
    "sand transport",
]

REQUIRED_SECTIONS = ["natural_processes", "landform_mechanics", "regional_relations", "theme_tracks"]

REQUIRED_PROFESSIONAL_AXES = [
    "nature_book",
    "geography_book",
    "geomorphology_book",
    "earth_science_book",
    "geology_book",
]

REQUIRED_CONTEXT_AXES = ["wiki_or_zim", "context_sources", "encyclopedia_context"]


def require_result_enum(value: str) -> str:
    if value not in RESULT_ENUMS:
        allowed = ", ".join(sorted(RESULT_ENUMS))
        raise ValueError(f"unknown result enum {value!r}; expected one of: {allowed}")
    return value
