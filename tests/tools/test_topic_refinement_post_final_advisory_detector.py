from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import topic_refinement_post_final_advisory_detector as detector


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools/topic_refinement_post_final_advisory_detector.py"


def _run_dir(
    tmp_path: Path,
    *,
    final: str = "Final answer with concrete recommendations.\n",
    quality: str = "Quality review: acceptable and specific.\n",
    convergence: str = "",
    calibration: str = "",
    evidence: str = "",
    runner: str = "",
    failure: str = "",
    include_final: bool = True,
    include_quality: bool = True,
) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
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
    (run_dir / "original_user_question.txt").write_text("Original question?\n", encoding="utf-8")
    return run_dir


def _advisory(tmp_path: Path, run_dir: Path, *, topic_id: str = "topic-1", feedback: str = "", topic_state: Path | None = None) -> dict:
    result = detector.analyze_post_final_advisory(
        run_dir=run_dir,
        topic_id=topic_id,
        output_dir=tmp_path / "out",
        topic_state=topic_state,
        user_feedback=feedback,
    )
    assert result.exit_code == 0
    return result.payload


def _blocked(tmp_path: Path, run_dir: Path, *, topic_id: str = "topic-1", topic_state: Path | None = None) -> dict:
    result = detector.analyze_post_final_advisory(
        run_dir=run_dir,
        topic_id=topic_id,
        output_dir=tmp_path / "out",
        topic_state=topic_state,
    )
    assert result.exit_code != 0
    return result.payload


def test_success_with_final_v1_and_quality_review(tmp_path: Path) -> None:
    payload = _advisory(tmp_path, _run_dir(tmp_path))

    assert payload["advisory_status"] == detector.STATUS_NO_REFINEMENT
    assert payload["advisory_verdict"] == detector.VERDICT_DO_NOT_REFINE
    assert (tmp_path / "out" / detector.REPORT_JSON).exists()
    assert (tmp_path / "out" / detector.REPORT_MD).exists()


def test_output_json_contains_required_fields(tmp_path: Path) -> None:
    payload = _advisory(tmp_path, _run_dir(tmp_path, quality="final too generic and low specificity\n"))
    required = {
        "advisory_status",
        "advisory_verdict",
        "topic_id",
        "run_dir",
        "artifact_paths",
        "detected_hard_boundaries",
        "detected_semantic_quality_issues",
        "suggested_next_action",
        "suggested_failure_type",
        "suggested_refinement_mode",
        "source_need",
        "environment_triage_needed",
        "confidence_upgrade_allowed",
        "requires_user_confirmation",
        "auto_execution",
        "auto_adoption",
        "allowed_next_step",
        "disallowed_next_steps",
        "reason_summary",
        "evidence_boundary_summary",
        "calibration_boundary_summary",
        "semantic_depth_summary",
        "model_or_detector_used",
        "detector_confidence",
        "false_positive_risk",
        "false_negative_risk",
        "no_llm_called",
        "no_adapter_called",
        "no_pipeline_rerun",
        "no_candidate_generated",
        "no_final_rewritten",
    }

    assert required <= set(payload)
    assert payload["model_or_detector_used"] == "deterministic"


def test_process_flags_are_true(tmp_path: Path) -> None:
    payload = _advisory(tmp_path, _run_dir(tmp_path, quality="missing obligation\n"))

    assert payload["no_llm_called"] is True
    assert payload["no_adapter_called"] is True
    assert payload["no_pipeline_rerun"] is True
    assert payload["no_candidate_generated"] is True
    assert payload["no_final_rewritten"] is True
    assert payload["auto_execution"] is False
    assert payload["auto_adoption"] is False


def test_missing_final_v1_blocks(tmp_path: Path) -> None:
    payload = _blocked(tmp_path, _run_dir(tmp_path, include_final=False))

    assert payload["status"] == detector.BLOCKED_MISSING_FINAL_V1
    assert (tmp_path / "out" / detector.BLOCKED_JSON).exists()


def test_missing_quality_review_blocks(tmp_path: Path) -> None:
    payload = _blocked(tmp_path, _run_dir(tmp_path, include_quality=False))

    assert payload["status"] == detector.BLOCKED_MISSING_QUALITY_REVIEW


def test_output_already_exists_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / detector.REPORT_JSON).write_text("{}\n", encoding="utf-8")

    result = detector.analyze_post_final_advisory(run_dir=run_dir, topic_id="topic-1", output_dir=out)

    assert result.exit_code != 0
    assert result.payload["status"] == detector.BLOCKED_OUTPUT_ALREADY_EXISTS


def test_empty_topic_id_blocks(tmp_path: Path) -> None:
    payload = _blocked(tmp_path, _run_dir(tmp_path), topic_id=" ")

    assert payload["status"] == detector.BLOCKED_INVALID_TOPIC_ID


def test_run_dir_missing_blocks(tmp_path: Path) -> None:
    result = detector.analyze_post_final_advisory(run_dir=tmp_path / "missing", topic_id="topic-1", output_dir=tmp_path / "out")

    assert result.exit_code != 0
    assert result.payload["status"] == detector.BLOCKED_RUN_DIR_MISSING


def test_artifact_path_escape_blocks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside_final = tmp_path / "outside_final.md"
    outside_final.write_text("final\n", encoding="utf-8")
    try:
        (run_dir / "final_controller_report.md").symlink_to(outside_final)
    except OSError:
        pytest.skip("symlinks are not available in this environment")
    (run_dir / "case_quality_review.md").write_text("quality review\n", encoding="utf-8")

    payload = _blocked(tmp_path, run_dir)

    assert payload["status"] == detector.BLOCKED_ARTIFACT_PATH_ESCAPE


def test_invalid_topic_state_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    state = tmp_path / "bad_state.json"
    state.write_text("{not json", encoding="utf-8")

    payload = _blocked(tmp_path, run_dir, topic_state=state)

    assert payload["status"] == detector.BLOCKED_INVALID_TOPIC_STATE


def test_topic_state_run_dir_mismatch_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"topic_id": "topic-1", "run_dir": str(other)}), encoding="utf-8")

    payload = _blocked(tmp_path, run_dir, topic_state=state)

    assert payload["status"] == detector.BLOCKED_TOPIC_STATE_RUN_DIR_MISMATCH


def test_cli_invocation_writes_advisory_reports(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="final too generic\n")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-dir",
            str(run_dir),
            "--topic-id",
            "topic-1",
            "--output-dir",
            str(out),
            "--user-feedback",
            "same topic refine",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert detector.STATUS_TOPIC_REFINEMENT in completed.stdout
    assert (out / detector.REPORT_JSON).exists()
    assert (out / detector.REPORT_MD).exists()


@pytest.mark.parametrize(
    "quality,convergence,calibration,evidence,feedback,expected_mode",
    [
        ("final too generic\n", "", "", "", "", "section_rewrite"),
        ("missing obligation\n", "", "", "", "", "section_rewrite"),
        ("", "convergence not absorbed\n", "", "", "", "final_absorption_pass"),
        ("", "", "calibration not absorbed\n", "", "", "final_absorption_pass"),
        ("weak priority and weak ranking\n", "", "", "", "", "section_rewrite"),
        ("evidence caveat hidden; caveat not absorbed\n", "", "", "", "", "section_rewrite"),
        ("", "", "", "", "same topic deeper work, make the same answer more specific", "user_feedback_refinement"),
        ("candidate validation needed for candidate refinement\n", "", "", "", "", "section_rewrite"),
    ],
)
def test_positive_quality_advisories_suggest_topic_refinement(
    tmp_path: Path,
    quality: str,
    convergence: str,
    calibration: str,
    evidence: str,
    feedback: str,
    expected_mode: str,
) -> None:
    payload = _advisory(
        tmp_path,
        _run_dir(tmp_path, quality=quality or "quality review\n", convergence=convergence, calibration=calibration, evidence=evidence),
        feedback=feedback,
    )

    assert payload["advisory_status"] == detector.STATUS_TOPIC_REFINEMENT
    assert payload["advisory_verdict"] == detector.VERDICT_CONFIRM_REFINEMENT
    assert payload["suggested_refinement_mode"] == expected_mode
    assert payload["requires_user_confirmation"] is True


def test_positive_source_need_advisory(tmp_path: Path) -> None:
    payload = _advisory(
        tmp_path,
        _run_dir(tmp_path, evidence="snippet-backed weak evidence with full-text verification required and evidence gap\n"),
    )

    assert payload["advisory_status"] == detector.STATUS_SOURCE_NEED
    assert payload["advisory_verdict"] == detector.VERDICT_AUTHORIZE_SOURCE
    assert payload["confidence_upgrade_allowed"] is False
    assert payload["source_need"] is True


def test_positive_environment_advisory(tmp_path: Path) -> None:
    payload = _advisory(tmp_path, _run_dir(tmp_path, failure="DDGS missing; environment blocker\n"))

    assert payload["advisory_status"] == detector.STATUS_ENVIRONMENT
    assert payload["advisory_verdict"] == detector.VERDICT_FIX_ENVIRONMENT
    assert payload["environment_triage_needed"] is True
