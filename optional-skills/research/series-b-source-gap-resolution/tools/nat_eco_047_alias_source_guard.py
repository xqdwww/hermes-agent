#!/usr/bin/env python3
"""Alias, source-family, and contamination guard for nat_eco_047."""

from __future__ import annotations

from typing import Any

from series_b_nat_eco_047_result_schema import (
    ALLOWED_BINDING_STATUSES,
    CASE_ID,
    REQUIRED_TERMS,
)


ACCEPTED_SOURCE_TYPES = {
    "wiki_or_zim",
    "encyclopedia_context",
    "local_professional_source_locator_context",
}

FORBIDDEN_TEXT_PATTERNS = {
    "listing_or_planning": [
        "travel listing",
        "route planning",
        "opening hours",
        "ticket booking",
        "hotel",
        "resort",
        "restaurant",
        "booking",
        "itinerary",
        "top attractions",
        "snorkeling tour",
        "diving package",
    ],
    "generic_tropical_tourism": [
        "beach vacation",
        "honeymoon package",
        "island getaway",
        "all inclusive",
    ],
    "wrong_domain_darwin": [
        "darwin biography",
        "origin of species",
        "natural selection",
        "finches",
    ],
    "wrong_domain_science": [
        "clovis point",
        "flintknapping",
        "mogao caves",
        "fresco",
        "roman concrete",
        "hindu temple",
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


class NatEco047GuardError(ValueError):
    """Raised when nat_eco_047 guard checks fail."""


def _contains_any(text: str, variants: list[str]) -> bool:
    lowered = text.lower()
    return any(variant.lower() in lowered for variant in variants)


def check_text(text: str) -> list[str]:
    violations: list[str] = []
    lowered = text.lower()
    for label, variants in FORBIDDEN_TEXT_PATTERNS.items():
        if _contains_any(text, variants):
            if label == "wrong_domain_darwin" and "darwin coral reef theory" in lowered:
                continue
            violations.append(label)
    return violations


def _source_title(chunk: dict[str, Any]) -> str:
    return str(chunk.get("article_title / source_title") or chunk.get("source_title") or chunk.get("article_title") or "")


def validate_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    violations: list[str] = []
    local_locator_count = 0
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id", ""))
        source_id = str(chunk.get("source_id", ""))
        source_type = str(chunk.get("source_type", ""))
        source_title = _source_title(chunk)
        if CASE_ID not in chunk_id or CASE_ID not in source_id:
            violations.append(f"{chunk_id}:wrong_case_scope")
        if source_type not in ACCEPTED_SOURCE_TYPES:
            violations.append(f"{chunk_id}:unapproved_source_type")
        if chunk.get("binding_status") not in ALLOWED_BINDING_STATUSES:
            violations.append(f"{chunk_id}:binding_caveat_missing")
        if chunk.get("source-backed text exists") is not True:
            violations.append(f"{chunk_id}:source_backed_text_missing")
        if chunk.get("wrong_context_guard_passed") is not True:
            violations.append(f"{chunk_id}:wrong_context_guard_failed")
        if chunk.get("reviewer_decision") != "FORMAL_READY_APPROVED_WITH_BINDING_CAVEAT":
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
        supported = {str(term) for term in chunk.get("supports_terms", [])}
        if not supported.intersection(REQUIRED_TERMS):
            violations.append(f"{chunk_id}:no_required_terms")
        if "README" in source_title or "title-only" in source_title.lower():
            violations.append(f"{chunk_id}:readme_or_title_only_source")
        if source_type == "local_professional_source_locator_context":
            local_locator_count += 1
            if "coral reefs" not in source_title.lower():
                violations.append(f"{chunk_id}:unexpected_local_locator_source")
    if local_locator_count != 1:
        violations.append(f"local_professional_locator_count:{local_locator_count}")
    if violations:
        raise NatEco047GuardError("; ".join(violations))
    return {
        "case_id": CASE_ID,
        "status": "PASS",
        "approved_chunk_count": len(chunks),
        "local_professional_locator_count": local_locator_count,
        "local_professional_source_primary_wiki_or_zim": False,
    }
