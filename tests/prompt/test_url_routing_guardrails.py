"""Guardrail tests for URL routing and tool output boundary fixes.

Covers all 5 test points:
  1. Bare Bilibili URL does NOT trigger youtube-content skill
  2. Bare URL with no explicit task asks intent first (or light recognition only)
  3. web_extract failure does NOT fall back to research_pipeline_runner
  4. Let me / Actually reasoning text filtered from visible output
  5. Engineering override phrase releases the RESEARCH gate
"""

import pytest


# ====================================================================
# Test 1: bare Bilibili URL → youtube-content NOT triggered
# ====================================================================

def test_url_routing_guidance_blocks_bilibili_youtube():
    """URL_ROUTING_GUIDANCE explicitly forbids youtube-content for Bilibili."""
    from agent.prompt_builder import URL_ROUTING_GUIDANCE
    assert "Bilibili" in URL_ROUTING_GUIDANCE
    assert "youtube-content" in URL_ROUTING_GUIDANCE
    assert "bilibili.com" in URL_ROUTING_GUIDANCE or "b23.tv" in URL_ROUTING_GUIDANCE
    # Should tell the model not to invoke youtube-content
    assert "do NOT" in URL_ROUTING_GUIDANCE or "do not" in URL_ROUTING_GUIDANCE
    assert "YouTube" in URL_ROUTING_GUIDANCE


def test_youtube_skill_excludes_bilibili():
    """youtube-content SKILL.md explicitly says do not trigger for Bilibili."""
    import os
    skill_path = os.path.expanduser(
        "~/.hermes/skills/media/youtube-content/SKILL.md"
    )
    with open(skill_path) as f:
        content = f.read()
    assert "Bilibili" in content or "bilibili" in content
    assert "b23.tv" in content or "bilibili.com" in content
    assert "do NOT" in content or "do not" in content


def test_web_extract_description_forbids_bilibili_youtube():
    """web_extract tool description says do NOT invoke youtube-content for Bilibili."""
    from tools.web_tools import WEB_EXTRACT_SCHEMA
    desc = WEB_EXTRACT_SCHEMA["description"]
    assert "bilibili.com" in desc or "b23.tv" in desc
    assert "youtube-content" in desc
    assert "do NOT" in desc or "do not" in desc


# ====================================================================
# Test 2: bare URL without explicit task → ask intent first
# ====================================================================

def test_url_routing_guidance_bare_url_asks_intent():
    """URL_ROUTING_GUIDANCE says ask intent for bare URLs without instruction."""
    from agent.prompt_builder import URL_ROUTING_GUIDANCE
    # Should tell model to ask what user wants
    assert "no explicit instruction" in URL_ROUTING_GUIDANCE
    # Should tell model NOT to jump into heavy chains
    assert "research_pipeline_runner" in URL_ROUTING_GUIDANCE
    assert "task_engine_runner" in URL_ROUTING_GUIDANCE
    assert "terminal curl" in URL_ROUTING_GUIDANCE
    # Should tell model to ask briefly
    assert "ask" in URL_ROUTING_GUIDANCE.lower()


# ====================================================================
# Test 3: web_extract failure → no fallback to research_pipeline_runner
# ====================================================================

def test_web_extract_description_no_research_fallback():
    """web_extract tool description says no fallback to research_pipeline_runner."""
    from tools.web_tools import WEB_EXTRACT_SCHEMA
    desc = WEB_EXTRACT_SCHEMA["description"]
    assert "research_pipeline_runner" in desc
    assert "task_engine_runner" in desc
    assert "terminal curl" in desc
    assert "do NOT fall back" in desc or "do not fall back" in desc


def test_url_routing_guidance_no_research_fallback():
    """URL_ROUTING_GUIDANCE says no fallback to research on failure."""
    from agent.prompt_builder import URL_ROUTING_GUIDANCE
    assert "falls" in URL_ROUTING_GUIDANCE or "fail" in URL_ROUTING_GUIDANCE
    assert "do NOT fall back" in URL_ROUTING_GUIDANCE
    assert "research_pipeline_runner" in URL_ROUTING_GUIDANCE


# ====================================================================
# Test 4: Let me / Actually reasoning text filtered from visible output
# ====================================================================

def test_think_scrubber_filters_let_me():
    """StreamingThinkScrubber filters 'Let me...' at block boundary."""
    from agent.think_scrubber import StreamingThinkScrubber

    s = StreamingThinkScrubber()
    result = s.feed("Let me check the URL first")
    assert result == "", f"Expected empty, got: {result!r}"


def test_think_scrubber_filters_actually():
    """StreamingThinkScrubber filters 'Actually,' at block boundary."""
    from agent.think_scrubber import StreamingThinkScrubber

    s = StreamingThinkScrubber()
    result = s.feed("Actually, I should check the config")
    assert result == "", f"Expected empty, got: {result!r}"


def test_think_scrubber_filters_i_should():
    """StreamingThinkScrubber filters 'I should' at block boundary."""
    from agent.think_scrubber import StreamingThinkScrubber

    s = StreamingThinkScrubber()
    result = s.feed("I should first check the repository")
    assert result == "", f"Expected empty, got: {result!r}"


def test_think_scrubber_mid_sentence_let_me_not_filtered():
    """Mid-sentence 'let me' NOT blocked (not at block boundary)."""
    from agent.think_scrubber import StreamingThinkScrubber

    s = StreamingThinkScrubber()
    result = s.feed("Hello there, let me show you")
    assert "let me show" in result, f"Expected content preserved, got: {result!r}"


def test_think_scrubber_blank_line_recovers_after_think():
    """Text-think block closed by blank line recovers real response."""
    from agent.think_scrubber import StreamingThinkScrubber

    s = StreamingThinkScrubber()
    result = s.feed("Let me check the URL...\n\nHere is the real answer")
    assert result == "Here is the real answer", f"Expected real answer, got: {result!r}"


def test_think_scrubber_multi_feed_text_think():
    """Multi-feed text think works across stream deltas."""
    from agent.think_scrubber import StreamingThinkScrubber

    s = StreamingThinkScrubber()
    r1 = s.feed("Let me check")
    assert r1 == "", f"Part 1 should be filtered, got: {r1!r}"
    r2 = s.feed(" this URL...")
    assert r2 == "", f"Part 2 should be filtered, got: {r2!r}"
    r3 = s.feed("\n\nOK here's the result")
    assert r3 == "OK here's the result", f"Part 3 should recover, got: {r3!r}"


def test_think_scrubber_no_close_flush_discards():
    """Text think without blank line close is discarded at flush."""
    from agent.think_scrubber import StreamingThinkScrubber

    s = StreamingThinkScrubber()
    r1 = s.feed("Let me think about this")
    assert r1 == "", f"Think text should be empty, got: {r1!r}"
    r2 = s.flush()
    assert r2 == "", f"Flush should discard, got: {r2!r}"


def test_think_scrubber_whitespace_prefixed():
    """Whitespace-prefixed think markers at block boundary are filtered."""
    from agent.think_scrubber import StreamingThinkScrubber

    s = StreamingThinkScrubber()
    result = s.feed("  Let me check this")
    assert result == "", f"Whitespace-prefixed think should be filtered, got: {result!r}"


def test_think_scrubber_normal_text_passes():
    """Normal text without think markers passes through."""
    from agent.think_scrubber import StreamingThinkScrubber

    s = StreamingThinkScrubber()
    result = s.feed("This is the actual response for the user")
    assert result == "This is the actual response for the user"


# ====================================================================
# Test 5: Engineering override releases the RESEARCH gate
# ====================================================================

def test_engineering_override_guidance_defined():
    """ENGINEERING_OVERRIDE_GUIDANCE exists and mentions release phrases."""
    from agent.prompt_builder import ENGINEERING_OVERRIDE_GUIDANCE
    text = ENGINEERING_OVERRIDE_GUIDANCE.lower()
    assert "gate" in text
    assert "blocked" in text
    assert "GATE_RELEASE_CONFIRMED" in ENGINEERING_OVERRIDE_GUIDANCE
    assert "engineering" in ENGINEERING_OVERRIDE_GUIDANCE.lower()


def test_turn_context_has_release_phrases():
    """turn_context.py has gate release detection phrases."""
    import ast
    import os

    # The test file is at tests/prompt/test_url_routing_guardrails.py.
    # Go up 3 levels to reach project root.
    tc_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "agent/turn_context.py",
    )
    with open(tc_path) as f:
        content = f.read()
    assert "GATE_RELEASE_CONFIRMED" in content
    assert "gate_release_confirmed" in content
    assert "gate_state" in content
    assert "auto-released" in content


def test_task_mode_runtime_reset_clears_gate():
    """TaskModeRuntime.reset() clears gate state."""
    from tools.task_mode_runtime import TaskModeRuntime, TaskModeState

    rt = TaskModeRuntime()
    # Activate gate
    rt.activate(task_type="RESEARCH", user_input="test")
    assert rt.is_gated
    # Reset
    rt.reset()
    assert not rt.is_gated
    assert rt.state == TaskModeState.ACTIVE


def test_task_mode_runtime_preflight_blocks_tools():
    """INIT_LOCKED blocks execution tools but allows clarify."""
    from tools.task_mode_runtime import (
        TaskModeRuntime,
        TaskModeState,
        _EXECUTION_TOOLS,
        _ALWAYS_ALLOWED,
    )

    rt = TaskModeRuntime()
    rt.activate(task_type="RESEARCH", user_input="test")

    # Terminal should be blocked
    blocked = rt.preflight("terminal")
    assert blocked is not None
    assert "GATE BLOCKED" in blocked

    # clarify should still be allowed
    allowed = rt.preflight("clarify")
    assert allowed is None


def test_youtube_content_skill_excludes_bilibili_and_bare_url():
    from pathlib import Path

    skill_path = Path("skills/media/youtube-content/SKILL.md")
    assert skill_path.exists(), "youtube-content skill must be checked at the canonical skills/media path"

    text = skill_path.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "bilibili" in lowered
    assert "b23.tv" in lowered
    assert "do **not** use this skill for bilibili urls" in lowered
    assert "bare url" in lowered
    assert "ask the user what they want done" in lowered

