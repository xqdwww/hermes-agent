#!/usr/bin/env python3
"""Alias and source-contamination guard for hist_arch_023."""

from __future__ import annotations

from typing import Any

from series_b_hist_arch_023_result_schema import CASE_ID, REQUIRED_TERMS


ACCEPTED_SOURCE_TITLES = {
    "Bradley Clovis Technology",
    "Tsirk Fractures in Knapping",
}

ACCEPTED_SOURCE_IDS = {
    "series_b_professional:hist_arch_023:archaeology_book:bradley_clovis_technology",
    "series_b_professional:hist_arch_023:archaeology_book:tsirk_fractures_knapping",
}

FORBIDDEN_TEXT_PATTERNS = {
    "listing_or_planning": [
        "travel listing",
        "opening hours",
        "ticket booking",
        "hotel",
        "restaurant",
        "booking",
        "itinerary",
    ],
    "sports_noise": [
        "sports point",
        "basketball point",
        "football score",
        "team score",
        "league table",
    ],
    "wrong_domain_roman": [
        "roman concrete",
        "pozzolana",
        "opus caementicium",
    ],
    "wrong_domain_hindu": [
        "hindu temple",
        "shikhara",
        "garbha griha",
        "mandapa",
    ],
    "wrong_domain_aeolian": [
        "aeolian sand",
        "saltation",
        "sand dune",
        "wind erosion",
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


class HistArch023GuardError(ValueError):
    """Raised when hist_arch_023 guard checks fail."""


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
        raise HistArch023GuardError("; ".join(violations))
    return {
        "case_id": CASE_ID,
        "status": "PASS",
        "approved_chunk_count": len(chunks),
        "accepted_source_titles": sorted(ACCEPTED_SOURCE_TITLES),
    }
