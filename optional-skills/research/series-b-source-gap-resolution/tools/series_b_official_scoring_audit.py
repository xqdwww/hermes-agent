#!/usr/bin/env python3
"""Candidate-only scoring audit for the Series B official input layer.

This module computes a non-writing candidate delta from the frozen 31/60
ledger and sealed controlled-evidence matrix. It does not run the production
builder, does not call production default retrieval, and cannot write official
baseline state.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_official_candidate_comparator import compare_candidate_to_frozen, validate_comparison_schema
from series_b_official_candidate_inputs import sha256_file
from series_b_official_candidate_no_write_guard import validate_no_write_policy
from series_b_official_input_layer import validate_frozen_ledger, validate_official_dataset


SCORING_AUDIT_VERSION = "series_b_official_scoring_audit.v1"
RESULT_PASS = "OFFICIAL_CANDIDATE_EXECUTION_PASS"
RESULT_PARTIAL = "OFFICIAL_CANDIDATE_EXECUTION_PARTIAL"
RESULT_SEMANTICS_NOT_CANONICAL = "OFFICIAL_SCORING_SEMANTICS_NOT_CANONICAL"

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


class OfficialScoringAuditError(ValueError):
    """Raised when candidate-only scoring cannot be performed safely."""


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OfficialScoringAuditError(f"JSON root must be object: {target}")
    return payload


def _write_json(output_dir: str | Path, filename: str, payload: dict[str, Any]) -> str:
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def _write_text(output_dir: str | Path, filename: str, text: str) -> str:
    target = Path(output_dir).expanduser().resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename
    path.write_text(text, encoding="utf-8")
    return str(path)


def _case_id(row: dict[str, Any]) -> str:
    return str(row.get("case_id") or row.get("id") or "").strip()


def load_controlled_evidence_matrix(path: str | Path) -> dict[str, Any]:
    payload = _load_json(path)
    if payload.get("classification") != "CONTROLLED_DRY_RUN_EVIDENCE_ONLY":
        raise OfficialScoringAuditError("controlled evidence matrix must preserve CONTROLLED_DRY_RUN_EVIDENCE_ONLY")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise OfficialScoringAuditError("controlled evidence matrix cases missing")
    controlled: dict[str, dict[str, Any]] = {}
    for item in cases:
        if not isinstance(item, dict):
            continue
        case_id = _case_id(item)
        if not case_id:
            continue
        if item.get("official_score_improvement") is True:
            raise OfficialScoringAuditError(f"controlled evidence case claims official score improvement: {case_id}")
        if item.get("official_baseline_update_performed") is not False:
            raise OfficialScoringAuditError(f"controlled evidence case has baseline update flag: {case_id}")
        result = str(item.get("case_result") or "")
        archive = str(item.get("archive_trace_status") or "")
        if "PASS" in result and archive.startswith("PASS"):
            controlled[case_id] = item
    return {
        "status": "PASS",
        "matrix_path": str(Path(path)),
        "matrix_sha256": sha256_file(path),
        "controlled_pass_cases": controlled,
        "controlled_case_count": len(controlled),
    }


def build_candidate_delta(
    *,
    dataset_path: str | Path,
    frozen_ledger_path: str | Path,
    controlled_evidence_matrix_path: str | Path,
) -> dict[str, Any]:
    dataset_validation = validate_official_dataset(dataset_path)
    dataset = _load_json(dataset_path)
    dataset_cases = dataset["cases"]
    dataset_ids = [_case_id(row) for row in dataset_cases]
    ledger_validation = validate_frozen_ledger(frozen_ledger_path, dataset_ids)
    ledger = _load_json(frozen_ledger_path)
    matrix = load_controlled_evidence_matrix(controlled_evidence_matrix_path)

    frozen_passed = set(ledger["passed_cases"])
    frozen_failed = set(ledger["failed_cases"])
    controlled = matrix["controlled_pass_cases"]
    controlled_pass_ids = set(controlled)
    newly_passed = sorted(controlled_pass_ids & frozen_failed)
    already_frozen_pass = sorted(controlled_pass_ids & frozen_passed)
    out_of_dataset = sorted(controlled_pass_ids - set(dataset_ids))
    if out_of_dataset:
        raise OfficialScoringAuditError(f"controlled evidence contains cases outside official dataset: {out_of_dataset}")

    candidate_passed_count = int(ledger["pass_count"]) + len(newly_passed)
    candidate_failed_count = len(dataset_ids) - candidate_passed_count
    case_results: list[dict[str, Any]] = []
    for row in dataset_cases:
        case_id = _case_id(row)
        controlled_item = controlled.get(case_id)
        if case_id in newly_passed:
            status = "CANDIDATE_CONTROLLED_PASS_DELTA"
            delta = "FAIL_TO_CANDIDATE_PASS"
        elif case_id in already_frozen_pass:
            status = "CONTROLLED_EVIDENCE_ALREADY_FROZEN_PASS"
            delta = "NO_PASS_COUNT_DELTA"
        elif case_id in frozen_passed:
            status = "FROZEN_PASS_UNCHANGED"
            delta = "NO_CHANGE"
        else:
            status = "FROZEN_FAIL_UNCHANGED"
            delta = "NO_CONTROLLED_PASS_EVIDENCE"
        case_results.append(
            {
                "case_id": case_id,
                "candidate_status": status,
                "delta_vs_frozen": delta,
                "controlled_evidence_classification": "CONTROLLED_DRY_RUN_EVIDENCE_ONLY",
                "controlled_case_result": controlled_item.get("case_result") if controlled_item else None,
                "caveats": controlled_item.get("caveats") if controlled_item else [],
            }
        )

    return {
        "status": RESULT_PASS,
        "result_enum": RESULT_PASS,
        "scoring_audit_version": SCORING_AUDIT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_score": f"{candidate_passed_count}/{len(dataset_ids)}",
        "candidate_passed_cases": candidate_passed_count,
        "candidate_failed_cases": candidate_failed_count,
        "old_frozen_baseline": ledger["official_baseline_score"],
        "candidate_vs_frozen_summary": (
            f"candidate {candidate_passed_count}/{len(dataset_ids)} vs frozen "
            f"{ledger['official_baseline_score']}: +{len(newly_passed)} pass-count delta "
            "from controlled evidence; candidate-only, no official score write"
        ),
        "newly_passed_candidate_delta_cases": newly_passed,
        "controlled_cases_already_frozen_pass": already_frozen_pass,
        "case_results": case_results,
        "dataset_validation": dataset_validation,
        "frozen_ledger_validation": ledger_validation,
        "controlled_evidence_matrix_validation": {
            "status": matrix["status"],
            "controlled_case_count": matrix["controlled_case_count"],
            "matrix_path": matrix["matrix_path"],
            "matrix_sha256": matrix["matrix_sha256"],
        },
        "classification": "CANDIDATE_ONLY_NO_BASELINE_WRITE",
        "full_series_b_run_performed": False,
        "notes": [
            "Candidate scoring uses the canonical 60-case dataset and frozen 31/60 ledger.",
            "Controlled dry-run evidence is used only as candidate delta evidence, not as an official score.",
            "No production default builder/retrieval path is called by this scoring audit.",
        ],
        **FALSE_FLAGS,
    }


def run_candidate_scoring(
    *,
    dataset_path: str | Path,
    frozen_ledger_path: str | Path,
    controlled_evidence_matrix_path: str | Path,
    output_dir: str | Path,
    repo_root: str | Path,
    no_official_write: bool,
    no_production_default: bool,
    no_push: bool,
    no_tag: bool,
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
        command="series_b_official_scoring_audit.py --candidate-only --no-official-write --no-production-default",
    )
    payload = build_candidate_delta(
        dataset_path=dataset_path,
        frozen_ledger_path=frozen_ledger_path,
        controlled_evidence_matrix_path=controlled_evidence_matrix_path,
    )
    payload["guard"] = guard
    candidate_path = _write_json(output_dir, "series_b_official_candidate_output.json", payload)
    comparison = compare_candidate_to_frozen(payload, frozen_baseline=payload["old_frozen_baseline"])
    comparison["schema_validation"] = validate_comparison_schema(comparison)
    comparison_path = _write_json(output_dir, "series_b_official_candidate_score_comparison.json", comparison)
    delta_matrix = {
        "schema_version": "series_b_official_candidate_case_delta_matrix.v1",
        "status": "PASS",
        "case_count": len(payload["case_results"]),
        "newly_passed_candidate_delta_cases": payload["newly_passed_candidate_delta_cases"],
        "case_deltas": payload["case_results"],
        **FALSE_FLAGS,
    }
    delta_path = _write_json(output_dir, "series_b_official_candidate_case_delta_matrix.json", delta_matrix)
    comparison_md = "\n".join(
        [
            "# Series B official candidate score comparison",
            "",
            f"candidate_score: `{payload['candidate_score']}`",
            f"old_frozen_baseline: `{payload['old_frozen_baseline']}`",
            f"summary: {payload['candidate_vs_frozen_summary']}",
            "",
            "This is a candidate-only comparison. No official baseline ledger or score was updated.",
            "",
        ]
    )
    comparison_md_path = _write_text(output_dir, "series_b_official_candidate_score_comparison.md", comparison_md)
    manifest = {
        "schema_version": "series_b_official_candidate_output_manifest.v1",
        "status": "PASS",
        "candidate_output": {"path": candidate_path, "sha256": sha256_file(candidate_path)},
        "comparison_output": {"path": comparison_path, "sha256": sha256_file(comparison_path)},
        "comparison_markdown": {"path": comparison_md_path, "sha256": sha256_file(comparison_md_path)},
        "case_delta_matrix": {"path": delta_path, "sha256": sha256_file(delta_path)},
        **FALSE_FLAGS,
    }
    manifest_path = _write_json(output_dir, "series_b_official_candidate_output_manifest.json", manifest)
    payload["artifact_path"] = candidate_path
    payload["comparison_path"] = comparison_path
    payload["comparison_markdown_path"] = comparison_md_path
    payload["case_delta_matrix_path"] = delta_path
    payload["output_manifest_path"] = manifest_path
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Candidate-only Series B official scoring audit.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--frozen-ledger", required=True)
    parser.add_argument("--controlled-evidence-matrix", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--no-official-write", action="store_true", required=True)
    parser.add_argument("--no-production-default", action="store_true", required=True)
    parser.add_argument("--no-push", action="store_true", required=True)
    parser.add_argument("--no-tag", action="store_true", required=True)
    args = parser.parse_args(argv)
    payload = run_candidate_scoring(
        dataset_path=args.dataset,
        frozen_ledger_path=args.frozen_ledger,
        controlled_evidence_matrix_path=args.controlled_evidence_matrix,
        output_dir=args.output_dir,
        repo_root=args.repo_root,
        no_official_write=args.no_official_write,
        no_production_default=args.no_production_default,
        no_push=args.no_push,
        no_tag=args.no_tag,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

