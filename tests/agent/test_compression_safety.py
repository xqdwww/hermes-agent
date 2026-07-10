from unittest.mock import MagicMock, patch

from agent.compression_safety import (
    classify_text_block,
    split_markdown_fenced_blocks,
    validate_compressed_text,
)
from agent.context_compressor import ContextCompressor
from agent.payload_diagnostics import payload_breakdown


def _summary_response(text: str = "Summary complete."):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = text
    response.usage.completion_tokens = 10
    return response


def _basic_history():
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "head"},
        {"role": "assistant", "content": "older background reply"},
        {"role": "user", "content": "historical user prose about project background"},
        {"role": "assistant", "content": "historical assistant prose about non-executive context"},
        {"role": "user", "content": "current user request must remain exact"},
        {"role": "assistant", "content": "tail"},
    ]


def test_chinese_prose_can_be_llm_compressed_when_validator_passes():
    text = "这是一段普通背景说明，用来解释项目历史和一些非执行性的上下文。它没有硬约束，也没有路径、命令或配置。"
    cls = classify_text_block(text)
    assert cls.block_type == "low_risk_prose"
    assert cls.allow_compression is True

    result = validate_compressed_text(text, "普通背景：项目历史和非执行性上下文。")
    assert result.ok is True


def test_instruction_tokens_force_bypass():
    text = "必须保留原文，不要压缩；只允许输出 diagnostics，禁止替换用户问题。"
    cls = classify_text_block(text)
    assert cls.allow_compression is False
    assert cls.block_type == "critical_instruction"
    assert "必须" in cls.critical_tokens


def test_codex_handoff_prompt_force_bypass():
    text = "Codex handoff prompt\nMUST edit only files in whitelist. DO_NOT commit. final_answer must include tests."
    cls = classify_text_block(text)
    assert cls.allow_compression is False
    assert cls.block_type == "critical_instruction"


def test_markdown_fenced_shell_block_is_atomic_and_bypassed():
    text = "Before\n```bash\npytest -q tests/agent/test_context_compressor.py\n```\nAfter"
    blocks = split_markdown_fenced_blocks(text)
    assert [kind for kind, _ in blocks] == ["text", "fenced", "text"]
    cls = classify_text_block(text)
    assert cls.allow_compression is False
    assert cls.block_type == "markdown_fence"


def test_unclosed_fence_bypasses_following_text():
    text = "Intro\n```json\n{\"a\": 1}\nno closing fence"
    blocks = split_markdown_fenced_blocks(text)
    assert blocks[-1][0] == "unclosed_fenced"
    cls = classify_text_block(text)
    assert cls.allow_compression is False
    assert cls.block_type == "markdown_fence_unclosed"


def test_structured_configs_bypass():
    samples = [
        '{"enabled": true, "threshold": 0.5}',
        "compression:\n  enabled: true\n  threshold: 0.5\n  protect_last_n: 20",
        "[paste_compression]\nenabled = true\nthreshold = 2000",
        '<?xml version="1.0"?><plist version="1.0"><dict></dict></plist>',
    ]
    for sample in samples:
        cls = classify_text_block(sample)
        assert cls.allow_compression is False
        assert cls.block_type in {"json", "yaml", "toml", "plist"}


def test_traceback_bypasses():
    text = 'Traceback (most recent call last):\n  File "app.py", line 12, in main\nValueError: bad'
    cls = classify_text_block(text)
    assert cls.allow_compression is False
    assert cls.block_type == "traceback"


def test_diff_bypasses_and_validator_detects_prefix_damage():
    original = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-print('a')\n+print('b')"
    cls = classify_text_block(original)
    assert cls.allow_compression is False
    assert cls.block_type == "diff"
    result = validate_compressed_text(original, "changed print a to print b.")
    assert result.ok is False
    assert any("diff" in reason for reason in result.reasons)


def test_repo_branch_head_commit_text_bypasses():
    text = (
        "repo: hermes-agent\nbranch: feat/compression-safety\n"
        "HEAD commit abc1234def5678\npath /Users/xqdwww/Workspace/AI_Core/hermes-agent/agent/context_compressor.py"
    )
    cls = classify_text_block(text)
    assert cls.allow_compression is False
    assert cls.block_type == "path_hash_branch_dense"


def test_evidence_packet_stage_artifact_bypasses():
    text = "research_evidence_packet.md\nstage records\ncalibration verdict\nPASS / BLOCKED 判定条件"
    cls = classify_text_block(text)
    assert cls.allow_compression is False
    assert cls.block_type in {"critical_instruction", "stage_artifact"}


def test_validator_flags_truncation_and_missing_tokens():
    original = (
        "The task must preserve /Users/xqdwww/project/app.py on branch main. "
        "PASS requires commit abc1234 and 95% coverage."
    )
    compressed = "Preserve the task on branch"
    result = validate_compressed_text(original, compressed, max_tokens=10, completion_tokens=10)
    assert result.ok is False
    assert any("max_tokens" in reason for reason in result.reasons)
    assert any("must-keep" in reason for reason in result.reasons)
    assert any("path/hash/number" in reason for reason in result.reasons)


def test_unknown_binary_like_content_bypasses():
    cls = classify_text_block("normal text\x00with nul")
    assert cls.allow_compression is False
    assert cls.block_type == "unknown"


def test_payload_diagnostics_reports_safe_replacement_false_for_critical_blocks():
    report = payload_breakdown(
        [{"role": "user", "content": "必须保留原文，不要压缩。"}],
        current_user_input="必须保留原文，不要压缩。",
    )
    reducer = report["context_reducer_diagnostics"]
    assert reducer["bypass_blocks"] == 1
    assert reducer["safe_for_replacement"] is False
    assert reducer["raw_ref_coverage_complete"] is True


def test_context_compressor_aborts_when_middle_window_contains_critical_block():
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        compressor = ContextCompressor(
            model="test/model",
            protect_first_n=1,
            protect_last_n=1,
            quiet_mode=True,
        )

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "head"},
        {"role": "assistant", "content": "old background"},
        {"role": "user", "content": "必须保留原文，不要压缩这个执行合同。"},
        {"role": "assistant", "content": "more old background"},
        {"role": "user", "content": "latest protected ask"},
        {"role": "assistant", "content": "tail"},
    ]

    with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=5):
        with patch("agent.context_compressor.call_llm") as call_llm:
            result = compressor.compress(messages)

    assert result == messages
    assert compressor._last_compress_aborted is False
    assert compressor._last_summary_critical_bypass is True
    assert compressor._last_context_reducer_diagnostics["replacement_applied"] is False
    assert compressor._last_context_reducer_diagnostics["fallback_used"] is True
    call_llm.assert_not_called()


def test_context_compressor_aborts_when_summary_validator_fails():
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "summary without terminal"
    mock_response.usage.completion_tokens = 100

    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        compressor = ContextCompressor(
            model="test/model",
            protect_first_n=1,
            protect_last_n=1,
            quiet_mode=True,
        )

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "head"},
        {"role": "assistant", "content": "ordinary background that can be summarized safely"},
        {"role": "user", "content": "another ordinary historical note"},
        {"role": "assistant", "content": "more ordinary context"},
        {"role": "user", "content": "latest ask"},
        {"role": "assistant", "content": "tail"},
    ]

    with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=5):
        with patch("agent.context_compressor.call_llm", return_value=mock_response):
            result = compressor.compress(messages)

    assert result == messages
    assert compressor._last_compress_aborted is False
    assert compressor._last_summary_validation_failed is True
    assert compressor._last_context_reducer_diagnostics["replacement_applied"] is False
    assert compressor._last_context_reducer_diagnostics["fallback_used"] is True


def test_context_compressor_default_shadow_only_does_not_replace_historical_user_prose():
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        compressor = ContextCompressor(
            model="test/model",
            protect_first_n=1,
            protect_last_n=1,
            quiet_mode=True,
        )

    messages = _basic_history()
    with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=5):
        with patch("agent.context_compressor.call_llm", return_value=_summary_response()) as call_llm:
            result = compressor.compress(messages)

    assert result == messages
    call_llm.assert_called_once()
    diagnostics = compressor._last_context_reducer_diagnostics
    assert diagnostics["shadow_only"] is True
    assert diagnostics["allow_llm_replacement"] is False
    assert diagnostics["would_replace"] is True
    assert diagnostics["replacement_applied"] is False
    assert compressor._last_shadow_summary_preview


def test_context_compressor_default_shadow_only_does_not_replace_historical_assistant_prose():
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        compressor = ContextCompressor(
            model="test/model",
            protect_first_n=1,
            protect_last_n=1,
            quiet_mode=True,
        )

    messages = _basic_history()
    with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=5):
        with patch("agent.context_compressor.call_llm", return_value=_summary_response()):
            result = compressor.compress(messages)

    assert result[4]["content"] == "historical assistant prose about non-executive context"
    assert compressor._last_context_reducer_diagnostics["replacement_applied"] is False


def test_context_compressor_explicit_llm_replacement_allows_validated_low_risk_summary():
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        compressor = ContextCompressor(
            model="test/model",
            protect_first_n=1,
            protect_last_n=1,
            quiet_mode=True,
            allow_llm_replacement=True,
        )

    messages = _basic_history()
    with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=5):
        with patch("agent.context_compressor.call_llm", return_value=_summary_response()):
            result = compressor.compress(messages)

    assert result != messages
    assert len(result) < len(messages)
    assert any("CONTEXT COMPACTION" in str(msg.get("content", "")) for msg in result)
    assert any(msg.get("content") == "current user request must remain exact" for msg in result)
    diagnostics = compressor._last_context_reducer_diagnostics
    assert diagnostics["shadow_only"] is False
    assert diagnostics["allow_llm_replacement"] is True
    assert diagnostics["replacement_applied"] is True


def test_context_compressor_critical_block_bypasses_even_with_llm_replacement_opt_in():
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        compressor = ContextCompressor(
            model="test/model",
            protect_first_n=1,
            protect_last_n=1,
            quiet_mode=True,
            allow_llm_replacement=True,
        )

    messages = _basic_history()
    messages[3]["content"] = "必须保留原文，不要压缩这个执行合同。"
    with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=5):
        with patch("agent.context_compressor.call_llm") as call_llm:
            result = compressor.compress(messages)

    assert result == messages
    assert compressor._last_compress_aborted is True
    assert compressor._last_summary_critical_bypass is True
    call_llm.assert_not_called()


def test_context_compressor_stage_evidence_contract_bypasses_even_with_opt_in():
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        compressor = ContextCompressor(
            model="test/model",
            protect_first_n=1,
            protect_last_n=1,
            quiet_mode=True,
            allow_llm_replacement=True,
        )

    messages = _basic_history()
    messages[3]["content"] = "research_evidence_packet.md\nstage records\ncalibration verdict\nPASS / BLOCKED"
    with patch.object(compressor, "_find_tail_cut_by_tokens", return_value=5):
        with patch("agent.context_compressor.call_llm") as call_llm:
            result = compressor.compress(messages)

    assert result == messages
    assert compressor._last_summary_critical_bypass is True
    call_llm.assert_not_called()


def test_context_compressor_multimodal_tool_output_without_raw_ref_bypasses_stripping():
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        compressor = ContextCompressor(model="test/model", quiet_mode=True)

    image_parts = [
        {"type": "text", "text": "screenshot"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    messages = [{"role": "tool", "tool_call_id": "c1", "content": image_parts}]

    result, pruned = compressor._prune_old_tool_results(messages, protect_tail_count=0)

    assert pruned == 0
    assert result[0]["content"] == image_parts
    assert "multimodal_no_raw_ref_bypass" in compressor._last_context_reducer_diagnostics["bypass_reasons"]


def test_context_compressor_tool_call_args_without_raw_ref_bypasses_truncation():
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        compressor = ContextCompressor(model="test/model", quiet_mode=True)

    args = '{"content":"' + ("x" * 800) + '"}'
    messages = [
        {
            "role": "assistant",
            "content": "calling tool",
            "tool_calls": [{"id": "c1", "function": {"name": "write_file", "arguments": args}}],
        }
    ]

    result, pruned = compressor._prune_old_tool_results(messages, protect_tail_count=0)

    assert pruned == 0
    assert result[0]["tool_calls"][0]["function"]["arguments"] == args
    assert "tool_call_args_no_raw_ref_bypass" in compressor._last_context_reducer_diagnostics["bypass_reasons"]


def test_context_compressor_raw_ref_text_tool_output_reducer_still_allowed():
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        compressor = ContextCompressor(model="test/model", quiet_mode=True)

    messages = [
        {
            "role": "assistant",
            "content": "run command",
            "tool_calls": [{"id": "c1", "function": {"name": "terminal", "arguments": '{"command":"pytest"}'}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "line\n" * 80},
    ]

    result, pruned = compressor._prune_old_tool_results(messages, protect_tail_count=0)

    assert pruned == 1
    assert "raw_ref=" in result[1]["content"]
    assert "original_sha256=" in result[1]["content"]
    assert compressor._last_context_reducer_diagnostics["raw_ref_reducer_applied"] is True
