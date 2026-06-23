#!/usr/bin/env python3
"""Fail-closed rel_space_029 dossier builder adapter.

Layer 1 intentionally does not connect a real builder. Tests may opt into a
mock builder path, which writes a clearly marked mock dossier and never counts
as a controlled regression pass.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_controlled_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


RAW_DOSSIER_FILENAME = "rel_space_029_controlled_raw_dossier.md"


class BuilderAdapterError(ValueError):
    """Raised when the builder adapter blocks execution."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_source_packet(path: str | Path) -> dict[str, Any]:
    source_packet_path = Path(path).expanduser()
    with source_packet_path.open("r", encoding="utf-8") as handle:
        packet = json.load(handle)
    if not isinstance(packet, dict):
        raise BuilderAdapterError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet root must be a JSON object")
    if packet.get("case_id") != CASE_ID:
        raise BuilderAdapterError("CASE_ID_MISMATCH", "source packet case_id must be rel_space_029")
    return packet


def build_rel_space_029_controlled_raw_dossier(
    *,
    case_id: str,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
    use_mock_builder: bool = False,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a raw dossier only when explicitly using the mock builder."""

    if case_id != CASE_ID:
        raise BuilderAdapterError("CASE_ID_MISMATCH", "case_id must be rel_space_029")
    if no_production_default is not True:
        raise BuilderAdapterError("BLOCKED_PRODUCTION_DEFAULT_RISK", "no_production_default must be true")
    if no_baseline_update is not True:
        raise BuilderAdapterError("BLOCKED_BASELINE_UPDATE_RISK", "no_baseline_update must be true")
    if no_full_series_b is not True:
        raise BuilderAdapterError("BLOCKED_FULL_SERIES_B_RISK", "no_full_series_b must be true")
    if not use_mock_builder:
        raise BuilderAdapterError(
            "BLOCKED_BUILDER_ENTRY_UNIMPLEMENTED",
            "real rel_space_029 dossier builder API is not implemented in layer 1",
        )

    try:
        target_dir = validate_output_dir_policy(output_dir, repo_root=repo_root)
    except ArtifactContractError as exc:
        raise BuilderAdapterError("OUTPUT_DIR_UNSAFE", str(exc)) from exc
    packet = _load_source_packet(source_packet_path)
    target_dir.mkdir(parents=True, exist_ok=True)

    terms = sorted({term for chunk in packet.get("chunks", []) for term in chunk.get("supports_terms", [])})
    source_ids = sorted({chunk.get("source_id") for chunk in packet.get("chunks", []) if chunk.get("source_id")})
    chunk_ids = [chunk.get("chunk_id") for chunk in packet.get("chunks", []) if chunk.get("chunk_id")]
    body = f"""# rel_space_029 controlled raw dossier

mock_builder_output: true
case_id: {CASE_ID}
generated_at: {datetime.now(timezone.utc).isoformat()}
source_packet: {source_packet_path}
handoff_manifest: {handoff_manifest_path}

## spatial_structure

Mock builder output only. The synagogue spatial structure is represented with
Torah ark / Aron ha-Kodesh orientation, bimah / Torah reading platform context,
and congregation layout bindings from the source packet.

## historical_layers

Mock builder output only. The historical layer keeps the synagogue, Torah,
Jewish liturgy, and orientation claims bound to approved source chunks.

## theme_tracks

Mock builder output only. Theme tracks preserve synagogue sacred-space terms:
{", ".join(terms)}.

## source_bindings

source_ids: {", ".join(source_ids)}
chunk_ids: {", ".join(chunk_ids)}
"""
    artifact_path = target_dir / RAW_DOSSIER_FILENAME
    artifact_path.write_text(body, encoding="utf-8")
    return {
        "status": "MOCK_BUILDER_OUTPUT_WRITTEN",
        "artifact_path": str(artifact_path),
        "mock_builder_output": True,
        **EXECUTION_FALSE_FLAGS,
    }
