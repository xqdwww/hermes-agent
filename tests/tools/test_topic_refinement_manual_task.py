from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools import topic_refinement_manual_task as manual
from tools import topic_refinement_artifact_loader as loader
from tools import topic_refinement_mode_router as router


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools/topic_refinement_manual_task.py"


def _run_dir(tmp_path: Path, *, quality: str = "", calibration: str = "", evidence: str = "", runner: str = "{}") -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "final_controller_report.md").write_text("final_v1 original\n", encoding="utf-8")
    (run_dir / "case_quality_review.md").write_text(quality or "quality review\n", encoding="utf-8")
    if calibration:
        (run_dir / "calibration_report.md").write_text(calibration, encoding="utf-8")
    if evidence:
        (run_dir / "research_evidence_packet.md").write_text(evidence, encoding="utf-8")
    (run_dir / "runner_result.json").write_text(runner, encoding="utf-8")
    (run_dir / "original_user_question.txt").write_text("original question\n", encoding="utf-8")
    return run_dir


def _rewrite_run(tmp_path: Path) -> Path:
    return _run_dir(
        tmp_path,
        quality="case quality review\n",
        calibration="overclaim caveat plausible calibration boundary\n",
    )


def _source_need_run(tmp_path: Path) -> Path:
    return _run_dir(
        tmp_path,
        quality="verification_required true snippet_limited true\n",
        evidence="snippet full-text verification unsupported evidence gap\n",
    )


def _read_report(output_dir: Path) -> dict:
    return json.loads((output_dir / "manual_task_report.json").read_text(encoding="utf-8"))


def _read_blocked(output_dir: Path) -> dict:
    return json.loads((output_dir / "manual_task_blocked_report.json").read_text(encoding="utf-8"))


def _run_manual(tmp_path: Path, run_dir: Path, **kwargs):
    output_dir = kwargs.pop("output_dir", tmp_path / "out")
    return manual.run_manual_task(
        run_dir=run_dir,
        topic_id=kwargs.pop("topic_id", "topic-1"),
        user_feedback=kwargs.pop("user_feedback", "继续这个话题。请把判断做实。"),
        output_dir=output_dir,
        confirm_same_topic=kwargs.pop("confirm_same_topic", True),
        **kwargs,
    )


def test_missing_confirm_same_topic_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    out = tmp_path / "out"
    result = manual.run_manual_task(run_dir=run_dir, topic_id="topic", user_feedback="continue", output_dir=out)
    assert result.exit_code != 0
    assert result.status == manual.BLOCKED_SAME_TOPIC_NOT_CONFIRMED
    assert _read_blocked(out)["status"] == manual.BLOCKED_SAME_TOPIC_NOT_CONFIRMED


def test_new_topic_phrase_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    out = tmp_path / "out"
    result = _run_manual(tmp_path, run_dir, output_dir=out, user_feedback="换个话题，新问题开始")
    assert result.status == manual.BLOCKED_NEW_TOPIC_DETECTED
    assert _read_blocked(out)["status"] == manual.BLOCKED_NEW_TOPIC_DETECTED


def test_empty_topic_id_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    result = _run_manual(tmp_path, run_dir, topic_id=" ")
    assert result.status == manual.BLOCKED_INVALID_TOPIC_ID


def test_empty_user_feedback_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    result = _run_manual(tmp_path, run_dir, user_feedback=" ")
    assert result.status == manual.BLOCKED_INVALID_USER_FEEDBACK


def test_missing_run_dir_blocks(tmp_path: Path) -> None:
    result = _run_manual(tmp_path, tmp_path / "missing")
    assert result.status == manual.BLOCKED_RUN_DIR_MISSING


def test_output_already_exists_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "existing.txt").write_text("x", encoding="utf-8")
    result = _run_manual(tmp_path, run_dir, output_dir=out)
    assert result.status == manual.BLOCKED_OUTPUT_ALREADY_EXISTS


def test_expected_branch_mismatch_blocks(tmp_path: Path, monkeypatch) -> None:
    run_dir = _run_dir(tmp_path)
    monkeypatch.setattr(manual, "_current_branch", lambda: "actual")
    result = _run_manual(tmp_path, run_dir, expected_branch="expected")
    assert result.status == manual.BLOCKED_EXPECTED_BRANCH_MISMATCH


def test_expected_head_mismatch_blocks(tmp_path: Path, monkeypatch) -> None:
    run_dir = _run_dir(tmp_path)
    monkeypatch.setattr(manual, "_current_head", lambda: "actual")
    result = _run_manual(tmp_path, run_dir, expected_head="expected")
    assert result.status == manual.BLOCKED_EXPECTED_HEAD_MISMATCH


def test_successful_rewrite_capable_route_generates_handoff_prompt(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    result = _run_manual(tmp_path, run_dir)
    out = tmp_path / "out"
    report = _read_report(out)
    assert result.status == manual.PASS_MANUAL_TASK_HANDOFF_READY
    assert (out / "refinement_handoff_prompt.md").exists()
    assert report["selected_refinement_mode"] == "final_absorption_pass"
    assert report["generated_handoff_prompt"]


def test_handoff_prompt_contains_hard_rules(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    _run_manual(tmp_path, run_dir)
    prompt = (tmp_path / "out" / "refinement_handoff_prompt.md").read_text(encoding="utf-8")
    assert "no full rerun" in prompt
    assert "no confidence increase without new evidence" in prompt
    assert "preserve caveats" in prompt
    assert "do not overwrite final_v1" in prompt
    assert "must pass output validator before usable" in prompt


def test_source_need_route_generates_stop_report(tmp_path: Path) -> None:
    run_dir = _source_need_run(tmp_path)
    result = _run_manual(
        tmp_path,
        run_dir,
        user_feedback="继续这个话题。第一版还是不够有结论，请写得更确定一点。但不要全量重跑，不要重新查资料。",
    )
    out = tmp_path / "out"
    assert result.status == manual.PASS_MANUAL_TASK_STOPPED_SOURCE_NEED
    assert (out / "candidate_output" / "refinement_stop_or_source_need.md").exists()
    assert not (out / "candidate_output" / "revised_final_v2.md").exists()


def test_source_need_route_runs_validator_and_passes(tmp_path: Path) -> None:
    run_dir = _source_need_run(tmp_path)
    _run_manual(tmp_path, run_dir, user_feedback="继续这个话题。请写得更确定一点。")
    out = tmp_path / "out"
    report = _read_report(out)
    validator_report = json.loads((out / "validator_output" / "refinement_output_validation_report.json").read_text(encoding="utf-8"))
    assert report["validator_result"] == "PASS_REFINEMENT_OUTPUT_VALIDATION"
    assert validator_report["confidence_boundary_check"]["pass"] is True


def test_environment_route_generates_triage_report_without_revised_final(tmp_path: Path, monkeypatch) -> None:
    run_dir = _run_dir(tmp_path)
    final = run_dir / "final_controller_report.md"

    def fake_loader(**kwargs):
        out = kwargs["output_dir"]
        out.mkdir(parents=True)
        state = _initial_state(final, environment=[{"signal": "DDGS missing"}])
        path = out / "topic_refinement_state.initial.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        return loader.LoadResult(loader.PASS_STATUS, 0, out, path, None, None)

    def fake_router(*, state_path: Path, output_dir: Path, strict: bool = True):
        output_dir.mkdir(parents=True)
        state = _routed_state(final, mode="environment_triage", failure_type="executor_or_environment_blocker", next_action="environment_triage_required", stop_reason="environment_or_runtime_blocker_detected")
        path = output_dir / router.ROUTED_STATE_FILENAME
        path.write_text(json.dumps(state), encoding="utf-8")
        return router.RouterResult(router.PASS_STATUS, 0, output_dir, path, None, None)

    monkeypatch.setattr(manual.artifact_loader, "load_artifacts", fake_loader)
    monkeypatch.setattr(manual.mode_router, "route_file", fake_router)
    result = _run_manual(tmp_path, run_dir)
    out = tmp_path / "out"
    assert result.status == manual.PASS_MANUAL_TASK_STOPPED_ENVIRONMENT_TRIAGE
    assert (out / "candidate_output" / "environment_triage_report.md").exists()
    assert not (out / "candidate_output" / "revised_final_v2.md").exists()


def test_no_actionable_route_generates_no_action_report(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    result = _run_manual(tmp_path, run_dir, user_feedback="OK")
    out = tmp_path / "out"
    assert result.status == manual.PASS_MANUAL_TASK_STOPPED_NO_ACTION
    assert (out / "candidate_output" / "no_actionable_refinement_report.md").exists()
    assert _read_report(out)["same_topic_warning"] == "same_topic_confirmed_without_continuation_phrase"


def test_candidate_refinement_dir_triggers_validator(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    cand = tmp_path / "candidate"
    cand.mkdir()
    (cand / "revised_final_v2.md").write_text("new_evidence: none\nCaveat preserved; conditional.\n", encoding="utf-8")
    (cand / "changed_unchanged_traceability.md").write_text("changed_sections: final\nwhat_was_not_changed: final_v1\n", encoding="utf-8")
    result = _run_manual(tmp_path, run_dir, candidate_refinement_dir=cand)
    report = _read_report(tmp_path / "out")
    assert result.status == manual.PASS_MANUAL_TASK_CANDIDATE_VALIDATED
    assert report["usable_candidate"] is True
    assert report["validator_result"] == "PASS_REFINEMENT_OUTPUT_VALIDATION"


def test_validator_failure_blocks_usable_final(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    cand = tmp_path / "candidate"
    cand.mkdir()
    (cand / "revised_final_v2.md").write_text("Caveat preserved. confidence upgraded.\n", encoding="utf-8")
    (cand / "changed_unchanged_traceability.md").write_text("changed_sections: final\nwhat_was_not_changed: final_v1\n", encoding="utf-8")
    result = _run_manual(tmp_path, run_dir, candidate_refinement_dir=cand)
    assert result.status == manual.BLOCKED_VALIDATOR_FAILED
    assert _read_blocked(tmp_path / "out")["status"] == manual.BLOCKED_VALIDATOR_FAILED


def test_allow_llm_refinement_true_still_does_not_call_llm(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    result = _run_manual(tmp_path, run_dir, allow_llm_refinement=True)
    report = _read_report(tmp_path / "out")
    assert result.status == manual.PASS_MANUAL_TASK_HANDOFF_READY
    assert report["no_llm_called"] is True
    assert report["generated_handoff_prompt"]


def test_dry_run_false_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    result = _run_manual(tmp_path, run_dir, dry_run=False)
    assert result.status == manual.BLOCKED_DRY_RUN_REQUIRED


def test_report_contains_no_runtime_integration_true(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    _run_manual(tmp_path, run_dir)
    assert _read_report(tmp_path / "out")["no_runtime_integration"] is True


def test_report_contains_no_task_engine_registry_integration_true(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    _run_manual(tmp_path, run_dir)
    assert _read_report(tmp_path / "out")["no_task_engine_registry_integration"] is True


def test_report_contains_no_pipeline_rerun_true(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    _run_manual(tmp_path, run_dir)
    assert _read_report(tmp_path / "out")["no_pipeline_rerun"] is True


def test_report_contains_no_evidence_acquisition_performed_true(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    _run_manual(tmp_path, run_dir)
    assert _read_report(tmp_path / "out")["no_evidence_acquisition_performed"] is True


def test_does_not_import_task_engine_runtime_modules() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "tools.task_engine_runner",
        "tools.research_pipeline_runner",
        "tools.task_mode_runtime",
        "from tools import task_engine_runner",
        "from tools import research_pipeline_runner",
    ]
    for token in forbidden:
        assert token not in text


def test_cli_success_exit_code_zero(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    out = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-dir",
            str(run_dir),
            "--topic-id",
            "topic-1",
            "--user-feedback",
            "继续这个话题。请把判断做实。",
            "--output-dir",
            str(out),
            "--confirm-same-topic",
            "true",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert manual.PASS_MANUAL_TASK_HANDOFF_READY in result.stdout


def test_cli_blocked_exit_code_nonzero(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    out = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-dir",
            str(run_dir),
            "--topic-id",
            "topic-1",
            "--user-feedback",
            "continue",
            "--output-dir",
            str(out),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert manual.BLOCKED_SAME_TOPIC_NOT_CONFIRMED in result.stdout


def test_final_v1_hash_unchanged_in_success(tmp_path: Path) -> None:
    run_dir = _source_need_run(tmp_path)
    _run_manual(tmp_path, run_dir, user_feedback="继续这个话题。请写得更确定一点。")
    check = _read_report(tmp_path / "out")["final_v1_overwrite_check"]
    assert check["pass"] is True
    assert check["expected_sha256"] == check["actual_sha256"]


def test_no_revised_final_generated_for_rewrite_without_candidate(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    _run_manual(tmp_path, run_dir)
    out = tmp_path / "out"
    assert (out / "refinement_handoff_prompt.md").exists()
    assert not (out / "revised_final_v2.md").exists()
    assert not (out / "candidate_output" / "revised_final_v2.md").exists()


def test_manual_task_report_contains_selected_failure_type_and_mode(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    _run_manual(tmp_path, run_dir)
    report = _read_report(tmp_path / "out")
    assert report["selected_failure_type"] == "calibration_absorption_gap"
    assert report["selected_refinement_mode"] == "final_absorption_pass"


def test_blocked_report_contains_correct_status(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    out = tmp_path / "out"
    manual.run_manual_task(run_dir=run_dir, topic_id="topic", user_feedback="new topic", output_dir=out, confirm_same_topic=False)
    assert _read_blocked(out)["status"] == manual.BLOCKED_SAME_TOPIC_NOT_CONFIRMED


def test_source_need_does_not_claim_full_text_verification_completed(tmp_path: Path) -> None:
    run_dir = _source_need_run(tmp_path)
    _run_manual(tmp_path, run_dir, user_feedback="继续这个话题。请写得更确定一点。")
    text = (tmp_path / "out" / "candidate_output" / "refinement_stop_or_source_need.md").read_text(encoding="utf-8").lower()
    assert "full-text verification completed" not in text
    assert "full_text_verified: true" not in text


def test_task_mode_wrong_value_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    result = _run_manual(tmp_path, run_dir, task_mode="RESEARCH_DECISION")
    assert result.status == manual.BLOCKED_RUNTIME_INTEGRATION_NOT_ALLOWED


def _initial_state(final: Path, *, environment: list[dict[str, str]] | None = None) -> dict:
    sha = manual._sha256(final)
    return {
        "schema_version": "1.0",
        "state_type": "topic_refinement_state_initial",
        "topic_id": "topic-1",
        "original_question": "question",
        "current_final_version": "final_v1",
        "current_final_version_path": str(final),
        "artifact_paths": {"final_v1": str(final)},
        "artifact_hashes": {"final_v1": sha},
        "user_feedback": "continue",
        "detected_quality_signals": [],
        "detected_evidence_boundary_signals": [],
        "detected_calibration_boundary_signals": [],
        "detected_environment_signals": environment or [],
        "authorization": {"allow_source_acquisition": False, "allow_full_text_verification": False},
        "preserved_caveats": ["caveat remains"],
        "unresolved_evidence_gaps": [],
        "selected_failure_type": None,
        "selected_refinement_mode": None,
        "selection_tie_breaker_reason": None,
        "confidence_boundary": "no confidence upgrade without evidence",
        "final_versions": [{"version": "final_v1", "path": str(final), "sha256": sha, "created_by": "existing_artifact", "overwritten": False}],
        "refinement_history": [],
        "next_action": "needs_mode_router",
        "no_runtime_integration": True,
        "no_llm_called": True,
        "no_pipeline_rerun": True,
    }


def _routed_state(final: Path, *, mode: str | None, failure_type: str | None, next_action: str, stop_reason: str | None = None) -> dict:
    state = _initial_state(final)
    state.update(
        {
            "state_type": "topic_refinement_state_routed",
            "selected_failure_type": failure_type,
            "selected_refinement_mode": mode,
            "selection_tie_breaker_reason": "test route",
            "routing_priority": 0,
            "stop_reason": stop_reason,
            "next_action": next_action,
            "no_final_rewritten": True,
            "no_evidence_acquisition_performed": True,
        }
    )
    return state
