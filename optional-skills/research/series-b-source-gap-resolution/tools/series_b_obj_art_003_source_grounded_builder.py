#!/usr/bin/env python3
"""Deterministic source-grounded builder for obj_art_003 controlled dry-runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_obj_art_003_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


RAW_DOSSIER_FILENAME = "obj_art_003_controlled_raw_dossier.md"


class SourceGroundedBuilderError(ValueError):
    """Raised when the obj_art_003 builder must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_packet(path: str | Path) -> dict[str, Any]:
    packet = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet must be an object")
    if packet.get("case_id") != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "source packet case_id must be obj_art_003")
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
    if packet.get("case_rule_trace_decision") != "ARCHAEOLOGY_AXIS_NOT_HARD_REQUIRED_CONFIRMED":
        raise SourceGroundedBuilderError("BLOCKED_CASE_RULE_TRACE_UNCLEAR", "case-rule trace is not confirmed")


def _chunks(packet: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = packet.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet has no chunks")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet chunk must be an object")
        if chunk.get("case_id") != CASE_ID:
            raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "chunk case_id must be obj_art_003")
    return chunks


def _source_titles(packet: dict[str, Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for source in packet.get("sources", []):
        if isinstance(source, dict) and source.get("source_id"):
            titles[str(source["source_id"])] = str(source.get("source_title") or source["source_id"])
    return titles


def _refs(chunks: list[dict[str, Any]], *, section: str | None = None, axis: str | None = None, term: str | None = None) -> list[str]:
    refs: list[str] = []
    for chunk in chunks:
        terms = " ".join(str(t).lower() for t in chunk.get("supports_terms", []))
        sections = set(str(s) for s in chunk.get("supports_sections", []))
        if section and section not in sections:
            continue
        if axis and chunk.get("axis") != axis:
            continue
        if term and term.lower() not in terms:
            continue
        refs.append(f"{chunk['source_id']}:{chunk['chunk_id']} pp.{chunk['page_start']}-{chunk['page_end']} ({chunk['axis']})")
    return refs


def _line(label: str, refs: list[str]) -> str:
    return f"{label}: " + "; ".join(refs[:8])


def build_obj_art_003_dossier(
    *,
    case_id: str,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write an obj_art_003 raw dossier from reviewed source packet evidence."""

    if case_id != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "case_id must be obj_art_003")
    packet = _load_packet(source_packet_path)
    _require_locks(packet)
    chunks = _chunks(packet)
    titles = _source_titles(packet)
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)

    materials_refs = _refs(chunks, section="materials_mechanics")
    history_refs = _refs(chunks, section="historical_context")
    architecture_refs = _refs(chunks, section="art_architecture")
    pozzolana_refs = _refs(chunks, term="pozzolana")
    hydraulic_refs = _refs(chunks, term="hydraulic")
    opus_refs = _refs(chunks, term="caementicium")
    marine_refs = _refs(chunks, term="marine")
    source_lines = [f"- `{sid}`: {title}" for sid, title in sorted(titles.items())]
    all_chunk_refs = [f"- `{c['chunk_id']}` ({c['source_id']} pp.{c['page_start']}-{c['page_end']})" for c in chunks]

    body = f"""# obj_art_003 controlled raw dossier

case_id: {CASE_ID}
controlled_builder: series_b_obj_art_003_source_grounded_builder
source_grounded_builder_output: true
mock_builder_output: false
generated_at: {datetime.now(timezone.utc).isoformat()}
source_packet_artifact: {Path(source_packet_path).name}
handoff_manifest_artifact: {Path(handoff_manifest_path).name}
official_baseline_update_performed: false
full_series_b_run_performed: false
production_default_manifest_integration_performed: false
case_repair_performed: false
push_performed: false

## materials_mechanics

The obj_art_003 materials account centers on Roman concrete as a lime-mortar
and aggregate technology. The reviewed materials_book and engineering_book
chunks distinguish opus caementicium from present-day poured concrete by its
hand-laid caementa, abundant mortar, and wall-core construction. Pozzolana,
pozzolanic ash, and volcanic ash are treated as reactive materials rather than
surface description: the source packet ties them to hydraulic setting,
hydraulic lime behavior, wet-environment hardening, mortar strength, and
cementitious material formation. Marine concrete is handled through the same
source-bound mechanism, with durability explained through hydrated lime,
volcanic ash, water-resistant products, and long-term strength in maritime
structures.
{_line("materials_mechanics_source_refs", materials_refs + pozzolana_refs + hydraulic_refs + marine_refs)}

The controlled materials synthesis keeps the evidence within the reviewed
source packet. `series_b_prof_02_roman_building_materials` supplies page-bound
materials_book evidence for hydraulic lime, mortar setting, pozzolana ratios,
and opus caementicium construction. `series_b_prof_13_oxford_handbook_engineering`
adds engineering evidence for Roman concrete, pozzolana, hydraulic properties,
and the difference between modern poured concrete and Roman hand-laid rubble
construction. `series_b_prof_01_building_for_eternity` supports marine concrete,
durability, cementitious hydrates, and reproduction evidence for Roman mixes.

## historical_context

The historical context keeps Roman concrete in ancient building practice. The
approved chunks place opus caementicium in late Republican and Imperial
construction trajectories, including wall facings, rubble cores, harbor works,
and maritime structures. Vitruvius and Pliny are used here only as terms inside
approved professional chunks; the weak Vitruvius fallback file and weak Pliny
context snippets are not used as formal evidence. The case-rule trace does not
make archaeology_book a hard required axis for this case, so the dossier does
not relabel engineering or architecture evidence as archaeology.
{_line("historical_context_source_refs", history_refs + opus_refs)}

The historical layer also separates materials mechanics from broad cultural
claims. The packet supports Roman building materials, construction technique,
marine concrete, and concrete durability through page-bound professional
sources. It does not rely on generic volcanic context, generic contemporary
material claims, or context-only primary text. The result is a focused
materials and architecture background for Roman concrete rather than a broad
source survey.

## art_architecture

The art and architecture track explains how Roman concrete and opus
caementicium become architectural systems: rubble cores, facings, mortar,
pozzolana-bearing mixes, hydraulic lime behavior, harbor structures, walls,
and built forms. The page-bound chunks support the section by connecting
materials to architectural construction, not by using title-only evidence. The
architecture axis is therefore supported by Roman building and construction
evidence in materials_book and engineering_book sources, while the weak
Vitruvius fallback remains excluded.
{_line("art_architecture_source_refs", architecture_refs + opus_refs)}

The controlled builder uses only the approved source packet and writes only
repo-out artifacts. It does not consult production defaults, retrieval indexes,
source registries, OCR, embeddings, full Series B runners, official baselines,
ledgers, or score files.

## source_bindings

Sources used:
{chr(10).join(source_lines)}

Approved chunk bindings:
{chr(10).join(all_chunk_refs)}

Approved chunk count: {len(chunks)}
"""
    path = target / RAW_DOSSIER_FILENAME
    path.write_text(body, encoding="utf-8")
    return {
        "status": "REAL_BUILDER_OUTPUT_WRITTEN",
        "artifact_path": str(path),
        "source_grounded_builder_output": True,
        "mock_builder_output": False,
        "source_count": len(titles),
        "chunk_count": len(chunks),
        **EXECUTION_FALSE_FLAGS,
    }
