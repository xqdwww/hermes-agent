#!/usr/bin/env python3
"""Run the router-installed RegionRestrictionCheck through a candidate sidecar."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import ipaddress
import json
import os
import re
import secrets
import shlex
import subprocess
import tempfile
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple


SCHEMA_VERSION = 3
METHOD_VERSION = "regionrestrictioncheck-sidecar-v8"
EXPECTED_TOOL_VERSION = "1.0.1"
DEFAULT_COMMAND_PATH = "/usr/bin/regioncheck"
DEFAULT_SCRIPT_PATH = "/usr/lib/regionrestrictioncheck/check.sh"
DEFAULT_TIMEOUT_SECONDS = 240
DEFAULT_STABILIZATION_SECONDS = 1.0
CONTROL_ATTRIBUTION_BACKENDS = (
    ("regioncheck-ipify", "https://api64.ipify.org", "plain"),
    ("ipify", "https://api.ipify.org?format=json", "json"),
    ("ifconfig-co", "https://ifconfig.co/json", "json"),
    ("ipinfo", "https://ipinfo.io/json", "json"),
    (
        "cloudflare-trace",
        "https://www.cloudflare.com/cdn-cgi/trace",
        "trace",
    ),
    ("aws-checkip", "https://checkip.amazonaws.com", "plain"),
)
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SERVICE_LABELS = {
    "gpt": "ChatGPT",
    "gemini": "Google Gemini",
    "disney": "Disney+",
}


class ProbeError(RuntimeError):
    """A fail-closed RegionRestrictionCheck orchestration error."""


class ControlAttributionUnavailable(ProbeError):
    """All bounded control exit backends were unavailable."""


class SidecarProxyContext(NamedTuple):
    """One explicitly resolved proxy endpoint in the runner's namespace."""

    runner_scope: Literal["local", "remote"]
    local_proxy_host: str
    local_proxy_port: int
    remote_proxy_host: str
    remote_proxy_port: int
    resolved_proxy_url: str
    selector_group: str
    controller_url: str


def resolve_sidecar_proxy_context(
    *,
    runner_scope: Literal["local", "remote"],
    local_proxy_host: str,
    local_proxy_port: int,
    remote_proxy_host: str,
    remote_proxy_port: int,
    controller_url: str,
    selector_group: str = "PROBE",
) -> SidecarProxyContext:
    if runner_scope not in {"local", "remote"}:
        raise ProbeError("RRC_RUNNER_SCOPE_INVALID")
    for host in (local_proxy_host, remote_proxy_host):
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ProbeError("RRC_PROXY_HOST_NOT_LOOPBACK")
        except ValueError as exc:
            raise ProbeError("RRC_PROXY_HOST_INVALID") from exc
    for port in (local_proxy_port, remote_proxy_port):
        if not 0 < port < 65536:
            raise ProbeError("RRC_PROXY_PORT_INVALID")
    proxy_host, proxy_port = (
        (local_proxy_host, local_proxy_port)
        if runner_scope == "local"
        else (remote_proxy_host, remote_proxy_port)
    )
    return SidecarProxyContext(
        runner_scope=runner_scope,
        local_proxy_host=local_proxy_host,
        local_proxy_port=local_proxy_port,
        remote_proxy_host=remote_proxy_host,
        remote_proxy_port=remote_proxy_port,
        resolved_proxy_url=f"http://{proxy_host}:{proxy_port}",
        selector_group=selector_group,
        controller_url=controller_url,
    )


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def resolve_run_id(
    *,
    resume: bool,
    previous: dict[str, Any] | None = None,
) -> str:
    previous_id = str((previous or {}).get("run_id") or "")
    if resume and re.fullmatch(r"[0-9a-f]{32}", previous_id):
        return previous_id
    return secrets.token_hex(16)


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("openclash_skill", path)
    if spec is None or spec.loader is None:
        raise ProbeError("RRC_SKILL_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def strip_ansi(value: str) -> str:
    return ANSI_RE.sub("", value).replace("\r", "")


def clean_output(value: str) -> list[str]:
    lines: list[str] = []
    for raw in strip_ansi(value).splitlines():
        line = raw.strip()
        if not line or "sleep: invalid number '0.03'" in line:
            continue
        if any(marker in line for marker in ("Telegram", "t.me/", "广告", "推广")):
            continue
        lines.append(line)
    return lines


def extract_service_values(value: str) -> dict[str, str]:
    lines = clean_output(value)
    extracted: dict[str, str] = {}
    for service, label in SERVICE_LABELS.items():
        prefix = label + ":"
        matches = [line.split(":", 1)[1].strip() for line in lines if line.startswith(prefix)]
        if matches:
            extracted[service] = matches[-1]
    return extracted


def normalize_result(service: str, raw: str) -> tuple[str, str]:
    lowered = raw.lower()
    if "failed (network connection)" in lowered or "unable to connect" in lowered:
        return "FAIL_TRANSPORT", "UNKNOWN"
    if "challenge" in lowered or "unknown" in lowered or "page error" in lowered:
        return "UNKNOWN", "UNKNOWN"
    if service == "disney":
        if raw.startswith("Yes"):
            return "SCREEN_PASS", "SCREEN_PASS"
        if "IP Banned" in raw:
            return "FAIL_IP_BANNED", "UNKNOWN"
        if raw.startswith("No") or "not supported" in lowered:
            return "FAIL_REGION", "UNKNOWN"
        return "UNKNOWN", "UNKNOWN"
    if raw.startswith("Yes"):
        return "SCREEN_PASS", "SCREEN_PASS"
    if raw.startswith("No"):
        return "SCREEN_NEGATIVE", "SCREEN_NEGATIVE"
    return "UNKNOWN", "UNKNOWN"


def extract_masked_ip(value: str) -> str | None:
    for line in clean_output(value):
        if "Network Provider:" not in line and "网络为:" not in line:
            continue
        candidates = re.findall(r"\(([^()]*)\)", line)
        if candidates:
            return candidates[-1].strip()
    return None


def masked_ip_matches(full_ip: str, masked_ip: str | None) -> bool:
    if not masked_ip:
        return False
    try:
        parsed = ipaddress.ip_address(full_ip)
    except ValueError:
        return False
    if parsed.version == 4:
        full = full_ip.split(".")
        masked = masked_ip.split(".")
        return len(masked) == 4 and all(
            part in {"*", "x", "X"} or part == full[index]
            for index, part in enumerate(masked)
        )
    normalized = masked_ip.lower().replace("*", "")
    return bool(normalized) and full_ip.lower().startswith(normalized.rstrip(":"))


def is_unattributable_tool_failure(returncode: int, masked_ip: str | None) -> bool:
    return returncode not in {0, 124} and masked_ip is None


def hmac_prefix(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:20]


def append_service_results(
    report: dict[str, Any],
    *,
    manifest: dict[str, Any],
    identities: dict[str, str],
    node_name: str,
    control_exit_hmac: str,
    regioncheck_exit_hmac: str,
    country: str,
    tool: dict[str, Any],
    raw_values: dict[str, str],
) -> None:
    for service, raw in raw_values.items():
        normalized, evidence = normalize_result(service, raw)
        report["results"].append(
            {
                "service": service,
                "exact_node_id": identities[node_name],
                "exact_node_name": node_name,
                "source_snapshot_id": manifest["source_snapshot_id"],
                "source_hash": manifest["source_hash"],
                "exit_ip_hmac": control_exit_hmac,
                "control_exit_ip_hmac": control_exit_hmac,
                "regioncheck_exit_ip_hmac": regioncheck_exit_hmac,
                "regioncheck_exit_ip_hmac_source": (
                    "post_regioncheck_control_same_proxy"
                ),
                "attribution_status": (
                    "ATTRIBUTION_MATCH"
                    if control_exit_hmac
                    and control_exit_hmac == regioncheck_exit_hmac
                    else "ATTRIBUTION_UNAVAILABLE"
                ),
                "exit_country": country,
                "tool_version": tool["tool_version"],
                "tool_sha256": tool["script_sha256"],
                "tested_at": iso_now(),
                "probe_method_version": METHOD_VERSION,
                "raw_screen_result": raw,
                "normalized_result": normalized,
                "result": normalized,
                "evidence_type": evidence,
            }
        )


def append_node_error(
    report: dict[str, Any],
    *,
    manifest: dict[str, Any],
    identities: dict[str, str],
    node_name: str,
    tool: dict[str, Any],
) -> None:
    report["node_errors"].append(
        {
            "exact_node_id": identities[node_name],
            "exact_node_name": node_name,
            "source_snapshot_id": manifest["source_snapshot_id"],
            "source_hash": manifest["source_hash"],
            "tool_version": tool["tool_version"],
            "tool_sha256": tool["script_sha256"],
            "tested_at": iso_now(),
            "probe_method_version": METHOD_VERSION,
            "error": "RRC_EXECUTION_FAILED_NO_ATTRIBUTABLE_RESULTS",
            "evidence_type": "UNKNOWN",
        }
    )


def inspect_tool(skill: Any, host: str) -> dict[str, Any]:
    command = (
        "set -e; c=$(command -v regioncheck); "
        "[ \"$c\" = /usr/bin/regioncheck ]; "
        "s=/usr/lib/regionrestrictioncheck/check.sh; [ -x \"$c\" ]; [ -r \"$s\" ]; "
        "v=$(sed -n \"s/^VER='\\([^']*\\)'.*/\\1/p\" \"$s\" | head -n1); "
        "h=$(sha256sum \"$s\" | awk '{print $1}'); "
        "grep -q -- '-P | --proxy)' \"$s\"; grep -q -- '-R | --region)' \"$s\"; "
        "grep -q -- '-M | --network-type)' \"$s\"; "
        "printf '%s|%s|%s|%s|yes\\n' \"$c\" \"$s\" \"$v\" \"$h\""
    )
    completed = skill.ssh_command(host, command, capture=True)
    fields = (completed.stdout or "").strip().split("|")
    if len(fields) != 5:
        raise ProbeError("STOP_RRC_EXPLICIT_PROXY_UNSUPPORTED")
    command_path, script_path, version, script_sha, proxy = fields
    if version != EXPECTED_TOOL_VERSION or proxy != "yes" or not re.fullmatch(
        r"[0-9a-f]{64}", script_sha
    ):
        raise ProbeError("STOP_RRC_EXPLICIT_PROXY_UNSUPPORTED")
    return {
        "tool_name": "RegionRestrictionCheck",
        "tool_version": version,
        "script_sha256": script_sha,
        "command_path": command_path,
        "script_path": script_path,
        "explicit_proxy_supported": True,
        "tested_at": iso_now(),
    }


def validate_proxy_url(proxy_url: str) -> None:
    parsed = urllib.parse.urlsplit(proxy_url)
    try:
        host = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise ProbeError("RRC_PROXY_URL_INVALID") from exc
    if (
        parsed.scheme != "http"
        or not host.is_loopback
        or port is None
        or not 0 < port < 65536
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ProbeError("RRC_PROXY_URL_INVALID")


def run_in_runner_scope(
    command: list[str],
    *,
    runner_scope: Literal["local", "remote"],
    host: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    if runner_scope == "local":
        runner_command = command
    elif runner_scope == "remote":
        runner_command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            host,
            shlex.join(command) + " </dev/null",
        ]
    else:
        raise ProbeError("RRC_RUNNER_SCOPE_INVALID")
    return subprocess.run(
        runner_command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def control_geo(
    *,
    proxy_url: str,
    runner_scope: Literal["local", "remote"],
    host: str,
    sleep_fn: Any = time.sleep,
) -> tuple[str, str]:
    validate_proxy_url(proxy_url)
    last_error: BaseException | None = None
    for control_attempt in range(2):
        for _backend_id, backend_url, parser in CONTROL_ATTRIBUTION_BACKENDS:
            try:
                completed = run_in_runner_scope(
                    [
                        "curl",
                        "--proxy",
                        proxy_url,
                        "--ipv4",
                        "--no-keepalive",
                        "--header",
                        "Connection: close",
                        "--connect-timeout",
                        "4",
                        "--max-time",
                        "12",
                        "--silent",
                        "--show-error",
                        backend_url,
                    ],
                    runner_scope=runner_scope,
                    host=host,
                    timeout_seconds=15,
                )
                if completed.returncode != 0:
                    raise ProbeError("CONTROL_GEO_TRANSPORT")
                ip, country = parse_control_backend_response(
                    completed.stdout,
                    parser=parser,
                )
                parsed_ip = ipaddress.ip_address(ip)
                if parsed_ip.version != 4 or not parsed_ip.is_global:
                    raise ProbeError("CONTROL_GEO_NOT_PUBLIC_IPV4")
                return ip, country
            except (
                AttributeError, KeyError, TypeError, ValueError,
                json.JSONDecodeError, OSError,
                subprocess.TimeoutExpired, ProbeError,
            ) as exc:
                last_error = exc
        if control_attempt == 0:
            sleep_fn(1)
    raise ControlAttributionUnavailable(
        "CONTROL_ATTRIBUTION_UNAVAILABLE"
    ) from last_error


def parse_control_backend_response(
    output: str,
    *,
    parser: str,
) -> tuple[str, str]:
    if parser == "json":
        payload = json.loads(output)
        return (
            str(payload.get("ip") or payload.get("ip_addr") or ""),
            str(
                payload.get("country")
                or payload.get("country_iso")
                or "UNKNOWN"
            ),
        )
    if parser == "trace":
        match = re.search(r"^ip=([^\r\n]+)$", output, re.MULTILINE)
        return (match.group(1).strip() if match else "", "UNKNOWN")
    if parser == "plain":
        return output.strip(), "UNKNOWN"
    raise ProbeError("CONTROL_GEO_PARSER_INVALID")


def discard_proxy_request(
    *,
    proxy_url: str,
    runner_scope: Literal["local", "remote"],
    host: str,
) -> bool:
    validate_proxy_url(proxy_url)
    try:
        completed = run_in_runner_scope(
            [
                "curl",
                "--proxy",
                proxy_url,
                "--ipv4",
                "--no-keepalive",
                "--header",
                "Connection: close",
                "--connect-timeout",
                "3",
                "--max-time",
                "8",
                "--silent",
                "--show-error",
                "--output",
                "/dev/null",
                "https://www.gstatic.com/generate_204",
            ],
            runner_scope=runner_scope,
            host=host,
            timeout_seconds=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def run_regioncheck(
    host: str,
    timeout_seconds: int,
    *,
    proxy_url: str,
    runner_scope: Literal["local", "remote"],
) -> tuple[int, str]:
    validate_proxy_url(proxy_url)
    try:
        completed = run_in_runner_scope(
            [
                DEFAULT_COMMAND_PATH,
                "-M",
                "4",
                "-R",
                "0",
                "-E",
                "en",
                "-P",
                proxy_url,
            ],
            runner_scope=runner_scope,
            host=host,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return 124, ""
    return completed.returncode, (completed.stdout or "") + "\n" + (completed.stderr or "")


def normalize_regioncheck_values(
    returncode: int,
    output: str,
) -> dict[str, str]:
    raw_values = extract_service_values(output)
    if returncode == 124:
        return {service: "Failed (Network Connection)" for service in SERVICE_LABELS}
    if not all(service in raw_values for service in SERVICE_LABELS):
        return {
            service: raw_values.get(service, "Failed (Error: Unknown)")
            for service in SERVICE_LABELS
        }
    return raw_values


def run_regioncheck_with_transport_retry(
    host: str,
    timeout_seconds: int,
    *,
    proxy_url: str,
    runner_scope: Literal["local", "remote"],
    sleep_fn: Any = time.sleep,
) -> tuple[int, str, dict[str, str]]:
    returncode, output = run_regioncheck(
        host,
        timeout_seconds,
        proxy_url=proxy_url,
        runner_scope=runner_scope,
    )
    raw_values = extract_service_values(output)
    if returncode != 0 or (
        raw_values and all("Network Connection" in raw for raw in raw_values.values())
    ):
        sleep_fn(1)
        returncode, output = run_regioncheck(
            host,
            timeout_seconds,
            proxy_url=proxy_url,
            runner_scope=runner_scope,
        )
    return returncode, output, normalize_regioncheck_values(returncode, output)


def safe_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if re.search(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])", serialized):
        raise ProbeError("RRC_REPORT_CONTAINS_FULL_IP")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def reset_sidecar_connections(
    skill: Any,
    controller_port: int,
    *,
    sleep_seconds: float,
    sleep_fn: Any = time.sleep,
) -> None:
    skill.controller_json_request(
        controller_port,
        "/connections",
        method="DELETE",
    )
    sleep_fn(max(0.0, sleep_seconds))


def selector_readback(skill: Any, controller_port: int, selector_group: str) -> str:
    selector_path = "/proxies/" + urllib.parse.quote(selector_group, safe="")
    payload = skill.controller_json_request(controller_port, selector_path)
    return str(payload.get("now") or "")


def probe_node_with_attribution(
    *,
    skill: Any,
    host: str,
    controller_port: int,
    proxy_context: SidecarProxyContext,
    node_name: str,
    timeout_seconds: int,
    run_key: bytes,
    stabilization_seconds: float,
    sleep_fn: Any = time.sleep,
) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    for attribution_attempt in range(1, 3):
        if not skill.select_probe_node(controller_port, node_name):
            raise ProbeError("STOP_RRC_PROXY_ATTRIBUTION_MISMATCH")
        selected = selector_readback(
            skill,
            controller_port,
            proxy_context.selector_group,
        )
        if selected != node_name:
            raise ProbeError("STOP_RRC_PROXY_ATTRIBUTION_MISMATCH")
        reset_sidecar_connections(
            skill,
            controller_port,
            sleep_seconds=stabilization_seconds,
            sleep_fn=sleep_fn,
        )
        try:
            # This connection is intentionally best-effort and carries no
            # attribution evidence.
            discard_proxy_request(
                proxy_url=proxy_context.resolved_proxy_url,
                runner_scope=proxy_context.runner_scope,
                host=host,
            )
            reset_sidecar_connections(
                skill,
                controller_port,
                sleep_seconds=min(0.25, stabilization_seconds),
                sleep_fn=sleep_fn,
            )
            control_ip, country = control_geo(
                proxy_url=proxy_context.resolved_proxy_url,
                runner_scope=proxy_context.runner_scope,
                host=host,
                sleep_fn=sleep_fn,
            )
            returncode, output, raw_values = run_regioncheck_with_transport_retry(
                host,
                timeout_seconds,
                proxy_url=proxy_context.resolved_proxy_url,
                runner_scope=proxy_context.runner_scope,
                sleep_fn=sleep_fn,
            )
            regioncheck_ip, regioncheck_country = control_geo(
                proxy_url=proxy_context.resolved_proxy_url,
                runner_scope=proxy_context.runner_scope,
                host=host,
                sleep_fn=sleep_fn,
            )
        except ControlAttributionUnavailable:
            return {
                "selector_readback": selected,
                "attribution_attempts": attribution_attempt,
                "attribution_valid": False,
                "status": "ATTRIBUTION_UNAVAILABLE",
                "control_exit_ip_hmac": "",
                "regioncheck_exit_ip_hmac": "",
                "exit_country": "UNKNOWN",
                "returncode": None,
                "output_complete": False,
                "transport_unknown": True,
                "raw_values": {},
                "masked_ip_present": False,
            }
        else:
            control_exit_hmac = hmac_prefix(run_key, control_ip)
            regioncheck_exit_hmac = hmac_prefix(run_key, regioncheck_ip)
            masked = extract_masked_ip(output)
            if masked is None:
                return {
                    "selector_readback": selected,
                    "attribution_attempts": attribution_attempt,
                    "attribution_valid": False,
                    "status": "ATTRIBUTION_UNAVAILABLE",
                    "control_exit_ip_hmac": control_exit_hmac,
                    "regioncheck_exit_ip_hmac": regioncheck_exit_hmac,
                    "regioncheck_exit_ip_hmac_source": (
                        "post_regioncheck_control_same_proxy"
                    ),
                    "exit_country": (
                        country
                        if country and country != "UNKNOWN"
                        else regioncheck_country or "UNKNOWN"
                    ),
                    "returncode": returncode,
                    "output_complete": False,
                    "transport_unknown": True,
                    "raw_values": {},
                    "masked_ip_present": False,
                }
            masked_matches = masked_ip_matches(regioncheck_ip, masked)
            attribution_valid = (
                control_exit_hmac == regioncheck_exit_hmac and masked_matches
            )
            output_complete = all(
                service in extract_service_values(output)
                for service in SERVICE_LABELS
            )
            transport_unknown = (
                returncode == 124
                or is_unattributable_tool_failure(returncode, masked)
                or not output_complete
            )
            last = {
                "selector_readback": selected,
                "attribution_attempts": attribution_attempt,
                "attribution_valid": attribution_valid,
                "status": (
                    "ATTRIBUTION_MATCH"
                    if attribution_valid
                    else "ATTRIBUTION_UNAVAILABLE"
                ),
                "control_exit_ip_hmac": control_exit_hmac,
                "regioncheck_exit_ip_hmac": regioncheck_exit_hmac,
                "regioncheck_exit_ip_hmac_source": (
                    "post_regioncheck_control_same_proxy"
                ),
                "exit_country": (
                    country
                    if country and country != "UNKNOWN"
                    else regioncheck_country or "UNKNOWN"
                ),
                "returncode": returncode,
                "output_complete": output_complete,
                "transport_unknown": transport_unknown,
                "raw_values": raw_values if attribution_valid else {},
                "masked_ip_present": masked is not None,
            }
            if attribution_valid:
                return last
        reset_sidecar_connections(
            skill,
            controller_port,
            sleep_seconds=stabilization_seconds,
            sleep_fn=sleep_fn,
        )
    assert last is not None
    return last


def reusable_node_ids(
    previous: dict[str, Any],
    *,
    manifest: dict[str, Any],
    tool: dict[str, Any],
) -> set[str]:
    if (
        previous.get("schema_version") != SCHEMA_VERSION
        or previous.get("probe_method_version") != METHOD_VERSION
        or previous.get("source_snapshot_id") != manifest["source_snapshot_id"]
        or previous.get("source_hash") != manifest["source_hash"]
        or previous.get("tool", {}).get("tool_version") != tool["tool_version"]
        or previous.get("tool", {}).get("script_sha256") != tool["script_sha256"]
    ):
        return set()
    results_by_id: dict[str, set[str]] = {}
    for result in previous.get("results", []):
        node_id = str(result.get("exact_node_id") or "")
        results_by_id.setdefault(node_id, set()).add(str(result.get("service") or ""))
    reusable: set[str] = set()
    for item in previous.get("node_attempts", []):
        node_id = str(item.get("exact_node_id") or "")
        control_hmac = str(item.get("control_exit_ip_hmac") or "")
        regioncheck_hmac = str(item.get("regioncheck_exit_ip_hmac") or "")
        if (
            item.get("status") == "ATTRIBUTION_MATCH"
            and item.get("attribution_valid") is True
            and item.get("selector_readback") == item.get("exact_node_name")
            and item.get("output_complete") is True
            and control_hmac
            and control_hmac == regioncheck_hmac
            and results_by_id.get(node_id) == set(SERVICE_LABELS)
        ):
            reusable.add(node_id)
    return reusable


def validate_calibration_report(
    path: Path,
    *,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProbeError("RRC_CALIBRATION_REPORT_INVALID") from exc
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("probe_method_version") != METHOD_VERSION
        or payload.get("source_snapshot_id") != manifest["source_snapshot_id"]
        or payload.get("source_hash") != manifest["source_hash"]
        or payload.get("status") != "COMPLETE"
        or payload.get("calibration_status")
        != "PASS_RRC_PROXY_ATTRIBUTION_TWO_NODE_CALIBRATION"
        or payload.get("production_fingerprint_preserved") is not True
        or payload.get("gid_bypass_verified") is not True
    ):
        raise ProbeError("RRC_TWO_NODE_CALIBRATION_REQUIRED")
    return payload


def update_report_counts(report: dict[str, Any]) -> None:
    nodes = report["node_attempts"]
    report["nodes_attempted"] = len(nodes)
    report["nodes_completed"] = len(nodes)
    report["attribution_match"] = sum(
        item.get("status") == "ATTRIBUTION_MATCH" for item in nodes
    )
    report["attribution_unavailable"] = sum(
        item.get("status") == "ATTRIBUTION_UNAVAILABLE" for item in nodes
    )
    report["attribution_mismatch"] = sum(
        item.get("status") == "ATTRIBUTION_MISMATCH" for item in nodes
    )
    report["transport_unknown"] = sum(
        item.get("transport_unknown") is True for item in nodes
    )
    report["newly_tested_records"] = len(nodes) - int(
        report.get("nodes_reused") or 0
    )
    report["unavailable_records"] = report["attribution_unavailable"]


def systemic_attribution_stop_reason(
    node_attempts: list[dict[str, Any]],
) -> str | None:
    unavailable = [
        item
        for item in node_attempts
        if item.get("status") == "ATTRIBUTION_UNAVAILABLE"
    ]
    trailing_unavailable_ids: list[str] = []
    for item in reversed(node_attempts):
        if item.get("status") != "ATTRIBUTION_UNAVAILABLE":
            break
        node_id = str(item.get("exact_node_id") or "")
        if node_id not in trailing_unavailable_ids:
            trailing_unavailable_ids.append(node_id)
    if len(trailing_unavailable_ids) >= 3:
        return "STOP_RRC_CONTROL_ATTRIBUTION_SYSTEMIC_UNAVAILABLE"
    if len(node_attempts) >= 8 and len(unavailable) / len(node_attempts) > 0.25:
        return "STOP_RRC_CONTROL_ATTRIBUTION_SYSTEMIC_UNAVAILABLE"
    return None


def confirm_systemic_attribution_health(
    *,
    skill: Any,
    host: str,
    controller_port: int,
    proxy_context: SidecarProxyContext,
    sentinel_names: list[str],
    timeout_seconds: int,
    run_key: bytes,
    stabilization_seconds: float,
    sleep_fn: Any = time.sleep,
) -> tuple[bool, list[dict[str, Any]]]:
    """Confirm that an unavailable-rate signal is actually system-wide."""
    confirmations: list[dict[str, Any]] = []
    for name in sentinel_names:
        outcome = probe_node_with_attribution(
            skill=skill,
            host=host,
            controller_port=controller_port,
            proxy_context=proxy_context,
            node_name=name,
            timeout_seconds=timeout_seconds,
            run_key=run_key,
            stabilization_seconds=stabilization_seconds,
            sleep_fn=sleep_fn,
        )
        confirmation = {
            key: value
            for key, value in outcome.items()
            if key != "raw_values"
        }
        confirmation["sentinel_name"] = name
        confirmation["completed_at"] = iso_now()
        confirmations.append(confirmation)
        if outcome["status"] == "ATTRIBUTION_MISMATCH":
            raise ProbeError("STOP_RRC_PROXY_ATTRIBUTION_MISMATCH")
        if outcome["status"] == "ATTRIBUTION_MATCH":
            return True, confirmations
    return False, confirmations


def validate_two_node_calibration(report: dict[str, Any]) -> None:
    nodes = report["node_attempts"]
    if any(item.get("status") == "ATTRIBUTION_MISMATCH" for item in nodes):
        raise ProbeError("STOP_RRC_PROXY_ATTRIBUTION_MISMATCH")
    if (
        len(nodes) != 2
        or any(item.get("status") != "ATTRIBUTION_MATCH" for item in nodes)
        or any(item.get("selector_readback") != item.get("exact_node_name") for item in nodes)
        or any(item.get("result_count") != len(SERVICE_LABELS) for item in nodes)
        or len({item.get("control_exit_ip_hmac") for item in nodes}) != 2
    ):
        raise ProbeError("STOP_RRC_TWO_NODE_CALIBRATION_FAILED")
    report["calibration_status"] = (
        "PASS_RRC_PROXY_ATTRIBUTION_TWO_NODE_CALIBRATION"
    )


def require_preserved_production_fingerprint(before: str, after: str) -> None:
    if before != after:
        raise ProbeError("CANDIDATE_SIDECAR_PRODUCTION_STATE_CHANGED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-script", type=Path, required=True)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", default="root@192.168.10.1")
    parser.add_argument("--core-path", default="/etc/openclash/core/clash_meta")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--node-interval", type=float, default=3.0)
    parser.add_argument("--max-nodes", type=int)
    parser.add_argument("--node", action="append", default=[])
    parser.add_argument("--calibration-only", action="store_true")
    parser.add_argument("--calibration-report", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--import-report", type=Path)
    args = parser.parse_args()
    if args.resume and args.import_report is not None:
        raise ProbeError("RRC_RESUME_AND_IMPORT_CONFLICT")

    skill = load_module(args.skill_script.resolve())
    manifest, payload_path = skill.verify_source_snapshot(args.source_snapshot.resolve())
    data = skill.load_yaml(payload_path)
    proxies = skill.static_proxy_objects(data)
    if args.node:
        requested = set(args.node)
        proxies = [proxy for proxy in proxies if str(proxy["name"]) in requested]
        if {str(proxy["name"]) for proxy in proxies} != requested:
            raise ProbeError("RRC_REQUESTED_NODE_NOT_FOUND")
    if args.max_nodes is not None:
        if args.max_nodes < 1:
            raise ProbeError("MAX_NODES_INVALID")
        proxies = proxies[: args.max_nodes]
    calibration_payload: dict[str, Any] | None = None
    if args.calibration_only:
        if len(proxies) != 2 or not args.node:
            raise ProbeError("RRC_TWO_NODE_CALIBRATION_REQUIRES_EXACTLY_TWO_NODES")
    elif len(proxies) > 2:
        if args.calibration_report is None:
            raise ProbeError("RRC_TWO_NODE_CALIBRATION_REQUIRED")
        calibration_payload = validate_calibration_report(
            args.calibration_report.resolve(),
            manifest=manifest,
        )
    identities = {
        str(item["exact_node_name"]): str(item["exact_node_id"])
        for item in manifest["nodes"]
    }
    tool = inspect_tool(skill, args.host)
    config = skill.build_probe_config(
        proxies,
        mixed_port=skill.REMOTE_SIDECAR_MIXED_PORT,
        controller_port=skill.REMOTE_SIDECAR_CONTROLLER_PORT,
        interface_name=None,
    )
    run_key = secrets.token_bytes(32)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "probe_method_version": METHOD_VERSION,
        "source_snapshot_id": manifest["source_snapshot_id"],
        "source_hash": manifest["source_hash"],
        "snapshot_node_count": len(manifest["nodes"]),
        "selected_node_count": len(proxies),
        "tool": tool,
        "run_id": resolve_run_id(resume=False),
        "started_at": iso_now(),
        "status": "RUNNING",
        "production_fingerprint_preserved": False,
        "results": [],
        "node_errors": [],
        "node_attempts": [],
        "nodes_reused": 0,
        "imported_verified_records": 0,
        "resumed_verified_records": 0,
        "control_attribution_backends": [
            backend_id
            for backend_id, _url, _parser in CONTROL_ATTRIBUTION_BACKENDS
        ],
        "runner_location": "router",
        "runner_scope": "remote",
        "tunnel_local_port_strategy": "dynamic_loopback",
        "remote_sidecar_port": skill.REMOTE_SIDECAR_MIXED_PORT,
        "resolved_proxy_url_strategy": "remote_loopback_sidecar_port",
        "gid_bypass_verified": False,
        "systemic_gate_confirmations": [],
    }
    previous_path: Path | None = None
    if args.resume and args.output.exists():
        previous_path = args.output
    elif args.import_report is not None:
        previous_path = args.import_report.resolve()
    if previous_path is not None:
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        reusable = reusable_node_ids(previous, manifest=manifest, tool=tool)
        selected_ids = {
            identities[str(proxy["name"])]
            for proxy in proxies
        }
        reusable &= selected_ids
        report["node_attempts"] = [
            item
            for item in previous.get("node_attempts", [])
            if item.get("exact_node_id") in reusable
        ]
        report["results"] = [
            item
            for item in previous.get("results", [])
            if item.get("exact_node_id") in reusable
        ]
        report["nodes_reused"] = len(reusable)
        if args.resume:
            report["resumed_verified_records"] = len(reusable)
            report["run_id"] = resolve_run_id(resume=True, previous=previous)
        else:
            report["imported_verified_records"] = len(reusable)
    else:
        reusable = set()
    before_fingerprint = skill.remote_production_fingerprint(args.host)
    with tempfile.TemporaryDirectory(prefix="rrc-sidecar-") as temporary:
        config_path = Path(temporary) / "probe.yaml"
        skill.dump_yaml(config, config_path)
        os.chmod(config_path, 0o600)
        with skill.remote_candidate_sidecar(
            config_path, host=args.host, core_path=args.core_path
        ) as sidecar:
            report["gid_bypass_verified"] = (
                "service=running" in before_fingerprint
            )
            skill.validate_probe_runtime(sidecar.controller_port)
            proxy_context = resolve_sidecar_proxy_context(
                runner_scope="remote",
                local_proxy_host="127.0.0.1",
                local_proxy_port=sidecar.mixed_port,
                remote_proxy_host="127.0.0.1",
                remote_proxy_port=skill.REMOTE_SIDECAR_MIXED_PORT,
                controller_url=f"http://127.0.0.1:{sidecar.controller_port}",
            )
            sentinel_names = [
                str(item["exact_node_name"])
                for item in (calibration_payload or {}).get("node_attempts", [])
                if item.get("status") == "ATTRIBUTION_MATCH"
            ]
            last_confirmed_unavailable_count = 0
            for proxy in proxies:
                name = str(proxy["name"])
                node_id = identities[name]
                if node_id in reusable:
                    continue
                outcome = probe_node_with_attribution(
                    skill=skill,
                    host=args.host,
                    controller_port=sidecar.controller_port,
                    proxy_context=proxy_context,
                    node_name=name,
                    timeout_seconds=args.timeout,
                    run_key=run_key,
                    stabilization_seconds=max(
                        DEFAULT_STABILIZATION_SECONDS,
                        skill.PROBE_SWITCH_WAIT_SECONDS,
                    ),
                )
                node_entry = {
                    key: value
                    for key, value in outcome.items()
                    if key != "raw_values"
                }
                node_entry.update(
                    {
                        "exact_node_id": node_id,
                        "exact_node_name": name,
                        "source_snapshot_id": manifest["source_snapshot_id"],
                        "completed_at": iso_now(),
                        "result_count": 0,
                    }
                )
                if outcome["status"] == "ATTRIBUTION_MISMATCH":
                    report["node_attempts"].append(node_entry)
                    update_report_counts(report)
                    report["status"] = "STOP_RRC_PROXY_ATTRIBUTION_MISMATCH"
                    safe_atomic_json(args.output.resolve(), report)
                    raise ProbeError("STOP_RRC_PROXY_ATTRIBUTION_MISMATCH")
                if outcome["status"] == "ATTRIBUTION_UNAVAILABLE":
                    append_node_error(
                        report,
                        manifest=manifest,
                        identities=identities,
                        node_name=name,
                        tool=tool,
                    )
                elif outcome["transport_unknown"] and not outcome["output_complete"]:
                    append_node_error(
                        report,
                        manifest=manifest,
                        identities=identities,
                        node_name=name,
                        tool=tool,
                    )
                else:
                    append_service_results(
                        report,
                        manifest=manifest,
                        identities=identities,
                        node_name=name,
                        control_exit_hmac=outcome["control_exit_ip_hmac"],
                        regioncheck_exit_hmac=outcome["regioncheck_exit_ip_hmac"],
                        country=outcome["exit_country"],
                        tool=tool,
                        raw_values=outcome["raw_values"],
                    )
                    node_entry["result_count"] = len(SERVICE_LABELS)
                report["node_attempts"].append(node_entry)
                update_report_counts(report)
                safe_atomic_json(args.output.resolve(), report)
                systemic_stop = systemic_attribution_stop_reason(
                    report["node_attempts"]
                )
                if systemic_stop is not None:
                    unavailable_count = int(report["attribution_unavailable"])
                    if unavailable_count > last_confirmed_unavailable_count:
                        healthy, confirmations = (
                            confirm_systemic_attribution_health(
                                skill=skill,
                                host=args.host,
                                controller_port=sidecar.controller_port,
                                proxy_context=proxy_context,
                                sentinel_names=sentinel_names,
                                timeout_seconds=args.timeout,
                                run_key=run_key,
                                stabilization_seconds=max(
                                    DEFAULT_STABILIZATION_SECONDS,
                                    skill.PROBE_SWITCH_WAIT_SECONDS,
                                ),
                            )
                        )
                        report["systemic_gate_confirmations"].append(
                            {
                                "trigger": systemic_stop,
                                "unavailable_count": unavailable_count,
                                "nodes_attempted": report["nodes_attempted"],
                                "healthy": healthy,
                                "sentinels": confirmations,
                            }
                        )
                        safe_atomic_json(args.output.resolve(), report)
                        if not healthy:
                            report["status"] = systemic_stop
                            safe_atomic_json(args.output.resolve(), report)
                            raise ProbeError(systemic_stop)
                        last_confirmed_unavailable_count = unavailable_count
                reset_sidecar_connections(
                    skill,
                    sidecar.controller_port,
                    sleep_seconds=max(0.0, args.node_interval),
                )
    after_fingerprint = skill.remote_production_fingerprint(args.host)
    require_preserved_production_fingerprint(
        before_fingerprint,
        after_fingerprint,
    )
    report["status"] = "COMPLETE"
    report["production_fingerprint_preserved"] = True
    update_report_counts(report)
    if args.calibration_only:
        validate_two_node_calibration(report)
    report["completed_at"] = iso_now()
    report["run_timestamp"] = report["completed_at"]
    expected_ids = {
        identities[str(proxy["name"])]
        for proxy in proxies
    }
    attempted_ids = {
        str(item.get("exact_node_id") or "")
        for item in report["node_attempts"]
    }
    report["identity_coverage"] = {
        "expected_node_count": len(expected_ids),
        "attempted_node_count": len(attempted_ids),
        "missing_node_ids": sorted(expected_ids - attempted_ids),
        "extra_node_ids": sorted(attempted_ids - expected_ids),
        "exact_id_set_equal": expected_ids == attempted_ids,
    }
    safe_atomic_json(args.output.resolve(), report)
    print("COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
