#!/usr/bin/env python3
"""Shared constants for the rel_space_029 controlled harness shell.

This module is intentionally explicit-only. It defines result and artifact
contracts, but it does not run Series B and does not touch production paths.
"""

from __future__ import annotations

CASE_ID = "rel_space_029"
SCHEMA_VERSION = "series_b_source_manifest.vNext.draft"

RESULT_ENUMS = {
    "PASS_CONTROLLED_REGRESSION",
    "FAIL_CONTROLLED_REGRESSION",
    "PARTIAL_SOURCE_GUARDED_PASS",
    "BLOCKED_HARNESS_UNAVAILABLE",
    "BLOCKED_REPO_PATCH_REQUIRED",
    "BLOCKED_GUARD_VIOLATION",
    "BLOCKED_PRODUCTION_DEFAULT_RISK",
    "BLOCKED_BASELINE_UPDATE_RISK",
    "BLOCKED_FULL_SERIES_B_RISK",
}

REQUIRED_ARTIFACTS = [
    "rel_space_029_controlled_manifest_used.json",
    "rel_space_029_controlled_raw_dossier.md",
    "rel_space_029_controlled_audit_trace.json",
    "rel_space_029_controlled_source_packet.json",
    "rel_space_029_alias_source_guard_report.md",
    "rel_space_029_contamination_check.md",
    "rel_space_029_controlled_execution_summary.md",
    "rel_space_029_controlled_execution_result.json",
]

POLICY_LOCKS = {
    "case_scoped_only": True,
    "production_default_loader_enabled": False,
    "full_series_b_enabled": False,
    "official_baseline_update_enabled": False,
}

EXECUTION_FALSE_FLAGS = {
    "official_baseline_update_performed": False,
    "full_series_b_run_performed": False,
    "production_default_manifest_integration_performed": False,
    "controlled_regression_execution_performed": False,
    "case_repair_performed": False,
    "push_performed": False,
}


def require_result_enum(value: str) -> str:
    if value not in RESULT_ENUMS:
        allowed = ", ".join(sorted(RESULT_ENUMS))
        raise ValueError(f"unknown result enum {value!r}; expected one of: {allowed}")
    return value
