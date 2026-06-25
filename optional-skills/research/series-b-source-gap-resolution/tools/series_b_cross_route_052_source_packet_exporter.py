#!/usr/bin/env python3
"""Case-scoped source packet exporter for cross_route_052."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cross_route_052_alias_source_guard import CrossRoute052GuardError, validate_chunks
from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_cross_route_052_result_schema import (
    CASE_ID,
    CAVEATED_AXES,
    EXECUTION_FALSE_FLAGS,
    REQUIRED_AXES,
    REQUIRED_SECTIONS,
    REQUIRED_TERMS,
)


SOURCE_PACKET_FILENAME = "cross_route_052_controlled_source_packet.json"
EXPECTED_FORMAL_DECISION = "CROSS_ROUTE_052_FORMAL_READY_REVIEW_APPROVED_WITH_BINDING_CAVEAT"


class SourcePacketExportError(ValueError):
    """Raised when the cross_route_052 source packet cannot be exported safely."""

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
    if manifest.get("production_default_loader_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_PRODUCTION_DEFAULT_RISK", "production default is enabled")
    if manifest.get("official_baseline_update_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_BASELINE_UPDATE_RISK", "baseline update is enabled")
    if manifest.get("full_series_b_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_FULL_SERIES_B_RISK", "full Series B is enabled")
    if manifest.get("case_scoped_only") is not True:
        raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", "manifest is not case scoped")
    if manifest.get("controlled_regression_execution_enabled") is not False:
        raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", "handoff must not pre-enable execution")
    if manifest.get("separate_execution_next_step_allowed") is not True:
        raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", "separate execution is not allowed")
    usage = chunks_payload.get("usage_boundary")
    if not isinstance(usage, dict):
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "usage_boundary is required")
    if usage.get("do_not_update_official_baseline") is not True:
        raise SourcePacketExportError("BLOCKED_BASELINE_UPDATE_RISK", "chunk handoff allows baseline update")
    if usage.get("do_not_use_production_default_loader") is not True:
        raise SourcePacketExportError("BLOCKED_PRODUCTION_DEFAULT_RISK", "chunk handoff allows production default")
    if usage.get("use_only_case_scoped_loader") is not True:
        raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", "chunk handoff is not case-scoped")


def _axis_for_chunk(chunk: dict[str, Any]) -> list[str]:
    source_id = str(chunk["source_id"])
    axes: set[str] = set()
    if "getty_cave85_conservation" in source_id:
        axes.update({"art_architecture_book", "conservation_source", "geology_hydrology_source"})
    if "wu_spatial_dunhuang" in source_id:
        axes.update({"art_architecture_book", "archaeology_history_source"})
    if "wang_mogao_cliff" in source_id:
        axes.update({"geology_hydrology_source", "conservation_source"})
    return sorted(axes)


def _chunk_record(chunk: dict[str, Any], *, group: str) -> dict[str, Any]:
    locator = {
        "chunk_id": chunk["chunk_id"],
        "binding_status": chunk["binding_status"],
        "page_precise": False,
        "source_ref": chunk["source_id"],
        "text_sha256": chunk.get("text_sha256"),
    }
    return {
        "case_id": CASE_ID,
        "chunk_group": group,
        "source_id": chunk["source_id"],
        "source_title": chunk["source_title"],
        "chunk_id": chunk["chunk_id"],
        "axis": _axis_for_chunk(chunk),
        "supports_terms": chunk.get("supports_terms", []),
        "supports_sections": chunk.get("supports_sections", []),
        "source_backed_text_locator": locator,
        "source_backed_text_locator_hash": _sha256_text(json.dumps(locator, sort_keys=True)),
        "reviewer_decision": "FORMAL_READY_APPROVED_WITH_BINDING_CAVEAT",
        "wrong_context_guard_passed": True,
        "binding_status": chunk["binding_status"],
        "binding_caveat_preserved": True,
        "evidence_strength": "strong" if group == "primary_professional" else "supplemental_support",
        "usage_role": chunk.get("usage_role"),
    }


def _context_record(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": CASE_ID,
        "chunk_group": "context_or_alias_guard_only",
        "source_id": chunk.get("source_id"),
        "source_title": chunk.get("source_title"),
        "chunk_id": chunk.get("chunk_id"),
        "axis": ["context_sources"],
        "supports_terms": chunk.get("supports_terms", []),
        "usage_role": chunk.get("usage_role", "context or alias guard only"),
        "primary_evidence": False,
    }


def validate_cross_route_052_handoff_inputs(
    *,
    manifest: dict[str, Any],
    chunks_payload: dict[str, Any],
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if manifest.get("case_id") != CASE_ID or chunks_payload.get("case_id") != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "handoff inputs must be cross_route_052 scoped")
    if manifest.get("formal_ready_decision") != EXPECTED_FORMAL_DECISION:
        raise SourcePacketExportError("HANDOFF_MANIFEST_MALFORMED", "formal-ready decision is not approved with caveat")
    if chunks_payload.get("formal_ready_decision") != EXPECTED_FORMAL_DECISION:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "chunk handoff decision is not approved with caveat")
    _require_policy(
        no_production_default=no_production_default,
        no_baseline_update=no_baseline_update,
        no_full_series_b=no_full_series_b,
        manifest=manifest,
        chunks_payload=chunks_payload,
    )
    primary = chunks_payload.get("approved_primary_chunks")
    supplemental = chunks_payload.get("approved_supplemental_chunks")
    context = chunks_payload.get("context_or_alias_guard_chunks")
    if not isinstance(primary, list) or len(primary) != 11:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "expected 11 approved primary chunks")
    if not isinstance(supplemental, list) or len(supplemental) != 3:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "expected 3 approved supplemental chunks")
    if not isinstance(context, list) or len(context) != 3:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "expected 3 context/alias guard chunks")
    approved_ids = {str(chunk.get("chunk_id")) for chunk in [*primary, *supplemental]}
    context_ids = {str(chunk.get("chunk_id")) for chunk in context}
    if approved_ids.intersection(context_ids):
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "approved chunks overlap context guard chunks")
    try:
        validate_chunks([*primary, *supplemental])
    except CrossRoute052GuardError as exc:
        raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", str(exc)) from exc
    hydrology_context = [
        chunk for chunk in context
        if "hydrology" in {str(term).lower() for term in chunk.get("supports_terms", [])}
    ]
    if not hydrology_context:
        raise SourcePacketExportError("BLOCKED_HYDROLOGY_PRIMARY_EVIDENCE_REQUIRED", "hydrology caveat context chunk is missing")
    return primary, supplemental, context


def export_cross_route_052_controlled_source_packet(
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
    """Export a cross_route_052 controlled source packet outside the repo."""

    if case_id != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "case_id must be cross_route_052")
    try:
        target_dir = validate_output_dir_policy(output_dir, repo_root=repo_root)
    except ArtifactContractError as exc:
        raise SourcePacketExportError("OUTPUT_DIR_UNSAFE", str(exc)) from exc
    target_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = Path(controlled_handoff_manifest_path).expanduser()
    chunks_path = Path(approved_chunks_handoff_path).expanduser()
    manifest = _load_json(manifest_path, kind="handoff_manifest")
    chunks_payload = _load_json(chunks_path, kind="approved_chunks")
    primary, supplemental, context = validate_cross_route_052_handoff_inputs(
        manifest=manifest,
        chunks_payload=chunks_payload,
        no_production_default=no_production_default,
        no_baseline_update=no_baseline_update,
        no_full_series_b=no_full_series_b,
    )

    chunk_records = [
        *[_chunk_record(chunk, group="primary_professional") for chunk in primary],
        *[_chunk_record(chunk, group="supplemental_professional") for chunk in supplemental],
    ]
    context_records = [_context_record(chunk) for chunk in context]
    source_records: dict[str, dict[str, Any]] = {}
    for record in chunk_records:
        source_records.setdefault(
            record["source_id"],
            {
                "source_id": record["source_id"],
                "source_title": record["source_title"],
                "axes": record["axis"],
                "accepted_chunk_ids": [],
                "case_scope_only": True,
            },
        )["accepted_chunk_ids"].append(record["chunk_id"])

    caveats = {
        "binding_caveat_preserved": True,
        "binding_status": "PAGE_BOUND_WEAK_EPUB_SECTION_BOUND",
        "page_precise_binding_available": False,
        "hydrology_caveat_preserved": True,
        "hydrology_primary_evidence": False,
        "hydrology_usage": "context_only_with_hydrogeology_near_support",
        "context_sources_primary_evidence": False,
        "title_only_chunks_count_as_evidence": False,
    }
    packet = {
        "schema_version": "cross_route_052.controlled_source_packet.v1",
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
            "approved_primary_chunks_count": len(primary),
            "approved_supplemental_chunks_count": len(supplemental),
            "context_or_alias_guard_chunks_count": len(context_records),
        },
        "required_terms": REQUIRED_TERMS,
        "required_axes": REQUIRED_AXES,
        "caveated_axes": CAVEATED_AXES,
        "required_sections": REQUIRED_SECTIONS,
        "sources": sorted(source_records.values(), key=lambda value: value["source_id"]),
        "chunks": chunk_records,
        "context_or_alias_guard_chunks": context_records,
        "guard_report": validate_chunks([*primary, *supplemental]),
        "caveats": caveats,
        "single_case_controlled_dryrun_evidence": True,
        **EXECUTION_FALSE_FLAGS,
    }
    path = target_dir / SOURCE_PACKET_FILENAME
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "SOURCE_PACKET_EXPORTED", "artifact_path": str(path), "chunk_count": len(chunk_records)}
