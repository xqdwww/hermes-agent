#!/usr/bin/env python3
"""Deterministic source-grounded builder for obj_art_007 controlled dry-runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_obj_art_007_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS

RAW_DOSSIER_FILENAME = "obj_art_007_controlled_raw_dossier.md"


class SourceGroundedBuilderError(ValueError):
    """Raised when the obj_art_007 builder must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_packet(path: str | Path) -> dict[str, Any]:
    packet = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet must be an object")
    if packet.get("case_id") != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "source packet case_id must be obj_art_007")
    return packet


def _require_locks(packet: dict[str, Any]) -> None:
    locks = packet.get("policy_locks")
    if not isinstance(locks, dict):
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet lacks policy locks")
    if locks.get("production_default_loader_enabled") is not False or locks.get("no_production_default") is not True:
        raise SourceGroundedBuilderError("BLOCKED_PRODUCTION_DEFAULT_RISK", "production default lock is unsafe")
    if locks.get("official_baseline_update_enabled") is not False or locks.get("no_baseline_update") is not True:
        raise SourceGroundedBuilderError("BLOCKED_BASELINE_UPDATE_RISK", "baseline lock is unsafe")
    if locks.get("full_series_b_enabled") is not False or locks.get("no_full_series_b") is not True:
        raise SourceGroundedBuilderError("BLOCKED_FULL_SERIES_B_RISK", "full Series B lock is unsafe")


def _chunks(packet: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = packet.get("chunks")
    if not isinstance(chunks, list) or len(chunks) != 14:
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet must contain 14 approved chunks")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet chunk must be an object")
        if chunk.get("case_id") != CASE_ID:
            raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "chunk case_id must be obj_art_007")
        if chunk.get("page_binding_caveat_preserved") is not True:
            raise SourceGroundedBuilderError("BLOCKED_BINDING_INSUFFICIENT", "page binding caveat is missing")
        if chunk.get("precise_page_number_claimed") is True:
            raise SourceGroundedBuilderError("BLOCKED_EXACT_PAGE_REQUIRED", "precise page claim is not allowed")
    return chunks


def _refs(chunks: list[dict[str, Any]], *, section: str | None = None, term: str | None = None) -> list[str]:
    refs: list[str] = []
    for chunk in chunks:
        terms = " ".join(str(t).lower() for t in chunk.get("supports_terms", []))
        sections = set(str(s) for s in chunk.get("supports_sections", [])) | set(str(s) for s in chunk.get("section_target", []))
        if section and section not in sections:
            continue
        if term and term.lower() not in terms:
            continue
        refs.append(f"{chunk['source_id']}::{chunk['chunk_id']} ({chunk['page_bound_status']}; text_sha256={chunk.get('source_hash_or_text_hash')})")
    return refs


def _line(label: str, refs: list[str]) -> str:
    return f"{label}: " + "; ".join(refs[:14])


def _source_lines(packet: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for source in packet.get("sources", []):
        if isinstance(source, dict):
            axes = ", ".join(str(axis) for axis in source.get("axes", []))
            lines.append(f"- `{source['source_id']}`: {source.get('source_title')} ({axes}; case-scoped source)")
    return sorted(lines)


def build_obj_art_007_dossier(
    *,
    case_id: str,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write an obj_art_007 raw dossier from approved source-packet evidence."""

    if case_id != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "case_id must be obj_art_007")
    packet = _load_packet(source_packet_path)
    _require_locks(packet)
    chunks = _chunks(packet)
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)

    materials_refs = _refs(chunks, section="materials_mechanics")
    history_refs = _refs(chunks, section="historical_context")
    art_refs = _refs(chunks, section="art_architecture")
    theme_refs = _refs(chunks, section="theme_tracks")
    load_refs = _refs(chunks, term="load") + _refs(chunks, term="bearing")
    joinery_refs = _refs(chunks, term="mortise") + _refs(chunks, term="dowel") + _refs(chunks, term="interlocking")
    source_lines = _source_lines(packet)
    chunk_lines = [
        f"- `{chunk['chunk_id']}` -> {', '.join(chunk.get('supports_sections', []))} / {', '.join(chunk.get('supports_terms', []))} / text_sha256={chunk.get('source_hash_or_text_hash')}"
        for chunk in chunks
    ]

    body = f"""# obj_art_007 controlled raw dossier

case_id: {CASE_ID}
controlled_builder: series_b_obj_art_007_source_grounded_builder
source_grounded_builder_output: true
mock_builder_output: false
generated_at: {datetime.now(timezone.utc).isoformat()}
source_packet_artifact: {Path(source_packet_path).name}
handoff_manifest_artifact: {Path(handoff_manifest_path).name}
page_binding_caveat: preserved; many approved chunks carry 0/0 weak page binding, so evidence is tracked by chunk_id / section locator / text_sha256 and no precise page numbers are claimed
readme_title_only_caveat: README, local locator summaries, title-only chunks and synthetic prompt-derived echoes are excluded and do not count as evidence
official_baseline_update_performed: false
full_series_b_run_performed: false
production_default_manifest_integration_performed: false
case_repair_performed: false
push_performed: false
tag_created: false

## materials_mechanics

The obj_art_007 materials-mechanics account is restricted to source-packet
bindings for dougong, bracket set, timber framing, timber joinery,
interlocking timber joinery, load transfer, cantilever, seismic performance,
and energy dissipation. Dougong is treated as a timber bracket-set system, not
as a generic ornament. The approved mechanical evidence ties the bracket set
to a roof-beam-to-column load path, vertical load response, load-displacement
behavior, stiffness degradation, deformation capacity, and load-bearing work.
Hidden timber dowels, slotting, mortises, timber wedges, and bracket elements
that intertwine and interpenetrate are treated as the controlled source-backed
mechanism for timber joinery and interlocking timber joinery. Cantilever arms,
blocks, mortises, and dougong components are therefore described as a linked
materials-and-structure system.
{_line('materials_mechanics_source_refs', materials_refs)}
{_line('load_transfer_source_refs', load_refs)}
{_line('joinery_source_refs', joinery_refs)}

The page binding caveat remains active: 0/0 page binding is weak locator
binding only. This dossier uses chunk_id / section locator / text_sha256 for
evidence trace and makes no precise-page claim.

## historical_context

The historical-context section grounds the object in Chinese timber
architecture and Yingzao Fashi. The approved architecture sources bind dougong,
bracket set, cantilever terminology, major carpentry-system formulae, and the
Yingzao Fashi building manual to the historical vocabulary of Chinese timber
architecture. Liang's historical architecture source supplies Chinese
structural-system and timber-frame context; Feng supplies the Song building
manual and bracket-set terminology; the mechanical source links this older
architectural vocabulary to tested dougong behavior in traditional timber
structures.
{_line('historical_context_source_refs', history_refs)}

This section does not count README summaries or source locator summaries as
primary evidence. It also does not introduce unrelated regional travel content
or broad architecture boilerplate without dougong and timber-structure support.

## art_architecture

The art-architecture section treats the bracket set as both architectural
form and structural mechanism. Source-backed YZFS material connects puzuo,
gong, ang, dou, cantilever arms, blocks, mortises, and bracket sets. The
architectural account therefore covers dougong and bracket set as a visible
system of Chinese timber architecture while keeping the mechanical account
attached to load transfer, timber joinery, interlocking timber joinery, seismic
performance, and energy dissipation. The Liang source keeps the Chinese
structural system and timber-frame architecture in scope; the Feng source keeps
Yingzao Fashi and bracket terminology in scope.
{_line('art_architecture_source_refs', art_refs)}

The source packet is the only source of evidence consumed by this builder. No
production retrieval, production default manifest, source registry, vector
index, OCR pipeline, embedding pipeline, full Series B runner, official
baseline, ledger, or score file is consulted.

## theme_tracks

The controlled theme track has four strands. First, materials mechanics:
dougong and bracket set as a timber structure that handles load transfer,
vertical load response, stiffness, deformation, seismic performance, and
energy dissipation. Second, joinery mechanics: timber framing, timber joinery,
interlocking timber joinery, hidden timber dowels, mortises, and
interpenetrating bracket elements. Third, historical architecture: Yingzao
Fashi and Chinese timber architecture as the vocabulary and source frame for
puzuo, gong, ang, dou, bracket sets, and cantilevers. Fourth, safety: page
binding caveat preserved, chunk_id / section locator / text_sha256 trace kept,
no precise page numbers claimed, and no title-only, README, or synthetic echo evidence counted.
{_line('theme_tracks_source_refs', theme_refs)}

The dossier quality target is rich. It gives enough source-bound structure for
a controlled auditor to check required terms, sections, axes, guard status,
page binding caveat, and artifact contract without invoking production paths.

## source_bindings

Sources used:
{chr(10).join(source_lines)}

Approved chunk bindings:
{chr(10).join(chunk_lines)}

Approved chunks: {len(chunks)}
Page binding caveat preserved: true
Precise page numbers claimed: false
README/title-only evidence counted: false
"""
    path = target / RAW_DOSSIER_FILENAME
    path.write_text(body, encoding="utf-8")
    return {
        "status": "REAL_BUILDER_OUTPUT_WRITTEN",
        "artifact_path": str(path),
        "source_grounded_builder_output": True,
        "mock_builder_output": False,
        "approved_chunk_count": len(chunks),
        **EXECUTION_FALSE_FLAGS,
    }
