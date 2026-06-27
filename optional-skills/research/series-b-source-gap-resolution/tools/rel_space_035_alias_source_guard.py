#!/usr/bin/env python3
"""Case guard for rel_space_035 controlled evidence."""

from __future__ import annotations

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_generic_controlled_harness import check_case_text

CASE_ID = "rel_space_035"


def check_text(text: str) -> list[str]:
    """Return guard labels for unsafe rel_space_035 text."""

    violations = check_case_text(text, case_id=CASE_ID)
    lowered = text.lower()
    if "hotel booking" in lowered or "ticket booking" in lowered or "opening hours" in lowered:
        violations.append("listing_or_planning")
    if "travel locator source counts as conceptual evidence" in lowered:
        violations.append("source_axis_overclaim")
    if "acoustic design is confirmed" in lowered or "professional acoustic design" in lowered:
        violations.append("unsupported_acoustics_overclaim")
    if "wikipedia is professional book evidence" in lowered or "le monde is professional book evidence" in lowered:
        violations.append("professional_book_axis_overclaim")
    return sorted(set(violations))


__all__ = ["check_text"]
