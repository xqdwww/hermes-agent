#!/usr/bin/env python3
"""Alias/source guard wrapper for hist_arch_022."""

from __future__ import annotations

from series_b_generic_controlled_harness import check_case_text, validate_case_chunks


def check_text(text: str) -> list[str]:
    violations = check_case_text(text, case_id="hist_arch_022")
    lowered = text.lower()
    if "cao zhi" in lowered and "tribute grain" not in lowered and "grain transport" not in lowered:
        violations.append("caozhi_spacing_ambiguity")
    if "materials_book" in lowered and "source-backed" in lowered and "not overclaimed" not in lowered:
        violations.append("materials_book_overclaim")
    return sorted(set(violations))


def validate_chunks(chunks: list[dict]) -> dict[str, object]:
    return validate_case_chunks(chunks, case_id="hist_arch_022")
