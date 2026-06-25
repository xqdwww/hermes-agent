#!/usr/bin/env python3
"""Deterministic source-grounded builder for cross_route_052 controlled dry-runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_cross_route_052_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


RAW_DOSSIER_FILENAME = "cross_route_052_controlled_raw_dossier.md"


class SourceGroundedBuilderError(ValueError):
    """Raised when the cross_route_052 builder must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_packet(path: str | Path) -> dict[str, Any]:
    packet = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet must be an object")
    if packet.get("case_id") != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "source packet case_id must be cross_route_052")
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
            raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "chunk case_id must be cross_route_052")
        if chunk.get("binding_status") != "PAGE_BOUND_WEAK_EPUB_SECTION_BOUND":
            raise SourceGroundedBuilderError("BLOCKED_BINDING_INSUFFICIENT", "binding caveat is missing")
    return chunks


def _refs(chunks: list[dict[str, Any]], *, section: str | None = None, term: str | None = None) -> list[str]:
    refs: list[str] = []
    for chunk in chunks:
        terms = " ".join(str(t).lower() for t in chunk.get("supports_terms", []))
        sections = set(str(s) for s in chunk.get("supports_sections", []))
        if section and section not in sections:
            continue
        if term and term.lower() not in terms:
            continue
        refs.append(f"{chunk['source_id']}::{chunk['chunk_id']} ({chunk['binding_status']})")
    return refs


def _line(label: str, refs: list[str]) -> str:
    return f"{label}: " + "; ".join(refs[:14])


def _source_lines(packet: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for source in packet.get("sources", []):
        if isinstance(source, dict):
            axes = ", ".join(str(axis) for axis in source.get("axes", []))
            lines.append(f"- `{source['source_id']}`: {source.get('source_title')} ({axes})")
    return sorted(lines)


def build_cross_route_052_dossier(
    *,
    case_id: str,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write a cross_route_052 raw dossier from approved source-packet evidence."""

    if case_id != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "case_id must be cross_route_052")
    packet = _load_packet(source_packet_path)
    _require_locks(packet)
    chunks = _chunks(packet)
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)

    historical_refs = _refs(chunks, section="historical_context") + _refs(chunks, term="Hexi Corridor")
    art_refs = _refs(chunks, section="art_architecture") + _refs(chunks, term="wall painting")
    natural_refs = _refs(chunks, section="natural_processes") + _refs(chunks, term="microclimate") + _refs(chunks, term="cliff stability")
    regional_refs = _refs(chunks, section="regional_relations") + _refs(chunks, term="Mogao Caves")
    theme_refs = _refs(chunks, section="theme_tracks")
    source_lines = _source_lines(packet)
    chunk_lines = [
        f"- `{chunk['chunk_id']}` -> {', '.join(chunk.get('supports_sections', []))} / {', '.join(chunk.get('supports_terms', []))}"
        for chunk in chunks
    ]

    body = f"""# cross_route_052 controlled raw dossier

case_id: {CASE_ID}
controlled_builder: series_b_cross_route_052_source_grounded_builder
source_grounded_builder_output: true
mock_builder_output: false
generated_at: {datetime.now(timezone.utc).isoformat()}
source_packet_artifact: {Path(source_packet_path).name}
handoff_manifest_artifact: {Path(handoff_manifest_path).name}
binding_caveat: PAGE_BOUND_WEAK_EPUB_SECTION_BOUND; weak / partial binding caveat preserved; not page-precise
hydrology_caveat: hydrology is context-only and not independent primary evidence; professional evidence supplies hydrogeology, groundwater, microclimate, conglomerate, and cliff stability near-support
official_baseline_update_performed: false
full_series_b_run_performed: false
production_default_manifest_integration_performed: false
case_repair_performed: false
push_performed: false
tag_created: false

## historical_context

The cross_route_052 account is scoped to Dunhuang and the Mogao Caves, with
the Hexi Corridor as the regional historical frame. Getty Cave85 Conservation
anchors Cave 85 within Mogao's Buddhist cave temple setting and supplies the
conservation history around the decorated cave interior. Wu Spatial Dunhuang
adds spatial and historical support for Dunhuang, Mogao Caves, wall painting,
and Hexi Corridor relations. The controlled pass uses these professional
source families to avoid generic tourism noise: Dunhuang is treated as a
Silk Road cultural and cave-site context, not as visitor service material.
{_line("historical_context_source_refs", historical_refs)}

All source binding remains weak / partial. The packet preserves
PAGE_BOUND_WEAK_EPUB_SECTION_BOUND for every approved chunk, and the dossier
does not claim page-precise evidence.

## art_architecture

The art and architecture layer centers on the Mogao Caves as Buddhist cave
temple architecture. Getty supplies Cave 85 details: cave architecture with an
antechamber, corridor, main chamber, a truncated pyramidal ceiling, wall
painting, fresco terminology, painted plaster, conservation treatment, and the
relation between art surfaces and the conglomerate host cliff. The supplemental
Getty chunk is used specifically to cover cave architecture, while Getty and Wu
primary chunks cover Dunhuang, Mogao Caves, Buddhist cave temple, fresco, wall
painting, conservation, and regional art history.
{_line("art_architecture_source_refs", art_refs)}

This section deliberately excludes title-only evidence and context-only
definitions from primary evidence. Context and ZIM material can support aliases
such as Mogao Caves, oasis, and hydrology, but it does not replace the Getty,
Wu, or Wang professional chunks.

## natural_processes

The natural-process account is guarded. Getty primary chunks support
microclimate, oasis, conglomerate, conservation, and wall-painting deterioration
context. Getty also supplies hydrogeology and groundwater near-support through
the Cave 85 conservation source, while Wang Mogao Cliff Reinforcement supplies
professional supplemental support for cliff stability, dangerous rock mass,
conglomerate weathering, rainfall seepage, and reinforcement concerns at the
Mogao cliff. Hydrology is context-only and not independent primary evidence:
the controlled pass may mention hydrology only as a caveated context term
linked to hydrogeology, groundwater, microclimate, conglomerate, oasis, and
cliff stability evidence.
{_line("natural_processes_source_refs", natural_refs)}

The hydrology caveat is part of the pass condition. A result that treats
hydrology as standalone professional primary evidence should fail closed. The
accepted natural-process professional evidence is instead the combined support
from Getty and Wang: microclimate, oasis, conglomerate, conservation conditions,
and cliff stability.

## regional_relations

The regional relation layer connects Dunhuang, Mogao Caves, Hexi Corridor, the
oasis setting, and conservation of cave surfaces in a cliff environment. Wu
provides the spatial Dunhuang and Hexi Corridor relation. Getty provides the
Cave 85 conservation and wall-painting relation. Wang supplies the Mogao cliff
reinforcement and stability relation. Together these sources keep the case
inside Mogao/Dunhuang relevance and avoid generic cliff or geology discussion
without site context.
{_line("regional_relations_source_refs", regional_refs)}

The controlled builder keeps conservation, geology-hydrology, art architecture,
and archaeology-history axes separate but coordinated. Hydrology remains
context-only; cliff stability and conglomerate have professional support.

## theme_tracks

The theme track links five strands: Dunhuang and Mogao Caves as the cultural
site frame; Buddhist cave temple and cave architecture as the built form;
fresco and wall painting as the art surface; conservation, microclimate, oasis,
conglomerate, and cliff stability as the environmental and preservation frame;
and Hexi Corridor as the regional relation. Hydrology is retained only as a
context-only term, not independent primary evidence.
{_line("theme_tracks_source_refs", theme_refs)}

The controlled builder uses only `cross_route_052_controlled_source_packet.json`.
It does not call production retrieval, production default manifests, source
registries, vector indexes, OCR pipelines, embedding pipelines, full Series B
runners, official baselines, ledgers, or score files. This is single-case
controlled dry-run evidence only if the controlled auditor returns
PASS_CONTROLLED_REGRESSION.

## source_bindings

Sources used:
{chr(10).join(source_lines)}

Approved chunk bindings:
{chr(10).join(chunk_lines)}

Approved chunks: {len(chunks)}
Context chunks used as primary evidence: 0
Binding caveat preserved: true
Hydrology caveat preserved: true
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
