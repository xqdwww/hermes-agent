#!/usr/bin/env python3
"""Old/new comparison schema for Series B official candidate outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from series_b_official_candidate_inputs import CONTROLLED_EVIDENCE_CASES


COMPARATOR_SCHEMA_VERSION = "series_b_official_candidate_comparison.v1"


def build_empty_comparison(*, reason: str = "candidate output not available") -> dict[str, Any]:
    return {
        "schema_version": COMPARATOR_SCHEMA_VERSION,
        "status": "NOT_COMPUTED",
        "reason": reason,
        "old_frozen_baseline": "31/60",
        "candidate_score": None,
        "candidate_passed_cases": None,
        "candidate_failed_cases": None,
        "candidate_vs_frozen_summary": "NOT_COMPUTED",
        "case_deltas": [
            {
                "case_id": case_id,
                "controlled_evidence_classification": "CONTROLLED_DRY_RUN_EVIDENCE_ONLY",
                "candidate_official_status": "NOT_SCORED",
                "delta_vs_frozen": "NOT_COMPUTED",
            }
            for case_id in CONTROLLED_EVIDENCE_CASES
        ],
        "official_baseline_update_performed": False,
    }


def load_candidate_output(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return build_empty_comparison(reason=f"candidate output not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return build_empty_comparison(reason="candidate output root is not an object")
    passed = payload.get("candidate_passed_cases")
    failed = payload.get("candidate_failed_cases")
    score = payload.get("candidate_score")
    return {
        "schema_version": COMPARATOR_SCHEMA_VERSION,
        "status": "COMPUTED_FROM_CANDIDATE_OUTPUT",
        "old_frozen_baseline": "31/60",
        "candidate_score": score,
        "candidate_passed_cases": passed,
        "candidate_failed_cases": failed,
        "candidate_vs_frozen_summary": payload.get("candidate_vs_frozen_summary", "candidate output loaded"),
        "case_deltas": payload.get("case_deltas", []),
        "official_baseline_update_performed": False,
    }


def validate_comparison_schema(payload: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "status",
        "old_frozen_baseline",
        "candidate_score",
        "candidate_passed_cases",
        "candidate_failed_cases",
        "candidate_vs_frozen_summary",
        "case_deltas",
        "official_baseline_update_performed",
    }
    missing = sorted(required - set(payload))
    if missing:
        return {"status": "INVALID", "missing": missing}
    if payload["official_baseline_update_performed"] is not False:
        return {"status": "INVALID", "missing": [], "error": "official baseline update flag must be false"}
    return {"status": "VALID", "missing": []}
