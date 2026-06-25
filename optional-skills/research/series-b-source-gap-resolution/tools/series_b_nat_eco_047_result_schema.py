#!/usr/bin/env python3
"""Shared constants for the nat_eco_047 controlled harness."""

from __future__ import annotations


CASE_ID = "nat_eco_047"

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
    "BLOCKED_CONTEXT_PRIMARY_EVIDENCE_REQUIRED",
    "BLOCKED_GUARD_VIOLATION",
    "BLOCKED_PRODUCTION_DEFAULT_RISK",
    "BLOCKED_BASELINE_UPDATE_RISK",
    "BLOCKED_FULL_SERIES_B_RISK",
}

REQUIRED_ARTIFACTS = [
    "nat_eco_047_controlled_manifest_used.json",
    "nat_eco_047_controlled_raw_dossier.md",
    "nat_eco_047_controlled_audit_trace.json",
    "nat_eco_047_controlled_source_packet.json",
    "nat_eco_047_alias_source_guard_report.md",
    "nat_eco_047_contamination_check.md",
    "nat_eco_047_controlled_execution_summary.md",
    "nat_eco_047_controlled_execution_result.json",
]

REQUIRED_TERMS = [
    "atoll",
    "coral reef",
    "fringing reef",
    "barrier reef",
    "lagoon",
    "reef flat",
    "reef development",
    "volcanic subsidence",
    "Darwin coral reef theory",
]

REQUIRED_SECTIONS = [
    "natural_processes",
    "landform_mechanics",
    "regional_relations",
    "theme_tracks",
]

REQUIRED_AXES = [
    "wiki_or_zim",
    "encyclopedia_context",
    "context_sources",
    "nature_book_if_available",
    "geography_book_if_available",
]

ALLOWED_BINDING_STATUSES = {
    "CONTEXT_ENTRY_BOUND",
    "CONTEXT_SECTION_BOUND",
    "LOCAL_SOURCE_SECTION_BOUND",
}


def require_result_enum(value: str) -> str:
    if value not in RESULT_ENUMS:
        allowed = ", ".join(sorted(RESULT_ENUMS))
        raise ValueError(f"unknown result enum {value!r}; expected one of: {allowed}")
    return value
