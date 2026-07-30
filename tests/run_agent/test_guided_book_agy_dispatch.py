from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.guided_book_dispatch import (
    AGY_TOOL_NAME,
    DISPATCH_BLOCKED_NOTICE,
    FALLBACK_NOTICE,
    build_agy_predispatch_args,
    build_guided_predispatch_plan,
    cap_guided_tool_calls,
    resolve_guided_book_dispatch,
)
from run_agent import AIAgent


def _tool_defs(*names: str) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"{name} tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in names
    ]


def _deepseek_agent(hermes_home: Path) -> AIAgent:
    with (
        patch("run_agent._hermes_home", hermes_home),
        patch(
            "run_agent.get_tool_definitions",
            return_value=_tool_defs(
                "agy_book_dialogue",
                "book_notes_retrieval",
                "skill_view",
            ),
        ),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key",
            base_url="https://api.deepseek.com/v1",
            provider="deepseek",
            model="deepseek-v4-flash",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            runtime_capabilities=["sensitive_tool_persistence_v1"],
        )
    agent.client = MagicMock()
    return agent


def _guided_history() -> list[dict]:
    return [
        {"role": "system", "content": "You are Hermes."},
        {"role": "user", "content": "进入引导式读书模式《测试书》"},
        {
            "role": "assistant",
            "content": (
                "已经进入《测试书》的引导式读书模式。\n"
                "<!-- guided_mode_b: active; "
                "stage=awaiting_focus_question; "
                "user_explanation_received=false -->"
            ),
        },
    ]


def _request_messages(message: str) -> list[dict]:
    return [*_guided_history(), {"role": "user", "content": message}]


def _tool_call(
    name: str,
    *,
    arguments: str = "{}",
    call_id: str = "call-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _response(
    content: str = "",
    *,
    tool_calls: list[SimpleNamespace] | None = None,
    finish_reason: str = "stop",
) -> SimpleNamespace:
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        reasoning=None,
        reasoning_content=None,
        reasoning_details=None,
        refusal=None,
        model_extra={},
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=message, finish_reason=finish_reason)
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
        ),
        model="deepseek-v4-flash",
    )


def _dispatcher_result(agy_result: str, calls: list[str]):
    def dispatch(function_name, *_args, **_kwargs):
        calls.append(function_name)
        if function_name == "book_notes_retrieval":
            return json.dumps(
                {
                    "status": "ok",
                    "results": [{"excerpt": "bounded excerpt"}],
                }
            )
        return agy_result

    return dispatch


def _agy_success(response: str = "AGY answer with one question?") -> str:
    return json.dumps(
        {
            "status": "ok",
            "delivery_mode": "verbatim",
            "response": response,
            "dialogue_engine": "agy_gemini_3_1_pro_high",
        }
    )


def test_guided_probe_predispatches_agy_before_any_model_request(tmp_path):
    agent = _deepseek_agent(tmp_path / "hermes")
    agent._interruptible_api_call = MagicMock(
        return_value=_response("DeepSeek must not run.")
    )
    calls: list[str] = []

    with (
        patch(
            "run_agent.handle_function_call",
            side_effect=_dispatcher_result(_agy_success(), calls),
        ),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation(
            "世事的变化，人生的回望。",
            conversation_history=_guided_history()[1:],
        )

    assert result["final_response"] == "AGY answer with one question?"
    assert result["api_calls"] == 0
    assert agent._interruptible_api_call.call_count == 0
    assert calls == ["book_notes_retrieval", AGY_TOOL_NAME]
    assert agent._guided_book_dispatch_evidence["dispatch_policy"] == (
        "guided_pre_dispatch"
    )


def test_predispatch_accepts_author_before_book_title_orient_wording():
    history = _guided_history()
    history[1]["content"] = "进入引导式读书模式约翰·厄普代克的《父亲的眼泪》"
    history[2]["content"] = (
        "已经进入约翰·厄普代克《父亲的眼泪》的引导式读书模式。\n"
        "当前个人摘录索引暂时无法访问。\n"
        "<!-- guided_mode_b: active; stage=awaiting_focus_question; "
        "user_explanation_received=false -->"
    )

    plan = build_guided_predispatch_plan(
        [*history, {"role": "user", "content": "世事的变化，人生的回望。"}],
        _tool_defs(AGY_TOOL_NAME, "book_notes_retrieval"),
    )

    assert plan is not None
    assert plan.book_title == "父亲的眼泪"
    assert plan.author == "约翰·厄普代克"
    assert plan.retrieval_status == "unavailable"


def test_filtered_agy_tool_blocks_deepseek_bypass(tmp_path):
    agent = _deepseek_agent(tmp_path / "hermes")
    agent.valid_tool_names.discard(AGY_TOOL_NAME)
    agent.tools = [
        tool
        for tool in agent.tools
        if tool["function"]["name"] != AGY_TOOL_NAME
    ]

    agent._interruptible_api_call = MagicMock(
        return_value=_response("DeepSeek must not run.")
    )

    with (
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation(
            "世事的变化，人生的回望。",
            conversation_history=_guided_history()[1:],
        )

    assert result["final_response"] == DISPATCH_BLOCKED_NOTICE
    assert agent._interruptible_api_call.call_count == 0
    assert agent._guided_book_dispatch_evidence["dispatch_policy"] == (
        "blocked_tool_unavailable"
    )


def test_guided_connect_and_close_predispatch_agy(tmp_path):
    for index, (message, stage, expected_calls) in enumerate(
        (
            (
                "把这个判断和我以前读过的其他书连接起来。",
                "connect",
                ["book_notes_retrieval", AGY_TOOL_NAME],
            ),
            ("退出引导式读书模式", "close", [AGY_TOOL_NAME]),
        )
    ):
        agent = _deepseek_agent(tmp_path / f"hermes-{index}")
        agent._interruptible_api_call = MagicMock(
            return_value=_response("DeepSeek must not run.")
        )
        calls: list[str] = []
        decision = resolve_guided_book_dispatch(
            _request_messages(message), agent.tools
        )
        with (
            patch(
                "run_agent.handle_function_call",
                side_effect=_dispatcher_result(_agy_success(stage), calls),
            ),
            patch.object(agent, "_persist_session"),
            patch.object(agent, "_save_trajectory"),
            patch.object(agent, "_cleanup_task_resources"),
        ):
            result = agent.run_conversation(
                message,
                conversation_history=_guided_history()[1:],
            )

        assert decision.guided_stage == stage
        assert result["final_response"] == stage
        assert agent._interruptible_api_call.call_count == 0
        assert calls == expected_calls


def test_orient_and_first_question_explain_do_not_force_agy(tmp_path):
    agent = _deepseek_agent(tmp_path / "hermes")
    orient = [
        {"role": "system", "content": "You are Hermes."},
        {"role": "user", "content": "进入引导式读书模式《测试书》"},
    ]
    explain = _request_messages("时间为什么总让回望变得沉重？")

    orient_decision = resolve_guided_book_dispatch(orient, agent.tools)
    explain_decision = resolve_guided_book_dispatch(explain, agent.tools)

    assert orient_decision.guided_stage == "orient"
    assert orient_decision.agy_required is False
    assert "tool_choice" not in agent._build_api_kwargs(orient)
    assert explain_decision.guided_stage == "explain"
    assert explain_decision.agy_required is False
    assert "tool_choice" not in agent._build_api_kwargs(explain)


def test_meta_question_bypasses_agy_and_preserves_stage(tmp_path):
    agent = _deepseek_agent(tmp_path / "hermes")
    messages = _request_messages("你现在用的是哪个模型和我讨论？")

    decision = resolve_guided_book_dispatch(messages, agent.tools)
    kwargs = agent._build_api_kwargs(messages)

    assert decision.turn_kind == "meta_question"
    assert decision.guided_mode_active is True
    assert decision.guided_stage is None
    assert decision.agy_required is False
    assert "tool_choice" not in kwargs


def test_meta_question_records_deepseek_as_final_engine(tmp_path):
    agent = _deepseek_agent(tmp_path / "hermes")
    history = [
        *_guided_history()[1:],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "agy-prev",
                    "type": "function",
                    "function": {
                        "name": AGY_TOOL_NAME,
                        "arguments": "{}",
                    },
                }
            ],
        },
        {
            "role": "tool",
            "name": AGY_TOOL_NAME,
            "tool_call_id": "agy-prev",
            "content": '{"sensitive_tool_result":"redacted"}',
        },
        {"role": "assistant", "content": "上一轮由 AGY 交付的文学回答。"},
    ]
    display_deltas: list[str] = []
    bridge_deltas: list[str] = []
    agent.stream_delta_callback = display_deltas.append
    agent._interruptible_api_call = MagicMock(
        return_value=_response(
            "当前主模型是 DeepSeek。\n\n"
            "要继续深入刚才的话题吗？"
        )
    )

    with (
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation(
            "你现在用的是哪个模型和我讨论？",
            conversation_history=history,
            stream_callback=bridge_deltas.append,
        )

    assert result["final_response"] == "当前主模型是 DeepSeek。"
    assert display_deltas == ["当前主模型是 DeepSeek。"]
    assert bridge_deltas == ["当前主模型是 DeepSeek。"]
    request_text = json.dumps(
        agent._interruptible_api_call.call_args.args[0],
        ensure_ascii=False,
    )
    assert "agy_book_dialogue call succeeded" in request_text
    assert "Book-notes retrieval availability is a separate status" in request_text
    evidence = agent._guided_book_dispatch_evidence
    assert evidence["turn_kind"] == "meta_question"
    assert evidence["agy_attempted"] is False
    assert evidence["final_answer_engine"] == "deepseek"


def test_unrelated_topic_and_mode_a_do_not_force_agy(tmp_path):
    agent = _deepseek_agent(tmp_path / "hermes")
    unrelated = _request_messages("帮我查天气。")
    mode_a = [
        {"role": "system", "content": "You are Hermes."},
        {"role": "user", "content": "开始讨论《测试书》"},
        {"role": "assistant", "content": "我们开始讨论。"},
        {"role": "user", "content": "世事的变化，人生的回望。"},
    ]

    assert resolve_guided_book_dispatch(
        unrelated, agent.tools
    ).turn_kind == "unrelated_topic"
    assert "tool_choice" not in agent._build_api_kwargs(unrelated)
    assert resolve_guided_book_dispatch(
        mode_a, agent.tools
    ).guided_mode_active is False
    assert "tool_choice" not in agent._build_api_kwargs(mode_a)


def test_guided_turn_caps_agy_and_retrieval_calls():
    tools = [
        _tool_call(AGY_TOOL_NAME, call_id="agy-1"),
        _tool_call(AGY_TOOL_NAME, call_id="agy-2"),
        _tool_call("book_notes_retrieval", call_id="book-1"),
        _tool_call("book_notes_retrieval", call_id="book-2"),
    ]
    required = resolve_guided_book_dispatch(
        _request_messages("世事的变化，人生的回望。"),
        _tool_defs(AGY_TOOL_NAME, "book_notes_retrieval"),
    )
    assert [
        call.function.name
        for call in cap_guided_tool_calls(required, tools) or []
    ] == [AGY_TOOL_NAME]

    attempted_messages = [
        *_request_messages("世事的变化，人生的回望。"),
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "agy-0",
                    "type": "function",
                    "function": {
                        "name": AGY_TOOL_NAME,
                        "arguments": "{}",
                    },
                }
            ],
        },
        {
            "role": "tool",
            "name": AGY_TOOL_NAME,
            "tool_call_id": "agy-0",
            "content": '{"status":"timeout"}',
        },
    ]
    attempted = resolve_guided_book_dispatch(
        attempted_messages,
        _tool_defs(AGY_TOOL_NAME, "book_notes_retrieval"),
    )
    assert [
        call.function.name
        for call in cap_guided_tool_calls(attempted, tools) or []
    ] == ["book_notes_retrieval"]


def test_not_found_and_unavailable_remain_distinct():
    tools = _tool_defs(AGY_TOOL_NAME, "book_notes_retrieval")
    histories = {}
    for status, status_text in (
        ("not_found", "个人书摘索引没有匹配这本书。"),
        ("unavailable", "个人书摘索引暂时不可用。"),
    ):
        history = _guided_history()
        history[-1]["content"] = (
            f"已经进入《测试书》的引导式读书模式。\n{status_text}\n"
            "<!-- guided_mode_b: active; stage=awaiting_focus_question; "
            "user_explanation_received=false -->"
        )
        plan = build_guided_predispatch_plan(
            [*history, {"role": "user", "content": "世事的变化。"}],
            tools,
        )
        assert plan is not None
        histories[status] = build_agy_predispatch_args(plan, None)["book"]

    assert histories["not_found"]["retrieval_status"] == "not_found"
    assert histories["not_found"]["personal_excerpt_available"] is False
    assert histories["not_found"]["retrieval_operational"] is True
    assert histories["unavailable"]["retrieval_status"] == "unavailable"
    assert histories["unavailable"]["personal_excerpt_available"] is None
    assert histories["unavailable"]["retrieval_operational"] is False


def test_agy_success_is_final_answer_without_second_deepseek_call(tmp_path):
    agent = _deepseek_agent(tmp_path / "hermes")
    agy_answer = "AGY answer with one question?"
    display_deltas: list[str] = []
    bridge_deltas: list[str] = []
    agent.stream_delta_callback = display_deltas.append
    agent._interruptible_api_call = MagicMock(
        return_value=_response("DeepSeek must not run.")
    )
    calls: list[str] = []

    with (
        patch(
            "run_agent.handle_function_call",
            side_effect=_dispatcher_result(_agy_success(agy_answer), calls),
        ),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation(
            "世事的变化，人生的回望。",
            conversation_history=_guided_history()[1:],
            stream_callback=bridge_deltas.append,
        )

    assert result["final_response"] == agy_answer
    assert agent._interruptible_api_call.call_count == 0
    assert result["api_calls"] == 0
    assert calls == ["book_notes_retrieval", AGY_TOOL_NAME]
    assert result["final_response"].count("?") == 1
    assert display_deltas == [agy_answer]
    assert bridge_deltas == [agy_answer]
    evidence = agent._guided_book_dispatch_evidence
    assert evidence["agy_attempted"] is True
    assert evidence["agy_succeeded"] is True
    assert evidence["fallback_used"] is False
    assert evidence["final_answer_engine"] == "agy_gemini"


def test_agy_timeout_allows_one_explicit_deepseek_fallback(tmp_path):
    agent = _deepseek_agent(tmp_path / "hermes")
    agent._interruptible_api_call = MagicMock(
        return_value=_response("当前模型的降级回答。")
    )
    timeout_result = (
        '{"status":"timeout","dialogue_engine":"deepseek_fallback",'
        '"fallback_required":true}'
    )

    calls: list[str] = []
    with (
        patch(
            "run_agent.handle_function_call",
            side_effect=_dispatcher_result(timeout_result, calls),
        ),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation(
            "世事的变化，人生的回望。",
            conversation_history=_guided_history()[1:],
        )

    assert result["api_calls"] == 1
    assert calls == ["book_notes_retrieval", AGY_TOOL_NAME]
    assert result["final_response"].startswith(FALLBACK_NOTICE)
    assert result["final_response"].count(FALLBACK_NOTICE) == 1
    assert "当前模型的降级回答。" in result["final_response"]
    evidence = agent._guided_book_dispatch_evidence
    assert evidence["agy_attempted"] is True
    assert evidence["agy_succeeded"] is False
    assert evidence["agy_failure_class"] == "timeout"
    assert evidence["fallback_used"] is True
    assert evidence["final_answer_engine"] == "deepseek_fallback"
