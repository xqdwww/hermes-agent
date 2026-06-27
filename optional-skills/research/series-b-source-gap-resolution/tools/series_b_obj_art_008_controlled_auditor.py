#!/usr/bin/env python3
"""Explicit obj_art_008 controlled auditor wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from series_b_generic_controlled_harness import audit_controlled_dossier

CASE_ID = "obj_art_008"


def audit(
    *,
    raw_dossier_path: str | Path,
    source_packet_path: str | Path,
    handoff_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Audit obj_art_008 without production defaults, baseline side effects, or alias overclaim."""

    return audit_controlled_dossier(
        case_id=CASE_ID,
        raw_dossier_path=raw_dossier_path,
        source_packet_path=source_packet_path,
        handoff_manifest_path=handoff_manifest_path,
        output_dir=output_dir,
    )


__all__ = ["audit"]
