#!/usr/bin/env python3
"""CLI for the dedicated full non-destructive Series B sanity runner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_full_sanity_runner import run_full_sanity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dedicated full non-destructive Series B production sanity runner.")
    parser.add_argument("--check-baseline", action="store_true")
    parser.add_argument("--check-production-target", action="store_true")
    parser.add_argument("--check-60case-dataset", action="store_true")
    parser.add_argument("--check-12case-trace", action="store_true")
    parser.add_argument("--dry-run-one-case", action="store_true")
    parser.add_argument("--dry-run-60case-plan", action="store_true")
    parser.add_argument("--check-no-mutation", action="store_true")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--no-source-write", action="store_true")
    parser.add_argument("--no-vector-write", action="store_true")
    parser.add_argument("--no-official-baseline-write", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--no-tag", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    status, payload = run_full_sanity(
        output_dir=args.output_dir,
        check_baseline_flag=args.check_baseline,
        check_production_target_flag=args.check_production_target,
        check_60case_dataset_flag=args.check_60case_dataset,
        check_12case_trace_flag=args.check_12case_trace,
        dry_run_one_case_flag=args.dry_run_one_case,
        dry_run_60case_plan_flag=args.dry_run_60case_plan,
        check_no_mutation_flag=args.check_no_mutation,
        no_source_write=args.no_source_write,
        no_vector_write=args.no_vector_write,
        no_official_baseline_write=args.no_official_baseline_write,
        no_push=args.no_push,
        no_tag=args.no_tag,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
