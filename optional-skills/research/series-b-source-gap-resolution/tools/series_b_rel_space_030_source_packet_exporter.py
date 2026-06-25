#!/usr/bin/env python3
"""Case-scoped source packet exporter for rel_space_030."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rel_space_030_alias_source_guard import RelSpace030GuardError, validate_chunks
from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_rel_space_030_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS, REQUIRED_AXES, REQUIRED_SECTIONS, REQUIRED_TERMS


SOURCE_PACKET_FILENAME = "rel_space_030_controlled_source_packet.json"
EXPECTED_FORMAL_DECISION = "REL_SPACE_030_FORMAL_READY_REVIEW_APPROVED_WITH_CAVEAT"


class SourcePacketExportError(ValueError):
    """Raised when the rel_space_030 source packet cannot be exported safely."""

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
    if manifest.get("production_default_loader_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_PRODUCTION_DEFAULT_RISK", "manifest enables production default")
    if manifest.get("official_baseline_update_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_BASELINE_UPDATE_RISK", "manifest enables baseline update")
    if manifest.get("full_series_b_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_FULL_SERIES_B_RISK", "manifest enables full Series B")
    if manifest.get("case_scoped_only") is not True:
        raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", "manifest is not case-scoped")
    if manifest.get("controlled_regression_execution_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", "manifest pre-enables execution")
    if manifest.get("separate_execution_next_step_allowed") is not True:
        raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", "manifest does not allow separate execution")


def _source_title(chunk: dict[str, Any]) -> str:
    return str(chunk.get("article_title / source_title") or chunk.get("source_title") or chunk.get("article_title") or "")


def _axes(chunk: dict[str, Any]) -> list[str]:
    raw = str(chunk.get("axis_candidate") or "")
    axes = {part.strip() for part in raw.replace(",", ";").split(";") if part.strip()}
    if "art_architecture_book" in axes:
        axes.add("architecture_book")
    if chunk.get("source_type") == "wiki_or_zim":
        axes.update({"wiki_or_zim", "encyclopedia_context", "context_sources"})
    if chunk.get("source_type") == "local_professional_source_locator_context":
        axes.add("context_sources")
    return sorted(axes)


def _chunk_record(chunk: dict[str, Any]) -> dict[str, Any]:
    locator = {
        "chunk_id": chunk["chunk_id"],
        "binding_status": chunk["binding_status"],
        "source_ref": chunk["source_id"],
        "source_type": chunk["source_type"],
        "locator": chunk.get("locator"),
    }
    source_type = str(chunk.get("source_type"))
    return {
        "case_id": CASE_ID,
        "source_id": chunk["source_id"],
        "source_title": _source_title(chunk),
        "source_type": source_type,
        "chunk_id": chunk["chunk_id"],
        "axis": _axes(chunk),
        "axis_candidate": chunk.get("axis_candidate"),
        "supports_terms": chunk.get("supports_terms", []),
        "supports_sections": chunk.get("supports_sections", []),
        "source_backed_text_exists": chunk.get("source_backed_text_exists") is True,
        "source_backed_text_locator": locator,
        "source_backed_text_locator_hash": _sha256_text(json.dumps(locator, sort_keys=True)),
        "content_preview": chunk.get("content_preview"),
        "reviewer_decision": chunk["reviewer_decision"],
        "wrong_context_guard_passed": chunk["wrong_context_guard_passed"],
        "binding_status": chunk["binding_status"],
        "binding_caveat_preserved": True,
        "mount_meru_context_only": "Mount Meru" in chunk.get("supports_terms", []),
        "sacred_geometry_equivalent": "sacred geometry" in chunk.get("supports_terms", []),
        "title_only": False,
        "query_echo": False,
        "generated_echo": False,
        "README_summary": False,
        "listing_or_planning_noise": False,
        "wrong_domain": False,
        "evidence_strength": chunk.get("evidence_strength", "strong"),
    }


def validate_rel_space_030_handoff_inputs(
    *,
    manifest: dict[str, Any],
    chunks_payload: dict[str, Any],
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
) -> list[dict[str, Any]]:
    if manifest.get("case_id") != CASE_ID or chunks_payload.get("case_id") != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "handoff inputs must be rel_space_030 scoped")
    if manifest.get("formal_ready_decision") != EXPECTED_FORMAL_DECISION:
        raise SourcePacketExportError("HANDOFF_MANIFEST_MALFORMED", "formal-ready decision is not approved with caveat")
    _require_policy(
        no_production_default=no_production_default,
        no_baseline_update=no_baseline_update,
        no_full_series_b=no_full_series_b,
        manifest=manifest,
    )
    chunks = chunks_payload.get("approved_chunks")
    if not isinstance(chunks, list) or len(chunks) != 8:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "expected 8 approved chunks")
    if manifest.get("approved_chunk_count") != len(chunks):
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "approved chunk count does not match manifest")
    try:
        validate_chunks(chunks)
    except RelSpace030GuardError as exc:
        raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", str(exc)) from exc
    return chunks


def export_rel_space_030_controlled_source_packet(
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
    """Export a rel_space_030 controlled source packet outside the repo."""

    if case_id != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "case_id must be rel_space_030")
    try:
        target_dir = validate_output_dir_policy(output_dir, repo_root=repo_root)
    except ArtifactContractError as exc:
        raise SourcePacketExportError("OUTPUT_DIR_UNSAFE", str(exc)) from exc
    target_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = Path(controlled_handoff_manifest_path).expanduser()
    chunks_path = Path(approved_chunks_handoff_path).expanduser()
    manifest = _load_json(manifest_path, kind="handoff_manifest")
    chunks_payload = _load_json(chunks_path, kind="approved_chunks")
    chunks = validate_rel_space_030_handoff_inputs(
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
                "source_type": record["source_type"],
                "axes": record["axis"],
                "accepted_chunk_ids": [],
                "case_scope_only": True,
                "mount_meru_context_only": record["mount_meru_context_only"],
            },
        )["accepted_chunk_ids"].append(record["chunk_id"])

    caveats = {
        "binding_caveat_preserved": True,
        "binding_statuses": sorted({record["binding_status"] for record in chunk_records}),
        "mount_meru_context_only": True,
        "sacred_geometry_equivalent_not_exact_professional_phrase": True,
        "context_locator_evidence_not_overstated": True,
        "readme_or_title_only_chunks_count_as_evidence": False,
    }
    packet = {
        "schema_version": "rel_space_030.controlled_source_packet.v1",
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
            "approved_chunks_count": len(chunks),
        },
        "required_terms": REQUIRED_TERMS,
        "required_axes": REQUIRED_AXES,
        "required_sections": REQUIRED_SECTIONS,
        "caveats": caveats,
        "sources": sorted(source_records.values(), key=lambda value: value["source_id"]),
        "chunks": chunk_records,
        "guard_report": validate_chunks(chunks),
        "single_case_controlled_dryrun_evidence": True,
        **EXECUTION_FALSE_FLAGS,
    }
    path = target_dir / SOURCE_PACKET_FILENAME
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "SOURCE_PACKET_EXPORTED", "artifact_path": str(path), "chunk_count": len(chunk_records)}
