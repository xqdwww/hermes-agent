#!/usr/bin/env python3
"""Explicit non-writing Series B official candidate runner wrapper."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from series_b_official_candidate_runner import run_mode

REPO_ROOT = Path(__file__).resolve().parents[4]
EXPECTED_BRANCH = "travel-series-b-validation"


def _git_text(args: list[str]) -> str:
    proc = subprocess.run(args, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return proc.stdout.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Non-writing official Series B candidate runner package. This wrapper never writes official baseline state."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--discover-only", action="store_true")
    modes.add_argument("--verify-inputs-only", action="store_true")
    modes.add_argument("--dry-run-plan-only", action="store_true")
    modes.add_argument("--execute-candidate", action="store_true")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--no-official-write", action="store_true", required=True)
    parser.add_argument("--no-production-default", action="store_true", required=True)
    parser.add_argument("--no-push", action="store_true", required=True)
    parser.add_argument("--no-tag", action="store_true", required=True)
    return parser


def _mode(args: argparse.Namespace) -> str:
    if args.discover_only:
        return "discover-only"
    if args.verify_inputs_only:
        return "verify-inputs-only"
    if args.dry_run_plan_only:
        return "dry-run-plan-only"
    return "execute-candidate"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    branch = _git_text(["git", "branch", "--show-current"])
    head = _git_text(["git", "rev-parse", "HEAD"])
    status, payload = run_mode(
        _mode(args),
        repo_path=REPO_ROOT,
        branch=branch or EXPECTED_BRANCH,
        head=head,
        output_dir=args.output_dir,
        no_official_write=args.no_official_write,
        no_production_default=args.no_production_default,
        no_push=args.no_push,
        no_tag=args.no_tag,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
