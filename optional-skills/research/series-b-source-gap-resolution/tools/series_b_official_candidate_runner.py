#!/usr/bin/env python3
"""Non-writing Series B official candidate runner wrapper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from series_b_official_candidate_comparator import build_empty_comparison, validate_comparison_schema
from series_b_official_candidate_inputs import discover_existing_primitives, resolve_official_candidate_inputs
from series_b_official_candidate_no_write_guard import OfficialCandidateGuardError, validate_no_write_policy
from series_b_official_candidate_scoring_adapter import assess_scoring_readiness, run_scoring_adapter


EXECUTION_FALSE_FLAGS = {
    "official_baseline_update_performed": False,
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


def _guard(
    *,
    output_dir: str | Path,
    repo_root: str | Path,
    no_official_write: bool,
    no_production_default: bool,
    no_push: bool,
    no_tag: bool,
    command: str | None = None,
) -> dict[str, Any]:
    return validate_no_write_policy(
        official_baseline_write_enabled=not no_official_write,
        production_default_enabled=not no_production_default,
        push_enabled=not no_push,
        tag_enabled=not no_tag,
        candidate_mode=True,
        output_dir=output_dir,
        repo_root=repo_root,
        write_targets=[output_dir],
        command=command,
    )


def discover_only(
    *,
    repo_path: str | Path,
    branch: str,
    head: str,
    output_dir: str | Path,
    no_official_write: bool,
    no_production_default: bool,
    no_push: bool,
    no_tag: bool,
) -> dict[str, Any]:
    guard = _guard(
        output_dir=output_dir,
        repo_root=repo_path,
        no_official_write=no_official_write,
        no_production_default=no_production_default,
        no_push=no_push,
        no_tag=no_tag,
    )
    inputs = resolve_official_candidate_inputs(
        repo_path=repo_path,
        branch=branch,
        head=head,
        output_dir=output_dir,
        require_clean_repo=True,
    )
    primitives = discover_existing_primitives(repo_path)
    payload = {
        "status": "OFFICIAL_CANDIDATE_DISCOVER_ONLY_PASS",
        "result_enum": "OFFICIAL_CANDIDATE_DISCOVER_ONLY_PASS",
        "guard": guard,
        "input_discovery": inputs,
        "existing_primitives": primitives,
        **EXECUTION_FALSE_FLAGS,
    }
    payload["artifact_path"] = _write_json(output_dir, "series_b_official_candidate_discover_only.json", payload)
    return payload


def verify_inputs_only(
    *,
    repo_path: str | Path,
    branch: str,
    head: str,
    output_dir: str | Path,
    no_official_write: bool,
    no_production_default: bool,
    no_push: bool,
    no_tag: bool,
) -> dict[str, Any]:
    guard = _guard(
        output_dir=output_dir,
        repo_root=repo_path,
        no_official_write=no_official_write,
        no_production_default=no_production_default,
        no_push=no_push,
        no_tag=no_tag,
    )
    inputs = resolve_official_candidate_inputs(
        repo_path=repo_path,
        branch=branch,
        head=head,
        output_dir=output_dir,
        require_clean_repo=True,
    )
    payload = {
        "status": "OFFICIAL_CANDIDATE_VERIFY_INPUTS_PASS",
        "result_enum": "OFFICIAL_CANDIDATE_VERIFY_INPUTS_PASS",
        "guard": guard,
        "inputs_status": inputs["status"],
        "official_candidate_execution_ready": inputs["official_candidate_execution_ready"],
        "missing_inputs": inputs["missing_inputs"],
        "partial_inputs": inputs["partial_inputs"],
        "input_discovery": inputs,
        **EXECUTION_FALSE_FLAGS,
    }
    payload["artifact_path"] = _write_json(output_dir, "series_b_official_candidate_verify_inputs.json", payload)
    return payload


def dry_run_plan_only(
    *,
    repo_path: str | Path,
    branch: str,
    head: str,
    output_dir: str | Path,
    no_official_write: bool,
    no_production_default: bool,
    no_push: bool,
    no_tag: bool,
) -> dict[str, Any]:
    guard = _guard(
        output_dir=output_dir,
        repo_root=repo_path,
        no_official_write=no_official_write,
        no_production_default=no_production_default,
        no_push=no_push,
        no_tag=no_tag,
    )
    inputs = resolve_official_candidate_inputs(
        repo_path=repo_path,
        branch=branch,
        head=head,
        output_dir=output_dir,
        require_clean_repo=True,
    )
    readiness = assess_scoring_readiness(inputs)
    comparison = build_empty_comparison(reason="candidate execution not run in dry-run-plan-only mode")
    payload = {
        "status": "OFFICIAL_CANDIDATE_DRY_RUN_PLAN_PASS",
        "result_enum": "OFFICIAL_CANDIDATE_DRY_RUN_PLAN_PASS",
        "guard": guard,
        "input_discovery": inputs,
        "scoring_adapter_readiness": readiness,
        "comparison_schema_validation": validate_comparison_schema(comparison),
        "candidate_execution_plan": {
            "execute_candidate_available": readiness["ready"],
            "execute_candidate_result_if_called": "OFFICIAL_CANDIDATE_SAFE_RUNNER_NOT_AVAILABLE"
            if readiness["ready"]
            else "OFFICIAL_CANDIDATE_SCORING_ADAPTER_INPUTS_PARTIAL",
            "required_before_execution": readiness["blockers"],
            "official_baseline_write_authorized": False,
            "production_default_integration_authorized": False,
        },
        "comparison_template": comparison,
        **EXECUTION_FALSE_FLAGS,
    }
    payload["artifact_path"] = _write_json(output_dir, "series_b_official_candidate_dry_run_plan.json", payload)
    return payload


def execute_candidate(
    *,
    repo_path: str | Path,
    branch: str,
    head: str,
    output_dir: str | Path,
    no_official_write: bool,
    no_production_default: bool,
    no_push: bool,
    no_tag: bool,
) -> dict[str, Any]:
    inputs = resolve_official_candidate_inputs(
        repo_path=repo_path,
        branch=branch,
        head=head,
        output_dir=output_dir,
        require_clean_repo=True,
    )
    payload = run_scoring_adapter(
        input_discovery=inputs,
        output_dir=output_dir,
        repo_root=repo_path,
        no_official_write=no_official_write,
        no_production_default=no_production_default,
        no_push=no_push,
        no_tag=no_tag,
    )
    payload["input_discovery"] = inputs
    return payload


def run_mode(mode: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
    try:
        if mode == "discover-only":
            return 0, discover_only(**kwargs)
        if mode == "verify-inputs-only":
            return 0, verify_inputs_only(**kwargs)
        if mode == "dry-run-plan-only":
            return 0, dry_run_plan_only(**kwargs)
        if mode == "execute-candidate":
            payload = execute_candidate(**kwargs)
            return (0 if payload.get("result_enum") == "OFFICIAL_CANDIDATE_EXECUTION_PASS" else 2), payload
    except OfficialCandidateGuardError as exc:
        return 2, {
            "status": exc.error_code,
            "result_enum": exc.error_code,
            "message": exc.message,
            **EXECUTION_FALSE_FLAGS,
        }
    return 2, {
        "status": "OFFICIAL_CANDIDATE_INPUTS_BLOCKED",
        "result_enum": "OFFICIAL_CANDIDATE_INPUTS_BLOCKED",
        "message": f"unknown mode: {mode}",
        **EXECUTION_FALSE_FLAGS,
    }
