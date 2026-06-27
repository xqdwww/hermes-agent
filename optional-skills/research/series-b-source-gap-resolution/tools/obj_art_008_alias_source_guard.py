#!/usr/bin/env python3
"""Alias-caveated guard for obj_art_008 controlled evidence."""

from __future__ import annotations

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_generic_controlled_harness import check_case_text

CASE_ID = "obj_art_008"


def check_text(text: str) -> list[str]:
    """Return guard labels for unsafe obj_art_008 text."""

    violations = check_case_text(text, case_id=CASE_ID)
    lowered = text.lower()
    if "mingan is a real architectural term" in lowered or "mingan proves the object" in lowered:
        violations.append("alias_ambiguity_overclaim")
    if "chinese mingan proves" in lowered or "mongolian mingan proves" in lowered:
        violations.append("wrong_context_overclaim")
    if "generic decorative screen proves the required object" in lowered:
        violations.append("generic_screen_overclaim")
    if "wikipedia_historic_cairo.md counted" in lowered or "wikipedia_islamic_architecture.md counted" in lowered:
        violations.append("rejected_source_counted")
    if "wikipedia api proves professional book body" in lowered:
        violations.append("source_axis_overclaim")
    return sorted(set(violations))


__all__ = ["check_text"]
