from __future__ import annotations

import importlib.util
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
