#!/usr/bin/env python3
"""Explicit adv_trap_059 source-grounded builder wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from series_b_generic_controlled_harness import build_controlled_dossier

CASE_ID = "adv_trap_059"


def build(*, source_packet_path: str | Path, handoff_manifest_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Build an adv_trap_059 controlled dossier from an explicit handoff packet only."""

    return build_controlled_dossier(
        case_id=CASE_ID,
        source_packet_path=source_packet_path,
        handoff_manifest_path=handoff_manifest_path,
        output_dir=output_dir,
    )


__all__ = ["build"]
