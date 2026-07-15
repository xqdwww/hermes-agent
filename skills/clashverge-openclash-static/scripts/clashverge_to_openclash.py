#!/usr/bin/env python3
"""Convert a Clash Verge effective YAML into the user's accepted simple OpenClash profile.

Policy:
- exactly 12 managed groups;
- manual groups list direct nodes;
- automatic groups are ordinary fallback groups;
- GPT uses the previously working candidate set, not the unreliable GPT probe;
- Gemini and Disney use the accepted candidate sets;
- the placeholder node is removed;
- service rules are narrow and the final rule is exactly MATCH,默认代理;
- no per-node wrapper groups are generated.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: PyYAML. Install with: python3 -m pip install PyYAML"
    ) from exc


DEFAULT_VERGE_CANDIDATES = (
    Path.home()
    / "Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml",
    Path.home()
    / "Library/Application Support/com.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml",
)

PLACEHOLDER_NODES = {"使用前先更新订阅"}

# Accepted working GPT candidates. Only names present in the current subscription are used.
GPT_CANDIDATES = (
    "🇨🇳台湾-住宅",
    "🇬🇧英国-住宅01",
    "🇯🇵日本aws高速02",
    "🇯🇵日本aws高速03",
    "🇯🇵日本-原生01",
    "🇸🇬新加坡aws高速01",
    "🇸🇬新加坡aws高速02",
    "🇸🇬新加坡-hy2",
    "🇺🇸美国-住宅",
    "🇺🇸美国迈阿密-hy2",
    "🇺🇸美国拉斯维加斯-hy2",
)

# Accepted Gemini set from the final reviewed profile.
GEMINI_CANDIDATES = (
    "🇨🇳台湾-住宅",
    "🇭🇰香港aws高速01",
    "🇸🇬新加坡aws高速01",
    "🇸🇬新加坡aws高速02",
    "🇯🇵日本aws高速01",
    "🇯🇵日本aws高速02",
    "🇨🇳香港原生htk高速01",
    "🇨🇳香港原生htk高速02",
    "🇨🇳香港hkb家宽01",
    "🇰🇷韩国aws01",
    "🇯🇵日本-流媒体02",
    "🇰🇷韩国-流媒体01",
    "新加坡-媒体流01",
    "🇨🇳香港原生hkt01-hy2",
    "🇺🇸美国住宅-hy2",
    "🇺🇸美国迈阿密-hy2",
    "🇺🇸美国拉斯维加斯-hy2",
)

# Accepted Disney set from the final reviewed profile.
DISNEY_CANDIDATES = (
    "🇨🇳台湾-住宅",
    "🇺🇸美国-住宅",
    "🇭🇰香港aws高速01",
    "🇸🇬新加坡aws高速01",
    "🇸🇬新加坡aws高速02",
    "🇯🇵日本aws高速01",
    "🇯🇵日本aws高速02",
    "🇨🇳香港原生htk高速01",
    "🇨🇳香港原生htk高速02",
    "🇨🇳香港hkb家宽01",
    "🇰🇷韩国aws01",
    "🇯🇵日本-流媒体02",
    "🇰🇷韩国-流媒体01",
    "新加坡-媒体流01",
    "🇨🇳香港原生hkt01-hy2",
    "🇺🇸美国住宅-hy2",
    "🇺🇸美国迈阿密-hy2",
    "🇺🇸美国拉斯维加斯-hy2",
)

SERVICE_RULES = (
    # GPT / ChatGPT
    "DOMAIN-SUFFIX,chatgpt.com,GPT专用",
    "DOMAIN-SUFFIX,openai.com,GPT专用",
    "DOMAIN-SUFFIX,oaistatic.com,GPT专用",
    "DOMAIN-SUFFIX,oaiusercontent.com,GPT专用",
    # Gemini: intentionally narrow; do not capture the whole Google ecosystem.
    "DOMAIN,gemini.google.com,Gemini专用",
    "DOMAIN,bard.google.com,Gemini专用",
    "DOMAIN,aistudio.google.com,Gemini专用",
    "DOMAIN-SUFFIX,generativelanguage.googleapis.com,Gemini专用",
    "DOMAIN-SUFFIX,ai.google.dev,Gemini专用",
    "DOMAIN-SUFFIX,deepmind.google,Gemini专用",
    "DOMAIN-SUFFIX,deepmind.com,Gemini专用",
    # Disney+
    "DOMAIN-SUFFIX,disneyplus.com,迪士尼",
    "DOMAIN-SUFFIX,disney-plus.net,迪士尼",
    "DOMAIN-SUFFIX,dssott.com,迪士尼",
    "DOMAIN-SUFFIX,bamgrid.com,迪士尼",
)

MANAGED_GROUP_NAMES = (
    "默认代理",
    "手动选择",
    "自动选择",
    "GPT专用",
    "GPT手动",
    "GPT自动",
    "Gemini专用",
    "Gemini手动",
    "Gemini自动",
    "迪士尼",
    "迪士尼手动",
    "迪士尼自动",
)

BUILTIN_TARGETS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE"}
SENSITIVE_KEYS = {
    "server",
    "port",
    "password",
    "uuid",
    "token",
    "servername",
    "sni",
    "public-key",
    "short-id",
    "private-key",
    "client-secret",
    "psk",
    "secret",
    "authorization",
    "proxy-authorization",
}

CLASH_VERGE_TOP_LEVEL_RUNTIME_KEYS = {
    "allow-lan",
    "bind-address",
    "external-controller",
    "external-controller-cors",
    "external-controller-unix",
    "mixed-port",
    "port",
    "profile",
    "redir-port",
    "secret",
    "socks-port",
    "tproxy-port",
}
HEALTH_CHECK_ATTEMPTS = 3
HEALTH_CHECK_DELAY_SECONDS = 2
LKG_SCHEMA_VERSION = 1
PROBE_SCHEMA_VERSION = 1
PROBE_VERSION = "2"
PROBE_CONNECT_TIMEOUT_SECONDS = 3
PROBE_TOTAL_TIMEOUT_SECONDS = 8
PROBE_REQUEST_ATTEMPTS = 2
PROBE_SWITCH_WAIT_SECONDS = 0.75
PROBE_RUN_TIMEOUT_SECONDS = 15 * 60
DEFAULT_LKG_STATE_PATH = (
    Path.home() / ".hermes/state/clashverge-openclash-static/service-probe-lkg.json"
)
DEFAULT_PROBE_REPORT_PATH = Path("/tmp/openclash-service-probe-results.json")
PROBE_CORE_CANDIDATES = (
    Path("/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo"),
    Path("/Applications/Clash Verge.app/Contents/Resources/mihomo"),
    Path("/opt/homebrew/bin/mihomo"),
    Path("/usr/local/bin/mihomo"),
)
SERVICE_KEYS = ("gpt", "gemini", "disney")
PASS_RESULTS = {"PASS", "MANUAL_OVERRIDE_PASS"}
PENDING_RESULTS = {"CHALLENGE_UNKNOWN", "AUTH_UNKNOWN", "UNKNOWN"}
REMOVE_RESULTS = {"FAIL_REGION", "MANUAL_OVERRIDE_FAIL"}
SERVICE_GROUP_NAMES = {
    "gpt": ("GPT自动", "GPT手动"),
    "gemini": ("Gemini自动", "Gemini手动"),
    "disney": ("迪士尼自动", "迪士尼手动"),
}
SERVICE_ENDPOINTS = {
    "gpt": ("https://chatgpt.com/", "https://cdn.oaistatic.com/"),
    "gemini": (
        "https://gemini.google.com/",
        "https://generativelanguage.googleapis.com/",
    ),
    "disney": ("https://www.disneyplus.com/", "https://global.edge.bamgrid.com/"),
}
EGRESS_METADATA_ENDPOINTS = (
    "https://speed.cloudflare.com/meta",
    "https://ipwho.is/",
    "https://ipapi.co/json/",
)
GPT_MANUAL_OVERRIDES = {"🇯🇵日本aws高速02": "MANUAL_OVERRIDE_PASS"}
GEMINI_MANUAL_OVERRIDES = {
    "🇺🇸美国-住宅": "MANUAL_OVERRIDE_FAIL",
    "🇺🇸美国迈阿密-hy2": "MANUAL_OVERRIDE_PASS",
    "🇺🇸美国拉斯维加斯-hy2": "MANUAL_OVERRIDE_PASS",
}
DISNEY_MANUAL_OVERRIDES: dict[str, str] = {}
MANUAL_OVERRIDES = {
    "gpt": GPT_MANUAL_OVERRIDES,
    "gemini": GEMINI_MANUAL_OVERRIDES,
    "disney": DISNEY_MANUAL_OVERRIDES,
}
REGION_FAILURE_MARKERS = (
    "not available in your country",
    "not available in your region",
    "unsupported country",
    "country is not supported",
    "region is not supported",
    "此服务在您所在的国家",
    "你所在的地区目前不支持",
)
CHALLENGE_MARKERS = (
    "cf-chl",
    "challenge-platform",
    "cloudflare",
    "captcha",
    "verify you are human",
    "attention required",
    "robot check",
    "bot detection",
)
AUTH_MARKERS = (
    "authentication required",
    "authorization required",
    "invalid api key",
)
REPORT_FORBIDDEN_KEYS = {
    "server",
    "port",
    "password",
    "uuid",
    "token",
    "servername",
    "sni",
    "private-key",
    "public-key",
    "short-id",
    "secret",
}
_DROP_RUNTIME = object()

_FLAG_PREFIX_RE = re.compile(r"^[\U0001F1E6-\U0001F1FF]{2}\s*")


class ConfigError(RuntimeError):
    """Raised when a source configuration cannot be transformed safely."""


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def find_default_source() -> Path:
    for candidate in DEFAULT_VERGE_CANDIDATES:
        if candidate.is_file():
            return candidate

    base = Path.home() / "Library/Application Support"
    matches = sorted(base.glob("*clash-verge*/**/*.yaml")) if base.exists() else []
    for match in matches:
        if match.is_file():
            try:
                data = load_yaml(match)
            except ConfigError:
                continue
            if isinstance(data.get("proxies"), list) and data["proxies"]:
                return match

    searched = "\n".join(f"  - {path}" for path in DEFAULT_VERGE_CANDIDATES)
    raise ConfigError(
        "Could not find a Clash Verge effective configuration containing static proxies. "
        f"Checked:\n{searched}\nPass --source explicitly."
    )


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Cannot read YAML: {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("The YAML root must be a mapping/object.")
    return data


def dump_yaml(data: dict[str, Any], path: Path, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=180,
    )
    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)


def ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_node_name(name: str) -> str:
    return _FLAG_PREFIX_RE.sub("", name).strip()


def static_proxy_objects(data: dict[str, Any]) -> list[dict[str, Any]]:
    proxies = data.get("proxies")
    if not isinstance(proxies, list) or not proxies:
        raise ConfigError(
            "No static nodes were found under 'proxies:'. Use the Clash Verge effective/merged YAML."
        )

    result: list[dict[str, Any]] = []
    names: list[str] = []
    for index, proxy in enumerate(proxies):
        if not isinstance(proxy, dict):
            raise ConfigError(f"proxies[{index}] is not an object.")
        name = proxy.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"proxies[{index}] has no valid name.")
        if name in PLACEHOLDER_NODES:
            continue
        result.append(proxy)
        names.append(name)

    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"Duplicate proxy names: {', '.join(duplicates)}")
    if not result:
        raise ConfigError("No usable static nodes remain after removing placeholders.")
    return result


def resolve_candidates(
    available_names: Sequence[str],
    candidates: Sequence[str],
    *,
    label: str,
) -> list[str]:
    raw_map = {name: name for name in available_names}
    normalized_map: dict[str, list[str]] = {}
    for name in available_names:
        normalized_map.setdefault(normalize_node_name(name), []).append(name)

    resolved: list[str] = []
    for candidate in candidates:
        if candidate in raw_map:
            resolved.append(candidate)
            continue
        matches = normalized_map.get(normalize_node_name(candidate), [])
        if len(matches) == 1:
            resolved.append(matches[0])
        elif len(matches) > 1:
            raise ConfigError(
                f"Ambiguous normalized {label} candidate '{candidate}': {', '.join(matches)}"
            )

    resolved = ordered_unique(resolved)
    if not resolved:
        raise ConfigError(f"No {label} candidate from the accepted profile exists in this subscription.")
    return resolved


def region_rank(name: str, *, gemini: bool = False) -> int:
    if "日本" in name or "🇯🇵" in name:
        return 0
    if "台湾" in name or "🇹🇼" in name:
        return 1
    if gemini and ("香港" in name or "🇭🇰" in name):
        return 2
    if gemini and ("德国" in name or "🇩🇪" in name):
        return 3
    return 4 if gemini else 2


def stable_region_sort(
    names: Sequence[str],
    source_order: dict[str, int],
    *,
    gemini: bool = False,
) -> list[str]:
    return sorted(names, key=lambda name: (region_rank(name, gemini=gemini), source_order[name]))


def iso_now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write_json(
    data: dict[str, Any], path: Path, *, private_parent: bool = False
) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    shared_temp_roots = {
        Path("/tmp").resolve(),
        Path("/private/tmp").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    }
    if private_parent and path.parent not in shared_temp_roots:
        os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Cannot read JSON: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"JSON root must be an object: {path}")
    return data


def legacy_service_members(config: dict[str, Any]) -> dict[str, list[str]]:
    groups = {
        str(group.get("name")): group
        for group in config.get("proxy-groups", [])
        if isinstance(group, dict)
    }
    result: dict[str, list[str]] = {}
    for service, (automatic_name, _) in SERVICE_GROUP_NAMES.items():
        group = groups.get(automatic_name)
        proxies = group.get("proxies") if isinstance(group, dict) else None
        if not isinstance(proxies, list) or not proxies:
            raise ConfigError(f"BLOCKED_NO_LKG_{service.upper()}_NODES")
        result[service] = [name for name in proxies if isinstance(name, str)]
    return result


def seed_lkg_state(legacy_config: dict[str, Any], *, updated_at: str | None = None) -> dict[str, Any]:
    timestamp = updated_at or iso_now()
    state: dict[str, Any] = {
        "schema_version": LKG_SCHEMA_VERSION,
        "updated_at": timestamp,
        "nodes": {},
    }
    for service, members in legacy_service_members(legacy_config).items():
        for name in members:
            node = state["nodes"].setdefault(name, {})
            node[service] = {
                "last_raw_result": "LEGACY_SEED",
                "last_final_result": "PASS",
                "last_confirmed_pass_at": timestamp,
                "source": "legacy_seed",
                "lkg": True,
            }
    return state


def load_or_seed_lkg_state(
    path: Path,
    legacy_config: dict[str, Any],
    *,
    persist_seed: bool,
) -> tuple[dict[str, Any], str]:
    path = path.expanduser().resolve()
    if not path.exists():
        state = seed_lkg_state(legacy_config)
        if persist_seed:
            atomic_write_json(state, path, private_parent=True)
        return state, "legacy_seed"
    state = load_json_object(path)
    if state.get("schema_version") != LKG_SCHEMA_VERSION or not isinstance(
        state.get("nodes"), dict
    ):
        raise ConfigError(f"Unsupported LKG state schema: {path}")
    return state, "state_file"


def exact_or_flag_normalized_match(name: str, expected: str) -> bool:
    return name == expected or normalize_node_name(name) == normalize_node_name(expected)


def manual_override_for(service: str, node_name: str) -> str | None:
    for expected, result in MANUAL_OVERRIDES[service].items():
        if exact_or_flag_normalized_match(node_name, expected):
            return result
    return None


def evidence_transport_result(evidence: dict[str, Any]) -> str | None:
    curl_code = evidence.get("curl_code")
    if curl_code in {6}:
        return "DNS_FAIL"
    if curl_code in {35, 51, 58, 59, 60, 77, 80, 82, 83, 90, 91}:
        return "TLS_FAIL"
    if curl_code in {7, 28}:
        return (
            "CONNECT_TIMEOUT"
            if not evidence.get("time_connect")
            else "HTTP_TIMEOUT"
        )
    if curl_code not in {None, 0}:
        return "FAIL_TRANSPORT"
    return None


def classify_service_evidence(
    service: str,
    main: dict[str, Any],
    support: dict[str, Any],
) -> str:
    transport = evidence_transport_result(main) or evidence_transport_result(support)
    if transport:
        return "FAIL_TRANSPORT"

    combined = "\n".join(
        str(value).lower()
        for evidence in (main, support)
        for value in (
            evidence.get("body_excerpt", ""),
            evidence.get("headers_excerpt", ""),
            evidence.get("final_host", ""),
            evidence.get("content_type", ""),
        )
    )
    if any(marker in combined for marker in REGION_FAILURE_MARKERS):
        return "FAIL_REGION"
    if any(marker in combined for marker in CHALLENGE_MARKERS):
        return "CHALLENGE_UNKNOWN"
    statuses = {main.get("http_status"), support.get("http_status")}
    if 401 in statuses or any(marker in combined for marker in AUTH_MARKERS):
        return "AUTH_UNKNOWN"

    main_status = main.get("http_status")
    support_status = support.get("http_status")
    main_http_signal = isinstance(main_status, int) and 200 <= main_status < 400
    if evidence_response_class(main) == "LOGIN_REACHABLE":
        main_http_signal = True
    support_http_signal = isinstance(support_status, int) and 200 <= support_status < 500
    if main_http_signal and support_http_signal:
        return "PASS"
    if 403 in statuses:
        return "UNKNOWN"
    return "UNKNOWN"


def apply_manual_override(service: str, node_name: str, raw_result: str) -> dict[str, Any]:
    override = manual_override_for(service, node_name)
    return {
        "raw_result": raw_result,
        "override": override,
        "final_result": override or raw_result,
    }


def declared_region(name: str) -> str:
    for flag, code in (
        ("🇯🇵", "JP"),
        ("🇹🇼", "TW"),
        ("🇭🇰", "HK"),
        ("🇸🇬", "SG"),
        ("🇺🇸", "US"),
        ("🇬🇧", "GB"),
        ("🇩🇪", "DE"),
        ("🇰🇷", "KR"),
    ):
        if flag in name:
            return code
    normalized = normalize_node_name(name)
    for marker, code in (
        ("日本", "JP"),
        ("台湾", "TW"),
        ("香港", "HK"),
        ("新加坡", "SG"),
        ("美国", "US"),
        ("英国", "GB"),
        ("德国", "DE"),
        ("韩国", "KR"),
    ):
        if marker in normalized:
            return code
    return "UNKNOWN"


def probable_unified_egress(nodes: Sequence[dict[str, Any]]) -> bool:
    base_pass_nodes = [node for node in nodes if node.get("base_result") == "BASE_PASS"]
    if len(base_pass_nodes) < 3:
        return False
    eligible: list[tuple[tuple[str, str, str], str]] = []
    for node in base_pass_nodes:
        country = str(node.get("egress_country") or "")
        asn = str(node.get("egress_asn") or "")
        ip_hash = str(node.get("egress_ip_hash") or "")
        if not country or not asn or not ip_hash:
            return False
        eligible.append(
            ((country, asn, ip_hash), declared_region(str(node.get("name", ""))))
        )
    declared_regions = {region for _, region in eligible if region != "UNKNOWN"}
    signatures = {signature for signature, _ in eligible}
    return len(declared_regions) >= 2 and len(signatures) == 1


def merge_lkg_results(
    current_names: Sequence[str],
    source_order: dict[str, int],
    state: dict[str, Any],
    probe_nodes: Sequence[dict[str, Any]],
    *,
    probable_recapture: bool,
    observed_at: str,
) -> tuple[dict[str, dict[str, list[str]]], dict[str, Any], list[dict[str, Any]]]:
    current_set = set(current_names)
    new_state = deepcopy(state)
    state_nodes = new_state.setdefault("nodes", {})
    probe_by_name = {str(item["name"]): deepcopy(item) for item in probe_nodes}

    if not probable_recapture:
        for stale_name in list(state_nodes):
            if stale_name not in current_set:
                del state_nodes[stale_name]

    enriched: list[dict[str, Any]] = []
    for name in current_names:
        item = probe_by_name.get(name)
        if item is None:
            continue
        item.setdefault("lkg_merge", {})
        item.setdefault("enters_auto", {})
        item.setdefault("enters_manual_candidate", {})
        for service in SERVICE_KEYS:
            service_result = item["services"][service]
            final_result = str(service_result["final_result"])
            prior = state.get("nodes", {}).get(name, {}).get(service, {})
            prior_lkg = bool(prior.get("lkg"))

            if probable_recapture:
                lkg = prior_lkg
                action = "LKG_UNCHANGED_PROBABLE_RECAPTURE"
            elif final_result in PASS_RESULTS:
                lkg = True
                action = "LKG_ADDED_OR_REFRESHED"
            elif final_result in REMOVE_RESULTS:
                lkg = False
                action = "LKG_REMOVED_EXPLICIT_FAIL"
            elif final_result in PENDING_RESULTS or final_result == "FAIL_TRANSPORT":
                lkg = prior_lkg
                action = "LKG_RETAINED_PENDING_RECHECK" if prior_lkg else "NEW_NODE_NOT_LKG"
            else:
                lkg = prior_lkg
                action = "LKG_UNCHANGED"

            if not probable_recapture:
                node_state = state_nodes.setdefault(name, {})
                confirmed_at = prior.get("last_confirmed_pass_at")
                if final_result in PASS_RESULTS:
                    confirmed_at = observed_at
                node_state[service] = {
                    "last_raw_result": service_result["raw_result"],
                    "last_final_result": final_result,
                    "last_confirmed_pass_at": confirmed_at,
                    "source": "manual_override" if service_result.get("override") else "probe",
                    "lkg": lkg,
                }

            item["lkg_merge"][service] = action
            item["enters_auto"][service] = lkg
            item["enters_manual_candidate"][service] = (
                not probable_recapture and not lkg and final_result in PENDING_RESULTS
            )
        enriched.append(item)

    selections: dict[str, dict[str, list[str]]] = {}
    effective_state = state if probable_recapture else new_state
    for service in SERVICE_KEYS:
        automatic = [
            name
            for name in current_names
            if bool(effective_state.get("nodes", {}).get(name, {}).get(service, {}).get("lkg"))
        ]
        pending = [
            str(item["name"])
            for item in enriched
            if item["enters_manual_candidate"][service]
            and str(item["name"]) not in automatic
        ]
        automatic = stable_region_sort(
            automatic, source_order, gemini=service == "gemini"
        )
        pending = stable_region_sort(pending, source_order, gemini=service == "gemini")
        if not automatic:
            raise ConfigError(f"BLOCKED_NO_LKG_{service.upper()}_NODES")
        selections[service] = {"automatic": automatic, "manual_candidates": pending}

    if not probable_recapture:
        new_state["updated_at"] = observed_at
    return selections, new_state, enriched


def curl_probe_once(
    url: str,
    mixed_port: int,
    *,
    workdir: Path,
    command_runner: Any = run,
) -> dict[str, Any]:
    request_id = uuid.uuid4().hex
    body_path = workdir / f"body-{request_id}.tmp"
    header_path = workdir / f"headers-{request_id}.tmp"
    write_out = "\n".join(
        (
            "%{http_code}",
            "%{url_effective}",
            "%{content_type}",
            "%{remote_ip}",
            "%{time_connect}",
        )
    )
    try:
        completed = command_runner(
            [
                "curl",
                "--proxy",
                f"http://127.0.0.1:{mixed_port}",
                "--connect-timeout",
                str(PROBE_CONNECT_TIMEOUT_SECONDS),
                "--max-time",
                str(PROBE_TOTAL_TIMEOUT_SECONDS),
                "--silent",
                "--show-error",
                "--location",
                "--max-redirs",
                "5",
                "--http1.1",
                "--header",
                "Cache-Control: no-cache",
                "--dump-header",
                str(header_path),
                "--output",
                str(body_path),
                "--write-out",
                write_out,
                url,
            ],
            check=False,
            capture=True,
        )
        lines = (completed.stdout or "").splitlines()
        status = int(lines[0]) if lines and lines[0].isdigit() else None
        effective_url = lines[1] if len(lines) > 1 else ""
        content_type = lines[2] if len(lines) > 2 else ""
        remote_ip = lines[3] if len(lines) > 3 else ""
        try:
            time_connect = float(lines[4]) if len(lines) > 4 else 0.0
        except ValueError:
            time_connect = 0.0
        try:
            body = body_path.read_text(encoding="utf-8", errors="replace")[:131072]
        except OSError:
            body = ""
        try:
            headers = header_path.read_text(encoding="utf-8", errors="replace")[:32768]
        except OSError:
            headers = ""
        final_host = urllib.parse.urlsplit(effective_url).hostname or ""
        try:
            ipaddress.ip_address(final_host)
        except ValueError:
            pass
        else:
            final_host = "IP_LITERAL_REDACTED"
        return {
            "curl_code": completed.returncode,
            "http_status": status,
            "final_host": final_host,
            "content_type": content_type,
            "remote_ip": remote_ip,
            "time_connect": time_connect,
            "body_excerpt": body,
            "headers_excerpt": headers,
        }
    finally:
        body_path.unlink(missing_ok=True)
        header_path.unlink(missing_ok=True)


def probe_url_with_retries(
    url: str,
    request_url: Any,
    *,
    attempts: int = PROBE_REQUEST_ATTEMPTS,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"curl_code": 1}
    for _ in range(attempts):
        evidence = request_url(url)
        if evidence_transport_result(evidence) is None:
            break
    return evidence


def parse_egress_metadata(
    evidence: dict[str, Any], run_key: bytes
) -> tuple[str | None, str | int | None, str | None]:
    try:
        payload = json.loads(str(evidence.get("body_excerpt", "")))
    except json.JSONDecodeError:
        return None, None, None
    if not isinstance(payload, dict):
        return None, None, None
    ip_value = payload.get("clientIp") or payload.get("ip")
    country = (
        payload.get("country")
        or payload.get("countryCode")
        or payload.get("country_code")
    )
    connection = payload.get("connection")
    asn = payload.get("asn")
    if asn is None and isinstance(connection, dict):
        asn = connection.get("asn")
    if isinstance(asn, str) and asn.upper().startswith("AS") and asn[2:].isdigit():
        asn = int(asn[2:])
    if not isinstance(ip_value, str):
        return str(country or "") or None, asn, None
    try:
        ipaddress.ip_address(ip_value)
    except ValueError:
        return str(country or "") or None, asn, None
    ip_hash = hmac.new(run_key, ip_value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return str(country or "") or None, asn, ip_hash


def classify_base(
    metadata: dict[str, Any], generate_204: dict[str, Any]
) -> str:
    for evidence in (metadata, generate_204):
        transport = evidence_transport_result(evidence)
        if transport:
            return transport
    metadata_status = metadata.get("http_status")
    if not isinstance(metadata_status, int) or not 200 <= metadata_status < 400:
        return "FAIL_TRANSPORT"
    if generate_204.get("http_status") != 204:
        return "FAIL_TRANSPORT"
    return "BASE_PASS"


def evidence_response_class(evidence: dict[str, Any]) -> str:
    text = "\n".join(
        str(evidence.get(key, "")).lower()
        for key in ("body_excerpt", "headers_excerpt", "final_host", "content_type")
    )
    if any(marker in text for marker in REGION_FAILURE_MARKERS):
        return "REGION_BLOCK"
    if any(marker in text for marker in CHALLENGE_MARKERS):
        return "CHALLENGE"
    if evidence.get("http_status") == 401 or any(marker in text for marker in AUTH_MARKERS):
        return "AUTH"
    if "accounts.google.com" in str(evidence.get("final_host", "")):
        return "LOGIN_REACHABLE"
    return "HTTP_RESPONSE" if evidence.get("http_status") is not None else "NO_HTTP_RESPONSE"


def safe_evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "http_status": evidence.get("http_status"),
        "final_host": evidence.get("final_host"),
        "content_type": evidence.get("content_type"),
        "response_class": evidence_response_class(evidence),
        "transport_result": evidence_transport_result(evidence),
    }


def probe_nodes_with_runner(
    proxies: Sequence[dict[str, Any]],
    *,
    switch_node: Any,
    request_url: Any,
    sleep_fn: Any = time.sleep,
    monotonic_fn: Any = time.monotonic,
    run_timeout_seconds: int = PROBE_RUN_TIMEOUT_SECONDS,
    run_key: bytes | None = None,
) -> dict[str, Any]:
    started = monotonic_fn()
    deadline = started + run_timeout_seconds
    observed_at = iso_now()
    run_key = run_key or secrets.token_bytes(32)
    results: list[dict[str, Any]] = []
    stopped_due_deadline = False

    for proxy in proxies:
        if monotonic_fn() >= deadline:
            stopped_due_deadline = True
            break
        name = str(proxy["name"])
        selector_confirmed = bool(switch_node(name))
        item: dict[str, Any] = {
            "name": name,
            "selector_confirmed": selector_confirmed,
            "observed_at": observed_at,
            "services": {},
        }
        if not selector_confirmed:
            item["base_result"] = "NODE_SWITCH_UNCONFIRMED"
            item["reason_code"] = "NODE_SWITCH_UNCONFIRMED"
            for service in SERVICE_KEYS:
                item["services"][service] = {
                    "raw_result": "NODE_SWITCH_UNCONFIRMED",
                    "override": None,
                    "final_result": "NODE_SWITCH_UNCONFIRMED",
                    "evidence": {},
                }
            results.append(item)
            continue

        sleep_fn(PROBE_SWITCH_WAIT_SECONDS)
        metadata: dict[str, Any] = {"curl_code": 1}
        country: str | None = None
        asn: str | int | None = None
        ip_hash: str | None = None
        for metadata_url in EGRESS_METADATA_ENDPOINTS:
            metadata = probe_url_with_retries(metadata_url, request_url)
            country, asn, ip_hash = parse_egress_metadata(metadata, run_key)
            if (
                isinstance(metadata.get("http_status"), int)
                and 200 <= metadata["http_status"] < 400
                and country
                and asn is not None
                and ip_hash
            ):
                break
        generate_204 = probe_url_with_retries(
            "https://www.gstatic.com/generate_204", request_url
        )
        base_result = classify_base(metadata, generate_204)
        item.update(
            {
                "base_result": base_result,
                "egress_country": country,
                "egress_asn": asn,
                "egress_ip_hash": ip_hash,
                "base_evidence": {
                    "metadata": safe_evidence_summary(metadata),
                    "generate_204": safe_evidence_summary(generate_204),
                },
            }
        )

        for service in SERVICE_KEYS:
            if base_result != "BASE_PASS":
                raw_result = "FAIL_TRANSPORT"
                main: dict[str, Any] = {}
                support: dict[str, Any] = {}
            else:
                main_url, support_url = SERVICE_ENDPOINTS[service]
                main = probe_url_with_retries(main_url, request_url)
                support = probe_url_with_retries(support_url, request_url)
                raw_result = classify_service_evidence(service, main, support)
            calibrated = apply_manual_override(service, name, raw_result)
            item["services"][service] = {
                **calibrated,
                "evidence": {
                    "main": safe_evidence_summary(main) if main else {},
                    "support": safe_evidence_summary(support) if support else {},
                },
            }
        item["reason_code"] = ",".join(
            f"{service}:{item['services'][service]['final_result']}"
            for service in SERVICE_KEYS
        )
        results.append(item)

    probable_recapture = probable_unified_egress(results)
    return {
        "schema_version": PROBE_SCHEMA_VERSION,
        "probe_version": PROBE_VERSION,
        "run_id": uuid.uuid4().hex,
        "run_timestamp": observed_at,
        "stopped_due_deadline": stopped_due_deadline,
        "probable_tun_or_upstream_recapture": probable_recapture,
        "nodes": results,
    }


def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def find_probe_core(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_file() and os.access(path, os.X_OK):
            return path
        raise ConfigError(f"BLOCKED_LOCAL_PROBE_CORE_MISSING: {path}")
    for candidate in PROBE_CORE_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    for executable in ("mihomo", "clash-meta"):
        found = shutil.which(executable)
        if found:
            return Path(found).resolve()
    raise ConfigError("BLOCKED_LOCAL_PROBE_CORE_MISSING")


def parse_default_interface(route_output: str) -> str:
    match = re.search(r"^\s*interface:\s*(\S+)\s*$", route_output, re.MULTILINE)
    if not match:
        raise ConfigError("BLOCKED_NO_PHYSICAL_INTERFACE")
    return match.group(1)


def is_safe_physical_interface(interface_name: str) -> bool:
    lowered = interface_name.lower()
    return interface_name.startswith("en") and not lowered.startswith(
        ("utun", "lo", "tun", "mihomo", "clash")
    )


def interface_is_active(interface_name: str, *, runner: Any = subprocess.run) -> bool:
    ifconfig = shutil.which("ifconfig") or "/sbin/ifconfig"
    try:
        completed = runner(
            [ifconfig, interface_name],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and bool(
        re.search(r"^\s*status:\s*active\s*$", completed.stdout, re.MULTILINE)
    )


def find_probe_interface(*, runner: Any = subprocess.run) -> str:
    if interface_is_active("en0", runner=runner):
        return "en0"
    route = shutil.which("route") or "/sbin/route"
    try:
        completed = runner(
            [route, "-n", "get", "default"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        candidate = parse_default_interface(completed.stdout)
    except (OSError, subprocess.SubprocessError, ConfigError) as exc:
        raise ConfigError("BLOCKED_NO_PHYSICAL_INTERFACE") from exc
    if not is_safe_physical_interface(candidate) or not interface_is_active(
        candidate, runner=runner
    ):
        raise ConfigError("BLOCKED_NO_PHYSICAL_INTERFACE")
    return candidate


def build_probe_config(
    proxies: Sequence[dict[str, Any]],
    *,
    mixed_port: int,
    controller_port: int,
    interface_name: str,
) -> dict[str, Any]:
    return {
        "mixed-port": mixed_port,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "external-controller": f"127.0.0.1:{controller_port}",
        "secret": "",
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "interface-name": interface_name,
        "dns": {
            "enable": True,
            "ipv6": False,
            "nameserver": ["1.1.1.1", "8.8.8.8"],
        },
        "proxies": list(proxies),
        "proxy-groups": [
            {
                "name": "PROBE",
                "type": "select",
                "proxies": [str(proxy["name"]) for proxy in proxies],
            }
        ],
        "rules": ["MATCH,PROBE"],
    }


def controller_json_request(
    controller_port: int,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{controller_port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        body = response.read()
    if not body:
        return {}
    parsed = json.loads(body.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def wait_for_controller(controller_port: int, process: subprocess.Popen[Any]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ConfigError("Temporary Mihomo exited before controller became ready.")
        try:
            controller_json_request(controller_port, "/version", timeout=0.5)
            return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.1)
    raise ConfigError("Temporary Mihomo controller readiness timed out.")


def validate_probe_runtime(
    controller_port: int, *, request: Any = controller_json_request
) -> str | None:
    configs = request(controller_port, "/configs")
    rules = request(controller_port, "/rules").get("rules", [])
    global_proxy = request(controller_port, "/proxies/GLOBAL")
    if configs.get("mode") != "rule":
        raise ConfigError("BLOCKED_PROBE_ROUTE_UNCONFIRMED")
    if (
        not rules
        or str(rules[-1].get("type", "")).upper() != "MATCH"
        or rules[-1].get("proxy") != "PROBE"
    ):
        raise ConfigError("BLOCKED_PROBE_ROUTE_UNCONFIRMED")
    return global_proxy.get("now")


def select_probe_node(
    controller_port: int,
    name: str,
    *,
    request: Any = controller_json_request,
) -> bool:
    selector_path = "/proxies/" + urllib.parse.quote("PROBE", safe="")
    try:
        request(
            controller_port,
            selector_path,
            method="PUT",
            payload={"name": name},
        )
        selected = request(controller_port, selector_path)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False
    return selected.get("now") == name


def run_local_service_probe(
    data: dict[str, Any],
    *,
    core_path: str | None = None,
) -> dict[str, Any]:
    proxies = static_proxy_objects(data)
    core = find_probe_core(core_path)
    interface_name = find_probe_interface()
    mixed_port = reserve_loopback_port()
    controller_port = reserve_loopback_port()

    with tempfile.TemporaryDirectory(prefix="openclash-service-probe-") as temporary:
        workdir = Path(temporary)
        config_path = workdir / "probe.yaml"
        log_path = workdir / "mihomo.log"
        config = build_probe_config(
            proxies,
            mixed_port=mixed_port,
            controller_port=controller_port,
            interface_name=interface_name,
        )
        dump_yaml(config, config_path)
        os.chmod(config_path, 0o600)
        process: subprocess.Popen[Any] | None = None
        with log_path.open("w", encoding="utf-8") as log_handle:
            os.chmod(log_path, 0o600)
            try:
                validation = subprocess.run(
                    [str(core), "-t", "-d", str(workdir), "-f", str(config_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    check=False,
                )
                if validation.returncode != 0:
                    raise ConfigError("BLOCKED_TEMP_MIHOMO_CONFIG_INVALID")
                process = subprocess.Popen(
                    [str(core), "-d", str(workdir), "-f", str(config_path)],
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                wait_for_controller(controller_port, process)
                global_now = validate_probe_runtime(controller_port)

                def switch_node(name: str) -> bool:
                    return select_probe_node(controller_port, name)

                def request_url(url: str) -> dict[str, Any]:
                    return curl_probe_once(url, mixed_port, workdir=workdir)

                report = probe_nodes_with_runner(
                    proxies,
                    switch_node=switch_node,
                    request_url=request_url,
                )
                report["probe_transport"] = {
                    "mode": "rule",
                    "interface_name": interface_name,
                    "route": "MATCH,PROBE",
                    "global_now_observed": global_now,
                    "request_path": "loopback_mixed_proxy",
                }
                return report
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


def validate_probe_report_safe(report: dict[str, Any]) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in REPORT_FORBIDDEN_KEYS:
                    raise ConfigError(f"Probe report contains forbidden key: {key}")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for candidate in re.findall(r"[0-9A-Fa-f:.]{3,}", value):
                try:
                    ipaddress.ip_address(candidate.strip(".:"))
                except ValueError:
                    continue
                raise ConfigError("Probe report contains a full egress IP address.")

    walk(report)


def dynamic_probe_and_select(
    data: dict[str, Any],
    *,
    state_path: Path,
    report_path: Path,
    core_path: str | None,
    update_lkg: bool,
    probe_runner: Any = run_local_service_probe,
) -> tuple[dict[str, dict[str, list[str]]], dict[str, Any]]:
    legacy_config = transform(data)
    state, seed_source = load_or_seed_lkg_state(
        state_path, legacy_config, persist_seed=update_lkg
    )
    report = probe_runner(data, core_path=core_path)
    proxies = static_proxy_objects(data)
    current_names = [str(proxy["name"]) for proxy in proxies]
    source_order = {name: index for index, name in enumerate(current_names)}
    probable_recapture = bool(report.get("probable_tun_or_upstream_recapture"))
    selections, new_state, enriched = merge_lkg_results(
        current_names,
        source_order,
        state,
        report.get("nodes", []),
        probable_recapture=probable_recapture,
        observed_at=str(report["run_timestamp"]),
    )
    report["nodes"] = enriched
    report["lkg_seed_source"] = seed_source
    report["lkg_state_updated"] = update_lkg and not probable_recapture
    report["service_groups"] = selections
    validate_probe_report_safe(report)
    atomic_write_json(report, report_path)
    written_report = load_json_object(report_path)
    if update_lkg and not probable_recapture:
        atomic_write_json(new_state, state_path, private_parent=True)
        load_json_object(state_path)
    return selections, written_report


def fallback_group(name: str, proxies: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "type": "fallback",
        "proxies": proxies,
        "url": "https://www.gstatic.com/generate_204",
        "interval": 60,
        "lazy": True,
        "timeout": 5000,
        "max-failed-times": 1,
    }


def build_groups(
    all_nodes: list[str],
    gpt_nodes: list[str],
    gemini_nodes: list[str],
    disney_nodes: list[str],
) -> list[dict[str, Any]]:
    return [
        {"name": "默认代理", "type": "select", "proxies": ["手动选择", "自动选择"]},
        {"name": "手动选择", "type": "select", "proxies": ["自动选择", *all_nodes]},
        fallback_group("自动选择", all_nodes),
        {"name": "GPT专用", "type": "select", "proxies": ["GPT手动", "GPT自动"]},
        {"name": "GPT手动", "type": "select", "proxies": ["GPT自动", *gpt_nodes]},
        fallback_group("GPT自动", gpt_nodes),
        {"name": "Gemini专用", "type": "select", "proxies": ["Gemini手动", "Gemini自动"]},
        {"name": "Gemini手动", "type": "select", "proxies": ["Gemini自动", *gemini_nodes]},
        fallback_group("Gemini自动", gemini_nodes),
        {"name": "迪士尼", "type": "select", "proxies": ["迪士尼手动", "迪士尼自动"]},
        {"name": "迪士尼手动", "type": "select", "proxies": ["迪士尼自动", *disney_nodes]},
        fallback_group("迪士尼自动", disney_nodes),
    ]


def rule_target(rule: str) -> str | None:
    parts = [part.strip() for part in rule.split(",")]
    if not parts:
        return None
    if parts[0].upper() == "MATCH":
        return parts[1] if len(parts) > 1 else None
    if parts[-1].lower() == "no-resolve":
        return parts[-2] if len(parts) >= 3 else None
    return parts[-1] if len(parts) >= 2 else None


def build_rules(data: dict[str, Any]) -> list[str]:
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise ConfigError("'rules' must be a list.")

    preserved: list[str] = []
    for rule in rules:
        if not isinstance(rule, str):
            continue
        stripped = rule.strip()
        target = rule_target(stripped)
        if stripped.upper().startswith("MATCH,"):
            continue
        # Replace older default-group name.
        stripped = stripped.replace(",顺畅网络", ",默认代理")
        # Service rules are regenerated from the accepted narrow rule set.
        if target in {"GPT专用", "Gemini专用", "迪士尼"}:
            continue
        preserved.append(stripped)

    return ordered_unique([*SERVICE_RULES, *preserved, "MATCH,默认代理"])


def validate_config(data: dict[str, Any]) -> None:
    proxies = static_proxy_objects(data)
    proxy_names = {str(proxy["name"]) for proxy in proxies}

    groups = data.get("proxy-groups")
    if not isinstance(groups, list):
        raise ConfigError("'proxy-groups' must be a list.")
    group_names = [group.get("name") for group in groups if isinstance(group, dict)]
    if group_names != list(MANAGED_GROUP_NAMES):
        raise ConfigError(
            "Managed groups do not match the accepted 12-group structure: "
            + ", ".join(str(name) for name in group_names)
        )
    if len(set(group_names)) != len(group_names):
        raise ConfigError("Duplicate proxy-group names detected.")
    if any("优先│" in str(name) or "优先｜" in str(name) for name in group_names):
        raise ConfigError("Per-node priority wrapper groups are forbidden.")

    group_name_set = set(group_names)
    graph: dict[str, list[str]] = {str(name): [] for name in group_names}
    errors: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            errors.append("proxy-groups contains a non-object item")
            continue
        name = str(group.get("name", "<unnamed>"))
        refs = group.get("proxies")
        if not isinstance(refs, list):
            errors.append(f"group '{name}' has a non-list proxies field")
            continue
        for ref in refs:
            if not isinstance(ref, str):
                errors.append(f"group '{name}' contains a non-string target")
                continue
            if ref not in proxy_names and ref not in group_name_set and ref not in BUILTIN_TARGETS:
                errors.append(f"group '{name}' references missing target '{ref}'")
            if ref in group_name_set:
                graph[name].append(ref)

    visiting: set[str] = set()
    visited: set[str] = set()

    def has_cycle(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for child in graph[node]:
            if has_cycle(child):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    if any(has_cycle(node) for node in graph):
        errors.append("proxy-group reference cycle detected")

    rules = data.get("rules")
    if not isinstance(rules, list):
        errors.append("'rules' must be a list")
    else:
        for rule in rules:
            if not isinstance(rule, str):
                errors.append("rules contains a non-string item")
                continue
            target = rule_target(rule)
            if target and target not in proxy_names and target not in group_name_set and target not in BUILTIN_TARGETS:
                errors.append(f"rule references missing target '{target}': {rule}")
        matches = [rule for rule in rules if isinstance(rule, str) and rule.upper().startswith("MATCH,")]
        if matches != ["MATCH,默认代理"] or not rules or rules[-1] != "MATCH,默认代理":
            errors.append(f"final MATCH must be exactly MATCH,默认代理; got {matches}")

    if errors:
        raise ConfigError("Validation failed:\n- " + "\n- ".join(errors))


def transform(
    data: dict[str, Any],
    service_selections: dict[str, dict[str, list[str]]] | None = None,
) -> dict[str, Any]:
    output = remove_clash_verge_runtime(deepcopy(data))
    proxies = static_proxy_objects(output)
    output["proxies"] = proxies
    names = [str(proxy["name"]) for proxy in proxies]
    source_order = {name: index for index, name in enumerate(names)}

    all_nodes = stable_region_sort(names, source_order)
    if service_selections is None:
        gpt_nodes = stable_region_sort(
            resolve_candidates(names, GPT_CANDIDATES, label="GPT"), source_order
        )
        gemini_nodes = stable_region_sort(
            resolve_candidates(names, GEMINI_CANDIDATES, label="Gemini"),
            source_order,
            gemini=True,
        )
        disney_nodes = stable_region_sort(
            resolve_candidates(names, DISNEY_CANDIDATES, label="Disney"), source_order
        )
    else:
        gpt_nodes = list(service_selections["gpt"]["automatic"])
        gemini_nodes = list(service_selections["gemini"]["automatic"])
        disney_nodes = list(service_selections["disney"]["automatic"])

    output["proxy-groups"] = build_groups(all_nodes, gpt_nodes, gemini_nodes, disney_nodes)
    if service_selections is not None:
        groups_by_name = {group["name"]: group for group in output["proxy-groups"]}
        for service, (_, manual_name) in SERVICE_GROUP_NAMES.items():
            groups_by_name[manual_name]["proxies"].extend(
                service_selections[service]["manual_candidates"]
            )
    output["rules"] = build_rules(output)

    validate_config(output)
    return output


def remove_clash_verge_runtime(value: Any, *, top_level: bool = True) -> Any:
    """Drop Clash Verge process-local fields without touching proxy connection fields."""
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            if (cleaned := remove_clash_verge_runtime(item, top_level=False)) is not _DROP_RUNTIME
        ]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            is_temporary_runtime_key = (
                lowered.startswith("probe-")
                or lowered.startswith("probe_")
                or lowered.startswith("controller-")
                or lowered.startswith("controller_")
                or lowered.startswith("temporary-probe")
                or lowered.startswith("temporary_probe")
                or lowered.startswith("temporary-controller")
                or lowered.startswith("temporary_controller")
            )
            if (top_level and lowered in CLASH_VERGE_TOP_LEVEL_RUNTIME_KEYS) or is_temporary_runtime_key:
                continue
            cleaned = remove_clash_verge_runtime(item, top_level=False)
            if cleaned is not _DROP_RUNTIME:
                result[key] = cleaned
        return result
    if isinstance(value, str) and (value == "/tmp/verge" or value.startswith("/tmp/verge/")):
        return _DROP_RUNTIME
    return value


def redact_value(value: Any, *, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, list):
        return [redact_value(item, path=path) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            provider_url = lowered == "url" and "proxy-providers" in path
            if lowered in SENSITIVE_KEYS or provider_url:
                if lowered == "port":
                    result[key] = 0
                elif lowered == "uuid":
                    result[key] = "00000000-0000-0000-0000-000000000000"
                else:
                    result[key] = "REDACTED"
            else:
                result[key] = redact_value(item, path=(*path, lowered))
        return result
    return value


def make_audit_copy(data: dict[str, Any]) -> dict[str, Any]:
    return redact_value(deepcopy(data))


def export_source(source: Path | None, workdir: Path) -> Path:
    source = source or find_default_source()
    source = source.expanduser().resolve()
    if not source.is_file():
        raise ConfigError(f"Source does not exist: {source}")
    workdir.mkdir(parents=True, exist_ok=True)
    destination = workdir / f"clash-verge-effective-{now_stamp()}.yaml"
    shutil.copy2(source, destination)
    os.chmod(destination, 0o600)
    return destination


def transform_file(
    input_path: Path,
    output_path: Path,
    audit_output: Path | None,
    service_selections: dict[str, dict[str, list[str]]] | None = None,
) -> dict[str, Any]:
    transformed = transform(load_yaml(input_path), service_selections)
    dump_yaml(transformed, output_path)
    # Reparse the actual written file before reporting success.
    validate_config(load_yaml(output_path))

    if audit_output is not None:
        dump_yaml(make_audit_copy(transformed), audit_output)
        load_yaml(audit_output)
    return transformed


def quote_remote(value: str) -> str:
    return shlex.quote(value)


def ssh_command(host: str, command: str, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command],
        capture=capture,
    )


def read_remote_openclash_state(host: str) -> dict[str, str | bool]:
    command = (
        "OPENCLASH_STATE_READ=1; set -e; "
        "active_path=\"$(uci -q get openclash.config.config_path)\"; "
        "[ -n \"$active_path\" ]; "
        "case \"$active_path\" in /*) ;; *) exit 1 ;; esac; "
        "printf 'active_path=%s\\n' \"$active_path\"; "
        "if [ -f \"$active_path\" ]; then printf 'active_exists=1\\n'; "
        "else printf 'active_exists=0\\n'; fi; "
        "if /etc/init.d/openclash enabled >/dev/null 2>&1; then printf 'enabled=1\\n'; "
        "else printf 'enabled=0\\n'; fi; "
        "if /etc/init.d/openclash running >/dev/null 2>&1; then printf 'running=1\\n'; "
        "else printf 'running=0\\n'; fi"
    )
    try:
        result = ssh_command(host, command, capture=True)
    except subprocess.CalledProcessError as exc:
        raise ConfigError("REMOTE_ACTIVE_CONFIG_PATH_READ_FAILED") from exc

    values: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"active_path", "active_exists", "enabled", "running"}:
            values[key] = value

    if set(values) != {"active_path", "active_exists", "enabled", "running"}:
        raise ConfigError("REMOTE_ACTIVE_CONFIG_PATH_READ_FAILED: incomplete state")
    active_path = values["active_path"]
    if not active_path.startswith("/") or "\n" in active_path:
        raise ConfigError("REMOTE_ACTIVE_CONFIG_PATH_READ_FAILED: invalid path")
    for key in ("active_exists", "enabled", "running"):
        if values[key] not in {"0", "1"}:
            raise ConfigError(f"REMOTE_ACTIVE_CONFIG_PATH_READ_FAILED: invalid {key}")

    return {
        "active_path": active_path,
        "active_exists": values["active_exists"] == "1",
        "enabled": values["enabled"] == "1",
        "running": values["running"] == "1",
    }


def verify_remote_health(
    host: str,
    *,
    remote_path: str,
    core_path: str,
    attempts: int = HEALTH_CHECK_ATTEMPTS,
    delay_seconds: int = HEALTH_CHECK_DELAY_SECONDS,
) -> None:
    if attempts < 1:
        raise ConfigError("HEALTH_CHECK_FAILED: attempts must be at least 1")
    command = (
        "OPENCLASH_HEALTH_CHECK=1; set -e; "
        "/etc/init.d/openclash running >/dev/null 2>&1; "
        "active_path=\"$(uci -q get openclash.config.config_path)\"; "
        "[ -n \"$active_path\" ]; "
        f"[ \"$active_path\" = {quote_remote(remote_path)} ]; "
        f"{quote_remote(core_path)} -t -d /etc/openclash -f \"$active_path\"; "
        "proxy_port=''; "
        "for option in mixed_port http_port; do "
        "candidate=\"$(uci -q get openclash.config.$option 2>/dev/null || true)\"; "
        "case \"$candidate\" in ''|*[!0-9]*) ;; *) proxy_port=\"$candidate\"; break ;; esac; "
        "done; "
        "runtime_path=\"/etc/openclash/$(basename \"$active_path\")\"; "
        "if [ -z \"$proxy_port\" ]; then "
        "for config_path in \"$runtime_path\" \"$active_path\"; do "
        "[ -f \"$config_path\" ] || continue; "
        "proxy_port=\"$(sed -n 's/^mixed-port:[[:space:]]*\\([0-9][0-9]*\\).*$/\\1/p' \"$config_path\" | head -n 1)\"; "
        "[ -n \"$proxy_port\" ] || proxy_port=\"$(sed -n 's/^port:[[:space:]]*\\([0-9][0-9]*\\).*$/\\1/p' \"$config_path\" | head -n 1)\"; "
        "[ -n \"$proxy_port\" ] && break; "
        "done; fi; "
        "case \"$proxy_port\" in ''|*[!0-9]*) exit 1 ;; esac; "
        "[ \"$proxy_port\" -ge 1 ] && [ \"$proxy_port\" -le 65535 ]; "
        "if command -v ss >/dev/null 2>&1; then "
        "ss -lnt | awk -v port=\"$proxy_port\" '$4 ~ (\":\" port \"$\") {found=1} END {exit !found}'; "
        "elif command -v netstat >/dev/null 2>&1; then "
        "netstat -lnt | awk -v port=\"$proxy_port\" '$4 ~ (\":\" port \"$\") {found=1} END {exit !found}'; "
        "else exit 1; fi; "
        "http_code=\"$(curl --proxy \"http://127.0.0.1:${proxy_port}\" "
        "--connect-timeout 3 --max-time 8 --silent --output /dev/null "
        "--write-out '%{http_code}' https://www.gstatic.com/generate_204)\"; "
        "[ \"$http_code\" = '204' ]"
    )
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(attempts):
        try:
            ssh_command(host, command, capture=True)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
    raise ConfigError(f"HEALTH_CHECK_FAILED after {attempts} attempts") from last_error


def rollback_remote_deployment(
    host: str,
    *,
    remote_path: str,
    target_backup: str,
    target_absent_marker: str,
    original_active_path: str,
    original_active_exists: bool,
    active_backup: str,
    uci_backup: str,
    service_state_backup: str,
    core_path: str,
    original_enabled: bool,
    original_running: bool,
) -> None:
    restore_parts = [
        "OPENCLASH_ROLLBACK=1; set -e",
        (
            f"if [ -f {quote_remote(target_absent_marker)} ]; then "
            f"rm -f {quote_remote(remote_path)}; else "
            f"cp -p {quote_remote(target_backup)} {quote_remote(remote_path)}; "
            f"chmod 600 {quote_remote(remote_path)}; fi"
        ),
        (
            f"cp -p {quote_remote(active_backup)} {quote_remote(original_active_path)}; "
            f"chmod 600 {quote_remote(original_active_path)}"
            if original_active_exists
            else f"rm -f {quote_remote(original_active_path)}"
        ),
        f"cp -p {quote_remote(uci_backup)} /etc/config/openclash",
        (
            "/etc/init.d/openclash enable"
            if original_enabled
            else "/etc/init.d/openclash disable"
        ),
        (
            "/etc/init.d/openclash restart"
            if original_running
            else "/etc/init.d/openclash stop"
        ),
    ]
    try:
        ssh_command(host, "; ".join(restore_parts))
    except subprocess.CalledProcessError as exc:
        raise ConfigError("ROLLBACK_FAILED: restore command failed") from exc

    verify_parts = [
        "OPENCLASH_ROLLBACK_VERIFY=1; set -e",
        (
            f"if [ -f {quote_remote(target_absent_marker)} ]; then "
            f"[ ! -e {quote_remote(remote_path)} ]; else "
            f"cmp -s {quote_remote(target_backup)} {quote_remote(remote_path)}; fi"
        ),
        f"cmp -s {quote_remote(uci_backup)} /etc/config/openclash",
        f"[ \"$(uci -q get openclash.config.config_path)\" = {quote_remote(original_active_path)} ]",
        (
            f"cmp -s {quote_remote(active_backup)} {quote_remote(original_active_path)}; "
            f"{quote_remote(core_path)} -t -d /etc/openclash -f {quote_remote(original_active_path)}"
            if original_active_exists
            else f"[ ! -e {quote_remote(original_active_path)} ]"
        ),
        (
            "/etc/init.d/openclash enabled >/dev/null 2>&1"
            if original_enabled
            else "! /etc/init.d/openclash enabled >/dev/null 2>&1"
        ),
        (
            "/etc/init.d/openclash running >/dev/null 2>&1"
            if original_running
            else "! /etc/init.d/openclash running >/dev/null 2>&1"
        ),
        f"grep -Fqx {quote_remote(f'active_path={original_active_path}')} {quote_remote(service_state_backup)}",
    ]
    try:
        ssh_command(host, "; ".join(verify_parts), capture=True)
    except subprocess.CalledProcessError as exc:
        raise ConfigError("ROLLBACK_FAILED: rollback verification failed") from exc


def deploy(
    local_file: Path,
    *,
    host: str,
    remote_name: str | None,
    core_path: str,
    activate: bool,
) -> str:
    local_file = local_file.expanduser().resolve()
    if not local_file.is_file():
        raise ConfigError(f"Output file does not exist: {local_file}")
    validate_config(load_yaml(local_file))

    filename = remote_name or local_file.name
    if "/" in filename or filename in {".", ".."}:
        raise ConfigError("--remote-name must be a plain filename.")

    remote_dir = "/etc/openclash/config"
    remote_path = f"{remote_dir}/{filename}"
    stamp = now_stamp()
    remote_tmp = f"/tmp/{filename}.upload.{stamp}"
    target_backup = f"/tmp/{filename}.target-yaml.{stamp}.bak"
    target_absent_marker = f"/tmp/{filename}.target-absent.{stamp}"
    active_backup = f"/tmp/{filename}.active-yaml.{stamp}.bak"
    uci_backup = f"/etc/config/openclash.bak.{stamp}"
    service_state_backup = f"/tmp/{filename}.service-state.{stamp}"

    original_state = read_remote_openclash_state(host)
    original_active_path = str(original_state["active_path"])
    original_active_exists = bool(original_state["active_exists"])
    original_enabled = bool(original_state["enabled"])
    original_running = bool(original_state["running"])

    active_snapshot = (
        f"[ -f {quote_remote(original_active_path)} ]; "
        f"cp -p {quote_remote(original_active_path)} {quote_remote(active_backup)}; "
        if original_active_exists
        else f"[ ! -e {quote_remote(original_active_path)} ]; "
    )
    snapshot = (
        "OPENCLASH_BACKUP=1; set -e; "
        f"rm -f {quote_remote(target_absent_marker)} {quote_remote(service_state_backup)}; "
        + active_snapshot
        +
        f"if [ -f {quote_remote(remote_path)} ]; then "
        f"cp -p {quote_remote(remote_path)} {quote_remote(target_backup)}; "
        f"else : > {quote_remote(target_absent_marker)}; fi; "
        f"cp -p /etc/config/openclash {quote_remote(uci_backup)}; "
        f"printf '%s\\n' {quote_remote(f'active_path={original_active_path}')} "
        f"{quote_remote(f'active_exists={int(original_active_exists)}')} "
        f"{quote_remote(f'enabled={int(original_enabled)}')} "
        f"{quote_remote(f'running={int(original_running)}')} > {quote_remote(service_state_backup)}"
    )
    try:
        ssh_command(host, snapshot)
    except subprocess.CalledProcessError as exc:
        raise ConfigError("Remote backup failed; deployment was not started.") from exc

    try:
        run(
            [
                "scp",
                "-O",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                str(local_file),
                f"{host}:{remote_tmp}",
            ]
        )
    except subprocess.CalledProcessError as exc:
        try:
            ssh_command(host, f"rm -f {quote_remote(remote_tmp)}", capture=True)
        except subprocess.CalledProcessError as cleanup_exc:
            raise ConfigError("REMOTE_UPLOAD_FAILED_AND_CLEANUP_FAILED") from cleanup_exc
        raise ConfigError("REMOTE_UPLOAD_FAILED; active configuration unchanged") from exc

    validate_and_install = (
        "set -e; "
        f"chmod 600 {quote_remote(remote_tmp)}; "
        f"{quote_remote(core_path)} -t -d /etc/openclash -f {quote_remote(remote_tmp)}; "
        f"mkdir -p {quote_remote(remote_dir)}; "
        f"mv -f {quote_remote(remote_tmp)} {quote_remote(remote_path)}; "
        f"chmod 600 {quote_remote(remote_path)}"
    )
    try:
        ssh_command(host, validate_and_install)
    except subprocess.CalledProcessError as exc:
        rollback_remote_deployment(
            host,
            remote_path=remote_path,
            target_backup=target_backup,
            target_absent_marker=target_absent_marker,
            original_active_path=original_active_path,
            original_active_exists=original_active_exists,
            active_backup=active_backup,
            uci_backup=uci_backup,
            service_state_backup=service_state_backup,
            core_path=core_path,
            original_enabled=original_enabled,
            original_running=original_running,
        )
        try:
            ssh_command(host, f"rm -f {quote_remote(remote_tmp)}", capture=True)
        except subprocess.CalledProcessError as cleanup_exc:
            raise ConfigError("REMOTE_CLEANUP_FAILED_AFTER_ROLLBACK") from cleanup_exc
        raise ConfigError("REMOTE_INSTALL_FAILED_ROLLED_BACK") from exc

    if activate:
        activate_cmd = (
            "set -e; "
            f"uci set openclash.config.config_path={quote_remote(remote_path)}; "
            "uci set openclash.config.enable='1'; "
            "uci commit openclash; "
            "/etc/init.d/openclash restart"
        )
        try:
            ssh_command(host, activate_cmd)
            verify_remote_health(host, remote_path=remote_path, core_path=core_path)
        except (subprocess.CalledProcessError, ConfigError) as exc:
            rollback_remote_deployment(
                host,
                remote_path=remote_path,
                target_backup=target_backup,
                target_absent_marker=target_absent_marker,
                original_active_path=original_active_path,
                original_active_exists=original_active_exists,
                active_backup=active_backup,
                uci_backup=uci_backup,
                service_state_backup=service_state_backup,
                core_path=core_path,
                original_enabled=original_enabled,
                original_running=original_running,
            )
            raise ConfigError("HEALTH_CHECK_FAILED_ROLLED_BACK") from exc

    return remote_path


def print_summary(data: dict[str, Any], output: Path, audit_output: Path | None) -> None:
    groups = {group["name"]: group for group in data["proxy-groups"]}
    print(f"output={output}")
    if audit_output is not None:
        print(f"audit_output={audit_output}")
    print(f"static_nodes={len(data['proxies'])}")
    print(f"managed_groups={len(data['proxy-groups'])}")
    print("priority_wrappers=0")
    print(f"gpt_nodes={len(groups['GPT自动']['proxies'])}")
    print(f"gemini_nodes={len(groups['Gemini自动']['proxies'])}")
    print(f"disney_nodes={len(groups['迪士尼自动']['proxies'])}")
    print("final_match=MATCH,默认代理")
    print("secrets_printed=false")


def print_probe_summary(report_path: Path) -> None:
    report = load_json_object(report_path)
    nodes = report.get("nodes", [])
    print(f"probe_report={report_path}")
    print(f"nodes_tested={len(nodes)}")
    print(f"selector_confirmed={sum(bool(node.get('selector_confirmed')) for node in nodes)}")
    signatures = {
        (node.get("egress_country"), node.get("egress_asn"), node.get("egress_ip_hash"))
        for node in nodes
        if node.get("egress_ip_hash")
    }
    print(f"unique_egress_signatures={len(signatures)}")
    print(
        "probable_tun_recapture="
        + str(bool(report.get("probable_tun_or_upstream_recapture"))).lower()
    )
    for service in SERVICE_KEYS:
        raw_pass = sum(
            node.get("services", {}).get(service, {}).get("raw_result") == "PASS"
            for node in nodes
        )
        final_count = len(report.get("service_groups", {}).get(service, {}).get("automatic", []))
        print(f"{service}_raw_pass={raw_pass}")
        print(f"{service}_final_group_count={final_count}")


def add_probe_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--probe-core")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_LKG_STATE_PATH)
    parser.add_argument("--probe-report", type=Path, default=DEFAULT_PROBE_REPORT_PATH)


def add_deploy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="root@192.168.10.1")
    parser.add_argument("--remote-name")
    parser.add_argument("--core-path", default="/etc/openclash/core/clash_meta")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Select the installed config through UCI and restart OpenClash after validation.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the accepted simple static OpenClash profile from Clash Verge."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser("export", help="Copy the current effective Clash Verge YAML.")
    export_p.add_argument("--source", type=Path)
    export_p.add_argument(
        "--workdir", type=Path, default=Path.home() / "Desktop/openclash-static-work"
    )

    transform_p = sub.add_parser("transform", help="Transform an effective YAML locally.")
    transform_p.add_argument("--input", type=Path, required=True)
    transform_p.add_argument("--output", type=Path, required=True)
    transform_p.add_argument("--audit-output", type=Path)

    all_p = sub.add_parser("all", help="Export and transform; optionally deploy.")
    all_p.add_argument("--source", type=Path)
    all_p.add_argument(
        "--workdir", type=Path, default=Path.home() / "Desktop/openclash-static-work"
    )
    all_p.add_argument("--output-name", default="openclash-simple-final.yaml")
    all_p.add_argument("--audit-name", default="openclash-simple-final-audit.yaml")
    all_p.add_argument("--deploy", action="store_true")
    add_probe_args(all_p)
    add_deploy_args(all_p)

    deploy_p = sub.add_parser("deploy", help="Validate and install an existing full YAML.")
    deploy_p.add_argument("--file", type=Path, required=True)
    add_deploy_args(deploy_p)

    probe_p = sub.add_parser(
        "probe", help="Test static nodes locally without generating or deploying OpenClash."
    )
    probe_p.add_argument("--source", type=Path)
    probe_p.add_argument("--update-lkg", action="store_true")
    add_probe_args(probe_p)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "export":
            exported = export_source(args.source, args.workdir.expanduser().resolve())
            print(f"exported={exported}")
            return 0

        if args.command == "transform":
            output = args.output.expanduser().resolve()
            audit_output = args.audit_output.expanduser().resolve() if args.audit_output else None
            data = transform_file(args.input.expanduser().resolve(), output, audit_output)
            print_summary(data, output, audit_output)
            return 0

        if args.command == "all":
            workdir = args.workdir.expanduser().resolve()
            exported = export_source(args.source, workdir)
            output = workdir / args.output_name
            audit_output = workdir / args.audit_name
            source_data = load_yaml(exported)
            selections, _ = dynamic_probe_and_select(
                source_data,
                state_path=args.state_path,
                report_path=args.probe_report,
                core_path=args.probe_core,
                update_lkg=True,
            )
            transform_file(exported, output, audit_output, selections)
            data = load_yaml(output)
            print(f"source_copy={exported}")
            print_summary(data, output, audit_output)
            print_probe_summary(args.probe_report)
            if args.deploy:
                remote = deploy(
                    output,
                    host=args.host,
                    remote_name=args.remote_name,
                    core_path=args.core_path,
                    activate=args.activate,
                )
                print(f"remote_config={remote}")
                print(f"activated={str(args.activate).lower()}")
            return 0

        if args.command == "probe":
            source = (args.source or find_default_source()).expanduser().resolve()
            source_data = load_yaml(source)
            dynamic_probe_and_select(
                source_data,
                state_path=args.state_path,
                report_path=args.probe_report,
                core_path=args.probe_core,
                update_lkg=args.update_lkg,
            )
            print_probe_summary(args.probe_report)
            print(f"lkg_updated={str(args.update_lkg).lower()}")
            print("router_contacted=false")
            return 0

        if args.command == "deploy":
            remote = deploy(
                args.file,
                host=args.host,
                remote_name=args.remote_name,
                core_path=args.core_path,
                activate=args.activate,
            )
            print(f"remote_config={remote}")
            print(f"activated={str(args.activate).lower()}")
            return 0

        parser.error("Unknown command")
        return 2
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: command failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
