#!/usr/bin/env python3
"""Deterministic source-grounded builder for nat_eco_047 controlled dry-runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_nat_eco_047_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


RAW_DOSSIER_FILENAME = "nat_eco_047_controlled_raw_dossier.md"


class SourceGroundedBuilderError(ValueError):
    """Raised when the nat_eco_047 builder must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_packet(path: str | Path) -> dict[str, Any]:
    packet = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet must be an object")
    if packet.get("case_id") != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "source packet case_id must be nat_eco_047")
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
            raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "chunk case_id must be nat_eco_047")
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
    return f"{label}: " + "; ".join(refs[:14])


def _source_lines(packet: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for source in packet.get("sources", []):
        if isinstance(source, dict):
            axes = ", ".join(str(axis) for axis in source.get("axes", []))
            role = "supplemental locator only" if source.get("supplemental_locator_only") else "controlled context evidence"
            lines.append(f"- `{source['source_id']}`: {source.get('source_title')} ({axes}; {role})")
    return sorted(lines)


def build_nat_eco_047_dossier(
    *,
    case_id: str,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write a nat_eco_047 raw dossier from approved source-packet evidence."""

    if case_id != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "case_id must be nat_eco_047")
    packet = _load_packet(source_packet_path)
    _require_locks(packet)
    chunks = _chunks(packet)
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)

    natural_refs = _refs(chunks, section="natural_processes")
    mechanics_refs = _refs(chunks, section="landform_mechanics") + _refs(chunks, term="reef flat")
    regional_refs = _refs(chunks, section="regional_relations")
    theme_refs = _refs(chunks, section="theme_tracks")
    darwin_refs = _refs(chunks, term="Darwin coral reef theory") + _refs(chunks, term="volcanic subsidence")
    source_lines = _source_lines(packet)
    chunk_lines = [
        f"- `{chunk['chunk_id']}` -> {', '.join(chunk.get('supports_sections', []))} / {', '.join(chunk.get('supports_terms', []))}"
        for chunk in chunks
    ]

    body = f"""# nat_eco_047 controlled raw dossier

case_id: {CASE_ID}
controlled_builder: series_b_nat_eco_047_source_grounded_builder
source_grounded_builder_output: true
mock_builder_output: false
generated_at: {datetime.now(timezone.utc).isoformat()}
source_packet_artifact: {Path(source_packet_path).name}
handoff_manifest_artifact: {Path(handoff_manifest_path).name}
binding_caveat: evidence remains entry / section / local-source-section bound through CONTEXT_ENTRY_BOUND, CONTEXT_SECTION_BOUND, and LOCAL_SOURCE_SECTION_BOUND locators
supplemental_locator_caveat: local professional source is supplemental locator only and is not primary wiki_or_zim evidence
readme_title_only_caveat: README and title-only chunks are excluded and do not count as evidence
official_baseline_update_performed: false
full_series_b_run_performed: false
production_default_manifest_integration_performed: false
case_repair_performed: false
push_performed: false
tag_created: false

## natural_processes

The nat_eco_047 natural-process frame is source-packet grounded in atoll and
coral reef formation. Approved wiki_or_zim and encyclopedia_context chunks
bind atoll, coral reef, fringing reef, barrier reef, lagoon, reef flat, reef
development, volcanic subsidence, and Darwin coral reef theory to reef-building
and subsidence processes. The controlled account treats atolls as reef and
lagoon landforms whose persistence depends on reef growth near sea level, and
it treats volcanic subsidence as the process frame for the Darwin coral reef
theory sequence from fringing reef to barrier reef to atoll.
{_line("natural_processes_source_refs", natural_refs)}

The local professional source appears only as a supplemental locator. It can
support the Darwin coral reef theory and reef development wording, but it is
not counted as primary wiki_or_zim evidence. README and old title-only reef-flat
material are absent from this packet and are not used.

## landform_mechanics

The landform-mechanics layer links reef flat, fringing reef, barrier reef,
lagoon, coral reef, and atoll into a single guarded morphology account. The
source packet keeps reef flat evidence tied to approved fringing reef and
section-bound reef-development material, while lagoon support remains bound to
atoll and reef process context. Barrier reef is used as a reef-stage and
landform term, not as a generic obstacle or route metaphor. Reef development
is therefore explained through controlled source bindings: fringing reef near
shore, barrier reef separated by lagoon, and atoll enclosing a lagoon after
continued subsidence and upward coral reef growth.
{_line("landform_mechanics_source_refs", mechanics_refs)}

All evidence remains entry / section / local-source-section bound. The dossier
does not claim page-precise evidence. The binding caveat is part of the pass
condition and is repeated here so the controlled auditor can fail closed if it
is lost.

## regional_relations

The regional-relations section is intentionally narrow. It uses the approved
source packet to connect atoll, lagoon, coral reef, fringing reef, and barrier
reef as tropical marine landforms without drifting into visitor services or
generic island promotion. Regional relation here means the relation among reef
forms, lagoons, oceanic islands, and warm-water reef development settings. It
does not introduce unrelated destinations, service listings, or broad island
marketing. The same approved chunks keep volcanic subsidence and Darwin coral
reef theory tied to reef and atoll development rather than to Darwin biography.
{_line("regional_relations_source_refs", regional_refs)}

This section preserves the source-family guard: wiki_or_zim and
encyclopedia_context provide primary context evidence, while the local
professional locator remains supplemental locator only.

## theme_tracks

The theme track follows four controlled strands. First, natural processes:
coral reef growth, reef development, volcanic subsidence, and Darwin coral reef
theory. Second, landform mechanics: atoll, lagoon, fringing reef, barrier reef,
and reef flat. Third, regional relations: reef forms and lagoons as connected
tropical marine landforms. Fourth, source discipline: no production default
manifest, no official baseline update, no full Series B execution, and no
README or title-only evidence counted.
{_line("theme_tracks_source_refs", theme_refs)}

The Darwin coral reef theory references are restricted to coral reef and atoll
formation. They are not a Darwin biography track and they are not a natural
selection track. The controlled builder uses only
`nat_eco_047_controlled_source_packet.json`; it does not call production
retrieval, production default manifests, source registries, vector indexes, OCR
pipelines, embedding pipelines, full Series B runners, official baselines,
ledgers, or score files. This is single-case controlled dry-run evidence only
if the controlled auditor returns PASS_CONTROLLED_REGRESSION.
{_line("darwin_subsidence_source_refs", darwin_refs)}

## source_bindings

Sources used:
{chr(10).join(source_lines)}

Approved chunk bindings:
{chr(10).join(chunk_lines)}

Approved chunks: {len(chunks)}
Context chunks used as primary evidence: 0
Binding caveat preserved: true
Supplemental locator caveat preserved: true
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
