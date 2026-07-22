#!/usr/bin/env python3
"""Definitive Disney+ region probe through the isolated router sidecar.

Only stage status, terminal classification, country, and supported-location are
persisted. Assertions, tokens, request bodies, and response bodies stay inside
one request scope and are never written to the report.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote


SCHEMA_VERSION = 1
METHOD_VERSION = "disney-full-chain-v2"
CLIENT_KEY = (
    "ZGlzbmV5JmJyb3dzZXImMS4wLjA."
    "Cu56AgSfBTDag5NiRA81oLHkDZfu5L3CKadnefEAY84"
)
USER_AGENT = "Mozilla/5.0 AppleWebKit/537.36 Chrome/125 Safari/537.36"
TERMINAL_RESULTS = {
    "PASS_SUPPORTED_REGION",
    "FAIL_FORBIDDEN_LOCATION",
    "FAIL_IP_BANNED",
    "FAIL_UNAVAILABLE",
    "FAIL_TRANSPORT",
    "UNKNOWN_RESPONSE_SCHEMA",
}


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_skill(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("openclash_skill", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("DISNEY_SKILL_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def curl_request(
    proxy_port: int,
    method: str,
    url: str,
    *,
    headers: list[str],
    body: str | None = None,
    follow: bool = False,
) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for attempt in range(1, 3):
        with tempfile.TemporaryDirectory(prefix="disney-stage-") as temporary:
            response_path = Path(temporary) / "response"
            command = [
                "curl", "--proxy", f"http://127.0.0.1:{proxy_port}",
                "--connect-timeout", "3", "--max-time", "12", "--silent",
                "--show-error", "--http1.1", "--request", method,
                "--user-agent", USER_AGENT, "--output", str(response_path),
                "--write-out", "%{http_code}\n%{url_effective}\n",
            ]
            if follow:
                command.extend(["--location", "--max-redirs", "5"])
            for header in headers:
                command.extend(["--header", header])
            if body is not None:
                command.extend(["--data-binary", "@-"])
            command.append(url)
            completed = subprocess.run(
                command, input=body, text=True, capture_output=True, check=False
            )
            lines = completed.stdout.splitlines()
            status = int(lines[0]) if lines and lines[0].isdigit() else None
            last = {
                "curl_code": completed.returncode,
                "http_status": status,
                "effective_url": lines[1] if len(lines) > 1 else "",
                "raw": response_path.read_text(encoding="utf-8", errors="replace")
                if response_path.exists() else "",
                "attempts": attempt,
            }
        if completed.returncode == 0 and status is not None:
            break
    return last


def json_object(response: dict[str, Any]) -> dict[str, Any] | None:
    try:
        payload = json.loads(str(response.get("raw", "")))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def safe_stage(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "curl_code": response.get("curl_code"),
        "http_status": response.get("http_status"),
        "attempts": response.get("attempts"),
    }


def classify_graphql(payload: Any) -> tuple[str, bool] | None:
    """Read the current BAMGrid session-level supported-location schema."""
    try:
        session = payload["extensions"]["sdk"]["session"]
        country = str(session["location"]["countryCode"])
        supported = session["inSupportedLocation"]
    except (KeyError, TypeError):
        return None
    if not country or not isinstance(supported, bool):
        return None
    return country, supported


def transport_or_ban(response: dict[str, Any], stage: str) -> dict[str, Any] | None:
    if response.get("curl_code") != 0:
        return {"result": "FAIL_TRANSPORT", "failure_stage": stage}
    if response.get("http_status") == 403:
        return {"result": "FAIL_IP_BANNED", "failure_stage": stage}
    return None


def run_chain(proxy_port: int) -> dict[str, Any]:
    stages: dict[str, Any] = {}
    bearer = f"authorization: Bearer {CLIENT_KEY}"
    devices = curl_request(
        proxy_port, "POST", "https://disney.api.edge.bamgrid.com/devices",
        headers=[bearer, "content-type: application/json; charset=UTF-8"],
        body=json.dumps({
            "deviceFamily": "browser", "applicationRuntime": "chrome",
            "deviceProfile": "windows", "attributes": {},
        }, separators=(",", ":")),
    )
    stages["devices"] = safe_stage(devices)
    terminal = transport_or_ban(devices, "devices")
    if terminal:
        return {**terminal, "stages": stages}
    device_payload = json_object(devices)
    assertion = device_payload.get("assertion") if device_payload else None
    if not isinstance(assertion, str) or not assertion:
        return {"result": "UNKNOWN_RESPONSE_SCHEMA", "failure_stage": "devices", "stages": stages}

    token = curl_request(
        proxy_port, "POST", "https://disney.api.edge.bamgrid.com/token",
        headers=[bearer, "content-type: application/x-www-form-urlencoded"],
        body=(
            "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Atoken-exchange"
            "&latitude=0&longitude=0&platform=browser&subject_token="
            + quote(assertion, safe="")
            + "&subject_token_type=urn%3Abamtech%3Aparams%3Aoauth%3Atoken-type%3Adevice"
        ),
    )
    stages["token"] = safe_stage(token)
    terminal = transport_or_ban(token, "token")
    token_payload = json_object(token)
    if token_payload and token_payload.get("error_description") == "forbidden-location":
        return {"result": "FAIL_FORBIDDEN_LOCATION", "failure_stage": "token", "stages": stages}
    if terminal:
        return {**terminal, "stages": stages}
    refresh = token_payload.get("refresh_token") if token_payload else None
    if not isinstance(refresh, str) or not refresh:
        return {"result": "UNKNOWN_RESPONSE_SCHEMA", "failure_stage": "token", "stages": stages}

    graphql = curl_request(
        proxy_port, "POST", "https://disney.api.edge.bamgrid.com/graph/v1/device/graphql",
        headers=[f"authorization: {CLIENT_KEY}", "content-type: application/json"],
        body=json.dumps({
            "query": "mutation refreshToken($input: RefreshTokenInput!) { refreshToken(refreshToken: $input) { activeSession { sessionId } } }",
            "variables": {"input": {"refreshToken": refresh}},
        }, separators=(",", ":")),
        follow=True,
    )
    stages["graphql"] = safe_stage(graphql)
    terminal = transport_or_ban(graphql, "graphql")
    if terminal:
        return {**terminal, "stages": stages}
    location = classify_graphql(json_object(graphql))
    if location is None:
        return {"result": "UNKNOWN_RESPONSE_SCHEMA", "failure_stage": "graphql", "stages": stages}
    country, supported = location

    redirect = curl_request(
        proxy_port, "GET", "https://disneyplus.com/", headers=[], follow=True
    )
    stages["redirect"] = safe_stage(redirect)
    if redirect.get("curl_code") != 0:
        return {
            "result": "FAIL_TRANSPORT", "failure_stage": "redirect",
            "country_code": country, "in_supported_location": supported, "stages": stages,
        }
    final_url = str(redirect.get("effective_url", "")).lower()
    unavailable = "preview" in final_url or "unavailable" in final_url
    result = "FAIL_UNAVAILABLE" if unavailable or not supported else "PASS_SUPPORTED_REGION"
    return {
        "result": result,
        "failure_stage": "redirect" if unavailable else None,
        "country_code": country,
        "in_supported_location": supported,
        "final_redirect_class": "UNAVAILABLE" if unavailable else "SUPPORTED_ROUTE",
        "stages": stages,
    }


def validate_safe_report(report: dict[str, Any]) -> None:
    forbidden = {"assertion", "token", "refresh_token", "authorization", "body", "raw"}
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in forbidden:
                    raise RuntimeError("DISNEY_REPORT_SENSITIVE_FIELD")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-script", type=Path, required=True)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--host", default="root@192.168.10.1")
    parser.add_argument("--core-path", default="/etc/openclash/core/clash_meta")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only-node-id", action="append", default=[])
    args = parser.parse_args()

    skill = load_skill(args.skill_script.resolve())
    manifest, payload_path = skill.verify_source_snapshot(args.source_snapshot.resolve())
    proxies = skill.static_proxy_objects(skill.load_yaml(payload_path))
    identities = {
        str(item["exact_node_name"]): str(item["exact_node_id"])
        for item in manifest["nodes"]
    }
    selected = set(args.only_node_id)
    run_proxies = [proxy for proxy in proxies if not selected or identities[str(proxy["name"])] in selected]
    if selected and len(run_proxies) != len(selected):
        raise RuntimeError("DISNEY_NODE_NOT_IN_SNAPSHOT")
    config = skill.build_probe_config(
        proxies, mixed_port=skill.REMOTE_SIDECAR_MIXED_PORT,
        controller_port=skill.REMOTE_SIDECAR_CONTROLLER_PORT, interface_name=None,
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "service": "disney",
        "probe_method_version": METHOD_VERSION,
        "source_snapshot_id": manifest["source_snapshot_id"],
        "source_hash": manifest["source_hash"], "started_at": iso_now(),
        "transport": "ssh_loopback_to_router_sidecar", "nodes": [],
    }
    with tempfile.TemporaryDirectory(prefix="disney-sidecar-") as temporary:
        config_path = Path(temporary) / "probe.yaml"
        skill.dump_yaml(config, config_path)
        os.chmod(config_path, 0o600)
        with skill.remote_candidate_sidecar(config_path, host=args.host, core_path=args.core_path) as sidecar:
            skill.validate_probe_runtime(sidecar.controller_port)
            for proxy in run_proxies:
                name = str(proxy["name"])
                if not skill.select_probe_node(sidecar.controller_port, name):
                    outcome = {"result": "UNKNOWN_RESPONSE_SCHEMA", "failure_stage": "selector"}
                else:
                    time.sleep(skill.PROBE_SWITCH_WAIT_SECONDS)
                    outcome = run_chain(sidecar.mixed_port)
                report["nodes"].append({
                    "exact_node_name": name, "exact_node_id": identities[name],
                    "source_snapshot_id": manifest["source_snapshot_id"],
                    "source_hash": manifest["source_hash"], "tested_at": iso_now(),
                    **outcome,
                })
    report["production_fingerprint_preserved"] = True
    report["completed_at"] = iso_now()
    report["summary"] = {
        result: sum(item["result"] == result for item in report["nodes"])
        for result in TERMINAL_RESULTS
    }
    validate_safe_report(report)
    skill.atomic_write_json(report, args.output.resolve(), private_parent=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
