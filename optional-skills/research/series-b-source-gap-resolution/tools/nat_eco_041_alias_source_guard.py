#!/usr/bin/env python3
"""Source and contamination guard for nat_eco_041 controlled dry-runs."""

from __future__ import annotations

import re
from typing import Iterable


class NatEco041GuardError(ValueError):
    """Raised when nat_eco_041 controlled content fails source guards."""


NOISE_PATTERNS = {
    "sports_noise": r"\bsports?\b|\bball\b|\bteam\b|\bscoreboard\b|\bmatch\b",
    "listing_or_planning": r"\blisting\b|\blistings\b|\bitinerary\b|\bvisitor\b|\btravel planning\b",
    "visitor_services": r"\bhotel\b|\brestaurant\b|\bticket\b|\bbooking\b|\breservation\b|\bopening hours\b",
    "contact_or_wayfinding": r"\baddress\b|\bphone\b|\btelephone\b|\bmap\b|\bmaps\b|\bgetting around\b",
    "wrong_domain_cosmic": r"\binterstellar\b|\bcosmic dust\b|\bplanetary nebula\b",
    "wrong_domain_roman": r"\bRoman concrete\b|\bopus caementicium\b|\bpozzolana\b",
    "wrong_domain_lithic": r"\bflintknapping\b|\bClovis\b|\blithic\b",
}

AEOLIAN_TERMS = re.compile(
    r"\baeolian\b|\bsaltation\b|\bsand transport\b|\bsediment transport\b|\bwind erosion\b|\bsand dune\b",
    re.IGNORECASE,
)


def check_text(text: str) -> list[str]:
    violations: list[str] = []
    for name, pattern in NOISE_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            violations.append(name)
    if re.search(r"\bsand\b", text, re.IGNORECASE) and not AEOLIAN_TERMS.search(text):
        violations.append("generic_sand_without_aeolian_process")
    return violations


def validate_chunks(chunks: Iterable[dict[str, object]]) -> dict[str, object]:
    violations: list[str] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id", "<unknown>"))
        if chunk.get("case_id") != "nat_eco_041":
            violations.append(f"{chunk_id}: case_id mismatch")
        decision = chunk.get("reviewer_decision")
        if decision not in {"FORMAL_READY_APPROVED_WITH_BINDING_CAVEAT", "CONTEXT_READY_APPROVED"}:
            violations.append(f"{chunk_id}: reviewer decision is not approved")
        if chunk.get("wrong_context_guard_passed") is not True:
            violations.append(f"{chunk_id}: wrong-context guard failed")
        for field in (
            "title_only",
            "query_echo",
            "generated_echo",
            "image_filename_only",
            "wrong_domain",
            "listing_or_planning_noise",
            "sports_noise",
        ):
            if chunk.get(field) is True:
                violations.append(f"{chunk_id}: rejected flag {field}")
        source_text = str(chunk.get("source_backed_text") or "")
        if source_text:
            for name in check_text(source_text):
                violations.append(f"{chunk_id}: source text guard {name}")
    if violations:
        raise NatEco041GuardError("; ".join(violations))
    return {"status": "PASS", "violations": []}
