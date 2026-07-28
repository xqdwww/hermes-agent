from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import stat
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "skills" / "clashverge-openclash-static" / "scripts" / "clashverge_to_openclash.py"
SPEC = importlib.util.spec_from_file_location("clashverge_to_openclash", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def proxy(name: str) -> dict[str, object]:
    return {
        "name": name,
        "type": "anytls",
        "server": "example.invalid",
        "port": 443,
        "password": "secret",
    }


def test_accepted_simple_profile() -> None:
    source = {
        "proxies": [
            proxy("🇨🇳台湾-住宅"),
            proxy("🇺🇸美国-住宅"),
            proxy("🇭🇰香港aws高速01"),
            proxy("🇸🇬新加坡aws高速01"),
            proxy("🇸🇬新加坡aws高速02"),
            proxy("🇯🇵日本aws高速01"),
            proxy("🇯🇵日本aws高速02"),
            proxy("🇨🇳香港原生htk高速01"),
            proxy("🇨🇳香港原生htk高速02"),
            proxy("🇨🇳香港hkb家宽01"),
            proxy("🇰🇷韩国aws01"),
            proxy("🇯🇵日本-流媒体02"),
            proxy("🇰🇷韩国-流媒体01"),
            proxy("新加坡-媒体流01"),
            proxy("🇨🇳香港原生hkt01-hy2"),
            proxy("🇺🇸美国住宅-hy2"),
            proxy("🇺🇸美国迈阿密-hy2"),
            proxy("🇺🇸美国拉斯维加斯-hy2"),
            proxy("使用前先更新订阅"),
        ],
        "proxy-groups": [{"name": "旧组", "type": "select", "proxies": ["DIRECT"]}],
        "rules": ["DOMAIN-SUFFIX,example.com,顺畅网络", "MATCH,顺畅网络"],
        "external-controller-unix": "/tmp/verge/verge-mihomo.sock",
        "tun": {"enable": True},
    }

    result = MODULE.transform(source)
    groups = {group["name"]: group for group in result["proxy-groups"]}

    assert list(groups) == list(MODULE.MANAGED_GROUP_NAMES)
    assert len(MODULE.GPT_CANDIDATES) == 11
    assert len(groups) == 12
    assert all("优先│" not in name and "优先｜" not in name for name in groups)
    assert groups["GPT候选"]["type"] == "fallback"
    assert "🇯🇵日本aws高速02" in groups["GPT候选"]["proxies"]
    assert groups["GPT手动"]["proxies"] == ["GPT候选", *groups["GPT候选"]["proxies"]]
    assert groups["Gemini手动"]["proxies"] == ["Gemini候选", *groups["Gemini候选"]["proxies"]]
    assert groups["迪士尼手动"]["proxies"] == ["迪士尼候选", *groups["迪士尼候选"]["proxies"]]
    assert result["rules"][-1] == "MATCH,默认代理"
    assert sum(rule.startswith("MATCH,") for rule in result["rules"]) == 1
    assert "external-controller-unix" not in result
    assert result["tun"] == {"enable": True}
    assert "使用前先更新订阅" not in {item["name"] for item in result["proxies"]}
    MODULE.validate_config(result)


def test_audit_redacts_nested_credentials() -> None:
    data = {
        "proxy-providers": {
            "nested": {
                "url": "https://user:token@provider.example/subscription",
                "server": "provider.example",
                "token": "provider-token",
                "headers": {
                    "Authorization": "Bearer real-token",
                    "Proxy-Authorization": "Basic real-token",
                },
            }
        },
        "controller": {"secret": "controller-secret"},
        "metadata": {
            "uuid": "metadata-uuid",
            "private-key": "private",
            "public-key": "public",
            "short-id": "short",
            "servername": "server-name",
            "sni": "sni-name",
        },
        "proxy-groups": [
            {
                "name": "自动选择",
                "type": "fallback",
                "proxies": ["node-b", "node-a"],
                "url": "https://www.gstatic.com/generate_204",
            }
        ],
        "rules": ["DOMAIN-SUFFIX,example.com,自动选择", "MATCH,默认代理"],
        "proxies": [
            {
                "name": "node",
                "server": "host.example",
                "port": 443,
                "uuid": "real-uuid",
                "reality-opts": {"public-key": "real-key", "short-id": "real-id"},
            }
        ]
    }
    original = deepcopy(data)
    audit = MODULE.make_audit_copy(data)
    item = audit["proxies"][0]
    assert item["server"] == "REDACTED"
    assert item["port"] == 0
    assert item["uuid"] == "00000000-0000-0000-0000-000000000000"
    assert item["reality-opts"]["public-key"] == "REDACTED"
    assert item["reality-opts"]["short-id"] == "REDACTED"
    assert audit["proxy-providers"]["nested"]["server"] == "REDACTED"
    assert audit["proxy-providers"]["nested"]["url"] == "REDACTED"
    assert audit["proxy-providers"]["nested"]["token"] == "REDACTED"
    assert audit["proxy-providers"]["nested"]["headers"]["Authorization"] == "REDACTED"
    assert audit["proxy-providers"]["nested"]["headers"]["Proxy-Authorization"] == "REDACTED"
    assert audit["controller"]["secret"] == "REDACTED"
    assert audit["metadata"]["uuid"] == "00000000-0000-0000-0000-000000000000"
    assert all(
        audit["metadata"][key] == "REDACTED"
        for key in ("private-key", "public-key", "short-id", "servername", "sni")
    )
    assert audit["proxy-groups"] == original["proxy-groups"]
    assert audit["rules"] == original["rules"]
    assert data == original


def test_match_must_be_unique_and_strictly_last() -> None:
    source = {
        "proxies": [proxy(name) for name in MODULE.GEMINI_CANDIDATES],
        "rules": [
            "MATCH,旧组",
            "DOMAIN-SUFFIX,example.com,顺畅网络",
            "MATCH,另一个旧组",
        ],
    }
    result = MODULE.transform(source)
    assert result["rules"][-1] == "MATCH,默认代理"
    assert sum(rule.startswith("MATCH,") for rule in result["rules"]) == 1
    result["rules"].append("DOMAIN-SUFFIX,example.com,默认代理")
    with pytest.raises(MODULE.ConfigError, match="final MATCH"):
        MODULE.validate_config(result)


def test_transform_removes_verge_runtime_without_touching_proxy_ports() -> None:
    source = {
        "proxies": [proxy(name) for name in MODULE.GEMINI_CANDIDATES],
        "rules": [],
        "external-controller": "127.0.0.1:9090",
        "external-controller-unix": "/tmp/verge/verge.sock",
        "external-controller-cors": {"allow-origins": ["*"]},
        "mixed-port": 7890,
        "profile": {"store-selected": True},
        "probe-controller": "127.0.0.1:19090",
        "controller-port": 19091,
        "tun": {"enable": True, "stack": "system"},
        "runtime": {
            "socket": "/tmp/verge/probe.sock",
            "keep": "persistent",
        },
    }
    result = MODULE.transform(source)
    assert not (set(source) & MODULE.CLASH_VERGE_TOP_LEVEL_RUNTIME_KEYS & set(result))
    assert "probe-controller" not in result
    assert "controller-port" not in result
    assert result["runtime"] == {"keep": "persistent"}
    assert result["tun"] == {"enable": True, "stack": "system"}
    assert all(item["port"] == 443 for item in result["proxies"])


def test_deploy_retries_health_then_rolls_back_and_verifies(tmp_path, monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        MODULE.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    candidate = MODULE.UploadedCandidate(
        "/etc/openclash/config/.clashverge-candidates/new.candidate",
        "/etc/openclash/config/new.yaml",
    )

    events: list[str] = []
    health_calls = 0

    def fake_ssh(host: str, command: str, *, capture: bool = False):
        nonlocal health_calls
        events.append(command)
        if "OPENCLASH_STATE_READ=1" in command:
            return subprocess.CompletedProcess(
                [],
                0,
                stdout=(
                    "active_path=/etc/openclash/config/original.yaml\n"
                    "active_exists=1\n"
                    "enabled=1\n"
                    "running=1\n"
                    "core_running=1\n"
                    "network_artifacts=1\n"
                    "tun_present=0\n"
                ),
                stderr="",
            )
        if "OPENCLASH_HEALTH_CHECK=1" in command:
            if "original.yaml" not in command:
                health_calls += 1
                raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess([], 0)

    def fake_run(cmd, *args, **kwargs):
        events.append("LAN_HEALTH" if cmd[0] == "curl" else "LOCAL_COMMAND")
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(MODULE, "run", fake_run)
    monkeypatch.setattr(MODULE, "ssh_command", fake_ssh)
    with pytest.raises(MODULE.ConfigError, match="HEALTH_CHECK_FAILED_ROLLED_BACK"):
        MODULE.activate_uploaded_candidate(
            candidate,
            host="router.invalid",
            core_path="/etc/openclash/core/clash_meta",
        )

    assert health_calls == MODULE.REMOTE_HEALTH_DEADLINE_SECONDS
    health_commands = [command for command in events if "OPENCLASH_HEALTH_CHECK=1" in command]
    assert all(
        "/etc/init.d/openclash running" in command
        and '-f "$active_path"' in command
        and "for option in mixed_port http_port" in command
        and 'http://127.0.0.1:${proxy_port}' in command
        and "ss -lnt" in command
        and "netstat -lnt" in command
        and "curl --proxy" in command
        and "curl --config -" in command
        and "--connect-timeout 3" in command
        and "--max-time 8" in command
        and "https://www.gstatic.com/generate_204" in command
        and '"$http_code" = \'204\'' in command
        for command in health_commands
    )
    state_index = next(i for i, event in enumerate(events) if "OPENCLASH_STATE_READ=1" in event)
    backup_index = next(i for i, event in enumerate(events) if "OPENCLASH_BACKUP=1" in event)
    activation_index = next(
        i for i, event in enumerate(events) if "OPENCLASH_ACTIVATION_INSTALL=1" in event
    )
    assert state_index < backup_index < activation_index
    activation_start = next(
        event for event in events if "OPENCLASH_ACTIVATION_START=1" in event
    )
    assert "/etc/init.d/openclash restart || true" in activation_start
    assert (
        "if ! /etc/init.d/openclash running >/dev/null 2>&1; then "
        "/etc/init.d/openclash start || true; fi"
    ) in activation_start
    assert any("original.yaml" in command and "active-yaml" in command for command in events)
    assert any(
        "cp -p /etc/config/openclash" in command
        and "cp -p /etc/config/dhcp" in command
        and "cp -p /etc/config/firewall" in command
        and "service-state" in command
        for command in events
    )
    stop_index = next(i for i, event in enumerate(events) if "OPENCLASH_ROLLBACK_STOP=1" in event)
    openclash_restore_index = next(
        i
        for i, event in enumerate(events)
        if event.startswith("cp -p /etc/config/openclash.bak")
    )
    assert stop_index < openclash_restore_index
    assert any("dhcp-uci" in command and "/etc/config/dhcp" in command for command in events)
    assert any("firewall-uci" in command and "/etc/config/firewall" in command for command in events)
    assert any(command == "/etc/init.d/firewall reload" for command in events)
    assert any(command == "/etc/init.d/dnsmasq restart" for command in events)
    assert any(command == "/etc/init.d/openclash start" for command in events)
    assert "LAN_HEALTH" in events
    assert any(
        "OPENCLASH_ROLLBACK_VERIFY=1" in command
        and "original.yaml" in command
        and "openclash enabled" in command
        for command in events
    )


def test_rollback_failure_has_explicit_status(tmp_path, monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(MODULE, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0))
    candidate = MODULE.UploadedCandidate(
        "/etc/openclash/config/.clashverge-candidates/new.candidate",
        "/etc/openclash/config/new.yaml",
    )

    def fake_ssh(host: str, command: str, *, capture: bool = False):
        if "OPENCLASH_STATE_READ=1" in command:
            return subprocess.CompletedProcess(
                [],
                0,
                stdout=(
                    "active_path=/etc/openclash/config/original.yaml\n"
                    "active_exists=1\n"
                    "enabled=1\n"
                    "running=1\n"
                    "core_running=1\n"
                    "network_artifacts=1\n"
                    "tun_present=0\n"
                ),
                stderr="",
            )
        if "OPENCLASH_HEALTH_CHECK=1" in command:
            raise subprocess.CalledProcessError(1, command)
        if command.startswith("cp -p /tmp/") and "dhcp-uci" in command:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(MODULE, "ssh_command", fake_ssh)
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        MODULE.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    with pytest.raises(MODULE.ConfigError, match="ROLLBACK_FAILED"):
        MODULE.activate_uploaded_candidate(
            candidate,
            host="router.invalid",
            core_path="/etc/openclash/core/clash_meta",
        )


def test_failed_restart_restores_previously_stopped_direct_lan_state(
    tmp_path, monkeypatch
) -> None:
    """Simulate the observed procd delete error after OpenClash changed the dataplane."""
    monkeypatch.setattr(MODULE.time, "sleep", lambda seconds: None)
    candidate = MODULE.UploadedCandidate(
        "/etc/openclash/config/.clashverge-candidates/new.candidate",
        "/etc/openclash/config/new.yaml",
    )

    events: list[str] = []

    def fake_run(cmd, *args, **kwargs):
        events.append("LAYER3_LAN_EGRESS" if cmd[0] == "curl" else "LOCAL_COMMAND")
        return subprocess.CompletedProcess([], 0)

    def fake_ssh(host: str, command: str, *, capture: bool = False):
        events.append(command)
        if "OPENCLASH_STATE_READ=1" in command:
            return subprocess.CompletedProcess(
                [],
                0,
                stdout=(
                    "active_path=/etc/openclash/config/original.yaml\n"
                    "active_exists=1\n"
                    "enabled=1\n"
                    "running=0\n"
                    "core_running=0\n"
                    "network_artifacts=0\n"
                    "tun_present=0\n"
                ),
                stderr="",
            )
        if "OPENCLASH_ACTIVATION_START=1" in command:
            raise subprocess.CalledProcessError(
                1,
                command,
                stderr='ubus call service delete { "name": "openclash" } (Not found)',
            )
        if "OPENCLASH_ROLLBACK_STOP=1" in command:
            raise subprocess.CalledProcessError(
                1,
                command,
                stderr='ubus call service delete { "name": "openclash" } (Not found)',
            )
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(MODULE, "run", fake_run)
    monkeypatch.setattr(MODULE, "ssh_command", fake_ssh)

    with pytest.raises(MODULE.ConfigError, match="HEALTH_CHECK_FAILED_ROLLED_BACK"):
        MODULE.activate_uploaded_candidate(
            candidate,
            host="router.invalid",
            core_path="/etc/openclash/core/clash_meta",
        )

    failed_stop = next(i for i, event in enumerate(events) if "OPENCLASH_ROLLBACK_STOP=1" in event)
    dhcp_restore = next(
        i for i, event in enumerate(events) if event.startswith("cp -p /tmp/") and "dhcp-uci" in event
    )
    firewall_restore = next(
        i
        for i, event in enumerate(events)
        if event.startswith("cp -p /tmp/") and "firewall-uci" in event
    )
    stopped_health = next(
        i for i, event in enumerate(events) if "OPENCLASH_ROLLBACK_HEALTH=1" in event
    )
    assert failed_stop < dhcp_restore < stopped_health
    assert failed_stop < firewall_restore < stopped_health
    assert "/etc/init.d/firewall reload" in events
    assert "/etc/init.d/dnsmasq restart" in events
    assert any(
        "ip -4 rule del fwmark 0x162 table 354" in event
        and "ip -4 route flush table 354" in event
        and "ip link delete utun" in event
        for event in events
    )
    assert "/etc/init.d/openclash stop" in events
    assert "LAYER3_LAN_EGRESS" in events
    assert all("/etc/init.d/openclash restart" not in event for event in events[failed_stop + 1 :])


def test_node_probe_failure_never_contacts_router(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.yaml"
    source.write_text("proxies: []\n", encoding="utf-8")
    router_calls: list[str] = []

    monkeypatch.setattr(
        MODULE,
        "prepare_source_snapshot",
        lambda **_kwargs: (
            {"source_snapshot_id": "snapshot-test", "source_hash": "a" * 64},
            source,
            {"manifest_path": str(tmp_path / "snapshot.json")},
        ),
    )
    monkeypatch.setattr(MODULE, "load_yaml", lambda _path: {})

    def failed_probe(*_args, **_kwargs):
        raise MODULE.ConfigError("SIMULATED_NODE_PROBE_FAILURE")

    monkeypatch.setattr(MODULE, "dynamic_probe_and_select", failed_probe)
    monkeypatch.setattr(
        MODULE,
        "ssh_command",
        lambda *_args, **_kwargs: router_calls.append("ssh"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "clashverge_to_openclash.py",
            "all",
            "--source",
            str(source),
            "--workdir",
            str(tmp_path),
            "--deploy",
            "--activate",
        ],
    )

    assert MODULE.main() == 1
    assert router_calls == []


def test_upload_succeeds_without_state_read_then_activation_blocks(tmp_path, monkeypatch) -> None:
    local_file = tmp_path / "openclash.yaml"
    local_file.write_text("proxies: []\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "load_yaml", lambda path: {})
    monkeypatch.setattr(MODULE, "validate_config", lambda data: None)
    uploads: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        uploads.append(cmd)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(MODULE, "run", fake_run)

    def failed_state_read(host: str, command: str, *, capture: bool = False):
        if "OPENCLASH_STATE_READ=1" in command:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(MODULE, "ssh_command", failed_state_read)
    candidate = MODULE.upload_candidate(
        local_file,
        host="router.invalid",
        remote_name=None,
        core_path="/etc/openclash/core/clash_meta",
    )
    assert len(uploads) == 1
    with pytest.raises(MODULE.ConfigError, match="REMOTE_ACTIVE_CONFIG_PATH_READ_FAILED"):
        MODULE.activate_uploaded_candidate(
            candidate,
            host="router.invalid",
            core_path="/etc/openclash/core/clash_meta",
        )


def http_evidence(
    status: int | None,
    *,
    body: str = "",
    host: str = "example.com",
    curl_code: int = 0,
) -> dict[str, object]:
    return {
        "curl_code": curl_code,
        "http_status": status,
        "final_host": host,
        "content_type": "text/html",
        "time_connect": 0.1 if curl_code == 0 else 0.0,
        "body_excerpt": body,
    }


def service_result(
    raw: str,
    *,
    final: str | None = None,
    override: str | None = None,
) -> dict[str, object]:
    return {
        "raw_result": raw,
        "override": override,
        "final_result": final or override or raw,
        "evidence": {},
        "functional_result": {
            "attribution_status": "ATTRIBUTION_MATCH",
            "exit_country": "United States",
        },
    }


def probe_node(
    name: str,
    *,
    gpt: dict[str, object] | None = None,
    gemini: dict[str, object] | None = None,
    disney: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "selector_confirmed": True,
        "base_result": "BASE_PASS",
        "egress_country": "United States",
        "services": {
            "gpt": gpt or service_result("UNKNOWN"),
            "gemini": gemini or service_result("UNKNOWN"),
            "disney": disney or service_result("UNKNOWN"),
        },
    }


def lkg_entry() -> dict[str, object]:
    return {
        "last_raw_result": "PASS",
        "last_final_result": "PASS",
        "last_confirmed_pass_at": "2026-07-15T00:00:00+08:00",
        "source": "legacy_seed",
        "lkg": True,
    }


def test_v3_challenge_and_structured_manual_results() -> None:
    challenge = MODULE.classify_service_evidence(
        "gpt",
        http_evidence(403, body="Cloudflare cf-chl verify you are human", host="chatgpt.com"),
        http_evidence(404, host="cdn.oaistatic.com"),
    )
    assert challenge == "CHALLENGE_UNKNOWN"
    report = {
        "run_timestamp": "2026-07-19T10:40:49+08:00",
        "nodes": [
            probe_node("🇯🇵日本aws高速02", gpt=service_result(challenge)),
        ],
    }
    updated = MODULE.apply_manual_results_to_report(
        report,
        [
            {
                "service": "gpt",
                "node": "日本aws高速02",
                "result": "PASS",
                "tested_at": "2026-07-20T00:00:00+08:00",
                "method": "logged_in_browser_actual_generation",
            }
        ],
    )
    result = updated["nodes"][0]["services"]["gpt"]
    assert result["raw_result"] == "CHALLENGE_UNKNOWN"
    assert result["final_result"] == "MANUAL_OVERRIDE_PASS"
    assert result["manual_result"]["method"] == "logged_in_browser_actual_generation"
    assert updated["manual_results"]["applied"] == 1
    assert MODULE.classify_service_evidence(
        "disney", http_evidence(401), http_evidence(404)
    ) == "AUTH_UNKNOWN"


def test_v3_screening_is_not_definitive_service_pass() -> None:
    main = http_evidence(200, host="gemini.google.com")
    support = http_evidence(404, host="generativelanguage.googleapis.com")
    assert MODULE.classify_service_evidence("gemini", main, support) == "GEMINI_SCREEN_PASS"
    assert MODULE.classify_service_evidence(
        "gemini",
        http_evidence(200, body="service is not available in your country"),
        support,
    ) == "GEMINI_SCREEN_FAIL"
    assert MODULE.classify_service_evidence(
        "disney",
        http_evidence(200, host="www.disneyplus.com"),
        http_evidence(404, host="global.edge.bamgrid.com"),
    ) == "UNKNOWN_INCOMPLETE_PROBE"
    assert "GEMINI_SCREEN_PASS" not in MODULE.PASS_RESULTS
    assert "GEMINI_SCREEN_FAIL" in MODULE.REMOVE_RESULTS
    assert "UNKNOWN_INCOMPLETE_PROBE" not in MODULE.PASS_RESULTS


def test_v3_stale_and_unmatched_manual_results_do_not_override() -> None:
    report = {
        "run_timestamp": "2026-07-20T12:00:00+08:00",
        "nodes": [probe_node("node-a", gemini=service_result("PASS"))],
    }
    updated = MODULE.apply_manual_results_to_report(
        report,
        [
            {
                "service": "gemini",
                "node": "node-a",
                "result": "PASS",
                "tested_at": "2026-07-19T12:00:00+08:00",
                "method": "logged_in_browser_actual_generation",
            },
            {
                "service": "gpt",
                "node": "missing-node",
                "result": "PASS",
                "tested_at": "2026-07-21T12:00:00+08:00",
                "method": "logged_in_browser_actual_generation",
            },
        ],
    )
    result = updated["nodes"][0]["services"]["gemini"]
    assert result["raw_result"] == "GEMINI_SCREEN_PASS"
    assert result["final_result"] == "GEMINI_SCREEN_PASS"
    assert updated["manual_results"]["applied"] == 0
    assert len(updated["manual_results"]["unmatched_or_stale"]) == 2


def test_v3_reconcile_adds_current_source_node_without_faking_probe(tmp_path) -> None:
    old_name = "🇯🇵日本aws高速02"
    new_name = "🇯🇵日本-流媒体01"
    data = {"proxies": [proxy(old_name), proxy(new_name)], "rules": []}
    state = {
        "schema_version": 1,
        "updated_at": "2026-07-19T10:40:49+08:00",
        "nodes": {
            old_name: {service: lkg_entry() for service in MODULE.SERVICE_KEYS},
        },
    }
    report = {
        "schema_version": 1,
        "probe_version": "2",
        "run_timestamp": "2026-07-19T10:40:49+08:00",
        "probable_tun_or_upstream_recapture": False,
        "nodes": [probe_node(old_name)],
    }
    manual = {
        "schema_version": 1,
        "results": [
            {
                "service": "gpt",
                "node": new_name,
                "result": "PASS",
                "tested_at": "2026-07-20T00:00:00+08:00",
                "method": "logged_in_browser_actual_generation",
            }
        ],
    }
    state_path = tmp_path / "state.json"
    report_path = tmp_path / "report.json"
    manual_path = tmp_path / "manual.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manual_path.write_text(json.dumps(manual), encoding="utf-8")
    selections, written = MODULE.reconcile_existing_probe(
        data,
        state_path=state_path,
        probe_report_path=report_path,
        manual_results_path=manual_path,
        report_output_path=tmp_path / "reconciled.json",
        state_output_path=tmp_path / "reconciled-state.json",
    )
    new_node = next(node for node in written["nodes"] if node["name"] == new_name)
    assert new_name in written["nodes_added_without_probe"]
    assert new_node["base_result"] == "NOT_PROBED_CURRENT_SOURCE"
    assert new_node["services"]["gpt"]["final_result"] == "MANUAL_OVERRIDE_PASS"
    assert new_name in selections["gpt"]["automatic"]
    assert written["definitive_pass_counts"]["gemini"] == 0
    assert "GEMINI_CURRENT_SCREEN_OR_MANUAL_CANDIDATE_MISSING" in written[
        "activation_blocked_reasons"
    ]


def test_network_snapshot_treats_absent_policy_tables_as_empty_state() -> None:
    command = MODULE.network_state_capture_command("/tmp/network-state")

    assert "ip -4 rule show 2>/dev/null || true" in command
    assert "ip -4 route show table 354 2>/dev/null || true" in command
    assert "ip -6 rule show 2>/dev/null || true" in command
    assert "ip -6 route show table 354 2>/dev/null || true" in command
    assert (
        "nft -s list table inet fw4 2>/dev/null | "
        "grep -E 'openclash|OpenClash' | sort || true"
    ) in command


def test_v2_lkg_merge_rules_and_current_subscription_filter() -> None:
    anchor = "🇯🇵锚点"
    existing_unknown = "🇨🇳台湾旧LKG"
    transport_lkg = "🇸🇬传输失败旧LKG"
    region_fail = "🇺🇸地区失败旧LKG"
    manual_fail = "🇺🇸美国-住宅"
    new_pass = "🇩🇪新PASS"
    new_unknown = "🇰🇷新UNKNOWN"
    absent_old = "🇬🇧已下线旧节点"
    names = [
        anchor,
        existing_unknown,
        transport_lkg,
        region_fail,
        manual_fail,
        new_pass,
        new_unknown,
    ]
    state = {
        "schema_version": 1,
        "updated_at": "old",
        "nodes": {
            anchor: {service: lkg_entry() for service in MODULE.SERVICE_KEYS},
            existing_unknown: {"gpt": lkg_entry()},
            transport_lkg: {"gpt": lkg_entry()},
            region_fail: {"gpt": lkg_entry()},
            manual_fail: {"gemini": lkg_entry()},
            absent_old: {"gpt": lkg_entry()},
        },
    }
    nodes = [
        probe_node(
            anchor,
            gpt=service_result("DEFINITIVE_AUTOMATED_PASS"),
            gemini=service_result("DEFINITIVE_AUTOMATED_PASS"),
            disney=service_result("PASS_SUPPORTED_REGION"),
        ),
        probe_node(existing_unknown, gpt=service_result("UNKNOWN")),
        probe_node(transport_lkg, gpt=service_result("FAIL_TRANSPORT")),
        probe_node(region_fail, gpt=service_result("FAIL_REGION")),
        probe_node(
            manual_fail,
            gemini=service_result(
                "PASS", final="MANUAL_OVERRIDE_FAIL", override="MANUAL_OVERRIDE_FAIL"
            ),
        ),
        probe_node(new_pass, gpt=service_result("DEFINITIVE_AUTOMATED_PASS")),
        probe_node(new_unknown, gpt=service_result("UNKNOWN")),
    ]
    selections, new_state, enriched = MODULE.merge_lkg_results(
        names,
        {name: index for index, name in enumerate(names)},
        state,
        nodes,
        probable_recapture=False,
        observed_at="2026-07-15T12:00:00+08:00",
    )

    assert existing_unknown in selections["gpt"]["historical_lkg"]
    assert transport_lkg in selections["gpt"]["historical_lkg"]
    assert new_pass in selections["gpt"]["automatic"]
    assert region_fail not in selections["gpt"]["automatic"]
    assert manual_fail not in selections["gemini"]["automatic"]
    assert new_unknown not in selections["gpt"]["automatic"]
    assert new_unknown in selections["gpt"]["manual_candidates"]
    assert absent_old not in new_state["nodes"]
    assert all(absent_old not in group["automatic"] for group in selections.values())
    new_unknown_result = next(item for item in enriched if item["name"] == new_unknown)
    assert new_unknown_result["lkg_merge"]["gpt"] == "NEW_NODE_NOT_LKG"
    generated = MODULE.transform(
        {"proxies": [proxy(name) for name in names], "rules": []}, selections
    )
    generated_groups = {group["name"]: group for group in generated["proxy-groups"]}
    assert "GPT历史LKG" in generated_groups
    assert "Gemini历史LKG" not in generated_groups
    assert "迪士尼历史LKG" not in generated_groups
    assert generated_groups["GPT候选"]["proxies"] == selections["gpt"]["automatic"]
    assert generated_groups["GPT手动"]["proxies"] == [
        "GPT候选",
        *selections["gpt"]["automatic"],
        "GPT历史LKG",
        *selections["gpt"]["manual_candidates"],
    ]


def test_v2_probable_recapture_does_not_update_lkg() -> None:
    anchor = "🇯🇵旧LKG"
    new_node = "🇺🇸新节点"
    state = {
        "schema_version": 1,
        "updated_at": "old",
        "nodes": {anchor: {service: lkg_entry() for service in MODULE.SERVICE_KEYS}},
    }
    signature_nodes = [
        {
            "name": anchor,
            "base_result": "BASE_PASS",
            "egress_country": "JP",
            "egress_asn": 64500,
            "egress_ip_hash": "samehash",
        },
        {
            "name": new_node,
            "base_result": "BASE_PASS",
            "egress_country": "JP",
            "egress_asn": 64500,
            "egress_ip_hash": "samehash",
        },
        {
            "name": "🇨🇳台湾节点",
            "base_result": "BASE_PASS",
            "egress_country": "JP",
            "egress_asn": 64500,
            "egress_ip_hash": "samehash",
        },
    ]
    assert MODULE.probable_unified_egress(signature_nodes) is True
    nodes = [
        probe_node(
            anchor,
            gpt=service_result("FAIL_REGION"),
            gemini=service_result("FAIL_REGION"),
            disney=service_result("FAIL_REGION"),
        ),
        probe_node(
            new_node,
            gpt=service_result("PASS"),
            gemini=service_result("PASS"),
            disney=service_result("PASS"),
        ),
    ]
    selections, new_state, _ = MODULE.merge_lkg_results(
        [anchor, new_node],
        {anchor: 0, new_node: 1},
        state,
        nodes,
        probable_recapture=True,
        observed_at="new",
    )
    assert new_state == state
    assert selections["gpt"]["automatic"] == []
    assert selections["gpt"]["historical_lkg"] == [anchor]
    assert new_node not in selections["gpt"]["automatic"]


def test_v2_state_seed_atomic_write_and_mode(tmp_path) -> None:
    legacy = {
        "proxy-groups": [
            {"name": "GPT自动", "proxies": ["gpt-node"]},
            {"name": "Gemini自动", "proxies": ["gemini-node"]},
            {"name": "迪士尼自动", "proxies": ["disney-node"]},
        ]
    }
    state = MODULE.seed_lkg_state(legacy, updated_at="seed-time")
    assert state["nodes"]["gpt-node"]["gpt"]["source"] == "legacy_seed"
    assert state["nodes"]["gemini-node"]["gemini"]["lkg"] is True
    state_path = tmp_path / "private" / "service-probe-lkg.json"
    MODULE.atomic_write_json(state, state_path, private_parent=True)
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_path.parent.stat().st_mode) == 0o700
    assert json.loads(state_path.read_text(encoding="utf-8"))["schema_version"] == 1
    assert not list(state_path.parent.glob("*.tmp"))

    for temp_root in {Path("/tmp").resolve(), Path(MODULE.tempfile.gettempdir()).resolve()}:
        temp_root_state = temp_root / "openclash-v2-test-state.json"
        original_parent_mode = stat.S_IMODE(temp_root_state.parent.stat().st_mode)
        try:
            MODULE.atomic_write_json(state, temp_root_state, private_parent=True)
            assert stat.S_IMODE(temp_root_state.stat().st_mode) == 0o600
            assert stat.S_IMODE(temp_root_state.parent.stat().st_mode) == original_parent_mode
        finally:
            temp_root_state.unlink(missing_ok=True)


def test_v2_empty_current_service_group_blocks_generation() -> None:
    name = "🇯🇵only-node"
    state = {"schema_version": 1, "updated_at": "old", "nodes": {}}
    selections, _, _ = MODULE.merge_lkg_results(
        [name],
        {name: 0},
        state,
        [
            probe_node(
                name,
                gpt=service_result("FAIL_REGION"),
                gemini=service_result("FAIL_REGION"),
                disney=service_result("FAIL_REGION"),
            )
        ],
        probable_recapture=False,
        observed_at="now",
    )
    with pytest.raises(MODULE.ConfigError, match="BLOCKED_NO_CURRENT_SERVICE_CANDIDATES"):
        MODULE.transform({"proxies": [proxy(name)], "rules": []}, selections)


def test_v2_probe_report_rejects_credentials_and_full_ip() -> None:
    MODULE.validate_probe_report_safe(
        {"nodes": [{"name": "node", "egress_ip_hash": "0123456789abcdef"}]}
    )
    with pytest.raises(MODULE.ConfigError, match="forbidden key"):
        MODULE.validate_probe_report_safe({"nodes": [{"password": "secret"}]})
    with pytest.raises(MODULE.ConfigError, match="full egress IP"):
        MODULE.validate_probe_report_safe({"nodes": [{"egress": "203.0.113.8"}]})


def test_v2_fake_selector_and_http_runner() -> None:
    selected: list[str] = []
    slept: list[float] = []

    def switch(name: str) -> bool:
        selected.append(name)
        return name != "🇺🇸unconfirmed"

    def request(url: str) -> dict[str, object]:
        if url == "https://speed.cloudflare.com/meta":
            return {
                **http_evidence(200, body='{"clientIp":"198.51.100.7","country":"JP","asn":16509}'),
                "remote_ip": "198.51.100.7",
            }
        if url == "https://www.gstatic.com/generate_204":
            return http_evidence(204, host="www.gstatic.com")
        if url == "https://chatgpt.com/":
            return http_evidence(403, body="Cloudflare challenge-platform", host="chatgpt.com")
        return http_evidence(404, host=urllib_host(url))

    report = MODULE.probe_nodes_with_runner(
        [proxy("🇯🇵日本aws高速02"), proxy("🇺🇸unconfirmed")],
        switch_node=switch,
        request_url=request,
        sleep_fn=slept.append,
        monotonic_fn=lambda: 0.0,
        run_key=b"fixed-test-key",
    )
    assert selected == ["🇯🇵日本aws高速02", "🇺🇸unconfirmed"]
    assert slept == [MODULE.PROBE_SWITCH_WAIT_SECONDS]
    first, second = report["nodes"]
    assert first["services"]["gpt"]["raw_result"] == "CHALLENGE_UNKNOWN"
    assert first["services"]["gpt"]["final_result"] == "CHALLENGE_UNKNOWN"
    assert first["egress_ip_hash"] and first["egress_ip_hash"] != "198.51.100.7"
    assert second["base_result"] == "NODE_SWITCH_UNCONFIRMED"
    assert second["services"]["gpt"]["final_result"] == "NODE_SWITCH_UNCONFIRMED"
    MODULE.validate_probe_report_safe(report)


def test_v2_probe_transport_rule_route_and_selector_confirmation() -> None:
    config = MODULE.build_probe_config(
        [proxy("node-a"), proxy("node-b")],
        mixed_port=12345,
        controller_port=23456,
        interface_name="en0",
    )
    assert config["mode"] == "rule"
    assert config["interface-name"] == "en0"
    assert config["rules"] == ["MATCH,PROBE"]
    assert config["proxy-groups"] == [
        {"name": "PROBE", "type": "select", "proxies": ["node-a", "node-b"]}
    ]

    calls: list[tuple[str, str]] = []

    def runtime_request(_port: int, path: str, **_kwargs):
        calls.append(("runtime", path))
        if path == "/configs":
            return {"mode": "rule"}
        if path == "/rules":
            return {"rules": [{"type": "Match", "proxy": "PROBE"}]}
        if path == "/proxies/GLOBAL":
            return {"now": "DIRECT"}
        raise AssertionError(path)

    assert MODULE.validate_probe_runtime(23456, request=runtime_request) == "DIRECT"
    assert ("runtime", "/proxies/GLOBAL") in calls

    def mismatched_selector(_port: int, _path: str, **kwargs):
        return {} if kwargs.get("method") == "PUT" else {"now": "node-b"}

    assert (
        MODULE.select_probe_node(23456, "node-a", request=mismatched_selector) is False
    )


def test_v2_recapture_ignores_transport_failure_and_distinct_egress() -> None:
    nodes = [
        {
            "name": "🇯🇵日本节点",
            "base_result": "BASE_PASS",
            "egress_country": "JP",
            "egress_asn": 16509,
            "egress_ip_hash": "japan-hash",
        },
        {
            "name": "🇨🇳台湾节点",
            "base_result": "BASE_PASS",
            "egress_country": "TW",
            "egress_asn": 3462,
            "egress_ip_hash": "taiwan-hash",
        },
        {
            "name": "🇺🇸失败节点",
            "base_result": "HTTP_TIMEOUT",
            "egress_country": None,
            "egress_asn": None,
            "egress_ip_hash": None,
        },
    ]
    assert MODULE.probable_unified_egress(nodes) is False


def test_v2_missing_physical_interface_blocks() -> None:
    def runner(args, **_kwargs):
        if args[-1] == "en0":
            return subprocess.CompletedProcess(args, 1, "", "")
        if "route" in args[0]:
            return subprocess.CompletedProcess(args, 0, "  interface: utun8\n", "")
        raise AssertionError(args)

    with pytest.raises(MODULE.ConfigError, match="BLOCKED_NO_PHYSICAL_INTERFACE"):
        MODULE.find_probe_interface(runner=runner)


def test_v2_temporary_probe_cleanup_on_runtime_validation_failure(
    tmp_path, monkeypatch
) -> None:
    class FakeProcess:
        def __init__(self):
            self.running = True
            self.terminated = False

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.terminated = True
            self.running = False

        def wait(self, timeout=None):
            return 0

    process = FakeProcess()
    started_config: list[Path] = []
    validation_commands: list[list[str]] = []
    ports = iter((12345, 23456))
    core = tmp_path / "mihomo"

    def fake_validation(args, **_kwargs):
        validation_commands.append(args)
        return subprocess.CompletedProcess(args, 0)

    def fake_popen(args, **_kwargs):
        started_config.append(Path(args[-1]))
        return process

    monkeypatch.setattr(MODULE, "find_probe_core", lambda _path=None: core)
    monkeypatch.setattr(MODULE, "find_probe_interface", lambda: "en0")
    monkeypatch.setattr(MODULE, "reserve_loopback_port", lambda: next(ports))
    monkeypatch.setattr(MODULE.subprocess, "run", fake_validation)
    monkeypatch.setattr(MODULE.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(MODULE, "wait_for_controller", lambda *_args: None)
    monkeypatch.setattr(
        MODULE,
        "validate_probe_runtime",
        lambda *_args: (_ for _ in ()).throw(MODULE.ConfigError("route failed")),
    )

    with pytest.raises(MODULE.ConfigError, match="route failed"):
        MODULE.run_local_service_probe(
            {"proxies": [proxy("node-a")]}, core_path=str(core)
        )
    assert validation_commands and "-t" in validation_commands[0]
    assert process.terminated is True
    assert started_config and not started_config[0].exists()


def test_v2_egress_metadata_falls_back_after_primary_403() -> None:
    requested: list[str] = []

    def request(url: str) -> dict[str, object]:
        requested.append(url)
        if url == "https://speed.cloudflare.com/meta":
            return http_evidence(403, body="forbidden")
        if url == "https://ipwho.is/":
            return http_evidence(
                200,
                body=(
                    '{"ip":"198.51.100.8","country_code":"JP",'
                    '"connection":{"asn":16509}}'
                ),
            )
        if url == "https://www.gstatic.com/generate_204":
            return http_evidence(204, host="www.gstatic.com")
        return http_evidence(200, host=urllib_host(url))

    report = MODULE.probe_nodes_with_runner(
        [proxy("fallback-node")],
        switch_node=lambda _name: True,
        request_url=request,
        sleep_fn=lambda _seconds: None,
        monotonic_fn=lambda: 0.0,
        run_key=b"fixed-test-key",
    )
    node = report["nodes"][0]
    assert requested[:2] == [
        "https://speed.cloudflare.com/meta",
        "https://ipwho.is/",
    ]
    assert "https://ipapi.co/json/" not in requested
    assert node["base_result"] == "BASE_PASS"
    assert node["egress_country"] == "JP"
    assert node["egress_asn"] == 16509
    assert node["egress_ip_hash"] != "198.51.100.8"
    MODULE.validate_probe_report_safe(report)


def test_v2_dynamic_pipeline_writes_report_and_lkg_state(tmp_path) -> None:
    names = MODULE.ordered_unique(
        [*MODULE.GPT_CANDIDATES, *MODULE.GEMINI_CANDIDATES, *MODULE.DISNEY_CANDIDATES]
    )
    data = {"proxies": [proxy(name) for name in names], "rules": []}
    report_path = tmp_path / "probe-results.json"
    state_path = tmp_path / "state" / "service-probe-lkg.json"
    manual_path = tmp_path / "manual-results.json"
    manual_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "results": [
                    {
                        "service": "gpt",
                        "node": "🇯🇵日本aws高速02",
                        "result": "PASS",
                        "tested_at": "2026-07-16T00:00:00+08:00",
                        "method": "logged_in_browser_actual_generation",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_probe(source, *, core_path=None):
        return {
            "schema_version": 1,
            "probe_version": "test",
            "run_id": "testrun",
            "run_timestamp": "2026-07-15T12:00:00+08:00",
            "stopped_due_deadline": False,
            "probable_tun_or_upstream_recapture": False,
            "nodes": [
                probe_node(
                    "🇯🇵日本aws高速02",
                    gpt=service_result(
                        "CHALLENGE_UNKNOWN",
                        final="MANUAL_OVERRIDE_PASS",
                        override="MANUAL_OVERRIDE_PASS",
                    ),
                    gemini=service_result("PASS"),
                    disney=service_result("PASS"),
                )
            ],
        }

    selections, written = MODULE.dynamic_probe_and_select(
        data,
        state_path=state_path,
        report_path=report_path,
        core_path=None,
        update_lkg=True,
        manual_results_path=manual_path,
        probe_runner=fake_probe,
    )
    assert written == json.loads(report_path.read_text(encoding="utf-8"))
    assert written["lkg_seed_source"] == "legacy_seed"
    assert written["lkg_state_updated"] is True
    assert "🇯🇵日本aws高速02" in selections["gpt"]["automatic"]
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved_state["nodes"]["🇯🇵日本aws高速02"]["gpt"]["source"] == "manual_override"


def urllib_host(url: str) -> str:
    return url.split("/", 3)[2]


def test_remote_health_deadline_is_bounded_and_stable() -> None:
    assert 45 <= MODULE.REMOTE_HEALTH_DEADLINE_SECONDS <= 120
    assert MODULE.REMOTE_HEALTH_POLL_INTERVAL_SECONDS == 1
    assert MODULE.REMOTE_HEALTH_CONSECUTIVE_SUCCESSES == 2


def test_remote_health_uses_deadline_auth_and_two_consecutive_passes(monkeypatch) -> None:
    commands: list[str] = []
    outcomes = iter([0, 1, 0, 0])
    clock = [0.0]

    def fake_ssh(host: str, command: str, *, capture: bool = False):
        commands.append(command)
        if next(outcomes):
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(MODULE, "ssh_command", fake_ssh)
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        MODULE.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    MODULE.verify_remote_health(
        "router.invalid",
        remote_path="/etc/openclash/config/new.yaml",
        core_path="/etc/openclash/core/clash_meta",
        expected_sha256="abc123",
        deadline_seconds=10,
        poll_interval_seconds=1,
        consecutive_successes=2,
    )

    assert len(commands) == 4
    command = commands[0]
    assert "OPENCLASH_HEALTH_CHECK=1" in command
    assert "openclash.@authentication[$auth_index].enabled" in command
    assert "curl --config -" in command
    assert "--proxy-user" not in command
    assert "cn_port" in command
    assert "nslookup" in command
    assert "abc123" in command


def test_remote_health_stops_only_at_deadline(monkeypatch) -> None:
    calls = 0
    clock = [0.0]

    def fake_ssh(host: str, command: str, *, capture: bool = False):
        nonlocal calls
        calls += 1
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(MODULE, "ssh_command", fake_ssh)
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        MODULE.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    with pytest.raises(MODULE.ConfigError, match="deadline"):
        MODULE.verify_remote_health(
            "router.invalid",
            remote_path="/etc/openclash/config/new.yaml",
            core_path="/etc/openclash/core/clash_meta",
            deadline_seconds=3,
            poll_interval_seconds=1,
            consecutive_successes=2,
        )

    assert calls == 3
    assert clock[0] == 3


def source_gate_fixture(tmp_path: Path, *, count: int = 4) -> tuple[Path, Path]:
    base = tmp_path / "clash-verge"
    base.mkdir()
    source = base / "clash-verge.yaml"
    MODULE.dump_yaml(
        {
            "proxies": [
                {
                    **proxy(f"node-{index}"),
                    "server": f"node-{index}.example.invalid",
                    "password": f"credential-{index}",
                }
                for index in range(count)
            ],
            "rules": [],
        },
        source,
    )
    MODULE.dump_yaml(
        {
            "current": "remote-main",
            "items": [
                {
                    "uid": "remote-main",
                    "type": "remote",
                    "url": "https://subscription.invalid/path?fixture=redacted",
                    "updated": 1,
                    "selected": [{"name": "GLOBAL", "now": "node-0"}],
                    "file": "remote.yaml",
                },
                {"uid": "merge", "type": "merge", "file": "Merge.yaml"},
            ],
        },
        base / "profiles.yaml",
    )
    MODULE.dump_yaml(
        {"enable_system_proxy": True, "enable_tun_mode": False}, base / "verge.yaml"
    )
    MODULE.dump_yaml({"mode": "rule"}, base / "config.yaml")
    return source, tmp_path / "identity.key"


def successful_refresh(monkeypatch, *, mutate=None, outcome="SUCCESS_CHANGED") -> None:
    def run_adapter(_adapter, *, profile_uid, paths, timeout_seconds, staging_dir):
        assert profile_uid == "remote-main"
        assert timeout_seconds > 0
        if mutate:
            mutate(paths)
        staging_dir.mkdir(parents=True, exist_ok=True)
        enhanced = staging_dir / ".source-refresh-snapshot-testnonce.yaml"
        shutil.copyfile(paths["effective"], enhanced)
        enhanced.chmod(0o600)
        content_before = "a" * 64
        content_after = content_before if outcome == "SUCCESS_NOT_MODIFIED" else "b" * 64
        return {
            "outcome": outcome,
            "profile_identity": hashlib.sha256(
                profile_uid.encode()
                + b"\0"
                + b"https://subscription.invalid/path?fixture=redacted"
            ).hexdigest()[:16],
            "source_identity_verified": True,
            "content_hash_before": content_before,
            "content_hash_after": content_after,
            "download_path_used": "DIRECT",
            "parsed_node_count_before": 4,
            "parsed_node_count_after": 5 if outcome == "SUCCESS_CHANGED" else 4,
            "enhanced_snapshot_path": str(enhanced),
            "enhanced_snapshot_hash": MODULE.sha256_file(enhanced),
            "started_at": "2026-07-22T00:00:00+08:00",
            "completed_at": "2026-07-22T00:00:01+08:00",
        }

    monkeypatch.setattr(MODULE, "run_source_refresh_adapter", run_adapter)


def prepare_gate(tmp_path, monkeypatch, **kwargs):
    source, key = source_gate_fixture(tmp_path, count=kwargs.pop("count", 4))
    return MODULE.prepare_source_snapshot(
        source=source,
        workdir=tmp_path / "output",
        refresh_adapter=tmp_path / "official-adapter",
        no_refresh=False,
        source_snapshot=None,
        identity_key_path=key,
        refresh_timeout=5,
        min_node_retention_ratio=kwargs.pop("ratio", 0.5),
        **kwargs,
    )


def test_source_refresh_changed_freezes_private_snapshot(tmp_path, monkeypatch) -> None:
    def mutate(paths):
        data = MODULE.load_yaml(paths["effective"])
        data["proxies"].append(
            {**proxy("node-new"), "server": "new.example.invalid", "password": "new-secret"}
        )
        MODULE.dump_yaml(data, paths["effective"])

    successful_refresh(monkeypatch, mutate=mutate)
    manifest, payload, runtime = prepare_gate(tmp_path, monkeypatch)
    assert manifest["refresh_outcome"] == "SUCCESS_CHANGED"
    assert manifest["node_count"] == 5
    assert stat.S_IMODE(payload.stat().st_mode) == 0o600
    assert runtime["router_contacted_before_snapshot"] is False
    assert runtime["clash_verge_state_preserved"] is True
    text = Path(runtime["manifest_path"]).read_text(encoding="utf-8")
    assert "top-secret" not in text and "credential-" not in text
    report_text = Path(runtime["report_path"]).read_text(encoding="utf-8")
    assert "top-secret" not in report_text and "credential-" not in report_text
    assert json.loads(report_text)["router_contacted_before_snapshot"] is False
    assert json.loads(report_text)["download_path_used"] == "DIRECT"


def test_source_refresh_not_modified_is_valid(tmp_path, monkeypatch) -> None:
    successful_refresh(monkeypatch, outcome="SUCCESS_NOT_MODIFIED")
    manifest, _payload, _runtime = prepare_gate(tmp_path, monkeypatch)
    assert manifest["refresh_outcome"] == "SUCCESS_NOT_MODIFIED"
    assert manifest["source_diff_summary"]["added"] == []


@pytest.mark.parametrize(
    "outcome",
    ["FAIL_AUTH", "FAIL_TRANSPORT", "FAIL_PARSE", "FAIL_TIMEOUT", "FAIL_EMPTY_RESULT"],
)
def test_source_refresh_failure_receipts_fail_closed(tmp_path, monkeypatch, outcome) -> None:
    source, key = source_gate_fixture(tmp_path)
    monkeypatch.setattr(
        MODULE,
        "run_source_refresh_adapter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MODULE.ConfigError(f"STOP_SOURCE_REFRESH_FAILED: {outcome}")
        ),
    )
    router_calls: list[str] = []
    monkeypatch.setattr(MODULE, "ssh_command", lambda *_a, **_k: router_calls.append("ssh"))
    with pytest.raises(MODULE.ConfigError, match="STOP_SOURCE_REFRESH_FAILED"):
        MODULE.prepare_source_snapshot(
            source=source,
            workdir=tmp_path / "output",
            refresh_adapter=tmp_path / "adapter",
            no_refresh=False,
            source_snapshot=None,
            identity_key_path=key,
            refresh_timeout=1,
            min_node_retention_ratio=0.5,
        )
    assert router_calls == []


@pytest.mark.parametrize(
    ("replacement", "message"),
    [("not: [valid", "STOP_SOURCE_PARSE_FAILED"), ("proxies: []\n", "STOP_SOURCE_EMPTY")],
)
def test_refreshed_source_parse_and_empty_gate(tmp_path, monkeypatch, replacement, message) -> None:
    def mutate(paths):
        paths["effective"].write_text(replacement, encoding="utf-8")

    successful_refresh(monkeypatch, mutate=mutate)
    with pytest.raises(MODULE.ConfigError, match=message):
        prepare_gate(tmp_path, monkeypatch)


def test_source_identity_drift_and_node_collapse_gate(tmp_path, monkeypatch) -> None:
    def drift(paths):
        data = MODULE.load_yaml(paths["profiles"])
        data["current"] = "other"
        data["items"].append(
            {"uid": "other", "type": "remote", "url": "https://other.invalid/sub"}
        )
        MODULE.dump_yaml(data, paths["profiles"])

    successful_refresh(monkeypatch, mutate=drift)
    with pytest.raises(MODULE.ConfigError, match="STOP_SOURCE_IDENTITY_DRIFT"):
        prepare_gate(tmp_path, monkeypatch)

    other = tmp_path / "collapse"
    other.mkdir()

    def collapse(paths):
        data = MODULE.load_yaml(paths["effective"])
        data["proxies"] = data["proxies"][:1]
        MODULE.dump_yaml(data, paths["effective"])

    successful_refresh(monkeypatch, mutate=collapse)
    with pytest.raises(MODULE.ConfigError, match="abnormal node-count collapse"):
        prepare_gate(other, monkeypatch, count=10, ratio=0.5)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current", "other"),
        ("selected", [{"name": "GLOBAL", "now": "node-2"}]),
        ("system_proxy", False),
        ("tun", True),
    ],
)
def test_clash_verge_runtime_state_drift_stops(tmp_path, monkeypatch, field, value) -> None:
    def mutate(paths):
        if field == "current":
            data = MODULE.load_yaml(paths["profiles"])
            data["current"] = value
            data["items"].append(
                {"uid": "other", "type": "remote", "url": "https://other.invalid/sub"}
            )
            MODULE.dump_yaml(data, paths["profiles"])
        elif field == "selected":
            data = MODULE.load_yaml(paths["profiles"])
            data["items"][0]["selected"] = value
            MODULE.dump_yaml(data, paths["profiles"])
        else:
            data = MODULE.load_yaml(paths["verge"])
            data["enable_system_proxy" if field == "system_proxy" else "enable_tun_mode"] = value
            MODULE.dump_yaml(data, paths["verge"])

    successful_refresh(monkeypatch, mutate=mutate)
    expected = "STOP_SOURCE_IDENTITY_DRIFT" if field == "current" else "STOP_CLASH_VERGE_STATE_DRIFT"
    with pytest.raises(MODULE.ConfigError, match=expected):
        prepare_gate(tmp_path, monkeypatch)


def test_snapshot_replay_never_rereads_changed_live_source(tmp_path, monkeypatch) -> None:
    successful_refresh(monkeypatch, outcome="SUCCESS_NOT_MODIFIED")
    manifest, payload, runtime = prepare_gate(tmp_path, monkeypatch)
    frozen = payload.read_bytes()
    source = tmp_path / "clash-verge" / "clash-verge.yaml"
    source.write_text("proxies: []\n", encoding="utf-8")
    replay, replay_payload, replay_runtime = MODULE.prepare_source_snapshot(
        source=source,
        workdir=tmp_path / "unused",
        refresh_adapter=None,
        no_refresh=False,
        source_snapshot=Path(runtime["manifest_path"]),
        identity_key_path=tmp_path / "unused.key",
        refresh_timeout=1,
        min_node_retention_ratio=0.5,
    )
    assert replay["source_snapshot_id"] == manifest["source_snapshot_id"]
    assert replay_payload.read_bytes() == frozen
    assert replay_runtime["live_source_reread_after_snapshot"] is False


def test_explicit_no_refresh_and_freshness_gate(tmp_path) -> None:
    source, key = source_gate_fixture(tmp_path)
    manifest, _payload, runtime = MODULE.prepare_source_snapshot(
        source=source,
        workdir=tmp_path / "output",
        refresh_adapter=None,
        no_refresh=True,
        source_snapshot=None,
        identity_key_path=key,
        refresh_timeout=1,
        min_node_retention_ratio=0.5,
    )
    assert runtime["refresh_result"] == "SOURCE_REFRESH_SKIPPED_EXPLICITLY"
    stale = deepcopy(manifest)
    stale["created_at"] = "2020-01-01T00:00:00+00:00"
    with pytest.raises(MODULE.ConfigError, match="STALE_SOURCE_SNAPSHOT"):
        MODULE.validate_snapshot_for_activation(stale, freshness_ttl=60, allow_stale=False)
    MODULE.validate_snapshot_for_activation(stale, freshness_ttl=60, allow_stale=True)


def test_same_name_changed_identity_does_not_inherit_lkg() -> None:
    name = "same-name"
    node = probe_node(name)
    node["exact_node_id"] = "node-new"
    state = {
        "schema_version": 1,
        "updated_at": "old",
        "nodes": {
            name: {
                service: {**lkg_entry(), "exact_node_id": "node-old"}
                for service in MODULE.SERVICE_KEYS
            }
        },
    }
    selections, _, _ = MODULE.merge_lkg_results(
        [name],
        {name: 0},
        state,
        [node],
        probable_recapture=False,
        observed_at="2026-07-20T12:00:00+08:00",
    )
    assert selections["gpt"]["historical_lkg"] == []


def test_evidence_matrix_binds_snapshot_and_definitive_counts_remain_zero() -> None:
    report = {
        "run_timestamp": "2026-07-20T12:00:00+08:00",
        "service_groups": {
            service: {
                "automatic": ["node-a"] if service == "gpt" else [],
                "manual_candidates": [],
                "historical_lkg": ["node-a"] if service != "gpt" else [],
            }
            for service in MODULE.SERVICE_KEYS
        },
        "nodes": [
            probe_node(
                "node-a",
                gpt=service_result("PASS", final="MANUAL_OVERRIDE_PASS", override="MANUAL_OVERRIDE_PASS"),
                gemini=service_result("GEMINI_SCREEN_PASS"),
                disney=service_result("UNKNOWN_INCOMPLETE_PROBE"),
            )
        ],
    }
    report["nodes"][0]["services"]["gpt"]["manual_result"] = {
        "tested_at": "2026-07-20T12:00:00+08:00",
        "method": "logged_in_browser_actual_generation",
    }
    MODULE.annotate_probe_semantics(report, report["nodes"])
    assert report["definitive_automated_pass_counts"] == {
        "gpt": 0,
        "gemini": 0,
        "disney": 0,
    }
    assert report["nodes"][0]["services"]["gpt"]["evidence_type"] == "MANUAL_FUNCTIONAL_PASS"
    assert report["nodes"][0]["services"]["gemini"]["evidence_type"] == "SCREEN_PASS"
    assert report["nodes"][0]["services"]["disney"]["evidence_type"] == "LKG_FALLBACK"


def test_refresh_adapter_protocol_identity_and_timeout(tmp_path, monkeypatch) -> None:
    adapter = tmp_path / "adapter"
    adapter.write_text("#!/bin/sh\n", encoding="utf-8")
    adapter.chmod(0o700)
    paths = {"profiles": tmp_path / "profiles.yaml", "effective": tmp_path / "source.yaml"}
    MODULE.dump_yaml(
        {
            "current": "uid",
            "items": [
                {
                    "uid": "uid",
                    "type": "remote",
                    "url": "https://subscription.invalid/source",
                    "file": "remote.yaml",
                }
            ],
        },
        paths["profiles"],
    )
    expected_identity = hashlib.sha256(
        b"uid\0https://subscription.invalid/source"
    ).hexdigest()[:16]
    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                {
                    "outcome": "SUCCESS_NOT_MODIFIED",
                    "profile_identity": expected_identity,
                    "source_identity_verified": True,
                }
            ),
        ),
    )
    receipt = MODULE.run_source_refresh_adapter(
        adapter,
        profile_uid="uid",
        paths=paths,
        timeout_seconds=1,
        staging_dir=tmp_path / "staging",
    )
    assert receipt["outcome"] == "SUCCESS_NOT_MODIFIED"

    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(str(adapter), 1)
        ),
    )
    with pytest.raises(MODULE.ConfigError, match="FAIL_TIMEOUT"):
        MODULE.run_source_refresh_adapter(
            adapter,
            profile_uid="uid",
            paths=paths,
            timeout_seconds=1,
            staging_dir=tmp_path / "staging",
        )


def test_snapshot_identity_propagates_into_probe_report(tmp_path) -> None:
    name = "🇨🇳台湾-住宅"
    data = {"proxies": [proxy(name)], "rules": []}
    manifest = {
        "source_snapshot_id": "snapshot-exact",
        "source_hash": "a" * 64,
        "nodes": [{"exact_node_name": name, "exact_node_id": "node-exact"}],
    }
    state_path = tmp_path / "state.json"
    report_path = tmp_path / "report.json"

    def runner(_data, *, core_path=None):
        return {
            "schema_version": 1,
            "probe_version": MODULE.PROBE_VERSION,
            "run_timestamp": "2026-07-20T12:00:00+08:00",
            "probable_tun_or_upstream_recapture": False,
            "nodes": [probe_node(name)],
        }

    _groups, report = MODULE.dynamic_probe_and_select(
        data,
        state_path=state_path,
        report_path=report_path,
        core_path=None,
        update_lkg=False,
        snapshot_manifest=manifest,
        probe_runner=runner,
    )
    assert report["source_snapshot_id"] == "snapshot-exact"
    assert report["source_hash"] == "a" * 64
    assert report["nodes"][0]["exact_node_id"] == "node-exact"
    assert all(
        result["probe_method_version"] == MODULE.PROBE_VERSION
        for result in report["nodes"][0]["services"].values()
    )


def test_runtime_sync_commit_requires_valid_deployment_marker(tmp_path) -> None:
    skill_root = tmp_path / "skill"
    script = skill_root / "scripts" / "entrypoint.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")

    assert MODULE.runtime_sync_commit(script) == "UNRECORDED"
    marker = skill_root / MODULE.RUNTIME_SYNC_COMMIT_FILE
    marker.write_text("not-a-commit\n", encoding="ascii")
    assert MODULE.runtime_sync_commit(script) == "INVALID"
    marker.write_text("a" * 40 + "\n", encoding="ascii")
    assert MODULE.runtime_sync_commit(script) == "a" * 40
