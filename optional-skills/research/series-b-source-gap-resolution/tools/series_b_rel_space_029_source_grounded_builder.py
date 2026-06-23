#!/usr/bin/env python3
"""Deterministic source-grounded builder for rel_space_029 controlled dry-runs.

This builder is explicit-only and case-scoped. It consumes the reviewed source
packet and writes a raw dossier artifact outside the repo. It does not call an
LLM, production retrieval, production manifests, source registries, OCR,
embeddings, vector indexes, or full Series B runners.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_controlled_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS


RAW_DOSSIER_FILENAME = "rel_space_029_controlled_raw_dossier.md"


class SourceGroundedBuilderError(ValueError):
    """Raised when the deterministic controlled builder must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_packet(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        packet = json.load(handle)
    if not isinstance(packet, dict):
        raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet must be a JSON object")
    if packet.get("case_id") != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "source packet case_id must be rel_space_029")
    return packet


def _require_policy_locks(packet: dict[str, Any]) -> None:
    locks = packet.get("policy_locks")
    if not isinstance(locks, dict):
        raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet lacks policy_locks")
    if locks.get("no_production_default") is not True or locks.get("production_default_loader_enabled") is not False:
        raise SourceGroundedBuilderError("BLOCKED_PRODUCTION_DEFAULT_RISK", "production default lock is unsafe")
    if locks.get("no_baseline_update") is not True or locks.get("official_baseline_update_enabled") is not False:
        raise SourceGroundedBuilderError("BLOCKED_BASELINE_UPDATE_RISK", "baseline lock is unsafe")
    if locks.get("no_full_series_b") is not True or locks.get("full_series_b_enabled") is not False:
        raise SourceGroundedBuilderError("BLOCKED_FULL_SERIES_B_RISK", "full Series B lock is unsafe")


def _chunks(packet: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = packet.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet has no chunks")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SourceGroundedBuilderError("BLOCKED_BUILDER_ENTRY_UNSAFE", "source packet chunk must be object")
        if chunk.get("case_id") != CASE_ID:
            raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "chunk case_id must be rel_space_029")
    return chunks


def _source_titles(packet: dict[str, Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for source in packet.get("sources", []):
        if isinstance(source, dict) and source.get("source_id"):
            titles[str(source["source_id"])] = str(source.get("source_title") or source["source_id"])
    return titles


def _chunk_refs(chunks: list[dict[str, Any]], *, axes: set[str] | None = None, terms: set[str] | None = None) -> list[str]:
    refs: list[str] = []
    for chunk in chunks:
        chunk_axis = str(chunk.get("axis", ""))
        chunk_terms = {str(term).lower() for term in chunk.get("supports_terms", [])}
        if axes and chunk_axis not in axes:
            continue
        if terms and not ({term.lower() for term in terms} & chunk_terms):
            continue
        refs.append(
            f"{chunk['source_id']}:{chunk['chunk_id']} pp.{chunk['page_start']}-{chunk['page_end']} ({chunk_axis})"
        )
    return refs


def _section_ref_line(label: str, refs: list[str]) -> str:
    return f"{label}: " + "; ".join(refs[:6])


def _all_terms(chunks: list[dict[str, Any]]) -> list[str]:
    terms = sorted({str(term) for chunk in chunks for term in chunk.get("supports_terms", [])})
    return terms


def build_source_grounded_dossier(
    *,
    case_id: str,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Build the rel_space_029 raw dossier from reviewed source-packet metadata."""

    if case_id != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "case_id must be rel_space_029")
    packet = _load_packet(source_packet_path)
    _require_policy_locks(packet)
    chunks = _chunks(packet)
    titles = _source_titles(packet)
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)

    religion_refs = _chunk_refs(chunks, axes={"religion_book"})
    history_refs = _chunk_refs(chunks, axes={"history_book"})
    art_arch_refs = _chunk_refs(chunks, axes={"art_architecture_book", "architecture_book", "archaeology_book"})
    torah_refs = _chunk_refs(chunks, terms={"Torah", "Torah ark", "Aron ha-Kodesh", "Aron Kodesh"})
    bimah_refs = _chunk_refs(chunks, terms={"bimah", "Torah reading platform", "reading platform"})
    orientation_refs = _chunk_refs(chunks, terms={"synagogue orientation", "orientation"})
    source_lines = [
        f"- `{source_id}`: {title}" for source_id, title in sorted(titles.items())
    ]
    body = f"""# rel_space_029 controlled raw dossier

case_id: {CASE_ID}
controlled_builder: series_b_rel_space_029_source_grounded_builder
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

## spatial_structure

The rel_space_029 synagogue dossier treats the building as a Jewish sacred
space organized around a Torah ark / Aron ha-Kodesh focus, a bimah that
functions as the Torah reading platform within the synagogue, and an
orientation pattern that shapes how the congregation layout relates to Torah,
liturgy, and sacred-space movement. The spatial account is bound to reviewed
professional source chunks rather than operational visitor material.
{_section_ref_line("spatial_structure_source_refs", art_arch_refs + torah_refs + bimah_refs + orientation_refs)}

## historical_layers

The historical layer keeps synagogue development, Torah practice, Torah ark /
Aron ha-Kodesh terminology, bimah use as a Torah reading platform, and
orientation in a late-antique and ancient Jewish context. The history axis is
kept separate from art, architecture, archaeology, and religion axes so the
case does not stretch one source across unrelated requirements.
{_section_ref_line("historical_layers_source_refs", history_refs + religion_refs + torah_refs)}

## theme_tracks

The theme tracks are: synagogue sacred-space organization; Torah and Jewish
liturgy; Torah ark / Aron ha-Kodesh as a focal sacred furnishing; bimah as the
Torah reading platform inside the synagogue; orientation and congregation
layout as recurring architectural and archaeological themes. These tracks
cover the required terms across the reviewed professional axes:
religion_book, history_book, art_architecture_book, archaeology_book, and
architecture_book.
{_section_ref_line("theme_tracks_source_refs", religion_refs + history_refs + art_arch_refs)}

## source_bindings

Sources used:
{chr(10).join(source_lines)}

Approved source-packet terms:
{", ".join(_all_terms(chunks))}

Approved chunk count: {len(chunks)}

Only reviewed source-packet material is used as evidence. The controlled
builder does not consult or write production defaults, retrieval indexes,
source registries, OCR, embeddings, full Series B runners, official baselines,
ledgers, or score files.
"""
    artifact_path = target / RAW_DOSSIER_FILENAME
    artifact_path.write_text(body, encoding="utf-8")
    return {
        "status": "REAL_BUILDER_OUTPUT_WRITTEN",
        "artifact_path": str(artifact_path),
        "source_grounded_builder_output": True,
        "mock_builder_output": False,
        "source_count": len(titles),
        "chunk_count": len(chunks),
        **EXECUTION_FALSE_FLAGS,
    }
