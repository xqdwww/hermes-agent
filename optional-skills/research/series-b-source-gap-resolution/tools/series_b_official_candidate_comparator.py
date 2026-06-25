#!/usr/bin/env python3
"""Old/new comparison schema for Series B official candidate outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from series_b_official_candidate_inputs import CONTROLLED_EVIDENCE_CASES


COMPARATOR_SCHEMA_VERSION = "series_b_official_candidate_comparison.v1"


def _parse_score(score: str | None) -> tuple[int | None, int | None]:
    if not score or "/" not in score:
        return None, None
    left, right = score.split("/", 1)
    try:
        return int(left.strip()), int(right.strip())
    except ValueError:
        return None, None


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


def compare_candidate_to_frozen(candidate_payload: dict[str, Any], *, frozen_baseline: str = "31/60") -> dict[str, Any]:
    candidate_score = candidate_payload.get("candidate_score")
    candidate_passed = candidate_payload.get("candidate_passed_cases")
    candidate_failed = candidate_payload.get("candidate_failed_cases")
    frozen_passed, frozen_total = _parse_score(frozen_baseline)
    candidate_score_passed, candidate_score_total = _parse_score(candidate_score)
    passed_for_delta = candidate_passed if isinstance(candidate_passed, int) else candidate_score_passed
    if passed_for_delta is None or frozen_passed is None:
        summary = "candidate/frozen delta not computed"
    else:
        delta = passed_for_delta - frozen_passed
        sign = "+" if delta >= 0 else ""
        total = candidate_score_total or frozen_total or 60
        summary = f"candidate {passed_for_delta}/{total} vs frozen {frozen_baseline}: {sign}{delta} pass-count delta"
    case_results = candidate_payload.get("case_results") or []
    case_deltas = []
    for item in case_results:
        if not isinstance(item, dict):
            continue
        case_deltas.append(
            {
                "case_id": item.get("case_id"),
                "controlled_evidence_classification": item.get(
                    "controlled_evidence_classification", "CONTROLLED_DRY_RUN_EVIDENCE_ONLY"
                ),
                "candidate_official_status": item.get("candidate_status", "NOT_SCORED"),
                "delta_vs_frozen": item.get("delta_vs_frozen", "CANDIDATE_ONLY"),
            }
        )
    return {
        "schema_version": COMPARATOR_SCHEMA_VERSION,
        "status": "COMPUTED_FROM_CANDIDATE_OUTPUT",
        "old_frozen_baseline": frozen_baseline,
        "candidate_score": candidate_score,
        "candidate_passed_cases": candidate_passed,
        "candidate_failed_cases": candidate_failed,
        "candidate_vs_frozen_summary": summary,
        "case_deltas": case_deltas,
        "official_baseline_update_performed": False,
    }


def load_candidate_output(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return build_empty_comparison(reason=f"candidate output not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return build_empty_comparison(reason="candidate output root is not an object")
    return compare_candidate_to_frozen(payload, frozen_baseline=payload.get("old_frozen_baseline", "31/60"))


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
    if "official_score" in payload:
        return {"status": "INVALID", "missing": [], "error": "candidate comparison must not expose official_score"}
    return {"status": "VALID", "missing": []}
