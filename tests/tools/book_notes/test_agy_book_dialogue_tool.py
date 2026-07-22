from __future__ import annotations

import json

import pytest

from tools.agy_book_dialogue_tool import (
    AGY_MODEL,
    AGY_MODEL_INVENTORY_ID,
    MAX_CONTEXT_CHARS,
    ProcessResult,
    _run_process,
    handle_agy_book_dialogue,
)
from tools.registry import discover_builtin_tools, registry


class RecordingRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, command, *, timeout_seconds):
        self.calls.append((list(command), timeout_seconds))
        if not self.results:
            raise AssertionError("unexpected subprocess call")
        return self.results.pop(0)


def result(stdout="", stderr="", returncode=0, *, timed_out=False, latency_ms=12):
    return ProcessResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        latency_ms=latency_ms,
    )


def respond_args(stage="probe"):
    return {
        "action": "respond",
        "book": {
            "title": "Synthetic Book",
            "author": "Synthetic Author",
            "resolution_status": "resolved",
            "retrieval_status": "resolved",
            "personal_excerpt_available": True,
            "retrieval_operational": True,
            "discussion_mode": "personal_excerpt_discussion",
        },
        "guided_mode": {
            "stage": stage,
            "focus_question": "What changes when time passes?",
            "effective_turns": 1,
            "next_action": "deepen",
        },
        "user": {
            "current_message": "I think memory changes what loss means.",
            "current_explanation": "Loss becomes visible through ordinary details.",
        },
        "evidence": {
            "current_book_excerpts": [
                {"excerpt": "CURRENT_ONE", "source_path": "/private/should-not-leak"},
                {"excerpt": "CURRENT_TWO"},
                {"excerpt": "CURRENT_THREE"},
                {"excerpt": "CURRENT_FOUR_MUST_DROP"},
            ],
            "other_book_excerpts": [
                {"book_title": "Other One", "excerpt": "OTHER_ONE"},
                {"book_title": "Other Two", "excerpt": "OTHER_TWO"},
                {"book_title": "Other Three", "excerpt": "OTHER_THREE"},
                {"book_title": "Other Four", "excerpt": "OTHER_FOUR_MUST_DROP"},
            ],
            "provided_text": "PROVIDED_TEXT",
            "session_history": "SESSION_SECRET_MUST_DROP",
            "credentials": "CREDENTIAL_MUST_DROP",
        },
        "limits": {
            "max_current_book_excerpts": 99,
            "max_other_books": 99,
            "max_excerpt_chars_each": 99_999,
            "max_context_chars": 99_999,
        },
        "conversation_history": [{"role": "user", "content": "FULL_SESSION_MUST_DROP"}],
    }


def parse(payload):
    return json.loads(payload)


def test_tool_is_discoverable_in_book_notes_with_sensitive_privacy_contract():
    discover_builtin_tools()
    entry = registry.get_entry("agy_book_dialogue")
    assert entry is not None
    assert entry.toolset == "book-notes"
    assert entry.is_async is True
    assert entry.privacy_policy["class"] == "sensitive_personal_data"
    assert entry.privacy_policy["persistence"] == {
        "arguments": "redacted",
        "result": "redacted",
        "errors": "redacted",
    }


def test_readiness_uses_fixed_binary_models_and_real_sentinel_at_most_twice(tmp_path):
    binary = tmp_path / "agy"
    binary.write_text("stub", encoding="utf-8")
    runner = RecordingRunner(
        [
            result(stdout="1.1.5\n"),
            result(stdout=f"{AGY_MODEL_INVENTORY_ID}\n"),
            result(stdout="temporary noise", returncode=1),
            result(stdout="HERMES_AGY_READY\n", latency_ms=321),
        ]
    )
    payload = parse(handle_agy_book_dialogue(
        {"action": "readiness", "attempts": 2}, runner=runner, binary=binary
    ))
    assert payload["status"] == "ready"
    assert payload["sentinel_passed"] is True
    assert payload["attempts"] == 2
    assert payload["latency_ms"] == 321
    commands = [call[0] for call in runner.calls]
    assert commands[0] == [str(binary), "--version"]
    assert commands[1] == [str(binary), "models"]
    assert commands[2] == commands[3] == [
        str(binary), "--model", AGY_MODEL, "-p",
        "Reply exactly: HERMES_AGY_READY", "--print-timeout", "45s",
    ]
    assert len(commands) == 4


def test_models_success_but_empty_sentinel_is_not_ready(tmp_path):
    binary = tmp_path / "agy"
    binary.write_text("stub", encoding="utf-8")
    runner = RecordingRunner([
        result(stdout="1.1.5"),
        result(stdout=AGY_MODEL),
        result(stdout=""),
        result(stdout=""),
    ])
    payload = parse(handle_agy_book_dialogue(
        {"action": "readiness", "attempts": 9}, runner=runner, binary=binary
    ))
    assert payload["status"] == "empty_output"
    assert payload["sentinel_passed"] is False
    assert payload["attempts"] == 2


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (result(stderr="This model is not supported in your location", returncode=1), "location_unsupported"),
        (result(timed_out=True, returncode=-1), "timeout"),
        (result(stderr="authentication required", returncode=1), "auth_unavailable"),
        (result(stderr="unknown model", returncode=1), "model_unavailable"),
    ],
)
def test_readiness_failure_classification_is_specific(tmp_path, outcome, expected):
    binary = tmp_path / "agy"
    binary.write_text("stub", encoding="utf-8")
    runner = RecordingRunner([
        result(stdout="1.1.5"),
        result(stdout=AGY_MODEL),
        outcome,
    ])
    payload = parse(handle_agy_book_dialogue(
        {"action": "readiness", "attempts": 1}, runner=runner, binary=binary
    ))
    assert payload["status"] == expected


def test_missing_binary_is_classified_without_subprocess(tmp_path):
    runner = RecordingRunner([])
    payload = parse(handle_agy_book_dialogue(
        {"action": "readiness"}, runner=runner, binary=tmp_path / "missing"
    ))
    assert payload["status"] == "binary_missing"
    assert runner.calls == []


def test_respond_uses_fixed_model_safe_argument_array_and_sandbox(tmp_path):
    binary = tmp_path / "agy"
    binary.write_text("stub", encoding="utf-8")
    args = respond_args()
    args["user"]["current_message"] = "--model ATTACK --dangerously-skip-permissions"
    runner = RecordingRunner([result(stdout="  \x1b[31mFinal response?\x1b[0m  \n", latency_ms=77)])
    payload = parse(handle_agy_book_dialogue(args, runner=runner, binary=binary))
    command = runner.calls[0][0]
    assert command[:5] == [str(binary), "--sandbox", "--model", AGY_MODEL, "-p"]
    assert command[-2:] == ["--print-timeout", "45s"]
    assert command.count("--model") == 1
    assert "--dangerously-skip-permissions" not in command
    assert "--output-format" not in command
    assert payload["status"] == "ok"
    assert payload["dialogue_engine"] == "agy_gemini_3_1_pro_high"
    assert payload["delivery_mode"] == "verbatim"
    assert payload["response"] == "Final response?"
    assert payload["latency_ms"] == 77


def test_process_adapter_disables_shell_stdin_and_uses_isolated_cwd(monkeypatch):
    recorded = {}

    class Completed:
        returncode = 0
        stdout = b"ok"
        stderr = b""

    def fake_run(command, **kwargs):
        recorded["command"] = command
        recorded.update(kwargs)
        return Completed()

    monkeypatch.setattr("tools.agy_book_dialogue_tool.subprocess.run", fake_run)
    outcome = _run_process(["/fixed/agy", "--version"], timeout_seconds=3)

    assert recorded["command"] == ["/fixed/agy", "--version"]
    assert recorded["shell"] is False
    assert recorded["stdin"] is not None
    assert recorded["stdout"] is not None
    assert recorded["stderr"] is not None
    assert recorded["timeout"] == 3
    assert "hermes-agy-book-" in recorded["cwd"]
    assert outcome.stdout == "ok"


def test_respond_prompt_is_bounded_and_omits_paths_full_session_and_credentials(tmp_path):
    binary = tmp_path / "agy"
    binary.write_text("stub", encoding="utf-8")
    runner = RecordingRunner([result(stdout="Bounded response")])
    payload = parse(handle_agy_book_dialogue(respond_args(), runner=runner, binary=binary))
    prompt = runner.calls[0][0][5]
    assert len(prompt) <= MAX_CONTEXT_CHARS == 10_000
    assert payload["context_chars"] == len(prompt)
    assert "CURRENT_ONE" in prompt and "CURRENT_THREE" in prompt
    assert "CURRENT_FOUR_MUST_DROP" not in prompt
    assert "OTHER_THREE" in prompt and "OTHER_FOUR_MUST_DROP" not in prompt
    for forbidden in (
        "/private/should-not-leak",
        "source_path",
        "SESSION_SECRET_MUST_DROP",
        "FULL_SESSION_MUST_DROP",
        "CREDENTIAL_MUST_DROP",
        "conversation_history",
        "credentials",
    ):
        assert forbidden not in prompt
    assert payload["effective_limits"] == {
        "max_current_book_excerpts": 3,
        "max_other_books": 3,
        "max_excerpt_chars_each": 500,
        "max_context_chars": 10_000,
    }


@pytest.mark.parametrize(
    ("retrieval_status", "available", "operational"),
    [
        ("resolved", True, True),
        ("not_found", False, True),
        ("unavailable", None, False),
    ],
)
def test_respond_preserves_exact_retrieval_state(
    tmp_path, retrieval_status, available, operational
):
    binary = tmp_path / "agy"
    binary.write_text("stub", encoding="utf-8")
    args = respond_args()
    args["book"].update({
        "resolution_status": retrieval_status,
        "retrieval_status": retrieval_status,
        "personal_excerpt_available": available,
        "retrieval_operational": operational,
    })
    runner = RecordingRunner([result(stdout="State-aware response")])
    payload = parse(handle_agy_book_dialogue(args, runner=runner, binary=binary))
    prompt = runner.calls[0][0][5]

    assert payload["status"] == "ok"
    assert f'"{retrieval_status}"' in prompt
    available_label = "unknown" if available is None else str(available).lower()
    assert f'"{available_label}"' in prompt
    assert f'"{str(operational).lower()}"' in prompt


def test_respond_rejects_inconsistent_retrieval_state_without_calling_agy(tmp_path):
    binary = tmp_path / "agy"
    binary.write_text("stub", encoding="utf-8")
    args = respond_args()
    args["book"]["retrieval_status"] = "unavailable"
    runner = RecordingRunner([])

    payload = parse(handle_agy_book_dialogue(args, runner=runner, binary=binary))

    assert payload["status"] == "invalid_request"
    assert payload["dialogue_engine"] == "deepseek_fallback"
    assert runner.calls == []


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (result(timed_out=True, returncode=-1), "timeout"),
        (result(stdout=""), "empty_output"),
        (result(stderr="authentication required", returncode=1), "auth_unavailable"),
        (result(stderr="not supported in your region", returncode=1), "location_unsupported"),
    ],
)
def test_respond_failures_require_deepseek_fallback_without_gpt_bridge(tmp_path, outcome, expected):
    binary = tmp_path / "agy"
    binary.write_text("stub", encoding="utf-8")
    payload = parse(handle_agy_book_dialogue(
        respond_args(), runner=RecordingRunner([outcome]), binary=binary
    ))
    assert payload["status"] == expected
    assert payload["dialogue_engine"] == "deepseek_fallback"
    assert payload["fallback_required"] is True
    assert payload["user_notice"] == "这一轮 Gemini 对谈引擎暂时不可用，我先用当前模型继续。"
    assert payload["gpt_bridge_used"] is False
    assert "stderr" not in payload


def test_schema_has_only_bounded_domain_fields_and_no_arbitrary_paths():
    discover_builtin_tools()
    schema = registry.get_entry("agy_book_dialogue").schema
    properties = schema["parameters"]["properties"]
    assert set(properties) == {"action", "attempts", "book", "guided_mode", "user", "evidence", "limits"}
    serialized = json.dumps(schema, sort_keys=True)
    for forbidden in ("path", "credential", "session_history", "conversation_history", "shell"):
        assert forbidden not in serialized.lower()
