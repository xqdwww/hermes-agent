"""Protocol V1 tests for generic sensitive registered tools."""

import json
import inspect

import pytest

import model_tools
from agent.tool_executor import _safe_tool_callback_args, _safe_tool_callback_result
from tools.registry import SENSITIVE_PERSISTENCE_PROTOCOL, ToolRegistry, registry
from run_agent import AIAgent


def _schema(name: str) -> dict:
    return {
        "name": name,
        "description": "Synthetic protocol test tool",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["action", "value"],
            "additionalProperties": False,
        },
    }


def _sensitive_policy() -> dict:
    return {
        "class": "sensitive_personal_data",
        "required_runtime_capability": SENSITIVE_PERSISTENCE_PROTOCOL,
        "persistence": {
            "arguments": "redacted",
            "result": "redacted",
            "errors": "redacted",
        },
        "live_result_delivery": "ephemeral",
    }


def test_standard_policy_is_explicit_compatibility_default():
    reg = ToolRegistry()
    reg.register("plain", "test", _schema("plain"), lambda args: "ok")
    assert reg.get_privacy_policy("plain") == {"class": "standard"}


def test_public_agent_constructor_accepts_runtime_capabilities():
    assert "runtime_capabilities" in inspect.signature(AIAgent.__init__).parameters


def test_sensitive_policy_is_detached_and_invalid_policy_is_rejected():
    reg = ToolRegistry()
    policy = _sensitive_policy()
    reg.register("private", "test", _schema("private"), lambda args: "ok", privacy_policy=policy)
    policy["persistence"]["result"] = "raw"
    assert reg.get_privacy_policy("private")["persistence"]["result"] == "redacted"
    with pytest.raises(ValueError):
        reg.register(
            "invalid", "test", _schema("invalid"), lambda args: "ok",
            privacy_policy={"class": "sensitive_personal_data"},
        )


def test_missing_or_wrong_capability_fails_before_handler_and_hooks(monkeypatch):
    reg = ToolRegistry()
    calls = []
    reg.register(
        "private", "test", _schema("private"),
        lambda args, **kwargs: calls.append(args) or json.dumps({"secret": args["value"]}),
        privacy_policy=_sensitive_policy(),
    )
    monkeypatch.setattr(model_tools, "registry", reg)
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("hook received private args")),
    )
    for capabilities in (None, [], ["sensitive_tool_persistence_v0"]):
        result = json.loads(model_tools.handle_function_call(
            "private",
            {"action": "echo", "value": "PRIVATE_ARGUMENT_CANARY"},
            runtime_capabilities=capabilities,
        ))
        assert result == {
            "status": "unavailable",
            "error_code": "sensitive_persistence_capability_missing",
            "handler_executed": False,
        }
        assert "PRIVATE_ARGUMENT_CANARY" not in json.dumps(result)
    assert calls == []


def test_formal_envelope_validates_schema_scope_and_preserves_call_id(monkeypatch):
    reg = ToolRegistry()
    received = []
    reg.register(
        "private", "test", _schema("private"),
        lambda args, **kwargs: received.append(args) or json.dumps({"secret": "PRIVATE_RESULT_CANARY"}),
        privacy_policy=_sensitive_policy(),
    )
    monkeypatch.setattr(model_tools, "registry", reg)
    envelope = model_tools.dispatch_tool_call_envelope(
        "private",
        {"action": "echo", "value": "PRIVATE_ARGUMENT_CANARY"},
        tool_call_id="call-stable-1",
        runtime_capabilities=[SENSITIVE_PERSISTENCE_PROTOCOL],
        enabled_tools=["private"],
    )
    assert envelope["tool_call_id"] == "call-stable-1"
    assert envelope["privacy_class"] == "sensitive_personal_data"
    assert json.loads(envelope["ephemeral_result"])["secret"] == "PRIVATE_RESULT_CANARY"
    assert "PRIVATE_ARGUMENT_CANARY" not in json.dumps(envelope["safe_audit"])
    assert received == [{"action": "echo", "value": "PRIVATE_ARGUMENT_CANARY"}]

    invalid = model_tools.dispatch_tool_call_envelope(
        "private", {"action": "echo"}, tool_call_id="invalid",
        runtime_capabilities=[SENSITIVE_PERSISTENCE_PROTOCOL], enabled_tools=["private"],
    )
    assert invalid["error_code"] == "tool_schema_validation_failed"
    disabled = model_tools.dispatch_tool_call_envelope(
        "private", {"action": "echo", "value": "hidden"}, tool_call_id="disabled",
        runtime_capabilities=[SENSITIVE_PERSISTENCE_PROTOCOL], enabled_tools=[],
    )
    assert disabled["error_code"] == "tool_not_enabled"
    assert len(received) == 1


def test_standard_tool_needs_no_sensitive_capability(monkeypatch):
    reg = ToolRegistry()
    reg.register("plain", "test", _schema("plain"), lambda args, **kwargs: json.dumps({"ok": True}))
    monkeypatch.setattr(model_tools, "registry", reg)
    result = model_tools.dispatch_tool_call_envelope(
        "plain", {"action": "run", "value": "ordinary"}, tool_call_id="plain-1",
        runtime_capabilities=[], enabled_tools=["plain"],
    )
    assert result["status"] == "ok"
    assert json.loads(result["ephemeral_result"]) == {"ok": True}


def test_sensitive_callbacks_expose_only_persistent_surrogates():
    name = "synthetic_sensitive_callback_test"
    registry.register(name, "test", _schema(name), lambda args: "ok", privacy_policy=_sensitive_policy())
    try:
        safe_args = _safe_tool_callback_args(
            name, {"action": "echo", "value": "PRIVATE_ARGUMENT_CANARY"}, "call-1",
        )
        safe_result = _safe_tool_callback_result(name, "PRIVATE_RESULT_CANARY", "call-1")
        combined = json.dumps(safe_args) + str(safe_result)
        assert "PRIVATE_ARGUMENT_CANARY" not in combined
        assert "PRIVATE_RESULT_CANARY" not in combined
        assert safe_args["_hermes_sensitive_tool"]["redaction_applied"] is True
        assert json.loads(safe_result)["audit"]["raw_result_persisted"] is False
    finally:
        registry.deregister(name)
