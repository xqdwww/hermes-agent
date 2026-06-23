#!/usr/bin/env python3
"""Alias and source-contamination guard for rel_space_029."""

from __future__ import annotations

import re
from typing import Any

ALLOWED_CONTEXT_TERMS = {
    "synagogue",
    "torah",
    "torah reading",
    "jewish",
    "liturgy",
    "liturgical",
    "aron",
    "ark",
    "kodesh",
    "sacred space",
    "congregation",
}

REJECT_PATTERNS = {
    "standalone bema": re.compile(r"\bbema\b", re.IGNORECASE),
    "Christian / Byzantine / Athenian bema": re.compile(
        r"\b(christian|byzantine|athenian|athens|basilica)\b.{0,80}\bbema\b|"
        r"\bbema\b.{0,80}\b(christian|byzantine|athenian|athens|basilica)\b",
        re.IGNORECASE,
    ),
    "church apse": re.compile(r"\bchurch\s+apse\b|\bapse\b.{0,80}\bchurch\b", re.IGNORECASE),
    "public-speaking platform": re.compile(
        r"\bpublic[- ]speaking platform\b|\bspeaker'?s platform\b", re.IGNORECASE
    ),
    "image filename evidence": re.compile(r"\.(jpg|jpeg|png|gif|webp|tif|tiff)\b", re.IGNORECASE),
    "title-only evidence": re.compile(r"\btitle[-_ ]only\b|^title:", re.IGNORECASE),
    "query echo": re.compile(r"\bquery[-_ ]echo\b|^query:", re.IGNORECASE),
    "generated echo": re.compile(r"\bgenerated[-_ ]echo\b|^generated:", re.IGNORECASE),
    "modern event noise": re.compile(r"\b(ticketed event|conference|concert|festival)\b", re.IGNORECASE),
    "travel/listing/planning noise": re.compile(
        r"\b(opening hours|tickets?|booking|reservation|hotel|restaurant|"
        r"tripadvisor|yelp|qyer|itinerary|transport|bus route)\b",
        re.IGNORECASE,
    ),
}

METADATA_REJECT_FLAGS = {
    "is_title_only": "title-only evidence",
    "is_query_echo": "query echo",
    "is_generated_echo": "generated echo",
    "is_image_filename_only": "image filename evidence",
    "is_wrong_context_bema": "standalone bema",
    "is_listing_or_travel_planning": "travel/listing/planning noise",
}


class AliasSourceGuardError(ValueError):
    """Raised when alias/source guard checks fail."""


def _has_allowed_context(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ALLOWED_CONTEXT_TERMS)


def check_text(text: str) -> list[str]:
    violations: list[str] = []
    text = text or ""
    lowered = text.lower()

    for reason, pattern in REJECT_PATTERNS.items():
        if pattern.search(text):
            violations.append(reason)

    if "reading platform" in lowered and not _has_allowed_context(text):
        violations.append("generic platform")

    generic_platform = re.search(r"\bplatform\b", text, re.IGNORECASE)
    if generic_platform and "reading platform" not in lowered and not _has_allowed_context(text):
        violations.append("generic platform")

    return sorted(set(violations))


def check_chunk_metadata(chunk: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    for field, reason in METADATA_REJECT_FLAGS.items():
        if chunk.get(field) is True:
            violations.append(reason)

    text_fields: list[str] = []
    for key in ("chunk_text", "text", "source_title"):
        value = chunk.get(key)
        if isinstance(value, str):
            text_fields.append(value)
    for key in ("supports_terms", "supports_sections"):
        value = chunk.get(key)
        if isinstance(value, list):
            text_fields.extend(str(item) for item in value)
    violations.extend(check_text(" ".join(text_fields)))
    return sorted(set(violations))


def validate_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    chunk_reports: list[dict[str, Any]] = []
    violations: list[str] = []
    for chunk in chunks:
        chunk_violations = check_chunk_metadata(chunk)
        chunk_reports.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "violations": chunk_violations,
            }
        )
        violations.extend(
            f"{chunk.get('chunk_id', '<unknown>')}: {violation}" for violation in chunk_violations
        )

    report = {
        "case_id": "rel_space_029",
        "status": "PASS" if not violations else "FAIL",
        "violations": violations,
        "chunk_reports": chunk_reports,
        "allow": [
            "exact bimah",
            "reading platform only in synagogue / Torah reading context",
            "Torah ark",
            "Aron ha-Kodesh",
            "synagogue sacred-space orientation",
            "source-backed Jewish liturgical / architectural context",
        ],
        "reject": sorted(REJECT_PATTERNS),
    }
    if violations:
        raise AliasSourceGuardError("; ".join(violations))
    return report
