from __future__ import annotations

from pathlib import Path

from tools import topic_refinement_post_final_advisory_report as report


def _run_dir(
    tmp_path: Path,
    *,
    final: str = "Concrete final with specific recommendation.\n",
    quality: str = "quality acceptable\n",
    convergence: str = "",
    calibration: str = "",
    evidence: str = "",
    failure: str = "",
) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "final_controller_report.md").write_text(final, encoding="utf-8")
    (run_dir / "case_quality_review.md").write_text(quality, encoding="utf-8")
    if convergence:
        (run_dir / "convergence_report.md").write_text(convergence, encoding="utf-8")
    if calibration:
        (run_dir / "calibration_report.md").write_text(calibration, encoding="utf-8")
    if evidence:
        (run_dir / "research_evidence_packet.md").write_text(evidence, encoding="utf-8")
    if failure:
        (run_dir / "failure_report.md").write_text(failure, encoding="utf-8")
    (run_dir / "runner_result.json").write_text('{"pipeline_status":"PIPELINE_COMPLETE"}\n', encoding="utf-8")
    (run_dir / "original_user_question.txt").write_text("Question\n", encoding="utf-8")
    return run_dir


def _payload(tmp_path: Path, run_dir: Path, *, feedback: str = "") -> dict:
    result = report.generate_post_final_topic_refinement_advisory_report(
        run_dir=run_dir,
        topic_id="topic-1",
        output_dir=tmp_path / "out",
        user_feedback=feedback,
    )
    assert result.exit_code == 0
    return result.payload


def _assert_all_no_flags(payload: dict) -> None:
    assert payload["no_adapter_called"] is True
    assert payload["no_manual_task_called"] is True
    assert payload["no_llm_called"] is True
    assert payload["no_pipeline_rerun"] is True
    assert payload["no_candidate_generated"] is True
    assert payload["no_final_rewritten"] is True
    assert payload["auto_execution"] is False
    assert payload["auto_adoption"] is False


def test_case_like_rewrite_advisory_fixture_asks_user_confirmation(tmp_path: Path) -> None:
    payload = _payload(
        tmp_path,
        _run_dir(
            tmp_path,
            quality="final too generic low specificity missing obligation weak ranking\n",
            convergence="convergence not absorbed\n",
        ),
        feedback="same topic refine this final",
    )

    assert payload["status"] == report.PASS_REPORT_ONLY_ADVISORY_GENERATED
    assert payload["user_confirmation_required"] is True
    assert "TOPIC_REFINEMENT" in payload["user_confirmation_question"]
    _assert_all_no_flags(payload)


def test_source_need_fixture_stops_for_source_authorization(tmp_path: Path) -> None:
    payload = _payload(
        tmp_path,
        _run_dir(
            tmp_path,
            quality="final too generic\n",
            evidence="snippet-backed full-text verification unsupported evidence gap source_need\n",
        ),
    )

    assert payload["status"] == report.PASS_REPORT_ONLY_SOURCE_NEED_ADVISED
    assert payload["suggested_next_action"] == "ask_user_to_authorize_source_or_full_text_verification"
    assert "Confidence cannot be upgraded from current artifacts" in "\n".join(payload["remaining_risks"])
    assert "ask_user_to_confirm_explicit_TOPIC_REFINEMENT" != payload["suggested_next_action"]
    _assert_all_no_flags(payload)


def test_environment_fixture_routes_to_environment_triage(tmp_path: Path) -> None:
    payload = _payload(
        tmp_path,
        _run_dir(tmp_path, failure="blocked_executor_unavailable DDGS missing service unhealthy\n"),
    )

    assert payload["status"] == report.PASS_REPORT_ONLY_ENVIRONMENT_TRIAGE_ADVISED
    assert payload["suggested_next_action"] == "ask_user_to_fix_environment"
    assert payload["user_confirmation_required"] is True
    _assert_all_no_flags(payload)


def test_high_quality_fixture_recommends_no_action(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _run_dir(tmp_path))

    assert payload["status"] == report.PASS_REPORT_ONLY_NO_REFINEMENT_ADVISED
    assert payload["quality_verdict"] == report.REPORT_ONLY_NO_ACTION_RECOMMENDED
    assert payload["user_confirmation_required"] is False
    _assert_all_no_flags(payload)


def test_new_topic_feedback_starts_new_task_instead(tmp_path: Path) -> None:
    payload = _payload(
        tmp_path,
        _run_dir(tmp_path, quality="final too generic\n"),
        feedback="new topic: ignore previous and research a different topic",
    )

    assert payload["status"] == report.PASS_REPORT_ONLY_NEW_TASK_ADVISED
    assert payload["quality_verdict"] == report.REPORT_ONLY_START_NEW_TASK_INSTEAD
    assert "TOPIC_REFINEMENT" not in payload["suggested_next_action"]
    _assert_all_no_flags(payload)


def test_process_checks_all_no_flags_true_for_refinement_case(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _run_dir(tmp_path, quality="calibration not absorbed caveat not absorbed\n"))

    _assert_all_no_flags(payload)
    assert payload["user_confirmation_required"] is True
    assert "does not mean adoption" in (tmp_path / "out" / report.REPORT_MD).read_text(encoding="utf-8")


def test_missing_obligation_positive_advisory(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _run_dir(tmp_path, quality="missing obligation\n"))

    assert payload["status"] == report.PASS_REPORT_ONLY_ADVISORY_GENERATED


def test_convergence_not_absorbed_positive_advisory(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _run_dir(tmp_path, convergence="convergence not absorbed\n"))

    assert payload["status"] == report.PASS_REPORT_ONLY_ADVISORY_GENERATED
    assert payload["suggested_refinement_mode"] == "final_absorption_pass"


def test_calibration_caveat_hidden_positive_advisory(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _run_dir(tmp_path, calibration="calibration not absorbed hidden caveat\n"))

    assert payload["status"] == report.PASS_REPORT_ONLY_ADVISORY_GENERATED
    assert payload["suggested_refinement_mode"] == "final_absorption_pass"


def test_same_topic_user_asks_deeper_positive_advisory(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _run_dir(tmp_path), feedback="same topic deeper, make this more specific")

    assert payload["status"] == report.PASS_REPORT_ONLY_ADVISORY_GENERATED
    assert payload["suggested_refinement_mode"] == "user_feedback_refinement"
