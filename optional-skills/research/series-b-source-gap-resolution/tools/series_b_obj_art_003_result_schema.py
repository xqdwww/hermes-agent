#!/usr/bin/env python3
"""Shared constants for the obj_art_003 controlled harness."""

from __future__ import annotations


CASE_ID = "obj_art_003"

EXECUTION_FALSE_FLAGS = {
    "official_baseline_update_performed": False,
    "full_series_b_run_performed": False,
    "production_default_manifest_integration_performed": False,
    "controlled_regression_execution_performed": False,
    "case_repair_performed": False,
    "push_performed": False,
}

REQUIRED_ARTIFACTS = [
    "obj_art_003_controlled_manifest_used.json",
    "obj_art_003_controlled_raw_dossier.md",
    "obj_art_003_controlled_audit_trace.json",
    "obj_art_003_controlled_source_packet.json",
    "obj_art_003_alias_source_guard_report.md",
    "obj_art_003_contamination_check.md",
    "obj_art_003_controlled_execution_summary.md",
    "obj_art_003_controlled_execution_result.json",
]

REQUIRED_TERMS = [
    "Roman concrete",
    "opus caementicium",
    "pozzolana",
    "hydraulic setting / hydraulic lime",
    "mortar",
    "marine concrete",
    "durability",
]

REQUIRED_SECTIONS = ["materials_mechanics", "historical_context", "art_architecture"]
REQUIRED_AXES = ["materials_book", "engineering_book", "architecture_book"]
