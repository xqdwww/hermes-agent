#!/usr/bin/env python3
"""Case guard for rel_space_034 controlled evidence."""

from __future__ import annotations

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_generic_controlled_harness import check_case_text

CASE_ID = "rel_space_034"


def check_text(text: str) -> list[str]:
    """Return guard labels for unsafe rel_space_034 text."""

    violations = check_case_text(text, case_id=CASE_ID)
    lowered = text.lower()
    if "hotel booking" in lowered or "ticket booking" in lowered or "opening hours" in lowered:
        violations.append("listing_or_planning")
    if "confirmed astronomical program" in lowered or "proves astronomical alignment" in lowered:
        violations.append("unsupported_astronomical_overclaim")
    if "orientation/cardinal" not in lowered and "cardinal planning" not in lowered and "oriented to true north" not in lowered:
        violations.append("alignment_orientation_caveat_missing")
    return sorted(set(violations))


__all__ = ["check_text"]
