from __future__ import annotations

import json
from pathlib import Path

import tools.task_engine_runner as runner
from tools.task_engine_contracts import (
    ENGINE_RESEARCH_DECISION,
    PIPELINE_BLOCKED,
    detect_task_engine_mode,
)


LEGACY_ENGINE_ROUTE = "engine.py " + "--route=hybrid"
LEGACY_DECISION_ENGINE_ROOT = "/Users/xqdwww/" + "decision-engine"

ADHD_FULL_RUN_FIXTURE = """
任务类型：RESEARCH_DECISION
主题：AI 信息环境下，ADHD 儿童特征的未来结构性反转与长期发展决策
执行要求：请使用 task_engine_runner full。
机制要求：不要输出 ROUTE_CARD，不要等待二次确认。
期望机制：选择当前 repo 内 task_engine_runner；如果被安全策略阻止，返回 BLOCKED_STATUS。
""".strip()


def _load(payload: str) -> dict:
    return json.loads(payload)


def _assert_no_confirmation_or_legacy_entrypoint(result: dict) -> None:
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["selected_entrypoint"] == "task_engine_runner"
    assert result["entrypoint_module"] == "tools.task_engine_runner"
    assert "task_engine_runner" in result["generated_command"]
    assert LEGACY_ENGINE_ROUTE not in result["generated_command"]
    assert LEGACY_DECISION_ENGINE_ROOT not in result["generated_command"]
    assert LEGACY_ENGINE_ROUTE not in serialized
    assert LEGACY_DECISION_ENGINE_ROOT not in serialized
    assert "ROUTE_CARD" not in serialized
    assert "EXECUTION_CONTRACT" not in serialized
    assert "route_card" not in serialized.lower()
    assert result["confirmation_required"] is False
    assert result["second_confirmation_required"] is False
    assert result["confirmation_card_generated"] is False
    assert result["legacy_engine_route_check"] == runner.NO_OLD_ENGINE_ROUTE_CHECK
    assert result["confirmation_card_check"] == runner.NO_CONFIRMATION_CARD_CHECK
    assert result["prompt_path_policy"]["prompt_file_path"] is None
    assert result["prompt_path_policy"]["legacy_decision_engine_prompt_path_allowed"] is False


def test_research_decision_full_fixture_blocks_with_status_not_routecard(tmp_path: Path) -> None:
    result = _load(
        runner.task_engine_runner(
            query=ADHD_FULL_RUN_FIXTURE,
            mode="AUTO",
            action="full",
            base_dir=str(tmp_path / "adhd"),
        )
    )

    assert detect_task_engine_mode(ADHD_FULL_RUN_FIXTURE) == ENGINE_RESEARCH_DECISION
    assert result["status"] == "blocked"
    assert result["BLOCKED_STATUS"] == PIPELINE_BLOCKED
    assert result["pipeline_status"] == PIPELINE_BLOCKED
    assert result["blocked_stage"] == "research_decision_archived"
    assert result["blocked_reason"] == runner.DIRECT_LEGACY_RESEARCH_DECISION_FULL
    assert result["artifact_dir"] == str(tmp_path / "adhd")
    assert result["execution_state"] == "blocked"
    assert result["not_executed"] is True
    assert result["full_run_request"] == {
        "requested_action": "full",
        "effective_action": "archived-research-decision",
        "mode": ENGINE_RESEARCH_DECISION,
        "runner_selected": True,
    }
    assert result["sidecar_policy"]["evidence_backed_sidecar_default"] is False
    assert result["sidecar_policy"]["evidence_backed_sidecar_requested"] is False
    assert not (tmp_path / "adhd" / "evidence_backed_sidecar").exists()
    _assert_no_confirmation_or_legacy_entrypoint(result)


def test_explicit_sidecar_flag_is_represented_without_defaulting_or_main_contract_change(tmp_path: Path) -> None:
    result = _load(
        runner.task_engine_runner(
            query=ADHD_FULL_RUN_FIXTURE,
            mode=ENGINE_RESEARCH_DECISION,
            action="full",
            base_dir=str(tmp_path / "adhd_sidecar"),
            emit_evidence_backed_sidecar=True,
            evidence_backed_sidecar_stage="fulltext_handoff_gate",
        )
    )

    assert result["status"] == "blocked"
    assert result["BLOCKED_STATUS"] == PIPELINE_BLOCKED
    assert result["sidecar_policy"]["evidence_backed_sidecar_default"] is False
    assert result["sidecar_policy"]["evidence_backed_sidecar_requested"] is True
    assert result["sidecar_policy"]["evidence_backed_sidecar_stage"] == "fulltext_handoff_gate"
    assert result["sidecar_policy"]["explicit_opt_in_only"] is True
    assert result["sidecar_policy"]["main_result_contract_changed_by_sidecar"] is False
    _assert_no_confirmation_or_legacy_entrypoint(result)


def test_adhd_fixture_is_generic_full_run_fixture_not_special_cased(tmp_path: Path) -> None:
    generic_result = _load(
        runner.task_engine_runner(
            query="任务类型：RESEARCH_DECISION。请使用 task_engine_runner full。不要二次确认。",
            mode=ENGINE_RESEARCH_DECISION,
            action="full",
            base_dir=str(tmp_path / "generic"),
        )
    )
    adhd_result = _load(
        runner.task_engine_runner(
            query=ADHD_FULL_RUN_FIXTURE,
            mode=ENGINE_RESEARCH_DECISION,
            action="full",
            base_dir=str(tmp_path / "adhd"),
        )
    )

    assert generic_result["blocked_reason"] == adhd_result["blocked_reason"]
    assert generic_result["selected_entrypoint"] == adhd_result["selected_entrypoint"] == "task_engine_runner"
    assert generic_result["full_run_request"]["mode"] == adhd_result["full_run_request"]["mode"] == ENGINE_RESEARCH_DECISION
    assert "ADHD" not in generic_result["generated_command"]
    assert "ADHD" not in adhd_result["generated_command"]
