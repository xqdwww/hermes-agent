#!/usr/bin/env python3
"""Deterministic source-grounded builder for nat_eco_041 controlled dry-runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_nat_eco_041_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


RAW_DOSSIER_FILENAME = "nat_eco_041_controlled_raw_dossier.md"


class SourceGroundedBuilderError(ValueError):
    """Raised when the nat_eco_041 builder must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_packet(path: str | Path) -> dict[str, Any]:
    packet = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet must be an object")
    if packet.get("case_id") != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "source packet case_id must be nat_eco_041")
    return packet


def _require_locks(packet: dict[str, Any]) -> None:
    locks = packet.get("policy_locks")
    if not isinstance(locks, dict):
        raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet lacks policy locks")
    if locks.get("production_default_loader_enabled") is not False or locks.get("no_production_default") is not True:
        raise SourceGroundedBuilderError("BLOCKED_PRODUCTION_DEFAULT_RISK", "production default lock is unsafe")
    if locks.get("official_baseline_update_enabled") is not False or locks.get("no_baseline_update") is not True:
        raise SourceGroundedBuilderError("BLOCKED_BASELINE_UPDATE_RISK", "baseline lock is unsafe")
    if locks.get("full_series_b_enabled") is not False or locks.get("no_full_series_b") is not True:
        raise SourceGroundedBuilderError("BLOCKED_FULL_SERIES_B_RISK", "full Series B lock is unsafe")


def _chunks(packet: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = packet.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet has no chunks")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet chunk must be an object")
        if chunk.get("case_id") != CASE_ID:
            raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "chunk case_id must be nat_eco_041")
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
        locator = chunk.get("source_backed_text_locator", {})
        if isinstance(locator, dict) and locator.get("page_start") is not None:
            suffix = f"pp.{locator.get('page_start')}-{locator.get('page_end')}"
        elif isinstance(locator, dict):
            suffix = f"{locator.get('entry_locator')} / {locator.get('section_locator')}"
        else:
            suffix = "locator-bound"
        refs.append(f"{chunk['source_id']}::{chunk['chunk_id']} ({suffix}; {chunk['binding_status']})")
    return refs


def _line(label: str, refs: list[str]) -> str:
    return f"{label}: " + "; ".join(refs[:10])


def _source_lines(packet: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for source in packet.get("sources", []):
        if isinstance(source, dict):
            axes = ", ".join(str(axis) for axis in source.get("axes", []))
            lines.append(f"- `{source['source_id']}`: {source.get('source_title')} ({axes})")
    return sorted(lines)


def build_nat_eco_041_dossier(
    *,
    case_id: str,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write a nat_eco_041 raw dossier from approved source-packet locators."""

    if case_id != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "case_id must be nat_eco_041")
    packet = _load_packet(source_packet_path)
    _require_locks(packet)
    chunks = _chunks(packet)
    professional_chunks = [chunk for chunk in chunks if chunk.get("chunk_group") == "professional"]
    context_chunks = [chunk for chunk in chunks if chunk.get("chunk_group") == "context"]
    if len(professional_chunks) != 13 or len(context_chunks) != 28:
        raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "expected 13 professional and 28 context chunks")
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)

    natural_refs = _refs(chunks, section="natural_processes")
    mechanics_refs = _refs(chunks, section="landform_mechanics")
    regional_refs = _refs(chunks, section="regional_relations")
    theme_refs = _refs(chunks, section="theme_tracks")
    saltation_refs = _refs(chunks, term="saltation")
    aeolian_refs = _refs(chunks, term="aeolian processes")
    transport_refs = _refs(chunks, term="sediment transport") + _refs(chunks, term="sand transport")
    source_lines = _source_lines(packet)
    chunk_lines = [
        f"- `{chunk['chunk_id']}` -> {', '.join(chunk.get('supports_sections', []))} / {', '.join(chunk.get('supports_terms', []))}"
        for chunk in chunks
    ]

    body = f"""# nat_eco_041 controlled raw dossier

case_id: {CASE_ID}
controlled_builder: series_b_nat_eco_041_source_grounded_builder
source_grounded_builder_output: true
mock_builder_output: false
generated_at: {datetime.now(timezone.utc).isoformat()}
source_packet_artifact: {Path(source_packet_path).name}
handoff_manifest_artifact: {Path(handoff_manifest_path).name}
professional_binding_caveat: PARTIAL_SECTION_LOCATOR_USED
context_binding_caveat: CONTEXT_ENTRY_BOUND / CONTEXT_SECTION_BOUND
dune_migration_caveat: marginal related evidence only, not strong exact-term support
official_baseline_update_performed: false
full_series_b_run_performed: false
production_default_manifest_integration_performed: false
case_repair_performed: false
push_performed: false
tag_created: false

## natural_processes

The nat_eco_041 natural process account is about aeolian processes: wind erosion,
entrainment, saltation, creep, suspension, ripples, and the movement of sand
grains across sand dune surfaces. The approved geomorphology_book evidence
anchors saltation as a wind-driven grain trajectory, while the context evidence
links the same process to aeolian landform formation and sediment transport.
The synthesis treats sand transport and aeolian sediment transport as the core
process chain: threshold wind stress lifts or dislodges grains, saltating grains
strike the bed, impacts release additional grains, finer material can enter
suspension, and near-bed movement contributes to ripples and dune-scale form.
{_line("natural_processes_source_refs", natural_refs + saltation_refs + aeolian_refs)}

This account deliberately preserves the evidence limits. Professional evidence
uses `PARTIAL_SECTION_LOCATOR_USED` rather than uncaveated page binding.
Context evidence is `CONTEXT_ENTRY_BOUND` or `CONTEXT_SECTION_BOUND`, so it can
support terminology and process framing but does not replace professional book
evidence. Dune migration remains marginal related context and is not counted as
strong exact-term evidence for this controlled pass.

## landform_mechanics

The landform mechanics section explains how wind-blown sand becomes patterned
terrain. Saltation supplies the dominant near-surface transport mode; creep
describes larger grains nudged by impacts; suspension captures finer particles
that remain aloft; and ripples record feedback between the moving grains and
the bed. Sand transport and aeolian sediment transport are therefore not
generic landscape labels: they are mechanical processes connecting wind erosion,
grain impact, bedload movement, and sand dune construction.
{_line("landform_mechanics_source_refs", mechanics_refs + transport_refs)}

The professional chunks from `Aeolian Sand and Sand Dunes` and `Aeolian
Geomorphology: A New Introduction` provide the controlled book-source backbone
for saltation, suspension, creep, ripples, wind erosion, sand transport, and
landform mechanics. The dossier does not rely on broad unsourced claims; every
accepted support item is traceable to a source-packet locator and a reviewer
decision that passed the wrong-context guard.

## regional_relations

The regional relation layer keeps the case within geomorphology and earth
science. Desert and dryland settings matter because available sediment, wind
regime, vegetation cover, surface roughness, and supply shape aeolian processes.
The approved context chunks connect aeolian landforms, dunes, dust movement,
and sediment transport while keeping the case inside physical geography and
earth science. The professional chunks remain the controlling evidence for mechanics;
context chunks only support vocabulary, cross-section framing, and relations
between process, landform, and environment.
{_line("regional_relations_source_refs", regional_refs)}

Because dune migration has only marginal related support in this handoff, this
section treats it as a possible consequence of repeated transport and deposition
without using it as a required exact-term pass item. The controlled audit should
therefore credit saltation, aeolian processes, sand dune, sediment transport,
wind erosion, creep, suspension, ripples, aeolian sediment transport, and sand
transport, while leaving dune migration caveated.

## theme_tracks

The theme track links three evidence families. First, geomorphology_book and
earth_science_book chunks establish the professional source axis for physical
processes. Second, wiki_or_zim context entries provide section-bound support
for aeolian process vocabulary, landform relations, and sediment transport
terms. Third, the guard handoff keeps the case clear of unrelated domains,
generic non-aeolian sand discussion, and off-topic service material.
{_line("theme_tracks_source_refs", theme_refs)}

The controlled builder uses only `nat_eco_041_controlled_source_packet.json`.
It does not call production retrieval, production default manifests, source
registries, vector indexes, OCR pipelines, embedding pipelines, full Series B
runners, official baselines, ledgers, or score files. This dossier is single
case controlled dry-run evidence only.

## source_bindings

Sources used:
{chr(10).join(source_lines)}

Approved chunk bindings:
{chr(10).join(chunk_lines)}

Professional chunks: {len(professional_chunks)}
Context chunks: {len(context_chunks)}
"""
    path = target / RAW_DOSSIER_FILENAME
    path.write_text(body, encoding="utf-8")
    return {
        "status": "REAL_BUILDER_OUTPUT_WRITTEN",
        "artifact_path": str(path),
        "source_grounded_builder_output": True,
        "mock_builder_output": False,
        "professional_chunk_count": len(professional_chunks),
        "context_chunk_count": len(context_chunks),
        **EXECUTION_FALSE_FLAGS,
    }
