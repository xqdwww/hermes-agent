#!/usr/bin/env python3
"""Alias/source guard wrapper for hist_arch_020."""

from __future__ import annotations

from series_b_generic_controlled_harness import check_case_text, validate_case_chunks


def check_text(text: str) -> list[str]:
    return check_case_text(text, case_id="hist_arch_020")


def validate_chunks(chunks: list[dict]) -> dict[str, object]:
    return validate_case_chunks(chunks, case_id="hist_arch_020")
