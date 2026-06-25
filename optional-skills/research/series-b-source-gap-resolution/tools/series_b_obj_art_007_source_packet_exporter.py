#!/usr/bin/env python3
"""Case-scoped source packet exporter for obj_art_007."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from obj_art_007_alias_source_guard import ObjArt007GuardError, validate_chunks
from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_obj_art_007_result_schema import (
    APPROVED_REVIEWER_DECISION,
    CASE_ID,
    EXECUTION_FALSE_FLAGS,
    EXPECTED_FORMAL_READY_DECISION,
    REQUIRED_AXES,
    REQUIRED_SECTIONS,
    REQUIRED_TERMS,
)

SOURCE_PACKET_FILENAME = "obj_art_007_controlled_source_packet.json"


class SourcePacketExportError(ValueError):
    """Raised when the obj_art_007 source packet cannot be exported safely."""

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
) -> None:
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


def _axis_list(chunk: dict[str, Any]) -> list[str]:
    axis = chunk.get("axis")
    if isinstance(axis, list):
        axes = {str(item) for item in axis}
    elif isinstance(axis, str):
        axes = {axis}
    else:
        axes = set()
    terms = " ".join(str(term).lower() for term in chunk.get("supports_terms", []))
    source = str(chunk.get("source_id", "")).lower()
    if "dougong_mechanical_behavior" in source or any(term in terms for term in ("load", "seismic", "energy", "bearing", "vertical")):
        axes.add("engineering_book")
        axes.add("structural_mechanics_source")
    if any(term in terms for term in ("mortise", "dowel", "timber joinery", "interlocking")):
        axes.add("materials_book")
    if "feng_chinese_architecture" in source or "liang_chinese_architecture" in source:
        axes.add("architecture_book")
    return sorted(axes)


def _chunk_record(chunk: dict[str, Any]) -> dict[str, Any]:
    locator = dict(chunk.get("source_backed_text_locator") or {})
    page_start = chunk.get("page_start")
    page_end = chunk.get("page_end")
    page_binding_caveat = page_start == 0 and page_end == 0
    return {
        "case_id": CASE_ID,
        "source_id": chunk["source_id"],
        "source_title": chunk["source_title"],
        "chunk_id": chunk["chunk_id"],
        "page_start": page_start,
        "page_end": page_end,
        "page_bound_status": chunk.get("page_bound_status"),
        "axis": _axis_list(chunk),
        "supports_terms": chunk.get("supports_terms", []),
        "supports_sections": chunk.get("supports_sections", []),
        "source_backed_text_exists": True,
        "source_backed_text_locator": locator,
        "source_backed_text_locator_hash": _sha256_text(json.dumps(locator, sort_keys=True)),
        "reviewer_decision": APPROVED_REVIEWER_DECISION,
        "wrong_context_guard_passed": True,
        "page_binding_caveat_preserved": page_binding_caveat,
        "precise_page_number_claimed": False,
        "title_only": False,
        "query_echo": False,
        "generated_echo": False,
        "image_filename_only": False,
        "README_summary": False,
        "listing_or_travel_planning": False,
        "wrong_domain": False,
        "evidence_strength": chunk.get("evidence_strength", "direct"),
        "source_hash_or_text_hash": chunk.get("source_hash_or_text_hash") or locator.get("text_sha256"),
        "provenance_metadata": chunk.get("provenance_metadata", {}),
        "section_target": chunk.get("section_target") or chunk.get("supports_sections", []),
    }


def validate_obj_art_007_handoff_inputs(
    *,
    manifest: dict[str, Any],
    chunks_payload: dict[str, Any],
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
) -> list[dict[str, Any]]:
    if manifest.get("case_id") != CASE_ID or chunks_payload.get("case_id") != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "handoff inputs must be obj_art_007 scoped")
    if manifest.get("formal_ready_decision") != EXPECTED_FORMAL_READY_DECISION:
        raise SourcePacketExportError("HANDOFF_MANIFEST_MALFORMED", "formal-ready decision is not approved with page-binding caveat")
    if "0" not in str(manifest.get("page_binding_caveat", "")):
        raise SourcePacketExportError("BLOCKED_BINDING_INSUFFICIENT", "page binding caveat is missing from manifest")
    _require_policy(
        no_production_default=no_production_default,
        no_baseline_update=no_baseline_update,
        no_full_series_b=no_full_series_b,
        manifest=manifest,
    )
    chunks = chunks_payload.get("approved_chunks")
    if not isinstance(chunks, list) or len(chunks) != 14:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "expected 14 approved chunks")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "approved chunk must be an object")
        if chunk.get("case_id") != CASE_ID:
            raise SourcePacketExportError("CASE_ID_MISMATCH", "approved chunk case_id must be obj_art_007")
        if chunk.get("reviewer_decision") != APPROVED_REVIEWER_DECISION:
            raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "approved chunk reviewer decision is not accepted")
    try:
        validate_chunks(chunks)
    except ObjArt007GuardError as exc:
        raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", str(exc)) from exc
    return chunks


def export_obj_art_007_controlled_source_packet(
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
    """Export an obj_art_007 controlled source packet outside the repo."""

    if case_id != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "case_id must be obj_art_007")
    try:
        target_dir = validate_output_dir_policy(output_dir, repo_root=repo_root)
    except ArtifactContractError as exc:
        raise SourcePacketExportError("OUTPUT_DIR_UNSAFE", str(exc)) from exc
    target_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = Path(controlled_handoff_manifest_path).expanduser()
    chunks_path = Path(approved_chunks_handoff_path).expanduser()
    manifest = _load_json(manifest_path, kind="handoff_manifest")
    chunks_payload = _load_json(chunks_path, kind="approved_chunks")
    chunks = validate_obj_art_007_handoff_inputs(
        manifest=manifest,
        chunks_payload=chunks_payload,
        no_production_default=no_production_default,
        no_baseline_update=no_baseline_update,
        no_full_series_b=no_full_series_b,
    )

    chunk_records = [_chunk_record(chunk) for chunk in chunks]
    source_records: dict[str, dict[str, Any]] = {}
    for record in chunk_records:
        source_records.setdefault(
            record["source_id"],
            {
                "source_id": record["source_id"],
                "source_title": record["source_title"],
                "axes": sorted(set(record["axis"])),
                "accepted_chunk_ids": [],
                "case_scope_only": True,
            },
        )["accepted_chunk_ids"].append(record["chunk_id"])

    caveats = {
        "page_binding_caveat_preserved": True,
        "zero_zero_page_binding_allowed_as_weak_locator_only": True,
        "precise_page_numbers_claimed": False,
        "chunk_id_section_locator_text_sha256_required": True,
        "readme_title_only_generated_query_echo_count_as_evidence": False,
        "context_sources_trace_only": True,
    }
    packet = {
        "schema_version": "obj_art_007.controlled_source_packet.v1",
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
        "approved_chunks_ref": {"path": str(chunks_path), "sha256": _sha256_file(chunks_path), "approved_chunks_count": len(chunks)},
        "required_terms": REQUIRED_TERMS,
        "required_axes": REQUIRED_AXES,
        "required_sections": REQUIRED_SECTIONS,
        "sources": sorted(source_records.values(), key=lambda value: value["source_id"]),
        "chunks": chunk_records,
        "guard_report": validate_chunks(chunks),
        "caveats": caveats,
        "single_case_controlled_dryrun_evidence": True,
        **EXECUTION_FALSE_FLAGS,
    }
    path = target_dir / SOURCE_PACKET_FILENAME
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "SOURCE_PACKET_EXPORTED", "artifact_path": str(path), "chunk_count": len(chunk_records)}
