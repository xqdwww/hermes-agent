#!/usr/bin/env python3
"""Shared constants for the rel_space_030 controlled harness."""

from __future__ import annotations


CASE_ID = "rel_space_030"

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
    "BLOCKED_MOUNT_MERU_PRIMARY_EVIDENCE_REQUIRED",
    "BLOCKED_SACRED_GEOMETRY_EXACT_PHRASE_REQUIRED",
    "BLOCKED_GUARD_VIOLATION",
    "BLOCKED_PRODUCTION_DEFAULT_RISK",
    "BLOCKED_BASELINE_UPDATE_RISK",
    "BLOCKED_FULL_SERIES_B_RISK",
}

REQUIRED_ARTIFACTS = [
    "rel_space_030_controlled_manifest_used.json",
    "rel_space_030_controlled_raw_dossier.md",
    "rel_space_030_controlled_audit_trace.json",
    "rel_space_030_controlled_source_packet.json",
    "rel_space_030_alias_source_guard_report.md",
    "rel_space_030_contamination_check.md",
    "rel_space_030_controlled_execution_summary.md",
    "rel_space_030_controlled_execution_result.json",
]

REQUIRED_TERMS = [
    "garbhagriha",
    "garbha griha",
    "Hindu temple",
    "Hindu temple architecture",
    "Vastu shastra",
    "Vastu Purusha Mandala",
    "shikhara",
    "mandapa",
    "axis mundi",
    "sacred geometry",
    "Mount Meru",
    "mandala plan",
]

REQUIRED_SECTIONS = [
    "spatial_structure",
    "ritual_space",
    "art_architecture",
    "historical_layers",
    "theme_tracks",
]

REQUIRED_AXES = [
    "religion_book",
    "architecture_book",
    "art_architecture_book",
    "wiki_or_zim",
    "encyclopedia_context",
    "context_sources",
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
