#!/usr/bin/env python3
"""Artifact contract checks for rel_space_030 controlled dry-runs."""

from __future__ import annotations

import json
from pathlib import Path

from series_b_rel_space_030_result_schema import CASE_ID, REQUIRED_ARTIFACTS, require_result_enum


class RelSpace030ArtifactContractError(ValueError):
    """Raised when rel_space_030 controlled artifacts are missing or unsafe."""


def validate_rel_space_030_artifact_contract(output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir).expanduser().resolve(strict=False)
    missing = [name for name in REQUIRED_ARTIFACTS if not (target / name).exists()]
    if missing:
        raise RelSpace030ArtifactContractError(f"missing required artifacts: {missing}")
    parsed: dict[str, object] = {}
    for name in REQUIRED_ARTIFACTS:
        path = target / name
        text = path.read_text(encoding="utf-8")
        if "dummy_test_artifact_only" in text:
            raise RelSpace030ArtifactContractError(f"{name} is a dummy artifact")
        if '"mock_builder_output": true' in text or '"mock_audit_output": true' in text:
            raise RelSpace030ArtifactContractError(f"{name} is a mock artifact")
        if CASE_ID not in text:
            raise RelSpace030ArtifactContractError(f"{name} does not mention rel_space_030")
        if path.suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                parsed[name] = payload
    result = parsed.get("rel_space_030_controlled_execution_result.json", {})
    if isinstance(result, dict):
        if result.get("case_id") != CASE_ID:
            raise RelSpace030ArtifactContractError("result case_id must be rel_space_030")
        require_result_enum(str(result.get("result_enum")))
        if result.get("mock_audit_output") is True or result.get("mock_builder_output") is True:
            raise RelSpace030ArtifactContractError("mock outputs are not allowed")
        if result.get("official_baseline_update_performed") is not False:
            raise RelSpace030ArtifactContractError("baseline update flag must be false")
        if result.get("full_series_b_run_performed") is not False:
            raise RelSpace030ArtifactContractError("full Series B flag must be false")
        if result.get("production_default_manifest_integration_performed") is not False:
            raise RelSpace030ArtifactContractError("production default flag must be false")
        if result.get("binding_caveat_preserved") is not True:
            raise RelSpace030ArtifactContractError("binding caveat was not preserved")
        if result.get("mount_meru_context_caveat_preserved") is not True:
            raise RelSpace030ArtifactContractError("Mount Meru caveat was not preserved")
        if result.get("sacred_geometry_equivalent_caveat_preserved") is not True:
            raise RelSpace030ArtifactContractError("sacred geometry caveat was not preserved")
    return {"status": "PASS", "artifacts": [str(target / name) for name in REQUIRED_ARTIFACTS]}
