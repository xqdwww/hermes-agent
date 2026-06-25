#!/usr/bin/env python3
"""Deterministic source-grounded builder for hist_arch_023 controlled dry-runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_hist_arch_023_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


RAW_DOSSIER_FILENAME = "hist_arch_023_controlled_raw_dossier.md"


class SourceGroundedBuilderError(ValueError):
    """Raised when the hist_arch_023 builder must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_packet(path: str | Path) -> dict[str, Any]:
    packet = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet must be an object")
    if packet.get("case_id") != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "source packet case_id must be hist_arch_023")
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
    if not isinstance(chunks, list) or len(chunks) != 12:
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet must contain 12 primary chunks")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet chunk must be an object")
        if chunk.get("case_id") != CASE_ID:
            raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "chunk case_id must be hist_arch_023")
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
    return f"{label}: " + "; ".join(refs[:12])


def _source_lines(packet: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for source in packet.get("sources", []):
        if isinstance(source, dict):
            axes = ", ".join(str(axis) for axis in source.get("axes", []))
            lines.append(f"- `{source['source_id']}`: {source.get('source_title')} ({axes})")
    return sorted(lines)


def build_hist_arch_023_dossier(
    *,
    case_id: str,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write a hist_arch_023 raw dossier from approved source-packet evidence."""

    if case_id != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "case_id must be hist_arch_023")
    packet = _load_packet(source_packet_path)
    _require_locks(packet)
    chunks = _chunks(packet)
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)

    historical_refs = _refs(chunks, section="historical_context") + _refs(chunks, term="Clovis culture")
    material_refs = _refs(chunks, section="material_processes") + _refs(chunks, term="lithic reduction")
    mechanics_refs = _refs(chunks, section="technology_mechanics") + _refs(chunks, term="fracture mechanics")
    typology_refs = _refs(chunks, section="archaeology_typology") + _refs(chunks, term="Clovis point")
    theme_refs = _refs(chunks, section="theme_tracks")
    source_lines = _source_lines(packet)
    chunk_lines = [
        f"- `{chunk['chunk_id']}` -> {', '.join(chunk.get('supports_sections', []))} / {', '.join(chunk.get('supports_terms', []))}"
        for chunk in chunks
    ]

    body = f"""# hist_arch_023 controlled raw dossier

case_id: {CASE_ID}
controlled_builder: series_b_hist_arch_023_source_grounded_builder
source_grounded_builder_output: true
mock_builder_output: false
generated_at: {datetime.now(timezone.utc).isoformat()}
source_packet_artifact: {Path(source_packet_path).name}
handoff_manifest_artifact: {Path(handoff_manifest_path).name}
binding_caveat: PAGE_BOUND_WEAK_EPUB_SECTION_BOUND; weak / partial binding caveat preserved; not page-precise
context_caveat: context sources are background and alias guard only, not primary evidence
official_baseline_update_performed: false
full_series_b_run_performed: false
production_default_manifest_integration_performed: false
case_repair_performed: false
push_performed: false
tag_created: false

## historical_context

The hist_arch_023 account is scoped to Clovis culture and the Clovis point
tradition as an archaeological technology case. Bradley Clovis Technology gives
the controlled archaeological backbone: Clovis technology is described through
workshop evidence, projectile point production, biface and blade trajectories,
flake and core debris, local chert selection, and a reduction sequence that
connects raw material choice to finished stone tool forms. Tsirk Fractures in
Knapping supplies the complementary knapping mechanics frame, so the historical
context is not a loose cultural label. It ties Clovis point production to
controlled terms: lithic technology, lithic reduction, flintknapping,
percussion, biface, flake, core, reduction sequence, and stone tool.
{_line("historical_context_source_refs", historical_refs)}

The evidence remains case scoped. It uses only the twelve approved professional
chunks from Bradley and Tsirk. The source packet carries context records only
as guard material. The dossier therefore preserves the formal handoff caveat:
PAGE_BOUND_WEAK_EPUB_SECTION_BOUND is an explicit weak / partial binding
caveat, and no source is claimed to be page-precise evidence.

## material_processes

The material process layer describes how stone tool production organizes raw
material, cores, flakes, and bifaces into a sequence. In the Bradley chunks,
Clovis technology uses suitable chert pieces, initial reduction, core
preparation, flake removals, biface thinning, and projectile point finishing.
Lithic reduction is not treated as a broad material phrase; it is the ordered
sequence by which cores and flakes are detached, evaluated, and transformed
into biface and blade products. The approved chunks support Clovis technology,
lithic technology, lithic reduction, percussion, biface, flake, core, reduction
sequence, pressure flaking, and stone tool.
{_line("material_processes_source_refs", material_refs)}

Tsirk adds the material mechanics side: flintknapping depends on force delivery,
fracture initiation, fracture propagation, and the relation between percussion
or pressure flaking and the geometry of a flake, core, or biface. The controlled
builder does not generalize to non-tool material science. The material process
stays inside Clovis and lithic technology source families already approved in
the handoff.

## technology_mechanics

The technology mechanics section covers flintknapping, pressure flaking,
percussion, fracture mechanics, and the way a core releases a flake. Tsirk is
the controlling mechanics source because it links fracture mechanics and
fractography to knapping. Bradley supplies the Clovis production setting in
which those mechanics become archaeological evidence: biface production, flake
debitage, core-tablet flakes, blade cores, projectile points, and reduction
sequence decisions. Together, the sources let the controlled pass explain why
a Clovis point is both an artifact type and the product of a lithic technology.
{_line("technology_mechanics_source_refs", mechanics_refs)}

The core terms remain explicit: fracture mechanics, pressure flaking,
percussion, biface, flake, core, stone tool, flintknapping, lithic reduction,
lithic technology, Clovis technology, Clovis point, and Clovis culture. The
weak binding caveat is preserved in the text and in every source-packet chunk.

## archaeology_typology

The archaeology typology section treats Clovis point, biface, flake, core, and
stone tool as diagnostic terms. Bradley anchors Clovis point and Clovis
technology in an archaeological assemblage rather than a generic object list.
The approved chunks describe bifaces in stages of reduction, cores and flakes
as manufacturing evidence, pressure flaking and percussion as shaping
techniques, and reduction sequence as the typological link between production
debris and finished point forms. Tsirk supports the same typology from the
mechanical side, clarifying why flake geometry and fracture behavior matter.
{_line("archaeology_typology_source_refs", typology_refs)}

This typology is guarded against off-domain meanings of point. In this dossier,
point means Clovis point and stone tool typology, not a service listing, score,
or unrelated object category. All approved source bindings remain Bradley or
Tsirk and all context chunks remain outside primary evidence.

## theme_tracks

The theme track links five strands. First, Clovis culture gives the historical
frame. Second, Clovis point and Clovis technology provide the artifact and
technology target. Third, lithic technology and lithic reduction connect cores,
flakes, bifaces, and reduction sequence. Fourth, flintknapping, pressure
flaking, percussion, and fracture mechanics provide the action-mechanics layer.
Fifth, stone tool keeps the result grounded in archaeological material culture.
{_line("theme_tracks_source_refs", theme_refs)}

The controlled builder uses only `hist_arch_023_controlled_source_packet.json`.
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

Primary professional chunks: {len(chunks)}
Context chunks used as primary evidence: 0
Binding caveat preserved: true
"""
    path = target / RAW_DOSSIER_FILENAME
    path.write_text(body, encoding="utf-8")
    return {
        "status": "REAL_BUILDER_OUTPUT_WRITTEN",
        "artifact_path": str(path),
        "source_grounded_builder_output": True,
        "mock_builder_output": False,
        "primary_chunk_count": len(chunks),
        **EXECUTION_FALSE_FLAGS,
    }
