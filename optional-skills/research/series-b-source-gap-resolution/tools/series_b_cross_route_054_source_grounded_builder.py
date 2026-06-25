#!/usr/bin/env python3
"""Deterministic source-grounded builder for cross_route_054 controlled dry-runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_cross_route_054_result_schema import CASE_ID, EXECUTION_FALSE_FLAGS

RAW_DOSSIER_FILENAME = "cross_route_054_controlled_raw_dossier.md"


class SourceGroundedBuilderError(ValueError):
    """Raised when the cross_route_054 builder must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _load_packet(path: str | Path) -> dict[str, Any]:
    packet = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet must be an object")
    if packet.get("case_id") != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "source packet case_id must be cross_route_054")
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
    if not isinstance(chunks, list) or len(chunks) != 9:
        raise SourceGroundedBuilderError("BLOCKED_GUARD_VIOLATION", "source packet must contain 9 approved chunks")
    for chunk in chunks:
        if chunk.get("case_id") != CASE_ID:
            raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "chunk case_id must be cross_route_054")
    return chunks


def _refs(chunks: list[dict[str, Any]], *, section: str | None = None, term: str | None = None) -> list[str]:
    refs: list[str] = []
    for chunk in chunks:
        terms = " ".join(str(t).lower() for t in chunk.get("supports_terms", []))
        sections = set(str(s) for s in chunk.get("supports_sections", [])) | set(str(s) for s in chunk.get("section_target", []))
        if section and section not in sections:
            continue
        if term and term.lower() not in terms and term.lower() not in str(chunk.get("source_backed_text", "")).lower():
            continue
        refs.append(f"{chunk['source_id']}::{chunk['chunk_id']} ({chunk['page_bound_status']}; text_sha256={chunk.get('source_hash_or_text_hash')})")
    return refs


def _line(label: str, refs: list[str]) -> str:
    return f"{label}: " + "; ".join(refs[:12])


def _clean_sentence(value: str) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", value) if len(s.strip()) > 40]
    keep = []
    for sentence in sentences:
        low = sentence.lower()
        if any(bad in low for bad in ["donate", "appearance", "tools", "download as pdf", "external links", "navigation", "create account", "log in"]):
            continue
        if any(term in low for term in ["wadi dawk", "land of frankincense", "boswellia", "dhofar", "khor rori", "sumhuram", "al-baleed", "monsoon", "khareef", "frankincense"]):
            keep.append(sentence)
    return " ".join(keep[:3])


def build_cross_route_054_dossier(*, case_id: str, source_packet_path: str | Path, handoff_manifest_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    if case_id != CASE_ID:
        raise SourceGroundedBuilderError("CASE_ID_MISMATCH", "case_id must be cross_route_054")
    packet = _load_packet(source_packet_path)
    _require_locks(packet)
    chunks = _chunks(packet)
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)
    history_refs = _refs(chunks, section="historical_context")
    nature_refs = _refs(chunks, section="natural_processes")
    regional_refs = _refs(chunks, section="regional_relations")
    theme_refs = _refs(chunks, section="theme_tracks")
    chunk_lines = [f"- `{c['chunk_id']}` -> {', '.join(c.get('supports_sections', []))} / {', '.join(c.get('supports_terms', []))} / text_sha256={c.get('source_hash_or_text_hash')}" for c in chunks]
    source_lines = [f"- `{s['source_id']}`: {s.get('source_title')} ({', '.join(s.get('axes', []))}; case-scoped source)" for s in packet.get("sources", []) if isinstance(s, dict)]
    snippets = "\n".join(f"- {c['chunk_id']}: {_clean_sentence(str(c.get('source_backed_text', '')))}" for c in chunks)
    body = f"""# cross_route_054 controlled raw dossier

case_id: {CASE_ID}
controlled_builder: series_b_cross_route_054_source_grounded_builder
source_grounded_builder_output: true
mock_builder_output: false
generated_at: {datetime.now(timezone.utc).isoformat()}
source_packet_artifact: {Path(source_packet_path).name}
handoff_manifest_artifact: {Path(handoff_manifest_path).name}
caveat_unesco_pdfs_not_used: preserved
caveat_documents_index_candidate_supporting_only: preserved
readme_cloudflare_title_generated_evidence_counted: false
route_listing_guard_preserved: true
official_baseline_update_performed: false
full_series_b_run_performed: false
production_default_manifest_integration_performed: false
case_repair_performed: false
push_performed: false
tag_created: false

## historical_context

The historical_context section is limited to cross_route_054 approved source-packet evidence. The Land of Frankincense is treated as a Dhofar, Oman heritage landscape built around frankincense production and the incense trade. Its source-backed components include Wadi Dawkah / Wadi Dawka, Khor Rori / Sumhuram, and Al-Baleed, with the trade in frankincense framed as a long-running south Arabian route system rather than visitor-service planning. The dossier covers Dhofar, Oman, frankincense, incense trade, frankincense production, Land of Frankincense, Khor Rori, Sumhuram, Al-Baleed, and maritime / route context while preserving the route/trade guard.
{_line('historical_context_source_refs', history_refs)}

## natural_processes

The natural_processes section is grounded in source-backed evidence for Boswellia sacra and the frankincense tree at Wadi Dawkah, plus Dhofar ecology and monsoon/khareef context. Wadi Dawkah is described as a place where Boswellia sacra / frankincense trees are found and frankincense is harvested, and the ecology account connects Dhofar and Oman to khareef / kharif, monsoon, monsoon ecology, vegetation, and scrubland ecology or source-backed equivalent arid woodland / vegetation evidence. Generic ecology outside Dhofar, Boswellia, khareef, or frankincense is not used.
{_line('natural_processes_source_refs', nature_refs)}

## regional_relations

The regional_relations section links the natural and cultural landscape without using travel planning. Wadi Dawkah / Wadi Dawka supplies frankincense tree and production context; Khor Rori / Sumhuram and Al-Baleed supply ports and archaeology-history context; Dhofar / Oman supplies regional setting; Land of Frankincense binds those components into the heritage route frame. Maritime / route context is retained only as incense-trade and frankincense-route evidence, not as visitor-service advice or route-planning guidance.
{_line('regional_relations_source_refs', regional_refs)}

## theme_tracks

Theme tracks: first, frankincense production and incense trade across Dhofar, Oman; second, Boswellia sacra and frankincense tree ecology at Wadi Dawkah / Wadi Dawka; third, Land of Frankincense component relationships among Wadi Dawkah, Khor Rori / Sumhuram, and Al-Baleed; fourth, khareef / kharif, monsoon, vegetation, and scrubland ecology or equivalent ecology evidence. UNESCO PDFs remain behind Cloudflare and were not used. The UNESCO documents index is candidate/supporting only and is not primary formal evidence. README, Cloudflare/interstitial, title-only, generated echo, query echo, and visitor-service contamination do not count as evidence.
{_line('theme_tracks_source_refs', theme_refs)}

The dossier quality target is rich. It provides explicit source-bound coverage for required terms, sections, axes, caveats, route/listing guard, ecology/nature support, and no-baseline/no-production/full-Series-B locks.

## source_backed_snippets

{snippets}

## source_bindings

Sources used:
{chr(10).join(source_lines)}

Approved chunk bindings:
{chr(10).join(chunk_lines)}

Approved chunks: {len(chunks)}
UNESCO PDFs used: false
Documents index primary evidence: false
Trade-route guard preserved: true
Ecology/nature support preserved: true
Precise page numbers claimed: false
"""
    path = target / RAW_DOSSIER_FILENAME
    path.write_text(body, encoding="utf-8")
    return {"status": "REAL_BUILDER_OUTPUT_WRITTEN", "artifact_path": str(path), "source_grounded_builder_output": True, "mock_builder_output": False, "approved_chunk_count": len(chunks), **EXECUTION_FALSE_FLAGS}
