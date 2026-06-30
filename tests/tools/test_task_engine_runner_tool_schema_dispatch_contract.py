import json

from tools.registry import registry
from tools.task_engine_runner import (
    DIRECT_LEGACY_RESEARCH_DECISION_FULL,
    TASK_ENGINE_RUNNER_SCHEMA,
)


DAILY_ADHD_PROMPT = """这是一个 RESEARCH_DECISION 任务。请走 task_engine_runner full。

任务主题：
AI 信息环境下，ADHD 儿童特征的未来结构性反转与长期发展决策。

执行要求：
* mode=RESEARCH_DECISION
* full-run
* 不要输出 ROUTE_CARD
* 不要等待二次确认
"""


def _load_json(raw: str) -> dict:
    return json.loads(raw)


def test_task_engine_runner_schema_exposes_structured_parameters():
    definitions = registry.get_definitions({"task_engine_runner"}, quiet=True)
    assert len(definitions) == 1
    function = definitions[0]["function"]
    properties = function["parameters"]["properties"]

    assert "function" not in function
    assert properties
    assert {"query", "mode", "action"} <= set(properties)
    assert "RESEARCH_DECISION" in properties["mode"]["enum"]
    assert "full" in properties["action"]["enum"]
    assert "base_dir" in properties
    assert "artifact_dir" in properties
    assert properties["emit_evidence_backed_sidecar"]["default"] is False
    assert not (set(properties) & {"command", "cmd", "code", "shell", "terminal", "execute_code"})


def test_task_engine_runner_schema_constant_uses_registry_shape():
    assert TASK_ENGINE_RUNNER_SCHEMA["name"] == "task_engine_runner"
    assert "parameters" in TASK_ENGINE_RUNNER_SCHEMA
    assert "function" not in TASK_ENGINE_RUNNER_SCHEMA
    assert TASK_ENGINE_RUNNER_SCHEMA["parameters"]["properties"]["query"]["type"] == "string"


def test_daily_prompt_full_dispatch_payload_blocks_without_schema_empty_failure(tmp_path, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("real executor must not be called")

    import tools.task_engine_runner as runner

    monkeypatch.setattr(runner, "run_research_decision_l1_l16_smoke", fail_if_called)
    monkeypatch.setattr(runner, "run_research_decision_l1_l15_smoke", fail_if_called)
    monkeypatch.setattr(runner, "run_research_decision_l1_l14_smoke", fail_if_called)

    payload = {
        "query": DAILY_ADHD_PROMPT,
        "mode": "RESEARCH_DECISION",
        "action": "full",
        "artifact_dir": str(tmp_path / "runtime_gate_dispatch"),
    }
    result = _load_json(registry.dispatch("task_engine_runner", payload))

    assert result["status"] == "blocked"
    assert result["BLOCKED_STATUS"] == "PIPELINE_BLOCKED"
    assert result["blocked_stage"] == "research_decision_archived"
    assert result["blocked_reason"] == DIRECT_LEGACY_RESEARCH_DECISION_FULL
    assert result["blocked_reason"] != "schema_empty"
    assert result["selected_entrypoint"] == "task_engine_runner"
    assert result["artifact_dir"] == str(tmp_path / "runtime_gate_dispatch")
    dumped = json.dumps(result, ensure_ascii=False)
    assert "ROUTE_CARD" not in dumped
    assert "EXECUTION_CONTRACT" not in dumped
    assert "等待确认" not in dumped
    assert "engine.py --route=hybrid" not in dumped
    assert "/Users/xqdwww/decision-engine" not in dumped


def test_unknown_args_are_rejected_not_silently_ignored():
    result = _load_json(
        registry.dispatch(
            "task_engine_runner",
            {
                "query": DAILY_ADHD_PROMPT,
                "mode": "RESEARCH_DECISION",
                "action": "mechanism-check",
                "command": "python3 unsafe.py",
            },
        )
    )

    assert result["status"] == "validation_error"
    assert result["blocked_stage"] == "tool_schema_validation"
    assert result["blocked_reason"] == "unknown_or_invalid_task_engine_runner_args"
    assert result["unknown_args"] == ["command"]
    assert result["schema_empty_blocker"] is False
    assert result["no_real_executor_called"] is True


def test_dry_run_alias_and_mechanism_check_do_not_call_real_executors(tmp_path, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("real executor must not be called")

    import tools.task_engine_runner as runner

    monkeypatch.setattr(runner, "run_research_l1_l5_smoke", fail_if_called)
    dry_result = _load_json(
        registry.dispatch(
            "task_engine_runner",
            {
                "query": "这是一个 RESEARCH 任务。请走 task_engine_runner dry-run。",
                "mode": "RESEARCH",
                "dry_run": True,
                "base_dir": str(tmp_path / "dry"),
            },
        )
    )
    assert dry_result["status"] == "ok"
    assert dry_result["plan"]

    mechanism_result = _load_json(
        registry.dispatch(
            "task_engine_runner",
            {
                "query": DAILY_ADHD_PROMPT,
                "mode": "RESEARCH_DECISION",
                "action": "mechanism-check",
                "base_dir": str(tmp_path / "mechanism"),
            },
        )
    )
    assert mechanism_result["status"] == "ok"
    assert mechanism_result["no_real_executor_called"] is True
    assert mechanism_result["dispatch_payload_valid"] is True


def test_explicit_sidecar_flag_is_accepted_without_changing_main_result(tmp_path):
    result = _load_json(
        registry.dispatch(
            "task_engine_runner",
            {
                "query": DAILY_ADHD_PROMPT,
                "mode": "RESEARCH_DECISION",
                "action": "full",
                "base_dir": str(tmp_path / "blocked"),
                "emit_evidence_backed_sidecar": True,
                "evidence_backed_sidecar_stage": "evidence_packet_gate",
            },
        )
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == DIRECT_LEGACY_RESEARCH_DECISION_FULL
    assert result["sidecar_policy"]["evidence_backed_sidecar_default"] is False
    assert result["sidecar_policy"]["evidence_backed_sidecar_requested"] is True
    assert result["sidecar_policy"]["evidence_backed_sidecar_stage"] == "evidence_packet_gate"
    assert result["sidecar_policy"]["main_result_contract_changed_by_sidecar"] is False
