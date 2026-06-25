#!/usr/bin/env python3
"""Artifact contract checks for obj_art_007 controlled dry-runs."""

from __future__ import annotations

import json
from pathlib import Path

from series_b_obj_art_007_result_schema import CASE_ID, REQUIRED_ARTIFACTS, require_result_enum


class ObjArt007ArtifactContractError(ValueError):
    """Raised when obj_art_007 controlled artifacts are missing or unsafe."""


def validate_obj_art_007_artifact_contract(output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir).expanduser().resolve(strict=False)
    missing = [name for name in REQUIRED_ARTIFACTS if not (target / name).exists()]
    if missing:
        raise ObjArt007ArtifactContractError(f"missing required artifacts: {missing}")
    parsed: dict[str, object] = {}
    for name in REQUIRED_ARTIFACTS:
        path = target / name
        text = path.read_text(encoding="utf-8")
        if "dummy_test_artifact_only" in text:
            raise ObjArt007ArtifactContractError(f"{name} is a dummy artifact")
        if '"mock_builder_output": true' in text or '"mock_audit_output": true' in text:
            raise ObjArt007ArtifactContractError(f"{name} is a mock artifact")
        if CASE_ID not in text:
            raise ObjArt007ArtifactContractError(f"{name} does not mention obj_art_007")
        if name == "obj_art_007_controlled_raw_dossier.md" and "no precise page numbers are claimed" not in text:
            raise ObjArt007ArtifactContractError("raw dossier must preserve no-precise-page caveat")
        if path.suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                parsed[name] = payload
    result = parsed.get("obj_art_007_controlled_execution_result.json", {})
    if isinstance(result, dict):
        if result.get("case_id") != CASE_ID:
            raise ObjArt007ArtifactContractError("result case_id must be obj_art_007")
        require_result_enum(str(result.get("result_enum")))
        if result.get("mock_audit_output") is True or result.get("mock_builder_output") is True:
            raise ObjArt007ArtifactContractError("mock outputs are not allowed")
        if result.get("official_baseline_update_performed") is not False:
            raise ObjArt007ArtifactContractError("baseline update flag must be false")
        if result.get("full_series_b_run_performed") is not False:
            raise ObjArt007ArtifactContractError("full Series B flag must be false")
        if result.get("production_default_manifest_integration_performed") is not False:
            raise ObjArt007ArtifactContractError("production default flag must be false")
        if result.get("page_binding_caveat_preserved") is not True:
            raise ObjArt007ArtifactContractError("page binding caveat was not preserved")
        if result.get("precise_page_number_claimed") is not False:
            raise ObjArt007ArtifactContractError("precise page number claim must be false")
    return {"status": "PASS", "artifacts": [str(target / name) for name in REQUIRED_ARTIFACTS]}
