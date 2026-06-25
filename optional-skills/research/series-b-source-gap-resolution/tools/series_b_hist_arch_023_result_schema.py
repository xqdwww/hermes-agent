#!/usr/bin/env python3
"""Shared constants for the hist_arch_023 controlled harness."""

from __future__ import annotations


CASE_ID = "hist_arch_023"

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
    "BLOCKED_GUARD_VIOLATION",
    "BLOCKED_PRODUCTION_DEFAULT_RISK",
    "BLOCKED_BASELINE_UPDATE_RISK",
    "BLOCKED_FULL_SERIES_B_RISK",
}

REQUIRED_ARTIFACTS = [
    "hist_arch_023_controlled_manifest_used.json",
    "hist_arch_023_controlled_raw_dossier.md",
    "hist_arch_023_controlled_audit_trace.json",
    "hist_arch_023_controlled_source_packet.json",
    "hist_arch_023_alias_source_guard_report.md",
    "hist_arch_023_contamination_check.md",
    "hist_arch_023_controlled_execution_summary.md",
    "hist_arch_023_controlled_execution_result.json",
]

REQUIRED_TERMS = [
    "Clovis culture",
    "Clovis point",
    "Clovis technology",
    "lithic technology",
    "lithic reduction",
    "flintknapping",
    "pressure flaking",
    "percussion",
    "biface",
    "flake",
    "core",
    "reduction sequence",
    "fracture mechanics",
    "stone tool",
]

REQUIRED_SECTIONS = [
    "historical_context",
    "material_processes",
    "technology_mechanics",
    "archaeology_typology",
    "theme_tracks",
]

REQUIRED_AXES = [
    "archaeology_book",
    "lithic_technology_source",
    "materials_book",
    "fracture_mechanics_source",
    "context_sources",
]

CAVEATED_AXES = ["wiki_or_zim"]


def require_result_enum(value: str) -> str:
    if value not in RESULT_ENUMS:
        allowed = ", ".join(sorted(RESULT_ENUMS))
        raise ValueError(f"unknown result enum {value!r}; expected one of: {allowed}")
    return value
