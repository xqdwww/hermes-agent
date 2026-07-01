from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.task_engine_runner as runner
from tools.task_engine_contracts import (
    ENGINE_DECISION,
    ENGINE_RESEARCH,
    PIPELINE_BLOCKED,
)


LEGACY_ENGINE_ROUTE = "engine.py " + "--route=hybrid"
LEGACY_DECISION_ENGINE_ROOT = "/Users/xqdwww/" + "decision-engine"


def _load(payload: str) -> dict:
    return json.loads(payload)


def _assert_current_runner_full_contract(result: dict) -> None:
    serialized = json.dumps(result, ensure_ascii=False)
    generated_command = result["generated_command"]

    assert result["selected_entrypoint"] == "task_engine_runner"
    assert result["entrypoint_module"] == "tools.task_engine_runner"
    assert result["generated_command_kind"] == "python_callable"
    assert "task_engine_runner" in generated_command
    assert LEGACY_ENGINE_ROUTE not in generated_command
    assert LEGACY_DECISION_ENGINE_ROOT not in generated_command
    assert LEGACY_ENGINE_ROUTE not in serialized
    assert LEGACY_DECISION_ENGINE_ROOT not in serialized
    assert "ROUTE_CARD" not in serialized
    assert "EXECUTION_CONTRACT" not in serialized
    assert "route_card" not in serialized.lower()
    assert result["full_run_entrypoint_check"] == runner.FULL_RUN_ENTRYPOINT_CHECK
    assert result["legacy_engine_route_check"] == runner.NO_OLD_ENGINE_ROUTE_CHECK
    assert result["confirmation_card_check"] == runner.NO_CONFIRMATION_CARD_CHECK
    assert result["prompt_path_policy_check"] == runner.PROMPT_PATH_POLICY_CHECK
    assert result["confirmation_required"] is False
    assert result["second_confirmation_required"] is False
    assert result["confirmation_card_generated"] is False
    assert result["prompt_path_policy"]["prompt_file_path"] is None
    assert result["prompt_path_policy"]["legacy_decision_engine_prompt_path_allowed"] is False
    assert result["sidecar_policy"]["evidence_backed_sidecar_default"] is False
    assert result["sidecar_policy"]["explicit_opt_in_only"] is True
    assert result["sidecar_policy"]["main_result_contract_changed_by_sidecar"] is False


def test_research_full_request_selects_task_engine_runner_without_real_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "run_research_l1_l5_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("RESEARCH full must not enter smoke")),
    )
    monkeypatch.setattr(
        runner,
        "run_research_l1_l5_real",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry intercept must not run real RESEARCH full")),
    )

    result = _load(
        runner.task_engine_runner(
            query="这是一个研究任务。请用 task_engine_runner full 执行。",
            mode=ENGINE_RESEARCH,
            action="full",
            base_dir=str(tmp_path / "research"),
            execution_intent="dry_run",
        )
    )

    dumped = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "ok"
    assert result["not_executed"] is True
    assert result["execution_state"] == "full_dry_intercept_not_executed"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    assert result["planned_l2_5_status"] == "real"
    assert result["packet_provenance_required"] is True
    assert result["planned_l5_provenance_fields"] == [
        "current_run_id",
        "current_query_hash",
        "current_artifact_dir",
    ]
    assert result["planned_l5_packet_generation"] == "research_evidence_packet.md"
    assert "real-smoke-l1-l5" not in dumped
    assert result["full_run_request"]["requested_action"] == "full"
    assert result["full_run_request"]["effective_action"] == runner.RESEARCH_FULL_REAL_ACTION
    assert result["prompt_path_policy"]["artifact_dir"] == str(tmp_path / "research")
    assert not (tmp_path / "research" / "evidence_backed_sidecar").exists()
    _assert_current_runner_full_contract(result)


def test_decision_full_blocked_latest_packet_returns_blocked_status_not_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "_find_latest_valid_research_packet", lambda *, base_dir: None)

    def fail_real_decision_full(*args: object, **kwargs: object) -> dict:
        raise AssertionError("real DECISION full pipeline must not run in mechanism test")

    monkeypatch.setattr(runner, "run_decision_final_smoke", fail_real_decision_full)

    result = _load(
        runner.task_engine_runner(
            query="这是一个决策任务。research_packet_path=latest 请用 task_engine_runner full 执行。",
            mode=ENGINE_DECISION,
            action="full",
            base_dir=str(tmp_path / "decision"),
        )
    )

    assert result["status"] == "blocked"
    assert result["BLOCKED_STATUS"] == PIPELINE_BLOCKED
    assert result["pipeline_status"] == PIPELINE_BLOCKED
    assert result["blocked_stage"] == "research_packet_discovery"
    assert result["blocked_reason"] == "no_valid_new_research_packet_found"
    assert result["artifact_dir"] == str(tmp_path / "decision")
    assert result["execution_state"] == "blocked"
    assert result["not_executed"] is True
    assert result["full_run_request"]["effective_action"] == runner.DECISION_FULL_REAL_ACTION
    _assert_current_runner_full_contract(result)


def test_decision_full_dry_intercept_does_not_execute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packet = tmp_path / "research_evidence_packet.md"
    packet.write_text("research_evidence_packet\naccepted: true\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "run_decision_full_real",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry intercept must not run DECISION full")),
    )

    result = _load(
        runner.task_engine_runner(
            query="这是一个决策任务。请用 task_engine_runner full 执行。",
            mode=ENGINE_DECISION,
            action="full",
            research_packet_path=str(packet),
            base_dir=str(tmp_path / "decision"),
            execution_intent="dry_run",
        )
    )

    dumped = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "ok"
    assert result["not_executed"] is True
    assert result["execution_state"] == "full_dry_intercept_not_executed"
    assert result["selected_handler"] == "run_decision_full_real"
    assert result["selected_execution_mode"] == "production-decision-full"
    assert result["research_packet_path"] == str(packet)
    assert result["real_executor_calls"] == []
    assert result["model_or_network_calls"] == []
    assert "real-smoke-decision-final" not in dumped
    assert result["full_run_request"]["effective_action"] == runner.DECISION_FULL_REAL_ACTION
    _assert_current_runner_full_contract(result)


def test_decision_full_result_is_labeled_production_not_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packet = tmp_path / "research_evidence_packet.md"
    packet.write_text("research_evidence_packet\naccepted: true\n", encoding="utf-8")

    def fake_decision_full(query: str, *, base_dir: str, research_packet_path: str | None = None) -> dict:
        return {
            "status": "ok",
            "pipeline_status": "PIPELINE_COMPLETE",
            "full_pipeline_validation": {"valid": True, "stage_count": 10},
            "run": {
                "mode": ENGINE_DECISION,
                "execution_mode": "real-smoke-decision-final",
                "stages": [],
            },
            "message": "DECISION final_controller_report smoke completed.",
        }

    monkeypatch.setattr(runner, "run_decision_full_real", fake_decision_full)

    result = _load(
        runner.task_engine_runner(
            query="这是一个决策任务。请用 task_engine_runner full 执行。",
            mode=ENGINE_DECISION,
            action="full",
            research_packet_path=str(packet),
            base_dir=str(tmp_path / "decision"),
        )
    )

    dumped = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "ok"
    assert result["run"]["execution_mode"] == "production-decision-full"
    assert result["production_run"] is True
    assert result["research_rerun_used"] is False
    assert result["research_packet_path_used"] == str(packet)
    assert result["full_run_request"]["effective_action"] == runner.DECISION_FULL_REAL_ACTION
    assert "real-smoke-decision-final" not in dumped
    assert "non_production_smoke_run" not in result
    _assert_current_runner_full_contract(result)


def test_route_or_contract_request_is_allowed_but_marked_not_executed(tmp_path: Path) -> None:
    contract = _load(
        runner.task_engine_runner(
            query="这是一个研究任务。只询问路线。",
            mode=ENGINE_RESEARCH,
            action="contract",
        )
    )
    dry_run = _load(
        runner.task_engine_runner(
            query="这是一个研究任务。只做 dry-run。",
            mode=ENGINE_RESEARCH,
            action="dry-run",
            base_dir=str(tmp_path / "dry"),
        )
    )

    assert contract["status"] == "ok"
    assert contract["not_executed"] is True
    assert contract["execution_state"] == "contract_not_executed"
    assert dry_run["status"] == "ok"
    assert dry_run["not_executed"] is True
    assert dry_run["execution_state"] == "dry_run_not_executed"
    assert dry_run["plan"]["stage_count"] == 6
    serialized = json.dumps({"contract": contract, "dry_run": dry_run}, ensure_ascii=False)
    assert LEGACY_ENGINE_ROUTE not in serialized
    assert LEGACY_DECISION_ENGINE_ROOT not in serialized
    assert "ROUTE_CARD" not in serialized
    assert "route_card" not in serialized.lower()
