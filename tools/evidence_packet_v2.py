"""Deterministic Evidence Packet v2 contract validation and rendering.

This module intentionally does not acquire evidence, call an LLM, access the
network, or integrate with the production Research/Decision runtime. It only
validates and renders structured Evidence Packet v2 JSON.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REQUIRED_SECTIONS: tuple[str, ...] = (
    "metadata",
    "user_question_obligations",
    "claim_table_v2",
    "source_registry",
    "citation_claim_pairs",
    "verification_matrix",
    "contradiction_table",
    "evidence_boundary",
    "confidence_policy",
    "final_answer_traceability",
)

METADATA_REQUIRED_FIELDS: tuple[str, ...] = (
    "packet_id",
    "case_id",
    "task_mode",
    "generated_at",
    "as_of_date",
    "evidence_mode",
    "network_used",
    "llm_used",
    "source_acquisition_used",
    "full_text_acquisition_used",
)

OBLIGATION_REQUIRED_FIELDS: tuple[str, ...] = (
    "obligation_id",
    "obligation_text",
    "obligation_type",
    "coverage_status",
    "linked_claim_ids",
)

CLAIM_REQUIRED_FIELDS: tuple[str, ...] = (
    "claim_id",
    "claim_text",
    "claim_type",
    "importance",
    "decision_relevance",
    "user_obligation_ids",
    "source_ids",
    "source_basis",
    "support_level",
    "contradiction_status",
    "full_text_verified",
    "retrieval_status",
    "applicability",
    "confidence_effect",
    "final_allowed_wording",
    "verification_notes",
)

SOURCE_REQUIRED_FIELDS: tuple[str, ...] = (
    "source_id",
    "title",
    "url_or_local_ref",
    "source_type",
    "publisher_or_author",
    "publication_date",
    "access_date",
    "as_of_relevance",
    "authority_tier",
    "independence",
    "potential_bias",
    "retrieval_status",
    "full_text_available",
    "full_text_accessed",
    "full_text_hash_or_excerpt_ref",
    "source_limitations",
)

CITATION_PAIR_REQUIRED_FIELDS: tuple[str, ...] = (
    "pair_id",
    "claim_id",
    "source_id",
    "cited_span_or_location",
    "source_statement_summary",
    "match_type",
    "consistency_status",
    "numeric_exactness",
    "date_exactness",
    "quote_exactness",
    "mismatch_notes",
)

VERIFICATION_REQUIRED_FIELDS: tuple[str, ...] = (
    "claim_id",
    "verified_by_sources",
    "contradicted_by_sources",
    "unresolved_sources",
    "support_level_final",
    "required_final_wording",
    "confidence_delta",
    "unresolved_reason",
)

CONTRADICTION_REQUIRED_FIELDS: tuple[str, ...] = (
    "contradiction_id",
    "claim_id",
    "source_ids",
    "contradiction_type",
    "severity",
    "resolution",
    "final_wording_constraint",
)

EVIDENCE_BOUNDARY_REQUIRED_FIELDS: tuple[str, ...] = (
    "what_is_verified",
    "what_is_plausible",
    "what_is_speculative",
    "what_is_unverified",
    "what_requires_full_text",
    "what_requires_domain_expert",
    "what_cannot_be_claimed",
)

CONFIDENCE_POLICY_REQUIRED_FIELDS: tuple[str, ...] = (
    "allowed_confidence_upgrades",
    "forced_confidence_downgrades",
    "no_upgrade_conditions",
    "source_need_conditions",
    "final_wording_constraints",
)

FINAL_TRACE_REQUIRED_FIELDS: tuple[str, ...] = (
    "final_section",
    "claim_ids_used",
    "source_ids_used",
    "unsupported_claims_removed",
    "caveats_required",
    "confidence_language_required",
)

EVIDENCE_MODES: tuple[str, ...] = ("simulated", "doc_only", "web_search", "full_text", "mixed")
CLAIM_TYPES: tuple[str, ...] = (
    "descriptive_fact",
    "statistic",
    "comparison",
    "causal_claim",
    "prediction",
    "recommendation",
    "legal_regulatory",
    "medical_health",
    "financial_risk",
    "technical_capability",
    "market_claim",
    "user_context_claim",
    "interpretation",
    "speculation",
)
SUPPORT_LEVELS: tuple[str, ...] = (
    "verified",
    "strongly_supported",
    "supported",
    "plausible",
    "weakly_supported",
    "speculative",
    "unverified",
    "disputed",
    "contradicted",
    "fabrication_risk",
)
RETRIEVAL_STATUSES: tuple[str, ...] = (
    "not_searched",
    "searched_no_result",
    "source_found",
    "source_accessible",
    "full_text_accessed",
    "paywalled_or_unavailable",
    "source_broken",
    "doc_only_matched",
    "simulated_fixture_only",
)
CONFIDENCE_EFFECTS: tuple[str, ...] = (
    "upgrade_allowed",
    "keep",
    "downgrade",
    "force_source_need",
    "remove_or_rewrite",
    "expert_review_required",
)
OBLIGATION_TYPES: tuple[str, ...] = (
    "decision_required",
    "comparison_required",
    "risk_required",
    "constraint_required",
    "user_context_required",
    "source_required",
    "time_sensitive_required",
    "high_impact_required",
    "format_required",
)
COVERAGE_STATUSES: tuple[str, ...] = (
    "covered_verified",
    "covered_with_limitations",
    "covered_unverified",
    "not_covered_source_needed",
    "not_applicable",
)
MATCH_TYPES: tuple[str, ...] = (
    "direct_statement",
    "numeric_support",
    "date_support",
    "quote_support",
    "definition_support",
    "method_support",
    "context_support",
    "indirect_support",
    "background_only",
    "contradiction",
    "not_found",
)
CONSISTENCY_STATUSES: tuple[str, ...] = (
    "consistent",
    "partially_consistent",
    "unsupported",
    "contradicted",
    "source_not_accessible",
    "not_checked",
)
EXACTNESS_VALUES: tuple[str, ...] = ("exact", "approximate", "not_applicable", "mismatch", "not_checked")
CONTRADICTION_STATUSES: tuple[str, ...] = ("none", "resolved", "unresolved", "contradicted", "disputed")
CONTRADICTION_TYPES: tuple[str, ...] = (
    "direct_conflict",
    "numeric_conflict",
    "date_conflict",
    "scope_conflict",
    "population_conflict",
    "methodology_conflict",
    "authority_conflict",
    "recency_conflict",
    "interpretation_conflict",
)
CONTRADICTION_SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "blocking")
CONTRADICTION_RESOLUTIONS: tuple[str, ...] = (
    "resolved_by_primary_source",
    "resolved_by_recency",
    "resolved_by_scope",
    "resolved_as_uncertain",
    "unresolved_source_needed",
    "unresolved_expert_needed",
    "claim_removed",
)
CONFIDENCE_DELTAS: tuple[str, ...] = ("upgrade", "none", "downgrade", "force_source_need", "remove", "expert_review")

HIGH_RISK_CLAIM_TYPES: set[str] = {
    "legal_regulatory",
    "medical_health",
    "financial_risk",
    "statistic",
    "causal_claim",
    "prediction",
}
WEAK_SUPPORT_FOR_UPGRADE: set[str] = {
    "plausible",
    "weakly_supported",
    "speculative",
    "unverified",
    "disputed",
    "contradicted",
    "fabrication_risk",
}
UNSUPPORTED_SUPPORT_LEVELS: set[str] = {"unverified", "disputed", "contradicted", "fabrication_risk"}
SOURCE_NEED_EFFECTS: set[str] = {"downgrade", "force_source_need", "remove_or_rewrite", "expert_review_required"}
CONTRADICTION_BAD_STATUSES: set[str] = {"unresolved", "contradicted"}

UNCERTAINTY_WORDS: tuple[str, ...] = (
    "uncertain",
    "not verified",
    "unverified",
    "source_need",
    "source need",
    "remove",
    "rewrite",
    "cannot claim",
    "do not claim",
    "insufficient",
    "disputed",
    "contradict",
    "fabrication",
    "speculative",
    "plausible",
    "may",
    "could",
    "requires",
    "expert",
    "caveat",
    "limited",
)
STRONG_ASSERTION_PATTERNS: tuple[str, ...] = (
    "verified fact",
    "strong assertion",
    "can assert",
    "must use",
    "definitely",
    "proven",
    "guaranteed",
    "without caveat",
    "recommend as fact",
)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]
    source_need_required: bool
    confidence_upgrade_blocked: bool
    high_risk_claims: list[str]
    unverified_claims: list[str]
    contradicted_claims: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_packet_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Evidence Packet v2 JSON must be an object.")
    return data


def validate_packet(packet: dict[str, Any]) -> ValidationResult:
    if not isinstance(packet, dict):
        return ValidationResult(
            ok=False,
            errors=["packet:not_object"],
            warnings=[],
            source_need_required=False,
            confidence_upgrade_blocked=False,
            high_risk_claims=[],
            unverified_claims=[],
            contradicted_claims=[],
        )

    errors: list[str] = []
    warnings: list[str] = []
    source_need_required = False
    confidence_upgrade_blocked = False
    high_risk_claims: list[str] = []
    unverified_claims: list[str] = []
    contradicted_claims: list[str] = []

    for section in REQUIRED_SECTIONS:
        if section not in packet:
            errors.append(f"missing_section:{section}")

    if errors:
        return ValidationResult(
            ok=False,
            errors=errors,
            warnings=warnings,
            source_need_required=False,
            confidence_upgrade_blocked=False,
            high_risk_claims=[],
            unverified_claims=[],
            contradicted_claims=[],
        )

    metadata = packet.get("metadata")
    obligations = packet.get("user_question_obligations")
    claims = packet.get("claim_table_v2")
    sources = packet.get("source_registry")
    pairs = packet.get("citation_claim_pairs")
    matrix = packet.get("verification_matrix")
    contradictions = packet.get("contradiction_table")
    evidence_boundary = packet.get("evidence_boundary")
    confidence_policy = packet.get("confidence_policy")
    final_trace = packet.get("final_answer_traceability")

    if not isinstance(metadata, dict):
        errors.append("metadata:not_object")
        metadata = {}
    if not isinstance(evidence_boundary, dict):
        errors.append("evidence_boundary:not_object")
        evidence_boundary = {}
    if not isinstance(confidence_policy, dict):
        errors.append("confidence_policy:not_object")
        confidence_policy = {}

    obligations = _require_list("user_question_obligations", obligations, errors, require_nonempty=False)
    claims = _require_list("claim_table_v2", claims, errors, require_nonempty=True)
    sources = _require_list("source_registry", sources, errors, require_nonempty=True)
    pairs = _require_list("citation_claim_pairs", pairs, errors, require_nonempty=True)
    matrix = _require_list("verification_matrix", matrix, errors, require_nonempty=True)
    contradictions = _require_list("contradiction_table", contradictions, errors, require_nonempty=False)
    final_trace = _require_list("final_answer_traceability", final_trace, errors, require_nonempty=True)

    _check_required_fields("metadata", metadata, METADATA_REQUIRED_FIELDS, errors)
    _check_required_fields("evidence_boundary", evidence_boundary, EVIDENCE_BOUNDARY_REQUIRED_FIELDS, errors)
    _check_required_fields("confidence_policy", confidence_policy, CONFIDENCE_POLICY_REQUIRED_FIELDS, errors)

    evidence_mode = _as_text(metadata.get("evidence_mode"))
    full_text_acquisition_used = metadata.get("full_text_acquisition_used")
    if evidence_mode and evidence_mode not in EVIDENCE_MODES:
        errors.append(f"invalid_enum:metadata.evidence_mode:{evidence_mode}")
    for bool_field in ("network_used", "llm_used", "source_acquisition_used", "full_text_acquisition_used"):
        if bool_field in metadata and not isinstance(metadata.get(bool_field), bool):
            errors.append(f"invalid_type:metadata.{bool_field}:expected_bool")
    if evidence_mode == "simulated":
        warnings.append("simulated_evidence_limitation:no_real_source_or_full_text_verification_performed")
        confidence_upgrade_blocked = True

    source_ids = _collect_unique_ids("source_registry", sources, "source_id", errors)
    claim_ids = _collect_unique_ids("claim_table_v2", claims, "claim_id", errors)

    for idx, obligation in enumerate(obligations):
        path = f"user_question_obligations[{idx}]"
        if not isinstance(obligation, dict):
            errors.append(f"{path}:not_object")
            continue
        _check_required_fields(path, obligation, OBLIGATION_REQUIRED_FIELDS, errors)
        _check_enum(path, obligation, "obligation_type", OBLIGATION_TYPES, errors)
        _check_enum(path, obligation, "coverage_status", COVERAGE_STATUSES, errors)
        _check_list_field(path, obligation, "linked_claim_ids", errors)
        for claim_id in _as_list(obligation.get("linked_claim_ids")):
            if claim_id not in claim_ids:
                errors.append(f"{path}.linked_claim_ids:unknown_claim_id:{claim_id}")

    for idx, source in enumerate(sources):
        path = f"source_registry[{idx}]"
        if not isinstance(source, dict):
            errors.append(f"{path}:not_object")
            continue
        _check_required_fields(path, source, SOURCE_REQUIRED_FIELDS, errors)
        _check_enum(path, source, "retrieval_status", RETRIEVAL_STATUSES, errors)
        if source.get("full_text_accessed") is True and source.get("retrieval_status") != "full_text_accessed":
            errors.append(f"{path}:full_text_accessed_requires_retrieval_status_full_text_accessed")
        if "full_text_available" in source and not isinstance(source.get("full_text_available"), bool):
            errors.append(f"{path}.full_text_available:expected_bool")
        if "full_text_accessed" in source and not isinstance(source.get("full_text_accessed"), bool):
            errors.append(f"{path}.full_text_accessed:expected_bool")

    claim_by_id = {str(claim.get("claim_id")): claim for claim in claims if isinstance(claim, dict)}
    for idx, claim in enumerate(claims):
        path = f"claim_table_v2[{idx}]"
        if not isinstance(claim, dict):
            errors.append(f"{path}:not_object")
            continue
        _check_required_fields(path, claim, CLAIM_REQUIRED_FIELDS, errors)
        _check_enum(path, claim, "claim_type", CLAIM_TYPES, errors)
        _check_enum(path, claim, "support_level", SUPPORT_LEVELS, errors)
        _check_enum(path, claim, "retrieval_status", RETRIEVAL_STATUSES, errors)
        _check_enum(path, claim, "confidence_effect", CONFIDENCE_EFFECTS, errors)
        _check_enum(path, claim, "contradiction_status", CONTRADICTION_STATUSES, errors)
        _check_list_field(path, claim, "user_obligation_ids", errors)
        _check_list_field(path, claim, "source_ids", errors)

        claim_id = _as_text(claim.get("claim_id")) or f"claim_{idx}"
        claim_type = _as_text(claim.get("claim_type"))
        support_level = _as_text(claim.get("support_level"))
        retrieval_status = _as_text(claim.get("retrieval_status"))
        confidence_effect = _as_text(claim.get("confidence_effect"))
        contradiction_status = _as_text(claim.get("contradiction_status"))
        final_allowed_wording = _as_text(claim.get("final_allowed_wording"))
        source_basis = _basis_text(claim.get("source_basis"))
        source_id_values = [str(value) for value in _as_list(claim.get("source_ids"))]
        is_simulated_basis = "simulated_fixture" in source_basis or source_basis == "simulated_fixture_only"
        is_snippet_basis = "snippet" in source_basis or source_basis == "search_result_snippet"
        full_text_verified = claim.get("full_text_verified")

        if full_text_verified is not False and not isinstance(full_text_verified, bool):
            errors.append(f"{path}.full_text_verified:expected_bool")
        if claim_type in HIGH_RISK_CLAIM_TYPES:
            high_risk_claims.append(claim_id)
        if support_level in {"unverified", "speculative", "weakly_supported", "disputed", "contradicted", "fabrication_risk"}:
            unverified_claims.append(claim_id)
        if support_level in {"disputed", "contradicted", "fabrication_risk"} or contradiction_status in CONTRADICTION_BAD_STATUSES:
            contradicted_claims.append(claim_id)

        if not is_simulated_basis:
            for source_id in source_id_values:
                if source_id not in source_ids:
                    errors.append(f"{path}.source_ids:unknown_source_id:{source_id}")

        if full_text_verified is True:
            if retrieval_status == "simulated_fixture_only":
                errors.append(f"{path}:full_text_verified_forbidden_for_simulated_fixture_retrieval")
            if is_simulated_basis:
                errors.append(f"{path}:full_text_verified_forbidden_for_simulated_fixture_basis")
            if is_snippet_basis:
                errors.append(f"{path}:full_text_verified_forbidden_for_snippet_basis")
            if full_text_acquisition_used is False:
                errors.append(f"{path}:full_text_verified_requires_metadata_full_text_acquisition_used")
            if evidence_mode == "simulated":
                errors.append(f"{path}:full_text_verified_forbidden_in_simulated_evidence_mode")

        if evidence_mode == "simulated" and confidence_effect == "upgrade_allowed":
            errors.append(f"{path}:upgrade_allowed_forbidden_in_simulated_evidence_mode")
            confidence_upgrade_blocked = True

        if confidence_effect == "upgrade_allowed":
            if support_level in WEAK_SUPPORT_FOR_UPGRADE:
                errors.append(f"{path}:upgrade_allowed_forbidden_for_support_level:{support_level}")
                confidence_upgrade_blocked = True
            if claim_type in HIGH_RISK_CLAIM_TYPES and full_text_verified is not True:
                errors.append(f"{path}:upgrade_allowed_forbidden_for_high_risk_without_full_text_verified")
                confidence_upgrade_blocked = True
            if contradiction_status in CONTRADICTION_BAD_STATUSES:
                errors.append(f"{path}:upgrade_allowed_forbidden_for_contradiction_status:{contradiction_status}")
                confidence_upgrade_blocked = True
            if not source_id_values and not is_simulated_basis:
                errors.append(f"{path}:upgrade_allowed_forbidden_without_sources")
                confidence_upgrade_blocked = True

        if claim_type in HIGH_RISK_CLAIM_TYPES and full_text_verified is not True and support_level not in {"verified", "strongly_supported"}:
            source_need_required = True
            confidence_upgrade_blocked = True
            if confidence_effect not in SOURCE_NEED_EFFECTS:
                errors.append(f"{path}:high_risk_weak_or_unverified_claim_requires_downgrade_source_need_remove_or_expert_review")

        if contradiction_status in CONTRADICTION_BAD_STATUSES:
            source_need_required = True
            if confidence_effect not in SOURCE_NEED_EFFECTS:
                errors.append(f"{path}:contradiction_requires_downgrade_source_need_remove_or_expert_review")
            if _is_strong_assertion(final_allowed_wording):
                errors.append(f"{path}:contradiction_final_allowed_wording_must_not_be_strong_assertion")

        if support_level in UNSUPPORTED_SUPPORT_LEVELS:
            if confidence_effect == "upgrade_allowed":
                errors.append(f"{path}:unsupported_support_level_cannot_upgrade")
                confidence_upgrade_blocked = True
            if not _has_uncertainty_or_removal_language(final_allowed_wording):
                errors.append(f"{path}:unsupported_claim_requires_uncertainty_or_removal_wording")

        if not final_allowed_wording.strip():
            errors.append(f"{path}:missing_final_allowed_wording")

    for idx, pair in enumerate(pairs):
        path = f"citation_claim_pairs[{idx}]"
        if not isinstance(pair, dict):
            errors.append(f"{path}:not_object")
            continue
        _check_required_fields(path, pair, CITATION_PAIR_REQUIRED_FIELDS, errors)
        _check_enum(path, pair, "match_type", MATCH_TYPES, errors)
        _check_enum(path, pair, "consistency_status", CONSISTENCY_STATUSES, errors)
        _check_enum(path, pair, "numeric_exactness", EXACTNESS_VALUES, errors)
        _check_enum(path, pair, "date_exactness", EXACTNESS_VALUES, errors)
        _check_enum(path, pair, "quote_exactness", EXACTNESS_VALUES, errors)
        claim_id = _as_text(pair.get("claim_id"))
        source_id = _as_text(pair.get("source_id"))
        if claim_id and claim_id not in claim_ids:
            errors.append(f"{path}:unknown_claim_id:{claim_id}")
        if source_id and source_id not in source_ids:
            errors.append(f"{path}:unknown_source_id:{source_id}")

    matrix_claim_ids: set[str] = set()
    for idx, row in enumerate(matrix):
        path = f"verification_matrix[{idx}]"
        if not isinstance(row, dict):
            errors.append(f"{path}:not_object")
            continue
        _check_required_fields(path, row, VERIFICATION_REQUIRED_FIELDS, errors)
        _check_enum(path, row, "support_level_final", SUPPORT_LEVELS, errors)
        _check_enum(path, row, "confidence_delta", CONFIDENCE_DELTAS, errors)
        for list_field in ("verified_by_sources", "contradicted_by_sources", "unresolved_sources"):
            _check_list_field(path, row, list_field, errors)
            for source_id in _as_list(row.get(list_field)):
                if source_id not in source_ids:
                    errors.append(f"{path}.{list_field}:unknown_source_id:{source_id}")
        claim_id = _as_text(row.get("claim_id"))
        if claim_id:
            matrix_claim_ids.add(claim_id)
            if claim_id not in claim_ids:
                errors.append(f"{path}:unknown_claim_id:{claim_id}")
            claim = claim_by_id.get(claim_id)
            if claim and _as_text(claim.get("contradiction_status")) in CONTRADICTION_BAD_STATUSES:
                if row.get("confidence_delta") not in {"downgrade", "force_source_need", "remove", "expert_review"}:
                    errors.append(f"{path}:unresolved_contradiction_requires_non_upgrade_confidence_delta")
                source_need_required = True

    for claim_id in sorted(claim_ids):
        if claim_id not in matrix_claim_ids:
            errors.append(f"verification_matrix:missing_claim_id:{claim_id}")

    for idx, contradiction in enumerate(contradictions):
        path = f"contradiction_table[{idx}]"
        if not isinstance(contradiction, dict):
            errors.append(f"{path}:not_object")
            continue
        _check_required_fields(path, contradiction, CONTRADICTION_REQUIRED_FIELDS, errors)
        _check_enum(path, contradiction, "contradiction_type", CONTRADICTION_TYPES, errors)
        _check_enum(path, contradiction, "severity", CONTRADICTION_SEVERITIES, errors)
        _check_enum(path, contradiction, "resolution", CONTRADICTION_RESOLUTIONS, errors)
        claim_id = _as_text(contradiction.get("claim_id"))
        if claim_id and claim_id not in claim_ids:
            errors.append(f"{path}:unknown_claim_id:{claim_id}")
        _check_list_field(path, contradiction, "source_ids", errors)
        for source_id in _as_list(contradiction.get("source_ids")):
            if source_id not in source_ids:
                errors.append(f"{path}.source_ids:unknown_source_id:{source_id}")
        if contradiction.get("severity") == "blocking" and contradiction.get("resolution") != "claim_removed":
            errors.append(f"{path}:blocking_contradiction_requires_claim_removed")

    for idx, trace in enumerate(final_trace):
        path = f"final_answer_traceability[{idx}]"
        if not isinstance(trace, dict):
            errors.append(f"{path}:not_object")
            continue
        _check_required_fields(path, trace, FINAL_TRACE_REQUIRED_FIELDS, errors)
        for list_field in ("claim_ids_used", "source_ids_used", "unsupported_claims_removed", "caveats_required"):
            _check_list_field(path, trace, list_field, errors)
        for claim_id in _as_list(trace.get("claim_ids_used")):
            if claim_id not in claim_ids:
                errors.append(f"{path}.claim_ids_used:unknown_claim_id:{claim_id}")
        for claim_id in _as_list(trace.get("unsupported_claims_removed")):
            if claim_id not in claim_ids:
                errors.append(f"{path}.unsupported_claims_removed:unknown_claim_id:{claim_id}")
        for source_id in _as_list(trace.get("source_ids_used")):
            if source_id not in source_ids:
                errors.append(f"{path}.source_ids_used:unknown_source_id:{source_id}")

    return ValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        source_need_required=source_need_required,
        confidence_upgrade_blocked=confidence_upgrade_blocked,
        high_risk_claims=sorted(set(high_risk_claims)),
        unverified_claims=sorted(set(unverified_claims)),
        contradicted_claims=sorted(set(contradicted_claims)),
    )


def render_packet_markdown(packet: dict[str, Any]) -> str:
    result = validate_packet(packet)
    lines: list[str] = ["# Evidence Packet v2", ""]
    lines.extend(_render_mapping_section("Metadata", packet.get("metadata", {})))
    lines.extend(_render_items_section("User Question Obligations", packet.get("user_question_obligations", []), "obligation_id"))
    lines.extend(_render_items_section("Claim Table v2", packet.get("claim_table_v2", []), "claim_id"))
    lines.extend(_render_items_section("Source Registry", packet.get("source_registry", []), "source_id"))
    lines.extend(_render_items_section("Citation-Claim Pairs", packet.get("citation_claim_pairs", []), "pair_id"))
    lines.extend(_render_items_section("Verification Matrix", packet.get("verification_matrix", []), "claim_id"))
    lines.extend(_render_items_section("Contradiction Table", packet.get("contradiction_table", []), "contradiction_id"))
    lines.extend(_render_mapping_section("Evidence Boundary", packet.get("evidence_boundary", {})))
    lines.extend(_render_mapping_section("Confidence Policy", packet.get("confidence_policy", {})))
    lines.extend(_render_items_section("Final Answer Traceability", packet.get("final_answer_traceability", []), "final_section"))
    lines.extend(
        [
            "## Validation Summary",
            "",
            f"- ok: {_bool_text(result.ok)}",
            f"- source_need_required: {_bool_text(result.source_need_required)}",
            f"- confidence_upgrade_blocked: {_bool_text(result.confidence_upgrade_blocked)}",
            f"- high_risk_claims: {_format_value(result.high_risk_claims)}",
            f"- unverified_claims: {_format_value(result.unverified_claims)}",
            f"- contradicted_claims: {_format_value(result.contradicted_claims)}",
            f"- warnings: {_format_value(result.warnings)}",
            f"- errors: {_format_value(result.errors)}",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_minimal_sample_packet(case_id: str, user_question: str) -> dict[str, Any]:
    safe_case_id = _safe_id(case_id or "sample")
    question = (user_question or "Sample Evidence Packet v2 contract validation question.").strip()
    claim_type = "financial_risk" if "B06" in safe_case_id.upper() or "lending" in safe_case_id.lower() else "market_claim"
    claim_id = "C1"
    source_id = "SIM-S1"
    packet_id = f"epv2-simulated-{safe_case_id.lower()}"
    return {
        "metadata": {
            "packet_id": packet_id,
            "case_id": safe_case_id,
            "task_mode": "CONTRACT_SAMPLE",
            "generated_at": "2026-06-29T00:00:00Z",
            "as_of_date": "2026-06-29",
            "evidence_mode": "simulated",
            "network_used": False,
            "llm_used": False,
            "source_acquisition_used": False,
            "full_text_acquisition_used": False,
        },
        "user_question_obligations": [
            {
                "obligation_id": "O1",
                "obligation_text": question,
                "obligation_type": "decision_required",
                "coverage_status": "covered_unverified",
                "linked_claim_ids": [claim_id],
            }
        ],
        "claim_table_v2": [
            {
                "claim_id": claim_id,
                "claim_text": "This simulated packet can validate Evidence Packet v2 contract shape but cannot verify real domain claims.",
                "claim_type": claim_type,
                "importance": "material",
                "decision_relevance": "contract_validation_only",
                "user_obligation_ids": ["O1"],
                "source_ids": [source_id],
                "source_basis": "simulated_fixture_only",
                "support_level": "unverified",
                "contradiction_status": "none",
                "full_text_verified": False,
                "retrieval_status": "simulated_fixture_only",
                "applicability": "Applies only to deterministic contract rendering and validation.",
                "confidence_effect": "force_source_need",
                "final_allowed_wording": "Do not claim as verified; source_need required before domain use.",
                "verification_notes": "No network, LLM, source acquisition, or full-text acquisition was performed.",
            }
        ],
        "source_registry": [
            {
                "source_id": source_id,
                "title": "Deterministic simulated fixture",
                "url_or_local_ref": "local:simulated_fixture",
                "source_type": "simulated_fixture",
                "publisher_or_author": "hermes-agent-research-decision",
                "publication_date": "2026-06-29",
                "access_date": "2026-06-29",
                "as_of_relevance": "contract_sample_only",
                "authority_tier": "fixture_only",
                "independence": "not_independent",
                "potential_bias": "not_real_evidence",
                "retrieval_status": "simulated_fixture_only",
                "full_text_available": False,
                "full_text_accessed": False,
                "full_text_hash_or_excerpt_ref": "",
                "source_limitations": "Fixture only; not an external source and not factual support.",
            }
        ],
        "citation_claim_pairs": [
            {
                "pair_id": "P1",
                "claim_id": claim_id,
                "source_id": source_id,
                "cited_span_or_location": "local simulated fixture row",
                "source_statement_summary": "The fixture states only that contract validation can run without real evidence.",
                "match_type": "direct_statement",
                "consistency_status": "consistent",
                "numeric_exactness": "not_applicable",
                "date_exactness": "not_applicable",
                "quote_exactness": "not_applicable",
                "mismatch_notes": "",
            }
        ],
        "verification_matrix": [
            {
                "claim_id": claim_id,
                "verified_by_sources": [],
                "contradicted_by_sources": [],
                "unresolved_sources": [source_id],
                "support_level_final": "unverified",
                "required_final_wording": "Only contract validation is supported; domain claims require source acquisition.",
                "confidence_delta": "force_source_need",
                "unresolved_reason": "simulated_fixture_only",
            }
        ],
        "contradiction_table": [],
        "evidence_boundary": {
            "what_is_verified": ["Contract shape can be validated deterministically."],
            "what_is_plausible": [],
            "what_is_speculative": [],
            "what_is_unverified": ["All real domain evidence claims remain unverified."],
            "what_requires_full_text": ["Any domain claim used for a user decision."],
            "what_requires_domain_expert": ["High-impact financial, legal, medical, or safety recommendations."],
            "what_cannot_be_claimed": ["Full-text verification, web verification, source-backed confidence, or real domain support."],
        },
        "confidence_policy": {
            "allowed_confidence_upgrades": [],
            "forced_confidence_downgrades": ["simulated evidence mode blocks confidence upgrades"],
            "no_upgrade_conditions": ["network_used=false", "full_text_acquisition_used=false", "simulated_fixture_only"],
            "source_need_conditions": ["real domain claim requires source acquisition and full-text verification"],
            "final_wording_constraints": ["Use only contract-validation wording; do not assert domain truth."],
        },
        "final_answer_traceability": [
            {
                "final_section": "contract_sample_summary",
                "claim_ids_used": [claim_id],
                "source_ids_used": [source_id],
                "unsupported_claims_removed": [claim_id],
                "caveats_required": ["simulated evidence limitation", "source_need before domain use"],
                "confidence_language_required": "Do not upgrade confidence; state that evidence is simulated only.",
            }
        ],
    }


def write_packet_outputs(packet: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    packet_copy = copy.deepcopy(packet)
    result = validate_packet(packet_copy)
    markdown = render_packet_markdown(packet_copy)

    packet_path = out / "packet.json"
    markdown_path = out / "packet.md"
    report_path = out / "validation_report.json"
    packet_path.write_text(json.dumps(packet_copy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    report_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "packet_json": str(packet_path),
        "packet_markdown": str(markdown_path),
        "validation_report": str(report_path),
        "validation": result.to_dict(),
    }


def _check_required_fields(path: str, obj: dict[str, Any], required: tuple[str, ...], errors: list[str]) -> None:
    for field in required:
        if field not in obj:
            errors.append(f"{path}:missing_field:{field}")


def _check_enum(path: str, obj: dict[str, Any], field: str, allowed: tuple[str, ...], errors: list[str]) -> None:
    if field not in obj:
        return
    value = obj.get(field)
    if value not in allowed:
        errors.append(f"invalid_enum:{path}.{field}:{value}")


def _check_list_field(path: str, obj: dict[str, Any], field: str, errors: list[str]) -> None:
    if field in obj and not isinstance(obj.get(field), list):
        errors.append(f"{path}.{field}:expected_list")


def _require_list(path: str, value: Any, errors: list[str], *, require_nonempty: bool) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{path}:expected_list")
        return []
    if require_nonempty and not value:
        errors.append(f"{path}:empty")
    return value


def _collect_unique_ids(path: str, rows: list[Any], id_field: str, errors: list[str]) -> set[str]:
    values: set[str] = set()
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        value = _as_text(row.get(id_field))
        if not value:
            errors.append(f"{path}[{idx}]:missing_field:{id_field}")
            continue
        if value in values:
            errors.append(f"{path}[{idx}]:duplicate_{id_field}:{value}")
        values.add(value)
    return values


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _basis_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(_as_text(item).lower() for item in value)
    return _as_text(value).lower()


def _has_uncertainty_or_removal_language(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in UNCERTAINTY_WORDS)


def _is_strong_assertion(text: str) -> bool:
    lowered = text.lower()
    if _has_uncertainty_or_removal_language(lowered):
        return False
    return any(pattern in lowered for pattern in STRONG_ASSERTION_PATTERNS)


def _render_mapping_section(title: str, data: Any) -> list[str]:
    lines = [f"## {title}", ""]
    if not isinstance(data, dict) or not data:
        lines.extend(["- missing", ""])
        return lines
    for key in sorted(data):
        lines.append(f"- {key}: {_format_value(data[key])}")
    lines.append("")
    return lines


def _render_items_section(title: str, items: Any, label_field: str) -> list[str]:
    lines = [f"## {title}", ""]
    if not isinstance(items, list) or not items:
        lines.extend(["- none", ""])
        return lines
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            lines.append(f"### Item {idx}")
            lines.append("")
            lines.append(f"- value: {_format_value(item)}")
            lines.append("")
            continue
        label = _as_text(item.get(label_field)) or f"item_{idx}"
        lines.append(f"### {label}")
        lines.append("")
        for key in sorted(item):
            lines.append(f"- {key}: {_format_value(item[key])}")
        lines.append("")
    return lines


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return _bool_text(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[" + "; ".join(_format_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    if value is None:
        return "null"
    return str(value)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("_") or "sample"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evidence Packet v2 deterministic contract utility.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate an Evidence Packet v2 JSON file.")
    validate.add_argument("--input", required=True, help="Path to packet JSON.")

    render = subparsers.add_parser("render", help="Render an Evidence Packet v2 JSON file to markdown.")
    render.add_argument("--input", required=True, help="Path to packet JSON.")
    render.add_argument("--output", required=True, help="Path to output markdown.")

    sample = subparsers.add_parser("sample", help="Write a deterministic simulated sample packet.")
    sample.add_argument("--case-id", required=True, help="Case id for the sample packet.")
    sample.add_argument("--user-question-file", required=True, help="Text file containing the user question.")
    sample.add_argument("--output-dir", required=True, help="Directory to receive packet.json, packet.md, validation_report.json.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        packet = load_packet_json(args.input)
        result = validate_packet(packet)
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.ok else 1

    if args.command == "render":
        packet = load_packet_json(args.input)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_packet_markdown(packet), encoding="utf-8")
        return 0

    if args.command == "sample":
        question = Path(args.user_question_file).read_text(encoding="utf-8")
        packet = build_minimal_sample_packet(args.case_id, question)
        result = write_packet_outputs(packet, args.output_dir)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["validation"]["ok"] else 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
