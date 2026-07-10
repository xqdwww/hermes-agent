"""Tests for the video_report_passthrough detection in conversation_loop.py.

Verifies that the conversation loop detects video_report_passthrough tool
results and uses them directly as the final_response, bypassing any
model-based re-summarization.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


# ── Tool call simulation helpers ─────────────────────────────────────────────


def make_tool_call(tool_name: str, tool_call_id: str, args: dict | None = None):
    """Create a mock tool call object similar to an OpenAI tool_call."""
    tc = MagicMock()
    tc.id = tool_call_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(args or {})
    return tc


def make_tool_result_message(tool_call_id: str, content: str):
    """Create a tool result message dict."""
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


# ── _video_summary_header tests ──────────────────────────────────────────────
# Uses lazy import to avoid heavy conversation_loop transitive deps at
# module level.


def _import_header():
    """Lazily import _video_summary_header from conversation_loop."""
    from agent.conversation_loop import _video_summary_header
    return _video_summary_header


@pytest.mark.parametrize(
    "content, expected_lines, expected_chars",
    [
        ("line1\nline2\n", 3, 12),
        ("short content", 1, 13),
        ("\n\n\n", 4, 3),
    ],
)
def test_video_summary_header(content, expected_lines, expected_chars):
    """Verify the header helper produces correct stats."""
    header_fn = _import_header()
    header = header_fn(content)
    assert str(expected_lines) in header
    assert str(expected_chars) in header
    assert "verbatim" in header


def test_header_is_not_part_of_report_content():
    """_video_summary_header should be a brief metadata line, not the report."""
    header_fn = _import_header()
    report = "# Video Summary\n\nDetailed analysis..."
    header = header_fn(report)
    assert "verbatim" in header
    assert "no LLM re-summarization" in header
    assert "lines" in header
    assert "chars" in header
    # The header should NOT contain the actual report content
    assert "# Video Summary" not in header


# ── Passthrough detection logic (extracted) ──────────────────────────────────
# These tests directly exercise the detection algorithm that lives in
# conversation_loop.py, extracted here for isolation.


def _detect_passthrough(
    assistant_message,
    messages: list,
) -> str | None:
    """Replica of the conversation_loop passthrough detection logic."""
    _passthrough_tc_ids = [
        tc.id for tc in assistant_message.tool_calls
        if tc.function.name == "video_report_passthrough"
    ]
    if not _passthrough_tc_ids:
        return None

    _passthrough_content = None
    for msg in reversed(messages):
        if (
            isinstance(msg, dict)
            and msg.get("role") == "tool"
            and msg.get("tool_call_id") in _passthrough_tc_ids
        ):
            _raw = msg.get("content", "") or ""
            _passthrough_content = _raw
            break

    if _passthrough_content:
        try:
            _parsed = json.loads(_passthrough_content)
            if isinstance(_parsed, dict) and "error" in _parsed:
                return None
        except (json.JSONDecodeError, TypeError):
            pass

    return _passthrough_content


class TestPassthroughDetection:
    """Test the passthrough detection algorithm."""

    def test_detects_passthrough_and_returns_content(self):
        tc = make_tool_call("video_report_passthrough", "tc-1", {"path": "/some/report.md"})
        msgs = [make_tool_result_message("tc-1", "# Full Report\n\ncontent here")]
        result = _detect_passthrough(
            MagicMock(tool_calls=[tc]),
            msgs,
        )
        assert result == "# Full Report\n\ncontent here"

    def test_ignores_non_passthrough_tools(self):
        tc = make_tool_call("read_file", "tc-1", {"path": "/some/file.md"})
        result = _detect_passthrough(
            MagicMock(tool_calls=[tc]),
            [make_tool_result_message("tc-1", "file content")],
        )
        assert result is None

    def test_returns_none_on_error_response(self):
        tc = make_tool_call("video_report_passthrough", "tc-1", {"path": "/bad/path"})
        msgs = [make_tool_result_message("tc-1", json.dumps({"error": "Path not allowed"}))]
        result = _detect_passthrough(MagicMock(tool_calls=[tc]), msgs)
        assert result is None

    def test_selects_last_tool_result_when_multiple_messages(self):
        tc = make_tool_call("video_report_passthrough", "tc-1")
        msgs = [
            make_tool_result_message("other-tc", "some previous result"),
            make_tool_result_message("tc-1", "# Final Report"),
        ]
        result = _detect_passthrough(MagicMock(tool_calls=[tc]), msgs)
        assert result == "# Final Report"

    def test_handles_multiple_tool_calls_mixed(self):
        tc1 = make_tool_call("web_search", "tc-1")
        tc2 = make_tool_call("video_report_passthrough", "tc-2")
        msgs = [
            make_tool_result_message("tc-1", "search results"),
            make_tool_result_message("tc-2", "# Report Content"),
        ]
        result = _detect_passthrough(MagicMock(tool_calls=[tc1, tc2]), msgs)
        assert result == "# Report Content"

    def test_handles_empty_content_gracefully(self):
        tc = make_tool_call("video_report_passthrough", "tc-1")
        msgs = [make_tool_result_message("tc-1", "")]
        result = _detect_passthrough(MagicMock(tool_calls=[tc]), msgs)
        assert result == ""  # empty content is returned (no error JSON)

    def test_no_tool_calls_returns_none(self):
        result = _detect_passthrough(MagicMock(tool_calls=[]), [])
        assert result is None

    def test_mismatched_tool_call_id_returns_none(self):
        tc = make_tool_call("video_report_passthrough", "tc-1")
        # Only have result for a different tool call id
        msgs = [make_tool_result_message("tc-2", "some content")]
        result = _detect_passthrough(MagicMock(tool_calls=[tc]), msgs)
        assert result is None

    def test_handles_multiple_passthrough_calls(self):
        """If multiple passthrough calls are made, the last result wins."""
        tc = make_tool_call("video_report_passthrough", "tc-1")
        tc2 = make_tool_call("video_report_passthrough", "tc-2")
        msgs = [
            make_tool_result_message("tc-1", "# First Report"),
            make_tool_result_message("tc-2", "# Second Report"),
        ]
        result = _detect_passthrough(MagicMock(tool_calls=[tc, tc2]), msgs)
        # reversed() means tc-2 result comes first — that becomes the content.
        assert result == "# Second Report"
