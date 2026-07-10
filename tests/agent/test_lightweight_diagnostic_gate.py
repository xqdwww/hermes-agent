import pytest

from agent.conversation_loop import _should_disable_tools_for_lightweight_diagnostic


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("请用最少步骤诊断：为什么我的 Langfuse tracing 之前一直 401", True),
        ("Be concise: why is the build failing?", False),
        ("快速判断一下，不用查", True),
    ],
)
def test_lightweight_diagnostic_gate_requested_examples(message, expected):
    assert _should_disable_tools_for_lightweight_diagnostic(message) is expected


@pytest.mark.parametrize(
    "message",
    [
        "minimal steps diagnose why this failed, check logs first",
        "最少步骤诊断：查日志确认为什么失败",
        "minimal steps diagnose why this failed, look at the build output",
        "最少步骤诊断：看一下日志为什么失败",
    ],
)
def test_lightweight_diagnostic_gate_keeps_tools_for_live_context(message):
    assert _should_disable_tools_for_lightweight_diagnostic(message) is False
