from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

import tools.task_engine_runner as runner
from tools import topic_refinement_post_final_advisory_report as report
from tools.task_engine_contracts import ENGINE_DECISION, ENGINE_RESEARCH, ENGINE_RESEARCH_DECISION, PIPELINE_BLOCKED, PIPELINE_COMPLETE


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_run_artifacts(
    run_dir: Path,
    *,
    final: str | None = "Final answer with concrete recommendations.\n",
    quality: str | None = "quality acceptable and specific\n",
    evidence: str = "",
    failure: str = "",
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    if final is not None:
        (run_dir / "final_controller_report.md").write_text(final, encoding="utf-8")
    if quality is not None:
        (run_dir / "case_quality_review.md").write_text(quality, encoding="utf-8")
    if evidence:
        (run_dir / "research_evidence_packet.md").write_text(evidence, encoding="utf-8")
    if failure:
        (run_dir / "failure_report.md").write_text(failure, encoding="utf-8")
    (run_dir / "runner_result.json").write_text('{"pipeline_status":"PIPELINE_COMPLETE","contract":"stable"}\n', encoding="utf-8")
    (run_dir / "original_user_question.txt").write_text("Original question\n", encoding="utf-8")


def _install_fake_simulated_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pipeline_status: str = PIPELINE_COMPLETE,
    final: str | None = "Final answer with concrete recommendations.\n",
    quality: str | None = "quality acceptable and specific\n",
    evidence: str = "",
    failure: str = "",
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_simulated(mode: str, *, base_dir: str | Path) -> dict:
        run_dir = Path(base_dir)
        calls.append({"mode": mode, "base_dir": str(run_dir)})
        if pipeline_status == PIPELINE_COMPLETE:
            _write_run_artifacts(run_dir, final=final, quality=quality, evidence=evidence, failure=failure)
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "runner_result.json").write_text('{"pipeline_status":"PIPELINE_BLOCKED"}\n', encoding="utf-8")
        return {
            "status": "ok" if pipeline_status == PIPELINE_COMPLETE else "blocked",
            "pipeline_status": pipeline_status,
            "run": {"mode": mode, "execution_mode": "fake-simulated", "stages": []},
            "validation": {"valid": pipeline_status == PIPELINE_COMPLETE},
            "markdown": f"pipeline_status={pipeline_status}",
        }

    monkeypatch.setattr(runner, "run_simulated_pipeline", fake_simulated)
    return calls


def _run_task_engine(
    tmp_path: Path,
    *,
    emit: bool | str | None = None,
    query: str = "这是一个决策任务。请完成已有问题。",
    mode: str = ENGINE_DECISION,
    advisory_output_dir: Path | None = None,
) -> dict:
    kwargs = {
        "query": query,
        "mode": mode,
        "action": "simulated-run",
        "base_dir": str(tmp_path / "run"),
    }
    if emit is not None:
        kwargs["emit_topic_refinement_advisory"] = emit
    if advisory_output_dir is not None:
        kwargs["topic_refinement_advisory_output_dir"] = str(advisory_output_dir)
    return json.loads(runner.task_engine_runner(**kwargs))


def _sidecar(tmp_path: Path) -> Path:
    return tmp_path / "run" / "topic_refinement_advisory"


def _sidecar_payload(tmp_path: Path) -> dict:
    return json.loads((_sidecar(tmp_path) / report.REPORT_JSON).read_text(encoding="utf-8"))


def _blocked_payload(tmp_path: Path) -> dict:
    return json.loads((_sidecar(tmp_path) / report.BLOCKED_JSON).read_text(encoding="utf-8"))


def test_flag_absent_no_advisory_emitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_simulated_pipeline(monkeypatch)

    result = _run_task_engine(tmp_path)

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert len(calls) == 1
    assert not _sidecar(tmp_path).exists()


def test_flag_false_no_advisory_emitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch)

    result = _run_task_engine(tmp_path, emit=False)

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert not _sidecar(tmp_path).exists()


def test_flag_false_string_no_advisory_emitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch)

    _run_task_engine(tmp_path, emit="false")

    assert not _sidecar(tmp_path).exists()


def test_flag_true_pipeline_complete_emits_report_only_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="final too generic and low specificity\n")

    result = _run_task_engine(tmp_path, emit=True)
    payload = _sidecar_payload(tmp_path)

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert (_sidecar(tmp_path) / report.REPORT_MD).exists()
    assert (_sidecar(tmp_path) / report.DETECTOR_OUTPUT_DIR / "post_final_advisory_report.json").exists()
    assert payload["status"] == report.PASS_REPORT_ONLY_ADVISORY_GENERATED
    assert payload["user_confirmation_required"] is True


def test_flag_true_pipeline_failed_does_not_emit_advisory_and_main_failure_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, pipeline_status=PIPELINE_BLOCKED)

    result = _run_task_engine(tmp_path, emit=True)

    assert result["status"] == "blocked"
    assert result["pipeline_status"] == PIPELINE_BLOCKED
    assert not _sidecar(tmp_path).exists()


def test_missing_final_v1_writes_blocked_sidecar_and_main_result_unaffected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, final=None, quality="quality acceptable\n")

    result = _run_task_engine(tmp_path, emit=True)
    blocked = _blocked_payload(tmp_path)

    assert result["status"] == "ok"
    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert blocked["status"] == report.BLOCKED_MISSING_REQUIRED_ARTIFACTS


def test_missing_quality_review_writes_blocked_sidecar_and_main_result_unaffected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, final="Final answer\n", quality=None)

    result = _run_task_engine(tmp_path, emit=True)
    blocked = _blocked_payload(tmp_path)

    assert result["status"] == "ok"
    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert blocked["status"] == report.BLOCKED_MISSING_REQUIRED_ARTIFACTS


def test_output_collision_blocks_advisory_without_overwriting_or_failing_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="final too generic\n")
    sidecar = _sidecar(tmp_path)
    sidecar.mkdir(parents=True)
    existing = sidecar / report.REPORT_JSON
    existing.write_text('{"existing": true}\n', encoding="utf-8")

    result = _run_task_engine(tmp_path, emit=True)
    blocked = _blocked_payload(tmp_path)

    assert result["status"] == "ok"
    assert existing.read_text(encoding="utf-8") == '{"existing": true}\n'
    assert blocked["status"] == report.BLOCKED_OUTPUT_ALREADY_EXISTS


def test_custom_advisory_output_dir_is_supported_without_runner_result_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="missing obligation\n")
    custom = tmp_path / "custom_sidecar"

    result = _run_task_engine(tmp_path, emit=True, advisory_output_dir=custom)

    assert (custom / report.REPORT_JSON).exists()
    assert not _sidecar(tmp_path).exists()
    assert result["artifact_dir"] == str(tmp_path / "run")
    assert not any("advisory" in key.lower() or "topic_refinement" in key.lower() for key in result)


def test_no_adapter_or_manual_task_or_semantic_model_call_path_in_runner_helper() -> None:
    source = inspect.getsource(runner._emit_topic_refinement_advisory_sidecar)

    assert "topic_refinement_post_final_advisory_report" in source
    assert "topic_refinement_registry_adapter" not in source
    assert "topic_refinement_manual_task" not in source
    assert "semantic_advisory" not in source
    assert "openai" not in source.lower()
    assert "anthropic" not in source.lower()


def test_no_adapter_or_manual_task_modules_imported_by_flag_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="missing obligation\n")
    sys.modules.pop("tools.topic_refinement_registry_adapter", None)
    sys.modules.pop("tools.topic_refinement_manual_task", None)

    _run_task_engine(tmp_path, emit=True)

    assert "tools.topic_refinement_registry_adapter" not in sys.modules
    assert "tools.topic_refinement_manual_task" not in sys.modules


def test_no_pipeline_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_simulated_pipeline(monkeypatch, quality="weak ranking\n")

    _run_task_engine(tmp_path, emit=True)

    assert len(calls) == 1


def test_no_candidate_output_generated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="missing obligation\n")

    _run_task_engine(tmp_path, emit=True)

    generated_names = {path.name for path in _sidecar(tmp_path).rglob("*")}
    assert "candidate_v2.md" not in generated_names
    assert "revised_final_v2.md" not in generated_names
    assert not (_sidecar(tmp_path) / "explicit_topic_refinement_adapter_output").exists()


def test_final_v1_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="missing obligation\n")
    captured: dict[str, str] = {}

    original_fake = runner.run_simulated_pipeline

    def fake_and_capture(mode: str, *, base_dir: str | Path) -> dict:
        result = original_fake(mode, base_dir=base_dir)
        final_path = Path(base_dir) / "final_controller_report.md"
        captured["path"] = str(final_path)
        captured["hash"] = _hash(final_path)
        return result

    monkeypatch.setattr(runner, "run_simulated_pipeline", fake_and_capture)

    _run_task_engine(tmp_path, emit=True)

    assert _hash(Path(captured["path"])) == captured["hash"]


def test_runner_result_file_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="weak priority\n")
    captured: dict[str, str] = {}
    original_fake = runner.run_simulated_pipeline

    def fake_and_capture(mode: str, *, base_dir: str | Path) -> dict:
        result = original_fake(mode, base_dir=base_dir)
        runner_result = Path(base_dir) / "runner_result.json"
        captured["path"] = str(runner_result)
        captured["hash"] = _hash(runner_result)
        return result

    monkeypatch.setattr(runner, "run_simulated_pipeline", fake_and_capture)

    result = _run_task_engine(tmp_path, emit=True)

    assert _hash(Path(captured["path"])) == captured["hash"]
    assert not any("advisory" in key.lower() or "topic_refinement" in key.lower() for key in result)


def test_advisory_sidecar_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="missing obligation\n")

    _run_task_engine(tmp_path, emit=True)

    run_children = {path.name for path in (tmp_path / "run").iterdir()}
    assert "topic_refinement_advisory" in run_children
    assert "final_controller_report.md" in run_children
    assert "case_quality_review.md" in run_children
    assert "runner_result.json" in run_children


def test_report_only_process_flags_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="missing obligation\n")

    _run_task_engine(tmp_path, emit=True)
    payload = _sidecar_payload(tmp_path)

    assert payload["auto_execution"] is False
    assert payload["auto_adoption"] is False
    assert payload["no_adapter_called"] is True
    assert payload["no_manual_task_called"] is True
    assert payload["no_llm_called"] is True
    assert payload["no_pipeline_rerun"] is True
    assert payload["no_candidate_generated"] is True
    assert payload["no_final_rewritten"] is True


def test_flag_must_not_auto_execute_topic_refinement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="final too generic\n")

    _run_task_engine(tmp_path, emit=True)
    payload = _sidecar_payload(tmp_path)

    assert payload["status"] == report.PASS_REPORT_ONLY_ADVISORY_GENERATED
    assert payload["suggested_next_action"] == "ask_user_to_confirm_explicit_TOPIC_REFINEMENT"
    assert not (_sidecar(tmp_path) / "explicit_topic_refinement_adapter_output").exists()


def test_flag_must_not_modify_final_controller_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final_text = "Final answer with concrete recommendations.\n"
    _install_fake_simulated_pipeline(monkeypatch, final=final_text, quality="missing obligation\n")

    _run_task_engine(tmp_path, emit=True)

    assert (tmp_path / "run" / "final_controller_report.md").read_text(encoding="utf-8") == final_text


def test_flag_must_not_mark_candidate_adopted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch, quality="missing obligation\n")

    _run_task_engine(tmp_path, emit=True)
    serialized = json.dumps(_sidecar_payload(tmp_path), ensure_ascii=False).lower()

    assert "revised_final_v2_adopted" not in serialized
    assert "candidate_adopted" not in serialized


def test_existing_default_route_mode_unchanged_when_flag_present_for_non_applicable_query(tmp_path: Path) -> None:
    result = json.loads(
        runner.task_engine_runner(
            query="帮我改一下这个按钮的颜色",
            mode="AUTO",
            emit_topic_refinement_advisory=True,
            base_dir=str(tmp_path / "unused"),
        )
    )

    assert result["status"] == "not_applicable"
    assert not (tmp_path / "unused" / "topic_refinement_advisory").exists()


@pytest.mark.parametrize("mode", [ENGINE_RESEARCH, ENGINE_DECISION, ENGINE_RESEARCH_DECISION])
def test_schema_flag_default_false_preserves_existing_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    _install_fake_simulated_pipeline(monkeypatch)

    _run_task_engine(tmp_path, mode=mode)

    assert not _sidecar(tmp_path).exists()


def test_runner_schema_exposes_explicit_flag_default_false() -> None:
    props = runner.TASK_ENGINE_RUNNER_SCHEMA["function"]["parameters"]["properties"]

    assert props["emit_topic_refinement_advisory"]["default"] is False
    assert props["topic_refinement_advisory_strict"]["default"] is True
    assert "topic_refinement_advisory_output_dir" in props
