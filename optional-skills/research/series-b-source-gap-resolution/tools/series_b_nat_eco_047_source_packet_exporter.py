#!/usr/bin/env python3
"""Case-scoped source packet exporter for nat_eco_047."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nat_eco_047_alias_source_guard import NatEco047GuardError, validate_chunks
from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy
from series_b_nat_eco_047_result_schema import (
    CASE_ID,
    EXECUTION_FALSE_FLAGS,
    REQUIRED_AXES,
    REQUIRED_SECTIONS,
    REQUIRED_TERMS,
)


SOURCE_PACKET_FILENAME = "nat_eco_047_controlled_source_packet.json"
EXPECTED_FORMAL_DECISION = "NAT_ECO_047_FORMAL_READY_REVIEW_APPROVED_WITH_BINDING_CAVEAT"


class SourcePacketExportError(ValueError):
    """Raised when the nat_eco_047 source packet cannot be exported safely."""

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
    for payload, label in ((manifest, "manifest"), (chunks_payload, "approved chunks")):
        if payload.get("production_default_loader_enabled") is not False:
            raise SourcePacketExportError("BLOCKED_PRODUCTION_DEFAULT_RISK", f"{label} enables production default")
        if payload.get("official_baseline_update_enabled") is not False:
            raise SourcePacketExportError("BLOCKED_BASELINE_UPDATE_RISK", f"{label} enables baseline update")
        if payload.get("full_series_b_enabled") is not False:
            raise SourcePacketExportError("BLOCKED_FULL_SERIES_B_RISK", f"{label} enables full Series B")
        if payload.get("case_scoped_only") is not True:
            raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", f"{label} is not case-scoped")
        if payload.get("controlled_regression_execution_enabled") is not False:
            raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", f"{label} pre-enables execution")
        if payload.get("separate_execution_next_step_allowed") is not True:
            raise SourcePacketExportError("BLOCKED_GUARD_VIOLATION", f"{label} does not allow separate execution")


def _axis_for_chunk(chunk: dict[str, Any]) -> list[str]:
    source_type = str(chunk.get("source_type"))
    axes = {"context_sources"}
    if source_type == "wiki_or_zim":
        axes.add("wiki_or_zim")
        axes.add("encyclopedia_context")
    elif source_type == "encyclopedia_context":
        axes.add("encyclopedia_context")
    elif source_type == "local_professional_source_locator_context":
        axes.add("nature_book_if_available")
        axes.add("geography_book_if_available")
    return sorted(axes)


def _source_title(chunk: dict[str, Any]) -> str:
    return str(chunk.get("article_title / source_title") or chunk.get("source_title") or chunk.get("article_title") or "")


def _chunk_record(chunk: dict[str, Any]) -> dict[str, Any]:
    locator = {
        "chunk_id": chunk["chunk_id"],
        "binding_status": chunk["binding_status"],
        "source_ref": chunk["source_id"],
        "source_type": chunk["source_type"],
        "locator": chunk.get("locator"),
    }
    source_type = str(chunk.get("source_type"))
    usage_role = "primary_context_evidence"
    if source_type == "local_professional_source_locator_context":
        usage_role = "supplemental_locator_only"
    return {
        "case_id": CASE_ID,
        "source_id": chunk["source_id"],
        "source_title": _source_title(chunk),
        "source_type": source_type,
        "chunk_id": chunk["chunk_id"],
        "axis": _axis_for_chunk(chunk),
        "axis_candidate": chunk.get("axis_candidate"),
        "supports_terms": chunk.get("supports_terms", []),
        "supports_sections": chunk.get("supports_sections", []),
        "source_backed_text_exists": chunk.get("source-backed text exists") is True,
        "source_backed_text_locator": locator,
        "source_backed_text_locator_hash": _sha256_text(json.dumps(locator, sort_keys=True)),
        "reviewer_decision": "FORMAL_READY_APPROVED_WITH_BINDING_CAVEAT",
        "wrong_context_guard_passed": True,
        "binding_status": chunk["binding_status"],
        "binding_caveat_preserved": True,
        "supplemental_locator_only": source_type == "local_professional_source_locator_context",
        "usage_role": usage_role,
        "title_only": False,
        "query_echo": False,
        "generated_echo": False,
        "README_summary": False,
        "listing_or_planning_noise": False,
        "wrong_domain": False,
        "evidence_strength": chunk.get("evidence_strength", "strong"),
    }


def validate_nat_eco_047_handoff_inputs(
    *,
    manifest: dict[str, Any],
    chunks_payload: dict[str, Any],
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
) -> list[dict[str, Any]]:
    if manifest.get("case_id") != CASE_ID or chunks_payload.get("case_id") != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "handoff inputs must be nat_eco_047 scoped")
    if manifest.get("formal_ready_decision") != EXPECTED_FORMAL_DECISION:
        raise SourcePacketExportError("HANDOFF_MANIFEST_MALFORMED", "formal-ready decision is not approved with caveat")
    _require_policy(
        no_production_default=no_production_default,
        no_baseline_update=no_baseline_update,
        no_full_series_b=no_full_series_b,
        manifest=manifest,
        chunks_payload=chunks_payload,
    )
    chunks = chunks_payload.get("chunks")
    if not isinstance(chunks, list) or len(chunks) != 14:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "expected 14 approved chunks")
    manifest_ids = set(manifest.get("approved_chunk_ids", []))
    chunk_ids = {str(chunk.get("chunk_id")) for chunk in chunks}
    if chunk_ids != manifest_ids:
        raise SourcePacketExportError("APPROVED_CHUNKS_MALFORMED", "approved chunk ids do not match manifest")
    try:
        validate_chunks(chunks)
    except NatEco047GuardError as exc:
        raise SourcePacketExportError("SOURCE_PACKET_CONTAMINATION_DETECTED", str(exc)) from exc
    return chunks


def export_nat_eco_047_controlled_source_packet(
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
    """Export a nat_eco_047 controlled source packet outside the repo."""

    if case_id != CASE_ID:
        raise SourcePacketExportError("CASE_ID_MISMATCH", "case_id must be nat_eco_047")
    try:
        target_dir = validate_output_dir_policy(output_dir, repo_root=repo_root)
    except ArtifactContractError as exc:
        raise SourcePacketExportError("OUTPUT_DIR_UNSAFE", str(exc)) from exc
    target_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = Path(controlled_handoff_manifest_path).expanduser()
    chunks_path = Path(approved_chunks_handoff_path).expanduser()
    manifest = _load_json(manifest_path, kind="handoff_manifest")
    chunks_payload = _load_json(chunks_path, kind="approved_chunks")
    chunks = validate_nat_eco_047_handoff_inputs(
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
                "supplemental_locator_only": record["supplemental_locator_only"],
            },
        )["accepted_chunk_ids"].append(record["chunk_id"])

    caveats = {
        "binding_caveat_preserved": True,
        "binding_statuses": sorted({record["binding_status"] for record in chunk_records}),
        "entry_section_or_local_source_section_bound": True,
        "local_professional_source_is_supplemental_locator_only": True,
        "readme_or_title_only_chunks_count_as_evidence": False,
    }
    packet = {
        "schema_version": "nat_eco_047.controlled_source_packet.v1",
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
            "carryover_excluded_or_weak_count": manifest.get("carryover_excluded_or_weak_count"),
        },
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
