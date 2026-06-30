from __future__ import annotations

import json
from pathlib import Path

import tools.task_engine_runner as runner
from tools.task_engine_contracts import ENGINE_RESEARCH_DECISION, PIPELINE_BLOCKED, PIPELINE_COMPLETE


DAILY_PRODUCTION_PROMPT = """这是一个 RESEARCH_DECISION 任务。请走 task_engine_runner full。

任务主题：
AI 信息环境下，ADHD 儿童特征的未来结构性反转与长期发展决策。

执行要求：
* mode=RESEARCH_DECISION
* full-run
* production
* fresh current-run evidence packet
* 当前任务专属 packet
* 不要 smoke
* 不要 fixture
* 不要 cached
* 不要复用 packet
"""


def _load(payload: str) -> dict:
    return json.loads(payload)


def test_allow_archived_true_without_smoke_intent_blocks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "run_research_decision_l1_l16_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("archived override must not call smoke")),
    )

    result = _load(
        runner.task_engine_runner(
            query="这是一个 RESEARCH_DECISION production full task.",
            mode=ENGINE_RESEARCH_DECISION,
            action="full",
            base_dir=str(tmp_path / "blocked"),
            allow_archived_research_decision=True,
        )
    )

    dumped = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "blocked"
    assert result["BLOCKED_STATUS"] == PIPELINE_BLOCKED
    assert result["blocked_reason"] == runner.UNSAFE_ARCHIVED_RESEARCH_DECISION_OVERRIDE_FOR_PRODUCTION
    assert "real-smoke-research-decision-final" not in dumped


def test_allow_archived_true_with_production_prompt_blocks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "run_research_decision_l1_l16_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("production prompt must not call smoke")),
    )

    result = _load(
        runner.task_engine_runner(
            query=DAILY_PRODUCTION_PROMPT,
            mode=ENGINE_RESEARCH_DECISION,
            action="smoke-research-decision-final",
            base_dir=str(tmp_path / "blocked"),
            allow_archived_research_decision=True,
            execution_intent="integration_smoke",
            explicit_smoke_intent=True,
        )
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == runner.UNSAFE_ARCHIVED_RESEARCH_DECISION_OVERRIDE_FOR_PRODUCTION
    assert result["recommended_next_step"].startswith("Run RESEARCH full")


def test_agent_override_cannot_bypass_production_guard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "run_research_decision_l1_l16_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("agent override must not call smoke")),
    )

    first = _load(
        runner.task_engine_runner(
            query=DAILY_PRODUCTION_PROMPT,
            mode=ENGINE_RESEARCH_DECISION,
            action="full",
            base_dir=str(tmp_path / "first"),
        )
    )
    second = _load(
        runner.task_engine_runner(
            query=DAILY_PRODUCTION_PROMPT,
            mode=ENGINE_RESEARCH_DECISION,
            action="full",
            base_dir=str(tmp_path / "second"),
            allow_archived_research_decision=True,
        )
    )

    assert first["status"] == "blocked"
    assert first["blocked_reason"] == runner.RESEARCH_DECISION_COMBINED_FULL_REQUIRES_FRESH_TWO_STAGE
    assert second["status"] == "blocked"
    assert second["blocked_reason"] == runner.UNSAFE_ARCHIVED_RESEARCH_DECISION_OVERRIDE_FOR_PRODUCTION


def test_explicit_integration_smoke_can_run_archived_but_labeled_non_production(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def fake_smoke(query: str, *, base_dir: str | Path) -> dict:
        calls.append((query, Path(base_dir)))
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_COMPLETE,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-final",
                "stages": [],
            },
            "full_pipeline_validation": {"valid": True},
        }

    monkeypatch.setattr(runner, "run_research_decision_l1_l16_smoke", fake_smoke)

    result = _load(
        runner.task_engine_runner(
            query="integration smoke test fixture for archived Research Decision path",
            mode=ENGINE_RESEARCH_DECISION,
            action="smoke-research-decision-final",
            base_dir=str(tmp_path / "smoke"),
            allow_archived_research_decision=True,
            execution_intent="integration_smoke",
            explicit_smoke_intent=True,
        )
    )

    assert result["status"] == "ok"
    assert result["pipeline_status"] == runner.PIPELINE_COMPLETE_NON_PRODUCTION_SMOKE
    assert result["structural_pipeline_status"] == PIPELINE_COMPLETE
    assert result["non_production_smoke_run"] is True
    assert result["production_valid"] is False
    assert result["evidence_freshness_valid"] is False
    assert calls == [("integration smoke test fixture for archived Research Decision path", tmp_path / "smoke")]


def test_smoke_complete_not_labeled_production_pipeline_complete(tmp_path: Path, monkeypatch) -> None:
    def fake_smoke(query: str, *, base_dir: str | Path) -> dict:
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_COMPLETE,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-final",
                "stages": [],
            },
            "full_pipeline_validation": {"valid": True},
        }

    monkeypatch.setattr(runner, "run_research_decision_l1_l16_smoke", fake_smoke)

    result = _load(
        runner.task_engine_runner(
            query="explicit smoke integration test only",
            mode=ENGINE_RESEARCH_DECISION,
            action="smoke-research-decision-final",
            base_dir=str(tmp_path / "smoke"),
            allow_archived_research_decision=True,
            execution_intent="integration_smoke",
        )
    )

    assert result["pipeline_status"] != PIPELINE_COMPLETE
    assert result["pipeline_status"] == runner.PIPELINE_COMPLETE_NON_PRODUCTION_SMOKE
    assert result["production_run"] is False
    assert result["production_valid"] is False
    assert result["evidence_freshness_valid"] is False
