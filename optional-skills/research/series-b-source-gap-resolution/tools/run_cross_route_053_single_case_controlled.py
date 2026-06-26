#!/usr/bin/env python3
"""Explicit-only cross_route_053 single-case controlled harness."""

from __future__ import annotations

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_generic_controlled_harness import main_for_case


if __name__ == "__main__":
    raise SystemExit(main_for_case("cross_route_053"))
