#!/usr/bin/env python3
"""Snapshot-bound Antigravity actual-use probing for Gemini nodes.

The probe deliberately keeps agy output in memory and records only the
snapshot-bound, route-attributed result fields consumed by the OpenClash
selection workflow.
"""

from __future__ import annotations

import concurrent.futures as futures
import datetime as dt
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
import uuid


PROBE_METHOD_VERSION = "antigravity_inference"
DEFAULT_HOST = "root@192.168.10.1"
DEFAULT_CORE_PATH = "/etc/openclash/core/clash_meta"
DEFAULT_AGY_COMMAND = "agy"
MAX_WORKERS = 3
REMOTE_LISTENER_PORT_BASE = 23000
AGY_PROCESS_TIMEOUT_SECONDS = 55
AGY_PRINT_TIMEOUT = "45s"


def _raise(skill: Any, message: str) -> None:
    error_type = getattr(skill, "ConfigError", RuntimeError)
    raise error_type(message)


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


_JSON_RESPONSE_KEYS = (
    "response",
    "result",
    "output",
    "text",
    "content",
    "message",
    "data",
    "payload",
)
_JSON_SUCCESS_STATUSES = {"SUCCESS", "SUCCEEDED", "COMPLETED", "OK"}


def _json_candidates(stdout: str) -> Iterable[Any]:
    """Yield JSON objects from object output or newline-delimited output."""

    complete = stdout.strip()
    if complete:
        try:
            yield json.loads(complete)
        except (TypeError, ValueError):
            pass
    for line in reversed(stdout.splitlines()):
        try:
            yield json.loads(line)
        except (TypeError, ValueError):
            continue


def _json_envelopes(value: Any, *, depth: int = 0) -> Iterable[Mapping[str, Any]]:
    if depth > 4:
        return
    if isinstance(value, Mapping):
        yield value
        for key in _JSON_RESPONSE_KEYS:
            child = value.get(key)
            if isinstance(child, (Mapping, list)):
                yield from _json_envelopes(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (Mapping, list)):
                yield from _json_envelopes(child, depth=depth + 1)


def _json_response_contains_marker(value: Any, marker: str, *, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if isinstance(value, str):
        return marker in value
    if isinstance(value, Mapping):
        return any(
            key in value
            and _json_response_contains_marker(value[key], marker, depth=depth + 1)
            for key in _JSON_RESPONSE_KEYS
        )
    if isinstance(value, list):
        return any(
            _json_response_contains_marker(child, marker, depth=depth + 1)
            for child in value
        )
    return False


def _json_envelope_is_success(envelope: Mapping[str, Any]) -> bool:
    status = str(envelope.get("status", "")).upper()
    if status in _JSON_SUCCESS_STATUSES:
        return True
    return (
        str(envelope.get("type", "")).lower() == "result"
        and str(envelope.get("subtype", "")).lower() in {"success", "completed"}
        and envelope.get("is_error") is not True
    )


def _json_envelope_is_error(envelope: Mapping[str, Any]) -> bool:
    status = str(envelope.get("status", "")).upper()
    if status in {"ERROR", "FAILED", "FAILURE"}:
        return True
    return envelope.get("is_error") is True or (
        str(envelope.get("type", "")).lower() == "result"
        and str(envelope.get("subtype", "")).lower() in {"error", "failed"}
    )


def parse_cli(stdout: str, stderr: str, marker: str) -> tuple[str, str | None]:
    """Classify agy output without returning or storing response content."""

    envelopes = [
        envelope
        for candidate in _json_candidates(stdout)
        for envelope in _json_envelopes(candidate)
    ]

    text = "\n".join((stdout, stderr))
    if any(
        _json_envelope_is_success(envelope)
        and _json_response_contains_marker(envelope, marker)
        for envelope in envelopes
    ):
        return "PASS", None

    lower = text.lower()
    if (
        "user location is not supported" in lower
        or "failed_precondition" in lower
        or "failed precondition" in lower
    ):
        return "REGION_BLOCKED", "FAIL_REGION"
    if (
        "unauthenticated" in lower
        or "authentication" in lower
        or "login required" in lower
        or "login" in lower
    ):
        return "UNKNOWN", "AUTHENTICATION_REQUIRED"
    if (
        "resource_exhausted" in lower
        or "rate limit" in lower
        or "quota" in lower
    ):
        return "UNKNOWN", "ACCOUNT_OR_RATE_LIMIT"
    if (
        "timed out" in lower
        or "timeout" in lower
        or "transport" in lower
        or "connection reset" in lower
    ):
        return "UNKNOWN", "TRANSPORT_FAILED"
    if any(_json_envelope_is_error(envelope) for envelope in envelopes):
        return "UNKNOWN", "CLI_ERROR"
    return "UNKNOWN", "UNKNOWN"


def _safe_reason_value(value: Any, fallback: str) -> str:
    text = str(value)
    if 0 < len(text) <= 64 and all(char.isalnum() or char == "_" for char in text):
        return text
    return fallback


def _calibration_failure_message(attempts: Sequence[Mapping[str, Any]]) -> str:
    """Return a structured, content-free reason for calibration failure."""

    safe_attempts = [
        {
            "result": _safe_reason_value(attempt.get("result"), "UNKNOWN"),
            "error_category": _safe_reason_value(
                attempt.get("error_category"), "UNKNOWN"
            ),
            "marker_verified": attempt.get("marker_verified") is True,
            "route_confirmed": attempt.get("route_confirmed") is True,
        }
        for attempt in attempts
    ]
    details = json.dumps(
        {"attempts": safe_attempts},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "STOP_GEMINI_ACTUAL_CALIBRATION_FAILED:" + details


def build_agy_command(
    agy_command: str,
    marker: str,
    *,
    model: str | None = None,
) -> list[str]:
    """Build an agy invocation while leaving model selection to agy by default."""

    command = shlex.split(str(agy_command))
    if not command:
        raise ValueError("--agy-command must not be empty")
    result = [
        *command,
        "-p",
        "Reply with exactly " + marker,
    ]
    if model is not None:
        if not str(model).strip():
            raise ValueError("--model must not be empty")
        result.extend(["--model", str(model)])
    result.extend(
        [
            "--effort",
            "low",
            "--output-format",
            "json",
            "--print-timeout",
            AGY_PRINT_TIMEOUT,
        ]
    )
    return result


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _start_listener_tunnel(
    host: str,
    remote_ports: Sequence[int],
) -> tuple[subprocess.Popen[Any], list[int]]:
    """Forward every remote sidecar listener to a local loopback port."""

    local_ports = [_reserve_loopback_port() for _ in remote_ports]
    command = [
        "ssh",
        "-N",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ExitOnForwardFailure=yes",
    ]
    for local_port, remote_port in zip(local_ports, remote_ports):
        command.extend(
            [
                "-L",
                f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}",
            ]
        )
    command.append(host)
    tunnel = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    time.sleep(0.2)
    if tunnel.poll() is not None:
        try:
            tunnel.wait(timeout=2)
        except subprocess.TimeoutExpired:
            tunnel.kill()
            tunnel.wait(timeout=2)
        raise RuntimeError("STOP_GEMINI_ACTUAL_LISTENER_TUNNEL_FAILED")
    return tunnel, local_ports


def _stop_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class _ConnectionWatcher:
    """Collect CloudCode hosts attributed to exact sidecar proxy chains."""

    def __init__(self, skill: Any, controller_port: int, node_names: Sequence[str]):
        self._skill = skill
        self._controller_port = controller_port
        self._node_names = set(node_names)
        self._seen: dict[str, set[str]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def clear(self, node_name: str) -> None:
        with self._lock:
            self._seen.pop(node_name, None)

    def _watch(self) -> None:
        while not self._stop.wait(0.15):
            try:
                connections = self._skill.controller_json_request(
                    self._controller_port,
                    "/connections",
                    timeout=0.5,
                ).get("connections", [])
                with self._lock:
                    for connection in connections:
                        if not isinstance(connection, dict):
                            continue
                        metadata = connection.get("metadata", {})
                        host = str(metadata.get("host", "")) if isinstance(metadata, dict) else ""
                        if not host:
                            continue
                        for chain_name in connection.get("chains", []):
                            if chain_name in self._node_names:
                                self._seen.setdefault(str(chain_name), set()).add(host)
            except Exception:
                # Controller polling is best-effort; attribution is required
                # by the result classification below.
                continue

    def has_cloudcode(self, node_name: str) -> bool:
        with self._lock:
            return any("cloudcode" in host.lower() for host in self._seen.get(node_name, set()))

    def wait_for_cloudcode(self, node_name: str, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if self.has_cloudcode(node_name):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.1, remaining))


def _verify_controller_nodes(
    skill: Any,
    controller_port: int,
    node_names: Sequence[str],
) -> None:
    payload = skill.controller_json_request(
        controller_port,
        "/proxies",
        timeout=2,
    )
    raw = payload.get("proxies") if isinstance(payload, dict) else None
    available = raw if isinstance(raw, dict) else payload
    if not isinstance(available, dict):
        _raise(skill, "STOP_GEMINI_ACTUAL_CONTROLLER_IDENTITY_MISSING")
    missing = [name for name in node_names if name not in available]
    if missing:
        _raise(
            skill,
            "STOP_GEMINI_ACTUAL_CONTROLLER_IDENTITY_MISSING:" + ",".join(missing),
        )


def _snapshot_nodes(
    skill: Any,
    source_snapshot: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest, payload_path = skill.verify_source_snapshot(source_snapshot)
    source = skill.load_yaml(payload_path)
    proxies = skill.static_proxy_objects(source)
    proxy_by_name = {
        str(proxy["name"]): proxy for proxy in proxies if isinstance(proxy, dict)
    }
    rows = manifest.get("nodes")
    if not isinstance(rows, list) or not rows:
        _raise(skill, "STOP_GEMINI_ACTUAL_SNAPSHOT_IDENTITY_INVALID")
    row_by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            _raise(skill, "STOP_GEMINI_ACTUAL_SNAPSHOT_IDENTITY_INVALID")
        name = str(row.get("exact_node_name") or "")
        node_id = str(row.get("exact_node_id") or "")
        if not name or not node_id or name in row_by_name or name not in proxy_by_name:
            _raise(skill, "STOP_GEMINI_ACTUAL_SNAPSHOT_IDENTITY_INVALID")
        row_by_name[name] = row
    if manifest.get("node_count", len(row_by_name)) != len(row_by_name):
        _raise(skill, "STOP_GEMINI_ACTUAL_SNAPSHOT_IDENTITY_INVALID")
    if not str(manifest.get("source_snapshot_id") or "") or not str(
        manifest.get("source_hash") or ""
    ):
        _raise(skill, "STOP_GEMINI_ACTUAL_SNAPSHOT_IDENTITY_INVALID")
    return manifest, row_by_name, proxy_by_name


def _resolve_names(
    skill: Any,
    row_by_name: Mapping[str, dict[str, Any]],
    calibration_nodes: Sequence[str],
    target_nodes: Sequence[str] | None,
) -> tuple[list[str], list[str], list[str]]:
    calibration = [str(name) for name in calibration_nodes]
    if not calibration or len(calibration) != len(set(calibration)):
        _raise(skill, "STOP_GEMINI_ACTUAL_CALIBRATION_NODES_INVALID")
    if any(name not in row_by_name for name in calibration):
        _raise(skill, "STOP_GEMINI_ACTUAL_CALIBRATION_NODE_UNKNOWN")
    if target_nodes is None:
        targets = list(row_by_name)
    else:
        targets = [str(name) for name in target_nodes]
        if not targets or len(targets) != len(set(targets)):
            _raise(skill, "STOP_GEMINI_ACTUAL_TARGET_NODES_INVALID")
        if any(name not in row_by_name for name in targets):
            _raise(skill, "STOP_GEMINI_ACTUAL_TARGET_NODE_UNKNOWN")
    needed = _ordered_unique([*calibration, *targets])
    return calibration, targets, needed


def _build_sidecar_config(
    skill: Any,
    row_by_name: Mapping[str, dict[str, Any]],
    proxy_by_name: Mapping[str, dict[str, Any]],
    needed_names: Sequence[str],
) -> tuple[dict[str, Any], dict[str, int]]:
    proxies = [proxy_by_name[name] for name in needed_names]
    config = skill.build_probe_config(
        proxies,
        mixed_port=skill.REMOTE_SIDECAR_MIXED_PORT,
        controller_port=skill.REMOTE_SIDECAR_CONTROLLER_PORT,
        interface_name=None,
    )
    config["listeners"] = []
    remote_ports: dict[str, int] = {}
    for offset, name in enumerate(needed_names):
        row = row_by_name[name]
        remote_port = REMOTE_LISTENER_PORT_BASE + offset
        remote_ports[name] = remote_port
        config["listeners"].append(
            {
                "name": "agy-node-" + str(offset),
                "type": "mixed",
                "listen": "127.0.0.1",
                "port": remote_port,
                "proxy": row["exact_node_name"],
            }
        )
    return config, remote_ports


def _probe_one(
    *,
    skill: Any,
    row: Mapping[str, Any],
    local_port: int,
    watcher: _ConnectionWatcher,
    agy_command: str,
    model: str | None,
    process_runner: Callable[..., Any],
) -> dict[str, Any]:
    node_name = str(row["exact_node_name"])
    marker = "AGY-GEMINI-" + uuid.uuid4().hex.upper()
    try:
        command = build_agy_command(agy_command, marker, model=model)
    except ValueError:
        _raise(skill, "STOP_GEMINI_ACTUAL_COMMAND_INVALID")
    environment = os.environ.copy()
    proxy = f"http://127.0.0.1:{local_port}"
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        environment[key] = proxy
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    environment["no_proxy"] = "127.0.0.1,localhost"
    watcher.clear(node_name)

    try:
        completed = process_runner(
            command,
            capture_output=True,
            text=True,
            timeout=AGY_PROCESS_TIMEOUT_SECONDS,
            env=environment,
            check=False,
        )
        parsed_status, parsed_error = parse_cli(
            str(getattr(completed, "stdout", "") or ""),
            str(getattr(completed, "stderr", "") or ""),
            marker,
        )
    except subprocess.TimeoutExpired:
        parsed_status, parsed_error = "UNKNOWN", "TRANSPORT_TIMEOUT"
    except (OSError, subprocess.SubprocessError):
        parsed_status, parsed_error = "UNKNOWN", "TRANSPORT_FAILED"

    route_confirmed = watcher.wait_for_cloudcode(node_name)
    marker_verified = parsed_status == "PASS"
    if parsed_status == "PASS":
        result = "PASS" if route_confirmed else "UNKNOWN"
        error_category = "" if route_confirmed else "ROUTE_UNCONFIRMED"
    elif parsed_status == "REGION_BLOCKED":
        result = "FAIL" if route_confirmed else "UNKNOWN"
        error_category = "FAIL_REGION" if route_confirmed else "REGION_ROUTE_UNCONFIRMED"
    else:
        result = "UNKNOWN"
        error_category = parsed_error or "UNKNOWN"

    return {
        "service": "gemini",
        "exact_node_id": str(row["exact_node_id"]),
        "exact_node_name": node_name,
        "source_snapshot_id": str(row["source_snapshot_id"]),
        "source_hash": str(row["source_hash"]),
        "tested_at": _now(),
        "probe_method_version": PROBE_METHOD_VERSION,
        "method": PROBE_METHOD_VERSION,
        "result": result,
        "status": result,
        "marker_verified": marker_verified,
        "route_confirmed": route_confirmed,
        "error_category": error_category,
        "isolated_listener": f"127.0.0.1:{local_port}",
    }


def run_probe(
    *,
    source_snapshot: Path,
    output: Path,
    calibration_nodes: Sequence[str],
    target_nodes: Sequence[str] | None = None,
    workers: int = 3,
    host: str = DEFAULT_HOST,
    core_path: str = DEFAULT_CORE_PATH,
    agy_command: str = DEFAULT_AGY_COMMAND,
    model: str | None = None,
    skill: Any,
    process_runner: Callable[..., Any] | None = None,
    sidecar_factory: Callable[..., Any] | None = None,
    listener_tunnel_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run calibration then bounded target probing against one frozen snapshot."""

    if workers < 1 or workers > MAX_WORKERS:
        _raise(skill, "--workers must be between 1 and 3")
    manifest, row_by_name, proxy_by_name = _snapshot_nodes(skill, source_snapshot)
    calibration, targets, needed_names = _resolve_names(
        skill,
        row_by_name,
        calibration_nodes,
        target_nodes,
    )
    for name in row_by_name:
        row_by_name[name] = {
            **row_by_name[name],
            "source_snapshot_id": manifest["source_snapshot_id"],
            "source_hash": manifest["source_hash"],
        }
    config, remote_ports = _build_sidecar_config(
        skill,
        row_by_name,
        proxy_by_name,
        needed_names,
    )
    sidecar_factory = sidecar_factory or skill.remote_candidate_sidecar
    process_runner = process_runner or subprocess.run
    listener_tunnel_factory = listener_tunnel_factory or _start_listener_tunnel
    output = output.expanduser().resolve()
    started_at = _now()
    successful_calibration: dict[str, Any] | None = None
    calibration_attempts: list[dict[str, Any]] = []
    target_records: dict[str, dict[str, Any]] = {}
    listener_process: subprocess.Popen[Any] | None = None
    watcher: _ConnectionWatcher | None = None

    with tempfile.TemporaryDirectory(prefix="agy-gemini-actual-") as temporary:
        config_path = Path(temporary) / "sidecar.private.yaml"
        skill.dump_yaml(config, config_path)
        with sidecar_factory(config_path, host=host, core_path=core_path) as sidecar:
            _verify_controller_nodes(skill, sidecar.controller_port, needed_names)
            try:
                try:
                    listener_process, local_ports = listener_tunnel_factory(
                        host,
                        [remote_ports[name] for name in needed_names],
                    )
                except Exception:
                    _raise(skill, "STOP_GEMINI_ACTUAL_LISTENER_TUNNEL_FAILED")
                if len(local_ports) != len(needed_names):
                    _raise(skill, "STOP_GEMINI_ACTUAL_LISTENER_TUNNEL_FAILED")
                local_port_by_name = dict(zip(needed_names, local_ports))
                watcher = _ConnectionWatcher(skill, sidecar.controller_port, needed_names)
                watcher.start()
                for name in calibration:
                    record = _probe_one(
                        skill=skill,
                        row=row_by_name[name],
                        local_port=local_port_by_name[name],
                        watcher=watcher,
                        agy_command=agy_command,
                        model=model,
                        process_runner=process_runner,
                    )
                    calibration_attempts.append(
                        {
                            "exact_node_id": record["exact_node_id"],
                            "exact_node_name": record["exact_node_name"],
                            "result": record["result"],
                            "error_category": record["error_category"],
                            "marker_verified": record["marker_verified"],
                            "route_confirmed": record["route_confirmed"],
                        }
                    )
                    if (
                        record["result"] == "PASS"
                        and record["marker_verified"] is True
                        and record["route_confirmed"] is True
                    ):
                        successful_calibration = record
                        break
                if successful_calibration is None:
                    _raise(skill, _calibration_failure_message(calibration_attempts))

                if successful_calibration["exact_node_name"] in targets:
                    target_records[successful_calibration["exact_node_name"]] = (
                        successful_calibration
                    )
                remaining_targets = [
                    name for name in targets if name not in target_records
                ]
                if remaining_targets:
                    with futures.ThreadPoolExecutor(
                        max_workers=min(workers, len(remaining_targets))
                    ) as pool:
                        pending = {
                            pool.submit(
                                _probe_one,
                                skill=skill,
                                row=row_by_name[name],
                                local_port=local_port_by_name[name],
                                watcher=watcher,
                                agy_command=agy_command,
                                model=model,
                                process_runner=process_runner,
                            ): name
                            for name in remaining_targets
                        }
                        try:
                            for future in futures.as_completed(pending):
                                name = pending[future]
                                target_records[name] = future.result()
                        except Exception:
                            _raise(skill, "STOP_GEMINI_ACTUAL_PROBE_FAILED")
            finally:
                if watcher is not None:
                    watcher.stop()
                _stop_process(listener_process)

    results = [target_records[name] for name in targets]
    report = {
        "schema_version": 1,
        "probe_method_version": PROBE_METHOD_VERSION,
        "service": "gemini",
        "source_snapshot_id": manifest["source_snapshot_id"],
        "source_hash": manifest["source_hash"],
        "status": "COMPLETE",
        "production_unchanged": True,
        "calibration": {
            "status": "PASS",
            "requested_nodes": list(calibration),
            "attempted_nodes": calibration_attempts,
            "passed_node": successful_calibration["exact_node_name"],
        },
        "results": results,
        "started_at": started_at,
        "completed_at": _now(),
    }
    skill.atomic_write_json(report, output, private_parent=True)
    return report


__all__ = [
    "DEFAULT_AGY_COMMAND",
    "DEFAULT_CORE_PATH",
    "DEFAULT_HOST",
    "PROBE_METHOD_VERSION",
    "build_agy_command",
    "parse_cli",
    "run_probe",
]
