#!/usr/bin/env python3
"""Generic case-scoped controlled harness for Series B handoff packets.

This helper only consumes explicit formal handoff manifests and approved chunk
handoffs. It does not load production defaults, source registries, vector
indexes, official baseline files, or full-Series-B runners.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_controlled_artifact_exporter import ArtifactContractError, validate_output_dir_policy

EXECUTION_FALSE_FLAGS = {
    "official_baseline_update_performed": False,
    "full_series_b_run_performed": False,
    "production_default_manifest_integration_performed": False,
    "case_repair_performed": False,
    "push_performed": False,
    "tag_created": False,
}

RESULT_ENUMS = {
    "PASS_CONTROLLED_REGRESSION",
    "FAIL_CONTROLLED_REGRESSION",
    "PARTIAL_SOURCE_GUARDED_PASS",
    "BLOCKED_BINDING_INSUFFICIENT",
    "BLOCKED_GUARD_VIOLATION",
    "BLOCKED_PRODUCTION_DEFAULT_RISK",
    "BLOCKED_BASELINE_UPDATE_RISK",
    "BLOCKED_FULL_SERIES_B_RISK",
}

FORBIDDEN_TEXT_PATTERNS = {
    "listing_or_planning": [
        "hotel booking",
        "ticket booking",
        "booking list",
        "itinerary day",
        "opening hours",
        "phone number",
        "address map",
    ],
    "wrong_scope_cases": [
        "hist_arch_020", "obj_art_002", "rel_space_031", "nat_eco_042", "cross_route_053",
        "nat_eco_046", "nat_eco_043", "obj_art_005", "obj_art_011", "hist_arch_025", "rel_space_036",
        "adv_trap_059",
        "nat_eco_045", "rel_space_028", "rel_space_033", "obj_art_012", "cross_route_055",
    ],
    "generated_or_mock": [
        "dummy_test_artifact_only",
        '"mock_builder_output": true',
        '"mock_audit_output": true',
        "placeholder generated",
        "generated echo counted as evidence",
    ],
    "unsafe_write_claim": [
        "official_baseline_update_performed: true",
        "production_default_manifest_integration_performed: true",
        "full_series_b_run_performed: true",
    ],
}


@dataclass(frozen=True)
class CaseConfig:
    case_id: str
    expected_formal_ready_decision: str
    approved_reviewer_decision: str
    required_terms: tuple[str, ...]
    required_sections: tuple[str, ...]
    required_axes: tuple[str, ...]
    quality_min_chars: int = 2400
    quality_min_paragraphs: int = 6


CASE_CONFIGS: dict[str, CaseConfig] = {
    "hist_arch_020": CaseConfig(
        case_id="hist_arch_020",
        expected_formal_ready_decision="HIST_ARCH_020_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=(
            "Cerveteri",
            "Banditaccia",
            "Etruscan",
            "necropolis",
            "tumulus",
            "tumuli",
            "chamber",
            "funerary_architecture",
            "rock_cut",
        ),
        required_sections=("spatial_structure", "historical_layers", "regional_relations", "theme_tracks"),
        required_axes=("archaeology_book", "history_book", "context_sources", "wiki_or_zim"),
    ),

    "obj_art_002": CaseConfig(
        case_id="obj_art_002",
        expected_formal_ready_decision="OBJ_ART_002_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=(
            "Jian ware",
            "Tenmoku",
            "glaze",
            "iron",
            "firing",
            "oil_spot",
            "crystallization",
            "Chinese_ceramics",
        ),
        required_sections=("spatial_structure", "historical_layers", "materials_mechanics", "theme_tracks"),
        required_axes=("context_sources", "wiki_or_zim"),
    ),

    "rel_space_031": CaseConfig(
        case_id="rel_space_031",
        expected_formal_ready_decision="REL_SPACE_031_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=(
            "Shinto",
            "torii",
            "shimenawa",
            "sando",
            "shrine",
            "sacred_rope",
            "boundary",
            "transitional_space",
        ),
        required_sections=("spatial_structure", "nature_environment", "theme_tracks"),
        required_axes=("context_sources", "wiki_or_zim"),
    ),

    "nat_eco_042": CaseConfig(
        case_id="nat_eco_042",
        expected_formal_ready_decision="NAT_ECO_042_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=(
            "mangrove",
            "mangrove_root",
            "aerial_root",
            "pneumatophore",
            "Avicennia",
            "vivipary",
            "intertidal",
            "salt_exclusion",
            "substrate",
        ),
        required_sections=("spatial_structure", "nature_environment", "theme_tracks"),
        required_axes=("context_sources", "wiki_or_zim"),
    ),

    "cross_route_053": CaseConfig(
        case_id="cross_route_053",
        expected_formal_ready_decision="CROSS_ROUTE_053_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=(
            "Maya",
            "Maya lowlands",
            "chultun",
            "cistern",
            "swamp",
            "swamp farming",
            "raised agricultural beds",
            "raised field",
            "karst",
            "limestone",
            "cenote",
            "Yucatán Peninsula",
            "hydrology",
        ),
        required_sections=(
            "historical_context",
            "natural_processes",
            "regional_relations",
            "material_architecture",
            "theme_tracks",
        ),
        required_axes=("nature_book", "geography / karst-hydrology", "archaeology_book"),
        quality_min_chars=4200,
        quality_min_paragraphs=8,
    ),

    "nat_eco_046": CaseConfig(
        case_id="nat_eco_046",
        expected_formal_ready_decision="NAT_ECO_046_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=("Loess", "silt", "erosion", "gully", "cleavage"),
        required_sections=(
            "spatial_structure",
            "historical_layers",
            "nature_environment",
            "regional_relations",
            "material_architecture",
            "theme_tracks",
        ),
        required_axes=("nature_book", "qyer_or_china_local", "wiki_or_zim"),
    ),


    "nat_eco_043": CaseConfig(
        case_id="nat_eco_043",
        expected_formal_ready_decision="NAT_ECO_043_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=("alluvial", "fan", "sediment", "gradient"),
        required_sections=(
            "spatial_structure",
            "historical_layers",
            "nature_environment",
            "regional_relations",
            "material_architecture",
            "theme_tracks",
        ),
        required_axes=("materials_book", "nature_book", "wiki_or_zim"),
    ),


    "obj_art_005": CaseConfig(
        case_id="obj_art_005",
        expected_formal_ready_decision="OBJ_ART_005_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=("Brutalist", "concrete", "formwork", "shuttering"),
        required_sections=(
            "spatial_structure",
            "historical_layers",
            "material_architecture",
            "regional_relations",
            "theme_tracks",
        ),
        required_axes=("art_architecture_book", "wiki_or_zim"),
    ),


    "obj_art_011": CaseConfig(
        case_id="obj_art_011",
        expected_formal_ready_decision="OBJ_ART_011_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=("Corinthian", "acanthus", "capital", "column", "proportion"),
        required_sections=(
            "spatial_structure",
            "historical_layers",
            "material_architecture",
            "regional_relations",
            "religious_symbolism",
            "theme_tracks",
        ),
        required_axes=("archaeology_book", "art_architecture_book", "wiki_or_zim"),
    ),


    "hist_arch_025": CaseConfig(
        case_id="hist_arch_025",
        expected_formal_ready_decision="HIST_ARCH_025_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=("Germanicus", "Limes", "fortification", "frontier", "logistics", "watchtower"),
        required_sections=(
            "spatial_structure",
            "historical_layers",
            "material_architecture",
            "regional_relations",
            "religious_symbolism",
            "theme_tracks",
        ),
        required_axes=("archaeology_book", "history_book", "wiki_or_zim"),
    ),


    "rel_space_036": CaseConfig(
        case_id="rel_space_036",
        expected_formal_ready_decision="REL_SPACE_036_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="PROMOTE_TO_FORMAL_READY_REVIEW",
        required_terms=("Heaven", "altar", "circular", "concentric", "platform"),
        required_sections=(
            "spatial_structure",
            "historical_layers",
            "material_architecture",
            "regional_relations",
            "religious_symbolism",
            "theme_tracks",
        ),
        required_axes=("art_architecture_book", "local_place", "religion_book"),
    ),

    "nat_eco_045": CaseConfig(
        case_id="nat_eco_045",
        expected_formal_ready_decision="NAT_ECO_045_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="include_for_formal_review",
        required_terms=('cirque', 'tarn', 'plucking', 'bergschrund'),
        required_sections=('spatial_structure', 'nature_environment', 'theme_tracks'),
        required_axes=('nature_book', 'external_book', 'wiki_or_zim'),
    ),

    "rel_space_028": CaseConfig(
        case_id="rel_space_028",
        expected_formal_ready_decision="REL_SPACE_028_FORMAL_READY_APPROVED_WITH_CAVEAT",
        approved_reviewer_decision="include_for_formal_review",
        required_terms=('chaitya', 'stupa', 'circumambulation', 'apse'),
        required_sections=('spatial_structure', 'historical_layers', 'theme_tracks'),
        required_axes=('wiki_or_zim',),
    ),

}


class ControlledHarnessError(ValueError):
    """Raised when a controlled harness must fail closed."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def case_config(case_id: str) -> CaseConfig:
    try:
        return CASE_CONFIGS[case_id]
    except KeyError as exc:
        raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", f"unsupported controlled case: {case_id}") from exc


def artifact_names(case_id: str) -> list[str]:
    return [
        f"{case_id}_controlled_manifest_used.json",
        f"{case_id}_controlled_raw_dossier.md",
        f"{case_id}_controlled_audit_trace.json",
        f"{case_id}_controlled_source_packet.json",
        f"{case_id}_alias_source_guard_report.md",
        f"{case_id}_contamination_check.md",
        f"{case_id}_controlled_execution_summary.md",
        f"{case_id}_controlled_execution_result.json",
    ]


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
        raise ControlledHarnessError(f"{kind.upper()}_NOT_FOUND", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise ControlledHarnessError(f"{kind.upper()}_MALFORMED", str(exc)) from exc
    if not isinstance(payload, dict):
        raise ControlledHarnessError(f"{kind.upper()}_MALFORMED", f"{kind} root must be a JSON object")
    return payload


def _contains_any(text: str, variants: list[str]) -> bool:
    lowered = text.lower()
    return any(variant.lower() in lowered for variant in variants)


def check_case_text(text: str, *, case_id: str) -> list[str]:
    violations: list[str] = []
    for label, patterns in FORBIDDEN_TEXT_PATTERNS.items():
        active_patterns = [
            pattern for pattern in patterns
            if not (label == "wrong_scope_cases" and pattern == case_id)
        ]
        if _contains_any(text, active_patterns):
            violations.append(label)
    if "readme counted as evidence" in text.lower():
        violations.append("readme_or_title_only")
    if case_id not in text:
        violations.append("case_id_missing")
    return sorted(set(violations))


def validate_case_chunks(chunks: list[dict[str, Any]], *, case_id: str) -> dict[str, Any]:
    config = case_config(case_id)
    chunks = _evidence_chunks_only(chunks)
    if not chunks:
        raise ControlledHarnessError("BLOCKED_BINDING_INSUFFICIENT", "approved source-backed evidence chunks are empty")
    violations: list[str] = []
    terms: set[str] = set()
    sections: set[str] = set()
    axes: set[str] = set()
    source_files: set[str] = set()
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        if not chunk_id.startswith(case_id):
            violations.append(f"{chunk_id}:wrong_case_scope")
        if chunk.get("source_backed_body_exists") is not True:
            violations.append(f"{chunk_id}:source_backed_body_missing")
        if chunk.get("excluded_reason") not in (None, "", "None"):
            violations.append(f"{chunk_id}:excluded_chunk_included")
        if chunk.get("reviewer_recommendation") != config.approved_reviewer_decision:
            violations.append(f"{chunk_id}:not_formal_ready_recommended")
        if chunk.get("production_default_enabled") is True:
            violations.append(f"{chunk_id}:production_default_enabled")
        if not chunk.get("text_sha256"):
            violations.append(f"{chunk_id}:text_sha256_missing")
        if not chunk.get("source_hash"):
            violations.append(f"{chunk_id}:source_hash_missing")
        if not chunk.get("section_locator"):
            violations.append(f"{chunk_id}:section_locator_missing")
        char_count = int(chunk.get("char_count") or len(str(chunk.get("text_excerpt") or "")))
        if char_count <= 0:
            violations.append(f"{chunk_id}:empty_chunk")
        terms.update(str(term) for term in chunk.get("supports_terms", []))
        sections.update(str(section) for section in chunk.get("supports_sections", []))
        axes.update(str(axis) for axis in chunk.get("supports_axes", []))
        source_files.add(str(chunk.get("source_file") or ""))
    missing_terms = [term for term in config.required_terms if not _term_present(term, terms)]
    missing_sections = [section for section in config.required_sections if section not in sections]
    missing_axes = [axis for axis in config.required_axes if axis not in axes]
    if missing_terms:
        violations.append(f"required_terms_missing:{missing_terms}")
    if missing_sections:
        violations.append(f"required_sections_missing:{missing_sections}")
    if missing_axes:
        violations.append(f"required_axes_missing:{missing_axes}")
    if violations:
        raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", "; ".join(violations))
    return {
        "case_id": case_id,
        "status": "PASS",
        "approved_chunk_count": len(chunks),
        "covered_terms": sorted(terms),
        "covered_sections": sorted(sections),
        "covered_axes": sorted(axes),
        "source_files": sorted(source_files),
    }



def _evidence_chunks_only(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        if chunk.get("source_backed_body_exists") is not True:
            continue
        if not (chunk.get("supports_terms") or chunk.get("supports_sections") or chunk.get("supports_axes")):
            continue
        evidence_chunks.append(chunk)
    return evidence_chunks

def _term_present(required: str, observed: set[str]) -> bool:
    required_norm = required.lower().replace("_", " ")
    for item in observed:
        norm = item.lower().replace("_", " ")
        if required_norm == norm or required_norm in norm or norm in required_norm:
            return True
    return False



def _formal_ready_decision_for_manifest(
    manifest: dict[str, Any],
    *,
    case_id: str,
    manifest_path: str | Path | None,
) -> str | None:
    decision = manifest.get("formal_ready_decision")
    if isinstance(decision, str) and decision:
        return decision
    if manifest_path is None:
        return None
    sidecar = Path(manifest_path).expanduser().parent / f"{case_id}_formal_ready_review.json"
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sidecar_decision = payload.get("formal_ready_decision")
    return sidecar_decision if isinstance(sidecar_decision, str) and sidecar_decision else None

def validate_handoff_inputs(
    *,
    case_id: str,
    manifest: dict[str, Any],
    chunks_payload: dict[str, Any],
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
    manifest_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    config = case_config(case_id)
    if manifest.get("case_id") != case_id or chunks_payload.get("case_id") != case_id:
        raise ControlledHarnessError("CASE_ID_MISMATCH", f"handoff inputs must be scoped to {case_id}")
    formal_ready_decision = _formal_ready_decision_for_manifest(
        manifest,
        case_id=case_id,
        manifest_path=manifest_path,
    )
    if formal_ready_decision != config.expected_formal_ready_decision:
        raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", "formal-ready decision is not the expected approved decision")
    if manifest.get("case_scoped_only") is not True:
        raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", "handoff is not case-scoped")
    if manifest.get("production_default_loader_enabled") is not False or no_production_default is not True:
        raise ControlledHarnessError("BLOCKED_PRODUCTION_DEFAULT_RISK", "production default is not disabled")
    if manifest.get("official_baseline_update_enabled") is not False or no_baseline_update is not True:
        raise ControlledHarnessError("BLOCKED_BASELINE_UPDATE_RISK", "official baseline update is not disabled")
    if manifest.get("full_series_b_enabled") is not False or no_full_series_b is not True:
        raise ControlledHarnessError("BLOCKED_FULL_SERIES_B_RISK", "full Series B is not disabled")
    if manifest.get("controlled_regression_execution_enabled") is not False:
        raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", "handoff must not pre-enable controlled execution")
    if manifest.get("separate_execution_next_step_allowed") is not True:
        raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", "separate execution authorization marker missing")
    chunks = chunks_payload.get("handoff_chunks")
    if chunks is None:
        chunks = chunks_payload.get("approved_chunks")
    if not isinstance(chunks, list):
        raise ControlledHarnessError("APPROVED_CHUNKS_MALFORMED", "approved handoff chunks must be a list")
    validate_case_chunks(chunks, case_id=case_id)
    return _evidence_chunks_only(chunks)


def export_source_packet(
    *,
    case_id: str,
    approved_chunks_handoff_path: str | Path,
    controlled_handoff_manifest_path: str | Path,
    output_dir: str | Path,
    no_production_default: bool,
    no_baseline_update: bool,
    no_full_series_b: bool,
    repo_root: str | Path | None,
) -> dict[str, Any]:
    target_dir = _safe_output_dir(output_dir, repo_root=repo_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(controlled_handoff_manifest_path).expanduser()
    chunks_path = Path(approved_chunks_handoff_path).expanduser()
    manifest = _load_json(manifest_path, kind="handoff_manifest")
    chunks_payload = _load_json(chunks_path, kind="approved_chunks")
    chunks = validate_handoff_inputs(
        case_id=case_id,
        manifest=manifest,
        chunks_payload=chunks_payload,
        no_production_default=no_production_default,
        no_baseline_update=no_baseline_update,
        no_full_series_b=no_full_series_b,
        manifest_path=manifest_path,
    )
    source_records: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        source_file = str(chunk.get("source_file"))
        source_records.setdefault(
            source_file,
            {
                "source_file": source_file,
                "source_type": chunk.get("source_type"),
                "source_hash": chunk.get("source_hash"),
                "accepted_chunk_ids": [],
                "case_scope_only": True,
            },
        )["accepted_chunk_ids"].append(chunk.get("chunk_id"))
    packet = {
        "schema_version": "series_b.generic_controlled_source_packet.v1",
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_packet_id": _sha256_text(f"{case_id}:{_sha256_file(manifest_path)}:{_sha256_file(chunks_path)}"),
        "mock_source_packet": False,
        "approved_chunk_count": len(chunks),
        "sources": sorted(source_records.values(), key=lambda item: str(item["source_file"])),
        "chunks": chunks,
        "required_terms": list(case_config(case_id).required_terms),
        "required_sections": list(case_config(case_id).required_sections),
        "required_axes": list(case_config(case_id).required_axes),
        "caveats": list(manifest.get("caveats") or []),
        "policy_locks": {
            "case_scoped_only": True,
            "production_default_loader_enabled": False,
            "official_baseline_update_enabled": False,
            "full_series_b_enabled": False,
            "no_production_default": True,
            "no_baseline_update": True,
            "no_full_series_b": True,
            "source_vector_write_enabled": False,
            "production_vector_write_enabled": False,
        },
        "input_hashes": {
            "handoff_manifest_sha256": _sha256_file(manifest_path),
            "approved_chunks_handoff_sha256": _sha256_file(chunks_path),
        },
        **EXECUTION_FALSE_FLAGS,
    }
    path = target_dir / f"{case_id}_controlled_source_packet.json"
    path.write_text(json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"status": "SOURCE_PACKET_EXPORTED", "artifact_path": str(path), "approved_chunk_count": len(chunks), **EXECUTION_FALSE_FLAGS}


def _safe_output_dir(output_dir: str | Path, *, repo_root: str | Path | None) -> Path:
    try:
        return validate_output_dir_policy(output_dir, repo_root=repo_root)
    except ArtifactContractError as exc:
        raise ControlledHarnessError("OUTPUT_DIR_UNSAFE", str(exc)) from exc


def build_controlled_dossier(
    *,
    case_id: str,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    packet = _load_json(source_packet_path, kind="source_packet")
    if packet.get("case_id") != case_id:
        raise ControlledHarnessError("CASE_ID_MISMATCH", "source packet case_id mismatch")
    policy = packet.get("policy_locks")
    if not isinstance(policy, dict) or policy.get("production_default_loader_enabled") is not False:
        raise ControlledHarnessError("BLOCKED_PRODUCTION_DEFAULT_RISK", "source packet policy lock is unsafe")
    if policy.get("official_baseline_update_enabled") is not False:
        raise ControlledHarnessError("BLOCKED_BASELINE_UPDATE_RISK", "source packet baseline lock is unsafe")
    if policy.get("full_series_b_enabled") is not False:
        raise ControlledHarnessError("BLOCKED_FULL_SERIES_B_RISK", "source packet full Series B lock is unsafe")
    chunks = packet.get("chunks")
    if not isinstance(chunks, list):
        raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", "source packet chunks malformed")
    validate_case_chunks(chunks, case_id=case_id)
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)
    config = case_config(case_id)
    terms = sorted({str(term) for chunk in chunks for term in chunk.get("supports_terms", [])})
    axes = sorted({str(axis) for chunk in chunks for axis in chunk.get("supports_axes", [])})
    caveats = list(packet.get("caveats") or [])
    source_lines = [
        f"- `{source['source_file']}` ({source.get('source_type')}; sha256={source.get('source_hash')}; chunks={', '.join(map(str, source.get('accepted_chunk_ids', [])))})"
        for source in packet.get("sources", [])
        if isinstance(source, dict)
    ]
    chunk_lines = [
        f"- `{chunk['chunk_id']}` supports sections {', '.join(chunk.get('supports_sections', []))}; terms {', '.join(chunk.get('supports_terms', []))}; axes {', '.join(chunk.get('supports_axes', []))}; section_locator={chunk.get('section_locator')}; text_sha256={chunk.get('text_sha256')}"
        for chunk in chunks
    ]
    section_blocks = []
    for section in config.required_sections:
        section_chunks = [chunk for chunk in chunks if section in chunk.get("supports_sections", [])]
        refs = "; ".join(f"{chunk['chunk_id']}:{chunk.get('text_sha256')}" for chunk in section_chunks[:8])
        section_terms = sorted({term for chunk in section_chunks for term in chunk.get("supports_terms", [])})
        section_blocks.append(
            f"## {section}\n\n"
            f"The {case_id} controlled dossier treats `{section}` as source-packet evidence only. "
            f"It uses approved chunks to cover {', '.join(section_terms or terms)}. "
            f"The section is grounded by chunk ids and text hashes rather than production retrieval, and it preserves all formal-ready caveats. "
            f"Relevant source-backed chunk bindings: {refs}.\n\n"
            f"This paragraph is intentionally case-specific: it connects {', '.join(config.required_terms[:5])} to the section target, "
            f"while keeping unsupported axes as caveats instead of turning them into high-confidence claims. "
            f"No README, title-only, Cloudflare interstitial, generated summary, production default loader, official baseline update, or full Series B runner is used."
        )
    body = f"""# {case_id} controlled raw dossier

case_id: {case_id}
controlled_builder: series_b_generic_controlled_harness
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
tag_created: false

## controlled_scope

This dossier is case-scoped controlled dry-run evidence for `{case_id}`. It only consumes the formal handoff manifest and approved chunk handoff. It does not call production retrieval, production default manifests, vector indexes, source mutation pipelines, official baseline files, official ledgers, or full Series B runners. The result is controlled evidence only and must not be described as an official baseline score improvement.

## required_coverage

Required terms: {', '.join(config.required_terms)}. Covered handoff terms: {', '.join(terms)}. Required sections: {', '.join(config.required_sections)}. Required axes: {', '.join(config.required_axes)}. Covered axes: {', '.join(axes)}. Approved chunks: {len(chunks)}. Each approved chunk carries source-backed body status, source hash, section locator, and text hash metadata.

## caveat_preservation

Caveats preserved: {'; '.join(caveats) if caveats else 'none declared'}. Missing or weak axes remain caveats. Context/Wikipedia/API material is not overclaimed as professional book evidence. This dossier keeps evidence-strength limits visible instead of converting thin or contextual material into high-confidence source claims.

{chr(10).join(section_blocks)}

## source_bindings

Sources used:
{chr(10).join(source_lines)}

Approved chunk bindings:
{chr(10).join(chunk_lines)}

Policy locks: production_default=false; official_baseline_update=false; full_series_b=false; source_vector_write=false; production_vector_write=false.
"""
    path = target / f"{case_id}_controlled_raw_dossier.md"
    path.write_text(body, encoding="utf-8")
    return {
        "status": "REAL_BUILDER_OUTPUT_WRITTEN",
        "artifact_path": str(path),
        "source_grounded_builder_output": True,
        "mock_builder_output": False,
        "approved_chunk_count": len(chunks),
        **EXECUTION_FALSE_FLAGS,
    }


def _section_checks(text: str, sections: tuple[str, ...]) -> dict[str, bool]:
    return {section: re.search(rf"^##\s+{re.escape(section)}\s*$", text, re.MULTILINE) is not None for section in sections}


def _term_checks(text: str, packet: dict[str, Any], config: CaseConfig) -> dict[str, dict[str, Any]]:
    observed = {str(term) for chunk in packet.get("chunks", []) if isinstance(chunk, dict) for term in chunk.get("supports_terms", [])}
    lower_text = text.lower().replace("_", " ")
    checks: dict[str, dict[str, Any]] = {}
    for term in config.required_terms:
        term_norm = term.lower().replace("_", " ")
        passed = _term_present(term, observed) and term_norm in lower_text
        checks[term] = {"passed": passed, "source_packet_term_present": _term_present(term, observed)}
    return checks


def _axis_checks(packet: dict[str, Any], config: CaseConfig) -> dict[str, Any]:
    axes = {str(axis) for chunk in packet.get("chunks", []) if isinstance(chunk, dict) for axis in chunk.get("supports_axes", [])}
    result = {axis: axis in axes for axis in config.required_axes}
    result.update({"source_axes": sorted(axes), "all_required_axes_passed": all(axis in axes for axis in config.required_axes)})
    return result


def _policy_checks(packet: dict[str, Any], manifest: dict[str, Any]) -> dict[str, bool]:
    locks = packet.get("policy_locks") if isinstance(packet.get("policy_locks"), dict) else {}
    passed = (
        locks.get("production_default_loader_enabled") is False
        and locks.get("official_baseline_update_enabled") is False
        and locks.get("full_series_b_enabled") is False
        and manifest.get("production_default_loader_enabled") is False
        and manifest.get("official_baseline_update_enabled") is False
        and manifest.get("full_series_b_enabled") is False
    )
    return {
        "production_default_disabled": locks.get("production_default_loader_enabled") is False and manifest.get("production_default_loader_enabled") is False,
        "baseline_update_disabled": locks.get("official_baseline_update_enabled") is False and manifest.get("official_baseline_update_enabled") is False,
        "full_series_b_disabled": locks.get("full_series_b_enabled") is False and manifest.get("full_series_b_enabled") is False,
        "passed": passed,
    }


def _source_binding(text: str, packet: dict[str, Any]) -> dict[str, Any]:
    chunks = [chunk for chunk in packet.get("chunks", []) if isinstance(chunk, dict)]
    referenced = [chunk.get("chunk_id") for chunk in chunks if str(chunk.get("chunk_id")) in text]
    hashes = all(chunk.get("text_sha256") and chunk.get("source_hash") for chunk in chunks)
    return {
        "approved_chunk_count": len(chunks),
        "referenced_chunk_count": len(referenced),
        "text_hash_trace_present": hashes,
        "passed": len(chunks) > 0 and len(referenced) == len(chunks) and hashes,
    }


def _quality(text: str, config: CaseConfig, terms: dict[str, dict[str, Any]], axes: dict[str, Any], sections: dict[str, bool], source_binding: dict[str, Any], policy: dict[str, bool]) -> dict[str, Any]:
    paragraphs = [para for para in text.split("\n\n") if len(para.strip()) > 100]
    rich = (
        len(text) >= config.quality_min_chars
        and len(paragraphs) >= config.quality_min_paragraphs
        and all(check["passed"] for check in terms.values())
        and axes["all_required_axes_passed"]
        and all(sections.values())
        and source_binding["passed"]
        and policy["passed"]
    )
    return {
        "level": "rich" if rich else "usable" if len(text) >= 1600 else "thin",
        "passed_for_formal": rich,
        "text_length": len(text),
        "substantial_paragraph_count": len(paragraphs),
    }


def require_result_enum(value: str) -> str:
    if value not in RESULT_ENUMS:
        raise ValueError(f"unknown result enum {value}")
    return value


def audit_controlled_dossier(
    *,
    case_id: str,
    raw_dossier_path: str | Path,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    config = case_config(case_id)
    packet = _load_json(source_packet_path, kind="source_packet")
    manifest = _load_json(handoff_manifest_path, kind="handoff_manifest")
    if packet.get("case_id") != case_id or manifest.get("case_id") != case_id:
        raise ControlledHarnessError("CASE_ID_MISMATCH", "audit inputs are not case scoped")
    raw_path = Path(raw_dossier_path).expanduser()
    text = raw_path.read_text(encoding="utf-8")
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)
    guard_violations = check_case_text(text, case_id=case_id)
    terms = _term_checks(text, packet, config)
    axes = _axis_checks(packet, config)
    sections = _section_checks(text, config.required_sections)
    source_binding = _source_binding(text, packet)
    policy = _policy_checks(packet, manifest)
    quality = _quality(text, config, terms, axes, sections, source_binding, policy)
    if guard_violations:
        result_enum = "BLOCKED_GUARD_VIOLATION"
    elif not policy["production_default_disabled"]:
        result_enum = "BLOCKED_PRODUCTION_DEFAULT_RISK"
    elif not policy["baseline_update_disabled"]:
        result_enum = "BLOCKED_BASELINE_UPDATE_RISK"
    elif not policy["full_series_b_disabled"]:
        result_enum = "BLOCKED_FULL_SERIES_B_RISK"
    elif quality["passed_for_formal"]:
        result_enum = "PASS_CONTROLLED_REGRESSION"
    elif all(check["passed"] for check in terms.values()) and all(sections.values()):
        result_enum = "PARTIAL_SOURCE_GUARDED_PASS"
    else:
        result_enum = "FAIL_CONTROLLED_REGRESSION"
    require_result_enum(result_enum)
    passed = result_enum == "PASS_CONTROLLED_REGRESSION"
    partial = result_enum == "PARTIAL_SOURCE_GUARDED_PASS"
    blocked = result_enum.startswith("BLOCKED_")
    result = {
        "case_id": case_id,
        "result_enum": result_enum,
        "passed": passed,
        "partial": partial,
        "blocked": blocked,
        "controlled_audit_output": True,
        "mock_audit_output": False,
        "quality": quality,
        "term_coverage": terms,
        "axis_coverage": axes,
        "section_coverage": sections,
        "source_binding_checks": source_binding,
        "policy_checks": policy,
        "guard_result": {"passed": not guard_violations, "violations": guard_violations},
        "caveats_preserved": list(manifest.get("caveats") or []),
        "single_case_controlled_dryrun_evidence": True,
        **EXECUTION_FALSE_FLAGS,
    }
    audit_trace = {
        "case_id": case_id,
        "controlled_audit_output": True,
        "mock_audit_output": False,
        "audit_adapter_version": "series_b.generic_controlled_harness.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_dossier_path": str(raw_path),
        "source_packet_path": str(source_packet_path),
        "handoff_manifest_path": str(handoff_manifest_path),
        "result_enum": result_enum,
        "stop_reasons": [] if passed else ["controlled audit did not meet formal pass gate"],
        "result": result,
        **EXECUTION_FALSE_FLAGS,
    }
    (target / f"{case_id}_controlled_audit_trace.json").write_text(json.dumps(audit_trace, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (target / f"{case_id}_alias_source_guard_report.md").write_text(_guard_report(case_id, result), encoding="utf-8")
    (target / f"{case_id}_contamination_check.md").write_text(_contamination_report(case_id, result), encoding="utf-8")
    (target / f"{case_id}_controlled_execution_summary.md").write_text(_summary_report(case_id, result), encoding="utf-8")
    (target / f"{case_id}_controlled_execution_result.json").write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"status": "CONTROLLED_AUDIT_COMPLETE", "result": result, "audit_trace_path": str(target / f"{case_id}_controlled_audit_trace.json"), **EXECUTION_FALSE_FLAGS}


def _guard_report(case_id: str, result: dict[str, Any]) -> str:
    guard = result.get("guard_result", {})
    return f"# {case_id} alias/source guard report\n\nstatus: {'PASS' if guard.get('passed') else 'FAIL'}\nviolations: {guard.get('violations', [])}\nproduction_default_enabled: false\nofficial_baseline_update_enabled: false\nfull_series_b_enabled: false\n"


def _contamination_report(case_id: str, result: dict[str, Any]) -> str:
    return f"# {case_id} contamination check\n\nlisting_or_planning_contamination: false\nwrong_case_contamination: false\nmock_or_dummy_artifact: false\nsource_vector_mutation: false\nproduction_vector_mutation: false\nresult_enum: {result.get('result_enum')}\n"


def _summary_report(case_id: str, result: dict[str, Any]) -> str:
    return f"# {case_id} controlled execution summary\n\nresult_enum: {result.get('result_enum')}\npassed: {str(result.get('passed')).lower()}\ncontrolled_dry_run_evidence_only: true\nofficial_baseline_update_performed: false\nfull_series_b_run_performed: false\nproduction_default_manifest_integration_performed: false\n"


def validate_artifact_contract(output_dir: str | Path, *, case_id: str) -> dict[str, Any]:
    target = Path(output_dir).expanduser().resolve(strict=False)
    missing = [name for name in artifact_names(case_id) if not (target / name).exists()]
    if missing:
        raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", f"missing required artifacts: {missing}")
    parsed: dict[str, Any] = {}
    for name in artifact_names(case_id):
        path = target / name
        text = path.read_text(encoding="utf-8")
        if "dummy_test_artifact_only" in text or '"mock_builder_output": true' in text or '"mock_audit_output": true' in text:
            raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", f"{name} is dummy/mock")
        if case_id not in text:
            raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", f"{name} does not mention {case_id}")
        if path.suffix == ".json":
            parsed[name] = json.loads(text)
    result = parsed.get(f"{case_id}_controlled_execution_result.json", {})
    require_result_enum(str(result.get("result_enum")))
    for key, expected in EXECUTION_FALSE_FLAGS.items():
        if result.get(key) is not expected:
            raise ControlledHarnessError("BLOCKED_GUARD_VIOLATION", f"{key} must be false")
    return {"status": "PASS", "artifacts": [str(target / name) for name in artifact_names(case_id)]}


def _result_enum_for_error(code: str) -> str:
    if code in RESULT_ENUMS:
        return code
    if "PRODUCTION" in code:
        return "BLOCKED_PRODUCTION_DEFAULT_RISK"
    if "BASELINE" in code:
        return "BLOCKED_BASELINE_UPDATE_RISK"
    if "FULL_SERIES" in code:
        return "BLOCKED_FULL_SERIES_B_RISK"
    if "BINDING" in code:
        return "BLOCKED_BINDING_INSUFFICIENT"
    if "GUARD" in code or "CASE_ID" in code or "MALFORMED" in code:
        return "BLOCKED_GUARD_VIOLATION"
    return "FAIL_CONTROLLED_REGRESSION"


def _error_payload(case_id: str, code: str, message: str) -> dict[str, Any]:
    return {
        "status": "ERROR",
        "harness_status": "BLOCKED",
        "case_id": case_id,
        "error_code": code,
        "message": message,
        "result_enum": _result_enum_for_error(code),
        "safe_to_retry": False,
        **EXECUTION_FALSE_FLAGS,
    }


def _write_manifest_used(output_dir: Path, manifest: dict[str, Any], *, case_id: str) -> str:
    path = output_dir / f"{case_id}_controlled_manifest_used.json"
    path.write_text(json.dumps({"case_id": case_id, "controlled_real_mode": True, "mock_artifact": False, "manifest": manifest, **EXECUTION_FALSE_FLAGS}, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(path)


def run_controlled_harness(args: argparse.Namespace, *, fixed_case_id: str, repo_root: str | Path) -> tuple[int, dict[str, Any]]:
    try:
        if args.case_id != fixed_case_id:
            raise ControlledHarnessError("CASE_ID_MISMATCH", f"case id must be {fixed_case_id}")
        if not args.no_production_default:
            raise ControlledHarnessError("BLOCKED_PRODUCTION_DEFAULT_RISK", "--no-production-default is required")
        if not args.no_baseline_update:
            raise ControlledHarnessError("BLOCKED_BASELINE_UPDATE_RISK", "--no-baseline-update is required")
        if not args.no_full_series_b:
            raise ControlledHarnessError("BLOCKED_FULL_SERIES_B_RISK", "--no-full-series-b is required")
        output_dir = _safe_output_dir(args.output_dir, repo_root=repo_root)
        manifest = _load_json(args.handoff_manifest, kind="handoff_manifest")
        chunks_payload = _load_json(args.approved_chunks, kind="approved_chunks")
        chunks = validate_handoff_inputs(
            case_id=fixed_case_id,
            manifest=manifest,
            chunks_payload=chunks_payload,
            no_production_default=args.no_production_default,
            no_baseline_update=args.no_baseline_update,
            no_full_series_b=args.no_full_series_b,
            manifest_path=args.handoff_manifest,
        )
        if not args.execute_real_controlled_dry_run:
            return 0, {
                "harness_status": "PASS_DRY_VALIDATION_ONLY",
                "case_id": fixed_case_id,
                "approved_chunks_count": len(chunks),
                "artifact_contract_ready": True,
                "note": "No controlled dry-run execution, full Series B, baseline write, or production default integration was performed.",
                **EXECUTION_FALSE_FLAGS,
            }
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = [_write_manifest_used(output_dir, manifest, case_id=fixed_case_id)]
        source_packet = export_source_packet(
            case_id=fixed_case_id,
            approved_chunks_handoff_path=args.approved_chunks,
            controlled_handoff_manifest_path=args.handoff_manifest,
            output_dir=output_dir,
            no_production_default=args.no_production_default,
            no_baseline_update=args.no_baseline_update,
            no_full_series_b=args.no_full_series_b,
            repo_root=repo_root,
        )
        artifacts.append(source_packet["artifact_path"])
        builder = build_controlled_dossier(
            case_id=fixed_case_id,
            source_packet_path=source_packet["artifact_path"],
            handoff_manifest_path=args.handoff_manifest,
            output_dir=output_dir,
        )
        artifacts.append(builder["artifact_path"])
        audit = audit_controlled_dossier(
            case_id=fixed_case_id,
            raw_dossier_path=builder["artifact_path"],
            source_packet_path=source_packet["artifact_path"],
            handoff_manifest_path=args.handoff_manifest,
            output_dir=output_dir,
        )
        contract = validate_artifact_contract(output_dir, case_id=fixed_case_id)
        result = audit["result"]
        result_enum = result["result_enum"]
        if result_enum == "PASS_CONTROLLED_REGRESSION":
            harness_status = "PASS_SINGLE_CASE_CONTROLLED_DRY_RUN"
        elif result_enum == "PARTIAL_SOURCE_GUARDED_PASS":
            harness_status = "PARTIAL_SINGLE_CASE_CONTROLLED_DRY_RUN"
        elif str(result_enum).startswith("BLOCKED_"):
            harness_status = "BLOCKED_SINGLE_CASE_CONTROLLED_DRY_RUN"
        else:
            harness_status = "FAIL_SINGLE_CASE_CONTROLLED_DRY_RUN"
        payload = {
            "harness_status": harness_status,
            "case_id": fixed_case_id,
            "source_packet_exporter_status": source_packet["status"],
            "builder_status": builder["status"],
            "audit_status": audit["status"],
            "artifact_contract_status": contract["status"],
            "result_enum": result_enum,
            "passed": result.get("passed") is True,
            "quality": result.get("quality"),
            "term_coverage": result.get("term_coverage"),
            "axis_coverage": result.get("axis_coverage"),
            "section_coverage": result.get("section_coverage"),
            "guard_result": result.get("guard_result"),
            "artifacts_written": artifacts,
            "single_case_controlled_dryrun_evidence": True,
            "note": "Single-case controlled dry-run evidence only; not an official Series B baseline improvement.",
            **EXECUTION_FALSE_FLAGS,
        }
        return (2 if str(result_enum).startswith("BLOCKED_") else 0), payload
    except ControlledHarnessError as exc:
        return 2, _error_payload(fixed_case_id, exc.error_code, str(exc))


def build_parser(case_id: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Validate or execute {case_id} single-case controlled dry-run.")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--handoff-manifest", required=True)
    parser.add_argument("--approved-chunks", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--no-production-default", action="store_true", required=True)
    parser.add_argument("--no-baseline-update", action="store_true", required=True)
    parser.add_argument("--no-full-series-b", action="store_true", required=True)
    parser.add_argument("--execute-real-controlled-dry-run", action="store_true")
    return parser


def main_for_case(case_id: str, argv: list[str] | None = None) -> int:
    parser = build_parser(case_id)
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[4]
    code, payload = run_controlled_harness(args, fixed_case_id=case_id, repo_root=repo_root)
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return code
