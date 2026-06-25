#!/usr/bin/env python3
"""Artifact contract checks for cross_route_054 controlled dry-runs."""

from __future__ import annotations

import json
from pathlib import Path

from series_b_cross_route_054_result_schema import CASE_ID, REQUIRED_ARTIFACTS, require_result_enum


class CrossRoute054ArtifactContractError(ValueError):
    """Raised when cross_route_054 controlled artifacts are missing or unsafe."""


def validate_cross_route_054_artifact_contract(output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir).expanduser().resolve(strict=False)
    missing = [name for name in REQUIRED_ARTIFACTS if not (target / name).exists()]
    if missing:
        raise CrossRoute054ArtifactContractError(f"missing required artifacts: {missing}")
    parsed: dict[str, object] = {}
    for name in REQUIRED_ARTIFACTS:
        path = target / name
        text = path.read_text(encoding="utf-8")
        if "dummy_test_artifact_only" in text:
            raise CrossRoute054ArtifactContractError(f"{name} is a dummy artifact")
        if '"mock_builder_output": true' in text or '"mock_audit_output": true' in text:
            raise CrossRoute054ArtifactContractError(f"{name} is a mock artifact")
        if CASE_ID not in text:
            raise CrossRoute054ArtifactContractError(f"{name} does not mention cross_route_054")
        if name == "cross_route_054_controlled_raw_dossier.md" and "route_listing_guard_preserved: true" not in text:
            raise CrossRoute054ArtifactContractError("raw dossier must preserve route/listing guard")
        if path.suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                parsed[name] = payload
    result = parsed.get("cross_route_054_controlled_execution_result.json", {})
    if isinstance(result, dict):
        if result.get("case_id") != CASE_ID:
            raise CrossRoute054ArtifactContractError("result case_id must be cross_route_054")
        require_result_enum(str(result.get("result_enum")))
        if result.get("mock_audit_output") is True or result.get("mock_builder_output") is True:
            raise CrossRoute054ArtifactContractError("mock outputs are not allowed")
        for flag in ["official_baseline_update_performed", "full_series_b_run_performed", "production_default_manifest_integration_performed"]:
            if result.get(flag) is not False:
                raise CrossRoute054ArtifactContractError(f"{flag} must be false")
        if result.get("route_listing_guard_preserved") is not True:
            raise CrossRoute054ArtifactContractError("route/listing guard was not preserved")
        if result.get("ecology_nature_support_preserved") is not True:
            raise CrossRoute054ArtifactContractError("ecology/nature support was not preserved")
        if result.get("caveats_preserved") is not True:
            raise CrossRoute054ArtifactContractError("caveats were not preserved")
    return {"status": "PASS", "artifacts": [str(target / name) for name in REQUIRED_ARTIFACTS]}
