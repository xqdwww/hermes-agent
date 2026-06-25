#!/usr/bin/env python3
"""Alias and contamination guard for cross_route_052."""

from __future__ import annotations

from typing import Any

from series_b_cross_route_052_result_schema import CASE_ID, REQUIRED_TERMS


ACCEPTED_SOURCE_TITLES = {
    "Getty Cave85 Conservation",
    "Wu Spatial Dunhuang",
    "Wang Mogao Cliff Reinforcement",
}

ACCEPTED_SOURCE_IDS = {
    "series_b_professional:cross_route_052:art_architecture:getty_cave85_conservation",
    "series_b_professional:cross_route_052:art_architecture:wu_spatial_dunhuang",
    "series_b_professional:cross_route_052:engineering_geology:wang_mogao_cliff",
}

FORBIDDEN_TEXT_PATTERNS = {
    "listing_or_planning": [
        "travel listing",
        "route planning",
        "opening hours",
        "ticket booking",
        "hotel",
        "restaurant",
        "booking",
        "itinerary",
        "top attractions",
    ],
    "generic_china_travel_noise": [
        "china travel guide",
        "tour package",
        "day trip",
        "visa tips",
    ],
    "wrong_domain_science": [
        "roman concrete",
        "clovis point",
        "flintknapping",
        "aeolian sand",
        "saltation",
        "atoll",
        "coral reef",
        "hindu temple",
        "shikhara",
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
    ],
}


class CrossRoute052GuardError(ValueError):
    """Raised when cross_route_052 guard checks fail."""


def _contains_any(text: str, variants: list[str]) -> bool:
    lowered = text.lower()
    return any(variant.lower() in lowered for variant in variants)


def check_text(text: str) -> list[str]:
    violations: list[str] = []
    for label, variants in FORBIDDEN_TEXT_PATTERNS.items():
        if _contains_any(text, variants):
            violations.append(label)
    return violations


def validate_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    violations: list[str] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id", ""))
        source_id = str(chunk.get("source_id", ""))
        source_title = str(chunk.get("source_title", ""))
        if chunk.get("case_id") not in (None, CASE_ID):
            violations.append(f"{chunk_id}:case_id_mismatch")
        if CASE_ID not in chunk_id or CASE_ID not in source_id:
            violations.append(f"{chunk_id}:wrong_case_scope")
        if source_id not in ACCEPTED_SOURCE_IDS:
            violations.append(f"{chunk_id}:unapproved_source_id")
        if source_title not in ACCEPTED_SOURCE_TITLES:
            violations.append(f"{chunk_id}:unapproved_source_title")
        if "context" in source_id.lower() or "context" in source_title.lower():
            violations.append(f"{chunk_id}:context_source_not_primary")
        if chunk.get("binding_status") != "PAGE_BOUND_WEAK_EPUB_SECTION_BOUND":
            violations.append(f"{chunk_id}:binding_caveat_missing")
        if "hydrology" in {str(term).lower() for term in chunk.get("supports_terms", [])}:
            violations.append(f"{chunk_id}:hydrology_must_not_be_primary_evidence")
        for flag in (
            "title_only",
            "is_title_only",
            "query_echo",
            "is_query_echo",
            "generated_echo",
            "is_generated_echo",
            "listing_or_planning_noise",
            "is_listing_or_travel_planning",
            "wrong_domain",
            "sports_noise",
        ):
            if chunk.get(flag) is True:
                violations.append(f"{chunk_id}:{flag}")
        supported = {str(term) for term in chunk.get("supports_terms", [])}
        if not supported.intersection(REQUIRED_TERMS):
            violations.append(f"{chunk_id}:no_required_terms")
    if violations:
        raise CrossRoute052GuardError("; ".join(violations))
    return {
        "case_id": CASE_ID,
        "status": "PASS",
        "approved_chunk_count": len(chunks),
        "accepted_source_titles": sorted(ACCEPTED_SOURCE_TITLES),
        "hydrology_primary_evidence": False,
    }
