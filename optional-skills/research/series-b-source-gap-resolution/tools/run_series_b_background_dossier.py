#!/usr/bin/env python3
"""CLI for the explicit Series B local background dossier runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_background_dossier_runtime import run_background_dossier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a no-write background dossier with the explicit Series B production target.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--production-target", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--no-source-write", action="store_true")
    parser.add_argument("--no-vector-write", action="store_true")
    parser.add_argument("--no-official-baseline-write", action="store_true")
    parser.add_argument("--background-dossier-only", action="store_true")
    parser.add_argument("--no-itinerary", action="store_true")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run-plan-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    status, payload = run_background_dossier(
        query=args.query,
        production_target=args.production_target,
        output_dir=args.output_dir,
        no_source_write=args.no_source_write,
        no_vector_write=args.no_vector_write,
        no_official_baseline_write=args.no_official_baseline_write,
        background_dossier_only=args.background_dossier_only,
        no_itinerary=args.no_itinerary,
        dry_run_plan_only=args.dry_run_plan_only,
        execute=args.execute,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
