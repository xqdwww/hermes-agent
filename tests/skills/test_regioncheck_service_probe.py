from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "skills/clashverge-openclash-static/scripts/regioncheck_service_probe.py"
SPEC = importlib.util.spec_from_file_location("regioncheck_probe", SCRIPT)
assert SPEC and SPEC.loader
RRC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RRC)


SAMPLE = """
\x1b[32m ChatGPT:\t\tYes\x1b[0m
sleep: invalid number '0.03'
 Google Gemini:\tNo
 Disney+:\tNo (IP Banned By Disney+ 1)
 ** Your Network Provider: Example ISP (203.0.*.*)
 Telegram: https://t.me/example
"""


def test_clean_and_parse_three_services_without_ads() -> None:
    values = RRC.extract_service_values(SAMPLE)
    assert values == {
        "gpt": "Yes",
        "gemini": "No",
        "disney": "No (IP Banned By Disney+ 1)",
    }
    cleaned = "\n".join(RRC.clean_output(SAMPLE))
    assert "sleep: invalid" not in cleaned
    assert "Telegram" not in cleaned
    assert "\x1b" not in cleaned


@pytest.mark.parametrize(
    ("service", "raw", "normalized", "evidence"),
    [
        ("gpt", "Yes", "SCREEN_PASS", "SCREEN_PASS"),
        ("gemini", "Yes (Region: JP)", "SCREEN_PASS", "SCREEN_PASS"),
        ("gemini", "No", "SCREEN_NEGATIVE", "SCREEN_NEGATIVE"),
        ("disney", "No (IP Banned By Disney+ 1)", "FAIL_IP_BANNED", "UNKNOWN"),
        ("disney", "No", "FAIL_REGION", "UNKNOWN"),
        ("gpt", "Failed (Network Connection)", "FAIL_TRANSPORT", "UNKNOWN"),
        ("gemini", "Failed (Error: Unknown)", "UNKNOWN", "UNKNOWN"),
    ],
)
def test_result_semantics(
    service: str, raw: str, normalized: str, evidence: str
) -> None:
    assert RRC.normalize_result(service, raw) == (normalized, evidence)


def test_masked_ip_attribution() -> None:
    masked = RRC.extract_masked_ip(SAMPLE)
    assert masked == "203.0.*.*"
    assert RRC.masked_ip_matches("203.0.113.8", masked) is True
    assert RRC.masked_ip_matches("198.51.100.2", masked) is False


def test_report_rejects_full_ip_and_persists_only_hmac(tmp_path: Path) -> None:
    path = tmp_path / "safe.json"
    RRC.safe_atomic_json(path, {"exit_ip_hmac": "a" * 20})
    assert json.loads(path.read_text())["exit_ip_hmac"] == "a" * 20
    with pytest.raises(RRC.ProbeError, match="FULL_IP"):
        RRC.safe_atomic_json(path, {"exit": "203.0.113.8"})


def test_tool_inspection_requires_proxy_version_and_sha() -> None:
    class Completed:
        stdout = (
            "/usr/bin/regioncheck|/usr/lib/regionrestrictioncheck/check.sh|1.0.1|"
            + "a" * 64
            + "|yes\n"
        )

    class Skill:
        @staticmethod
        def ssh_command(_host: str, command: str, *, capture: bool):
            assert "-P | --proxy)" in command
            assert capture is True
            return Completed()

    metadata = RRC.inspect_tool(Skill, "router")
    assert metadata["explicit_proxy_supported"] is True
    assert metadata["tool_version"] == "1.0.1"


def test_regioncheck_invocation_is_noninteractive_and_explicit_proxy(monkeypatch) -> None:
    observed = {}

    class Completed:
        returncode = 0
        stdout = "ChatGPT: Yes"
        stderr = ""

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return Completed()

    class Skill:
        REMOTE_SIDECAR_MIXED_PORT = 7891

    monkeypatch.setattr(RRC.subprocess, "run", fake_run)
    code, _ = RRC.run_regioncheck(Skill, "router", 30)
    assert code == 0
    remote = observed["command"][-1]
    assert "-M 4" in remote
    assert "-R 0" in remote
    assert "-P http://127.0.0.1:7891" in remote
    assert "</dev/null" in remote
    assert observed["kwargs"]["timeout"] == 30


def test_control_geo_is_forced_to_same_ipv4_family_as_regioncheck(monkeypatch) -> None:
    observed = {}

    class Completed:
        returncode = 0
        stdout = '{"ip":"203.0.113.8","country":"JP"}'

    def fake_run(command, **kwargs):
        observed["command"] = command
        return Completed()

    monkeypatch.setattr(RRC.subprocess, "run", fake_run)
    assert RRC.control_geo(1234, sleep_fn=lambda _seconds: None) == ("203.0.113.8", "JP")
    assert "--ipv4" in observed["command"]


def test_control_geo_retries_once_then_succeeds(monkeypatch) -> None:
    calls = []

    class Completed:
        def __init__(self, returncode: int, stdout: str):
            self.returncode = returncode
            self.stdout = stdout

    responses = iter([
        Completed(7, ""),
        Completed(0, '{"ip":"203.0.113.8","country":"JP"}'),
    ])
    monkeypatch.setattr(RRC.subprocess, "run", lambda *_args, **_kwargs: next(responses))
    assert RRC.control_geo(1234, sleep_fn=calls.append) == ("203.0.113.8", "JP")
    assert calls == [1]


def test_node_transport_failure_records_all_services_without_ip() -> None:
    report = {"results": []}
    manifest = {
        "source_snapshot_id": "snapshot_test",
        "source_hash": "a" * 64,
    }
    tool = {
        "tool_version": "1.0.1",
        "script_sha256": "b" * 64,
    }
    RRC.append_service_results(
        report,
        manifest=manifest,
        identities={"node-a": "node_abc"},
        node_name="node-a",
        exit_hmac="",
        country="UNKNOWN",
        tool=tool,
        raw_values={
            service: "Failed (Network Connection)"
            for service in RRC.SERVICE_LABELS
        },
    )

    assert [item["service"] for item in report["results"]] == ["gpt", "gemini", "disney"]
    assert {item["result"] for item in report["results"]} == {"FAIL_TRANSPORT"}
    assert {item["exit_ip_hmac"] for item in report["results"]} == {""}
    assert {item["exit_country"] for item in report["results"]} == {"UNKNOWN"}


def test_regioncheck_values_are_completed_without_service_reuse() -> None:
    output = "ChatGPT: Yes\nDisney+: No (IP Banned By Disney+ 1)\n"

    assert RRC.normalize_regioncheck_values(0, output) == {
        "gpt": "Yes",
        "gemini": "Failed (Error: Unknown)",
        "disney": "No (IP Banned By Disney+ 1)",
    }
    assert RRC.normalize_regioncheck_values(124, "") == {
        "gpt": "Failed (Network Connection)",
        "gemini": "Failed (Network Connection)",
        "disney": "Failed (Network Connection)",
    }


def test_regioncheck_transport_retry_reruns_once(monkeypatch) -> None:
    calls = []
    responses = iter([
        (1, "ChatGPT: Failed (Network Connection)\n"),
        (0, "ChatGPT: Yes\nGoogle Gemini: No\nDisney+: Yes (Region: JP)\n"),
    ])

    def fake_run(_skill, _host, _timeout):
        calls.append("run")
        return next(responses)

    monkeypatch.setattr(RRC, "run_regioncheck", fake_run)
    code, _output, values = RRC.run_regioncheck_with_transport_retry(
        object(), "router", 30, sleep_fn=lambda _seconds: calls.append("sleep")
    )

    assert code == 0
    assert calls == ["run", "sleep", "run"]
    assert values == {
        "gpt": "Yes",
        "gemini": "No",
        "disney": "Yes (Region: JP)",
    }
