from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import topic_refinement_post_final_advisory_detector as detector
from tools import topic_refinement_post_final_advisory_report as report


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools/topic_refinement_post_final_advisory_report.py"


def _run_dir(
    tmp_path: Path,
    *,
    final: str = "Final answer with concrete recommendations.\n",
    quality: str = "Quality review: acceptable and specific.\n",
    convergence: str = "",
    calibration: str = "",
    evidence: str = "",
    runner: str = '{"pipeline_status":"PIPELINE_COMPLETE"}\n',
    failure: str = "",
    include_final: bool = True,
    include_quality: bool = True,
) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    if include_final:
        (run_dir / "final_controller_report.md").write_text(final, encoding="utf-8")
    if include_quality:
        (run_dir / "case_quality_review.md").write_text(quality, encoding="utf-8")
    if convergence:
        (run_dir / "convergence_report.md").write_text(convergence, encoding="utf-8")
    if calibration:
        (run_dir / "calibration_report.md").write_text(calibration, encoding="utf-8")
    if evidence:
        (run_dir / "research_evidence_packet.md").write_text(evidence, encoding="utf-8")
    if runner:
        (run_dir / "runner_result.json").write_text(runner, encoding="utf-8")
    if failure:
        (run_dir / "failure_report.md").write_text(failure, encoding="utf-8")
    (run_dir / "original_user_question.txt").write_text("Original user question\n", encoding="utf-8")
    return run_dir


def _generate(tmp_path: Path, run_dir: Path, *, topic_id: str = "topic-1", feedback: str = "", topic_state: Path | None = None) -> report.ReportOnlyResult:
    return report.generate_post_final_topic_refinement_advisory_report(
        run_dir=run_dir,
        topic_id=topic_id,
        output_dir=tmp_path / "out",
        user_feedback=feedback,
        topic_state=topic_state,
    )


def _payload(tmp_path: Path, run_dir: Path, **kwargs) -> dict:
    result = _generate(tmp_path, run_dir, **kwargs)
    assert result.exit_code == 0
    return result.payload


def test_report_only_wrapper_success_for_topic_refinement_suggested(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="final too generic and low specificity\n")
    payload = _payload(tmp_path, run_dir, feedback="same topic refine")

    assert payload["status"] == report.PASS_REPORT_ONLY_ADVISORY_GENERATED
    assert payload["quality_verdict"] == report.REPORT_ONLY_ADVISORY_READY_FOR_USER_CONFIRMATION
    assert payload["detector_advisory_status"] == detector.STATUS_TOPIC_REFINEMENT
    assert payload["suggested_next_action"] == "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"


def test_writes_report_only_markdown_and_json(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="missing obligation\n")
    result = _generate(tmp_path, run_dir)

    assert result.exit_code == 0
    assert (tmp_path / "out" / report.REPORT_JSON).exists()
    assert (tmp_path / "out" / report.REPORT_MD).exists()


def test_detector_output_is_preserved_under_detector_output(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="weak ranking\n")
    _payload(tmp_path, run_dir)

    detector_dir = tmp_path / "out" / report.DETECTOR_OUTPUT_DIR
    assert (detector_dir / detector.REPORT_JSON).exists()
    assert (detector_dir / detector.REPORT_MD).exists()


def test_topic_refinement_requires_user_confirmation(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="final too generic\n")
    payload = _payload(tmp_path, run_dir)

    assert payload["user_confirmation_required"] is True
    assert "确认只表示允许生成/验证 candidate" in payload["user_confirmation_question"]
    assert "不表示自动采纳" in payload["user_confirmation_question"]


def test_process_flags_are_report_only(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="missing obligation\n")
    payload = _payload(tmp_path, run_dir)

    assert payload["auto_execution"] is False
    assert payload["auto_adoption"] is False
    assert payload["no_adapter_called"] is True
    assert payload["no_manual_task_called"] is True
    assert payload["no_llm_called"] is True
    assert payload["no_pipeline_rerun"] is True
    assert payload["no_candidate_generated"] is True
    assert payload["no_final_rewritten"] is True


@pytest.mark.parametrize(
    "kwargs,expected_status,expected_quality,confirmation",
    [
        ({"evidence": "snippet full-text verification unsupported evidence gap\n"}, report.PASS_REPORT_ONLY_SOURCE_NEED_ADVISED, report.REPORT_ONLY_STOP_SOURCE_OR_ENVIRONMENT, True),
        ({"failure": "executor_resource_exhausted environment blocker\n"}, report.PASS_REPORT_ONLY_ENVIRONMENT_TRIAGE_ADVISED, report.REPORT_ONLY_STOP_SOURCE_OR_ENVIRONMENT, True),
        ({}, report.PASS_REPORT_ONLY_NO_REFINEMENT_ADVISED, report.REPORT_ONLY_NO_ACTION_RECOMMENDED, False),
        ({"quality": "final too generic\n"}, report.PASS_REPORT_ONLY_NEW_TASK_ADVISED, report.REPORT_ONLY_START_NEW_TASK_INSTEAD, False),
        ({"quality": "insufficient artifacts but final and quality exist\n"}, report.BLOCKED_INVALID_INPUT, report.REPORT_ONLY_NEEDS_REPAIR, False),
    ],
)
def test_status_mapping(tmp_path: Path, kwargs: dict, expected_status: str, expected_quality: str, confirmation: bool) -> None:
    feedback = "new topic: ignore previous" if expected_status == report.PASS_REPORT_ONLY_NEW_TASK_ADVISED else ""
    run_dir = _run_dir(tmp_path, **kwargs)
    result = _generate(tmp_path, run_dir, feedback=feedback)

    assert result.payload["status"] == expected_status
    assert result.payload["quality_verdict"] == expected_quality
    assert result.payload["user_confirmation_required"] is confirmation


def test_source_need_maps_to_stop_not_rewrite(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="final too generic\n", evidence="source_need snippet-backed unsupported\n")
    payload = _payload(tmp_path, run_dir)

    assert payload["status"] == report.PASS_REPORT_ONLY_SOURCE_NEED_ADVISED
    assert payload["suggested_next_action"] == "ask_user_to_authorize_source_or_full_text_verification"
    assert payload["suggested_next_action"] != "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"


def test_environment_maps_to_triage_not_rewrite(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="missing obligation\n", failure="ModuleNotFoundError service unhealthy\n")
    payload = _payload(tmp_path, run_dir)

    assert payload["status"] == report.PASS_REPORT_ONLY_ENVIRONMENT_TRIAGE_ADVISED
    assert payload["suggested_next_action"] == "ask_user_to_fix_environment"


def test_no_refinement_has_no_confirmation(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _run_dir(tmp_path))

    assert payload["status"] == report.PASS_REPORT_ONLY_NO_REFINEMENT_ADVISED
    assert payload["user_confirmation_required"] is False


def test_new_topic_feedback_starts_new_task_instead(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="final too generic\n")
    payload = _payload(tmp_path, run_dir, feedback="换个话题，新问题")

    assert payload["status"] == report.PASS_REPORT_ONLY_NEW_TASK_ADVISED
    assert payload["detector_advisory_status"] == detector.STATUS_NEW_TOPIC


def test_insufficient_artifacts_status_is_safe(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="insufficient artifacts\n")
    result = _generate(tmp_path, run_dir)

    assert result.exit_code != 0
    assert result.payload["status"] == report.BLOCKED_INVALID_INPUT
    assert "artifacts" in result.payload["advisory_display_status"].lower()


def test_markdown_says_user_confirmation_is_not_adoption(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="missing obligation\n")
    _payload(tmp_path, run_dir)
    text = (tmp_path / "out" / report.REPORT_MD).read_text(encoding="utf-8")

    assert "User confirmation does not mean adoption" in text
    assert "not candidate adoption" in text or "不表示自动采纳" in text


def test_markdown_says_no_automatic_execution(tmp_path: Path) -> None:
    _payload(tmp_path, _run_dir(tmp_path, quality="weak priority\n"))
    text = (tmp_path / "out" / report.REPORT_MD).read_text(encoding="utf-8")

    assert "no automatic execution" in text
    assert "was not executed" in text


def test_markdown_says_no_final_rewrite(tmp_path: Path) -> None:
    _payload(tmp_path, _run_dir(tmp_path, quality="weak ranking\n"))
    text = (tmp_path / "out" / report.REPORT_MD).read_text(encoding="utf-8")

    assert "no final rewrite" in text
    assert "does not generate a candidate or revised final" in text


def test_source_need_markdown_says_confidence_cannot_be_upgraded(tmp_path: Path) -> None:
    _payload(tmp_path, _run_dir(tmp_path, evidence="full-text verification unsupported evidence gap\n"))
    text = (tmp_path / "out" / report.REPORT_MD).read_text(encoding="utf-8")

    assert "Confidence cannot be upgraded from current artifacts" in text


def test_followup_command_is_present_but_not_executed(tmp_path: Path) -> None:
    payload = _payload(tmp_path, _run_dir(tmp_path, quality="missing obligation\n"))

    assert "tools/topic_refinement_registry_adapter.py" in payload["recommended_followup_command"]
    assert not (tmp_path / "out" / "explicit_topic_refinement_adapter_output").exists()


def test_missing_run_dir_blocks(tmp_path: Path) -> None:
    result = report.generate_post_final_topic_refinement_advisory_report(
        run_dir=tmp_path / "missing",
        topic_id="topic-1",
        output_dir=tmp_path / "out",
    )

    assert result.exit_code != 0
    assert result.payload["status"] == report.BLOCKED_RUN_DIR_MISSING
    assert (tmp_path / "out" / report.BLOCKED_JSON).exists()


def test_empty_topic_id_blocks(tmp_path: Path) -> None:
    result = _generate(tmp_path, _run_dir(tmp_path), topic_id=" ")

    assert result.exit_code != 0
    assert result.payload["status"] == report.BLOCKED_INVALID_TOPIC_ID


def test_output_already_exists_blocks(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / report.REPORT_JSON).write_text("{}\n", encoding="utf-8")

    result = report.generate_post_final_topic_refinement_advisory_report(
        run_dir=_run_dir(tmp_path),
        topic_id="topic-1",
        output_dir=out,
    )

    assert result.exit_code != 0
    assert result.payload["status"] == report.BLOCKED_OUTPUT_ALREADY_EXISTS


def test_detector_failure_blocks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeDetectorResult:
        exit_code = 2
        payload = {"status": "UNEXPECTED_DETECTOR_FAILURE", "reason": "boom"}

    monkeypatch.setattr(report.detector, "analyze_post_final_advisory", lambda **kwargs: FakeDetectorResult())
    result = _generate(tmp_path, _run_dir(tmp_path))

    assert result.exit_code != 0
    assert result.payload["status"] == report.BLOCKED_DETECTOR_FAILED


def test_invalid_topic_state_blocks(tmp_path: Path) -> None:
    state = tmp_path / "bad_state.json"
    state.write_text("{not json", encoding="utf-8")
    result = _generate(tmp_path, _run_dir(tmp_path), topic_state=state)

    assert result.exit_code != 0
    assert result.payload["status"] == report.BLOCKED_INVALID_TOPIC_STATE


def test_missing_final_or_quality_blocks_as_missing_required_artifacts(tmp_path: Path) -> None:
    final_missing = _generate(tmp_path / "a", _run_dir(tmp_path / "a", include_final=False))
    quality_missing = _generate(tmp_path / "b", _run_dir(tmp_path / "b", include_quality=False))

    assert final_missing.payload["status"] == report.BLOCKED_MISSING_REQUIRED_ARTIFACTS
    assert quality_missing.payload["status"] == report.BLOCKED_MISSING_REQUIRED_ARTIFACTS


def test_module_does_not_import_task_engine_runtime() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "task_mode_runtime" not in source
    assert "task_engine_runner" not in source
    assert "task_engine_executors" not in source


def test_module_does_not_import_or_call_registry_adapter() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "import topic_refinement_registry_adapter" not in source
    assert "from tools import topic_refinement_registry_adapter" not in source
    assert "run_topic_refinement_registry_adapter" not in source


def test_module_does_not_import_or_call_manual_task_wrapper() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "import topic_refinement_manual_task" not in source
    assert "from tools import topic_refinement_manual_task" not in source
    assert "run_manual_task" not in source


def test_module_has_no_llm_network_or_api_imports() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    forbidden = ["openai", "anthropic", "requests", "httpx", "urllib", "socket", "web_search", "api_key", "API_KEY"]

    assert all(token not in source for token in forbidden)


def test_wrapper_does_not_generate_candidate_output(tmp_path: Path) -> None:
    _payload(tmp_path, _run_dir(tmp_path, quality="final too generic\n"))

    generated = [p.name for p in (tmp_path / "out").rglob("*")]
    assert "candidate_output" not in generated
    assert "revised_final_v2.md" not in generated


def test_cli_success_exit_code_zero(tmp_path: Path) -> None:
    out = tmp_path / "out"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(_run_dir(tmp_path, quality="final too generic\n")), "--topic-id", "topic-1", "--output-dir", str(out)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert report.PASS_REPORT_ONLY_ADVISORY_GENERATED in completed.stdout
    assert (out / report.REPORT_JSON).exists()


def test_cli_blocked_exit_code_nonzero(tmp_path: Path) -> None:
    out = tmp_path / "out"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(tmp_path / "missing"), "--topic-id", "topic-1", "--output-dir", str(out)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert report.BLOCKED_RUN_DIR_MISSING in completed.stdout
    assert (out / report.BLOCKED_JSON).exists()
