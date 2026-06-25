#!/usr/bin/env python3
"""Alias/source guard for cross_route_054 controlled execution."""

from __future__ import annotations

from typing import Any

from series_b_cross_route_054_result_schema import CASE_ID

FORBIDDEN_SUBSTRINGS = [
    "hotel",
    "restaurant",
    "booking",
    "ticket",
    "opening hours",
    "itinerary",
    "route-planning advice",
    "travel package",
    "cloudflare managed challenge",
    "just a moment... enable javascript",
    "__cf_chl",
]

FORBIDDEN_SOURCE_FILES = {
    "README.md",
    "unesco_land_of_frankincense_sustainable_tourism_case_study.html",
    "unesco_land_of_frankincense_sustainable_tourism_case_study_saved_page.html",
}


class CrossRoute054GuardError(ValueError):
    """Raised when cross_route_054 evidence violates the source guard."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def check_text(text: str) -> list[str]:
    lower = text.lower()
    return [term for term in FORBIDDEN_SUBSTRINGS if term in lower]


def validate_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    violations: list[str] = []
    for chunk in chunks:
        if chunk.get("case_id") != CASE_ID:
            violations.append(f"case mismatch: {chunk.get('chunk_id')}")
        source_file = str(chunk.get("source_file") or chunk.get("provenance_metadata", {}).get("source_file") or "")
        if source_file in FORBIDDEN_SOURCE_FILES:
            violations.append(f"forbidden source file: {source_file}")
        if chunk.get("title_only") is True or chunk.get("generated_echo") is True or chunk.get("query_echo") is True:
            violations.append(f"weak/generated chunk: {chunk.get('chunk_id')}")
        if chunk.get("wrong_context_guard_passed") is not True:
            violations.append(f"wrong-context guard failed: {chunk.get('chunk_id')}")
        text = str(chunk.get("source_backed_text") or chunk.get("content") or "")
        bad = check_text(text)
        if bad:
            violations.append(f"forbidden text {bad}: {chunk.get('chunk_id')}")
    if violations:
        raise CrossRoute054GuardError("BLOCKED_ROUTE_LISTING_CONTAMINATION", "; ".join(violations))
    return {"case_id": CASE_ID, "guard_result": "PASS", "checked_chunks": len(chunks)}
