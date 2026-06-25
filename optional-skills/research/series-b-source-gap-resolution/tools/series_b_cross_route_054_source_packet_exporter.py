#!/usr/bin/env python3
"""Case-scoped source packet exporter for cross_route_054."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cross_route_054_alias_source_guard import CrossRoute054GuardError, validate_chunks
from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_cross_route_054_result_schema import (
    APPROVED_REVIEWER_DECISION,
    CASE_ID,
    EXECUTION_FALSE_FLAGS,
    EXPECTED_FORMAL_READY_DECISION,
    REQUIRED_AXES,
    REQUIRED_SECTIONS,
    REQUIRED_TERMS,
)

SOURCE_PACKET_FILENAME = "cross_route_054_controlled_source_packet.json"


class SourcePacketExportError(ValueError):
    """Raised when the cross_route_054 source packet cannot be exported safely."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: str | Path, *, kind: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SourcePacketExportError(f"{kind.upper()}_NOT_FOUND", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise SourcePacketExportError(f"{kind.upper()}_MALFORMED", str(exc)) from exc
    if not isinstance(payload, dict):
        raise SourcePacketExportError(f"{kind.upper()}_MALFORMED", f"{kind} root must be a JSON object")
    return payload


def _require_policy(*, no_production_default: bool, no_baseline_update: bool, no_full_series_b: bool, manifest: dict[str, Any]) -> None:
    if no_production_default is not True:
        raise SourcePacketExportError("BLOCKED_PRODUCTION_DEFAULT_RISK", "no_production_default must be true")
    if no_baseline_update is not True:
        raise SourcePacketExportError("BLOCKED_BASELINE_UPDATE_RISK", "no_baseline_update must be true")
    if no_full_series_b is not True:
        raise SourcePacketExportError("BLOCKED_FULL_SERIES_B_RISK", "no_full_series_b must be true")
    policy = manifest.get("production_path_policy")
    if not isinstance(policy, dict):
        raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", "manifest lacks production_path_policy")
    if policy.get("case_scoped_only") is not True:
        raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", "manifest is not case-scoped")
    if policy.get("production_default_loader_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_PRODUCTION_DEFAULT_RISK", "manifest enables production default")
    if policy.get("official_baseline_update_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_BASELINE_UPDATE_RISK", "manifest enables baseline update")
    if policy.get("full_series_b_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_FULL_SERIES_B_RISK", "manifest enables full Series B")


def _chunk_record(chunk: dict[str, Any]) -> dict[str, Any]:
    text = str(chunk.get("source_backed_text") or "")
    if not text.strip():
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", f"missing source-backed text: {chunk.get('chunk_id')}")
    source_file = str(chunk.get("source_file") or chunk.get("provenance_metadata", {}).get("source_file") or "")
    if source_file.endswith("README.md") or "sustainable_tourism_case_study" in source_file:
        raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", f"forbidden source file in approved chunks: {source_file}")
    return {
        "case_id": CASE_ID,
        "source_id": chunk["source_id"],
        "source_title": chunk["source_title"],
        "source_file": source_file,
        "source_type": chunk.get("source_type"),
        "chunk_id": chunk["chunk_id"],
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "page_bound_status": chunk.get("page_bound_status"),
        "axis": list(chunk.get("axis") or []),
        "supports_terms": chunk.get("supports_terms", []),
        "supports_sections": chunk.get("supports_sections", []),
        "source_backed_text": text,
        "source_backed_text_hash": _sha256_text(text),
        "reviewer_decision": APPROVED_REVIEWER_DECISION,
        "wrong_context_guard_passed": True,
        "title_only": False,
        "query_echo": False,
        "generated_echo": False,
        "image_filename_only": False,
        "README_summary": False,
        "listing_or_travel_planning": False,
        "wrong_domain": False,
        "evidence_strength": chunk.get("evidence_strength", "direct"),
        "source_hash_or_text_hash": chunk.get("source_hash") or chunk.get("text_sha256") or _sha256_text(text),
        "provenance_metadata": chunk.get("provenance_metadata", {}),
        "section_target": chunk.get("supports_sections", []),
    }


def validate_cross_route_054_handoff_inputs(*, manifest: dict[str, Any], chunks_payload: dict[str, Any], no_production_default: bool, no_baseline_update: bool, no_full_series_b: bool) -> list[dict[str, Any]]:
    if manifest.get("case_id") != CASE_ID or chunks_payload.get("case_id") != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "handoff inputs must be cross_route_054 scoped")
    if manifest.get("formal_ready_decision") != EXPECTED_FORMAL_READY_DECISION:
        raise SourcePacketExportError("HANDOFF_MANIFEST_MALFORMED", "formal-ready decision is not approved with caveat")
    _require_policy(no_production_default=no_production_default, no_baseline_update=no_baseline_update, no_full_series_b=no_full_series_b, manifest=manifest)
    chunks = chunks_payload.get("approved_chunks")
    if not isinstance(chunks, list) or len(chunks) != 9:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "expected 9 approved chunks")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "approved chunk must be an object")
        if chunk.get("case_id") != CASE_ID:
            raise SourcePacketExportError("CASE_ID_MISMATCH", "approved chunk case_id must be cross_route_054")
        if chunk.get("reviewer_decision") != APPROVED_REVIEWER_DECISION:
            raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "approved chunk reviewer decision is not accepted")
    try:
        validate_chunks(chunks)
    except CrossRoute054GuardError as exc:
        raise SourcePacketExportError(exc.error_code, str(exc)) from exc
    return chunks


def export_cross_route_054_controlled_source_packet(*, case_id: str, approved_chunks_handoff_path: str | Path, controlled_handoff_manifest_path: str | Path, output_dir: str | Path, no_production_default: bool, no_baseline_update: bool, no_full_series_b: bool, repo_root: str | Path | None = None) -> dict[str, Any]:
    if case_id != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "case_id must be cross_route_054")
    try:
        target_dir = validate_output_dir_policy(output_dir, repo_root=repo_root)
    except ArtifactContractError as exc:
        raise SourcePacketExportError("OUTPUT_DIR_UNSAFE", str(exc)) from exc
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(controlled_handoff_manifest_path).expanduser()
    chunks_path = Path(approved_chunks_handoff_path).expanduser()
    manifest = _load_json(manifest_path, kind="handoff_manifest")
    chunks_payload = _load_json(chunks_path, kind="approved_chunks")
    chunks = validate_cross_route_054_handoff_inputs(manifest=manifest, chunks_payload=chunks_payload, no_production_default=no_production_default, no_baseline_update=no_baseline_update, no_full_series_b=no_full_series_b)
    chunk_records = [_chunk_record(chunk) for chunk in chunks]
    source_records: dict[str, dict[str, Any]] = {}
    for record in chunk_records:
        source_records.setdefault(record["source_id"], {"source_id": record["source_id"], "source_title": record["source_title"], "source_file": record["source_file"], "axes": sorted(set(record["axis"])), "accepted_chunk_ids": [], "case_scope_only": True})["accepted_chunk_ids"].append(record["chunk_id"])
    packet = {
        "schema_version": "cross_route_054.controlled_source_packet.v1",
        "case_id": CASE_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_packet_id": _sha256_text(f"{CASE_ID}:{_sha256_file(manifest_path)}:{_sha256_file(chunks_path)}"),
        "mock_source_packet": False,
        "policy_locks": {"no_production_default": True, "no_baseline_update": True, "no_full_series_b": True, "production_default_loader_enabled": False, "official_baseline_update_enabled": False, "full_series_b_enabled": False},
        "manifest_ref": {"path": str(manifest_path), "sha256": _sha256_file(manifest_path)},
        "approved_chunks_ref": {"path": str(chunks_path), "sha256": _sha256_file(chunks_path), "approved_chunks_count": len(chunks)},
        "required_terms": REQUIRED_TERMS,
        "required_axes": REQUIRED_AXES,
        "required_sections": REQUIRED_SECTIONS,
        "sources": sorted(source_records.values(), key=lambda value: value["source_id"]),
        "chunks": chunk_records,
        "guard_report": validate_chunks(chunks),
        "caveats": {"unesco_pdfs_not_used": True, "documents_index_candidate_supporting_only": True, "route_listing_guard_required": True, "readme_cloudflare_title_generated_count_as_evidence": False},
        "single_case_controlled_dryrun_evidence": True,
        **EXECUTION_FALSE_FLAGS,
    }
    path = target_dir / SOURCE_PACKET_FILENAME
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "PASS_SOURCE_PACKET_EXPORTED", "artifact_path": str(path), "approved_chunk_count": len(chunks), **EXECUTION_FALSE_FLAGS}
