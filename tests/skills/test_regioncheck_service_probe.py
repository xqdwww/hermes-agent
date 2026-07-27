from __future__ import annotations

import importlib.util
import inspect
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

    monkeypatch.setattr(RRC.subprocess, "run", fake_run)
    code, _ = RRC.run_regioncheck(
        "router",
        30,
        proxy_url="http://127.0.0.1:7891",
        runner_scope="remote",
    )
    assert code == 0
    remote = observed["command"][-1]
    assert "-M 4" in remote
    assert "-R 0" in remote
    assert "-P http://127.0.0.1:7891" in remote
    assert "</dev/null" in remote
    assert observed["kwargs"]["timeout"] == 30


def test_control_geo_falls_back_across_fresh_ipv4_backends(monkeypatch) -> None:
    observed = []

    class Completed:
        def __init__(self, returncode: int, stdout: str):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(command, **kwargs):
        observed.append((command, kwargs))
        return [
            Completed(7, ""),
            Completed(0, "<html>challenge</html>"),
            Completed(0, '{"ip":"8.8.8.8","country":"US"}'),
        ][len(observed) - 1]

    monkeypatch.setattr(RRC, "run_in_runner_scope", fake_run)
    assert RRC.control_geo(
        proxy_url="http://127.0.0.1:1234",
        runner_scope="local",
        host="unused",
        sleep_fn=lambda _seconds: None,
    ) == ("8.8.8.8", "US")
    assert len(observed) == 3
    assert all("--ipv4" in command for command, _kwargs in observed)
    assert all("--no-keepalive" in command for command, _kwargs in observed)
    assert all(
        command[command.index("--proxy") + 1] == "http://127.0.0.1:1234"
        for command, _kwargs in observed
    )
    assert len({command[-1] for command, _kwargs in observed}) == 3


def test_control_geo_rejects_non_public_or_non_ipv4_results(monkeypatch) -> None:
    class Completed:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str):
            self.stdout = stdout

    responses = iter(
        [
            Completed('{"ip":"10.0.0.1"}'),
            Completed('{"ip":"2001:4860:4860::8888"}'),
            Completed('{"ip":"1.1.1.1","country":"AU"}'),
        ]
    )
    monkeypatch.setattr(
        RRC,
        "run_in_runner_scope",
        lambda *_args, **_kwargs: next(responses),
    )
    assert RRC.control_geo(
        proxy_url="http://127.0.0.1:1234",
        runner_scope="local",
        host="unused",
    ) == ("1.1.1.1", "AU")


def test_control_geo_falls_back_to_cloudflare_trace_after_json_tls_failures(
    monkeypatch,
) -> None:
    class Completed:
        stderr = ""

        def __init__(self, returncode: int, stdout: str):
            self.returncode = returncode
            self.stdout = stdout

    responses = iter(
        [
            Completed(35, ""),
            Completed(35, ""),
            Completed(35, ""),
            Completed(0, "fl=1\nip=8.8.4.4\nts=1\n"),
        ]
    )
    monkeypatch.setattr(
        RRC,
        "run_in_runner_scope",
        lambda *_args, **_kwargs: next(responses),
    )

    assert RRC.control_geo(
        proxy_url="http://127.0.0.1:1234",
        runner_scope="local",
        host="unused",
    ) == ("8.8.4.4", "UNKNOWN")


def test_control_geo_retries_full_backend_set_once(monkeypatch) -> None:
    class Completed:
        stderr = ""

        def __init__(self, returncode: int, stdout: str):
            self.returncode = returncode
            self.stdout = stdout

    responses = iter(
        [Completed(28, "") for _backend in RRC.CONTROL_ATTRIBUTION_BACKENDS]
        + [Completed(0, '{"ip":"8.8.8.8","country":"US"}')]
    )
    sleeps = []
    monkeypatch.setattr(
        RRC,
        "run_in_runner_scope",
        lambda *_args, **_kwargs: next(responses),
    )

    assert RRC.control_geo(
        proxy_url="http://127.0.0.1:1234",
        runner_scope="local",
        host="unused",
        sleep_fn=sleeps.append,
    ) == ("8.8.8.8", "US")
    assert sleeps == [1]


def test_discard_proxy_request_is_best_effort(monkeypatch) -> None:
    monkeypatch.setattr(
        RRC,
        "run_in_runner_scope",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RRC.subprocess.TimeoutExpired("curl", 8)
        ),
    )

    assert (
        RRC.discard_proxy_request(
            proxy_url="http://127.0.0.1:1234",
            runner_scope="local",
            host="unused",
        )
        is False
    )


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
        control_exit_hmac="",
        regioncheck_exit_hmac="",
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


def test_failed_tool_without_provider_records_node_error_not_service_results() -> None:
    assert RRC.is_unattributable_tool_failure(1, None) is True
    assert RRC.is_unattributable_tool_failure(0, None) is False
    assert RRC.is_unattributable_tool_failure(1, "203.0.*.*") is False

    report = {"results": [], "node_errors": []}
    manifest = {
        "source_snapshot_id": "snapshot_test",
        "source_hash": "a" * 64,
    }
    tool = {
        "tool_version": "1.0.1",
        "script_sha256": "b" * 64,
    }
    RRC.append_node_error(
        report,
        manifest=manifest,
        identities={"node-a": "node_abc"},
        node_name="node-a",
        tool=tool,
    )

    assert report["results"] == []
    assert report["node_errors"] == [
        {
            "exact_node_id": "node_abc",
            "exact_node_name": "node-a",
            "source_snapshot_id": "snapshot_test",
            "source_hash": "a" * 64,
            "tool_version": "1.0.1",
            "tool_sha256": "b" * 64,
            "tested_at": report["node_errors"][0]["tested_at"],
            "probe_method_version": RRC.METHOD_VERSION,
            "error": "RRC_EXECUTION_FAILED_NO_ATTRIBUTABLE_RESULTS",
            "evidence_type": "UNKNOWN",
        }
    ]


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

    def fake_run(_host, _timeout, *, proxy_url, runner_scope):
        assert proxy_url == "http://127.0.0.1:17890"
        assert runner_scope == "remote"
        calls.append("run")
        return next(responses)

    monkeypatch.setattr(RRC, "run_regioncheck", fake_run)
    code, _output, values = RRC.run_regioncheck_with_transport_retry(
        "router",
        30,
        proxy_url="http://127.0.0.1:17890",
        runner_scope="remote",
        sleep_fn=lambda _seconds: calls.append("sleep"),
    )

    assert code == 0
    assert calls == ["run", "sleep", "run"]
    assert values == {
        "gpt": "Yes",
        "gemini": "No",
        "disney": "Yes (Region: JP)",
    }


def test_sidecar_proxy_context_resolves_endpoint_once_for_runner_scope() -> None:
    local = RRC.resolve_sidecar_proxy_context(
        runner_scope="local",
        local_proxy_host="127.0.0.1",
        local_proxy_port=57012,
        remote_proxy_host="127.0.0.1",
        remote_proxy_port=17890,
        controller_url="http://127.0.0.1:57013",
    )
    remote = RRC.resolve_sidecar_proxy_context(
        runner_scope="remote",
        local_proxy_host="127.0.0.1",
        local_proxy_port=57012,
        remote_proxy_host="127.0.0.1",
        remote_proxy_port=17890,
        controller_url="http://127.0.0.1:57013",
    )

    assert local.resolved_proxy_url == "http://127.0.0.1:57012"
    assert remote.resolved_proxy_url == "http://127.0.0.1:17890"


def test_remote_control_and_regioncheck_receive_same_resolved_proxy_url(
    monkeypatch,
) -> None:
    observed: list[list[str]] = []

    class Completed:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str):
            self.stdout = stdout

    def fake_run(command, **_kwargs):
        observed.append(command)
        if RRC.DEFAULT_COMMAND_PATH in command[-1]:
            return Completed(
                "ChatGPT: Yes\nGoogle Gemini: No\nDisney+: Yes (Region: JP)\n"
            )
        return Completed('{"ip":"8.8.8.8","country":"US"}')

    monkeypatch.setattr(RRC.subprocess, "run", fake_run)
    proxy_url = "http://127.0.0.1:17890"

    assert RRC.control_geo(
        proxy_url=proxy_url,
        runner_scope="remote",
        host="router",
        sleep_fn=lambda _seconds: None,
    ) == ("8.8.8.8", "US")
    code, _ = RRC.run_regioncheck(
        "router",
        30,
        proxy_url=proxy_url,
        runner_scope="remote",
    )

    assert code == 0
    assert len(observed) == 2
    assert all(proxy_url in command[-1] for command in observed)


class FakeSkill:
    def __init__(self) -> None:
        self.selected = ""
        self.selections: list[str] = []
        self.connection_resets = 0

    def select_probe_node(self, _controller_port: int, name: str) -> bool:
        self.selected = name
        self.selections.append(name)
        return True

    def controller_json_request(
        self,
        _controller_port: int,
        path: str,
        *,
        method: str = "GET",
    ) -> dict:
        if path == "/connections" and method == "DELETE":
            self.connection_resets += 1
            return {}
        return {"now": self.selected}


def proxy_context() -> RRC.SidecarProxyContext:
    return RRC.resolve_sidecar_proxy_context(
        runner_scope="remote",
        local_proxy_host="127.0.0.1",
        local_proxy_port=57012,
        remote_proxy_host="127.0.0.1",
        remote_proxy_port=17890,
        controller_url="http://127.0.0.1:57013",
    )


def successful_regioncheck(*_args, **_kwargs):
    return (
        0,
        (
            "ChatGPT: Yes\nGoogle Gemini: No\n"
            "Disney+: Yes (Region: JP)\n"
            "** Your Network Provider: ISP (203.0.*.*)\n"
        ),
        {"gpt": "Yes", "gemini": "No", "disney": "Yes (Region: JP)"},
    )


def test_matching_control_and_regioncheck_hmac_accepts_node(monkeypatch) -> None:
    skill = FakeSkill()
    monkeypatch.setattr(RRC, "discard_proxy_request", lambda **_kwargs: True)
    exits = iter([("203.0.113.8", "JP")] * 3)
    monkeypatch.setattr(RRC, "control_geo", lambda **_kwargs: next(exits))
    monkeypatch.setattr(
        RRC,
        "run_regioncheck_with_transport_retry",
        successful_regioncheck,
    )

    outcome = RRC.probe_node_with_attribution(
        skill=skill,
        host="router",
        controller_port=57013,
        proxy_context=proxy_context(),
        node_name="node-a",
        timeout_seconds=217,
        run_key=b"k" * 32,
        stabilization_seconds=0,
        sleep_fn=lambda _seconds: None,
    )

    assert outcome["status"] == "ATTRIBUTION_MATCH"
    assert outcome["control_exit_ip_hmac"] == outcome["regioncheck_exit_ip_hmac"]
    assert outcome["selector_readback"] == "node-a"
    assert skill.connection_resets >= 2


def test_stale_exit_pollution_retries_once_then_accepts_fresh_exit(
    monkeypatch,
) -> None:
    skill = FakeSkill()
    monkeypatch.setattr(RRC, "discard_proxy_request", lambda **_kwargs: True)
    exits = iter(
        [
            ("203.0.113.8", "JP"),
            ("198.51.100.2", "US"),
            ("203.0.113.8", "JP"),
            ("203.0.113.8", "JP"),
        ]
    )
    monkeypatch.setattr(RRC, "control_geo", lambda **_kwargs: next(exits))
    monkeypatch.setattr(
        RRC,
        "run_regioncheck_with_transport_retry",
        successful_regioncheck,
    )

    outcome = RRC.probe_node_with_attribution(
        skill=skill,
        host="router",
        controller_port=57013,
        proxy_context=proxy_context(),
        node_name="node-a",
        timeout_seconds=217,
        run_key=b"k" * 32,
        stabilization_seconds=0,
        sleep_fn=lambda _seconds: None,
    )

    assert outcome["status"] == "ATTRIBUTION_MATCH"
    assert outcome["attribution_attempts"] == 2


def test_repeated_exit_mismatch_is_rejected(monkeypatch) -> None:
    skill = FakeSkill()
    monkeypatch.setattr(RRC, "discard_proxy_request", lambda **_kwargs: True)
    exits = iter(
        [
            ("203.0.113.8", "JP"),
            ("198.51.100.2", "US"),
        ]
        * 2
    )
    monkeypatch.setattr(RRC, "control_geo", lambda **_kwargs: next(exits))
    monkeypatch.setattr(
        RRC,
        "run_regioncheck_with_transport_retry",
        successful_regioncheck,
    )

    outcome = RRC.probe_node_with_attribution(
        skill=skill,
        host="router",
        controller_port=57013,
        proxy_context=proxy_context(),
        node_name="node-a",
        timeout_seconds=217,
        run_key=b"k" * 32,
        stabilization_seconds=0,
        sleep_fn=lambda _seconds: None,
    )

    assert outcome["status"] == "ATTRIBUTION_MISMATCH"
    assert outcome["attribution_valid"] is False
    assert outcome["attribution_attempts"] == 2


def test_selector_switch_produces_a_different_attributed_exit(monkeypatch) -> None:
    skill = FakeSkill()
    monkeypatch.setattr(RRC, "discard_proxy_request", lambda **_kwargs: True)
    exits = iter(
        [("203.0.113.8", "TW")] * 2
        + [("203.0.113.9", "US")] * 2
    )
    monkeypatch.setattr(RRC, "control_geo", lambda **_kwargs: next(exits))
    monkeypatch.setattr(
        RRC,
        "run_regioncheck_with_transport_retry",
        successful_regioncheck,
    )
    outcomes = [
        RRC.probe_node_with_attribution(
            skill=skill,
            host="router",
            controller_port=57013,
            proxy_context=proxy_context(),
            node_name=name,
            timeout_seconds=217,
            run_key=b"k" * 32,
            stabilization_seconds=0,
            sleep_fn=lambda _seconds: None,
        )
        for name in ("node-tw", "node-us")
    ]

    assert skill.selections == ["node-tw", "node-us"]
    assert all(item["status"] == "ATTRIBUTION_MATCH" for item in outcomes)
    assert (
        outcomes[0]["control_exit_ip_hmac"]
        != outcomes[1]["control_exit_ip_hmac"]
    )


def test_two_node_calibration_requires_distinct_attributed_exits() -> None:
    report = {
        "node_attempts": [
            {
                "status": "ATTRIBUTION_MATCH",
                "selector_readback": "node-a",
                "exact_node_name": "node-a",
                "control_exit_ip_hmac": "a" * 20,
                "result_count": 3,
            },
            {
                "status": "ATTRIBUTION_MATCH",
                "selector_readback": "node-b",
                "exact_node_name": "node-b",
                "control_exit_ip_hmac": "b" * 20,
                "result_count": 3,
            },
        ]
    }
    RRC.validate_two_node_calibration(report)
    assert (
        report["calibration_status"]
        == "PASS_RRC_PROXY_ATTRIBUTION_TWO_NODE_CALIBRATION"
    )

    report["node_attempts"][1]["control_exit_ip_hmac"] = "a" * 20
    with pytest.raises(RRC.ProbeError, match="TWO_NODE_CALIBRATION_FAILED"):
        RRC.validate_two_node_calibration(report)


def test_only_complete_attribution_records_are_reusable() -> None:
    manifest = {"source_snapshot_id": "snapshot_test", "source_hash": "a" * 64}
    tool = {
        "tool_version": RRC.EXPECTED_TOOL_VERSION,
        "script_sha256": "b" * 64,
    }
    previous = {
        "schema_version": RRC.SCHEMA_VERSION,
        "probe_method_version": RRC.METHOD_VERSION,
        **manifest,
        "tool": tool,
        "results": [
            {"exact_node_id": "node-1", "service": service}
            for service in RRC.SERVICE_LABELS
        ],
        "node_attempts": [
            {
                "exact_node_id": "node-1",
                "exact_node_name": "one",
                "selector_readback": "one",
                "status": "ATTRIBUTION_MATCH",
                "attribution_valid": True,
                "output_complete": True,
                "control_exit_ip_hmac": "c" * 20,
                "regioncheck_exit_ip_hmac": "c" * 20,
            },
            {
                "exact_node_id": "node-2",
                "exact_node_name": "two",
                "selector_readback": "two",
                "status": "ATTRIBUTION_MATCH",
                "attribution_valid": True,
                "output_complete": False,
                "control_exit_ip_hmac": "d" * 20,
                "regioncheck_exit_ip_hmac": "d" * 20,
            },
        ],
    }

    assert RRC.reusable_node_ids(previous, manifest=manifest, tool=tool) == {
        "node-1"
    }
    previous["schema_version"] = 1
    assert RRC.reusable_node_ids(previous, manifest=manifest, tool=tool) == set()


def test_legacy_attribution_valid_record_is_not_reusable() -> None:
    manifest = {"source_snapshot_id": "snapshot_test", "source_hash": "a" * 64}
    tool = {"tool_version": RRC.EXPECTED_TOOL_VERSION, "script_sha256": "b" * 64}
    previous = {
        "schema_version": RRC.SCHEMA_VERSION,
        "probe_method_version": RRC.METHOD_VERSION,
        **manifest,
        "tool": tool,
        "results": [
            {"exact_node_id": "node-1", "service": service}
            for service in RRC.SERVICE_LABELS
        ],
        "node_attempts": [
            {
                "exact_node_id": "node-1",
                "exact_node_name": "one",
                "selector_readback": "one",
                "status": "ATTRIBUTION_VALID",
                "attribution_valid": True,
                "output_complete": True,
                "control_exit_ip_hmac": "c" * 20,
                "regioncheck_exit_ip_hmac": "c" * 20,
            }
        ],
    }
    assert RRC.reusable_node_ids(previous, manifest=manifest, tool=tool) == set()


def test_new_run_id_is_distinct_and_resume_preserves_checkpoint_run_id() -> None:
    first = RRC.resolve_run_id(resume=False)
    second = RRC.resolve_run_id(resume=False, previous={"run_id": first})
    resumed = RRC.resolve_run_id(resume=True, previous={"run_id": first})

    assert first != second
    assert resumed == first
    assert len(first) == 32


def test_node_local_attribution_unavailable_has_no_service_evidence(
    monkeypatch,
) -> None:
    skill = FakeSkill()
    monkeypatch.setattr(RRC, "discard_proxy_request", lambda **_kwargs: False)
    monkeypatch.setattr(
        RRC,
        "control_geo",
        lambda **_kwargs: (_ for _ in ()).throw(
            RRC.ControlAttributionUnavailable("CONTROL_ATTRIBUTION_UNAVAILABLE")
        ),
    )

    outcome = RRC.probe_node_with_attribution(
        skill=skill,
        host="router",
        controller_port=57013,
        proxy_context=proxy_context(),
        node_name="node-a",
        timeout_seconds=217,
        run_key=b"k" * 32,
        stabilization_seconds=0,
        sleep_fn=lambda _seconds: None,
    )

    assert outcome["status"] == "ATTRIBUTION_UNAVAILABLE"
    assert outcome["raw_values"] == {}
    assert outcome["attribution_valid"] is False


def _attempt(status: str, node_id: str) -> dict:
    return {"status": status, "exact_node_id": node_id}


def test_isolated_unavailable_does_not_stop_run() -> None:
    attempts = [
        _attempt("ATTRIBUTION_MATCH", "a"),
        _attempt("ATTRIBUTION_UNAVAILABLE", "b"),
        _attempt("ATTRIBUTION_MATCH", "c"),
        _attempt("ATTRIBUTION_MATCH", "d"),
        _attempt("ATTRIBUTION_MATCH", "e"),
        _attempt("ATTRIBUTION_MATCH", "f"),
        _attempt("ATTRIBUTION_MATCH", "g"),
        _attempt("ATTRIBUTION_MATCH", "h"),
    ]
    assert RRC.systemic_attribution_stop_reason(attempts) is None


def test_three_consecutive_unavailable_nodes_stop_run() -> None:
    attempts = [
        _attempt("ATTRIBUTION_MATCH", "a"),
        _attempt("ATTRIBUTION_UNAVAILABLE", "b"),
        _attempt("ATTRIBUTION_UNAVAILABLE", "c"),
        _attempt("ATTRIBUTION_UNAVAILABLE", "d"),
    ]
    assert (
        RRC.systemic_attribution_stop_reason(attempts)
        == "STOP_RRC_CONTROL_ATTRIBUTION_SYSTEMIC_UNAVAILABLE"
    )


def test_unavailable_ratio_over_25_percent_after_eight_nodes_stops_run() -> None:
    attempts = [
        _attempt("ATTRIBUTION_UNAVAILABLE", "a"),
        _attempt("ATTRIBUTION_MATCH", "b"),
        _attempt("ATTRIBUTION_MATCH", "c"),
        _attempt("ATTRIBUTION_UNAVAILABLE", "d"),
        _attempt("ATTRIBUTION_MATCH", "e"),
        _attempt("ATTRIBUTION_MATCH", "f"),
        _attempt("ATTRIBUTION_UNAVAILABLE", "g"),
        _attempt("ATTRIBUTION_MATCH", "h"),
    ]
    assert (
        RRC.systemic_attribution_stop_reason(attempts)
        == "STOP_RRC_CONTROL_ATTRIBUTION_SYSTEMIC_UNAVAILABLE"
    )


def test_unavailable_ratio_equal_to_25_percent_does_not_stop_run() -> None:
    attempts = [
        _attempt("ATTRIBUTION_UNAVAILABLE", "a"),
        _attempt("ATTRIBUTION_MATCH", "b"),
        _attempt("ATTRIBUTION_MATCH", "c"),
        _attempt("ATTRIBUTION_MATCH", "d"),
        _attempt("ATTRIBUTION_UNAVAILABLE", "e"),
        _attempt("ATTRIBUTION_MATCH", "f"),
        _attempt("ATTRIBUTION_MATCH", "g"),
        _attempt("ATTRIBUTION_MATCH", "h"),
    ]
    assert RRC.systemic_attribution_stop_reason(attempts) is None


def test_systemic_gate_confirmation_accepts_healthy_calibration_sentinel(
    monkeypatch,
) -> None:
    outcomes = iter(
        [
            {"status": "ATTRIBUTION_UNAVAILABLE", "raw_values": {}},
            {
                "status": "ATTRIBUTION_MATCH",
                "raw_values": {"gpt": "Yes"},
                "control_exit_ip_hmac": "a" * 20,
                "regioncheck_exit_ip_hmac": "a" * 20,
            },
        ]
    )
    monkeypatch.setattr(
        RRC,
        "probe_node_with_attribution",
        lambda **_kwargs: next(outcomes),
    )

    healthy, confirmations = RRC.confirm_systemic_attribution_health(
        skill=FakeSkill(),
        host="router",
        controller_port=57013,
        proxy_context=proxy_context(),
        sentinel_names=["node-tw", "node-us"],
        timeout_seconds=217,
        run_key=b"k" * 32,
        stabilization_seconds=0,
        sleep_fn=lambda _seconds: None,
    )

    assert healthy is True
    assert [item["status"] for item in confirmations] == [
        "ATTRIBUTION_UNAVAILABLE",
        "ATTRIBUTION_MATCH",
    ]
    assert all("raw_values" not in item for item in confirmations)


def test_systemic_gate_confirmation_rejects_unavailable_sentinels(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        RRC,
        "probe_node_with_attribution",
        lambda **_kwargs: {
            "status": "ATTRIBUTION_UNAVAILABLE",
            "raw_values": {},
        },
    )

    healthy, confirmations = RRC.confirm_systemic_attribution_health(
        skill=FakeSkill(),
        host="router",
        controller_port=57013,
        proxy_context=proxy_context(),
        sentinel_names=["node-tw", "node-us"],
        timeout_seconds=217,
        run_key=b"k" * 32,
        stabilization_seconds=0,
        sleep_fn=lambda _seconds: None,
    )

    assert healthy is False
    assert len(confirmations) == 2


def test_systemic_gate_confirmation_preserves_mismatch_fail_closed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        RRC,
        "probe_node_with_attribution",
        lambda **_kwargs: {
            "status": "ATTRIBUTION_MISMATCH",
            "raw_values": {},
        },
    )

    with pytest.raises(RRC.ProbeError, match="STOP_RRC_PROXY_ATTRIBUTION_MISMATCH"):
        RRC.confirm_systemic_attribution_health(
            skill=FakeSkill(),
            host="router",
            controller_port=57013,
            proxy_context=proxy_context(),
            sentinel_names=["node-tw"],
            timeout_seconds=217,
            run_key=b"k" * 32,
            stabilization_seconds=0,
            sleep_fn=lambda _seconds: None,
        )


def test_regioncheck_timeout_is_per_node_and_no_global_port_fallback(
    monkeypatch,
) -> None:
    observed = {}

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(command, *, runner_scope, host, timeout_seconds):
        observed.update(
            command=command,
            runner_scope=runner_scope,
            host=host,
            timeout_seconds=timeout_seconds,
        )
        return Completed()

    monkeypatch.setattr(RRC, "run_in_runner_scope", fake_runner)
    RRC.run_regioncheck(
        "router",
        217,
        proxy_url="http://127.0.0.1:19001",
        runner_scope="remote",
    )

    assert observed["timeout_seconds"] == 217
    assert "http://127.0.0.1:19001" in observed["command"]
    assert "REMOTE_SIDECAR_MIXED_PORT" not in inspect.getsource(
        RRC.run_regioncheck
    )
    assert "REMOTE_SIDECAR_MIXED_PORT" not in inspect.getsource(RRC.control_geo)


def test_production_fingerprint_must_remain_exact() -> None:
    RRC.require_preserved_production_fingerprint("same", "same")
    with pytest.raises(RRC.ProbeError, match="PRODUCTION_STATE_CHANGED"):
        RRC.require_preserved_production_fingerprint("before", "after")
