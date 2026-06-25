#!/usr/bin/env python3
"""Shared constants for the obj_art_007 controlled harness."""

from __future__ import annotations


CASE_ID = "obj_art_007"

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
    "BLOCKED_EXACT_PAGE_REQUIRED",
    "BLOCKED_GUARD_VIOLATION",
    "BLOCKED_PRODUCTION_DEFAULT_RISK",
    "BLOCKED_BASELINE_UPDATE_RISK",
    "BLOCKED_FULL_SERIES_B_RISK",
}

REQUIRED_ARTIFACTS = [
    "obj_art_007_controlled_manifest_used.json",
    "obj_art_007_controlled_raw_dossier.md",
    "obj_art_007_controlled_audit_trace.json",
    "obj_art_007_controlled_source_packet.json",
    "obj_art_007_alias_source_guard_report.md",
    "obj_art_007_contamination_check.md",
    "obj_art_007_controlled_execution_summary.md",
    "obj_art_007_controlled_execution_result.json",
]

REQUIRED_TERMS = [
    "dougong",
    "bracket set",
    "timber framing",
    "timber joinery",
    "interlocking timber joinery",
    "load transfer",
    "cantilever",
    "seismic performance",
    "energy dissipation",
    "Yingzao Fashi",
    "Chinese timber architecture",
]

REQUIRED_SECTIONS = [
    "materials_mechanics",
    "historical_context",
    "art_architecture",
    "theme_tracks",
]

REQUIRED_AXES = [
    "architecture_book",
    "materials_book",
    "engineering_book",
    "structural_mechanics_source",
    "context_sources",
]

ALLOWED_PAGE_BOUND_STATUSES = {
    "PAGE_BOUND_WEAK_EPUB_SECTION_BOUND",
    "PAGE_BOUND_WEAK_SECTION_BOUND",
    "SECTION_BOUND",
    "CHUNK_BOUND",
}

EXPECTED_FORMAL_READY_DECISION = "OBJ_ART_007_FORMAL_READY_APPROVED_WITH_PAGE_BINDING_CAVEAT"
APPROVED_REVIEWER_DECISION = "FORMAL_READY_APPROVED_WITH_PAGE_BINDING_CAVEAT"


def require_result_enum(value: str) -> str:
    if value not in RESULT_ENUMS:
        allowed = ", ".join(sorted(RESULT_ENUMS))
        raise ValueError(f"unknown result enum {value!r}; expected one of: {allowed}")
    return value
