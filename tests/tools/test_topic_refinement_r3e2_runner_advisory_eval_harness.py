from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.task_engine_runner as runner
from tools import topic_refinement_post_final_advisory_report as report
from tools.task_engine_contracts import ENGINE_DECISION, PIPELINE_COMPLETE


def _write_fixture(base_dir: Path, *, quality: str = "quality acceptable and specific\n", evidence: str = "", failure: str = "") -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "final_controller_report.md").write_text("Final answer with specific tradeoffs and recommendation.\n", encoding="utf-8")
    (base_dir / "case_quality_review.md").write_text(quality, encoding="utf-8")
    if evidence:
        (base_dir / "research_evidence_packet.md").write_text(evidence, encoding="utf-8")
    if failure:
        (base_dir / "failure_report.md").write_text(failure, encoding="utf-8")
    (base_dir / "runner_result.json").write_text('{"pipeline_status":"PIPELINE_COMPLETE"}\n', encoding="utf-8")
    (base_dir / "original_user_question.txt").write_text("Original user question\n", encoding="utf-8")


def _install(monkeypatch: pytest.MonkeyPatch, *, quality: str = "quality acceptable and specific\n", evidence: str = "", failure: str = "") -> None:
    def fake(mode: str, *, base_dir: str | Path) -> dict:
        _write_fixture(Path(base_dir), quality=quality, evidence=evidence, failure=failure)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_COMPLETE,
            "run": {"mode": mode, "execution_mode": "fake-simulated", "stages": []},
            "validation": {"valid": True},
            "markdown": "pipeline_status=PIPELINE_COMPLETE",
        }

    monkeypatch.setattr(runner, "run_simulated_pipeline", fake)



def _run_with_monkeypatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    query: str = "这是一个决策任务。",
    quality: str = "quality acceptable and specific\n",
    evidence: str = "",
    failure: str = "",
) -> tuple[dict, dict]:
    _install(monkeypatch, quality=quality, evidence=evidence, failure=failure)
    result = json.loads(
        runner.task_engine_runner(
            query=query,
            mode=ENGINE_DECISION,
            action="simulated-run",
            base_dir=str(tmp_path / "run"),
            emit_topic_refinement_advisory=True,
        )
    )
    payload_path = tmp_path / "run" / "topic_refinement_advisory" / report.REPORT_JSON
    blocked_path = tmp_path / "run" / "topic_refinement_advisory" / report.BLOCKED_JSON
    payload = json.loads((payload_path if payload_path.exists() else blocked_path).read_text(encoding="utf-8"))
    return result, payload


@pytest.mark.parametrize(
    "quality,expected_status,expected_next_action",
    [
        ("final too generic low specificity\n", report.PASS_REPORT_ONLY_ADVISORY_GENERATED, "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"),
        ("missing obligation\n", report.PASS_REPORT_ONLY_ADVISORY_GENERATED, "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"),
        ("convergence not absorbed\n", report.PASS_REPORT_ONLY_ADVISORY_GENERATED, "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"),
        ("calibration not absorbed hidden caveat\n", report.PASS_REPORT_ONLY_ADVISORY_GENERATED, "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"),
        ("weak ranking weak priority\n", report.PASS_REPORT_ONLY_ADVISORY_GENERATED, "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"),
        ("candidate validation needed\n", report.PASS_REPORT_ONLY_ADVISORY_GENERATED, "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"),
    ],
)
def test_rewrite_advisory_eval_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quality: str, expected_status: str, expected_next_action: str) -> None:
    result, payload = _run_with_monkeypatch(tmp_path, monkeypatch, quality=quality)

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert payload["status"] == expected_status
    assert payload["suggested_next_action"] == expected_next_action
    assert payload["user_confirmation_required"] is True


def test_source_need_case_maps_to_source_authorization_not_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, payload = _run_with_monkeypatch(
        tmp_path,
        monkeypatch,
        quality="final too generic\n",
        evidence="snippet-backed full-text verification unsupported evidence gap source_need\n",
    )

    assert payload["status"] == report.PASS_REPORT_ONLY_SOURCE_NEED_ADVISED
    assert payload["suggested_next_action"] == "ask_user_to_authorize_source_or_full_text_verification"
    assert payload["suggested_next_action"] != "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"


def test_environment_triage_case_maps_to_environment_advisory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, payload = _run_with_monkeypatch(tmp_path, monkeypatch, failure="executor_resource_exhausted service unhealthy\n")

    assert payload["status"] == report.PASS_REPORT_ONLY_ENVIRONMENT_TRIAGE_ADVISED
    assert payload["suggested_next_action"] == "ask_user_to_fix_environment"


def test_no_refinement_case_maps_to_no_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, payload = _run_with_monkeypatch(tmp_path, monkeypatch)

    assert payload["status"] == report.PASS_REPORT_ONLY_NO_REFINEMENT_ADVISED
    assert payload["user_confirmation_required"] is False


def test_new_task_case_maps_to_new_task_not_topic_refinement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, payload = _run_with_monkeypatch(tmp_path, monkeypatch, query="new topic: ignore previous and start over")

    assert payload["status"] == report.PASS_REPORT_ONLY_NEW_TASK_ADVISED
    assert payload["suggested_next_action"] == "start_new_task"
    assert payload["suggested_next_action"] != "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"


def test_source_acquisition_request_maps_to_source_need(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, payload = _run_with_monkeypatch(tmp_path, monkeypatch, query="source acquisition request for this decision")

    assert payload["status"] == report.PASS_REPORT_ONLY_SOURCE_NEED_ADVISED
    assert payload["suggested_next_action"] == "ask_user_to_authorize_source_or_full_text_verification"


def test_full_rerun_request_maps_to_new_task_not_refinement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, payload = _run_with_monkeypatch(tmp_path, monkeypatch, query="full rerun the pipeline from scratch")

    assert payload["status"] == report.PASS_REPORT_ONLY_NEW_TASK_ADVISED
    assert payload["quality_verdict"] == report.REPORT_ONLY_START_NEW_TASK_INSTEAD


def test_process_checks_all_no_flags_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, payload = _run_with_monkeypatch(tmp_path, monkeypatch, quality="missing obligation\n")

    assert payload["auto_execution"] is False
    assert payload["auto_adoption"] is False
    assert payload["no_adapter_called"] is True
    assert payload["no_manual_task_called"] is True
    assert payload["no_llm_called"] is True
    assert payload["no_pipeline_rerun"] is True
    assert payload["no_candidate_generated"] is True
    assert payload["no_final_rewritten"] is True


def test_runner_result_contract_unchanged_by_advisory_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = _run_with_monkeypatch(tmp_path, monkeypatch, quality="missing obligation\n")

    assert not any("advisory" in key.lower() for key in result)
    assert not any("topic_refinement" in key.lower() for key in result)
    assert set(result) == {"status", "pipeline_status", "run", "validation", "markdown", "artifact_dir"}


def test_flag_does_not_create_candidate_or_adoption_markers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _run_with_monkeypatch(tmp_path, monkeypatch, quality="candidate validation needed\n")

    sidecar = tmp_path / "run" / "topic_refinement_advisory"
    path_names = {path.name for path in sidecar.rglob("*")}
    assert "candidate_v2.md" not in path_names
    assert "revised_final_v2_adopted.md" not in path_names
    assert not (sidecar / "explicit_topic_refinement_adapter_output").exists()


def test_flag_does_not_call_semantic_evaluator_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _run_with_monkeypatch(tmp_path, monkeypatch, quality="missing obligation\n")

    sidecar_text = (tmp_path / "run" / "topic_refinement_advisory" / report.REPORT_MD).read_text(encoding="utf-8")
    assert "semantic evaluator model call" not in sidecar_text.lower()
    assert "no LLM call" in sidecar_text


def test_flag_emits_sidecar_only_and_keeps_final_output_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final_text = "Final answer with specific tradeoffs and recommendation.\n"

    def fake(mode: str, *, base_dir: str | Path) -> dict:
        base = Path(base_dir)
        _write_fixture(base, quality="missing obligation\n")
        (base / "final_controller_report.md").write_text(final_text, encoding="utf-8")
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_COMPLETE,
            "run": {"mode": mode, "execution_mode": "fake-simulated", "stages": []},
            "validation": {"valid": True},
            "markdown": "pipeline_status=PIPELINE_COMPLETE",
        }

    monkeypatch.setattr(runner, "run_simulated_pipeline", fake)
    runner.task_engine_runner(
        query="这是一个决策任务。",
        mode=ENGINE_DECISION,
        action="simulated-run",
        base_dir=str(tmp_path / "run"),
        emit_topic_refinement_advisory=True,
    )

    assert (tmp_path / "run" / "final_controller_report.md").read_text(encoding="utf-8") == final_text
    assert (tmp_path / "run" / "topic_refinement_advisory" / report.REPORT_JSON).exists()
