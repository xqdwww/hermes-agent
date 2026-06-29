from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import topic_refinement_manual_task as manual
from tools import topic_refinement_registry_adapter as adapter


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools/topic_refinement_registry_adapter.py"


def _run_dir(tmp_path: Path, *, quality: str = "", calibration: str = "", evidence: str = "", failure: str = "") -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "final_controller_report.md").write_text("final_v1 original\nCaveat: bounded evidence.\n", encoding="utf-8")
    (run_dir / "case_quality_review.md").write_text(quality or "quality review\n", encoding="utf-8")
    if calibration:
        (run_dir / "calibration_report.md").write_text(calibration, encoding="utf-8")
    if evidence:
        (run_dir / "research_evidence_packet.md").write_text(evidence, encoding="utf-8")
    if failure:
        (run_dir / "failure_report.md").write_text(failure, encoding="utf-8")
    (run_dir / "original_user_question.txt").write_text("original question\n", encoding="utf-8")
    return run_dir


def _rewrite_run(tmp_path: Path) -> Path:
    return _run_dir(tmp_path, calibration="overclaim caveat plausible calibration boundary\n")


def _source_need_run(tmp_path: Path) -> Path:
    return _run_dir(
        tmp_path,
        quality="verification_required true snippet_limited true\n",
        evidence="snippet full-text verification unsupported evidence gap\n",
    )


def _candidate(tmp_path: Path, text: str = "new_evidence: none\nCaveat preserved; conditional.\n") -> Path:
    cand = tmp_path / "candidate"
    cand.mkdir()
    (cand / "revised_final_v2.md").write_text(text, encoding="utf-8")
    (cand / "changed_unchanged_traceability.md").write_text(
        "changed_sections: final\nwhat_was_not_changed: final_v1\n",
        encoding="utf-8",
    )
    return cand


def _payload(run_dir: Path, output_dir: Path, feedback: str, **extra) -> dict:
    payload = {
        "task_mode": adapter.TASK_MODE,
        "run_dir": str(run_dir),
        "topic_id": "topic-1",
        "user_feedback": feedback,
        "confirm_same_topic": True,
        "output_dir": str(output_dir),
    }
    payload.update(extra)
    return payload


def _read_adapter_result(output_dir: Path) -> dict:
    return json.loads((output_dir / "adapter_result.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "feedback",
    [
        "继续这个话题，把第 2 部分做实",
        "同一个 run 上，只重写 final 里太泛的架构选择",
        "基于这个 run_dir 做 TOPIC_REFINEMENT",
        "same topic refine",
        "只补这个 topic 的证据边界说明",
        "不要全量重跑，只做 topic refinement",
    ],
)
def test_positive_explicit_invocations_pass_only_with_contract_fields(tmp_path: Path, feedback: str) -> None:
    run_dir = _rewrite_run(tmp_path)
    result = adapter.run_topic_refinement_registry_adapter(_payload(run_dir, tmp_path / "out", feedback))

    assert result["status"] == adapter.PASS_STATUS
    assert result["adapter_mode"] == "explicit_only"
    assert result["no_auto_invocation"] is True
    assert result["no_final_controller_hook"] is True
    assert result["no_pipeline_rerun"] is True
    assert result["no_llm_called"] is True
    assert result["no_source_acquisition"] is True
    assert result["manual_task_result"]["status"] == manual.PASS_MANUAL_TASK_HANDOFF_READY


def test_positive_explicit_candidate_validation_passes_with_validator_gate(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    cand = _candidate(tmp_path)
    result = adapter.run_topic_refinement_registry_adapter(
        _payload(run_dir, tmp_path / "out", "验证这个 candidate refinement", candidate_refinement_dir=str(cand))
    )

    assert result["status"] == adapter.PASS_STATUS
    assert result["validator_mandatory_if_candidate"] is True
    assert result["manual_task_result"]["validator_result"] == "PASS_REFINEMENT_OUTPUT_VALIDATION"
    assert result["manual_task_result"]["usable_candidate"] is True


def test_positive_source_need_stops_without_forced_conclusion(tmp_path: Path) -> None:
    run_dir = _source_need_run(tmp_path)
    result = adapter.run_topic_refinement_registry_adapter(
        _payload(run_dir, tmp_path / "out", "source_need 时停止，不要强写结论")
    )

    assert result["status"] == adapter.PASS_STATUS
    assert result["manual_task_result"]["status"] == manual.PASS_MANUAL_TASK_STOPPED_SOURCE_NEED
    assert result["manual_task_result"]["selected_refinement_mode"] == "targeted_evidence_acquisition"
    assert result["manual_task_result"]["final_v1_overwrite_check"]["pass"] is True


def test_natural_language_prompt_alone_does_not_trigger(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    result = adapter.validate_registry_request({"prompt": "继续这个话题，把第 2 部分做实", "run_dir": str(run_dir)})

    assert result["status"] == adapter.BLOCKED_TASK_MODE_REQUIRED


@pytest.mark.parametrize(
    "label,override,expected_status",
    [
        ("new question", {"user_feedback": "新问题：请研究一个全新的市场进入策略。"}, adapter.BLOCKED_NEW_TOPIC_DETECTED),
        ("different topic", {"user_feedback": "换话题，帮我做另一个行业分析。"}, adapter.BLOCKED_NEW_TOPIC_DETECTED),
        ("research again", {"user_feedback": "重新研究这个问题，全部从头跑一遍。"}, adapter.BLOCKED_FULL_RERUN_REQUESTED),
        ("full rerun", {"user_feedback": "full rerun the Research/Decision pipeline."}, adapter.BLOCKED_FULL_RERUN_REQUESTED),
        ("latest sources", {"user_feedback": "查最新资料并更新所有证据。"}, adapter.BLOCKED_SOURCE_ACQUISITION_REQUESTED),
        ("new report", {"user_feedback": "生成一个新报告，不要看旧 artifacts。"}, adapter.BLOCKED_REPORT_OR_RUNTIME_TASK),
        ("environment repair", {"user_feedback": "修 environment blocker / DDGS missing。"}, adapter.BLOCKED_REPORT_OR_RUNTIME_TASK),
        ("general advice", {"user_feedback": "Give me general advice about this topic."}, adapter.BLOCKED_REPORT_OR_RUNTIME_TASK),
        ("travel migration", {"user_feedback": "Do the Travel-specific migration now."}, adapter.BLOCKED_REPORT_OR_RUNTIME_TASK),
        ("source acquisition", {"user_feedback": "Please acquire new sources for this claim."}, adapter.BLOCKED_SOURCE_ACQUISITION_REQUESTED),
        ("full text verification", {"user_feedback": "Perform full-text verification for these papers."}, adapter.BLOCKED_FULL_TEXT_VERIFICATION_REQUESTED),
        ("final controller repair", {"user_feedback": "Repair the final controller implementation."}, adapter.BLOCKED_REPORT_OR_RUNTIME_TASK),
        ("evidence packet repair", {"user_feedback": "Repair the evidence packet generator."}, adapter.BLOCKED_REPORT_OR_RUNTIME_TASK),
        ("blind set", {"user_feedback": "Run blind-set validation."}, adapter.BLOCKED_REPORT_OR_RUNTIME_TASK),
        ("push release", {"user_feedback": "Push/release this branch."}, adapter.BLOCKED_REPORT_OR_RUNTIME_TASK),
        ("no run_dir", {"run_dir": None}, adapter.BLOCKED_MISSING_RUN_CONTEXT),
        ("no user_feedback", {"user_feedback": " "}, adapter.BLOCKED_MISSING_USER_FEEDBACK),
        ("confirm false", {"confirm_same_topic": False}, adapter.BLOCKED_SAME_TOPIC_NOT_CONFIRMED),
        ("task mode missing", {"task_mode": None}, adapter.BLOCKED_TASK_MODE_REQUIRED),
        ("research decision", {"task_mode": "RESEARCH_DECISION"}, adapter.BLOCKED_UNSUPPORTED_TASK_MODE),
    ],
)
def test_negative_triggers_block(tmp_path: Path, label: str, override: dict, expected_status: str) -> None:
    del label
    run_dir = _rewrite_run(tmp_path)
    payload = _payload(run_dir, tmp_path / "out", "继续这个话题")
    payload.update(override)
    if payload.get("run_dir") is None:
        payload.pop("run_dir")
    if payload.get("task_mode") is None:
        payload.pop("task_mode")

    result = adapter.validate_registry_request(payload)

    assert result["status"] == expected_status


@pytest.mark.parametrize("task_mode", ["RESEARCH", "DECISION", "RESEARCH_DECISION"])
def test_research_decision_modes_are_not_accepted(tmp_path: Path, task_mode: str) -> None:
    run_dir = _rewrite_run(tmp_path)
    result = adapter.validate_registry_request(_payload(run_dir, tmp_path / "out", "same topic refine", task_mode=task_mode))

    assert result["status"] == adapter.BLOCKED_UNSUPPORTED_TASK_MODE


def test_dry_run_false_blocks_first_adapter_stub(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    result = adapter.validate_registry_request(_payload(run_dir, tmp_path / "out", "same topic refine", dry_run=False))

    assert result["status"] == adapter.BLOCKED_DRY_RUN_REQUIRED


def test_allow_llm_refinement_true_requires_existing_candidate_dir(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    result = adapter.validate_registry_request(_payload(run_dir, tmp_path / "out", "same topic refine", allow_llm_refinement=True))

    assert result["status"] == adapter.BLOCKED_LLM_REFINEMENT_NOT_ALLOWED


def test_allow_llm_refinement_true_with_candidate_still_does_not_call_llm(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    cand = _candidate(tmp_path)
    result = adapter.run_topic_refinement_registry_adapter(
        _payload(run_dir, tmp_path / "out", "验证这个 candidate refinement", candidate_refinement_dir=str(cand), allow_llm_refinement=True)
    )

    assert result["status"] == adapter.PASS_STATUS
    assert result["no_llm_called"] is True
    assert result["manual_task_result"]["no_llm_called"] is True


def test_topic_state_path_can_supply_run_context(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    state = tmp_path / "topic_state.json"
    state.write_text(json.dumps({"artifact_paths": {"final_v1": str(run_dir / "final_controller_report.md")}}), encoding="utf-8")
    payload = _payload(run_dir, tmp_path / "out", "same topic refine")
    payload.pop("run_dir")
    payload["topic_state_path"] = str(state)

    result = adapter.run_topic_refinement_registry_adapter(payload)

    assert result["status"] == adapter.PASS_STATUS
    assert result["run_dir"] == str(run_dir)


def test_output_contains_required_adapter_fields(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    result = adapter.run_topic_refinement_registry_adapter(_payload(run_dir, tmp_path / "out", "same topic refine"))
    written = _read_adapter_result(tmp_path / "out")

    for key in [
        "status",
        "quality_verdict",
        "adapter_mode",
        "task_mode",
        "manual_task_result",
        "selected_failure_type",
        "selected_refinement_mode",
        "no_auto_invocation",
        "no_final_controller_hook",
        "no_pipeline_rerun",
        "no_llm_called",
        "no_source_acquisition",
        "validator_mandatory_if_candidate",
    ]:
        assert key in result
        assert key in written


def test_cli_invocation_writes_adapter_reports(tmp_path: Path) -> None:
    run_dir = _rewrite_run(tmp_path)
    request = tmp_path / "request.json"
    output_dir = tmp_path / "out"
    request.write_text(json.dumps(_payload(run_dir, output_dir, "same topic refine")), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--request-json", str(request), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert adapter.PASS_STATUS in completed.stdout
    assert (output_dir / "adapter_result.json").exists()
    assert (output_dir / "adapter_result.md").exists()


def test_adapter_source_has_no_runtime_registry_or_pipeline_imports() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "tools.task_engine_runner",
        "tools.task_mode_runtime",
        "tools.research_pipeline_runner",
        "research_pipeline_runner",
        "register_task_mode",
        "from tools import final_controller",
    ]
    assert not any(token in source for token in forbidden)
