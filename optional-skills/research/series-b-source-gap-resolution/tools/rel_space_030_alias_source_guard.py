#!/usr/bin/env python3
"""Alias, source-family, and contamination guard for rel_space_030."""

from __future__ import annotations

from typing import Any

from series_b_rel_space_030_result_schema import (
    ALLOWED_BINDING_STATUSES,
    CASE_ID,
    REQUIRED_TERMS,
)


ACCEPTED_SOURCE_TYPES = {
    "local_professional_source_locator_context",
    "wiki_or_zim",
    "encyclopedia_context",
}

FORBIDDEN_TEXT_PATTERNS = {
    "listing_or_planning": [
        "travel listing",
        "route planning",
        "opening hours",
        "ticket booking",
        "booking link",
        "hotel recommendation",
        "restaurant recommendation",
        "itinerary",
        "top attractions",
    ],
    "generic_tourism": [
        "tour package",
        "visitor center schedule",
        "best time to visit",
    ],
    "wrong_domain_mythology": [
        "generic hindu mythology",
        "mythology retelling without temple",
        "shiva family story without architecture",
    ],
    "wrong_domain_science": [
        "coral reef",
        "atoll",
        "flintknapping",
        "roman concrete",
        "mogao caves",
    ],
    "query_echo": [
        "query echo",
        "search query",
    ],
    "generated_echo": [
        "generated echo",
        "placeholder generated",
        "dummy_test_artifact_only",
        "mock_builder_output: true",
        '"mock_builder_output": true',
        '"mock_audit_output": true',
    ],
    "readme_or_title_only": [
        "README summary counted as evidence",
        "title-only evidence counted: true",
        "README or title-only chunks counted as evidence: true",
    ],
}


class RelSpace030GuardError(ValueError):
    """Raised when rel_space_030 guard checks fail."""


def _contains_any(text: str, variants: list[str]) -> bool:
    lowered = text.lower()
    return any(variant.lower() in lowered for variant in variants)


def check_text(text: str) -> list[str]:
    violations: list[str] = []
    for label, variants in FORBIDDEN_TEXT_PATTERNS.items():
        if _contains_any(text, variants):
            violations.append(label)
    return violations


def _source_title(chunk: dict[str, Any]) -> str:
    return str(chunk.get("article_title / source_title") or chunk.get("source_title") or chunk.get("article_title") or "")


def _source_backed(chunk: dict[str, Any]) -> bool:
    return chunk.get("source_backed_text_exists") is True or chunk.get("source-backed text exists") is True


def _approved(chunk: dict[str, Any]) -> bool:
    return str(chunk.get("reviewer_decision", "")).startswith("FORMAL_READY_APPROVED")


def validate_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    violations: list[str] = []
    local_locator_count = 0
    wiki_context_count = 0
    mount_meru_context_count = 0
    sacred_geometry_count = 0

    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id", ""))
        source_id = str(chunk.get("source_id", ""))
        source_type = str(chunk.get("source_type", ""))
        source_title = _source_title(chunk)
        supported = {str(term) for term in chunk.get("supports_terms", [])}

        if CASE_ID not in chunk_id or CASE_ID not in source_id:
            violations.append(f"{chunk_id}:wrong_case_scope")
        if source_type not in ACCEPTED_SOURCE_TYPES:
            violations.append(f"{chunk_id}:unapproved_source_type")
        if chunk.get("binding_status") not in ALLOWED_BINDING_STATUSES:
            violations.append(f"{chunk_id}:binding_caveat_missing")
        if not _source_backed(chunk):
            violations.append(f"{chunk_id}:source_backed_text_missing")
        if chunk.get("wrong_context_guard_passed") is not True:
            violations.append(f"{chunk_id}:wrong_context_guard_failed")
        if not _approved(chunk):
            violations.append(f"{chunk_id}:not_formal_ready_approved")
        for flag in (
            "title_only",
            "query_echo",
            "generated_echo",
            "README_summary",
            "listing_or_planning_noise",
            "wrong_domain",
        ):
            if chunk.get(flag) is True:
                violations.append(f"{chunk_id}:{flag}")
        if not supported.intersection(REQUIRED_TERMS):
            violations.append(f"{chunk_id}:no_required_terms")
        if "README" in source_title or "title-only" in source_title.lower():
            violations.append(f"{chunk_id}:readme_or_title_only_source")

        if source_type == "local_professional_source_locator_context":
            local_locator_count += 1
            if "mount meru" in {term.lower() for term in supported}:
                violations.append(f"{chunk_id}:mount_meru_miscast_as_professional_primary")
        if source_type in {"wiki_or_zim", "encyclopedia_context"}:
            wiki_context_count += 1
        if "Mount Meru" in supported:
            mount_meru_context_count += 1
            if source_type not in {"wiki_or_zim", "encyclopedia_context"}:
                violations.append(f"{chunk_id}:mount_meru_not_contextual")
        if "sacred geometry" in supported:
            sacred_geometry_count += 1

    if local_locator_count < 4:
        violations.append(f"local_professional_locator_count:{local_locator_count}")
    if wiki_context_count < 4:
        violations.append(f"wiki_or_zim_context_count:{wiki_context_count}")
    if mount_meru_context_count < 1:
        violations.append("mount_meru_context_missing")
    if sacred_geometry_count < 1:
        violations.append("sacred_geometry_equivalent_missing")

    if violations:
        raise RelSpace030GuardError("; ".join(violations))
    return {
        "case_id": CASE_ID,
        "status": "PASS",
        "approved_chunk_count": len(chunks),
        "local_professional_locator_count": local_locator_count,
        "wiki_or_zim_context_count": wiki_context_count,
        "mount_meru_contextual_evidence_only": True,
        "sacred_geometry_equivalent_evidence_present": True,
        "context_locator_evidence_not_overstated": True,
    }
