from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from tools import topic_refinement_post_final_advisory_detector as detector


REPO_ROOT = Path(__file__).resolve().parents[2]
DETECTOR_SOURCE = REPO_ROOT / "tools/topic_refinement_post_final_advisory_detector.py"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_dir(
    tmp_path: Path,
    *,
    final: str = "Final answer with specific recommendation, rationale, and caveats.\n",
    quality: str = "Quality review: high-quality final; no clear quality issue.\n",
    convergence: str = "",
    calibration: str = "",
    evidence: str = "",
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
    if failure:
        (run_dir / "failure_report.md").write_text(failure, encoding="utf-8")
    (run_dir / "original_user_question.txt").write_text("Original user question?\n", encoding="utf-8")
    return run_dir


def _result(tmp_path: Path, run_dir: Path, *, feedback: str = "", topic_state: Path | None = None):
    return detector.analyze_post_final_advisory(
        run_dir=run_dir,
        topic_id="topic-1",
        output_dir=tmp_path / "out",
        user_feedback=feedback,
        topic_state=topic_state,
    )


@pytest.mark.parametrize(
    "label,run_kwargs,feedback,expected_status,expected_verdict",
    [
        ("new topic", {}, "新问题：换个话题研究另外一个产品。", detector.STATUS_NEW_TOPIC, detector.VERDICT_START_NEW_TASK),
        ("full rerun", {}, "full rerun the Research/Decision pipeline", detector.STATUS_NEW_TOPIC, detector.VERDICT_START_NEW_TASK),
        ("source acquisition request", {}, "please perform source acquisition", detector.STATUS_SOURCE_NEED, detector.VERDICT_AUTHORIZE_SOURCE),
        ("full-text verification request", {}, "perform full-text verification request", detector.STATUS_SOURCE_NEED, detector.VERDICT_AUTHORIZE_SOURCE),
        ("push release task", {}, "push/release this branch", detector.STATUS_NEW_TOPIC, detector.VERDICT_START_NEW_TASK),
        ("final controller repair", {}, "final controller repair needed", detector.STATUS_NEW_TOPIC, detector.VERDICT_START_NEW_TASK),
        ("evidence packet repair", {}, "evidence packet repair needed", detector.STATUS_NEW_TOPIC, detector.VERDICT_START_NEW_TASK),
        ("environment-only task", {}, "environment-only task: DDGS missing", detector.STATUS_ENVIRONMENT, detector.VERDICT_FIX_ENVIRONMENT),
        ("already high-quality final", {}, "", detector.STATUS_NO_REFINEMENT, detector.VERDICT_DO_NOT_REFINE),
        ("insufficient artifacts signal", {"quality": "insufficient artifacts to advise\n"}, "", detector.STATUS_INSUFFICIENT, detector.VERDICT_BLOCKED_CONTEXT),
        ("general advice", {}, "general advice about leadership", detector.STATUS_NEW_TOPIC, detector.VERDICT_START_NEW_TASK),
        ("travel migration", {}, "travel migration / unrelated domain task", detector.STATUS_NEW_TOPIC, detector.VERDICT_START_NEW_TASK),
    ],
)
def test_negative_advisory_cases_do_not_suggest_topic_refinement(
    tmp_path: Path,
    label: str,
    run_kwargs: dict,
    feedback: str,
    expected_status: str,
    expected_verdict: str,
) -> None:
    del label
    result = _result(tmp_path, _run_dir(tmp_path, **run_kwargs), feedback=feedback)

    assert result.exit_code == 0
    assert result.payload["advisory_status"] == expected_status
    assert result.payload["advisory_verdict"] == expected_verdict
    assert result.payload["advisory_status"] != detector.STATUS_TOPIC_REFINEMENT


def test_negative_no_final_v1_blocks(tmp_path: Path) -> None:
    result = _result(tmp_path, _run_dir(tmp_path, include_final=False))

    assert result.exit_code != 0
    assert result.payload["status"] == detector.BLOCKED_MISSING_FINAL_V1


def test_negative_no_quality_review_blocks(tmp_path: Path) -> None:
    result = _result(tmp_path, _run_dir(tmp_path, include_quality=False))

    assert result.exit_code != 0
    assert result.payload["status"] == detector.BLOCKED_MISSING_QUALITY_REVIEW


def test_negative_topic_mismatch_blocks(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"topic_id": "other-topic", "run_dir": str(run_dir)}), encoding="utf-8")

    result = _result(tmp_path, run_dir, topic_state=state)

    assert result.exit_code != 0
    assert result.payload["status"] == detector.BLOCKED_TOPIC_STATE_RUN_DIR_MISMATCH


def test_false_positive_new_topic_never_suggests_topic_refinement(tmp_path: Path) -> None:
    result = _result(tmp_path, _run_dir(tmp_path, quality="final too generic\n"), feedback="new topic, ignore previous")

    assert result.payload["advisory_status"] == detector.STATUS_NEW_TOPIC
    assert result.payload.get("suggested_next_action") != "explicit_TOPIC_REFINEMENT_after_user_confirmation"


def test_false_positive_source_need_outranks_rewrite(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        _run_dir(
            tmp_path,
            quality="final too generic with missing obligation\n",
            evidence="snippet full-text verification unsupported evidence gap\n",
        ),
        feedback="same topic refine",
    )

    assert result.payload["advisory_status"] == detector.STATUS_SOURCE_NEED
    assert result.payload["confidence_upgrade_allowed"] is False
    assert result.payload["suggested_next_action"] == "source_need_or_full_text_verification"


def test_false_positive_environment_outranks_source_and_llm_candidate(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        _run_dir(
            tmp_path,
            quality="final too generic\n",
            evidence="snippet full-text verification required\n",
            failure="executor_resource_exhausted and service unhealthy\n",
        ),
        feedback="same topic refine",
    )

    assert result.payload["advisory_status"] == detector.STATUS_ENVIRONMENT
    assert result.payload["suggested_next_action"] == "environment_triage"
    assert result.payload["no_llm_called"] is True
    assert result.payload["no_candidate_generated"] is True


def test_false_negative_missing_obligation_is_caught(tmp_path: Path) -> None:
    result = _result(tmp_path, _run_dir(tmp_path, quality="missing obligation: user asked for ranking and final omitted it\n"))

    assert result.payload["advisory_status"] == detector.STATUS_TOPIC_REFINEMENT
    assert "missing obligation" in result.payload["detected_semantic_quality_issues"]


def test_false_negative_convergence_loss_is_caught(tmp_path: Path) -> None:
    result = _result(tmp_path, _run_dir(tmp_path, convergence="convergence_to_final_specificity_loss: convergence not absorbed\n"))

    assert result.payload["advisory_status"] == detector.STATUS_TOPIC_REFINEMENT
    assert result.payload["suggested_refinement_mode"] == "final_absorption_pass"


def test_false_negative_hidden_calibration_caveat_is_caught(tmp_path: Path) -> None:
    result = _result(tmp_path, _run_dir(tmp_path, calibration="evidence caveat hidden; caveat not absorbed by final\n"))

    assert result.payload["advisory_status"] == detector.STATUS_TOPIC_REFINEMENT
    assert "caveat not absorbed" in result.payload["detected_semantic_quality_issues"]


def test_process_advisory_only_no_candidate_or_adapter_outputs(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="final too generic\n")
    result = _result(tmp_path, run_dir)
    out = tmp_path / "out"

    assert result.payload["advisory_status"] == detector.STATUS_TOPIC_REFINEMENT
    assert (out / detector.REPORT_JSON).exists()
    assert not (out / "adapter_result.json").exists()
    assert not (out / "manual_task_report.json").exists()
    assert not (out / "revised_final_v2.md").exists()
    assert not (out / "candidate_output").exists()


def test_process_topic_refinement_suggestion_requires_user_confirmation(tmp_path: Path) -> None:
    result = _result(tmp_path, _run_dir(tmp_path, quality="low specificity\n"))

    assert result.payload["advisory_status"] == detector.STATUS_TOPIC_REFINEMENT
    assert result.payload["requires_user_confirmation"] is True
    assert result.payload["auto_execution"] is False
    assert result.payload["auto_adoption"] is False
    assert result.payload["allowed_next_step"] == "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"


def test_process_no_llm_no_pipeline_no_candidate_flags(tmp_path: Path) -> None:
    result = _result(tmp_path, _run_dir(tmp_path, evidence="source need due to weak evidence\n"))

    assert result.payload["no_llm_called"] is True
    assert result.payload["no_adapter_called"] is True
    assert result.payload["no_pipeline_rerun"] is True
    assert result.payload["no_candidate_generated"] is True
    assert result.payload["no_final_rewritten"] is True


def test_final_v1_hash_unchanged(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, quality="final too generic\n")
    final_v1 = run_dir / "final_controller_report.md"
    before = _sha(final_v1)

    result = _result(tmp_path, run_dir)

    assert result.exit_code == 0
    assert _sha(final_v1) == before
    assert result.payload["artifact_hashes"]["final_v1"] == before


def test_runtime_safety_import_has_no_side_effects() -> None:
    module = importlib.reload(detector)

    assert module.MODEL_OR_DETECTOR_USED == "deterministic"
    assert module.REPORT_JSON == detector.REPORT_JSON


def test_runtime_safety_no_adapter_manual_or_runtime_imports() -> None:
    source = DETECTOR_SOURCE.read_text(encoding="utf-8")
    forbidden = [
        "import tools.topic_refinement_registry_adapter",
        "from tools import topic_refinement_registry_adapter",
        "import tools.topic_refinement_manual_task",
        "from tools import topic_refinement_manual_task",
        "import final_controller",
        "from final_controller",
        "import task_engine",
        "from task_engine",
        "openai",
        "anthropic",
        "requests",
        "urllib",
    ]

    for token in forbidden:
        assert token not in source


def test_runtime_safety_no_default_route_or_hook_declared() -> None:
    assert not hasattr(detector, "DEFAULT_TASK_MODE")
    assert not hasattr(detector, "AUTO_TRIGGER")
    assert not hasattr(detector, "FINAL_CONTROLLER_HOOK")
