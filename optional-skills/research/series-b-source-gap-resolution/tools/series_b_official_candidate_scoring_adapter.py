#!/usr/bin/env python3
"""Fail-closed non-writing scoring adapter for Series B official candidate runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_official_candidate_comparator import compare_candidate_to_frozen, validate_comparison_schema
from series_b_official_candidate_inputs import CONTROLLED_EVIDENCE_CASES, sha256_file
from series_b_official_candidate_no_write_guard import validate_no_write_policy
from series_b_official_scoring_audit import run_candidate_scoring


SCORING_ADAPTER_VERSION = "series_b_official_candidate_scoring_adapter.v1"
READY_INPUT_FIELDS = (
    "official_dataset_path",
    "source_state_manifest_path",
    "scoring_audit_path",
    "frozen_baseline_ledger_path",
)

FALSE_FLAGS = {
    "official_baseline_update_performed": False,
    "official_baseline_write_authorized": False,
    "full_series_b_run_performed": False,
    "production_default_manifest_integration_performed": False,
    "controlled_regression_execution_performed": False,
    "repo_modified": False,
    "commit_created": False,
    "push_performed": False,
    "tag_created": False,
}


def _write_json(output_dir: str | Path, filename: str, payload: dict[str, Any]) -> str:
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def _status(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("status", "missing"))
    return "missing"


def assess_scoring_readiness(input_discovery: dict[str, Any]) -> dict[str, Any]:
    input_status = input_discovery.get("status") or input_discovery.get("result_enum")
    inputs = input_discovery.get("inputs", {})
    missing = list(input_discovery.get("missing_inputs", []))
    partial = list(input_discovery.get("partial_inputs", []))
    for field in READY_INPUT_FIELDS:
        status = _status(inputs.get(field))
        if status == "missing" and field not in missing:
            missing.append(field)
        if status == "partial" and field not in partial:
            partial.append(field)
    if input_status == "OFFICIAL_CANDIDATE_REPO_DIRTY_BLOCKED":
        return {
            "status": "OFFICIAL_CANDIDATE_INPUTS_BLOCKED",
            "ready": False,
            "missing_inputs": sorted(set(missing)),
            "partial_inputs": sorted(set(partial)),
            "blockers": ["repo dirty"],
        }
    if input_status != "OFFICIAL_CANDIDATE_INPUTS_READY" or missing or partial:
        return {
            "status": "OFFICIAL_CANDIDATE_SCORING_ADAPTER_INPUTS_PARTIAL",
            "ready": False,
            "missing_inputs": sorted(set(missing)),
            "partial_inputs": sorted(set(partial)),
            "blockers": sorted(set(missing + partial)),
        }
    return {"status": "OFFICIAL_CANDIDATE_INPUTS_READY", "ready": True, "missing_inputs": [], "partial_inputs": [], "blockers": []}


def build_fixture_candidate_payload(*, passed_cases: list[str], total_cases: int = 60) -> dict[str, Any]:
    failed_count = max(total_cases - len(passed_cases), 0)
    return {
        "adapter_version": SCORING_ADAPTER_VERSION,
        "candidate_score": f"{len(passed_cases)}/{total_cases}",
        "candidate_passed_cases": len(passed_cases),
        "candidate_failed_cases": failed_count,
        "old_frozen_baseline": "31/60",
        "candidate_vs_frozen_summary": "fixture candidate comparison",
        "case_results": [
            {
                "case_id": case_id,
                "candidate_status": "PASS" if case_id in passed_cases else "NOT_SCORED_BY_FIXTURE",
                "controlled_evidence_classification": "CONTROLLED_DRY_RUN_EVIDENCE_ONLY",
            }
            for case_id in CONTROLLED_EVIDENCE_CASES
        ],
        **FALSE_FLAGS,
    }


def run_scoring_adapter(
    *,
    input_discovery: dict[str, Any],
    output_dir: str | Path,
    repo_root: str | Path,
    no_official_write: bool,
    no_production_default: bool,
    no_push: bool,
    no_tag: bool,
    fixture_candidate_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    guard = validate_no_write_policy(
        official_baseline_write_enabled=not no_official_write,
        production_default_enabled=not no_production_default,
        push_enabled=not no_push,
        tag_enabled=not no_tag,
        candidate_mode=True,
        output_dir=output_dir,
        repo_root=repo_root,
        write_targets=[output_dir],
        command="run_series_b_official_candidate.py --execute-candidate --no-official-write --no-production-default --no-push --no-tag",
    )
    readiness = assess_scoring_readiness(input_discovery)
    if not readiness["ready"]:
        payload = {
            "status": readiness["status"],
            "result_enum": readiness["status"],
            "adapter_version": SCORING_ADAPTER_VERSION,
            "candidate_run_executed": False,
            "candidate_score": None,
            "candidate_passed_cases": None,
            "candidate_failed_cases": None,
            "candidate_vs_frozen_summary": "candidate scoring not executed because verified canonical inputs are incomplete",
            "readiness": readiness,
            "guard": guard,
            **FALSE_FLAGS,
        }
        payload["artifact_path"] = _write_json(output_dir, "series_b_official_candidate_execute_attempt.json", payload)
        return payload

    if fixture_candidate_payload is None:
        inputs = input_discovery.get("inputs", {})
        controlled_matrix = inputs.get("controlled_evidence_matrix_path") or inputs.get("final_case_matrix_path")
        if not isinstance(controlled_matrix, dict) or not controlled_matrix.get("path"):
            payload = {
                "status": "OFFICIAL_CANDIDATE_SAFE_RUNNER_NOT_AVAILABLE",
                "result_enum": "OFFICIAL_CANDIDATE_SAFE_RUNNER_NOT_AVAILABLE",
                "adapter_version": SCORING_ADAPTER_VERSION,
                "candidate_run_executed": False,
                "candidate_score": None,
                "candidate_passed_cases": None,
                "candidate_failed_cases": None,
                "candidate_vs_frozen_summary": "verified inputs are ready, but controlled evidence matrix input is missing",
                "readiness": readiness,
                "guard": guard,
                **FALSE_FLAGS,
            }
            payload["artifact_path"] = _write_json(output_dir, "series_b_official_candidate_execute_attempt.json", payload)
            return payload
        payload = run_candidate_scoring(
            dataset_path=inputs["official_dataset_path"]["path"],
            frozen_ledger_path=inputs["frozen_baseline_ledger_path"]["path"],
            controlled_evidence_matrix_path=controlled_matrix["path"],
            output_dir=output_dir,
            repo_root=repo_root,
            no_official_write=no_official_write,
            no_production_default=no_production_default,
            no_push=no_push,
            no_tag=no_tag,
        )
        payload["adapter_version"] = SCORING_ADAPTER_VERSION
        payload["candidate_run_executed"] = True
        payload["readiness"] = readiness
        return payload

    candidate = dict(fixture_candidate_payload)
    if "official_score" in candidate:
        candidate.pop("official_score")
    candidate.update(
        {
            "status": "OFFICIAL_CANDIDATE_EXECUTION_PASS",
            "result_enum": "OFFICIAL_CANDIDATE_EXECUTION_PASS",
            "adapter_version": SCORING_ADAPTER_VERSION,
            "candidate_run_executed": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "guard": guard,
            **FALSE_FLAGS,
        }
    )
    candidate_path = _write_json(output_dir, "series_b_official_candidate_output.json", candidate)
    comparison = compare_candidate_to_frozen(candidate, frozen_baseline=candidate.get("old_frozen_baseline", "31/60"))
    comparison["schema_validation"] = validate_comparison_schema(comparison)
    comparison_path = _write_json(output_dir, "series_b_official_candidate_score_comparison.json", comparison)
    manifest = {
        "status": "PASS",
        "candidate_output": {"path": candidate_path, "sha256": sha256_file(candidate_path)},
        "comparison_output": {"path": comparison_path, "sha256": sha256_file(comparison_path)},
        **FALSE_FLAGS,
    }
    manifest_path = _write_json(output_dir, "series_b_official_candidate_output_manifest.json", manifest)
    candidate["artifact_path"] = candidate_path
    candidate["comparison_path"] = comparison_path
    candidate["output_manifest_path"] = manifest_path
    return candidate
