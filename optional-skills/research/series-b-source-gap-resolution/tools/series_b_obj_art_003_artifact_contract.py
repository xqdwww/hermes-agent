#!/usr/bin/env python3
"""Artifact contract checks for obj_art_003 controlled dry-runs."""

from __future__ import annotations

import json
from pathlib import Path

from series_b_obj_art_003_result_schema import CASE_ID, REQUIRED_ARTIFACTS


class ObjArt003ArtifactContractError(ValueError):
    """Raised when obj_art_003 controlled artifacts are missing or unsafe."""


def validate_obj_art_003_artifact_contract(output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir).expanduser().resolve(strict=False)
    missing = [name for name in REQUIRED_ARTIFACTS if not (target / name).exists()]
    if missing:
        raise ObjArt003ArtifactContractError(f"missing required artifacts: {missing}")
    parsed: dict[str, object] = {}
    for name in REQUIRED_ARTIFACTS:
        path = target / name
        text = path.read_text(encoding="utf-8")
        if "dummy_test_artifact_only" in text:
            raise ObjArt003ArtifactContractError(f"{name} is a dummy artifact")
        if '"mock_builder_output": true' in text or '"mock_audit_output": true' in text:
            raise ObjArt003ArtifactContractError(f"{name} is a mock artifact")
        if CASE_ID not in text:
            raise ObjArt003ArtifactContractError(f"{name} does not mention obj_art_003")
        if path.suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                parsed[name] = payload
    result = parsed.get("obj_art_003_controlled_execution_result.json", {})
    if isinstance(result, dict):
        if result.get("case_id") != CASE_ID:
            raise ObjArt003ArtifactContractError("result case_id must be obj_art_003")
        if result.get("mock_audit_output") is True or result.get("mock_builder_output") is True:
            raise ObjArt003ArtifactContractError("mock outputs are not allowed")
    return {"status": "PASS", "artifacts": [str(target / name) for name in REQUIRED_ARTIFACTS]}
