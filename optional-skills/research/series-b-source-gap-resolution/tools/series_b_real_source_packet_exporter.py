#!/usr/bin/env python3
"""Case-scoped real source packet exporter for rel_space_029.

This module converts already-reviewed handoff artifacts into a repo-out source
packet. It does not build a dossier, run audit scoring, run Series B, or touch
production/default retrieval paths.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from rel_space_029_alias_source_guard import AliasSourceGuardError, validate_chunks
from series_b_approved_chunks_loader import (
    ApprovedChunksValidationError,
    load_approved_chunks,
    validate_chunks_against_manifest,
)
from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_controlled_handoff_loader import HandoffValidationError, load_handoff_manifest
from series_b_controlled_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


SOURCE_PACKET_FILENAME = "rel_space_029_controlled_source_packet.json"
SOURCE_PACKET_SCHEMA_VERSION = "rel_space_029.controlled_source_packet.v1.layer1"


class SourcePacketExportError(ValueError):
    """Raised when a source packet cannot be safely exported."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_policy_locks(
    *,
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
) -> None:
    if no_production_default is not True:
        raise SourcePacketExportError("PRODUCTION_DEFAULT_RISK", "no_production_default must be true")
    if no_baseline_update is not True:
        raise SourcePacketExportError("BASELINE_UPDATE_RISK", "no_baseline_update must be true")
    if no_full_series_b is not True:
        raise SourcePacketExportError("FULL_SERIES_B_RISK", "no_full_series_b must be true")


def _source_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for source in manifest.get("professional_sources", []):
        if isinstance(source, dict) and isinstance(source.get("source_id"), str):
            sources[source["source_id"]] = source
    return sources


def _rejected_chunk_state(chunk: dict[str, Any]) -> str | None:
    reject_flags = {
        "is_title_only": "title-only evidence",
        "is_query_echo": "query echo",
        "is_generated_echo": "generated echo",
        "is_image_filename_only": "image filename evidence",
        "is_wrong_context_bema": "standalone or wrong-context bema",
        "is_listing_or_travel_planning": "listing / travel planning source",
    }
    for field, reason in reject_flags.items():
        if chunk.get(field) is True:
            return f"{chunk.get('chunk_id', '<unknown>')}: {reason}"
    return None


def _chunk_source_locator(chunk: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    source_path = source.get("source_path")
    if not source_path:
        raise SourcePacketExportError(
            "MISSING_SOURCE_BACKED_TEXT",
            f"{chunk['chunk_id']} has no source-backed text locator",
        )
    return {
        "type": "source_page_range",
        "source_path": source_path,
        "source_sha256": source.get("source_sha256"),
        "page_start": chunk["page_start"],
        "page_end": chunk["page_end"],
        "chunk_id": chunk["chunk_id"],
    }


def _source_provenance(source: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "license_or_provenance_status",
        "source_group",
        "source_path",
        "source_sha256",
        "ingestion_run_id",
        "formal_ready",
    )
    return {key: source.get(key) for key in keys if key in source}


def _source_record(source: dict[str, Any], chunk_ids: list[str]) -> dict[str, Any]:
    return {
        "source_id": source["source_id"],
        "source_title": source.get("title") or source.get("source_title"),
        "author_or_editor": source.get("author") or source.get("editor") or source.get("author_or_editor"),
        "axis": source.get("axis"),
        "source_hash": source.get("source_sha256"),
        "source_path": source.get("source_path"),
        "provenance_metadata": _source_provenance(source),
        "accepted_chunk_ids": chunk_ids,
        "case_scope_only": True,
    }


def _chunk_record(chunk: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    locator = _chunk_source_locator(chunk, source)
    locator_hash = _sha256_text(json.dumps(locator, sort_keys=True))
    source_text = chunk.get("source_backed_text") or chunk.get("chunk_text") or chunk.get("text")
    return {
        "case_id": chunk.get("case_id", CASE_ID),
        "source_id": chunk["source_id"],
        "source_title": chunk["source_title"],
        "chunk_id": chunk["chunk_id"],
        "page_start": chunk["page_start"],
        "page_end": chunk["page_end"],
        "axis": chunk["axis"],
        "supports_terms": chunk["supports_terms"],
        "supports_sections": chunk["supports_sections"],
        "source_backed_text": source_text,
        "source_backed_text_locator": locator,
        "source_backed_text_hash": _sha256_text(source_text) if isinstance(source_text, str) else locator_hash,
        "reviewer_decision": chunk["reviewer_decision"],
        "wrong_context_guard_passed": chunk["wrong_context_guard_passed"],
        "page_bound": chunk["page_bound"],
        "source_backed_text_exists": chunk["source_backed_text_exists"],
        "source_hash_or_text_hash": source.get("source_sha256") or locator_hash,
        "provenance_metadata": _source_provenance(source),
        "section_target": chunk["supports_sections"],
        "evidence_strength": chunk["evidence_strength"],
    }


def export_rel_space_029_controlled_source_packet(
    *,
    case_id: str,
    approved_chunks_handoff_path: str | Path,
    controlled_handoff_manifest_path: str | Path,
    output_dir: str | Path,
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Export a real source packet artifact for the rel_space_029 harness."""

    if case_id != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "case_id must be rel_space_029")
    _require_policy_locks(
        no_production_default=no_production_default,
        no_baseline_update=no_baseline_update,
        no_full_series_b=no_full_series_b,
    )

    try:
        target_dir = validate_output_dir_policy(output_dir, repo_root=repo_root)
    except ArtifactContractError as exc:
        raise SourcePacketExportError("OUTPUT_DIR_UNSAFE", str(exc)) from exc

    manifest_path = Path(controlled_handoff_manifest_path).expanduser()
    chunks_path = Path(approved_chunks_handoff_path).expanduser()
    try:
        manifest = load_handoff_manifest(manifest_path)
        chunks = load_approved_chunks(chunks_path)
        validate_chunks_against_manifest(chunks, manifest)
        guard_report = validate_chunks(chunks)
    except HandoffValidationError as exc:
        raise SourcePacketExportError("HANDOFF_MANIFEST_MALFORMED", str(exc)) from exc
    except ApprovedChunksValidationError as exc:
        message = str(exc)
        code = "CHUNK_CASE_MISMATCH" if "case_id" in message.lower() else "APPROVED_CHUNKS_MALFORMED"
        raise SourcePacketExportError(code, message) from exc
    except AliasSourceGuardError as exc:
        raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", str(exc)) from exc

    sources = _source_map(manifest)
    chunk_records: list[dict[str, Any]] = []
    source_to_chunk_ids: dict[str, list[str]] = {}
    for chunk in chunks:
        rejected = _rejected_chunk_state(chunk)
        if rejected:
            raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", rejected)
        source = sources.get(chunk["source_id"])
        if source is None:
            raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", f"unknown source_id: {chunk['source_id']}")
        chunk_records.append(_chunk_record(chunk, source))
        source_to_chunk_ids.setdefault(chunk["source_id"], []).append(chunk["chunk_id"])

    source_records = [
        _source_record(sources[source_id], chunk_ids)
        for source_id, chunk_ids in sorted(source_to_chunk_ids.items())
    ]
    packet = {
        "schema_version": SOURCE_PACKET_SCHEMA_VERSION,
        "case_id": CASE_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_packet_id": _sha256_text(
            f"{CASE_ID}:{manifest_path}:{chunks_path}:{_sha256_file(manifest_path)}:{_sha256_file(chunks_path)}"
        ),
        "mock_source_packet": False,
        "policy_locks": {
            "no_production_default": True,
            "no_baseline_update": True,
            "no_full_series_b": True,
            "production_default_loader_enabled": False,
            "official_baseline_update_enabled": False,
            "full_series_b_enabled": False,
        },
        "manifest_ref": {
            "path": str(manifest_path),
            "sha256": _sha256_file(manifest_path),
            "schema_version": manifest.get("schema_version"),
        },
        "approved_chunks_ref": {
            "path": str(chunks_path),
            "sha256": _sha256_file(chunks_path),
            "approved_chunks_count": len(chunks),
        },
        "required_terms": [
            "synagogue",
            "Torah",
            "Torah ark / Aron ha-Kodesh",
            "bimah / Torah reading platform",
            "orientation",
        ],
        "required_axes": manifest.get("required_professional_axes", []),
        "required_sections": ["spatial_structure", "historical_layers", "theme_tracks"],
        "sources": source_records,
        "chunks": chunk_records,
        "traceability": {
            "source_id_to_chunk_ids": source_to_chunk_ids,
            "chunk_id_to_page_range": {
                chunk["chunk_id"]: [chunk["page_start"], chunk["page_end"]] for chunk in chunk_records
            },
            "chunk_id_to_axis": {chunk["chunk_id"]: chunk["axis"] for chunk in chunk_records},
            "chunk_id_to_section_targets": {
                chunk["chunk_id"]: chunk["section_target"] for chunk in chunk_records
            },
        },
        "guard_summary": guard_report,
        **EXECUTION_FALSE_FLAGS,
    }

    target_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = target_dir / SOURCE_PACKET_FILENAME
    artifact_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "SOURCE_PACKET_EXPORTED", "artifact_path": str(artifact_path), "packet": packet}
