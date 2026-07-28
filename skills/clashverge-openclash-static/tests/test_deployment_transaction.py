from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "clashverge_to_openclash.py"
SKILL = Path(__file__).parents[1] / "SKILL.md"
SPEC = importlib.util.spec_from_file_location("deployment_converter", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["deployment_converter"] = MODULE
SPEC.loader.exec_module(MODULE)


def completed(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def remote_state(*, running: bool) -> dict[str, str | bool]:
    return {
        "active_path": "/etc/openclash/config/old.yaml",
        "active_exists": True,
        "enabled": running,
        "running": running,
        "core_running": running,
        "network_artifacts": running,
        "tun_present": running,
    }


def transaction(*, running: bool = True) -> MODULE.DeploymentTransaction:
    return MODULE.DeploymentTransaction(
        remote_path="/etc/openclash/config/new.yaml",
        target_backup="/tmp/target.bak",
        target_absent_marker="/tmp/target.absent",
        original_active_path="/etc/openclash/config/old.yaml",
        original_active_exists=True,
        active_backup="/tmp/active.bak",
        openclash_uci_backup="/tmp/openclash.bak",
        dhcp_uci_backup="/tmp/dhcp.bak",
        firewall_uci_backup="/tmp/firewall.bak",
        service_state_backup="/tmp/service.state",
        network_state_backup="/tmp/network.state",
        core_path="/etc/openclash/core/clash_meta",
        original_enabled=running,
        original_running=running,
        original_core_running=running,
        original_network_artifacts=running,
        original_tun_present=running,
    )


def test_runtime_version_matches_authoritative_skill_frontmatter() -> None:
    match = re.search(r"^version:\s*(\S+)\s*$", SKILL.read_text(), re.MULTILINE)
    assert match is not None
    assert MODULE.SKILL_VERSION == match.group(1)


def test_upload_candidate_never_reads_or_mutates_production(tmp_path: Path) -> None:
    source = tmp_path / "candidate.yaml"
    source.write_text("ignored: true\n")
    commands: list[str] = []

    def fake_ssh(_host: str, command: str, **_kwargs):
        commands.append(command)
        return completed()

    with (
        patch.object(MODULE, "load_yaml", return_value={}),
        patch.object(MODULE, "validate_config"),
        patch.object(MODULE, "run", return_value=completed()),
        patch.object(MODULE, "ssh_command", side_effect=fake_ssh),
        patch.object(
            MODULE,
            "read_remote_openclash_state",
            side_effect=AssertionError("production state must not be read"),
        ),
    ):
        result = MODULE.upload_candidate(
            source, host="router", remote_name="new.yaml", core_path="/core"
        )

    combined = "\n".join(commands)
    assert result.production_path == "/etc/openclash/config/new.yaml"
    assert result.candidate_path.startswith(MODULE.REMOTE_CANDIDATE_DIR + "/")
    assert "OPENCLASH_CANDIDATE_UPLOAD=1" in combined
    assert "uci " not in combined
    assert "/etc/init.d/openclash" not in combined
    assert "OPENCLASH_BACKUP" not in combined


def test_probe_failure_never_enters_activation_transaction(tmp_path: Path) -> None:
    source = tmp_path / "candidate.yaml"
    source.write_text("ignored: true\n")
    candidate = MODULE.UploadedCandidate(
        "/etc/openclash/config/.clashverge-candidates/new.candidate",
        "/etc/openclash/config/new.yaml",
    )
    with (
        patch.object(MODULE, "upload_candidate", return_value=candidate),
        patch.object(
            MODULE,
            "probe_uploaded_candidate",
            side_effect=MODULE.ConfigError("CANDIDATE_PROBE_FAILED"),
        ),
        patch.object(MODULE, "activate_uploaded_candidate") as activate,
    ):
        with pytest.raises(MODULE.ConfigError, match="CANDIDATE_PROBE_FAILED"):
            MODULE.deploy(
                source,
                host="router",
                remote_name="new.yaml",
                core_path="/core",
                activate=True,
            )
    activate.assert_not_called()


def test_no_activate_returns_candidate_without_transaction(tmp_path: Path) -> None:
    source = tmp_path / "candidate.yaml"
    source.write_text("ignored: true\n")
    candidate = MODULE.UploadedCandidate("/candidate", "/production")
    with (
        patch.object(MODULE, "upload_candidate", return_value=candidate),
        patch.object(MODULE, "probe_uploaded_candidate"),
        patch.object(MODULE, "activate_uploaded_candidate") as activate,
    ):
        result = MODULE.deploy(
            source, host="router", remote_name=None, core_path="/core", activate=False
        )
    assert result == "/candidate"
    activate.assert_not_called()


def test_candidate_sidecar_strips_dataplane_features() -> None:
    source = {
        "proxies": [{"name": "n", "type": "ss"}],
        "tun": {"enable": True, "auto-route": True},
        "listeners": [{"name": "unsafe"}],
        "tunnels": [{"network": "tcp"}],
        "routing-mark": 354,
        "dns": {"listen": "0.0.0.0:53"},
    }
    result = MODULE.build_candidate_sidecar_config(source)
    assert result["tun"] == {"enable": False}
    assert result["allow-lan"] is False
    assert result["bind-address"] == "127.0.0.1"
    assert result["dns"].get("listen") is None
    assert "listeners" not in result
    assert "tunnels" not in result
    assert "routing-mark" not in result


def test_sidecar_runs_as_bypass_gid_and_always_cleans(tmp_path: Path) -> None:
    config = tmp_path / "candidate.yaml"
    config.write_text("mixed-port: 17890\n")
    commands: list[str] = []

    class Tunnel:
        def __init__(self, *_args, **_kwargs):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    def fake_ssh(_host: str, command: str, **_kwargs):
        commands.append(command)
        if "CANDIDATE_FINGERPRINT=1" in command:
            return completed("same-production-state\n")
        return completed()

    with (
        patch.object(MODULE, "run", return_value=completed()),
        patch.object(MODULE, "ssh_command", side_effect=fake_ssh),
        patch.object(MODULE, "reserve_loopback_port", side_effect=[27890, 29090]),
        patch.object(MODULE.subprocess, "Popen", Tunnel),
        patch.object(MODULE, "wait_for_controller"),
    ):
        with pytest.raises(RuntimeError, match="injected probe failure"):
            with MODULE.remote_candidate_sidecar(
                config, host="router", core_path="/core"
            ):
                raise RuntimeError("injected probe failure")

    combined = "\n".join(commands)
    assert "meta skgid 65534" in combined
    assert "-c 65534:65534" in combined
    assert "CANDIDATE_SIDECAR_CLEANUP=1" in combined
    assert "sidecar_core=/core" in combined
    assert "/proc/[0-9]*" in combined
    assert 'readlink "$proc_dir/exe"' in combined
    assert '*"$sidecar_config"*) stop_sidecar_pid "$pid"' in combined
    assert combined.count("CANDIDATE_FINGERPRINT=1") == 2


def test_remote_sidecar_cleanup_requires_exact_process_and_path_postconditions() -> None:
    commands: list[str] = []

    def fake_ssh(_host: str, command: str, **_kwargs):
        commands.append(command)
        return completed()

    with patch.object(MODULE, "ssh_command", side_effect=fake_ssh):
        MODULE._stop_remote_sidecar(
            "router",
            "/tmp/clashverge-openclash-sidecar.token",
            "/tmp/clashverge-openclash-sidecar.token.upload",
            "/tmp/clashverge-openclash-sidecar.lock",
            "token",
            "/etc/openclash/core/clash_meta",
        )

    command = commands[0]
    assert "set -e" in command
    assert "sidecar_config=/tmp/clashverge-openclash-sidecar.token/config.yaml" in command
    assert "sidecar_core=/etc/openclash/core/clash_meta" in command
    assert "stop_sidecar_pid" in command
    assert command.count("/proc/[0-9]*") == 2
    assert 'exit 1' in command
    assert "test ! -e /tmp/clashverge-openclash-sidecar.token" in command
    assert "test ! -e /tmp/clashverge-openclash-sidecar.lock" in command


def test_activation_failure_rolls_back_running_state() -> None:
    candidate = MODULE.UploadedCandidate(
        "/etc/openclash/config/.clashverge-candidates/new.candidate",
        "/etc/openclash/config/new.yaml",
    )
    commands: list[str] = []

    def fake_ssh(_host: str, command: str, **_kwargs):
        commands.append(command)
        if "OPENCLASH_ACTIVATION_START=1" in command:
            raise subprocess.CalledProcessError(1, ["ssh"])
        return completed()

    with (
        patch.object(MODULE, "read_remote_openclash_state", return_value=remote_state(running=True)),
        patch.object(MODULE, "ssh_command", side_effect=fake_ssh),
        patch.object(MODULE, "rollback_remote_deployment") as rollback,
    ):
        with pytest.raises(MODULE.ConfigError, match="HEALTH_CHECK_FAILED_ROLLED_BACK"):
            MODULE.activate_uploaded_candidate(candidate, host="router", core_path="/core")
    rollback.assert_called_once()
    saved = rollback.call_args.kwargs["transaction"]
    assert saved.original_running is True
    assert saved.original_active_path == "/etc/openclash/config/old.yaml"
    assert any("[rule4]" in command for command in commands)


@pytest.mark.parametrize(
    ("running", "expected_action"), [(True, "restart"), (False, "start")]
)
def test_activation_success_preserves_running_and_stopped_entry_semantics(
    running: bool, expected_action: str
) -> None:
    candidate = MODULE.UploadedCandidate(
        "/etc/openclash/config/.clashverge-candidates/new.candidate",
        "/etc/openclash/config/new.yaml",
    )
    commands: list[str] = []

    def fake_ssh(_host: str, command: str, **_kwargs):
        commands.append(command)
        return completed()

    with (
        patch.object(
            MODULE, "read_remote_openclash_state", return_value=remote_state(running=running)
        ),
        patch.object(MODULE, "ssh_command", side_effect=fake_ssh),
        patch.object(MODULE, "verify_remote_health") as health,
        patch.object(MODULE, "verify_lan_client_egress") as lan_health,
        patch.object(MODULE, "rollback_remote_deployment") as rollback,
    ):
        result = MODULE.activate_uploaded_candidate(
            candidate, host="router", core_path="/core"
        )

    assert result == "/etc/openclash/config/new.yaml"
    assert f"/etc/init.d/openclash {expected_action}" in "\n".join(commands)
    assert health.call_args.kwargs["expected_config_path"] == candidate.candidate_path
    lan_health.assert_called_once()
    rollback.assert_not_called()


def test_rollback_finally_restores_firewall_dns_and_service_after_copy_failure() -> None:
    commands: list[str] = []

    def fake_ssh(_host: str, command: str, **_kwargs):
        commands.append(command)
        if "dhcp.bak" in command and "/etc/config/dhcp" in command:
            raise subprocess.CalledProcessError(1, ["ssh"])
        return completed()

    with patch.object(MODULE, "ssh_command", side_effect=fake_ssh):
        with pytest.raises(MODULE.ConfigError, match="dhcp_uci"):
            MODULE.rollback_remote_deployment("router", transaction=transaction())

    combined = "\n".join(commands)
    assert "/etc/init.d/firewall reload" in combined
    assert "/etc/init.d/dnsmasq restart" in combined
    assert "/etc/init.d/openclash start" in combined


def test_stopped_rollback_removes_transaction_residue_and_stays_stopped() -> None:
    commands: list[str] = []

    def fake_ssh(_host: str, command: str, **_kwargs):
        commands.append(command)
        return completed()

    with (
        patch.object(MODULE, "ssh_command", side_effect=fake_ssh),
        patch.object(MODULE, "verify_post_rollback_health") as health,
    ):
        MODULE.rollback_remote_deployment("router", transaction=transaction(running=False))

    combined = "\n".join(commands)
    assert "ip -4 route flush table 354" in combined
    assert "ip link delete utun" in combined
    assert "/etc/init.d/openclash disable" in combined
    assert "/etc/init.d/openclash stop" in combined
    health.assert_called_once()


@pytest.mark.parametrize(
    ("failure_marker", "rollback_must_fail"),
    [
        ("OPENCLASH_ROLLBACK_STOP=1", False),  # observed ubus delete failure path
        ("/etc/init.d/firewall reload", True),
        ("/etc/init.d/dnsmasq restart", True),
    ],
)
def test_rollback_finally_continues_after_control_plane_failures(
    failure_marker: str, rollback_must_fail: bool
) -> None:
    commands: list[str] = []

    def fake_ssh(_host: str, command: str, **_kwargs):
        commands.append(command)
        if failure_marker in command:
            raise subprocess.CalledProcessError(1, ["ssh"])
        return completed()

    with (
        patch.object(MODULE, "ssh_command", side_effect=fake_ssh),
        patch.object(MODULE, "verify_post_rollback_health"),
    ):
        if rollback_must_fail:
            with pytest.raises(MODULE.ConfigError):
                MODULE.rollback_remote_deployment("router", transaction=transaction())
        else:
            MODULE.rollback_remote_deployment("router", transaction=transaction())

    combined = "\n".join(commands)
    assert "/etc/init.d/firewall reload" in combined
    assert "/etc/init.d/dnsmasq restart" in combined
    assert "/etc/init.d/openclash start" in combined


def test_stopped_with_stale_dataplane_is_blocked_before_transaction() -> None:
    candidate = MODULE.UploadedCandidate("/candidate", "/etc/openclash/config/new.yaml")
    state = remote_state(running=False)
    state["network_artifacts"] = True
    with (
        patch.object(MODULE, "read_remote_openclash_state", return_value=state),
        patch.object(MODULE, "ssh_command") as ssh,
    ):
        with pytest.raises(MODULE.ConfigError, match="STOPPED_DATAPLANE_INCONSISTENT"):
            MODULE.activate_uploaded_candidate(candidate, host="router", core_path="/core")
    ssh.assert_not_called()


def test_rollback_network_verification_retries_until_final_state_matches() -> None:
    clock = [0.0]
    calls = 0

    def fake_ssh(_host: str, _command: str, **_kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise subprocess.CalledProcessError(1, ["ssh"])
        return completed()

    def advance(seconds: float) -> None:
        clock[0] += seconds

    with (
        patch.object(MODULE, "ssh_command", side_effect=fake_ssh),
        patch.object(MODULE.time, "monotonic", side_effect=lambda: clock[0]),
        patch.object(MODULE.time, "sleep", side_effect=advance),
    ):
        MODULE.verify_rollback_network_state(
            "router",
            transaction(),
            deadline_seconds=5,
            poll_interval_seconds=1,
        )

    assert calls == 3
    assert clock[0] == 2
