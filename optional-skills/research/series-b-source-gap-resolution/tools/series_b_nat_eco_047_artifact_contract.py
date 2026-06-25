#!/usr/bin/env python3
"""Artifact contract checks for nat_eco_047 controlled dry-runs."""

from __future__ import annotations

import json
from pathlib import Path

from series_b_nat_eco_047_result_schema import CASE_ID, REQUIRED_ARTIFACTS, require_result_enum


class NatEco047ArtifactContractError(ValueError):
    """Raised when nat_eco_047 controlled artifacts are missing or unsafe."""


def validate_nat_eco_047_artifact_contract(output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir).expanduser().resolve(strict=False)
    missing = [name for name in REQUIRED_ARTIFACTS if not (target / name).exists()]
    if missing:
        raise NatEco047ArtifactContractError(f"missing required artifacts: {missing}")
    parsed: dict[str, object] = {}
    for name in REQUIRED_ARTIFACTS:
        path = target / name
        text = path.read_text(encoding="utf-8")
        if "dummy_test_artifact_only" in text:
            raise NatEco047ArtifactContractError(f"{name} is a dummy artifact")
        if '"mock_builder_output": true' in text or '"mock_audit_output": true' in text:
            raise NatEco047ArtifactContractError(f"{name} is a mock artifact")
        if CASE_ID not in text:
            raise NatEco047ArtifactContractError(f"{name} does not mention nat_eco_047")
        if path.suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                parsed[name] = payload
    result = parsed.get("nat_eco_047_controlled_execution_result.json", {})
    if isinstance(result, dict):
        if result.get("case_id") != CASE_ID:
            raise NatEco047ArtifactContractError("result case_id must be nat_eco_047")
        require_result_enum(str(result.get("result_enum")))
        if result.get("mock_audit_output") is True or result.get("mock_builder_output") is True:
            raise NatEco047ArtifactContractError("mock outputs are not allowed")
        if result.get("official_baseline_update_performed") is not False:
            raise NatEco047ArtifactContractError("baseline update flag must be false")
        if result.get("full_series_b_run_performed") is not False:
            raise NatEco047ArtifactContractError("full Series B flag must be false")
        if result.get("production_default_manifest_integration_performed") is not False:
            raise NatEco047ArtifactContractError("production default flag must be false")
        if result.get("binding_caveat_preserved") is not True:
            raise NatEco047ArtifactContractError("binding caveat was not preserved")
        if result.get("supplemental_locator_caveat_preserved") is not True:
            raise NatEco047ArtifactContractError("supplemental locator caveat was not preserved")
    return {"status": "PASS", "artifacts": [str(target / name) for name in REQUIRED_ARTIFACTS]}
