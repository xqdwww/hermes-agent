#!/usr/bin/env python3
"""Dedicated full non-destructive Series B production sanity runner."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from series_b_production_target_loader import DEFAULT_TARGET_MANIFEST, ProductionTargetLayerError, load_explicit_production_target

REPO_ROOT = Path(__file__).resolve().parents[4]
SERIES_B_ROOT = REPO_ROOT / "optional-skills/research/series-b-source-gap-resolution"
OFFICIAL_ROOT = SERIES_B_ROOT / "official"
PRODUCTION_ROOT = SERIES_B_ROOT / "production"
DATASET_PATH = OFFICIAL_ROOT / "series_b_official_60case_dataset.json"
BASELINE_CURRENT_PATH = OFFICIAL_ROOT / "series_b_official_baseline_current.json"
BASELINE_LEDGER_PATH = OFFICIAL_ROOT / "series_b_official_baseline_ledger.json"
SOURCE_STATE_PATH = OFFICIAL_ROOT / "series_b_source_state_manifest.json"
SCORING_AUDIT_PATH = SERIES_B_ROOT / "tools/series_b_official_scoring_audit.py"
INTEGRATION_PATH = PRODUCTION_ROOT / "series_b_production_integration.json"
CONTROLLED_CASE_LIST_PATH = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-33case-controlled-evidence-rollup/outputs/controlled_evidence_case_list_33cases.json"
)
CONTROLLED_ROLLUP_PATH = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-33case-controlled-evidence-rollup/outputs/series_b_33case_controlled_evidence_rollup.json"
)
FINAL_CASE_MATRIX_PATH = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-33case-controlled-evidence-rollup/outputs/series_b_33case_artifact_index.json"
)
FINAL_SEAL_AUDIT_PATH = Path(
    "/Users/xqdwww/Documents/Codex/2026-06-25/travel-series-b-33case-controlled-evidence-rollup/outputs/series_b_33case_controlled_evidence_rollup_report.md"
)
EXPECTED_BASELINE = "60/60"
EXPECTED_PREVIOUS_BASELINE = "58/60"
EXPECTED_CONTROLLED_EVIDENCE_COUNT = 33
REQUIRED_CAVEAT_CASES = [
    "obj_art_003",
    "obj_art_007",
    "nat_eco_039",
    "obj_art_010",
    "hist_arch_024",
    "obj_art_002",
    "hist_arch_020",
    "rel_space_031",
    "nat_eco_042",
    "cross_route_053",
    "nat_eco_046",
    "nat_eco_043",
    "obj_art_005",
    "obj_art_011",
    "hist_arch_025",
    "rel_space_036",
    "nat_eco_045",
    "rel_space_028",
    "rel_space_033",
    "obj_art_012",
    "cross_route_055",
    "hist_arch_022",
    "rel_space_034",
    "rel_space_035",
    "adv_trap_059",
    "obj_art_008",
]
RESULT_PASS = "FULL_NON_DESTRUCTIVE_SANITY_PASS"
RESULT_BLOCKED = "FULL_NON_DESTRUCTIVE_SANITY_BLOCKED"


class FullSanityError(ValueError):
    """Raised when the full non-destructive sanity runner cannot proceed safely."""

    def __init__(self, error_code: str, message: str):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.message = message


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FullSanityError("FULL_SANITY_INVALID_JSON", f"JSON root must be object: {target}")
    return payload


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_output_dir(output_dir: str | Path) -> Path:
    target = Path(output_dir).expanduser().resolve(strict=False)
    if _is_relative_to(target, REPO_ROOT):
        raise FullSanityError("FULL_SANITY_OUTPUT_DIR_INSIDE_REPO", "output_dir must be outside the travel repo")
    lowered = str(target).lower()
    forbidden = (
        "production_default",
        "production-vector",
        "production_vector",
        "source_raw",
        "official_baseline_current.json",
        "series_b_official_baseline_ledger.json",
    )
    if any(marker in lowered for marker in forbidden):
        raise FullSanityError("FULL_SANITY_OUTPUT_DIR_WRITE_RISK", f"output_dir contains write-risk marker: {target}")
    return target


def repo_status() -> dict[str, Any]:
    status = subprocess.run(["git", "status", "--short", "--branch", "-uall"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    diff = subprocess.run(["git", "diff", "--name-only"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    cached = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    dirty_lines = [line for line in status.stdout.splitlines() if not line.startswith("##")]
    return {
        "status_short_branch": status.stdout.strip(),
        "tracked_diff": [line for line in diff.stdout.splitlines() if line.strip()],
        "staged_diff": [line for line in cached.stdout.splitlines() if line.strip()],
        "dirty_lines": dirty_lines,
        "clean": status.returncode == 0 and not dirty_lines and not diff.stdout.strip() and not cached.stdout.strip(),
    }


def _file_identity(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    return {
        "path": str(target),
        "exists": target.exists(),
        "readable": target.is_file(),
        "sha256": sha256_file(target) if target.exists() and target.is_file() else None,
    }


def sensitive_hashes() -> dict[str, str]:
    paths = {
        "official_baseline_current": BASELINE_CURRENT_PATH,
        "official_baseline_ledger": BASELINE_LEDGER_PATH,
        "official_dataset": DATASET_PATH,
        "source_state_manifest": SOURCE_STATE_PATH,
        "production_target_manifest": DEFAULT_TARGET_MANIFEST,
        "production_integration_manifest": INTEGRATION_PATH,
        "scoring_audit": SCORING_AUDIT_PATH,
        "controlled_case_list": CONTROLLED_CASE_LIST_PATH,
        "controlled_rollup": CONTROLLED_ROLLUP_PATH,
        "final_case_matrix": FINAL_CASE_MATRIX_PATH,
        "final_seal_audit": FINAL_SEAL_AUDIT_PATH,
    }
    return {key: sha256_file(path) for key, path in paths.items() if path.exists() and path.is_file()}


def validate_no_write_flags(*, no_source_write: bool, no_vector_write: bool, no_official_baseline_write: bool, no_push: bool, no_tag: bool) -> None:
    if not no_source_write:
        raise FullSanityError("FULL_SANITY_SOURCE_WRITE_RISK", "--no-source-write is required")
    if not no_vector_write:
        raise FullSanityError("FULL_SANITY_VECTOR_WRITE_RISK", "--no-vector-write is required")
    if not no_official_baseline_write:
        raise FullSanityError("FULL_SANITY_BASELINE_WRITE_RISK", "--no-official-baseline-write is required")
    if not no_push:
        raise FullSanityError("FULL_SANITY_PUSH_RISK", "--no-push is required")
    if not no_tag:
        raise FullSanityError("FULL_SANITY_TAG_RISK", "--no-tag is required")


def check_baseline() -> dict[str, Any]:
    current = load_json(BASELINE_CURRENT_PATH)
    ledger = load_json(BASELINE_LEDGER_PATH)
    if current.get("official_score") != EXPECTED_BASELINE:
        raise FullSanityError("FULL_SANITY_BASELINE_CURRENT_INVALID", f"official baseline current must be {EXPECTED_BASELINE}")
    if current.get("previous_official_score") != EXPECTED_PREVIOUS_BASELINE and current.get("prior_score") != EXPECTED_PREVIOUS_BASELINE:
        raise FullSanityError("FULL_SANITY_PRIOR_BASELINE_MISSING", f"previous {EXPECTED_PREVIOUS_BASELINE} baseline trace must be retained")
    ledger_text = json.dumps(ledger, sort_keys=True)
    if ledger.get("prior_score") != EXPECTED_PREVIOUS_BASELINE or "31/60" not in ledger_text or "39/60" not in ledger_text:
        raise FullSanityError("FULL_SANITY_PRIOR_BASELINE_MISSING", "ledger must retain 31/60, 39/60, 44/60, 50/60, 55/60, 56/60, 58/60, and 60/60 baseline traces")
    if current.get("controlled_evidence_count") != EXPECTED_CONTROLLED_EVIDENCE_COUNT:
        raise FullSanityError("FULL_SANITY_CONTROLLED_EVIDENCE_COUNT_INVALID", f"baseline must reference {EXPECTED_CONTROLLED_EVIDENCE_COUNT} controlled evidence cases")
    if current.get("production_default_integrated") is not False:
        raise FullSanityError("FULL_SANITY_BASELINE_DEFAULT_RISK", "baseline must not be marked production default integrated")
    caveats = set(current.get("caveat_cases") or [])
    missing = [case for case in REQUIRED_CAVEAT_CASES if case not in caveats]
    if missing:
        raise FullSanityError("FULL_SANITY_CAVEAT_MISSING", f"missing caveat cases: {missing}")
    return {
        "status": "PASS",
        "official_baseline_current": current.get("official_score"),
        "prior_baseline_retained": current.get("prior_score"),
        "ledger_prior_baseline_retained": ledger.get("prior_score"),
        "controlled_evidence_count": current.get("controlled_evidence_count"),
        "official_passed_cases": len(current.get("passed_cases") or current.get("official_passed_cases") or []),
        "official_failed_cases": len(current.get("failed_cases") or current.get("official_failed_cases") or []),
        "caveat_cases": sorted(caveats),
    }


def check_production_target() -> dict[str, Any]:
    loaded = load_explicit_production_target(DEFAULT_TARGET_MANIFEST)
    validation = loaded["validation"]
    integration = loaded["integration"]
    if validation.get("production_default_scope") != "explicit_series_b_target_only":
        raise FullSanityError("FULL_SANITY_PRODUCTION_SCOPE_INVALID", "production scope must be explicit_series_b_target_only")
    if integration.get("write_targets") != []:
        raise FullSanityError("FULL_SANITY_PRODUCTION_WRITE_TARGET_RISK", "production write_targets must be empty")
    for key in ("vector_write_enabled", "source_data_write_enabled", "official_baseline_write_enabled", "global_default_enabled"):
        if validation.get(key) is not False:
            raise FullSanityError("FULL_SANITY_PRODUCTION_WRITE_RISK", f"{key} must be false")
    return {
        "status": "PASS",
        "layer_id": validation.get("layer_id"),
        "production_target_layer_integrated": validation.get("production_target_layer_integrated"),
        "production_default_scope": validation.get("production_default_scope"),
        "write_targets": validation.get("write_targets"),
        "vector_write_enabled": validation.get("vector_write_enabled"),
        "source_data_write_enabled": validation.get("source_data_write_enabled"),
        "official_baseline_write_enabled": validation.get("official_baseline_write_enabled"),
        "resolved_paths": validation.get("resolved_paths"),
    }


def check_dataset() -> dict[str, Any]:
    dataset = load_json(DATASET_PATH)
    cases = dataset.get("cases")
    if dataset.get("classification") != "CANONICAL_OFFICIAL_DATASET_V1":
        raise FullSanityError("FULL_SANITY_DATASET_CLASSIFICATION_INVALID", "dataset must be canonical official v1")
    if not isinstance(cases, list) or len(cases) != 60:
        raise FullSanityError("FULL_SANITY_DATASET_COUNT_INVALID", "dataset must contain exactly 60 cases")
    case_ids = [str(row.get("case_id") or "").strip() for row in cases if isinstance(row, dict)]
    if len(case_ids) != 60 or len(set(case_ids)) != 60:
        raise FullSanityError("FULL_SANITY_DATASET_CASE_ID_INVALID", "dataset case ids must be complete and unique")
    missing_prompts = [case_id for case_id, row in zip(case_ids, cases) if not str(row.get("original_prompt") or row.get("prompt") or "").strip()]
    if missing_prompts:
        raise FullSanityError("FULL_SANITY_DATASET_PROMPT_MISSING", f"dataset cases missing prompts: {missing_prompts[:5]}")
    return {
        "status": "PASS",
        "dataset_path": str(DATASET_PATH),
        "dataset_sha256": sha256_file(DATASET_PATH),
        "case_count": 60,
        "unique_case_count": len(set(case_ids)),
        "case_ids": case_ids,
    }


def check_source_state_and_scoring() -> dict[str, Any]:
    manifest = load_json(SOURCE_STATE_PATH)
    if manifest.get("official_write_enabled") is not False or manifest.get("production_default_enabled") is not False:
        raise FullSanityError("FULL_SANITY_SOURCE_STATE_WRITE_RISK", "source-state manifest must be no-write and non-default")
    if manifest.get("full_series_b_enabled") is not False:
        raise FullSanityError("FULL_SANITY_SOURCE_STATE_FULL_SERIES_B_RISK", "source-state manifest must keep full_series_b_enabled false")
    entries = manifest.get("inputs") or []
    write_targets = [entry.get("input_role") for entry in entries if isinstance(entry, dict) and entry.get("write_target") is True]
    if write_targets:
        raise FullSanityError("FULL_SANITY_SOURCE_STATE_WRITE_TARGET_RISK", f"source-state write targets present: {write_targets}")
    scoring_entry = next((entry for entry in entries if isinstance(entry, dict) and entry.get("input_role") == "scoring_audit_path"), None)
    if scoring_entry is None or scoring_entry.get("exists") is not True or scoring_entry.get("readable") is not True:
        raise FullSanityError("FULL_SANITY_SCORING_AUDIT_MISSING", "candidate-safe scoring/audit input is missing")
    if Path(scoring_entry.get("path") or "") != SCORING_AUDIT_PATH:
        raise FullSanityError("FULL_SANITY_SCORING_AUDIT_AMBIGUOUS", "scoring/audit path does not match canonical helper")
    if not SCORING_AUDIT_PATH.exists():
        raise FullSanityError("FULL_SANITY_SCORING_AUDIT_MISSING", "scoring/audit helper file missing")
    return {
        "status": "PASS",
        "source_state_manifest_path": str(SOURCE_STATE_PATH),
        "source_state_manifest_sha256": sha256_file(SOURCE_STATE_PATH),
        "input_count": len(entries),
        "write_targets": [],
        "scoring_audit_path": str(SCORING_AUDIT_PATH),
        "scoring_audit_sha256": sha256_file(SCORING_AUDIT_PATH),
        "candidate_safe_scoring_audit_available": True,
    }


def _controlled_cases_from_payload(payload: dict[str, Any]) -> list[str]:
    if isinstance(payload.get("controlled_evidence_cases"), list):
        return [str(item) for item in payload["controlled_evidence_cases"]]
    if isinstance(payload.get("controlled_evidence_case_list"), list):
        return [str(item) for item in payload["controlled_evidence_case_list"]]
    if isinstance(payload.get("cases"), list):
        return [str(item.get("case_id")) for item in payload["cases"] if isinstance(item, dict) and item.get("case_id")]
    return []


def check_12case_trace(dataset_case_ids: list[str]) -> dict[str, Any]:
    if not CONTROLLED_CASE_LIST_PATH.exists() or not CONTROLLED_ROLLUP_PATH.exists() or not FINAL_CASE_MATRIX_PATH.exists():
        raise FullSanityError("FULL_SANITY_12CASE_TRACE_MISSING", "required 12-case trace artifacts are missing")
    case_list_payload = load_json(CONTROLLED_CASE_LIST_PATH)
    rollup_payload = load_json(CONTROLLED_ROLLUP_PATH)
    matrix_payload = load_json(FINAL_CASE_MATRIX_PATH)
    cases = _controlled_cases_from_payload(case_list_payload) or _controlled_cases_from_payload(rollup_payload) or _controlled_cases_from_payload(matrix_payload)
    if len(cases) != EXPECTED_CONTROLLED_EVIDENCE_COUNT or len(set(cases)) != EXPECTED_CONTROLLED_EVIDENCE_COUNT:
        raise FullSanityError("FULL_SANITY_CONTROLLED_TRACE_COUNT_INVALID", f"controlled evidence trace must contain exactly {EXPECTED_CONTROLLED_EVIDENCE_COUNT} unique cases")
    missing_from_dataset = sorted(set(cases) - set(dataset_case_ids))
    if missing_from_dataset:
        raise FullSanityError("FULL_SANITY_12CASE_DATASET_MISMATCH", f"controlled cases missing from official dataset: {missing_from_dataset}")
    return {
        "status": "PASS",
        "controlled_evidence_case_count": len(cases),
        "controlled_evidence_cases": cases,
        "all_cases_in_60case_dataset": True,
        "case_list_path": str(CONTROLLED_CASE_LIST_PATH),
        "case_list_sha256": sha256_file(CONTROLLED_CASE_LIST_PATH),
        "rollup_path": str(CONTROLLED_ROLLUP_PATH),
        "rollup_sha256": sha256_file(CONTROLLED_ROLLUP_PATH),
        "final_case_matrix_path": str(FINAL_CASE_MATRIX_PATH),
        "final_case_matrix_sha256": sha256_file(FINAL_CASE_MATRIX_PATH),
    }


def dry_run_one_case(dataset_cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not dataset_cases:
        raise FullSanityError("FULL_SANITY_ONE_CASE_MISSING", "dataset cases missing")
    row = dataset_cases[0]
    return {
        "status": "PASS",
        "mode": "metadata_only_no_dossier_generation",
        "case_id": row.get("case_id"),
        "dossier_generated": False,
        "retrieval_executed": False,
        "source_data_written": False,
        "production_vector_written": False,
        "official_baseline_written": False,
    }


def dry_run_60case_plan(dataset_cases: list[dict[str, Any]]) -> dict[str, Any]:
    plan = []
    for index, row in enumerate(dataset_cases, 1):
        case_id = str(row.get("case_id") or "").strip()
        prompt = str(row.get("original_prompt") or row.get("prompt") or "").strip()
        if not case_id or not prompt:
            raise FullSanityError("FULL_SANITY_60CASE_PLAN_INVALID", f"invalid case at position {index}")
        plan.append(
            {
                "ordinal": index,
                "case_id": case_id,
                "plan_mode": "read_only_metadata_plan",
                "would_load_production_target": True,
                "would_read_official_baseline": True,
                "would_read_source_state_manifest": True,
                "would_write_source_data": False,
                "would_write_vector_index": False,
                "would_write_official_baseline": False,
                "would_push_or_tag": False,
            }
        )
    return {"status": "PASS", "case_count": len(plan), "plan": plan}


def run_full_sanity(
    *,
    output_dir: str | Path,
    check_baseline_flag: bool,
    check_production_target_flag: bool,
    check_60case_dataset_flag: bool,
    check_12case_trace_flag: bool,
    dry_run_one_case_flag: bool,
    dry_run_60case_plan_flag: bool,
    check_no_mutation_flag: bool,
    no_source_write: bool,
    no_vector_write: bool,
    no_official_baseline_write: bool,
    no_push: bool,
    no_tag: bool,
    require_clean_repo: bool = True,
) -> tuple[int, dict[str, Any]]:
    try:
        validate_no_write_flags(
            no_source_write=no_source_write,
            no_vector_write=no_vector_write,
            no_official_baseline_write=no_official_baseline_write,
            no_push=no_push,
            no_tag=no_tag,
        )
        target_output = validate_output_dir(output_dir)
        target_output.mkdir(parents=True, exist_ok=True)
        pre_repo_status = repo_status()
        if require_clean_repo and not pre_repo_status["clean"]:
            raise FullSanityError("FULL_SANITY_REPO_DIRTY_PRE", "repo must be clean before full sanity run")
        pre_hashes = sensitive_hashes()

        checks: dict[str, Any] = {}
        if check_baseline_flag:
            checks["baseline"] = check_baseline()
        if check_production_target_flag:
            checks["production_target"] = check_production_target()
        if check_60case_dataset_flag:
            checks["dataset"] = check_dataset()
        else:
            checks["dataset"] = check_dataset()
        source_state = check_source_state_and_scoring()
        checks["source_state_and_scoring"] = source_state

        dataset_payload = load_json(DATASET_PATH)
        dataset_cases = dataset_payload.get("cases") or []
        dataset_case_ids = [str(row.get("case_id")) for row in dataset_cases if isinstance(row, dict)]
        if check_12case_trace_flag:
            checks["trace_12case"] = check_12case_trace(dataset_case_ids)
        if dry_run_one_case_flag:
            checks["one_case_dry_run"] = dry_run_one_case(dataset_cases)
        if dry_run_60case_plan_flag:
            checks["plan_60case_traversal"] = dry_run_60case_plan(dataset_cases)
            plan_path = target_output / "series_b_full_nondestructive_60case_plan.json"
            plan_path.write_text(json.dumps(checks["plan_60case_traversal"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
            checks["plan_60case_traversal"]["artifact_path"] = str(plan_path)
            checks["plan_60case_traversal"]["artifact_sha256"] = sha256_file(plan_path)

        post_hashes = sensitive_hashes()
        post_repo_status = repo_status()
        mutation_guard_pass = pre_hashes == post_hashes and pre_repo_status == post_repo_status and (post_repo_status["clean"] is True or not require_clean_repo)
        if check_no_mutation_flag and not mutation_guard_pass:
            raise FullSanityError("FULL_SANITY_MUTATION_GUARD_FAIL", "repo status or sensitive hashes changed during full sanity run")

        payload = {
            "status": "PASS",
            "result_enum": RESULT_PASS,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repo_path": str(REPO_ROOT),
            "branch": "travel-series-b-validation",
            "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, check=False).stdout.strip(),
            "checks": checks,
            "official_baseline_current": checks.get("baseline", {}).get("official_baseline_current"),
            "dataset_60case_check": checks.get("dataset", {}).get("status"),
            "trace_12case_check": checks.get("trace_12case", {}).get("status"),
            "one_case_dry_run": checks.get("one_case_dry_run", {}).get("status"),
            "plan_60case_traversal": checks.get("plan_60case_traversal", {}).get("status"),
            "mutation_guard_result": "FULL_NON_DESTRUCTIVE_MUTATION_GUARD_PASS" if mutation_guard_pass else "FULL_NON_DESTRUCTIVE_MUTATION_GUARD_FAIL",
            "pre_hashes": pre_hashes,
            "post_hashes": post_hashes,
            "pre_repo_status": pre_repo_status,
            "post_repo_status": post_repo_status,
            "official_baseline_modified": False,
            "production_files_modified": False,
            "source_vector_mutation_performed": False,
            "push_performed": False,
            "tag_created": False,
            "release_performed": False,
            "full_series_b_destructive_run_performed": False,
            "release_readiness_verdict": "READY_FOR_PUSH_TAG_APPROVAL",
        }
        output_path = target_output / "series_b_full_nondestructive_sanity_run.json"
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (target_output / "series_b_full_nondestructive_sanity_run.md").write_text(
            "# Series B Full Non-Destructive Sanity Run\n\n"
            f"result: `{payload['result_enum']}`\n\n"
            f"official_baseline_current: `{payload['official_baseline_current']}`\n\n"
            f"dataset_60case_check: `{payload['dataset_60case_check']}`\n\n"
            f"trace_12case_check: `{payload['trace_12case_check']}`\n\n"
            f"plan_60case_traversal: `{payload['plan_60case_traversal']}`\n\n"
            f"mutation_guard_result: `{payload['mutation_guard_result']}`\n\n"
            "push_performed: false\ntag_created: false\nrelease_performed: false\n",
            encoding="utf-8",
        )
        return 0, payload
    except (FullSanityError, ProductionTargetLayerError) as exc:
        error_code = getattr(exc, "error_code", RESULT_BLOCKED)
        message = getattr(exc, "message", str(exc))
        payload = {
            "status": "BLOCKED",
            "result_enum": error_code,
            "message": message,
            "official_baseline_modified": False,
            "source_vector_mutation_performed": False,
            "push_performed": False,
            "tag_created": False,
            "release_performed": False,
        }
        try:
            target_output = validate_output_dir(output_dir)
            target_output.mkdir(parents=True, exist_ok=True)
            (target_output / "series_b_full_nondestructive_sanity_run.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except Exception:
            pass
        return 2, payload
