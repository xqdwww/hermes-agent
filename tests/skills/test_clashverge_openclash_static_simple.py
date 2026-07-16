from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
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
    assert groups["GPT自动"]["type"] == "fallback"
    assert "🇯🇵日本aws高速02" in groups["GPT自动"]["proxies"]
    assert groups["GPT手动"]["proxies"] == ["GPT自动", *groups["GPT自动"]["proxies"]]
    assert groups["Gemini手动"]["proxies"] == ["Gemini自动", *groups["Gemini自动"]["proxies"]]
    assert groups["迪士尼手动"]["proxies"] == ["迪士尼自动", *groups["迪士尼自动"]["proxies"]]
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
    local_file = tmp_path / "openclash.yaml"
    local_file.write_text("proxies: []\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "load_yaml", lambda path: {})
    monkeypatch.setattr(MODULE, "validate_config", lambda data: None)
    monkeypatch.setattr(MODULE, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(MODULE.time, "sleep", lambda seconds: None)

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
                ),
                stderr="",
            )
        if "OPENCLASH_HEALTH_CHECK=1" in command:
            health_calls += 1
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess([], 0)

    def fake_run(*args, **kwargs):
        events.append("SCP_UPLOAD")
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(MODULE, "run", fake_run)
    monkeypatch.setattr(MODULE, "ssh_command", fake_ssh)
    with pytest.raises(MODULE.ConfigError, match="HEALTH_CHECK_FAILED_ROLLED_BACK"):
        MODULE.deploy(
            local_file,
            host="router.invalid",
            remote_name=None,
            core_path="/etc/openclash/core/clash_meta",
            activate=True,
        )

    assert health_calls == MODULE.HEALTH_CHECK_ATTEMPTS
    health_commands = [command for command in events if "OPENCLASH_HEALTH_CHECK=1" in command]
    assert all(
        "/etc/init.d/openclash running" in command
        and '-f "$active_path"' in command
        and "for option in mixed_port http_port" in command
        and 'http://127.0.0.1:${proxy_port}' in command
        and "ss -lnt" in command
        and "netstat -lnt" in command
        and "curl --proxy" in command
        and "--connect-timeout 3" in command
        and "--max-time 8" in command
        and "https://www.gstatic.com/generate_204" in command
        and '"$http_code" = \'204\'' in command
        for command in health_commands
    )
    state_index = next(i for i, event in enumerate(events) if "OPENCLASH_STATE_READ=1" in event)
    backup_index = next(i for i, event in enumerate(events) if "OPENCLASH_BACKUP=1" in event)
    upload_index = events.index("SCP_UPLOAD")
    assert state_index < backup_index < upload_index
    assert any("original.yaml" in command and "active-yaml" in command for command in events)
    assert any("cp -p /etc/config/openclash" in command and "service-state" in command for command in events)
    assert any("OPENCLASH_ROLLBACK=1" in command and "original.yaml" in command for command in events)
    assert any(
        "OPENCLASH_ROLLBACK_VERIFY=1" in command
        and "original.yaml" in command
        and "/etc/openclash/core/clash_meta -t" in command
        and "openclash enabled" in command
        and "openclash running" in command
        for command in events
    )


def test_rollback_failure_has_explicit_status(tmp_path, monkeypatch) -> None:
    local_file = tmp_path / "openclash.yaml"
    local_file.write_text("proxies: []\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "load_yaml", lambda path: {})
    monkeypatch.setattr(MODULE, "validate_config", lambda data: None)
    monkeypatch.setattr(MODULE, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0))

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
                ),
                stderr="",
            )
        if "OPENCLASH_HEALTH_CHECK=1" in command:
            raise subprocess.CalledProcessError(1, command)
        if "OPENCLASH_ROLLBACK=1" in command:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(MODULE, "ssh_command", fake_ssh)
    monkeypatch.setattr(MODULE.time, "sleep", lambda seconds: None)
    with pytest.raises(MODULE.ConfigError, match="ROLLBACK_FAILED"):
        MODULE.deploy(
            local_file,
            host="router.invalid",
            remote_name=None,
            core_path="/etc/openclash/core/clash_meta",
            activate=True,
        )


def test_deploy_blocks_before_upload_when_active_path_read_fails(tmp_path, monkeypatch) -> None:
    local_file = tmp_path / "openclash.yaml"
    local_file.write_text("proxies: []\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "load_yaml", lambda path: {})
    monkeypatch.setattr(MODULE, "validate_config", lambda data: None)
    uploads: list[list[str]] = []
    monkeypatch.setattr(MODULE, "run", lambda cmd, **kwargs: uploads.append(cmd))

    def failed_state_read(host: str, command: str, *, capture: bool = False):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(MODULE, "ssh_command", failed_state_read)
    with pytest.raises(MODULE.ConfigError, match="REMOTE_ACTIVE_CONFIG_PATH_READ_FAILED"):
        MODULE.deploy(
            local_file,
            host="router.invalid",
            remote_name=None,
            core_path="/etc/openclash/core/clash_meta",
            activate=True,
        )
    assert uploads == []


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


def test_v2_challenge_and_exact_manual_overrides() -> None:
    challenge = MODULE.classify_service_evidence(
        "gpt",
        http_evidence(403, body="Cloudflare cf-chl verify you are human", host="chatgpt.com"),
        http_evidence(404, host="cdn.oaistatic.com"),
    )
    assert challenge == "CHALLENGE_UNKNOWN"
    assert MODULE.apply_manual_override("gpt", "🇯🇵日本aws高速02", challenge) == {
        "raw_result": "CHALLENGE_UNKNOWN",
        "override": "MANUAL_OVERRIDE_PASS",
        "final_result": "MANUAL_OVERRIDE_PASS",
    }

    assert MODULE.manual_override_for("gemini", "🇺🇸美国-住宅") == "MANUAL_OVERRIDE_FAIL"
    assert MODULE.manual_override_for("gemini", "美国迈阿密-hy2") == "MANUAL_OVERRIDE_PASS"
    assert MODULE.manual_override_for("gemini", "🇺🇸美国拉斯维加斯-hy2") == "MANUAL_OVERRIDE_PASS"
    assert MODULE.manual_override_for("gemini", "🇺🇸美国-住宅-备用") is None
    assert MODULE.classify_service_evidence(
        "disney", http_evidence(401), http_evidence(404)
    ) == "AUTH_UNKNOWN"


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
            gpt=service_result("PASS"),
            gemini=service_result("PASS"),
            disney=service_result("PASS"),
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
        probe_node(new_pass, gpt=service_result("PASS")),
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

    assert existing_unknown in selections["gpt"]["automatic"]
    assert transport_lkg in selections["gpt"]["automatic"]
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
    assert len(generated_groups) == 12
    assert generated_groups["GPT自动"]["proxies"] == selections["gpt"]["automatic"]
    assert generated_groups["GPT手动"]["proxies"] == [
        "GPT自动",
        *selections["gpt"]["automatic"],
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
    assert selections["gpt"]["automatic"] == [anchor]
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


def test_v2_empty_service_group_blocks() -> None:
    name = "🇯🇵only-node"
    state = {"schema_version": 1, "updated_at": "old", "nodes": {}}
    with pytest.raises(MODULE.ConfigError, match="BLOCKED_NO_LKG_GPT_NODES"):
        MODULE.merge_lkg_results(
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
    assert first["services"]["gpt"]["final_result"] == "MANUAL_OVERRIDE_PASS"
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


def test_wait_for_openclash_running_polls_until_success(monkeypatch) -> None:
    """Test: running succeeds on 3rd second - should not wait full 15 seconds."""
    call_count = 0

    def counting_ssh(host: str, command: str, *, capture: bool = False) -> None:
        nonlocal call_count
        call_count += 1
        if "/etc/init.d/openclash running" in command:
            if call_count < 3:  # Fail first 2 times
                raise subprocess.CalledProcessError(1, command)
            # Succeed on 3rd call
        return None

    monkeypatch.setattr(MODULE, "ssh_command", counting_ssh)
    monkeypatch.setattr(MODULE.time, "sleep", lambda seconds: None)

    # Should succeed on 3rd attempt (after 2 failures)
    MODULE.wait_for_openclash_running("root@192.168.10.1", max_wait_seconds=15)

    # Verify: exactly 3 calls (2 failures + 1 success)
    assert call_count == 3, f"Expected 3 calls, got {call_count}"


def test_wait_for_openclash_running_times_out_after_15_seconds(monkeypatch) -> None:
    """Test: running fails for 15 seconds - should raise ConfigError."""
    call_count = 0

    def always_fail_ssh(host: str, command: str, *, capture: bool = False) -> None:
        nonlocal call_count
        call_count += 1
        if "/etc/init.d/openclash running" in command:
            raise subprocess.CalledProcessError(1, command)
        return None

    monkeypatch.setattr(MODULE, "ssh_command", always_fail_ssh)
    monkeypatch.setattr(MODULE.time, "sleep", lambda seconds: None)

    # Should fail after 15 attempts (one per second)
    with pytest.raises(MODULE.ConfigError, match="OpenClash not running after 15 seconds"):
        MODULE.wait_for_openclash_running("root@192.168.10.1", max_wait_seconds=15)

    # Verify: at least 15 calls (could be 16 due to final check)
    assert call_count >= 15, f"Expected at least 15 calls, got {call_count}"
