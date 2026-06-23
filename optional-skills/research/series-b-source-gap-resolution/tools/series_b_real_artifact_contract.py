#!/usr/bin/env python3
"""Real-mode artifact contract checks for rel_space_029 layer 1."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_controlled_result_schema import REQUIRED_ARTIFACTS


class RealArtifactContractError(ValueError):
    """Raised when real-mode artifacts are incomplete or unsafe."""


def validate_real_mode_artifact_contract(output_dir: str | Path, *, allow_mock: bool = False) -> dict[str, object]:
    target = Path(output_dir).expanduser().resolve(strict=False)
    missing = [name for name in REQUIRED_ARTIFACTS if not (target / name).exists()]
    if missing:
        raise RealArtifactContractError(f"missing required artifacts: {missing}")

    parsed_json: dict[str, object] = {}
    for name in REQUIRED_ARTIFACTS:
        path = target / name
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                parsed_json[name] = payload
                if payload.get("dummy_test_artifact_only") is True:
                    raise RealArtifactContractError(f"{name} is a dummy artifact")

    result = parsed_json.get("rel_space_029_controlled_execution_result.json", {})
    if isinstance(result, dict):
        if result.get("result_enum") == "PASS_CONTROLLED_REGRESSION":
            raise RealArtifactContractError("layer 1 real-mode skeleton must not write PASS_CONTROLLED_REGRESSION")
        if not allow_mock and (result.get("mock_audit_output") or result.get("mock_builder_output")):
            raise RealArtifactContractError("mock artifacts are not allowed without allow_mock")
    return {"status": "PASS", "artifacts": [str(target / name) for name in REQUIRED_ARTIFACTS]}
