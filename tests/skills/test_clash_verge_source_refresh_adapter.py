from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import socket
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml


SCRIPT = (
    Path(__file__).parents[2]
    / "skills"
    / "clashverge-openclash-static"
    / "scripts"
    / "clash_verge_source_refresh_adapter.py"
)
SPEC = importlib.util.spec_from_file_location("clash_verge_source_refresh_adapter", SCRIPT)
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


class FakeProcess:
    def __init__(self) -> None:
        self.waited = False
        self.terminated = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.waited = True
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True


def fixture(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    app_home = tmp_path / "app"
    profile_dir = app_home / "profiles"
    profile_dir.mkdir(parents=True)
    uid = "remote-main"
    url = "https://subscription.invalid/path?fixture=redacted"
    profiles = app_home / "profiles.yaml"
    profiles.write_text(
        yaml.safe_dump(
            {
                "current": uid,
                "items": [
                    {
                        "uid": uid,
                        "type": "remote",
                        "url": url,
                        "file": "remote.yaml",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (profile_dir / "remote.yaml").write_text("proxies:\n- {name: old, type: ss}\n", encoding="utf-8")
    effective = app_home / "clash-verge.yaml"
    effective.write_text("proxies:\n- {name: old, type: ss}\n", encoding="utf-8")
    (app_home / "verge.yaml").write_text("enable_system_proxy: false\nenable_tun_mode: false\n")
    (app_home / "config.yaml").write_text("mode: rule\n")
    request = {
        "protocol_version": 1,
        "action": "update_profile_source",
        "profile_uid": uid,
        "profiles_path": str(profiles),
        "effective_path": str(effective),
        "snapshot_staging_dir": str(tmp_path / "staging"),
    }
    return request, app_home, profile_dir / "remote.yaml"


def run_main(monkeypatch, request: dict[str, object], capsys) -> dict[str, object]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))
    assert ADAPTER.main() == 0
    return json.loads(capsys.readouterr().out)


def test_source_identity_is_bound_to_uid_and_stored_url() -> None:
    one = ADAPTER.source_identity("uid", "https://one")
    assert one == hashlib.sha256(b"uid\0https://one").hexdigest()
    assert one != ADAPTER.source_identity("other", "https://one")
    assert one != ADAPTER.source_identity("uid", "https://two")


def test_active_profile_requires_exact_current_remote_uid(tmp_path) -> None:
    request, app_home, _ = fixture(tmp_path)
    item, path = ADAPTER.load_active_profile(app_home / "profiles.yaml", "remote-main")
    assert item["type"] == "remote" and path.name == "remote.yaml"
    with pytest.raises(ValueError, match="FAIL_PROFILE_NOT_FOUND"):
        ADAPTER.load_active_profile(app_home / "profiles.yaml", "wrong")


def test_private_snapshot_requires_0600_and_hash(tmp_path) -> None:
    path = tmp_path / "snapshot"
    path.write_bytes(b"safe")
    path.chmod(0o600)
    ADAPTER.verify_private_file(path, hashlib.sha256(b"safe").hexdigest())
    path.chmod(0o644)
    with pytest.raises(ValueError, match="FAIL_SAVE"):
        ADAPTER.verify_private_file(path, hashlib.sha256(b"safe").hexdigest())
    path.chmod(0o600)
    with pytest.raises(ValueError, match="FAIL_SAVE"):
        ADAPTER.verify_private_file(path, hashlib.sha256(b"different").hexdigest())


def test_stopped_app_is_temporarily_started_refreshed_and_stopped(tmp_path, monkeypatch, capsys) -> None:
    request, app_home, _ = fixture(tmp_path)
    token = app_home / ".source-refresh-adapter-token"
    token.write_text("token")
    token.chmod(0o600)
    binary = tmp_path / "clash-verge"
    binary.write_text("binary")
    binary.chmod(0o700)
    monkeypatch.setenv("CLASH_VERGE_SOURCE_REFRESH_BINARY", str(binary))
    monkeypatch.setattr(ADAPTER, "port_open", lambda _port: False)
    monkeypatch.setattr(ADAPTER, "ready", lambda _token, _port=ADAPTER.PORT: True)
    process = FakeProcess()
    launch: dict[str, object] = {}

    def popen(*args, **kwargs):
        launch.update(kwargs)
        token.write_text("token")
        token.chmod(0o600)
        return process

    monkeypatch.setattr(ADAPTER.subprocess, "Popen", popen)
    snapshot = app_home / ".source-refresh-snapshot-nonce.yaml"
    snapshot.write_text("proxies:\n- {name: new, type: ss}\n")
    snapshot.chmod(0o600)
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    def post(path, _token, body, timeout=10, port=ADAPTER.PORT):
        if path.endswith("shutdown"):
            return 200, {"outcome": "SHUTTING_DOWN", "request_nonce": body["request_nonce"]}
        return 200, {
            "outcome": "SUCCESS_CHANGED",
            "request_nonce": body["request_nonce"],
            "profile_identity": "masked",
            "source_identity_verified": True,
            "content_hash_before": "a" * 64,
            "content_hash_after": "b" * 64,
            "parsed_node_count_before": 1,
            "parsed_node_count_after": 1,
            "download_path_used": "DIRECT",
            "enhanced_snapshot_path": str(snapshot),
            "enhanced_snapshot_hash": snapshot_hash,
            "enhanced_snapshot_node_count": 1,
            "started_at": "start",
            "completed_at": "end",
        }

    monkeypatch.setattr(ADAPTER, "post", post)
    result = run_main(monkeypatch, request, capsys)
    assert result["outcome"] == "SUCCESS_CHANGED"
    assert result["temporary_app_started"] is True
    assert launch["env"]["CLASH_VERGE_SOURCE_REFRESH_MODE"] == "1"
    assert process.waited is True and process.terminated is False


def test_running_normal_app_reports_missing_bridge_binary(tmp_path, monkeypatch, capsys) -> None:
    request, _app_home, _ = fixture(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "empty-hermes"))
    monkeypatch.setattr(ADAPTER, "port_open", lambda port: port == ADAPTER.APP_PORT)
    monkeypatch.setattr(
        ADAPTER.subprocess,
        "Popen",
        lambda *_a, **_k: pytest.fail("must not launch a second app"),
    )
    result = run_main(monkeypatch, request, capsys)
    assert result == {"app_state_before": "RUNNING", "outcome": "FAIL_ADAPTER_BINARY_MISSING"}


def test_bridge_binary_is_discovered_from_hermes_home(tmp_path, monkeypatch) -> None:
    hermes_home = tmp_path / "hermes"
    binary = hermes_home / "bin" / "clash-verge-source-refresh"
    binary.parent.mkdir(parents=True)
    binary.write_text("binary")
    binary.chmod(0o700)
    monkeypatch.delenv("CLASH_VERGE_SOURCE_REFRESH_BINARY", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    assert ADAPTER.source_refresh_binary() == binary.resolve()


def test_running_normal_app_starts_isolated_source_bridge(tmp_path, monkeypatch, capsys) -> None:
    request, app_home, _ = fixture(tmp_path)
    binary = tmp_path / "clash-verge-source-refresh"
    binary.write_text("binary")
    binary.chmod(0o700)
    monkeypatch.setenv("CLASH_VERGE_SOURCE_REFRESH_BINARY", str(binary))
    monkeypatch.setenv("CLASH_VERGE_SOURCE_REFRESH_PORT", "33332")
    monkeypatch.setattr(ADAPTER, "port_open", lambda port: port == ADAPTER.APP_PORT)
    monkeypatch.setattr(ADAPTER, "ready", lambda _token, _port=33332: True)
    process = FakeProcess()
    launch: dict[str, object] = {}
    token = app_home / ".source-refresh-adapter-token"

    def popen(*args, **kwargs):
        launch.update(kwargs)
        token.write_text("token")
        token.chmod(0o600)
        return process

    monkeypatch.setattr(ADAPTER.subprocess, "Popen", popen)
    snapshot = app_home / ".source-refresh-snapshot-running.yaml"
    snapshot.write_text("proxies:\n- {name: current, type: ss}\n")
    snapshot.chmod(0o600)
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    def post(path, _token, body, timeout=10, port=33332):
        if path.endswith("shutdown"):
            return 200, {"outcome": "SHUTTING_DOWN", "request_nonce": body["request_nonce"]}
        return 200, {
            "outcome": "SUCCESS_NOT_MODIFIED",
            "request_nonce": body["request_nonce"],
            "profile_identity": "masked",
            "source_identity_verified": True,
            "content_hash_before": "a" * 64,
            "content_hash_after": "a" * 64,
            "parsed_node_count_before": 1,
            "parsed_node_count_after": 1,
            "download_path_used": "DIRECT",
            "enhanced_snapshot_path": str(snapshot),
            "enhanced_snapshot_hash": digest,
            "enhanced_snapshot_node_count": 1,
            "started_at": "start",
            "completed_at": "end",
        }

    monkeypatch.setattr(ADAPTER, "post", post)
    result = run_main(monkeypatch, request, capsys)
    assert result["outcome"] == "SUCCESS_NOT_MODIFIED"
    assert result["app_state_before"] == "RUNNING"
    assert result["temporary_app_started"] is True
    assert launch["env"]["CLASH_VERGE_SOURCE_REFRESH_PORT"] == "33332"
    assert process.waited is True and process.terminated is False


@pytest.mark.parametrize("download_path", ["CLASH_PROXY", "SYSTEM_PROXY"])
def test_running_source_adapter_refreshes_without_restarting_app(
    tmp_path, monkeypatch, capsys, download_path
) -> None:
    request, app_home, _ = fixture(tmp_path)
    token = app_home / ".source-refresh-adapter-token"
    token.write_text("token")
    token.chmod(0o600)
    snapshot = app_home / ".source-refresh-snapshot-running.yaml"
    snapshot.write_text("proxies:\n- {name: current, type: ss}\n")
    snapshot.chmod(0o600)
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    monkeypatch.setattr(ADAPTER, "port_open", lambda _port: True)
    monkeypatch.setattr(ADAPTER, "ready", lambda _token, _port=ADAPTER.PORT: True)
    monkeypatch.setattr(
        ADAPTER.subprocess,
        "Popen",
        lambda *_a, **_k: pytest.fail("running source adapter must not be restarted"),
    )

    def post(_path, _token, body, timeout=10, port=ADAPTER.PORT):
        return 200, {
            "outcome": "SUCCESS_NOT_MODIFIED",
            "request_nonce": body["request_nonce"],
            "profile_identity": "masked",
            "source_identity_verified": True,
            "content_hash_before": "a" * 64,
            "content_hash_after": "a" * 64,
            "parsed_node_count_before": 1,
            "parsed_node_count_after": 1,
            "download_path_used": download_path,
            "enhanced_snapshot_path": str(snapshot),
            "enhanced_snapshot_hash": digest,
            "enhanced_snapshot_node_count": 1,
            "started_at": "start",
            "completed_at": "end",
        }

    monkeypatch.setattr(ADAPTER, "post", post)
    result = run_main(monkeypatch, request, capsys)
    assert result["outcome"] == "SUCCESS_NOT_MODIFIED"
    assert result["temporary_app_started"] is False
    assert result["download_path_used"] == download_path


def test_running_app_nonce_mismatch_does_not_overwrite_concurrent_source(tmp_path, monkeypatch, capsys) -> None:
    request, app_home, remote = fixture(tmp_path)
    before = remote.read_bytes()
    token = app_home / ".source-refresh-adapter-token"
    token.write_text("token")
    token.chmod(0o600)
    monkeypatch.setattr(ADAPTER, "port_open", lambda _port: True)
    monkeypatch.setattr(ADAPTER, "ready", lambda _token, _port=ADAPTER.PORT: True)

    def post(_path, _token, _body, timeout=10, port=ADAPTER.PORT):
        remote.write_bytes(b"corrupt")
        return 200, {"outcome": "SUCCESS_CHANGED", "request_nonce": "wrong"}

    monkeypatch.setattr(ADAPTER, "post", post)
    result = run_main(monkeypatch, request, capsys)
    assert result["outcome"] == "FAIL_NONCE_MISMATCH"
    assert remote.read_bytes() != before
    assert remote.read_bytes() == b"corrupt"


def test_receipt_never_contains_subscription_url_or_token(tmp_path, monkeypatch, capsys) -> None:
    request, app_home, _ = fixture(tmp_path)
    monkeypatch.setattr(ADAPTER, "port_open", lambda _port: True)
    token = app_home / ".source-refresh-adapter-token"
    token.write_text("local-secret-token")
    token.chmod(0o600)
    monkeypatch.setattr(ADAPTER, "ready", lambda _token, _port=ADAPTER.PORT: True)
    monkeypatch.setattr(
        ADAPTER,
        "post",
        lambda *_a, **_k: (400, {"outcome": "FAIL_TIMEOUT", "request_nonce": "unused"}),
    )
    result = run_main(monkeypatch, request, capsys)
    text = json.dumps(result)
    assert "subscription.invalid" not in text
    assert "local-secret-token" not in text


def test_transport_is_loopback_only() -> None:
    assert ADAPTER.BASE_URL.startswith("http://127.0.0.1:")
    assert "0.0.0.0" not in ADAPTER.BASE_URL


@pytest.mark.skipif(
    not os.environ.get("CLASH_VERGE_SOURCE_REFRESH_E2E_BINARY"),
    reason="set CLASH_VERGE_SOURCE_REFRESH_E2E_BINARY for the built-app integration test",
)
def test_built_app_local_source_end_to_end(tmp_path) -> None:
    with socket.socket() as check:
        check.settimeout(0.2)
        assert check.connect_ex(("127.0.0.1", ADAPTER.PORT)) != 0

    new_source = b"""proxies:
- name: new-node
  type: ss
  server: 127.0.0.1
  port: 443
  cipher: aes-128-gcm
  password: <fixture-only>
proxy-groups:
- name: PROXY
  type: select
  proxies: [new-node]
rules: [MATCH,PROXY]
"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/yaml")
            self.send_header("Content-Length", str(len(new_source)))
            self.end_headers()
            self.wfile.write(new_source)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request, app_home, remote = fixture(tmp_path)
        profiles_path = app_home / "profiles.yaml"
        profiles = yaml.safe_load(profiles_path.read_text())
        profiles["items"][0]["url"] = f"http://127.0.0.1:{server.server_port}/subscription"
        profiles_path.write_text(yaml.safe_dump(profiles), encoding="utf-8")
        effective = app_home / "clash-verge.yaml"
        effective_before = effective.read_bytes()
        verge_before = (app_home / "verge.yaml").read_bytes()
        config_before = (app_home / "config.yaml").read_bytes()
        env = os.environ.copy()
        env["CLASH_VERGE_SOURCE_REFRESH_BINARY"] = os.environ[
            "CLASH_VERGE_SOURCE_REFRESH_E2E_BINARY"
        ]
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=60,
            env=env,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        receipt = json.loads(completed.stdout)
        assert receipt["outcome"] == "SUCCESS_CHANGED", receipt
        assert receipt["download_path_used"] == "DIRECT"
        assert receipt["app_state_before"] == "STOPPED"
        assert receipt["temporary_app_started"] is True
        assert b"new-node" in remote.read_bytes()
        assert effective.read_bytes() == effective_before
        assert (app_home / "verge.yaml").read_bytes() == verge_before
        assert (app_home / "config.yaml").read_bytes() == config_before
        snapshot = Path(receipt["enhanced_snapshot_path"])
        assert snapshot.is_file() and stat.S_IMODE(snapshot.stat().st_mode) == 0o600
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == receipt["enhanced_snapshot_hash"]
        snapshot.unlink()
        assert not (app_home / ".source-refresh-adapter-token").exists()
        with socket.socket() as check:
            check.settimeout(0.2)
            assert check.connect_ex(("127.0.0.1", ADAPTER.PORT)) != 0
    finally:
        server.shutdown()
        server.server_close()
