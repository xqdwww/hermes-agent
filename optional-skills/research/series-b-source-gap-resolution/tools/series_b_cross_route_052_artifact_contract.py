#!/usr/bin/env python3
"""Artifact contract checks for cross_route_052 controlled dry-runs."""

from __future__ import annotations

import json
from pathlib import Path

from series_b_cross_route_052_result_schema import CASE_ID, REQUIRED_ARTIFACTS, require_result_enum


class CrossRoute052ArtifactContractError(ValueError):
    """Raised when cross_route_052 controlled artifacts are missing or unsafe."""


def validate_cross_route_052_artifact_contract(output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir).expanduser().resolve(strict=False)
    missing = [name for name in REQUIRED_ARTIFACTS if not (target / name).exists()]
    if missing:
        raise CrossRoute052ArtifactContractError(f"missing required artifacts: {missing}")
    parsed: dict[str, object] = {}
    for name in REQUIRED_ARTIFACTS:
        path = target / name
        text = path.read_text(encoding="utf-8")
        if "dummy_test_artifact_only" in text:
            raise CrossRoute052ArtifactContractError(f"{name} is a dummy artifact")
        if '"mock_builder_output": true' in text or '"mock_audit_output": true' in text:
            raise CrossRoute052ArtifactContractError(f"{name} is a mock artifact")
        if CASE_ID not in text:
            raise CrossRoute052ArtifactContractError(f"{name} does not mention cross_route_052")
        if path.suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                parsed[name] = payload
    result = parsed.get("cross_route_052_controlled_execution_result.json", {})
    if isinstance(result, dict):
        if result.get("case_id") != CASE_ID:
            raise CrossRoute052ArtifactContractError("result case_id must be cross_route_052")
        require_result_enum(str(result.get("result_enum")))
        if result.get("mock_audit_output") is True or result.get("mock_builder_output") is True:
            raise CrossRoute052ArtifactContractError("mock outputs are not allowed")
        if result.get("official_baseline_update_performed") is not False:
            raise CrossRoute052ArtifactContractError("baseline update flag must be false")
        if result.get("full_series_b_run_performed") is not False:
            raise CrossRoute052ArtifactContractError("full Series B flag must be false")
        if result.get("production_default_manifest_integration_performed") is not False:
            raise CrossRoute052ArtifactContractError("production default flag must be false")
        if result.get("binding_caveat_preserved") is not True:
            raise CrossRoute052ArtifactContractError("binding caveat was not preserved")
        if result.get("hydrology_caveat_preserved") is not True:
            raise CrossRoute052ArtifactContractError("hydrology caveat was not preserved")
    return {"status": "PASS", "artifacts": [str(target / name) for name in REQUIRED_ARTIFACTS]}
