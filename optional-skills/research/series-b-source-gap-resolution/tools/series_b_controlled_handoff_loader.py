#!/usr/bin/env python3
"""vNext handoff manifest loader for rel_space_029.

The loader adapts the case-scoped handoff shape to the existing standalone
vNext validator, then applies execution-scope locks that are specific to the
rel_space_029 explicit-only harness.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
SKILL_DIR = TOOL_DIR.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_controlled_result_schema import CASE_ID, POLICY_LOCKS, SCHEMA_VERSION
from validate_series_b_source_manifest_vnext import TOP_LEVEL_FIELDS, validate_manifest


class HandoffValidationError(ValueError):
    """Raised when a rel_space_029 handoff manifest is unsafe or malformed."""


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise HandoffValidationError("handoff manifest root must be a JSON object")
    return data


def _validator_core_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    core = {field: manifest[field] for field in TOP_LEVEL_FIELDS if field in manifest}
    core.setdefault("prototype_evidence", [])
    core.setdefault("excluded_sources", [])
    return core


def _require_policy_locks(policy: dict[str, Any]) -> None:
    if not isinstance(policy, dict):
        raise HandoffValidationError("production_path_policy must be an object")
    for field, expected in POLICY_LOCKS.items():
        if policy.get(field) is not expected:
            if field == "production_default_loader_enabled":
                raise HandoffValidationError("production default loader must remain disabled")
            if field == "full_series_b_enabled":
                raise HandoffValidationError("full Series B must remain disabled")
            if field == "official_baseline_update_enabled":
                raise HandoffValidationError("official baseline update must remain disabled")
            raise HandoffValidationError(f"production_path_policy.{field} must be {expected}")


def load_handoff_manifest(path: str | Path, *, expected_case_id: str = CASE_ID) -> dict[str, Any]:
    manifest_path = Path(path).expanduser()
    manifest = _load_json_object(manifest_path)

    required = {
        "schema_version",
        "case_id",
        "professional_sources",
        "context_sources",
        "axis_satisfaction",
        "formal_pass_gate",
        "production_path_policy",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise HandoffValidationError(f"handoff manifest missing required fields: {missing}")

    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise HandoffValidationError(f"schema_version must be {SCHEMA_VERSION}")
    if manifest.get("case_id") != expected_case_id:
        raise HandoffValidationError(f"handoff manifest case_id must be {expected_case_id}")

    scope = manifest.get("controlled_execution_scope", {})
    if scope:
        if scope.get("case_scoped_only") is not True:
            raise HandoffValidationError("controlled_execution_scope.case_scoped_only must be true")
        allowed = scope.get("allowed_case_ids")
        if not isinstance(allowed, list) or expected_case_id not in allowed:
            raise HandoffValidationError("controlled_execution_scope must allow only rel_space_029")
        if scope.get("not_a_production_manifest") is not True:
            raise HandoffValidationError("handoff manifest must be marked not_a_production_manifest")

    _require_policy_locks(manifest["production_path_policy"])

    gate = manifest.get("formal_pass_gate", {})
    if gate.get("context_sources_used_as_professional_sources") is True:
        raise HandoffValidationError("context source used as professional source")
    if gate.get("prototype_evidence_used_as_formal_pass") is True:
        raise HandoffValidationError("prototype evidence used as formal pass")

    if not manifest.get("approved_chunks") and not any(
        source.get("accepted_chunks") for source in manifest.get("professional_sources", [])
        if isinstance(source, dict)
    ):
        raise HandoffValidationError("handoff manifest must include approved chunks or references")

    core = _validator_core_manifest(manifest)
    errors = validate_manifest(core)
    if errors:
        raise HandoffValidationError("vNext manifest validation failed: " + "; ".join(errors))

    return manifest


def manifest_accepted_chunk_ids(manifest: dict[str, Any]) -> set[str]:
    chunk_ids: set[str] = set()
    for source in manifest.get("professional_sources", []):
        if not isinstance(source, dict):
            continue
        for chunk in source.get("accepted_chunks", []):
            if isinstance(chunk, dict) and isinstance(chunk.get("chunk_id"), str):
                chunk_ids.add(chunk["chunk_id"])
    for chunk in manifest.get("approved_chunks", []):
        if isinstance(chunk, dict) and isinstance(chunk.get("chunk_id"), str):
            chunk_ids.add(chunk["chunk_id"])
    return chunk_ids
