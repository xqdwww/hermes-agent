#!/usr/bin/env python3
"""Case-scoped source packet exporter for obj_art_003."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from obj_art_003_alias_source_guard import ObjArt003GuardError, validate_chunks
from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_obj_art_003_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS, REQUIRED_AXES, REQUIRED_SECTIONS, REQUIRED_TERMS


SOURCE_PACKET_FILENAME = "obj_art_003_controlled_source_packet.json"


class SourcePacketExportError(ValueError):
    """Raised when the obj_art_003 source packet cannot be exported safely."""

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
    policy = manifest.get("production_path_policy")
    if not isinstance(policy, dict):
        raise SourcePacketExportError("HANDOFF_MANIFEST_MALFORMED", "production_path_policy is required")
    if policy.get("production_default_loader_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_PRODUCTION_DEFAULT_RISK", "production default is enabled")
    if policy.get("official_baseline_update_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_BASELINE_UPDATE_RISK", "baseline update is enabled")
    if policy.get("full_series_b_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_FULL_SERIES_B_RISK", "full Series B is enabled")
    chunk_policy = chunks_payload.get("production_path_policy", {})
    if isinstance(chunk_policy, dict) and chunk_policy.get("production_default_loader_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_PRODUCTION_DEFAULT_RISK", "chunk handoff production default is enabled")


def _validate_chunk(chunk: dict[str, Any]) -> None:
    if chunk.get("case_id") != CASE_ID:
        raise SourcePacketExportError("CHUNK_CASE_MISMATCH", "approved chunk case_id must be obj_art_003")
    if chunk.get("reviewer_decision") != "FORMAL_READY_APPROVED":
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "reviewer_decision must be FORMAL_READY_APPROVED")
    if chunk.get("wrong_context_guard_passed") is not True:
        raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", "wrong_context_guard_passed must be true")
    if chunk.get("page_bound") is not True or not isinstance(chunk.get("page_start"), int) or not isinstance(chunk.get("page_end"), int):
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "chunk must be page-bound")
    text = chunk.get("source_backed_text")
    locator = chunk.get("source_backed_text_locator")
    if not isinstance(text, str) and not locator:
        raise SourcePacketExportError("MISSING_SOURCE_BACKED_TEXT", "chunk requires source-backed text or locator")
    if isinstance(text, str) and len(text.strip()) < 250:
        raise SourcePacketExportError("MISSING_SOURCE_BACKED_TEXT", "source-backed text is too short")
    for field in ("is_title_only", "is_query_echo", "is_generated_echo", "is_image_filename_only", "is_wrong_context", "is_listing_or_travel_planning"):
        if chunk.get(field) is True:
            raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", f"{chunk['chunk_id']} has rejected flag {field}")


def export_obj_art_003_controlled_source_packet(
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
    """Export an obj_art_003 controlled source packet outside the repo."""

    if case_id != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "case_id must be obj_art_003")
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
        raise SourcePacketExportError("CASE_ID_MISMATCH", "handoff inputs must be obj_art_003 scoped")
    if manifest.get("archaeology_axis_decision") != "ARCHAEOLOGY_AXIS_NOT_HARD_REQUIRED_CONFIRMED":
        raise SourcePacketExportError("BLOCKED_CASE_RULE_TRACE_UNCLEAR", "archaeology axis decision is not confirmed")
    _require_policy(
        no_production_default=no_production_default,
        no_baseline_update=no_baseline_update,
        no_full_series_b=no_full_series_b,
        manifest=manifest,
        chunks_payload=chunks_payload,
    )
    chunks = chunks_payload.get("approved_chunks")
    if not isinstance(chunks, list) or not chunks:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "approved_chunks must be a non-empty list")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "chunk must be an object")
        _validate_chunk(chunk)
    try:
        guard_report = validate_chunks(chunks)
    except ObjArt003GuardError as exc:
        raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", str(exc)) from exc

    source_records: dict[str, dict[str, Any]] = {}
    chunk_records: list[dict[str, Any]] = []
    for chunk in chunks:
        text = chunk.get("source_backed_text")
        text_hash = _sha256_text(text) if isinstance(text, str) else chunk.get("source_backed_text_sha256")
        source_records.setdefault(
            chunk["source_id"],
            {
                "source_id": chunk["source_id"],
                "source_title": chunk["source_title"],
                "axis": chunk["axis"],
                "source_hash": chunk.get("source_sha256"),
                "provenance_metadata": chunk.get("provenance_metadata", {}),
                "accepted_chunk_ids": [],
                "case_scope_only": True,
            },
        )["accepted_chunk_ids"].append(chunk["chunk_id"])
        chunk_records.append(
            {
                "case_id": CASE_ID,
                "source_id": chunk["source_id"],
                "source_title": chunk["source_title"],
                "chunk_id": chunk["chunk_id"],
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "axis": chunk["axis"],
                "supports_terms": chunk.get("supports_terms", []),
                "supports_sections": chunk.get("supports_sections", []),
                "source_backed_text": text,
                "source_backed_text_locator": chunk.get("source_backed_text_locator"),
                "source_backed_text_hash": text_hash,
                "reviewer_decision": chunk["reviewer_decision"],
                "wrong_context_guard_passed": chunk["wrong_context_guard_passed"],
                "page_bound": chunk["page_bound"],
                "source_backed_text_exists": chunk["source_backed_text_exists"],
                "source_hash_or_text_hash": chunk.get("source_sha256") or text_hash,
                "provenance_metadata": chunk.get("provenance_metadata", {}),
                "section_target": chunk.get("section_target") or chunk.get("supports_sections", []),
                "evidence_strength": chunk["evidence_strength"],
            }
        )

    packet = {
        "schema_version": "obj_art_003.controlled_source_packet.v1",
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
        "case_rule_trace_decision": "ARCHAEOLOGY_AXIS_NOT_HARD_REQUIRED_CONFIRMED",
        "manifest_ref": {"path": str(manifest_path), "sha256": _sha256_file(manifest_path)},
        "approved_chunks_ref": {"path": str(chunks_path), "sha256": _sha256_file(chunks_path), "approved_chunks_count": len(chunks)},
        "required_terms": REQUIRED_TERMS,
        "required_axes": REQUIRED_AXES,
        "required_sections": REQUIRED_SECTIONS,
        "sources": sorted(source_records.values(), key=lambda value: value["source_id"]),
        "chunks": chunk_records,
        "guard_report": guard_report,
        "single_case_controlled_dryrun_evidence": True,
        **EXECUTION_FALSE_FLAGS,
    }
    path = target_dir / SOURCE_PACKET_FILENAME
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "SOURCE_PACKET_EXPORTED", "artifact_path": str(path), "chunk_count": len(chunk_records)}
