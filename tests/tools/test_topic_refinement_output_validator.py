from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from tools import topic_refinement_output_validator as validator


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools/topic_refinement_output_validator.py"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_routed_state(
    tmp_path: Path,
    *,
    mode: str | None = "final_absorption_pass",
    failure_type: str | None = "calibration_absorption_gap",
    next_action: str = "ready_for_final_absorption_pass",
    state_type: str = "topic_refinement_state_routed",
    flags: dict | None = None,
    caveats: list[str] | None = None,
) -> Path:
    final_path = tmp_path / "final_controller_report.md"
    final_path.write_text("final_v1 original\n", encoding="utf-8")
    state = {
        "schema_version": "1.0",
        "state_type": state_type,
        "topic_id": "topic-1",
        "original_question": "question",
        "current_final_version": "final_v1",
        "current_final_version_path": str(final_path),
        "artifact_paths": {"final_v1": str(final_path)},
        "artifact_hashes": {"final_v1": _sha(final_path)},
        "user_feedback": "continue",
        "detected_quality_signals": [],
        "detected_evidence_boundary_signals": [],
        "detected_calibration_boundary_signals": [],
        "detected_environment_signals": [],
        "authorization": {"allow_source_acquisition": False, "allow_full_text_verification": False},
        "preserved_caveats": caveats if caveats is not None else ["caveat remains"],
        "unresolved_evidence_gaps": [],
        "selected_failure_type": failure_type,
        "selected_refinement_mode": mode,
        "selection_tie_breaker_reason": "test",
        "routing_priority": 2,
        "confidence_boundary": "no confidence upgrade without evidence",
        "final_versions": [{"version": "final_v1", "path": str(final_path), "sha256": _sha(final_path), "created_by": "existing_artifact", "overwritten": False}],
        "refinement_history": [],
        "stop_reason": None,
        "next_action": next_action,
        "no_runtime_integration": True,
        "no_llm_called": True,
        "no_pipeline_rerun": True,
        "no_final_rewritten": True,
        "no_evidence_acquisition_performed": True,
    }
    if flags:
        state.update(flags)
    path = tmp_path / "topic_refinement_state.routed.json"
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return path


def _candidate(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "candidate"
    root.mkdir(exist_ok=True)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _validate(tmp_path: Path, state_path: Path, candidate_dir: Path):
    output_dir = tmp_path / "validator_out"
    return validator.validate_output(routed_state_path=state_path, refinement_dir=candidate_dir, output_dir=output_dir)


def _blocked_status(output_dir: Path) -> str:
    return json.loads((output_dir / "refinement_output_validation_blocked_report.json").read_text(encoding="utf-8"))["status"]


def test_pass_final_absorption_with_revised_final_and_traceability(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    cand = _candidate(tmp_path, {
        "revised_final_v2.md": "new_evidence: none\nCaveat preserved; conclusion remains conditional.\n",
        "changed_unchanged_traceability.md": "changed_sections: final\nwhat_was_not_changed: final_v1\n",
    })

    result = _validate(tmp_path, state, cand)

    assert result.exit_code == 0
    assert result.status == validator.PASS_STATUS


def test_pass_section_rewrite_with_refined_sections_and_traceability(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path, mode="section_rewrite", failure_type="low_domain_specificity", next_action="ready_for_refinement")
    cand = _candidate(tmp_path, {
        "refined_sections_v2.md": "Caveat preserved. new_evidence: none\n",
        "changed_unchanged_traceability.md": "changed_sections: section 2\nwhat_was_not_changed: rest of final\n",
    })

    assert _validate(tmp_path, state, cand).exit_code == 0


def test_pass_targeted_evidence_acquisition_stop_source_need(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path, mode="targeted_evidence_acquisition", failure_type="evidence_gap_needs_full_text_verification", next_action="source_need_or_full_text_verification")
    cand = _candidate(tmp_path, {"refinement_stop_or_source_need.md": "source_need: needed sources and full-text verification required.\n"})

    assert _validate(tmp_path, state, cand).exit_code == 0


def test_pass_environment_triage_without_answer_rewrite(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path, mode="environment_triage", failure_type="executor_or_environment_blocker", next_action="environment_triage_required")
    cand = _candidate(tmp_path, {"environment_triage_report.md": "answer rewrite not allowed until blocker clears.\n"})

    assert _validate(tmp_path, state, cand).exit_code == 0


def test_pass_no_actionable_refinement_stop_report(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path, mode=None, failure_type=None, next_action="stop_no_actionable_refinement", caveats=[])
    cand = _candidate(tmp_path, {"no_actionable_refinement_report.md": "no actionable refinement signal.\n"})

    assert _validate(tmp_path, state, cand).exit_code == 0


def test_missing_routed_state_blocks(tmp_path: Path) -> None:
    cand = _candidate(tmp_path, {"no_actionable_refinement_report.md": "stop\n"})
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=tmp_path / "missing.json", refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_ROUTED_STATE_MISSING


def test_invalid_routed_state_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path, state_type="topic_refinement_state_initial")
    cand = _candidate(tmp_path, {"no_actionable_refinement_report.md": "stop\n"})
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_INVALID_ROUTED_STATE


def test_missing_refinement_dir_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=tmp_path / "missing", output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_REFINEMENT_DIR_MISSING


def test_output_already_exists_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    cand = _candidate(tmp_path, {"revised_final_v2.md": "caveat\n", "changed_unchanged_traceability.md": "changed_sections:x\nwhat_was_not_changed:y\n"})
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / validator.REPORT_FILENAME).write_text("{}\n", encoding="utf-8")

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_OUTPUT_ALREADY_EXISTS


def test_final_v1_overwrite_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    routed = json.loads(state.read_text(encoding="utf-8"))
    Path(routed["current_final_version_path"]).write_text("mutated final\n", encoding="utf-8")
    cand = _candidate(tmp_path, {"revised_final_v2.md": "caveat\n", "changed_unchanged_traceability.md": "changed_sections:x\nwhat_was_not_changed:y\n"})
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_FINAL_V1_OVERWRITTEN


def test_revised_final_not_allowed_for_source_need_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path, mode="targeted_evidence_acquisition", failure_type="evidence_gap_needs_full_text_verification", next_action="source_need_or_full_text_verification")
    cand = _candidate(tmp_path, {"revised_final_v2.md": "caveat\n", "refinement_stop_or_source_need.md": "source_need: full-text verification required\n"})
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_REVISED_FINAL_NOT_ALLOWED


def test_missing_required_refinement_output_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    cand = _candidate(tmp_path, {"revised_final_v2.md": "caveat\n"})
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT


def test_false_full_text_verification_claim_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path, mode="targeted_evidence_acquisition", failure_type="evidence_gap_needs_full_text_verification", next_action="source_need_or_full_text_verification")
    cand = _candidate(tmp_path, {"refinement_stop_or_source_need.md": "source_need: full-text verification required\nfull_text_verified: true\n"})
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_FALSE_FULL_TEXT_VERIFICATION_CLAIM


def test_confidence_upgrade_without_new_evidence_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    cand = _candidate(tmp_path, {
        "revised_final_v2.md": "confidence upgraded. Caveat preserved.\n",
        "changed_unchanged_traceability.md": "changed_sections:x\nwhat_was_not_changed:y\n",
    })
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_CONFIDENCE_UPGRADE_WITHOUT_NEW_EVIDENCE


def test_evidence_acquisition_claim_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    cand = _candidate(tmp_path, {
        "revised_final_v2.md": "Caveat preserved.\n",
        "changed_unchanged_traceability.md": "changed_sections:x\nwhat_was_not_changed:y\n",
        "evidence_acquisition_result.md": "new evidence acquired\n",
    })
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_EVIDENCE_ACQUISITION_CLAIM


def test_full_rerun_claim_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path, mode="section_rewrite", failure_type="low_domain_specificity", next_action="ready_for_refinement")
    cand = _candidate(tmp_path, {
        "refined_sections_v2.md": "Caveat preserved. full rerun completed.\n",
        "changed_unchanged_traceability.md": "changed_sections:x\nwhat_was_not_changed:y\n",
    })
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_FULL_RERUN_CLAIM


def test_runtime_integration_claim_blocks(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    cand = _candidate(tmp_path, {
        "revised_final_v2.md": "Caveat preserved. runtime integration completed.\n",
        "changed_unchanged_traceability.md": "changed_sections:x\nwhat_was_not_changed:y\n",
    })
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_RUNTIME_INTEGRATION_CLAIM


def test_missing_changed_unchanged_traceability_blocks_for_rewrite_modes(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path, mode="user_feedback_refinement", failure_type="user_feedback_requests_deeper_specificity", next_action="ready_for_user_feedback_refinement")
    cand = _candidate(tmp_path, {"refined_sections_v2.md": "Caveat preserved.\n"})
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT


def test_missing_source_need_language_blocks_for_source_need_mode(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path, mode="targeted_evidence_acquisition", failure_type="evidence_gap_needs_full_text_verification", next_action="source_need_or_full_text_verification")
    cand = _candidate(tmp_path, {"refinement_stop_or_source_need.md": "stop here.\n"})
    output_dir = tmp_path / "out"

    result = validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert result.exit_code != 0
    assert _blocked_status(output_dir) == validator.BLOCKED_MISSING_REQUIRED_REFINEMENT_OUTPUT


def test_final_v1_hash_remains_unchanged(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    cand = _candidate(tmp_path, {
        "revised_final_v2.md": "new_evidence: none\nCaveat preserved.\n",
        "changed_unchanged_traceability.md": "changed_sections:x\nwhat_was_not_changed:y\n",
    })
    output_dir = tmp_path / "out"

    validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)
    report = json.loads((output_dir / validator.REPORT_FILENAME).read_text(encoding="utf-8"))

    assert report["final_v1_overwrite_check"]["pass"] is True


def test_validator_output_report_contains_pass_status(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    cand = _candidate(tmp_path, {
        "revised_final_v2.md": "new_evidence: none\nCaveat preserved.\n",
        "changed_unchanged_traceability.md": "changed_sections:x\nwhat_was_not_changed:y\n",
    })
    output_dir = tmp_path / "out"

    validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert validator.PASS_STATUS in (output_dir / "refinement_output_validation_report.md").read_text(encoding="utf-8")


def test_blocked_report_contains_correct_status(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    cand = _candidate(tmp_path, {"revised_final_v2.md": "confidence upgraded. Caveat preserved.\n", "changed_unchanged_traceability.md": "changed_sections:x\nwhat_was_not_changed:y\n"})
    output_dir = tmp_path / "out"

    validator.validate_output(routed_state_path=state, refinement_dir=cand, output_dir=output_dir)

    assert validator.BLOCKED_CONFIDENCE_UPGRADE_WITHOUT_NEW_EVIDENCE in (output_dir / "refinement_output_validation_blocked_report.md").read_text(encoding="utf-8")


def test_no_llm_runtime_or_pipeline_imports() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "tools.task_engine_runner",
        "tools.task_engine_executors",
        "tools.task_mode_runtime",
        "tools.task_engine_contracts",
        "research_pipeline_runner",
    ]
    assert not any(token in source for token in forbidden)


def test_cli_success_exit_code_zero(tmp_path: Path) -> None:
    state = _write_routed_state(tmp_path)
    cand = _candidate(tmp_path, {
        "revised_final_v2.md": "new_evidence: none\nCaveat preserved.\n",
        "changed_unchanged_traceability.md": "changed_sections:x\nwhat_was_not_changed:y\n",
    })
    output_dir = tmp_path / "cli_out"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--routed-state", str(state), "--refinement-dir", str(cand), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert validator.PASS_STATUS in result.stdout


def test_cli_blocked_exit_code_nonzero(tmp_path: Path) -> None:
    cand = _candidate(tmp_path, {"no_actionable_refinement_report.md": "stop\n"})
    output_dir = tmp_path / "cli_out"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--routed-state", str(tmp_path / "missing.json"), "--refinement-dir", str(cand), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert validator.BLOCKED_ROUTED_STATE_MISSING in result.stdout
