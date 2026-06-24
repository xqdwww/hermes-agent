#!/usr/bin/env python3
"""Contamination guard for obj_art_003 controlled dry-runs."""

from __future__ import annotations

import re
from typing import Iterable


class ObjArt003GuardError(ValueError):
    """Raised when controlled obj_art_003 content fails source/alias guards."""


NOISE_PATTERNS = {
    "listing_or_planning": r"\blisting\b|\blistings\b|\bplanning\b",
    "visitor_noise": r"\bhotel\b|\brestaurant\b|\bticket\b|\bbooking\b|\breservation\b|\bopening hours\b",
    "contact_or_wayfinding": r"\baddress\b|\bphone\b|\btelephone\b|\bmap\b|\bmaps\b",
    "modern_marketing": r"\bmodern concrete marketing\b|\bready-mix\b|\bcommercial concrete\b",
    "volcanic_tourism": r"\bvolcanic tourism\b|\bvolcano tour\b",
}


def check_text(text: str) -> list[str]:
    violations: list[str] = []
    for name, pattern in NOISE_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            violations.append(name)
    if re.search(r"\bvolcanic\b", text, re.IGNORECASE) and not re.search(
        r"\bRoman concrete\b|\bpozzolana\b|\bpozzolanic\b|\bvolcanic ash\b",
        text,
        re.IGNORECASE,
    ):
        violations.append("generic_volcanic_without_roman_concrete")
    return violations


def validate_chunks(chunks: Iterable[dict[str, object]]) -> dict[str, object]:
    violations: list[str] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id", "<unknown>"))
        if chunk.get("case_id") != "obj_art_003":
            violations.append(f"{chunk_id}: case_id mismatch")
        if chunk.get("reviewer_decision") != "FORMAL_READY_APPROVED":
            violations.append(f"{chunk_id}: reviewer decision is not approved")
        if chunk.get("wrong_context_guard_passed") is not True:
            violations.append(f"{chunk_id}: wrong-context guard failed")
        for field in (
            "is_title_only",
            "is_query_echo",
            "is_generated_echo",
            "is_image_filename_only",
            "is_wrong_context",
            "is_listing_or_travel_planning",
        ):
            if chunk.get(field) is True:
                violations.append(f"{chunk_id}: rejected flag {field}")
        source_text = str(chunk.get("source_backed_text") or "")
        for name in check_text(source_text):
            violations.append(f"{chunk_id}: source text guard {name}")
    if violations:
        raise ObjArt003GuardError("; ".join(violations))
    return {"status": "PASS", "violations": []}
