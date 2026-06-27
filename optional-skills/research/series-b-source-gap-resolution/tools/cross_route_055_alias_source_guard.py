#!/usr/bin/env python3
"""Alias/source guard wrapper for cross_route_055."""

from __future__ import annotations

from series_b_generic_controlled_harness import check_case_text, validate_case_chunks


def check_text(text: str) -> list[str]:
    violations = check_case_text(text, case_id="cross_route_055")
    lowered = text.lower()
    if "computer proxy" in lowered or "proxy server" in lowered or "generic proxy" in lowered:
        violations.append("proxy_trade_contamination")
    return sorted(set(violations))


def validate_chunks(chunks: list[dict]) -> dict[str, object]:
    return validate_case_chunks(chunks, case_id="cross_route_055")
