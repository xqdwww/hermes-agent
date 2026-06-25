#!/usr/bin/env python3
"""Alias, source, and contamination guard for obj_art_007."""

from __future__ import annotations

from typing import Any

from series_b_obj_art_007_result_schema import (
    ALLOWED_PAGE_BOUND_STATUSES,
    APPROVED_REVIEWER_DECISION,
    CASE_ID,
    REQUIRED_TERMS,
)

FORBIDDEN_TEXT_PATTERNS = {
    "listing_or_planning": [
        "travel listing",
        "route planning",
        "opening hours",
        "ticket booking",
        "hotel",
        "restaurant",
        "booking",
        "phone number",
        "address map",
        "itinerary",
        "top attractions",
    ],
    "wrong_domain_generic_architecture": [
        "generic chinese architecture without dougong",
        "generic earthquake content without timber",
    ],
    "wrong_domain_other_cases": [
        "roman concrete",
        "pozzolana",
        "atoll",
        "coral reef",
        "garbha griha",
        "frankincense",
        "clovis point",
        "mogao caves",
    ],
    "query_echo": ["query echo", "search query"],
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
    "exact_page_claim": [
        "precise page-bound evidence",
        "exact page citation",
        "exact page number claimed",
    ],
}

REQUIRED_SOURCE_TITLE_TOKENS = {
    "Dou-Gong Mechanical Behavior",
    "Feng Chinese Architecture and Metaphor (preview)",
    "Liang Chinese Architecture Pictorial History",
}


class ObjArt007GuardError(ValueError):
    """Raised when obj_art_007 guard checks fail."""


def _contains_any(text: str, variants: list[str]) -> bool:
    lowered = text.lower()
    return any(variant.lower() in lowered for variant in variants)


def check_text(text: str) -> list[str]:
    violations: list[str] = []
    lowered = text.lower()
    for label, variants in FORBIDDEN_TEXT_PATTERNS.items():
        if _contains_any(text, variants):
            if label == "wrong_domain_generic_architecture" and "dougong" in lowered and "timber" in lowered:
                continue
            if label == "exact_page_claim" and "no precise page numbers are claimed" in lowered:
                continue
            violations.append(label)
    return violations


def _source_title(chunk: dict[str, Any]) -> str:
    return str(chunk.get("source_title") or chunk.get("article_title") or "")


def _source_backed_locator(chunk: dict[str, Any]) -> bool:
    locator = chunk.get("source_backed_text_locator")
    return isinstance(locator, dict) and bool(locator.get("chunk_id")) and bool(locator.get("text_sha256"))


def validate_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    violations: list[str] = []
    source_titles: set[str] = set()
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id", ""))
        source_id = str(chunk.get("source_id", ""))
        source_title = _source_title(chunk)
        source_titles.add(source_title)
        if CASE_ID not in chunk_id or CASE_ID not in source_id:
            violations.append(f"{chunk_id}:wrong_case_scope")
        if "context" in source_id.lower() or "README" in source_title or "local_source_term_locators" in source_id:
            violations.append(f"{chunk_id}:readme_or_locator_source_not_allowed")
        if chunk.get("page_start") == 0 and chunk.get("page_end") == 0:
            if chunk.get("provenance_metadata", {}).get("page_binding_caveat") is not True:
                violations.append(f"{chunk_id}:page_binding_caveat_missing")
        status = chunk.get("page_bound_status")
        if status not in ALLOWED_PAGE_BOUND_STATUSES:
            violations.append(f"{chunk_id}:unsupported_page_bound_status")
        if not _source_backed_locator(chunk):
            violations.append(f"{chunk_id}:source_backed_text_locator_missing")
        if chunk.get("reviewer_decision") != APPROVED_REVIEWER_DECISION:
            violations.append(f"{chunk_id}:not_formal_ready_approved")
        if chunk.get("wrong_context_guard_passed") is not True:
            violations.append(f"{chunk_id}:wrong_context_guard_failed")
        for flag in (
            "title_only",
            "query_echo",
            "generated_echo",
            "image_filename_only",
            "wrong_context",
            "listing_or_travel_planning",
            "README_summary",
        ):
            if chunk.get(flag) is True:
                violations.append(f"{chunk_id}:{flag}")
        supported = {str(term) for term in chunk.get("supports_terms", [])}
        if not supported:
            violations.append(f"{chunk_id}:no_supported_terms")
        if not any(
            required.lower() in " ".join(supported).lower()
            or any(part in " ".join(supported).lower() for part in ("dougong", "bracket", "timber", "load", "mortise"))
            for required in REQUIRED_TERMS
        ):
            violations.append(f"{chunk_id}:no_required_term_family")
    if not REQUIRED_SOURCE_TITLE_TOKENS.intersection(source_titles):
        violations.append("expected_professional_sources_missing")
    if violations:
        raise ObjArt007GuardError("; ".join(violations))
    return {
        "case_id": CASE_ID,
        "status": "PASS",
        "approved_chunk_count": len(chunks),
        "source_titles": sorted(source_titles),
        "page_binding_caveat_required": True,
        "precise_page_claim_allowed": False,
    }
