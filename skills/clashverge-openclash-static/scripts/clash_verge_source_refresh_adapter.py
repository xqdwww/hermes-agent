#!/usr/bin/env python3
"""Authenticated loopback bridge for the custom Clash Verge source-only mode."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml


APP_PORT = 33331
PORT = 33332
BASE_URL = f"http://127.0.0.1:{PORT}/commands"
SUCCESS = {"SUCCESS_CHANGED", "SUCCESS_NOT_MODIFIED"}


def emit(outcome: str, **fields: Any) -> None:
    print(json.dumps({"outcome": outcome, **fields}, ensure_ascii=False, sort_keys=True))


def endpoint(path: str, port: int) -> str:
    return f"http://127.0.0.1:{port}/commands{path}"


def post(
    path: str,
    token: str,
    body: dict[str, Any],
    timeout: float = 10,
    port: int = PORT,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        endpoint(path, port),
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    payload = json.loads(response.read().decode())
    return response.status, payload


def ready(token: str, port: int = PORT) -> bool:
    request = urllib.request.Request(
        endpoint("/source-refresh-ready", port),
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=1) as response:
            return response.status == 200 and json.loads(response.read().decode()).get("outcome") == "READY"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def port_open(port: int = APP_PORT) -> bool:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def load_active_profile(profiles_path: Path, requested_uid: str) -> tuple[dict[str, Any], Path]:
    profiles = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    if not isinstance(profiles, dict) or profiles.get("current") != requested_uid:
        raise ValueError("FAIL_PROFILE_NOT_FOUND")
    matches = [
        item
        for item in profiles.get("items", [])
        if isinstance(item, dict)
        and item.get("uid") == requested_uid
        and item.get("type") == "remote"
        and item.get("url")
        and item.get("file")
    ]
    if len(matches) != 1:
        raise ValueError("FAIL_PROFILE_NOT_FOUND")
    return matches[0], profiles_path.parent / "profiles" / str(matches[0]["file"])


def source_identity(uid: str, url: str) -> str:
    return hashlib.sha256(uid.encode() + b"\0" + url.encode()).hexdigest()


def safe_read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def restore(backups: dict[Path, bytes | None]) -> None:
    for path, data in backups.items():
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)


def prepare_helper_home(app_home: Path, staging_dir: Path) -> Path:
    helper_home = Path(tempfile.mkdtemp(prefix="source-refresh-helper-", dir=staging_dir))
    helper_home.chmod(0o700)
    for name in (
        "profiles.yaml",
        "verge.yaml",
        "config.yaml",
        "clash-verge.yaml",
        "dns_config.yaml",
        "geoip.dat",
        "geosite.dat",
        "Country.mmdb",
    ):
        source = app_home / name
        if source.is_file():
            shutil.copy2(source, helper_home / name)
    profiles = app_home / "profiles"
    if not profiles.is_dir():
        raise ValueError("FAIL_PROFILE_NOT_FOUND")
    shutil.copytree(profiles, helper_home / "profiles")
    return helper_home


def commit_source_files(
    live_profile: Path,
    helper_profile: Path,
    live_profiles: Path,
    helper_profiles: Path,
    backups: dict[Path, bytes | None],
) -> None:
    if safe_read(live_profile) != backups[live_profile] or safe_read(live_profiles) != backups[live_profiles]:
        raise ValueError("FAIL_CONCURRENT_SOURCE_CHANGE")
    updated = {
        live_profile: helper_profile.read_bytes(),
        live_profiles: helper_profiles.read_bytes(),
    }
    temporaries: list[Path] = []
    try:
        for path, data in updated.items():
            temporary = path.with_name(f".{path.name}.source-refresh-{secrets.token_hex(8)}")
            temporaries.append(temporary)
            temporary.write_bytes(data)
            temporary.chmod(0o600)
            os.replace(temporary, path)
    except OSError:
        restore(backups)
        raise ValueError("FAIL_SAVE") from None
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)


def verify_private_file(path: Path, expected_hash: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError("FAIL_SAVE")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("FAIL_SAVE")


def source_refresh_port() -> int:
    try:
        port = int(os.environ.get("CLASH_VERGE_SOURCE_REFRESH_PORT", str(PORT)))
    except ValueError as error:
        raise ValueError("FAIL_ADAPTER_PORT_INVALID") from error
    if not 1024 <= port <= 65535 or port == APP_PORT:
        raise ValueError("FAIL_ADAPTER_PORT_INVALID")
    return port


def source_refresh_binary() -> Path | None:
    configured = os.environ.get("CLASH_VERGE_SOURCE_REFRESH_BINARY")
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.append(hermes_home / "bin" / "clash-verge-source-refresh")
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    return None


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if request.get("protocol_version") != 1 or request.get("action") != "update_profile_source":
            raise ValueError("FAIL_PROTOCOL")
        uid = str(request["profile_uid"])
        profiles_path = Path(request["profiles_path"]).expanduser().resolve()
        effective_path = Path(request["effective_path"]).expanduser().resolve()
        staging_dir = Path(request["snapshot_staging_dir"]).expanduser().resolve()
        staging_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(staging_dir, 0o700)
        app_home = profiles_path.parent
        profile, profile_path = load_active_profile(profiles_path, uid)
        identity = source_identity(uid, str(profile["url"]))
        backups = {path: safe_read(path) for path in (profiles_path, profile_path)}
        helper_home = prepare_helper_home(app_home, staging_dir)
        helper_profiles_path = helper_home / "profiles.yaml"
        helper_profile_path = helper_home / "profiles" / profile_path.name
        token_path = helper_home / ".source-refresh-adapter-token"
        bridge_port = source_refresh_port()
        was_running = port_open(APP_PORT)
        bridge_running = port_open(bridge_port)
        process: subprocess.Popen[bytes] | None = None
        launched = False
        refresh_attempted = False
        source_committed = False
        snapshot_artifacts: list[Path] = []

        if bridge_running:
            emit("FAIL_ADAPTER_PORT_IN_USE", app_state_before="RUNNING" if was_running else "STOPPED")
            return 0
        binary = source_refresh_binary()
        if binary is None:
            emit(
                "FAIL_ADAPTER_BINARY_MISSING",
                app_state_before="RUNNING" if was_running else "STOPPED",
            )
            return 0
        env = os.environ.copy()
        env["CLASH_VERGE_SOURCE_REFRESH_MODE"] = "1"
        env["CLASH_VERGE_SOURCE_REFRESH_HOME"] = str(helper_home)
        env["CLASH_VERGE_SOURCE_REFRESH_PORT"] = str(bridge_port)
        process = subprocess.Popen(
            [str(binary)],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        launched = True

        deadline = time.monotonic() + 30
        token = ""
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                break
            if token_path.is_file() and stat.S_IMODE(token_path.stat().st_mode) == 0o600:
                token = token_path.read_text(encoding="ascii")
                if ready(token, bridge_port):
                    break
            time.sleep(0.1)
        else:
            emit("FAIL_TIMEOUT", app_state_before="RUNNING" if was_running else "STOPPED")
            return 0
        if not token or not ready(token, bridge_port):
            emit("FAIL_TRANSPORT", app_state_before="RUNNING" if was_running else "STOPPED")
            return 0

        nonce = secrets.token_urlsafe(24)
        refresh_attempted = True
        status, response = post(
            "/update-profile-source",
            token,
            {
                "profile_uid": uid,
                "expected_profile_identity": identity,
                "request_nonce": nonce,
            },
            timeout=120,
            port=bridge_port,
        )
        if response.get("request_nonce") != nonce:
            emit("FAIL_NONCE_MISMATCH")
            return 0
        outcome = str(response.get("outcome", "FAIL_TRANSPORT"))
        if status != 200 or outcome not in SUCCESS:
            emit(outcome)
            return 0
        snapshot_path = Path(str(response.get("enhanced_snapshot_path", ""))).resolve()
        snapshot_artifacts.append(snapshot_path)
        expected_snapshot_hash = str(response.get("enhanced_snapshot_hash", ""))
        if snapshot_path.parent != helper_home or not snapshot_path.name.startswith(".source-refresh-snapshot-"):
            emit("FAIL_SAVE")
            return 0
        verify_private_file(snapshot_path, expected_snapshot_hash)
        commit_source_files(
            profile_path,
            helper_profile_path,
            profiles_path,
            helper_profiles_path,
            backups,
        )
        source_committed = True
        staged_snapshot = staging_dir / snapshot_path.name
        snapshot_artifacts.append(staged_snapshot)
        if staged_snapshot.exists():
            raise ValueError("FAIL_SAVE")
        shutil.copyfile(snapshot_path, staged_snapshot)
        staged_snapshot.chmod(0o600)
        verify_private_file(staged_snapshot, expected_snapshot_hash)
        snapshot_path.unlink()
        emit(
            outcome,
            profile_identity=response.get("profile_identity"),
            source_identity_verified=response.get("source_identity_verified") is True,
            content_hash_before=response.get("content_hash_before"),
            content_hash_after=response.get("content_hash_after"),
            parsed_node_count_before=response.get("parsed_node_count_before"),
            parsed_node_count_after=response.get("parsed_node_count_after"),
            download_path_used=response.get("download_path_used"),
            enhanced_snapshot_path=str(staged_snapshot),
            enhanced_snapshot_hash=expected_snapshot_hash,
            enhanced_snapshot_node_count=response.get("enhanced_snapshot_node_count"),
            started_at=response.get("started_at"),
            completed_at=response.get("completed_at"),
            request_nonce=nonce,
            app_state_before="RUNNING" if was_running else "STOPPED",
            temporary_app_started=launched,
        )
        return 0
    except (KeyError, OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        outcome = str(error) if str(error).startswith("FAIL_") else "FAIL_TRANSPORT"
        emit(outcome)
        return 0
    finally:
        if "launched" in locals() and launched and "token" in locals() and token:
            shutdown_nonce = secrets.token_urlsafe(24)
            try:
                post(
                    "/source-refresh-shutdown",
                    token,
                    {"request_nonce": shutdown_nonce},
                    timeout=3,
                    port=bridge_port,
                )
            except Exception:
                pass
            if process is not None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
        if "refresh_attempted" in locals() and refresh_attempted and not source_committed:
            for artifact in snapshot_artifacts:
                artifact.unlink(missing_ok=True)
        if "helper_home" in locals():
            shutil.rmtree(helper_home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
