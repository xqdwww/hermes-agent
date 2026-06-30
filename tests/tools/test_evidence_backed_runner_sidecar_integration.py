from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.task_engine_runner as runner
from tools import evidence_backed_runner_sidecar as sidecar
from tools.task_engine_contracts import ENGINE_DECISION, PIPELINE_COMPLETE


def _write_run_artifacts(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "runner_result.json").write_text('{"pipeline_status":"PIPELINE_COMPLETE"}\n', encoding="utf-8")
    (run_dir / "final_controller_report.md").write_text("Final answer fixture\n", encoding="utf-8")
    (run_dir / "case_quality_review.md").write_text("quality acceptable\n", encoding="utf-8")
    (run_dir / "original_user_question.txt").write_text("Question\n", encoding="utf-8")


def _install_fake_simulated_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    def fake_simulated(mode: str, *, base_dir: str | Path) -> dict:
        run_dir = Path(base_dir)
        calls.append(run_dir)
        _write_run_artifacts(run_dir)
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_COMPLETE,
            "run": {"mode": mode, "execution_mode": "fake-simulated", "stages": []},
            "validation": {"valid": True},
            "markdown": "pipeline complete",
        }

    monkeypatch.setattr(runner, "run_simulated_pipeline", fake_simulated)
    return calls


def _run(tmp_path: Path, **kwargs: object) -> dict:
    payload = {
        "query": "这是一个决策任务，请给出建议。",
        "mode": ENGINE_DECISION,
        "action": "simulated-run",
        "base_dir": str(tmp_path / "run"),
    }
    payload.update(kwargs)
    return json.loads(runner.task_engine_runner(**payload))


def test_runner_default_emits_no_evidence_backed_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch)

    result = _run(tmp_path)

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert not (tmp_path / "run" / sidecar.SIDECAR_DIRNAME).exists()
    assert "evidence_backed_sidecar" not in result


def test_runner_flag_true_emits_status_sidecar_without_result_contract_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch)

    result = _run(tmp_path, emit_evidence_backed_sidecar=True)
    output_dir = tmp_path / "run" / sidecar.SIDECAR_DIRNAME
    validation = json.loads((output_dir / sidecar.VALIDATION_JSON).read_text(encoding="utf-8"))

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert result["artifact_dir"] == str(tmp_path / "run")
    assert not any("evidence_backed" in key for key in result)
    assert (output_dir / sidecar.MANIFEST_JSON).exists()
    assert (output_dir / sidecar.STATUS_MD).exists()
    assert validation["stage"] == "status_only"
    assert validation["next_action"] == "needs_source_registry"


def test_runner_explicit_sidecar_stage_is_honored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch)

    _run(tmp_path, emit_evidence_backed_sidecar=True, evidence_backed_sidecar_stage="source_registry_gate")
    validation = json.loads((tmp_path / "run" / sidecar.SIDECAR_DIRNAME / sidecar.VALIDATION_JSON).read_text(encoding="utf-8"))

    assert validation["stage"] == "source_registry_gate"
    assert any("source_registry_gate requested" in warning for warning in validation["warnings"])


def test_runner_invalid_sidecar_stage_is_isolated_from_main_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch)

    result = _run(tmp_path, emit_evidence_backed_sidecar=True, evidence_backed_sidecar_stage="invalid")
    validation = json.loads((tmp_path / "run" / sidecar.SIDECAR_DIRNAME / sidecar.VALIDATION_JSON).read_text(encoding="utf-8"))

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert validation["ok"] is False
    assert validation["errors"] == ["unsupported sidecar_stage: invalid"]


def test_runner_sidecar_does_not_rerun_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_simulated_pipeline(monkeypatch)

    _run(tmp_path, emit_evidence_backed_sidecar=True)

    assert len(calls) == 1


def test_runner_sidecar_does_not_modify_final_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch)

    _run(tmp_path, emit_evidence_backed_sidecar=True)

    assert (tmp_path / "run" / "final_controller_report.md").read_text(encoding="utf-8") == "Final answer fixture\n"
    assert not (tmp_path / "run" / "candidate_rewrite.md").exists()
    assert not (tmp_path / "run" / "revised_final_v2.md").exists()


def test_runner_handler_accepts_sidecar_schema_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch)

    result = json.loads(
        runner._task_engine_handler(
            {
                "query": "这是一个决策任务。",
                "mode": ENGINE_DECISION,
                "action": "simulated-run",
                "base_dir": str(tmp_path / "run"),
                "emit_evidence_backed_sidecar": "true",
                "evidence_backed_sidecar_stage": "evidence_packet_gate",
            }
        )
    )
    validation = json.loads((tmp_path / "run" / sidecar.SIDECAR_DIRNAME / sidecar.VALIDATION_JSON).read_text(encoding="utf-8"))

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert validation["stage"] == "evidence_packet_gate"


def test_runner_schema_defaults_sidecar_off() -> None:
    props = runner.TASK_ENGINE_RUNNER_SCHEMA["function"]["parameters"]["properties"]

    assert props["emit_evidence_backed_sidecar"]["default"] is False
    assert props["evidence_backed_sidecar_stage"]["default"] == "status_only"
    assert "status_only" in props["evidence_backed_sidecar_stage"]["enum"]


def test_sidecar_helper_failure_isolated_from_main_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_simulated_pipeline(monkeypatch)

    def fail_sidecar(**kwargs: object) -> dict:
        raise RuntimeError("sidecar exploded")

    monkeypatch.setattr(sidecar, "maybe_emit_sidecar", fail_sidecar)

    result = _run(tmp_path, emit_evidence_backed_sidecar=True)

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert (tmp_path / "run" / sidecar.SIDECAR_DIRNAME / "evidence_backed_sidecar_failed.json").exists()
