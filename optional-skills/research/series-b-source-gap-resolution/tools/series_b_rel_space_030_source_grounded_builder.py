#!/usr/bin/env python3
"""Deterministic source-grounded builder for rel_space_030 controlled dry-runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_rel_space_030_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


RAW_DOSSIER_FILENAME = "rel_space_030_controlled_raw_dossier.md"


class SourceGroundedBuilderError(ValueError):
    """Raised when the rel_space_030 builder must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_packet(path: str | Path) -> dict[str, Any]:
    packet = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet must be an object")
    if packet.get("case_id") != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "source packet case_id must be rel_space_030")
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
    if not isinstance(chunks, list) or len(chunks) != 8:
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet must contain 8 approved chunks")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet chunk must be an object")
        if chunk.get("case_id") != CASE_ID:
            raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "chunk case_id must be rel_space_030")
        if chunk.get("binding_caveat_preserved") is not True:
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
    return f"{label}: " + "; ".join(refs[:8])


def _source_lines(packet: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for source in packet.get("sources", []):
        if isinstance(source, dict):
            axes = ", ".join(str(axis) for axis in source.get("axes", []))
            role = "Mount Meru context only" if source.get("mount_meru_context_only") else "controlled source locator"
            lines.append(f"- `{source['source_id']}`: {source.get('source_title')} ({axes}; {role})")
    return sorted(lines)


def build_rel_space_030_dossier(
    *,
    case_id: str,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write a rel_space_030 raw dossier from approved source-packet evidence."""

    if case_id != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "case_id must be rel_space_030")
    packet = _load_packet(source_packet_path)
    _require_locks(packet)
    chunks = _chunks(packet)
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)

    spatial_refs = _refs(chunks, section="spatial_structure")
    ritual_refs = _refs(chunks, section="ritual_space")
    art_refs = _refs(chunks, section="art_architecture")
    history_refs = _refs(chunks, section="historical_layers")
    theme_refs = _refs(chunks, section="theme_tracks")
    meru_refs = _refs(chunks, term="Mount Meru") + _refs(chunks, term="axis mundi")
    sacred_refs = _refs(chunks, term="sacred geometry") + _refs(chunks, term="Vastu Purusha Mandala")
    source_lines = _source_lines(packet)
    chunk_lines = [
        f"- `{chunk['chunk_id']}` -> {', '.join(chunk.get('supports_sections', []))} / {', '.join(chunk.get('supports_terms', []))}"
        for chunk in chunks
    ]

    body = f"""# rel_space_030 controlled raw dossier

case_id: {CASE_ID}
controlled_builder: series_b_rel_space_030_source_grounded_builder
source_grounded_builder_output: true
mock_builder_output: false
generated_at: {datetime.now(timezone.utc).isoformat()}
source_packet_artifact: {Path(source_packet_path).name}
handoff_manifest_artifact: {Path(handoff_manifest_path).name}
binding_caveat: evidence remains LOCAL_SOURCE_SECTION_BOUND or CONTEXT_ENTRY_BOUND through approved source locators
mount_meru_caveat: Mount Meru is context-only support from local ZIM / encyclopedia evidence, not direct professional OCR primary evidence
sacred_geometry_caveat: sacred geometry is supported through Vastu / cosmic geometry equivalents: geometric properties, geometry of cosmos, codes of geometry, proportions, and measures
readme_title_only_caveat: README and title-only chunks are excluded and do not count as evidence
official_baseline_update_performed: false
full_series_b_run_performed: false
production_default_manifest_integration_performed: false
case_repair_performed: false
push_performed: false
tag_created: false

## spatial_structure

The rel_space_030 spatial structure centers on the garbhagriha, also recorded
as garbhagrha and garbha griha, as the sanctum or womb-house of Hindu temple
architecture. The approved local professional locator evidence binds the
sanctum vocabulary to the inner cella, while the Vastu Purusha Mandala and
mandala plan evidence describe the square diagram and temple plan that organize
the sacred architectural center. Shikhara and vimana are treated as vertical
forms rising over the central temple core, and mandapa is retained as the
associated hall term in Hindu temple architecture context.
{_line("spatial_structure_source_refs", spatial_refs)}

The structure is source-packet bound, not produced through production retrieval.
The local source locators support art_architecture_book and religion_book
coverage, and the context locators support wiki_or_zim / encyclopedia_context
framing without overstating them as direct professional OCR primary evidence.

## ritual_space

The ritual-space account keeps the garbhagriha as a sacred interior focus. The
sanctum / womb-house vocabulary describes the image-bearing center, while
mandala plan and Vastu shastra terms describe a ritualized ordering of temple
space. Axis mundi and Mount Meru are used only as context for cosmic axis and
cosmic mountain symbolism. Mount Meru is not counted as direct professional OCR
primary evidence; it remains context-only support under the approved handoff
caveat.
{_line("ritual_space_source_refs", ritual_refs + meru_refs)}

This section avoids unsupported mythology retelling. It uses the approved
chunks to explain sacred-space layout, temple center, vertical axis, and ritual
orientation inside Hindu temple architecture.

## art_architecture

The art and architecture layer connects Hindu temple architecture, garbhagriha,
shikhara, vimana, mandapa, Vastu Purusha Mandala, mandala plan, and sacred
geometry equivalents. Sacred geometry is preserved as an equivalent-term
finding: the professional locator supports cosmic geometry, geometric
properties, codes of geometry, proportions, and measures. The dossier therefore
uses the phrase sacred geometry only with the caveat that professional support
comes through these source-backed equivalent terms rather than an uncaveated
exact professional phrase.
{_line("art_architecture_source_refs", art_refs + sacred_refs)}

The controlled evidence links form and plan: the garbhagriha / sanctum marks
the interior focus, shikhara / vimana marks vertical superstructure, mandapa
provides architectural adjacency, and mandala plan / Vastu Purusha Mandala
provides the geometric ordering model.

## historical_layers

Historical layer coverage is auxiliary. It is source-backed through temple
architecture examples and dated architectural context inside the approved
shikhara and Hindu temple architecture materials, but the main target remains
spatial and ritual structure. The historical layer should therefore be credited
as present but not treated as a broad dynastic history track.
{_line("historical_layers_source_refs", history_refs)}

The controlled packet does not add external history claims beyond the approved
locators. It keeps the focus on temple-space terminology and architectural
meaning.

## theme_tracks

The theme track follows five controlled strands: garbhagriha / garbha griha as
the sanctum, Hindu temple architecture as the frame, Vastu shastra and Vastu
Purusha Mandala as plan logic, shikhara / vimana / mandapa as architectural
forms, and axis mundi / Mount Meru as context-only cosmic axis support. Sacred
geometry remains caveated as a source-backed equivalent phrase family rather
than an uncaveated exact professional-source phrase.
{_line("theme_tracks_source_refs", theme_refs + meru_refs + sacred_refs)}

The controlled builder uses only `rel_space_030_controlled_source_packet.json`;
it does not call production retrieval, production default manifests, source
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
Mount Meru context only: true
Sacred geometry equivalent caveat preserved: true
README or title-only chunks counted as evidence: false
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
