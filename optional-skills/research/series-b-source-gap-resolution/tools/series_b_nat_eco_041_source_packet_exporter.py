#!/usr/bin/env python3
"""Case-scoped source packet exporter for nat_eco_041."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nat_eco_041_alias_source_guard import NatEco041GuardError, validate_chunks
from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_nat_eco_041_result_schema import (
    CASE_ID,
    EXECUTION_FALSE_FLAGS,
    REQUIRED_CONTEXT_AXES,
    REQUIRED_PROFESSIONAL_AXES,
    REQUIRED_SECTIONS,
    REQUIRED_TERMS,
)


SOURCE_PACKET_FILENAME = "nat_eco_041_controlled_source_packet.json"


class SourcePacketExportError(ValueError):
    """Raised when the nat_eco_041 source packet cannot be exported safely."""

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


def _require_policy(
    *,
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
    manifest: dict[str, Any],
    chunks_payload: dict[str, Any],
) -> None:
    if no_production_default is not True:
        raise SourcePacketExportError("BLOCKED_PRODUCTION_DEFAULT_RISK", "no_production_default must be true")
    if no_baseline_update is not True:
        raise SourcePacketExportError("BLOCKED_BASELINE_UPDATE_RISK", "no_baseline_update must be true")
    if no_full_series_b is not True:
        raise SourcePacketExportError("BLOCKED_FULL_SERIES_B_RISK", "no_full_series_b must be true")
    for payload, label in ((manifest, "manifest"), (chunks_payload, "chunks")):
        locks = payload.get("policy_locks")
        if not isinstance(locks, dict):
            raise SourcePacketExportError("HANDOFF_MANIFEST_MALFORMED", f"{label} policy_locks is required")
        if locks.get("production_default_loader_enabled") is not False:
            raise SourcePacketExportError("BLOCKED_PRODUCTION_DEFAULT_RISK", f"{label} production default enabled")
        if locks.get("official_baseline_update_enabled") is not False:
            raise SourcePacketExportError("BLOCKED_BASELINE_UPDATE_RISK", f"{label} baseline update enabled")
        if locks.get("full_series_b_enabled") is not False:
            raise SourcePacketExportError("BLOCKED_FULL_SERIES_B_RISK", f"{label} full Series B enabled")


def _locator_pages(locator: dict[str, Any]) -> tuple[int | None, int | None]:
    start = locator.get("page_start")
    end = locator.get("page_end")
    return (start if isinstance(start, int) else None, end if isinstance(end, int) else None)


def _validate_professional_chunk(chunk: dict[str, Any]) -> None:
    if chunk.get("case_id") != CASE_ID:
        raise SourcePacketExportError("CHUNK_CASE_MISMATCH", "professional chunk case_id must be nat_eco_041")
    if chunk.get("reviewer_decision") != "FORMAL_READY_APPROVED_WITH_BINDING_CAVEAT":
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "professional chunk decision must preserve binding caveat")
    if chunk.get("binding_status") != "PARTIAL_SECTION_LOCATOR_USED":
        raise SourcePacketExportError("BLOCKED_BINDING_INSUFFICIENT", "professional binding caveat is missing")
    locator = chunk.get("source_backed_text_locator")
    if not isinstance(locator, dict):
        raise SourcePacketExportError("MISSING_SOURCE_BACKED_LOCATOR", "professional chunk requires locator")
    page_start, page_end = _locator_pages(locator)
    if page_start is None or page_end is None:
        raise SourcePacketExportError("MISSING_SOURCE_BACKED_LOCATOR", "professional chunk locator requires page range")


def _validate_context_chunk(chunk: dict[str, Any]) -> None:
    if chunk.get("case_id") != CASE_ID:
        raise SourcePacketExportError("CHUNK_CASE_MISMATCH", "context chunk case_id must be nat_eco_041")
    if chunk.get("reviewer_decision") != "CONTEXT_READY_APPROVED":
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "context chunk decision must be CONTEXT_READY_APPROVED")
    if chunk.get("binding_status") not in {"CONTEXT_ENTRY_BOUND", "CONTEXT_SECTION_BOUND"}:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "context chunk binding status is not accepted")
    locator = chunk.get("source_backed_text_locator")
    if not isinstance(locator, dict) or not locator.get("entry_locator"):
        raise SourcePacketExportError("MISSING_SOURCE_BACKED_LOCATOR", "context chunk requires entry locator")


def _validate_common_chunk(chunk: dict[str, Any]) -> None:
    if chunk.get("wrong_context_guard_passed") is not True:
        raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", "wrong_context_guard_passed must be true")
    for field in ("title_only", "query_echo", "generated_echo", "image_filename_only", "wrong_domain", "listing_or_planning_noise", "sports_noise"):
        if chunk.get(field) is True:
            raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", f"{chunk.get('chunk_id')} has rejected flag {field}")
    if not isinstance(chunk.get("source_backed_text_locator"), dict):
        raise SourcePacketExportError("MISSING_SOURCE_BACKED_LOCATOR", "source-backed locator is required")


def _chunk_record(chunk: dict[str, Any], *, chunk_group: str) -> dict[str, Any]:
    locator = chunk["source_backed_text_locator"]
    page_start, page_end = _locator_pages(locator)
    locator_hash = _sha256_text(json.dumps(locator, sort_keys=True))
    return {
        "case_id": CASE_ID,
        "chunk_group": chunk_group,
        "source_id": chunk["source_id"],
        "source_title": chunk["source_title"],
        "source_type": chunk.get("source_type"),
        "chunk_id": chunk["chunk_id"],
        "page_start": page_start,
        "page_end": page_end,
        "axis": chunk.get("axis_candidate", []),
        "supports_terms": chunk.get("supports_terms", []),
        "supports_sections": chunk.get("supports_sections", []),
        "source_backed_text": chunk.get("source_backed_text"),
        "source_backed_text_locator": locator,
        "source_backed_text_locator_hash": locator_hash,
        "source_hash_or_text_hash": chunk.get("source_sha256") or locator_hash,
        "reviewer_decision": chunk["reviewer_decision"],
        "wrong_context_guard_passed": chunk["wrong_context_guard_passed"],
        "binding_status": chunk["binding_status"],
        "binding_caveat_preserved": True,
        "provenance_metadata": chunk.get("provenance_metadata", {}),
        "section_target": chunk.get("supports_sections", []),
        "evidence_strength": chunk["evidence_strength"],
    }


def export_nat_eco_041_controlled_source_packet(
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
    """Export a nat_eco_041 controlled source packet outside the repo."""

    if case_id != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "case_id must be nat_eco_041")
    try:
        target_dir = validate_output_dir_policy(output_dir, repo_root=repo_root)
    except ArtifactContractError as exc:
        raise SourcePacketExportError("OUTPUT_DIR_UNSAFE", str(exc)) from exc
    target_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = Path(controlled_handoff_manifest_path).expanduser()
    chunks_path = Path(approved_chunks_handoff_path).expanduser()
    manifest = _load_json(manifest_path, kind="handoff_manifest")
    chunks_payload = _load_json(chunks_path, kind="approved_chunks")
    if manifest.get("case_id") != CASE_ID or chunks_payload.get("case_id") != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "handoff inputs must be nat_eco_041 scoped")
    if manifest.get("formal_ready_decision") != "NAT_ECO_041_FORMAL_READY_REVIEW_APPROVED_WITH_BINDING_CAVEAT":
        raise SourcePacketExportError("HANDOFF_MANIFEST_MALFORMED", "formal-ready decision is not approved with caveat")
    _require_policy(
        no_production_default=no_production_default,
        no_baseline_update=no_baseline_update,
        no_full_series_b=no_full_series_b,
        manifest=manifest,
        chunks_payload=chunks_payload,
    )

    professional_chunks = chunks_payload.get("professional_chunks")
    context_chunks = chunks_payload.get("context_chunks")
    if not isinstance(professional_chunks, list) or len(professional_chunks) != 13:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "expected 13 professional chunks")
    if not isinstance(context_chunks, list) or len(context_chunks) != 28:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "expected 28 context chunks")
    if chunks_payload.get("excluded_rejected_deferred_chunks_included") is not False:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "rejected/deferred chunks are included")

    for chunk in professional_chunks:
        if not isinstance(chunk, dict):
            raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "professional chunk must be an object")
        _validate_common_chunk(chunk)
        _validate_professional_chunk(chunk)
    for chunk in context_chunks:
        if not isinstance(chunk, dict):
            raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "context chunk must be an object")
        _validate_common_chunk(chunk)
        _validate_context_chunk(chunk)
    try:
        guard_report = validate_chunks([*professional_chunks, *context_chunks])
    except NatEco041GuardError as exc:
        raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", str(exc)) from exc

    chunk_records = [
        *[_chunk_record(chunk, chunk_group="professional") for chunk in professional_chunks],
        *[_chunk_record(chunk, chunk_group="context") for chunk in context_chunks],
    ]
    source_records: dict[str, dict[str, Any]] = {}
    for record in chunk_records:
        source_records.setdefault(
            record["source_id"],
            {
                "source_id": record["source_id"],
                "source_title": record["source_title"],
                "source_type": record["source_type"],
                "axes": record["axis"],
                "accepted_chunk_ids": [],
                "case_scope_only": True,
            },
        )["accepted_chunk_ids"].append(record["chunk_id"])

    caveats = {
        "professional_binding": "PARTIAL_SECTION_LOCATOR_USED",
        "context_binding": "CONTEXT_ENTRY_BOUND / CONTEXT_SECTION_BOUND",
        "dune_migration": "marginal_related_not_strong_exact_term_evidence",
        "binding_caveat_preserved": True,
        "dune_migration_caveat_preserved": True,
    }
    packet = {
        "schema_version": "nat_eco_041.controlled_source_packet.v1",
        "case_id": CASE_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_packet_id": _sha256_text(f"{CASE_ID}:{_sha256_file(manifest_path)}:{_sha256_file(chunks_path)}"),
        "mock_source_packet": False,
        "policy_locks": {
            "no_production_default": True,
            "no_baseline_update": True,
            "no_full_series_b": True,
            "production_default_loader_enabled": False,
            "official_baseline_update_enabled": False,
            "full_series_b_enabled": False,
        },
        "manifest_ref": {"path": str(manifest_path), "sha256": _sha256_file(manifest_path)},
        "approved_chunks_ref": {
            "path": str(chunks_path),
            "sha256": _sha256_file(chunks_path),
            "professional_chunks_count": len(professional_chunks),
            "context_chunks_count": len(context_chunks),
            "total_chunks_count": len(chunk_records),
        },
        "required_terms": REQUIRED_TERMS,
        "required_professional_axes": REQUIRED_PROFESSIONAL_AXES,
        "required_context_axes": REQUIRED_CONTEXT_AXES,
        "required_sections": REQUIRED_SECTIONS,
        "caveats": caveats,
        "sources": sorted(source_records.values(), key=lambda value: value["source_id"]),
        "chunks": chunk_records,
        "professional_chunks": [record for record in chunk_records if record["chunk_group"] == "professional"],
        "context_chunks": [record for record in chunk_records if record["chunk_group"] == "context"],
        "guard_report": guard_report,
        "single_case_controlled_dryrun_evidence": True,
        **EXECUTION_FALSE_FLAGS,
    }
    path = target_dir / SOURCE_PACKET_FILENAME
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "SOURCE_PACKET_EXPORTED",
        "artifact_path": str(path),
        "professional_chunk_count": len(professional_chunks),
        "context_chunk_count": len(context_chunks),
        "chunk_count": len(chunk_records),
    }
