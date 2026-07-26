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
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
METHOD_VERSION = "regionrestrictioncheck-sidecar-v1"
EXPECTED_TOOL_VERSION = "1.0.1"
DEFAULT_COMMAND_PATH = "/usr/bin/regioncheck"
DEFAULT_SCRIPT_PATH = "/usr/lib/regionrestrictioncheck/check.sh"
DEFAULT_TIMEOUT_SECONDS = 240
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SERVICE_LABELS = {
    "gpt": "ChatGPT",
    "gemini": "Google Gemini",
    "disney": "Disney+",
}


class ProbeError(RuntimeError):
    """A fail-closed RegionRestrictionCheck orchestration error."""


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
    exit_hmac: str,
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
                "exit_ip_hmac": exit_hmac,
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


def control_geo(proxy_port: int, *, sleep_fn: Any = time.sleep) -> tuple[str, str]:
    last_error: BaseException | None = None
    for attempt in range(2):
        try:
            completed = subprocess.run(
                [
                    "curl", "--proxy", f"http://127.0.0.1:{proxy_port}",
                    "--ipv4", "--connect-timeout", "4", "--max-time", "12",
                    "--silent", "--show-error", "https://ipinfo.io/json",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if completed.returncode != 0:
                raise ProbeError("CONTROL_GEO_TRANSPORT")
            payload = json.loads(completed.stdout)
            ip = str(payload["ip"])
            country = str(payload.get("country") or "UNKNOWN")
            ipaddress.ip_address(ip)
            return ip, country
        except (
            KeyError, ValueError, json.JSONDecodeError, OSError,
            subprocess.TimeoutExpired, ProbeError,
        ) as exc:
            last_error = exc
            if attempt == 0:
                sleep_fn(1)
    raise ProbeError("STOP_RRC_PROXY_ATTRIBUTION_FAILED") from last_error


def run_regioncheck(skill: Any, host: str, timeout_seconds: int) -> tuple[int, str]:
    command = (
        f"{DEFAULT_COMMAND_PATH} -M 4 -R 0 -E en "
        f"-P http://127.0.0.1:{skill.REMOTE_SIDECAR_MIXED_PORT} </dev/null"
    )
    try:
        completed = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
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
    skill: Any,
    host: str,
    timeout_seconds: int,
    *,
    sleep_fn: Any = time.sleep,
) -> tuple[int, str, dict[str, str]]:
    returncode, output = run_regioncheck(skill, host, timeout_seconds)
    raw_values = extract_service_values(output)
    if returncode != 0 or (
        raw_values and all("Network Connection" in raw for raw in raw_values.values())
    ):
        sleep_fn(1)
        returncode, output = run_regioncheck(skill, host, timeout_seconds)
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
    args = parser.parse_args()

    skill = load_module(args.skill_script.resolve())
    manifest, payload_path = skill.verify_source_snapshot(args.source_snapshot.resolve())
    data = skill.load_yaml(payload_path)
    proxies = skill.static_proxy_objects(data)
    if args.max_nodes is not None:
        if args.max_nodes < 1:
            raise ProbeError("MAX_NODES_INVALID")
        proxies = proxies[: args.max_nodes]
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
        "started_at": iso_now(),
        "status": "RUNNING",
        "production_fingerprint_preserved": False,
        "results": [],
        "node_errors": [],
    }
    with tempfile.TemporaryDirectory(prefix="rrc-sidecar-") as temporary:
        config_path = Path(temporary) / "probe.yaml"
        skill.dump_yaml(config, config_path)
        os.chmod(config_path, 0o600)
        with skill.remote_candidate_sidecar(
            config_path, host=args.host, core_path=args.core_path
        ) as sidecar:
            skill.validate_probe_runtime(sidecar.controller_port)
            for node_index, proxy in enumerate(proxies, start=1):
                name = str(proxy["name"])
                if not skill.select_probe_node(sidecar.controller_port, name):
                    raise ProbeError("NODE_SWITCH_UNCONFIRMED")
                skill.controller_json_request(
                    sidecar.controller_port, "/connections", method="DELETE"
                )
                time.sleep(skill.PROBE_SWITCH_WAIT_SECONDS)
                try:
                    control_ip, country = control_geo(sidecar.mixed_port)
                except ProbeError as exc:
                    if str(exc) != "STOP_RRC_PROXY_ATTRIBUTION_FAILED":
                        raise
                    append_service_results(
                        report,
                        manifest=manifest,
                        identities=identities,
                        node_name=name,
                        exit_hmac="",
                        country="UNKNOWN",
                        tool=tool,
                        raw_values={
                            service: "Failed (Network Connection)"
                            for service in SERVICE_LABELS
                        },
                    )
                    report["nodes_completed"] = node_index
                    safe_atomic_json(args.output, report)
                    time.sleep(args.node_interval)
                    continue
                exit_hmac = hmac_prefix(run_key, control_ip)
                returncode, output, raw_values = run_regioncheck_with_transport_retry(
                    skill, args.host, args.timeout
                )
                masked = extract_masked_ip(output)
                if returncode != 124 and not masked_ip_matches(control_ip, masked):
                    skill.controller_json_request(
                        sidecar.controller_port, "/connections", method="DELETE"
                    )
                    time.sleep(skill.PROBE_SWITCH_WAIT_SECONDS)
                    control_ip, country = control_geo(sidecar.mixed_port)
                    exit_hmac = hmac_prefix(run_key, control_ip)
                    returncode, output, raw_values = run_regioncheck_with_transport_retry(
                        skill, args.host, args.timeout
                    )
                    masked = extract_masked_ip(output)
                    if returncode != 124 and not masked_ip_matches(control_ip, masked):
                        if is_unattributable_tool_failure(returncode, masked):
                            append_node_error(
                                report,
                                manifest=manifest,
                                identities=identities,
                                node_name=name,
                                tool=tool,
                            )
                            report["nodes_completed"] = node_index
                            safe_atomic_json(args.output.resolve(), report)
                            skill.controller_json_request(
                                sidecar.controller_port,
                                "/connections",
                                method="DELETE",
                            )
                            time.sleep(max(0.0, args.node_interval))
                            continue
                        raise ProbeError("STOP_RRC_PROXY_ATTRIBUTION_FAILED")
                append_service_results(
                    report,
                    manifest=manifest,
                    identities=identities,
                    node_name=name,
                    exit_hmac=exit_hmac,
                    country=country,
                    tool=tool,
                    raw_values=raw_values,
                )
                report["nodes_completed"] = node_index
                safe_atomic_json(args.output.resolve(), report)
                skill.controller_json_request(
                    sidecar.controller_port, "/connections", method="DELETE"
                )
                time.sleep(max(0.0, args.node_interval))
    report["status"] = "COMPLETE"
    report["production_fingerprint_preserved"] = True
    report["completed_at"] = iso_now()
    safe_atomic_json(args.output.resolve(), report)
    print("COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
