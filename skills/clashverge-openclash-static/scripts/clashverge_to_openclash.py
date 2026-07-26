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
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence

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
    "GPT候选",
    "Gemini专用",
    "Gemini手动",
    "Gemini候选",
    "迪士尼",
    "迪士尼手动",
    "迪士尼候选",
)
OPTIONAL_HISTORY_GROUP_NAMES = ("GPT历史LKG", "Gemini历史LKG", "迪士尼历史LKG")

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
LAN_HEALTH_URL = "https://www.baidu.com/"
REMOTE_SIDECAR_MIXED_PORT = 17890
REMOTE_SIDECAR_CONTROLLER_PORT = 19090
REMOTE_SIDECAR_UID = 65534
REMOTE_SIDECAR_GID = 65534
REMOTE_CANDIDATE_DIR = "/etc/openclash/config/.clashverge-candidates"
LKG_SCHEMA_VERSION = 1
PROBE_SCHEMA_VERSION = 1
PROBE_VERSION = "3"
MANUAL_RESULT_SCHEMA_VERSION = 1
SOURCE_SNAPSHOT_SCHEMA_VERSION = 1
SOURCE_REFRESH_PROTOCOL_VERSION = 1
DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS = 24 * 60 * 60
DEFAULT_MIN_NODE_RETENTION_RATIO = 0.50
DEFAULT_SOURCE_IDENTITY_KEY = (
    Path.home() / ".hermes/state/clashverge-openclash-static/source-identity.key"
)
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
PASS_RESULTS = {
    "DEFINITIVE_AUTOMATED_PASS",
    "MANUAL_OVERRIDE_PASS",
    "PASS_SUPPORTED_REGION",
    "SCREEN_PASS",
    "PASS_WITH_SCREEN_FALSE_NEGATIVE",
}
PENDING_RESULTS = {
    "CHALLENGE_UNKNOWN",
    "AUTH_UNKNOWN",
    "UNKNOWN",
    "GEMINI_SCREEN_PASS",
    "SCREEN_NEGATIVE",
    "UNKNOWN_INCOMPLETE_PROBE",
    "UNKNOWN_RESPONSE_SCHEMA",
}
REMOVE_RESULTS = {
    "DEFINITIVE_AUTOMATED_FAIL",
    "DEFINITIVE_AUTOMATED_FAIL_UNSUPPORTED_REGION",
    "EVIDENCE_CONFLICT",
    "FAIL_REGION",
    "MANUAL_OVERRIDE_FAIL",
    "FAIL_FORBIDDEN_LOCATION",
    "FAIL_IP_BANNED",
    "FAIL_UNAVAILABLE",
    "GEMINI_SCREEN_FAIL",
}
SERVICE_GROUP_NAMES = {
    "gpt": ("GPT候选", "GPT手动"),
    "gemini": ("Gemini候选", "Gemini手动"),
    "disney": ("迪士尼候选", "迪士尼手动"),
}
EVIDENCE_TYPES = {
    "DEFINITIVE_AUTOMATED_PASS",
    "DEFINITIVE_AUTOMATED_FAIL",
    "MANUAL_FUNCTIONAL_PASS",
    "MANUAL_FUNCTIONAL_FAIL",
    "SCREEN_PASS",
    "SCREEN_NEGATIVE",
    "LKG_FALLBACK",
    "UNKNOWN",
}
FUNCTIONAL_RESULT_SCHEMA_VERSION = 1
SOURCE_REFRESH_OUTCOMES = {
    "SUCCESS_CHANGED",
    "SUCCESS_NOT_MODIFIED",
    "FAIL_AUTH",
    "FAIL_TRANSPORT",
    "FAIL_PARSE",
    "FAIL_TIMEOUT",
    "FAIL_SOURCE_IDENTITY",
    "FAIL_EMPTY_RESULT",
    "FAIL_PROFILE_NOT_FOUND",
    "FAIL_DOWNLOAD_DIRECT",
    "FAIL_DOWNLOAD_ALL_PATHS",
    "FAIL_SAVE",
    "FAIL_NONCE_REPLAY",
    "FAIL_NONCE_MISMATCH",
    "FAIL_APP_RUNNING_WITHOUT_ADAPTER",
    "FAIL_ADAPTER_BINARY_MISSING",
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
DEFINITIVE_MANUAL_METHODS = {
    "logged_in_browser_actual_generation",
    "logged_in_app_actual_generation",
    "logged_in_browser_actual_playback",
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


class DeploymentTransaction(NamedTuple):
    """Remote state required to put OpenClash and the LAN dataplane back."""

    remote_path: str
    target_backup: str
    target_absent_marker: str
    original_active_path: str
    original_active_exists: bool
    active_backup: str
    openclash_uci_backup: str
    dhcp_uci_backup: str
    firewall_uci_backup: str
    service_state_backup: str
    network_state_backup: str
    core_path: str
    original_enabled: bool
    original_running: bool
    original_core_running: bool
    original_network_artifacts: bool
    original_tun_present: bool


class UploadedCandidate(NamedTuple):
    candidate_path: str
    production_path: str


class RemoteSidecarSession(NamedTuple):
    mixed_port: int
    controller_port: int

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


def parse_aware_timestamp(value: str, *, field: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError(f"Invalid {field} timestamp.") from exc
    if parsed.tzinfo is None:
        raise ConfigError(f"{field} timestamp must include a timezone.")
    return parsed


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_or_create_identity_key(path: Path) -> bytes:
    path = path.expanduser().resolve()
    if path.exists():
        key = path.read_bytes()
        if len(key) < 32:
            raise ConfigError("STOP_SOURCE_SNAPSHOT_FAILED: identity key is too short")
        return key
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    key = secrets.token_bytes(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, key)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return key


def identity_hmac(key: bytes, value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def stable_node_identity(proxy: dict[str, Any], key: bytes) -> str:
    # The display name is deliberately excluded. Connection credentials remain only
    # inside the HMAC input and never enter manifests or logs.
    identity = {k: v for k, v in proxy.items() if k not in {"name", "udp"}}
    return "node_" + identity_hmac(key, identity)[:24]


def clash_verge_paths(source: Path | None = None) -> dict[str, Path]:
    effective = (source or find_default_source()).expanduser().resolve()
    base = effective.parent
    return {
        "effective": effective,
        "profiles": base / "profiles.yaml",
        "verge": base / "verge.yaml",
        "config": base / "config.yaml",
    }


def load_optional_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = load_yaml(path)
    return value if isinstance(value, dict) else {}


def capture_clash_verge_state(paths: dict[str, Path], key: bytes) -> dict[str, Any]:
    profiles = load_optional_yaml(paths["profiles"])
    verge = load_optional_yaml(paths["verge"])
    config = load_optional_yaml(paths["config"])
    current = profiles.get("current")
    items = profiles.get("items") if isinstance(profiles.get("items"), list) else []
    current_item = next(
        (
            item
            for item in items
            if isinstance(item, dict) and item.get("uid") == current
        ),
        None,
    )
    remote_items = [
        item for item in items if isinstance(item, dict) and item.get("type") == "remote"
    ]
    selection_hash = (
        identity_hmac(key, current_item.get("selected"))[:24]
        if current_item and current_item.get("selected") is not None
        else None
    )
    try:
        with socket.create_connection(("127.0.0.1", 33331), timeout=0.2):
            running = True
    except OSError:
        running = False
    try:
        route = subprocess.run(
            ["/usr/sbin/netstat", "-rn", "-f", "inet"],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
        default_route = next(
            (
                line.split()[:4]
                for line in route.stdout.splitlines()
                if line.split() and line.split()[0] == "default"
            ),
            None,
        )
        network_exit_hash = (
            identity_hmac(key, default_route)[:24]
            if route.returncode == 0 and default_route
            else None
        )
    except (OSError, subprocess.SubprocessError):
        network_exit_hash = None
    try:
        proxy_state = subprocess.run(
            ["/usr/sbin/scutil", "--proxy"],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
        proxy_enabled = any(
            line.strip().endswith(": 1")
            for line in proxy_state.stdout.splitlines()
            if any(
                line.strip().startswith(name)
                for name in ("HTTPEnable", "HTTPSEnable", "SOCKSEnable")
            )
        )
    except (OSError, subprocess.SubprocessError):
        proxy_enabled = None
    mihomo_running = False
    for name in ("verge-mihomo", "mihomo"):
        try:
            result = subprocess.run(
                ["/usr/bin/pgrep", "-x", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
            mihomo_running = mihomo_running or result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "running": running,
        "active_profile_id": identity_hmac(key, current)[:16] if current else None,
        "active_profile_type": current_item.get("type") if current_item else None,
        "active_profile_updated": current_item.get("updated") if current_item else None,
        "proxy_mode": config.get("mode"),
        "selected_node_state_hash": selection_hash,
        "system_proxy": verge.get("enable_system_proxy"),
        "system_proxy_effective": proxy_enabled,
        "tun": verge.get("enable_tun_mode"),
        "mihomo_running": mihomo_running,
        "mac_network_exit_state_hash": network_exit_hash,
        "bound_subscription_ids": [
            identity_hmac(key, item.get("uid"))[:16]
            for item in remote_items
            if item.get("uid") == current
        ],
        "profile_count": len(items),
    }


def active_remote_profile(paths: dict[str, Path]) -> dict[str, Any]:
    profiles = load_optional_yaml(paths["profiles"])
    current = profiles.get("current")
    items = profiles.get("items") if isinstance(profiles.get("items"), list) else []
    matches = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("uid") == current
        and item.get("type") == "remote"
    ]
    if len(matches) != 1 or not matches[0].get("url"):
        raise ConfigError("STOP_SOURCE_IDENTITY_DRIFT: active profile is not one remote subscription")
    return matches[0]


def safe_source_summary(source: Path, key: bytes) -> dict[str, Any]:
    data = load_yaml(source)
    proxies = static_proxy_objects(data)
    node_ids: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    for proxy in proxies:
        name = str(proxy["name"])
        node_id = stable_node_identity(proxy, key)
        if node_id in node_ids and node_ids[node_id] != name:
            raise ConfigError("STOP_SOURCE_SNAPSHOT_FAILED: stable node ID collision")
        node_ids[node_id] = name
        nodes.append(
            {
                "exact_node_name": name,
                "exact_node_id": node_id,
                "protocol": str(proxy.get("type", "unknown")),
            }
        )
    if not nodes:
        raise ConfigError("STOP_SOURCE_EMPTY")
    return {
        "source_hash": sha256_file(source),
        "node_count": len(nodes),
        "nodes": nodes,
    }


def run_source_refresh_adapter(
    adapter: Path,
    *,
    profile_uid: str,
    paths: dict[str, Path],
    timeout_seconds: int,
    staging_dir: Path,
) -> dict[str, Any]:
    adapter = adapter.expanduser().resolve()
    if not adapter.is_file() or not os.access(adapter, os.X_OK):
        raise ConfigError("STOP_SOURCE_REFRESH_FAILED: refresh adapter is not executable")
    request = {
        "protocol_version": SOURCE_REFRESH_PROTOCOL_VERSION,
        "action": "update_profile_source",
        "profile_uid": profile_uid,
        "profiles_path": str(paths["profiles"]),
        "effective_path": str(paths["effective"]),
        "snapshot_staging_dir": str(staging_dir),
    }
    try:
        completed = subprocess.run(
            [str(adapter)],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConfigError("STOP_SOURCE_REFRESH_FAILED: FAIL_TIMEOUT") from exc
    if completed.returncode != 0:
        raise ConfigError("STOP_SOURCE_REFRESH_FAILED: refresh adapter failed")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigError("STOP_SOURCE_REFRESH_FAILED: invalid adapter receipt") from exc
    if not isinstance(response, dict):
        raise ConfigError("STOP_SOURCE_REFRESH_FAILED: invalid adapter receipt")
    outcome = response.get("outcome")
    if outcome not in SOURCE_REFRESH_OUTCOMES:
        raise ConfigError("STOP_SOURCE_REFRESH_FAILED: unknown refresh outcome")
    if outcome not in {"SUCCESS_CHANGED", "SUCCESS_NOT_MODIFIED"}:
        raise ConfigError(f"STOP_SOURCE_REFRESH_FAILED: {outcome}")
    profile = active_remote_profile(paths)
    expected_identity = hashlib.sha256(
        profile_uid.encode() + b"\0" + str(profile["url"]).encode()
    ).hexdigest()[:16]
    if response.get("profile_identity") != expected_identity:
        raise ConfigError("STOP_SOURCE_IDENTITY_DRIFT")
    if response.get("source_identity_verified") is not True:
        raise ConfigError("STOP_SOURCE_IDENTITY_DRIFT")
    return response


def freeze_source_snapshot(
    source: Path,
    *,
    output_dir: Path,
    key: bytes,
    source_identity: str,
    refresh: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = safe_source_summary(source, key)
    snapshot_id = "snapshot_" + hashlib.sha256(
        (summary["source_hash"] + source_identity + str(refresh["completed_at"])).encode()
    ).hexdigest()[:24]
    payload_path = output_dir / f"{snapshot_id}.private.yaml"
    manifest_path = output_dir / f"{snapshot_id}.json"
    shutil.copyfile(source, payload_path)
    os.chmod(payload_path, 0o600)
    manifest = {
        "schema_version": SOURCE_SNAPSHOT_SCHEMA_VERSION,
        "source_snapshot_id": snapshot_id,
        "created_at": iso_now(),
        "refresh_started_at": refresh["started_at"],
        "refresh_completed_at": refresh["completed_at"],
        "source_identity": source_identity,
        "source_hash": summary["source_hash"],
        "source_snapshot_hash": summary["source_hash"],
        "node_count": summary["node_count"],
        "nodes": summary["nodes"],
        "source_diff_summary": refresh["diff_summary"],
        "refresh_outcome": refresh["outcome"],
        "source_age_seconds_at_snapshot": refresh.get("source_age_seconds", 0),
        "source_payload": payload_path.name,
    }
    atomic_write_json(manifest, manifest_path)
    return manifest_path, payload_path, manifest


def verify_source_snapshot(manifest_path: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest = load_json_object(manifest_path)
    if manifest.get("schema_version") != SOURCE_SNAPSHOT_SCHEMA_VERSION:
        raise ConfigError("STOP_SOURCE_SNAPSHOT_FAILED: unsupported schema")
    payload = (manifest_path.parent / str(manifest.get("source_payload", ""))).resolve()
    if payload.parent != manifest_path.parent or not payload.is_file():
        raise ConfigError("STOP_SOURCE_SNAPSHOT_FAILED: missing private payload")
    if sha256_file(payload) != manifest.get("source_hash"):
        raise ConfigError("STOP_SOURCE_SNAPSHOT_FAILED: payload hash mismatch")
    return manifest, payload


def prepare_source_snapshot(
    *,
    source: Path | None,
    workdir: Path,
    refresh_adapter: Path | None,
    no_refresh: bool,
    source_snapshot: Path | None,
    identity_key_path: Path,
    refresh_timeout: int,
    min_node_retention_ratio: float,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    if source_snapshot:
        manifest, payload = verify_source_snapshot(source_snapshot)
        return manifest, payload, {"live_source_reread_after_snapshot": False}
    key = load_or_create_identity_key(identity_key_path)
    paths = clash_verge_paths(source)
    profile = active_remote_profile(paths)
    before_state = capture_clash_verge_state(paths, key)
    before = safe_source_summary(paths["effective"], key)
    started_at = iso_now()
    if no_refresh:
        outcome = "SOURCE_REFRESH_SKIPPED_EXPLICITLY"
        receipt: dict[str, Any] = {}
    else:
        if refresh_adapter is None:
            raise ConfigError(
                "STOP_SOURCE_REFRESH_FAILED: Clash Verge 2.5.1 exposes update_profile only "
                "inside Tauri; configure the authenticated custom source-refresh bridge"
            )
        receipt = run_source_refresh_adapter(
            refresh_adapter,
            profile_uid=str(profile["uid"]),
            paths=paths,
            timeout_seconds=refresh_timeout,
            staging_dir=workdir / "source-refresh-staging",
        )
        outcome = str(receipt["outcome"])
    completed_at = iso_now()
    current_profile = active_remote_profile(paths)
    if current_profile.get("uid") != profile.get("uid"):
        raise ConfigError("STOP_SOURCE_IDENTITY_DRIFT")
    refreshed_snapshot: Path | None = None
    if no_refresh:
        snapshot_source = paths["effective"]
    else:
        refreshed_snapshot = Path(str(receipt.get("enhanced_snapshot_path", ""))).resolve()
        if refreshed_snapshot.parent != (workdir / "source-refresh-staging").resolve():
            raise ConfigError("STOP_SOURCE_REFRESH_FAILED: invalid enhanced snapshot path")
        if sha256_file(refreshed_snapshot) != receipt.get("enhanced_snapshot_hash"):
            raise ConfigError("STOP_SOURCE_REFRESH_FAILED: enhanced snapshot hash mismatch")
        snapshot_source = refreshed_snapshot
    try:
        after = safe_source_summary(snapshot_source, key)
    except ConfigError as exc:
        message = str(exc)
        if "No static nodes" in message or message == "STOP_SOURCE_EMPTY":
            raise ConfigError("STOP_SOURCE_EMPTY") from exc
        raise ConfigError("STOP_SOURCE_PARSE_FAILED") from exc
    if before["node_count"] and (
        after["node_count"] / before["node_count"] < min_node_retention_ratio
    ):
        raise ConfigError("STOP_SOURCE_REFRESH_FAILED: abnormal node-count collapse")
    if outcome == "SUCCESS_NOT_MODIFIED" and receipt.get("content_hash_before") != receipt.get(
        "content_hash_after"
    ):
        raise ConfigError("STOP_SOURCE_REFRESH_FAILED: NOT_MODIFIED receipt conflicts with source hash")
    after_state = capture_clash_verge_state(paths, key)
    preserved_keys = {
        "running",
        "active_profile_id",
        "active_profile_type",
        "proxy_mode",
        "selected_node_state_hash",
        "system_proxy",
        "system_proxy_effective",
        "tun",
        "mihomo_running",
        "bound_subscription_ids",
        "mac_network_exit_state_hash",
    }
    if {k: before_state.get(k) for k in preserved_keys} != {
        k: after_state.get(k) for k in preserved_keys
    }:
        raise ConfigError("STOP_CLASH_VERGE_STATE_DRIFT")
    source_identity = identity_hmac(key, profile.get("uid"))[:24]
    diff_summary = {
        "node_count_before": before["node_count"],
        "node_count_after": after["node_count"],
        "added": sorted(
            {n["exact_node_id"] for n in after["nodes"]}
            - {n["exact_node_id"] for n in before["nodes"]}
        ),
        "removed": sorted(
            {n["exact_node_id"] for n in before["nodes"]}
            - {n["exact_node_id"] for n in after["nodes"]}
        ),
    }
    manifest_path, payload, manifest = freeze_source_snapshot(
        snapshot_source,
        output_dir=workdir / "source-snapshots",
        key=key,
        source_identity=source_identity,
        refresh={
            "started_at": started_at,
            "completed_at": completed_at,
            "outcome": outcome,
            "diff_summary": diff_summary,
            "source_age_seconds": max(
                0, int(time.time() - snapshot_source.stat().st_mtime)
            ),
        },
    )
    runtime = {
        "manifest_path": str(manifest_path),
        "refresh_result": outcome,
        "clash_verge_state_before": before_state,
        "clash_verge_state_after": after_state,
        "clash_verge_state_preserved": True,
        "live_source_reread_after_snapshot": False,
        "router_contacted_before_snapshot": False,
        "source_hash_before": before["source_hash"],
        "source_hash_after": after["source_hash"],
        "download_path_used": receipt.get("download_path_used") if receipt else None,
    }
    refresh_report = {
        "source_refresh_implemented": True,
        "source_refresh_method": "custom_authenticated_loopback_bridge_reusing_clash_verge_profile_semantics",
        "bound_subscriptions": before_state["bound_subscription_ids"],
        "refresh_result": outcome,
        "refresh_started_at": started_at,
        "refresh_completed_at": completed_at,
        "source_identity_verified": (
            receipt.get("source_identity_verified") is True if receipt else True
        ),
        "adapter_profile_identity": receipt.get("profile_identity") if receipt else None,
        "download_path_used": receipt.get("download_path_used") if receipt else None,
        "raw_source_hash_before": receipt.get("content_hash_before") if receipt else None,
        "raw_source_hash_after": receipt.get("content_hash_after") if receipt else None,
        "raw_node_count_before": receipt.get("parsed_node_count_before") if receipt else None,
        "raw_node_count_after": receipt.get("parsed_node_count_after") if receipt else None,
        "adapter_started_at": receipt.get("started_at") if receipt else None,
        "adapter_completed_at": receipt.get("completed_at") if receipt else None,
        "source_hash_before": before["source_hash"],
        "source_hash_after": after["source_hash"],
        "node_count_before": before["node_count"],
        "node_count_after": after["node_count"],
        "source_diff_summary": diff_summary,
        "clash_verge_state_before": before_state,
        "clash_verge_state_after": after_state,
        "clash_verge_state_preserved": True,
        "source_snapshot_created": True,
        "source_snapshot_id": manifest["source_snapshot_id"],
        "source_snapshot_hash": manifest["source_snapshot_hash"],
        "source_snapshot_manifest": str(manifest_path),
        "live_source_reread_after_snapshot": False,
        "router_contacted_before_snapshot": False,
        "sensitive_data_scan": "STRUCTURAL_REDACTION_ENFORCED",
        "production_touched": False,
        "activation_recommendation": "BLOCKED_PENDING_DEFINITIVE_FUNCTIONAL_EVIDENCE",
    }
    refresh_report_path = workdir / f"source-refresh-report-{manifest['source_snapshot_id']}.json"
    atomic_write_json(refresh_report, refresh_report_path)
    if refreshed_snapshot is not None:
        refreshed_snapshot.unlink(missing_ok=True)
    runtime["report_path"] = str(refresh_report_path)
    return manifest, payload, runtime


def legacy_service_members(config: dict[str, Any]) -> dict[str, list[str]]:
    groups = {
        str(group.get("name")): group
        for group in config.get("proxy-groups", [])
        if isinstance(group, dict)
    }
    result: dict[str, list[str]] = {}
    old_names = {"gpt": "GPT自动", "gemini": "Gemini自动", "disney": "迪士尼自动"}
    for service, (automatic_name, _) in SERVICE_GROUP_NAMES.items():
        group = groups.get(automatic_name) or groups.get(old_names[service])
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


def load_manual_results(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    payload = load_json_object(path.expanduser().resolve())
    if payload.get("schema_version") != MANUAL_RESULT_SCHEMA_VERSION:
        raise ConfigError(f"Unsupported manual-result schema: {path}")
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise ConfigError("Manual-result file must contain a results list.")
    accepted: list[dict[str, str]] = []
    forbidden = {"cookie", "cookies", "prompt", "response", "answer", "body", "token"}
    for index, item in enumerate(raw_results):
        if not isinstance(item, dict):
            raise ConfigError(f"Manual result {index} must be an object.")
        if forbidden.intersection(str(key).lower() for key in item):
            raise ConfigError(f"Manual result {index} contains sensitive content.")
        service = str(item.get("service", ""))
        node = str(item.get("node", ""))
        result = str(item.get("result", ""))
        tested_at = str(item.get("tested_at", ""))
        method = str(item.get("method", ""))
        exact_node_id = str(item.get("exact_node_id", ""))
        source_snapshot_id = str(item.get("source_snapshot_id", ""))
        if service not in SERVICE_KEYS:
            raise ConfigError(f"Manual result {index} has an invalid service.")
        if not node or result not in {"PASS", "FAIL"} or not tested_at:
            raise ConfigError(f"Manual result {index} is incomplete.")
        parse_aware_timestamp(tested_at, field=f"manual result {index}")
        if method not in DEFINITIVE_MANUAL_METHODS:
            raise ConfigError(f"Manual result {index} is not a definitive use test.")
        accepted.append(
            {
                "service": service,
                "node": node,
                "result": result,
                "tested_at": tested_at,
                "method": method,
                "exact_node_id": exact_node_id,
                "source_snapshot_id": source_snapshot_id,
            }
        )
    return accepted


def load_functional_results(paths: Sequence[Path] | None) -> list[dict[str, str]]:
    """Load safe snapshot-bound browser and Disney functional results."""
    accepted: list[dict[str, str]] = []
    forbidden = {
        "authorization", "cookie", "cookies", "localstorage", "sessionstorage",
        "prompt", "response", "answer", "body", "token", "assertion", "refresh_token",
    }
    def contains_sensitive(value: Any) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = str(key).lower()
                safe_token_stage = lowered == "token" and isinstance(child, dict) and set(child) <= {
                    "curl_code", "http_status", "attempts"
                }
                if (lowered in forbidden and not safe_token_stage) or contains_sensitive(child):
                    return True
            return False
        if isinstance(value, list):
            return any(contains_sensitive(child) for child in value)
        if isinstance(value, str):
            return "GPT_NODE_TEST_" in value or "GEMINI_NODE_TEST_" in value
        return False
    for path in paths or ():
        payload = load_json_object(path.expanduser().resolve())
        if payload.get("schema_version") != FUNCTIONAL_RESULT_SCHEMA_VERSION:
            raise ConfigError(f"Unsupported functional-result schema: {path}")
        if contains_sensitive(payload):
            raise ConfigError(f"Functional-result file contains sensitive content: {path}")
        service_hint = str(payload.get("service", ""))
        raw_results = payload.get("results")
        if raw_results is None and service_hint == "disney":
            raw_results = payload.get("nodes")
        if not isinstance(raw_results, list):
            raise ConfigError(f"Functional-result file must contain results or nodes: {path}")
        for index, item in enumerate(raw_results):
            if not isinstance(item, dict):
                raise ConfigError(f"Functional result {index} must be an object.")
            service = str(item.get("service") or service_hint)
            node = str(item.get("exact_node_name", ""))
            node_id = str(item.get("exact_node_id", ""))
            snapshot_id = str(item.get("source_snapshot_id", ""))
            source_hash = str(item.get("source_hash") or payload.get("source_hash", ""))
            tested_at = str(item.get("tested_at", ""))
            method = str(item.get("probe_method_version") or payload.get("probe_method_version", ""))
            raw_result = str(item.get("result", ""))
            error = str(item.get("error_category") or item.get("failure_stage") or "")
            if service not in SERVICE_KEYS or not all(
                (node, node_id, snapshot_id, source_hash, tested_at, method, raw_result)
            ):
                raise ConfigError(f"Functional result {index} is incomplete.")
            parse_aware_timestamp(tested_at, field=f"functional result {index}")
            if service == "disney":
                if method.startswith("regionrestrictioncheck-"):
                    if raw_result in {
                        "SCREEN_PASS", "FAIL_REGION", "FAIL_IP_BANNED",
                        "FAIL_TRANSPORT", "UNKNOWN",
                    }:
                        result = raw_result
                        error = "" if raw_result == "SCREEN_PASS" else raw_result
                    else:
                        raise ConfigError(
                            f"Functional result {index} has an invalid Disney "
                            "screening result."
                        )
                elif raw_result == "PASS_SUPPORTED_REGION":
                    result = "PASS"
                elif raw_result in {
                    "FAIL_FORBIDDEN_LOCATION", "FAIL_IP_BANNED", "FAIL_UNAVAILABLE"
                }:
                    result = "FAIL"
                    error = raw_result
                elif raw_result in {"FAIL_TRANSPORT", "UNKNOWN_RESPONSE_SCHEMA"}:
                    result = "UNKNOWN"
                    error = raw_result
                else:
                    raise ConfigError(f"Functional result {index} has an invalid Disney result.")
            elif raw_result in {
                "PASS", "FAIL", "UNKNOWN", "SCREEN_PASS", "SCREEN_NEGATIVE",
                "FAIL_TRANSPORT", "FAIL_IP_BANNED", "FAIL_REGION",
            }:
                result = raw_result
            else:
                raise ConfigError(f"Functional result {index} has an invalid result.")
            accepted.append(
                {
                    "service": service,
                    "node": node,
                    "exact_node_id": node_id,
                    "source_snapshot_id": snapshot_id,
                    "source_hash": source_hash,
                    "tested_at": tested_at,
                    "method": method,
                    "result": result,
                    "raw_result": raw_result,
                    "error_category": error,
                }
            )
    return accepted


def apply_functional_results_to_report(
    report: dict[str, Any],
    functional_results: Sequence[dict[str, str]],
    snapshot_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Apply exact-identity automated results; UNKNOWN never becomes a pass."""
    updated = deepcopy(report)
    probe_timestamp = parse_aware_timestamp(str(updated.get("run_timestamp", "")), field="probe run")
    snapshot_id = str(snapshot_manifest.get("source_snapshot_id", ""))
    source_hash = str(snapshot_manifest.get("source_hash", ""))
    identity_by_name = {
        str(item.get("exact_node_name")): str(item.get("exact_node_id"))
        for item in snapshot_manifest.get("nodes", []) if isinstance(item, dict)
    }
    matched: set[int] = set()
    for node in updated.get("nodes", []):
        name = str(node.get("name", ""))
        node_id = identity_by_name.get(name, "")
        node["source_snapshot_id"] = snapshot_id
        node["source_hash"] = source_hash
        node["exact_node_id"] = node_id
        node["exact_node_name"] = name
        for service in SERVICE_KEYS:
            candidates = [
                (index, item) for index, item in enumerate(functional_results)
                if item["service"] == service and item["node"] == name
                and item["exact_node_id"] == node_id
                and item["source_snapshot_id"] == snapshot_id
                and item["source_hash"] == source_hash
                and parse_aware_timestamp(item["tested_at"], field="functional result") >= probe_timestamp
            ]
            if not candidates:
                continue
            index, latest = max(
                candidates,
                key=lambda pair: (
                    1
                    if service == "disney"
                    and str(pair[1].get("method", "")).startswith("disney-full-chain")
                    else 0,
                    parse_aware_timestamp(pair[1]["tested_at"], field="functional result"),
                ),
            )
            matched.add(index)
            service_result = node["services"][service]
            service_result["functional_result"] = {
                key: latest.get(key) for key in (
                    "result", "tested_at", "method", "source_snapshot_id",
                    "source_hash", "exact_node_id", "error_category", "raw_result"
                )
            }
            if service == "disney" and latest.get("raw_result") in {
                "PASS_SUPPORTED_REGION", "FAIL_FORBIDDEN_LOCATION", "FAIL_IP_BANNED",
                "FAIL_UNAVAILABLE", "FAIL_TRANSPORT", "UNKNOWN_RESPONSE_SCHEMA",
            }:
                service_result["final_result"] = latest["raw_result"]
            elif latest["result"] == "PASS":
                service_result["final_result"] = "DEFINITIVE_AUTOMATED_PASS"
            elif latest["result"] == "FAIL":
                service_result["final_result"] = (
                    "DEFINITIVE_AUTOMATED_FAIL_UNSUPPORTED_REGION"
                    if latest.get("error_category") == "FAIL_UNSUPPORTED_REGION"
                    else "DEFINITIVE_AUTOMATED_FAIL"
                )
            elif latest["result"] in {
                "SCREEN_PASS", "SCREEN_NEGATIVE", "FAIL_TRANSPORT",
                "FAIL_IP_BANNED", "FAIL_REGION",
            }:
                service_result["final_result"] = latest["result"]
    updated["functional_results"] = {
        "applied": len(matched),
        "unmatched_or_stale_count": len(functional_results) - len(matched),
    }
    return updated


def apply_manual_results_to_report(
    report: dict[str, Any],
    manual_results: Sequence[dict[str, str]],
    snapshot_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply only definitive, time-qualified human use results to a probe report."""
    updated = deepcopy(report)
    probe_at = str(updated.get("run_timestamp", ""))
    probe_timestamp = parse_aware_timestamp(probe_at, field="probe run")
    nodes = updated.get("nodes", [])
    matched: set[int] = set()
    snapshot_id = str((snapshot_manifest or {}).get("source_snapshot_id", ""))
    identity_by_name = {
        str(item.get("exact_node_name")): str(item.get("exact_node_id"))
        for item in (snapshot_manifest or {}).get("nodes", [])
        if isinstance(item, dict)
    }

    # Reports produced before structured calibration may contain hard-coded overrides.
    # Restore their raw result before applying the auditable result file.
    for node in nodes:
        for service in SERVICE_KEYS:
            service_result = node.get("services", {}).get(service, {})
            raw_result = str(service_result.get("raw_result", "UNKNOWN"))
            if service == "gemini" and raw_result == "PASS":
                raw_result = "GEMINI_SCREEN_PASS"
            elif service == "disney" and raw_result == "PASS":
                raw_result = "UNKNOWN_INCOMPLETE_PROBE"
            service_result["raw_result"] = raw_result
            service_result["override"] = None
            functional = service_result.get("functional_result", {})
            if functional.get("result") == "PASS":
                service_result["final_result"] = "DEFINITIVE_AUTOMATED_PASS"
            elif functional.get("result") == "FAIL":
                service_result["final_result"] = "DEFINITIVE_AUTOMATED_FAIL"
            elif functional.get("result") in {
                "SCREEN_PASS", "SCREEN_NEGATIVE", "FAIL_TRANSPORT",
                "FAIL_IP_BANNED", "FAIL_REGION",
            }:
                service_result["final_result"] = functional["result"]
            else:
                service_result["final_result"] = raw_result
            service_result.pop("manual_result", None)

    for node in nodes:
        node_name = str(node.get("name", ""))
        node_id = identity_by_name.get(node_name, "")
        if snapshot_manifest:
            node["source_snapshot_id"] = snapshot_id
            node["source_hash"] = snapshot_manifest.get("source_hash")
            node["exact_node_id"] = node_id
            node["exact_node_name"] = node_name
        for service in SERVICE_KEYS:
            candidates = [
                (index, item)
                for index, item in enumerate(manual_results)
                if item["service"] == service
                and (
                    (
                        snapshot_manifest is not None
                        and bool(node_id)
                        and item.get("exact_node_id") == node_id
                        and item.get("source_snapshot_id") == snapshot_id
                        and item["node"] == node_name
                    )
                    or (
                        snapshot_manifest is None
                        and exact_or_flag_normalized_match(node_name, item["node"])
                    )
                )
                and parse_aware_timestamp(item["tested_at"], field="manual result")
                >= probe_timestamp
            ]
            if not candidates:
                continue
            index, latest = max(
                candidates,
                key=lambda pair: parse_aware_timestamp(
                    pair[1]["tested_at"], field="manual result"
                ),
            )
            matched.add(index)
            override = (
                "MANUAL_OVERRIDE_PASS"
                if latest["result"] == "PASS"
                else "MANUAL_OVERRIDE_FAIL"
            )
            service_result = node["services"][service]
            service_result["override"] = override
            functional_result = str(service_result.get("functional_result", {}).get("result", ""))
            if latest["result"] == "PASS":
                if functional_result == "FAIL_TRANSPORT":
                    service_result["final_result"] = "FAIL_TRANSPORT"
                elif service == "gemini" and functional_result == "SCREEN_NEGATIVE":
                    service_result["final_result"] = "PASS_WITH_SCREEN_FALSE_NEGATIVE"
                    service_result["screen_false_negative"] = True
                elif functional_result in {"PASS", "SCREEN_PASS"}:
                    service_result["final_result"] = (
                        "DEFINITIVE_AUTOMATED_PASS"
                        if functional_result == "PASS" else "SCREEN_PASS"
                    )
                else:
                    service_result["final_result"] = override
            elif functional_result in {"PASS", "SCREEN_PASS"}:
                service_result["final_result"] = "EVIDENCE_CONFLICT"
                service_result["evidence_conflict"] = True
            else:
                service_result["final_result"] = override
            service_result["manual_result"] = {
                "result": latest["result"],
                "tested_at": latest["tested_at"],
                "method": latest["method"],
                "source_snapshot_id": latest.get("source_snapshot_id"),
                "exact_node_id": latest.get("exact_node_id"),
            }

    updated["manual_results"] = {
        "applied": len(matched),
        "unmatched_or_stale": [
            {
                "service": item["service"],
                "node": item["node"],
                "result": item["result"],
                "tested_at": item["tested_at"],
                "method": item["method"],
                "source_snapshot_id": item.get("source_snapshot_id"),
                "exact_node_id": item.get("exact_node_id"),
            }
            for index, item in enumerate(manual_results)
            if index not in matched
        ],
    }
    return updated


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
        return "GEMINI_SCREEN_FAIL" if service == "gemini" else "FAIL_REGION"
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
        if service == "gemini":
            return "GEMINI_SCREEN_PASS"
        if service == "disney":
            return "UNKNOWN_INCOMPLETE_PROBE"
        return "PASS"
    if 403 in statuses:
        return "UNKNOWN"
    return "UNKNOWN"


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
        ("马来西亚", "MY"),
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
            exact_node_id = str(item.get("exact_node_id", ""))
            prior_node_id = str(prior.get("exact_node_id", ""))
            identity_matches = not exact_node_id or not prior_node_id or exact_node_id == prior_node_id
            prior_lkg = bool(prior.get("lkg")) and identity_matches

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
                    confirmed_at = service_result.get("manual_result", {}).get(
                        "tested_at", observed_at
                    )
                node_state[service] = {
                    "last_raw_result": service_result["raw_result"],
                    "last_final_result": final_result,
                    "last_confirmed_pass_at": confirmed_at,
                    "source": "manual_override" if service_result.get("override") else "probe",
                    "lkg": lkg,
                    "exact_node_id": exact_node_id or prior_node_id or None,
                }

            item["lkg_merge"][service] = action
            is_current_candidate = (
                final_result in {
                    "DEFINITIVE_AUTOMATED_PASS", "PASS_SUPPORTED_REGION", "SCREEN_PASS"
                }
                or (
                    service in {"gpt", "gemini"}
                    and final_result in {
                        "MANUAL_OVERRIDE_PASS", "PASS_WITH_SCREEN_FALSE_NEGATIVE"
                    }
                )
            )
            item["enters_auto"][service] = is_current_candidate
            item["enters_manual_candidate"][service] = (
                not probable_recapture and not lkg and final_result in PENDING_RESULTS
            )
        enriched.append(item)

    selections: dict[str, dict[str, list[str]]] = {}
    effective_state = state if probable_recapture else new_state
    for service in SERVICE_KEYS:
        automatic = [
            str(item["name"])
            for item in enriched
            if item["enters_auto"][service]
        ]
        historical = [
            name for name in current_names
            if name not in automatic
            and bool(effective_state.get("nodes", {}).get(name, {}).get(service, {}).get("lkg"))
            and (
                not probe_by_name.get(name, {}).get("exact_node_id")
                or not effective_state.get("nodes", {}).get(name, {}).get(service, {}).get("exact_node_id")
                or probe_by_name[name]["exact_node_id"]
                == effective_state["nodes"][name][service]["exact_node_id"]
            )
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
        historical = stable_region_sort(historical, source_order, gemini=service == "gemini")
        selections[service] = {
            "automatic": automatic,
            "manual_candidates": pending,
            "historical_lkg": historical,
        }

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
            item["services"][service] = {
                "raw_result": raw_result,
                "override": None,
                "final_result": raw_result,
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
    interface_name: str | None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "mixed-port": mixed_port,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "external-controller": f"127.0.0.1:{controller_port}",
        "secret": "",
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
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
    if interface_name:
        config["interface-name"] = interface_name
    return config


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


def remote_production_fingerprint(host: str) -> str:
    """Hash production control/data-plane state without returning its contents."""
    command = (
        "CANDIDATE_FINGERPRINT=1; set -e; "
        "for path in /etc/config/openclash /etc/config/dhcp /etc/config/firewall; do "
        "printf 'file:%s=' \"$path\"; sha256sum \"$path\" | awk '{print $1}'; done; "
        "if /etc/init.d/openclash running >/dev/null 2>&1; then echo service=running; "
        "else echo service=stopped; fi; "
        "printf 'rule4='; ip -4 rule show 2>/dev/null | "
        "grep -E 'fwmark (0x)?0*162|lookup 354' | sha256sum | awk '{print $1}'; "
        "printf 'rule6='; ip -6 rule show 2>/dev/null | "
        "grep -E 'fwmark (0x)?0*162|lookup 354' | sha256sum | awk '{print $1}'; "
        "printf 'route4='; ip -4 route show table 354 2>/dev/null | sha256sum | awk '{print $1}'; "
        "printf 'route6='; ip -6 route show table 354 2>/dev/null | sha256sum | awk '{print $1}'; "
        "printf 'nft='; if command -v nft >/dev/null 2>&1; then "
        "nft -s list table inet fw4 2>/dev/null | grep -E 'openclash|OpenClash' | "
        "sha256sum | awk '{print $1}'; else echo unavailable; fi; "
        "if ip link show utun >/dev/null 2>&1; then echo utun=present; else echo utun=absent; fi"
    )
    return ssh_command(host, command, capture=True).stdout or ""


def _stop_remote_sidecar(
    host: str, remote_dir: str, upload_path: str, lock_dir: str, token: str
) -> None:
    command = (
        "CANDIDATE_SIDECAR_CLEANUP=1; "
        f"if [ \"$(cat {quote_remote(lock_dir + '/owner')} 2>/dev/null)\" = "
        f"{quote_remote(token)} ]; then "
        f"pid_file={quote_remote(remote_dir + '/sidecar.pid')}; "
        "if [ -s \"$pid_file\" ]; then "
        "pid=\"$(cat \"$pid_file\")\"; kill \"$pid\" 2>/dev/null || true; "
        "for wait_count in 1 2 3 4 5; do kill -0 \"$pid\" 2>/dev/null || break; sleep 1; done; "
        "kill -9 \"$pid\" 2>/dev/null || true; fi; "
        f"rm -rf {quote_remote(remote_dir)}; rm -f {quote_remote(upload_path)}; "
        f"rm -rf {quote_remote(lock_dir)}; else rm -f {quote_remote(upload_path)}; fi"
    )
    ssh_command(host, command, capture=True)


@contextmanager
def remote_candidate_sidecar(
    config_path: Path,
    *,
    host: str,
    core_path: str,
):
    token = uuid.uuid4().hex
    remote_dir = f"/tmp/clashverge-openclash-sidecar.{token}"
    upload_path = f"/tmp/clashverge-openclash-sidecar.{token}.upload"
    lock_dir = "/tmp/clashverge-openclash-sidecar.lock"
    local_mixed = reserve_loopback_port()
    local_controller = reserve_loopback_port()
    before = remote_production_fingerprint(host)
    tunnel: subprocess.Popen[Any] | None = None
    primary_error: BaseException | None = None
    try:
        run(
            [
                "scp",
                "-O",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                str(config_path),
                f"{host}:{upload_path}",
            ]
        )
        setup = (
            "CANDIDATE_SIDECAR_SETUP=1; set -e; "
            f"mkdir {quote_remote(lock_dir)}; "
            f"printf '%s\\n' {quote_remote(token)} > {quote_remote(lock_dir + '/owner')}; "
            f"mkdir {quote_remote(remote_dir)}; "
            f"mv {quote_remote(upload_path)} {quote_remote(remote_dir + '/config.yaml')}; "
            f"chmod 700 {quote_remote(remote_dir)}; "
            f"chmod 600 {quote_remote(remote_dir + '/config.yaml')}; "
            f"{quote_remote(core_path)} -t -d {quote_remote(remote_dir)} "
            f"-f {quote_remote(remote_dir + '/config.yaml')}; "
            "if /etc/init.d/openclash running >/dev/null 2>&1; then "
            "nft list table inet fw4 2>/dev/null | "
            f"grep -qE 'meta skgid {REMOTE_SIDECAR_GID} .*return'; fi; "
            f"chown -R {REMOTE_SIDECAR_UID}:{REMOTE_SIDECAR_GID} {quote_remote(remote_dir)}; "
            f"start-stop-daemon -S -b -m -p {quote_remote(remote_dir + '/sidecar.pid')} "
            f"-c {REMOTE_SIDECAR_UID}:{REMOTE_SIDECAR_GID} -x {quote_remote(core_path)} -- "
            f"-d {quote_remote(remote_dir)} -f {quote_remote(remote_dir + '/config.yaml')}; "
            f"sleep 1; pid=\"$(cat {quote_remote(remote_dir + '/sidecar.pid')})\"; "
            "kill -0 \"$pid\"; "
            f"grep -q '^Gid:[[:space:]]*{REMOTE_SIDECAR_GID}[[:space:]]' /proc/\"$pid\"/status"
        )
        ssh_command(host, setup, capture=True)
        tunnel = subprocess.Popen(
            [
                "ssh",
                "-N",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "ExitOnForwardFailure=yes",
                "-L",
                f"127.0.0.1:{local_mixed}:127.0.0.1:{REMOTE_SIDECAR_MIXED_PORT}",
                "-L",
                f"127.0.0.1:{local_controller}:127.0.0.1:{REMOTE_SIDECAR_CONTROLLER_PORT}",
                host,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        wait_for_controller(local_controller, tunnel)
        yield RemoteSidecarSession(local_mixed, local_controller)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if tunnel is not None and tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait(timeout=5)
        cleanup_error: BaseException | None = None
        try:
            _stop_remote_sidecar(host, remote_dir, upload_path, lock_dir, token)
        except BaseException as exc:
            cleanup_error = exc
        try:
            after = remote_production_fingerprint(host)
            if after != before:
                raise ConfigError("CANDIDATE_SIDECAR_PRODUCTION_STATE_CHANGED")
        except BaseException as exc:
            cleanup_error = cleanup_error or exc
        if cleanup_error is not None:
            suffix = "_AFTER_PROBE_FAILURE" if primary_error is not None else ""
            raise ConfigError(f"CANDIDATE_SIDECAR_CLEANUP_FAILED{suffix}") from cleanup_error


def run_remote_service_probe(
    data: dict[str, Any],
    *,
    host: str,
    core_path: str,
) -> dict[str, Any]:
    proxies = static_proxy_objects(data)
    with tempfile.TemporaryDirectory(prefix="openclash-remote-service-probe-") as temporary:
        workdir = Path(temporary)
        config_path = workdir / "probe.yaml"
        config = build_probe_config(
            proxies,
            mixed_port=REMOTE_SIDECAR_MIXED_PORT,
            controller_port=REMOTE_SIDECAR_CONTROLLER_PORT,
            interface_name=None,
        )
        dump_yaml(config, config_path)
        with remote_candidate_sidecar(
            config_path, host=host, core_path=core_path
        ) as sidecar:
            global_now = validate_probe_runtime(sidecar.controller_port)

            def switch_node(name: str) -> bool:
                return select_probe_node(sidecar.controller_port, name)

            def request_url(url: str) -> dict[str, Any]:
                return curl_probe_once(url, sidecar.mixed_port, workdir=workdir)

            report = probe_nodes_with_runner(
                proxies,
                switch_node=switch_node,
                request_url=request_url,
            )
            report["probe_transport"] = {
                "mode": "rule",
                "interface_name": None,
                "route": "MATCH,PROBE",
                "global_now_observed": global_now,
                "request_path": "ssh_loopback_to_router_sidecar",
                "sidecar_gid": REMOTE_SIDECAR_GID,
                "production_openclash_bypass": "nft_meta_skgid_return_verified",
            }
            return report


def build_candidate_sidecar_config(data: dict[str, Any]) -> dict[str, Any]:
    config = deepcopy(data)
    for key in (
        *CLASH_VERGE_TOP_LEVEL_RUNTIME_KEYS,
        "listeners",
        "tunnels",
        "routing-mark",
        "ebpf",
    ):
        config.pop(key, None)
    config.update(
        {
            "mixed-port": REMOTE_SIDECAR_MIXED_PORT,
            "allow-lan": False,
            "bind-address": "127.0.0.1",
            "external-controller": f"127.0.0.1:{REMOTE_SIDECAR_CONTROLLER_PORT}",
            "secret": "",
            "mode": "rule",
            "tun": {"enable": False},
            "dns": {
                "enable": True,
                "ipv6": False,
                "nameserver": ["1.1.1.1", "8.8.8.8"],
            },
        }
    )
    return config


def probe_uploaded_candidate(
    local_file: Path,
    *,
    host: str,
    core_path: str,
    candidate_path: str | None = None,
) -> None:
    if candidate_path is not None:
        digest = hashlib.sha256(local_file.read_bytes()).hexdigest()
        identity_check = (
            "OPENCLASH_CANDIDATE_IDENTITY_CHECK=1; set -e; "
            f"[ -f {quote_remote(candidate_path)} ]; "
            f"[ \"$(sha256sum {quote_remote(candidate_path)} | awk '{{print $1}}')\" = "
            f"{quote_remote(digest)} ]"
        )
        try:
            ssh_command(host, identity_check, capture=True)
        except subprocess.CalledProcessError as exc:
            raise ConfigError("REMOTE_CANDIDATE_IDENTITY_MISMATCH") from exc
    data = load_yaml(local_file)
    validate_config(data)
    with tempfile.TemporaryDirectory(prefix="openclash-candidate-probe-") as temporary:
        workdir = Path(temporary)
        config_path = workdir / "candidate-sidecar.yaml"
        dump_yaml(build_candidate_sidecar_config(data), config_path)
        with remote_candidate_sidecar(
            config_path, host=host, core_path=core_path
        ) as sidecar:
            evidence = curl_probe_once(
                "https://www.gstatic.com/generate_204",
                sidecar.mixed_port,
                workdir=workdir,
            )
            if evidence.get("curl_code") != 0 or evidence.get("http_status") != 204:
                raise ConfigError("CANDIDATE_PROBE_FAILED")


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


def annotate_probe_semantics(
    report: dict[str, Any], nodes: Sequence[dict[str, Any]]
) -> None:
    report["service_semantics"] = {
        "gpt": "regionrestrictioncheck_screen_or_snapshot_bound_manual_use",
        "gemini": "regionrestrictioncheck_screen_or_snapshot_bound_manual_use",
        "disney": "full_chain_preferred_then_regionrestrictioncheck_screen",
    }
    groups = report.get("service_groups", {})
    summaries: dict[str, dict[str, int]] = {}
    for service in SERVICE_KEYS:
        candidate_names = set(groups.get(service, {}).get("automatic", []))
        historical_names = set(groups.get(service, {}).get("historical_lkg", []))
        counts = {evidence: 0 for evidence in EVIDENCE_TYPES}
        candidate_count = 0
        for node in nodes:
            node_name = str(node.get("name", ""))
            result = node.get("services", {}).get(service, {})
            final_result = str(result.get("final_result", "UNKNOWN"))
            if final_result == "MANUAL_OVERRIDE_PASS":
                evidence_type = "MANUAL_FUNCTIONAL_PASS"
            elif final_result == "MANUAL_OVERRIDE_FAIL":
                evidence_type = "MANUAL_FUNCTIONAL_FAIL"
            elif final_result in {"DEFINITIVE_AUTOMATED_PASS", "PASS_SUPPORTED_REGION"}:
                evidence_type = "DEFINITIVE_AUTOMATED_PASS"
            elif final_result.startswith("DEFINITIVE_AUTOMATED_FAIL"):
                evidence_type = "DEFINITIVE_AUTOMATED_FAIL"
            elif final_result in {"PASS", "GEMINI_SCREEN_PASS"}:
                evidence_type = "SCREEN_PASS"
            elif final_result == "SCREEN_PASS":
                evidence_type = "SCREEN_PASS"
            elif final_result == "SCREEN_NEGATIVE":
                evidence_type = "SCREEN_NEGATIVE"
            elif final_result == "PASS_WITH_SCREEN_FALSE_NEGATIVE":
                evidence_type = "MANUAL_FUNCTIONAL_PASS"
            elif node_name in historical_names:
                evidence_type = "LKG_FALLBACK"
            else:
                evidence_type = "UNKNOWN"
            result["evidence_type"] = evidence_type
            result["probe_method_version"] = PROBE_VERSION
            result["tested_at"] = (
                result.get("functional_result", {}).get("tested_at")
                or
                result.get("manual_result", {}).get("tested_at")
                or node.get("observed_at")
                or report.get("run_timestamp")
            )
            counts[evidence_type] += 1
            if node_name in candidate_names:
                candidate_count += 1
        summaries[service] = {
            "candidates": candidate_count,
            "definitive_automated": sum(
                1
                for node in nodes
                if node.get("name") in candidate_names
                and node.get("services", {}).get(service, {}).get("evidence_type")
                == "DEFINITIVE_AUTOMATED_PASS"
            ),
            "manual_functional_pass": sum(
                1
                for node in nodes
                if node.get("name") in candidate_names
                and node.get("services", {}).get(service, {}).get("evidence_type")
                == "MANUAL_FUNCTIONAL_PASS"
            ),
            "lkg_only": sum(
                1
                for node in nodes
                if node.get("name") in historical_names
                and node.get("services", {}).get(service, {}).get("evidence_type")
                == "LKG_FALLBACK"
            ),
            "manual_functional_fail": counts["MANUAL_FUNCTIONAL_FAIL"],
            "unknown": counts["UNKNOWN"],
            "evidence_conflict": sum(
                node.get("services", {}).get(service, {}).get("final_result") == "EVIDENCE_CONFLICT"
                for node in nodes
            ),
            "candidate_evidence_conflict": sum(
                node.get("name") in candidate_names
                and node.get("services", {}).get(service, {}).get("final_result")
                == "EVIDENCE_CONFLICT"
                for node in nodes
            ),
        }
    report["candidate_evidence_summary"] = summaries
    report["definitive_automated_pass_counts"] = {
        service: summaries[service]["definitive_automated"] for service in SERVICE_KEYS
    }
    # Compatibility field now has one unambiguous meaning: automated functional proof only.
    report["definitive_pass_counts"] = dict(report["definitive_automated_pass_counts"])
    blockers: list[str] = []
    if summaries["gpt"]["candidates"] == 0:
        blockers.append("GPT_CURRENT_FUNCTIONAL_CANDIDATE_MISSING")
    if summaries["gemini"]["candidates"] == 0:
        blockers.append("GEMINI_CURRENT_SCREEN_OR_MANUAL_CANDIDATE_MISSING")
    if summaries["disney"]["candidates"] == 0:
        blockers.append("DISNEY_FULL_REGION_CHAIN_RESULT_MISSING")
    conflicts = sum(
        summaries[service]["candidate_evidence_conflict"]
        for service in SERVICE_KEYS
    )
    if conflicts:
        blockers.append("EVIDENCE_CONFLICT_PRESENT")
    report["activation_blocked_reasons"] = blockers


def dynamic_probe_and_select(
    data: dict[str, Any],
    *,
    state_path: Path,
    report_path: Path,
    core_path: str | None,
    update_lkg: bool,
    manual_results_path: Path | None = None,
    functional_results_paths: Sequence[Path] | None = None,
    snapshot_manifest: dict[str, Any] | None = None,
    probe_runner: Any = run_local_service_probe,
) -> tuple[dict[str, dict[str, list[str]]], dict[str, Any]]:
    legacy_config = transform(data)
    state, seed_source = load_or_seed_lkg_state(
        state_path, legacy_config, persist_seed=update_lkg
    )
    report = probe_runner(data, core_path=core_path)
    if snapshot_manifest:
        report = apply_functional_results_to_report(
            report, load_functional_results(functional_results_paths), snapshot_manifest
        )
    report = apply_manual_results_to_report(
        report,
        load_manual_results(manual_results_path),
        snapshot_manifest,
    )
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
    if snapshot_manifest:
        report["source_snapshot_id"] = snapshot_manifest["source_snapshot_id"]
        report["source_hash"] = snapshot_manifest["source_hash"]
    annotate_probe_semantics(report, enriched)
    validate_probe_report_safe(report)
    atomic_write_json(report, report_path)
    written_report = load_json_object(report_path)
    if update_lkg and not probable_recapture:
        atomic_write_json(new_state, state_path, private_parent=True)
        load_json_object(state_path)
    return selections, written_report


def reconcile_existing_probe(
    data: dict[str, Any],
    *,
    state_path: Path,
    probe_report_path: Path,
    manual_results_path: Path,
    report_output_path: Path,
    state_output_path: Path,
    snapshot_manifest: dict[str, Any] | None = None,
    functional_results_paths: Sequence[Path] | None = None,
) -> tuple[dict[str, dict[str, list[str]]], dict[str, Any]]:
    """Reconcile an existing report without starting Mihomo, curl, SSH, or deployment."""
    legacy_config = transform(data)
    state, seed_source = load_or_seed_lkg_state(
        state_path, legacy_config, persist_seed=False
    )
    proxies = static_proxy_objects(data)
    current_names = [str(proxy["name"]) for proxy in proxies]
    report = load_json_object(probe_report_path)
    reported_names = {
        str(node.get("name", "")) for node in report.get("nodes", [])
    }
    for name in current_names:
        if name in reported_names:
            continue
        report.setdefault("nodes", []).append(
            {
                "name": name,
                "selector_confirmed": None,
                "observed_at": report.get("run_timestamp"),
                "base_result": "NOT_PROBED_CURRENT_SOURCE",
                "services": {
                    service: {
                        "raw_result": "UNKNOWN",
                        "override": None,
                        "final_result": "UNKNOWN",
                        "evidence": {},
                    }
                    for service in SERVICE_KEYS
                },
                "reason_code": "NOT_PROBED_CURRENT_SOURCE",
            }
        )
    if snapshot_manifest:
        report = apply_functional_results_to_report(
            report, load_functional_results(functional_results_paths), snapshot_manifest
        )
    report = apply_manual_results_to_report(
        report, load_manual_results(manual_results_path), snapshot_manifest
    )
    source_order = {name: index for index, name in enumerate(current_names)}
    reconciled_at = iso_now()
    selections, new_state, enriched = merge_lkg_results(
        current_names,
        source_order,
        state,
        report.get("nodes", []),
        probable_recapture=bool(report.get("probable_tun_or_upstream_recapture")),
        observed_at=reconciled_at,
    )
    report["nodes"] = enriched
    report["probe_version"] = PROBE_VERSION
    report["reconciled_at"] = reconciled_at
    report["lkg_seed_source"] = seed_source
    report["lkg_state_updated"] = True
    report["current_source_node_count"] = len(current_names)
    report["nodes_added_without_probe"] = [
        name for name in current_names if name not in reported_names
    ]
    report["service_groups"] = selections
    if snapshot_manifest:
        report["source_snapshot_id"] = snapshot_manifest["source_snapshot_id"]
        report["source_hash"] = snapshot_manifest["source_hash"]
    annotate_probe_semantics(report, enriched)
    validate_probe_report_safe(report)
    atomic_write_json(report, report_output_path)
    atomic_write_json(new_state, state_output_path, private_parent=True)
    return selections, load_json_object(report_output_path)


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
    historical_lkg: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    groups = [
        {"name": "默认代理", "type": "select", "proxies": ["手动选择", "自动选择"]},
        {"name": "手动选择", "type": "select", "proxies": ["自动选择", *all_nodes]},
        fallback_group("自动选择", all_nodes),
        {"name": "GPT专用", "type": "select", "proxies": ["GPT手动", "GPT候选"]},
        {"name": "GPT手动", "type": "select", "proxies": ["GPT候选", *gpt_nodes]},
        fallback_group("GPT候选", gpt_nodes),
        {"name": "Gemini专用", "type": "select", "proxies": ["Gemini手动", "Gemini候选"]},
        {"name": "Gemini手动", "type": "select", "proxies": ["Gemini候选", *gemini_nodes]},
        fallback_group("Gemini候选", gemini_nodes),
        {"name": "迪士尼", "type": "select", "proxies": ["迪士尼手动", "迪士尼候选"]},
        {"name": "迪士尼手动", "type": "select", "proxies": ["迪士尼候选", *disney_nodes]},
        fallback_group("迪士尼候选", disney_nodes),
    ]
    for service, group_name, selector_name in (
        ("gpt", "GPT历史LKG", "GPT手动"),
        ("gemini", "Gemini历史LKG", "Gemini手动"),
        ("disney", "迪士尼历史LKG", "迪士尼手动"),
    ):
        members = list((historical_lkg or {}).get(service, []))
        if not members:
            continue
        groups.append(fallback_group(group_name, members))
        selector = next(group for group in groups if group["name"] == selector_name)
        selector["proxies"].append(group_name)
    return groups


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
    expected_prefix = list(MANAGED_GROUP_NAMES)
    optional_tail = group_names[len(expected_prefix):]
    if group_names[:len(expected_prefix)] != expected_prefix or any(
        name not in OPTIONAL_HISTORY_GROUP_NAMES for name in optional_tail
    ) or optional_tail != [name for name in OPTIONAL_HISTORY_GROUP_NAMES if name in optional_tail]:
        raise ConfigError(
            "Managed groups do not match the accepted candidate/history structure: "
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
        missing = [
            service.upper()
            for service, nodes in (
                ("gpt", gpt_nodes), ("gemini", gemini_nodes), ("disney", disney_nodes)
            )
            if not nodes
        ]
        if missing:
            raise ConfigError("BLOCKED_NO_CURRENT_SERVICE_CANDIDATES: " + ",".join(missing))

    history = None
    if service_selections is not None:
        history = {
            service: list(service_selections[service].get("historical_lkg", []))
            for service in SERVICE_KEYS
        }
    output["proxy-groups"] = build_groups(
        all_nodes, gpt_nodes, gemini_nodes, disney_nodes, history
    )
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


def network_state_capture_command(output_path: str) -> str:
    """Capture the transaction-relevant dataplane and DNS upstream semantics."""
    return (
        f"{{ echo '[rule4]'; ip -4 rule show 2>/dev/null; echo '[route4-354]'; "
        f"ip -4 route show table 354 2>/dev/null; echo '[rule6]'; "
        f"ip -6 rule show 2>/dev/null; echo '[route6-354]'; "
        f"ip -6 route show table 354 2>/dev/null; echo '[nft-openclash]'; "
        f"nft -s list table inet fw4 2>/dev/null | grep -E 'openclash|OpenClash' || true; "
        f"echo '[utun]'; ip -details link show utun 2>/dev/null || true; "
        f"echo '[dnsmasq-upstream]'; "
        f"grep -hE '^(no-resolv|server=|resolv-file=)' "
        f"/tmp/etc/dnsmasq.conf.* 2>/dev/null || true; }} > {quote_remote(output_path)}"
    )


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
        "else printf 'running=0\\n'; fi; "
        "if pidof clash >/dev/null 2>&1 || pidof mihomo >/dev/null 2>&1; "
        "then printf 'core_running=1\\n'; else printf 'core_running=0\\n'; fi; "
        "network_artifacts=0; "
        "ip -4 rule show 2>/dev/null | grep -qE 'fwmark (0x)?0*162 .*lookup (0x)?0*162|fwmark (0x)?0*162 .*lookup 354' "
        "&& network_artifacts=1; "
        "ip -4 route show table 354 2>/dev/null | grep -q . && network_artifacts=1; "
        "if command -v nft >/dev/null 2>&1; then "
        "nft list chains 2>/dev/null | grep -q 'chain openclash' && network_artifacts=1; "
        "fi; printf 'network_artifacts=%s\\n' \"$network_artifacts\"; "
        "if ip link show utun >/dev/null 2>&1; then printf 'tun_present=1\\n'; "
        "else printf 'tun_present=0\\n'; fi"
    )
    try:
        result = ssh_command(host, command, capture=True)
    except subprocess.CalledProcessError as exc:
        raise ConfigError("REMOTE_ACTIVE_CONFIG_PATH_READ_FAILED") from exc

    values: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {
            "active_path",
            "active_exists",
            "enabled",
            "running",
            "core_running",
            "network_artifacts",
            "tun_present",
        }:
            values[key] = value

    expected = {
        "active_path",
        "active_exists",
        "enabled",
        "running",
        "core_running",
        "network_artifacts",
        "tun_present",
    }
    if set(values) != expected:
        raise ConfigError("REMOTE_ACTIVE_CONFIG_PATH_READ_FAILED: incomplete state")
    active_path = values["active_path"]
    if not active_path.startswith("/") or "\n" in active_path:
        raise ConfigError("REMOTE_ACTIVE_CONFIG_PATH_READ_FAILED: invalid path")
    for key in (
        "active_exists",
        "enabled",
        "running",
        "core_running",
        "network_artifacts",
        "tun_present",
    ):
        if values[key] not in {"0", "1"}:
            raise ConfigError(f"REMOTE_ACTIVE_CONFIG_PATH_READ_FAILED: invalid {key}")

    return {
        "active_path": active_path,
        "active_exists": values["active_exists"] == "1",
        "enabled": values["enabled"] == "1",
        "running": values["running"] == "1",
        "core_running": values["core_running"] == "1",
        "network_artifacts": values["network_artifacts"] == "1",
        "tun_present": values["tun_present"] == "1",
    }


def wait_for_openclash_running(host: str, max_wait_seconds: int = 15) -> None:
    """Poll /etc/init.d/openclash running every second until success or timeout.

    Args:
        host: SSH host
        max_wait_seconds: Maximum seconds to wait (default 15)

    Raises:
        ConfigError: If running check fails after max_wait_seconds
    """
    start_time = time.monotonic()
    last_error: subprocess.CalledProcessError | None = None

    while time.monotonic() - start_time < max_wait_seconds:
        try:
            ssh_command(host, "/etc/init.d/openclash running >/dev/null 2>&1", capture=True)
            return  # Success: running check passed
        except subprocess.CalledProcessError as exc:
            last_error = exc
            time.sleep(1)  # Wait 1 second before next attempt

    raise ConfigError(
        f"OpenClash not running after {max_wait_seconds} seconds"
    ) from last_error


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
        "pidof clash >/dev/null 2>&1 || pidof mihomo >/dev/null 2>&1; "
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


def verify_lan_client_egress(
    *,
    attempts: int = HEALTH_CHECK_ATTEMPTS,
    delay_seconds: int = HEALTH_CHECK_DELAY_SECONDS,
) -> None:
    """Layer 3: verify egress from the machine running this deployment."""
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(attempts):
        try:
            run(
                [
                    "curl",
                    "--noproxy",
                    "*",
                    "--connect-timeout",
                    "3",
                    "--max-time",
                    "8",
                    "--silent",
                    "--show-error",
                    "--fail",
                    "--location",
                    "--output",
                    "/dev/null",
                    LAN_HEALTH_URL,
                ]
            )
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
    raise ConfigError("ROLLBACK_HEALTH_LAYER3_LAN_EGRESS_FAILED") from last_error


def verify_stopped_openclash_health(
    host: str,
    transaction: DeploymentTransaction,
) -> None:
    expected_artifacts = "1" if transaction.original_network_artifacts else "0"
    tun_check = (
        "ip link show utun >/dev/null 2>&1"
        if transaction.original_tun_present
        else "! ip link show utun >/dev/null 2>&1"
    )
    config_check = (
        f"cmp -s {quote_remote(transaction.active_backup)} "
        f"{quote_remote(transaction.original_active_path)}; "
        f"{quote_remote(transaction.core_path)} -t -d /etc/openclash "
        f"-f {quote_remote(transaction.original_active_path)}"
        if transaction.original_active_exists
        else f"[ ! -e {quote_remote(transaction.original_active_path)} ]"
    )
    command = (
        "OPENCLASH_ROLLBACK_HEALTH=1; set -e; "
        # Layer 0: both procd and the actual core must be stopped.
        "! /etc/init.d/openclash running >/dev/null 2>&1; "
        "! pidof clash >/dev/null 2>&1; ! pidof mihomo >/dev/null 2>&1; "
        # Layer 1: the restored selected config still validates.
        f"{config_check}; "
        # Layer 2: no stale transparent-proxy dataplane may survive a stopped service.
        "network_artifacts=0; "
        "ip -4 rule show 2>/dev/null | grep -qE "
        "'fwmark (0x)?0*162 .*lookup (0x)?0*162|fwmark (0x)?0*162 .*lookup 354' "
        "&& network_artifacts=1; "
        "ip -4 route show table 354 2>/dev/null | grep -q . && network_artifacts=1; "
        "if command -v nft >/dev/null 2>&1; then "
        "nft list chains 2>/dev/null | grep -q 'chain openclash' && network_artifacts=1; fi; "
        f"[ \"$network_artifacts\" = {quote_remote(expected_artifacts)} ]; "
        f"{tun_check}; "
        "/etc/init.d/dnsmasq running >/dev/null 2>&1"
    )
    try:
        ssh_command(host, command, capture=True)
    except subprocess.CalledProcessError as exc:
        raise ConfigError("ROLLBACK_HEALTH_LAYER0_2_FAILED") from exc


def verify_post_rollback_health(host: str, transaction: DeploymentTransaction) -> None:
    if transaction.original_running:
        wait_for_openclash_running(host, max_wait_seconds=15)
        verify_remote_health(
            host,
            remote_path=transaction.original_active_path,
            core_path=transaction.core_path,
        )
    else:
        verify_stopped_openclash_health(host, transaction)
    verify_lan_client_egress()


def rollback_remote_deployment(
    host: str,
    *,
    transaction: DeploymentTransaction,
) -> None:
    restore_errors: list[str] = []

    def restore_step(label: str, command: str, *, required: bool = True) -> None:
        try:
            ssh_command(host, command, capture=True)
        except subprocess.CalledProcessError:
            if required:
                restore_errors.append(label)

    # Stop first, while OpenClash's live UCI still contains the DNS/firewall
    # bookkeeping required by revert_dnsmasq() and revert_firewall().  A procd
    # "service delete: Not found" must not prevent the remaining restoration.
    restore_step(
        "pre_restore_stop",
        "OPENCLASH_ROLLBACK_STOP=1; /etc/init.d/openclash stop",
        required=False,
    )

    try:
        restore_step(
            "target_yaml",
            (
                f"if [ -f {quote_remote(transaction.target_absent_marker)} ]; then "
                f"rm -f {quote_remote(transaction.remote_path)}; else "
                f"cp -p {quote_remote(transaction.target_backup)} "
                f"{quote_remote(transaction.remote_path)}; "
                f"chmod 600 {quote_remote(transaction.remote_path)}; fi"
            ),
        )
        restore_step(
            "active_yaml",
            (
                f"cp -p {quote_remote(transaction.active_backup)} "
                f"{quote_remote(transaction.original_active_path)}; "
                f"chmod 600 {quote_remote(transaction.original_active_path)}"
                if transaction.original_active_exists
                else f"rm -f {quote_remote(transaction.original_active_path)}"
            ),
        )
        restore_step(
            "openclash_uci",
            f"cp -p {quote_remote(transaction.openclash_uci_backup)} /etc/config/openclash",
        )
        restore_step(
            "dhcp_uci",
            f"cp -p {quote_remote(transaction.dhcp_uci_backup)} /etc/config/dhcp",
        )
        restore_step(
            "firewall_uci",
            f"cp -p {quote_remote(transaction.firewall_uci_backup)} /etc/config/firewall",
        )
    finally:
        # This is deliberately independent from file/UCI restoration.  Even if
        # one copy fails, reload the saved dataplane and restore service state.
        restore_step("firewall_reload", "/etc/init.d/firewall reload")
        restore_step("dnsmasq_restart", "/etc/init.d/dnsmasq restart")
        if transaction.original_running or not transaction.original_network_artifacts:
            residual_cleanup = (
                "while ip -4 rule del fwmark 0x162 table 354 2>/dev/null; do :; done; "
                "ip -4 route flush table 354 2>/dev/null || true; "
                "while ip -6 rule del fwmark 0x162 table 354 2>/dev/null; do :; done; "
                "ip -6 route flush table 354 2>/dev/null || true"
            )
            if not transaction.original_tun_present:
                residual_cleanup += (
                    "; ip link show utun >/dev/null 2>&1 && "
                    "ip link delete utun 2>/dev/null || true"
                )
            restore_step("policy_route_cleanup", residual_cleanup)
        restore_step(
            "boot_state",
            (
                "/etc/init.d/openclash enable"
                if transaction.original_enabled
                else "/etc/init.d/openclash disable"
            ),
        )
        restore_step(
            "service_state",
            (
                "/etc/init.d/openclash start"
                if transaction.original_running
                else "/etc/init.d/openclash stop"
            ),
            required=False,
        )

    if restore_errors:
        raise ConfigError(
            "ROLLBACK_FAILED: restore steps failed: " + ",".join(restore_errors)
        )

    verify_parts = [
        "OPENCLASH_ROLLBACK_VERIFY=1; set -e",
        (
            f"if [ -f {quote_remote(transaction.target_absent_marker)} ]; then "
            f"[ ! -e {quote_remote(transaction.remote_path)} ]; else "
            f"cmp -s {quote_remote(transaction.target_backup)} "
            f"{quote_remote(transaction.remote_path)}; fi"
        ),
        f"[ \"$(uci -q get openclash.config.config_path)\" = "
        f"{quote_remote(transaction.original_active_path)} ]",
        f"grep -Fqx {quote_remote(f'active_path={transaction.original_active_path}')} "
        f"{quote_remote(transaction.service_state_backup)}",
        (
            "/etc/init.d/openclash enabled >/dev/null 2>&1"
            if transaction.original_enabled
            else "! /etc/init.d/openclash enabled >/dev/null 2>&1"
        ),
    ]
    if not transaction.original_running:
        verify_parts.extend(
            [
                f"cmp -s {quote_remote(transaction.openclash_uci_backup)} /etc/config/openclash",
                f"cmp -s {quote_remote(transaction.dhcp_uci_backup)} /etc/config/dhcp",
                f"cmp -s {quote_remote(transaction.firewall_uci_backup)} /etc/config/firewall",
            ]
        )
    try:
        ssh_command(host, "; ".join(verify_parts), capture=True)
        verify_post_rollback_health(host, transaction)
        verify_network_path = transaction.network_state_backup + ".verify"
        ssh_command(
            host,
            "OPENCLASH_ROLLBACK_NETWORK_VERIFY=1; set -e; "
            + network_state_capture_command(verify_network_path)
            + f"; cmp -s {quote_remote(transaction.network_state_backup)} "
            + f"{quote_remote(verify_network_path)}; rm -f {quote_remote(verify_network_path)}",
            capture=True,
        )
    except (subprocess.CalledProcessError, ConfigError) as exc:
        raise ConfigError("ROLLBACK_FAILED: rollback verification failed") from exc


def upload_candidate(
    local_file: Path,
    *,
    host: str,
    remote_name: str | None,
    core_path: str,
) -> UploadedCandidate:
    """Upload and validate an immutable candidate without reading production state."""
    local_file = local_file.expanduser().resolve()
    if not local_file.is_file():
        raise ConfigError(f"Output file does not exist: {local_file}")
    validate_config(load_yaml(local_file))

    filename = remote_name or local_file.name
    if "/" in filename or filename in {".", ".."}:
        raise ConfigError("--remote-name must be a plain filename.")

    digest = hashlib.sha256(local_file.read_bytes()).hexdigest()
    production_path = f"/etc/openclash/config/{filename}"
    candidate_path = f"{REMOTE_CANDIDATE_DIR}/{filename}.{digest[:16]}.candidate"
    remote_tmp = f"/tmp/{filename}.upload.{uuid.uuid4().hex}"

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
        install = (
            "OPENCLASH_CANDIDATE_UPLOAD=1; set -e; "
            f"chmod 600 {quote_remote(remote_tmp)}; "
            f"[ \"$(sha256sum {quote_remote(remote_tmp)} | awk '{{print $1}}')\" = "
            f"{quote_remote(digest)} ]; "
            f"{quote_remote(core_path)} -t -d /etc/openclash -f {quote_remote(remote_tmp)}; "
            f"mkdir -p {quote_remote(REMOTE_CANDIDATE_DIR)}; "
            f"if [ -e {quote_remote(candidate_path)} ]; then "
            f"cmp -s {quote_remote(remote_tmp)} {quote_remote(candidate_path)}; "
            f"rm -f {quote_remote(remote_tmp)}; else "
            f"mv {quote_remote(remote_tmp)} {quote_remote(candidate_path)}; fi; "
            f"chmod 600 {quote_remote(candidate_path)}"
        )
        ssh_command(host, install, capture=True)
    except subprocess.CalledProcessError as exc:
        try:
            ssh_command(host, f"rm -f {quote_remote(remote_tmp)}", capture=True)
        except subprocess.CalledProcessError as cleanup_exc:
            raise ConfigError("REMOTE_CANDIDATE_UPLOAD_AND_CLEANUP_FAILED") from cleanup_exc
        raise ConfigError("REMOTE_CANDIDATE_UPLOAD_FAILED; production unchanged") from exc
    return UploadedCandidate(candidate_path, production_path)


def activate_uploaded_candidate(
    candidate: UploadedCandidate,
    *,
    host: str,
    core_path: str,
) -> str:
    """Begin the deployment transaction and atomically activate one candidate."""
    remote_path = candidate.production_path
    filename = Path(remote_path).name
    stamp = f"{now_stamp()}-{uuid.uuid4().hex[:8]}"
    target_backup = f"/tmp/{filename}.target-yaml.{stamp}.bak"
    target_absent_marker = f"/tmp/{filename}.target-absent.{stamp}"
    active_backup = f"/tmp/{filename}.active-yaml.{stamp}.bak"
    openclash_uci_backup = f"/etc/config/openclash.bak.{stamp}"
    dhcp_uci_backup = f"/tmp/{filename}.dhcp-uci.{stamp}.bak"
    firewall_uci_backup = f"/tmp/{filename}.firewall-uci.{stamp}.bak"
    service_state_backup = f"/tmp/{filename}.service-state.{stamp}"
    network_state_backup = f"/tmp/{filename}.network-state.{stamp}"

    original_state = read_remote_openclash_state(host)
    original_active_path = str(original_state["active_path"])
    original_active_exists = bool(original_state["active_exists"])
    original_enabled = bool(original_state["enabled"])
    original_running = bool(original_state["running"])
    original_core_running = bool(original_state["core_running"])
    original_network_artifacts = bool(original_state["network_artifacts"])
    original_tun_present = bool(original_state["tun_present"])

    if original_running != original_core_running:
        raise ConfigError("REMOTE_OPENCLASH_STATE_INCONSISTENT")
    if not original_running and (original_network_artifacts or original_tun_present):
        raise ConfigError(
            "REMOTE_STOPPED_DATAPLANE_INCONSISTENT: repair stale OpenClash "
            "DNS/firewall/policy-route/TUN state before activation"
        )

    transaction = DeploymentTransaction(
        remote_path=remote_path,
        target_backup=target_backup,
        target_absent_marker=target_absent_marker,
        original_active_path=original_active_path,
        original_active_exists=original_active_exists,
        active_backup=active_backup,
        openclash_uci_backup=openclash_uci_backup,
        dhcp_uci_backup=dhcp_uci_backup,
        firewall_uci_backup=firewall_uci_backup,
        service_state_backup=service_state_backup,
        network_state_backup=network_state_backup,
        core_path=core_path,
        original_enabled=original_enabled,
        original_running=original_running,
        original_core_running=original_core_running,
        original_network_artifacts=original_network_artifacts,
        original_tun_present=original_tun_present,
    )

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
        f"cp -p /etc/config/openclash {quote_remote(openclash_uci_backup)}; "
        f"cp -p /etc/config/dhcp {quote_remote(dhcp_uci_backup)}; "
        f"cp -p /etc/config/firewall {quote_remote(firewall_uci_backup)}; "
        f"printf '%s\\n' {quote_remote(f'active_path={original_active_path}')} "
        f"{quote_remote(f'active_exists={int(original_active_exists)}')} "
        f"{quote_remote(f'enabled={int(original_enabled)}')} "
        f"{quote_remote(f'running={int(original_running)}')} "
        f"{quote_remote(f'core_running={int(original_core_running)}')} "
        f"{quote_remote(f'network_artifacts={int(original_network_artifacts)}')} "
        f"{quote_remote(f'tun_present={int(original_tun_present)}')} "
        f"> {quote_remote(service_state_backup)}; "
        + network_state_capture_command(network_state_backup)
    )
    try:
        ssh_command(host, snapshot)
    except subprocess.CalledProcessError as exc:
        raise ConfigError("Remote backup failed; deployment was not started.") from exc

    activation_tmp = f"{remote_path}.activate.{uuid.uuid4().hex}.tmp"
    validate_and_install = (
        "OPENCLASH_ACTIVATION_INSTALL=1; set -e; "
        f"[ -f {quote_remote(candidate.candidate_path)} ]; "
        f"{quote_remote(core_path)} -t -d /etc/openclash "
        f"-f {quote_remote(candidate.candidate_path)}; "
        f"cp -p {quote_remote(candidate.candidate_path)} {quote_remote(activation_tmp)}; "
        f"chmod 600 {quote_remote(activation_tmp)}; "
        f"mv -f {quote_remote(activation_tmp)} {quote_remote(remote_path)}"
    )
    try:
        ssh_command(host, validate_and_install, capture=True)
    except subprocess.CalledProcessError as exc:
        rollback_remote_deployment(host, transaction=transaction)
        raise ConfigError("REMOTE_ACTIVATION_INSTALL_FAILED_ROLLED_BACK") from exc

    service_action = "restart" if original_running else "start"
    activate_cmd = (
        "OPENCLASH_ACTIVATION_START=1; set -e; "
        f"uci set openclash.config.config_path={quote_remote(remote_path)}; "
        "uci set openclash.config.enable='1'; uci commit openclash; "
        f"/etc/init.d/openclash {service_action}"
    )
    try:
        ssh_command(host, activate_cmd, capture=True)
        wait_for_openclash_running(host, max_wait_seconds=15)
        verify_remote_health(host, remote_path=remote_path, core_path=core_path)
    except (subprocess.CalledProcessError, ConfigError) as exc:
        rollback_remote_deployment(host, transaction=transaction)
        raise ConfigError("HEALTH_CHECK_FAILED_ROLLED_BACK") from exc

    return remote_path


def deploy(
    local_file: Path,
    *,
    host: str,
    remote_name: str | None,
    core_path: str,
    activate: bool,
) -> str:
    candidate = upload_candidate(
        local_file, host=host, remote_name=remote_name, core_path=core_path
    )
    probe_uploaded_candidate(
        local_file,
        host=host,
        core_path=core_path,
        candidate_path=candidate.candidate_path,
    )
    if not activate:
        return candidate.candidate_path
    return activate_uploaded_candidate(candidate, host=host, core_path=core_path)


def print_summary(data: dict[str, Any], output: Path, audit_output: Path | None) -> None:
    groups = {group["name"]: group for group in data["proxy-groups"]}
    print(f"output={output}")
    if audit_output is not None:
        print(f"audit_output={audit_output}")
    print(f"static_nodes={len(data['proxies'])}")
    print(f"managed_groups={len(data['proxy-groups'])}")
    print("priority_wrappers=0")
    print(f"gpt_candidates={len(groups['GPT候选']['proxies'])}")
    print(f"gemini_candidates={len(groups['Gemini候选']['proxies'])}")
    print(f"disney_candidates={len(groups['迪士尼候选']['proxies'])}")
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
        print(
            f"{service}_definitive_pass="
            f"{report.get('definitive_pass_counts', {}).get(service, 0)}"
        )
        print(f"{service}_final_group_count={final_count}")


def add_probe_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--probe-core")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_LKG_STATE_PATH)
    parser.add_argument("--probe-report", type=Path, default=DEFAULT_PROBE_REPORT_PATH)
    parser.add_argument(
        "--manual-results",
        type=Path,
        help="Structured, timestamped definitive manual use results (no cookies or content).",
    )
    parser.add_argument(
        "--functional-results",
        type=Path,
        action="append",
        default=[],
        help="Snapshot-bound definitive browser or Disney result JSON (repeatable).",
    )


def add_source_args(parser: argparse.ArgumentParser, *, include_source: bool = True) -> None:
    if include_source:
        parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--source-snapshot",
        type=Path,
        help="Replay one verified immutable source snapshot; never reread the live source.",
    )
    refresh = parser.add_mutually_exclusive_group()
    refresh.add_argument(
        "--refresh-source",
        dest="no_refresh_source",
        action="store_false",
        help="Refresh the bound subscription before freezing the source (default).",
    )
    refresh.add_argument(
        "--no-refresh-source",
        dest="no_refresh_source",
        action="store_true",
        help="Explicitly freeze the current live source without claiming it is fresh.",
    )
    parser.set_defaults(no_refresh_source=False)
    parser.add_argument(
        "--refresh-adapter",
        type=Path,
        help=(
            "Executable custom bridge that calls the authenticated loopback source-only "
            "endpoint and reuses Clash Verge profile update semantics."
        ),
    )
    parser.add_argument("--refresh-timeout", type=int, default=120)
    parser.add_argument(
        "--min-node-retention-ratio",
        type=float,
        default=DEFAULT_MIN_NODE_RETENTION_RATIO,
    )
    parser.add_argument(
        "--source-identity-key",
        type=Path,
        default=DEFAULT_SOURCE_IDENTITY_KEY,
    )
    parser.add_argument(
        "--source-freshness-ttl",
        type=int,
        default=DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS,
    )
    parser.add_argument(
        "--allow-stale-source-activate",
        action="store_true",
        help="Explicit human approval to activate a snapshot older than the configured TTL.",
    )


def validate_snapshot_for_activation(
    manifest: dict[str, Any], *, freshness_ttl: int, allow_stale: bool
) -> None:
    created = parse_aware_timestamp(str(manifest.get("created_at", "")), field="snapshot")
    age = (dt.datetime.now().astimezone() - created).total_seconds()
    if age > freshness_ttl and not allow_stale:
        raise ConfigError("BLOCKED_ACTIVATION_STALE_SOURCE_SNAPSHOT")


def add_deploy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="root@192.168.10.1")
    parser.add_argument("--remote-name")
    parser.add_argument("--core-path", default="/etc/openclash/core/clash_meta")
    activation = parser.add_mutually_exclusive_group()
    activation.add_argument(
        "--activate",
        dest="activate",
        action="store_true",
        help="Select the installed config through UCI and restart OpenClash after validation.",
    )
    activation.add_argument(
        "--no-activate",
        dest="activate",
        action="store_false",
        help="Upload and sidecar-test only; do not enter the activation transaction.",
    )
    parser.set_defaults(activate=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the accepted simple static OpenClash profile from Clash Verge."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser("export", help="Deprecated; use snapshot-source.")
    export_p.add_argument("--source", type=Path)
    export_p.add_argument(
        "--workdir", type=Path, default=Path.home() / "Desktop/openclash-static-work"
    )

    transform_p = sub.add_parser("transform", help="Transform an effective YAML locally.")
    transform_p.add_argument("--source-snapshot", type=Path, required=True)
    transform_p.add_argument("--output", type=Path, required=True)
    transform_p.add_argument("--audit-output", type=Path)

    all_p = sub.add_parser("all", help="Export and transform; optionally deploy.")
    add_source_args(all_p)
    all_p.add_argument(
        "--workdir", type=Path, default=Path.home() / "Desktop/openclash-static-work"
    )
    all_p.add_argument("--output-name", default="openclash-simple-final.yaml")
    all_p.add_argument("--audit-name", default="openclash-simple-final-audit.yaml")
    all_p.add_argument("--deploy", action="store_true")
    add_probe_args(all_p)
    add_deploy_args(all_p)

    refresh_p = sub.add_parser(
        "refresh-source",
        help="Refresh the bound Clash Verge subscription and freeze an immutable snapshot.",
    )
    refresh_p.add_argument(
        "--workdir", type=Path, default=Path.home() / "Desktop/openclash-static-work"
    )
    add_source_args(refresh_p)

    snapshot_p = sub.add_parser(
        "snapshot-source",
        help="Freeze the current source without refresh and mark the skip explicitly.",
    )
    snapshot_p.add_argument(
        "--workdir", type=Path, default=Path.home() / "Desktop/openclash-static-work"
    )
    add_source_args(snapshot_p)
    snapshot_p.set_defaults(no_refresh_source=True)

    deploy_p = sub.add_parser("deploy", help="Validate and install an existing full YAML.")
    deploy_p.add_argument("--file", type=Path, required=True)
    deploy_p.add_argument("--source-snapshot", type=Path, required=True)
    add_deploy_args(deploy_p)

    upload_p = sub.add_parser(
        "upload-candidate",
        help="Upload and validate an immutable candidate without reading production state.",
    )
    upload_p.add_argument("--file", type=Path, required=True)
    upload_p.add_argument("--source-snapshot", type=Path, required=True)
    upload_p.add_argument("--host", default="root@192.168.10.1")
    upload_p.add_argument("--remote-name")
    upload_p.add_argument("--core-path", default="/etc/openclash/core/clash_meta")

    candidate_probe_p = sub.add_parser(
        "probe-candidate",
        help="Test a candidate in an isolated router sidecar without TUN/firewall changes.",
    )
    candidate_probe_p.add_argument("--file", type=Path, required=True)
    candidate_probe_p.add_argument("--source-snapshot", type=Path, required=True)
    candidate_probe_p.add_argument("--candidate-path")
    candidate_probe_p.add_argument("--host", default="root@192.168.10.1")
    candidate_probe_p.add_argument(
        "--core-path", default="/etc/openclash/core/clash_meta"
    )

    activate_p = sub.add_parser(
        "activate", help="Activate a previously uploaded candidate transactionally."
    )
    activate_p.add_argument("--candidate-path", required=True)
    activate_p.add_argument("--production-name", required=True)
    activate_p.add_argument("--source-snapshot", type=Path, required=True)
    activate_p.add_argument(
        "--source-freshness-ttl", type=int, default=DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS
    )
    activate_p.add_argument("--allow-stale-source-activate", action="store_true")
    activate_p.add_argument("--host", default="root@192.168.10.1")
    activate_p.add_argument("--core-path", default="/etc/openclash/core/clash_meta")

    probe_p = sub.add_parser(
        "probe", help="Test static nodes locally without generating or deploying OpenClash."
    )
    probe_p.add_argument(
        "--workdir", type=Path, default=Path.home() / "Desktop/openclash-static-work"
    )
    add_source_args(probe_p)
    probe_p.add_argument("--update-lkg", action="store_true")
    add_probe_args(probe_p)

    reconcile_p = sub.add_parser(
        "reconcile-probe",
        help="Apply timestamped manual results to an existing report without network access.",
    )
    reconcile_p.add_argument(
        "--source-snapshot", type=Path, required=True, help="Verified frozen source manifest."
    )
    reconcile_p.add_argument("--probe-report", type=Path, required=True)
    reconcile_p.add_argument("--state-path", type=Path, required=True)
    reconcile_p.add_argument("--manual-results", type=Path, required=True)
    reconcile_p.add_argument(
        "--functional-results", type=Path, action="append", default=[]
    )
    reconcile_p.add_argument("--report-output", type=Path, required=True)
    reconcile_p.add_argument("--state-output", type=Path, required=True)
    reconcile_p.add_argument("--output", type=Path, required=True)
    reconcile_p.add_argument("--audit-output", type=Path)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "export":
            raise ConfigError("SOURCE_EXPORT_REPLACED_BY_SNAPSHOT_SOURCE")

        if args.command == "transform":
            _manifest, frozen_source = verify_source_snapshot(args.source_snapshot)
            output = args.output.expanduser().resolve()
            audit_output = args.audit_output.expanduser().resolve() if args.audit_output else None
            data = transform_file(frozen_source, output, audit_output)
            print_summary(data, output, audit_output)
            return 0

        if args.command == "all":
            workdir = args.workdir.expanduser().resolve()
            if not 0 < args.min_node_retention_ratio <= 1:
                raise ConfigError("--min-node-retention-ratio must be in (0, 1].")
            snapshot_manifest, exported, source_runtime = prepare_source_snapshot(
                source=args.source,
                workdir=workdir,
                refresh_adapter=args.refresh_adapter,
                no_refresh=args.no_refresh_source,
                source_snapshot=args.source_snapshot,
                identity_key_path=args.source_identity_key,
                refresh_timeout=args.refresh_timeout,
                min_node_retention_ratio=args.min_node_retention_ratio,
            )
            output = workdir / args.output_name
            audit_output = workdir / args.audit_name
            source_data = load_yaml(exported)
            probe_runner = run_local_service_probe
            if args.deploy:
                probe_runner = lambda data, *, core_path: run_remote_service_probe(
                    data, host=args.host, core_path=args.core_path
                )
            selections, probe_report = dynamic_probe_and_select(
                source_data,
                state_path=args.state_path,
                report_path=args.probe_report,
                core_path=args.probe_core,
                update_lkg=True,
                manual_results_path=args.manual_results,
                functional_results_paths=args.functional_results,
                snapshot_manifest=snapshot_manifest,
                probe_runner=probe_runner,
            )
            if args.activate and probe_report.get("activation_blocked_reasons"):
                raise ConfigError(
                    "BLOCKED_ACTIVATION_NON_DEFINITIVE_SERVICE_RESULTS: "
                    + ",".join(probe_report["activation_blocked_reasons"])
                )
            if args.activate:
                validate_snapshot_for_activation(
                    snapshot_manifest,
                    freshness_ttl=args.source_freshness_ttl,
                    allow_stale=args.allow_stale_source_activate,
                )
            transform_file(exported, output, audit_output, selections)
            data = load_yaml(output)
            print(f"source_snapshot={source_runtime.get('manifest_path', args.source_snapshot)}")
            print(f"source_snapshot_id={snapshot_manifest['source_snapshot_id']}")
            print(f"source_hash={snapshot_manifest['source_hash']}")
            print(f"source_age_seconds={snapshot_manifest.get('source_age_seconds_at_snapshot', 0)}")
            if source_runtime.get("report_path"):
                print(f"source_refresh_report={source_runtime['report_path']}")
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

        if args.command in {"refresh-source", "snapshot-source"}:
            if args.command == "refresh-source" and args.no_refresh_source:
                raise ConfigError("refresh-source cannot be combined with --no-refresh-source")
            if args.command == "refresh-source" and args.source_snapshot:
                raise ConfigError("refresh-source cannot replay an existing snapshot")
            if args.command == "snapshot-source" and not args.no_refresh_source:
                raise ConfigError("snapshot-source cannot be combined with --refresh-source")
            if not 0 < args.min_node_retention_ratio <= 1:
                raise ConfigError("--min-node-retention-ratio must be in (0, 1].")
            manifest, _payload, runtime = prepare_source_snapshot(
                source=args.source,
                workdir=args.workdir.expanduser().resolve(),
                refresh_adapter=args.refresh_adapter,
                no_refresh=args.no_refresh_source,
                source_snapshot=args.source_snapshot,
                identity_key_path=args.source_identity_key,
                refresh_timeout=args.refresh_timeout,
                min_node_retention_ratio=args.min_node_retention_ratio,
            )
            print(f"source_snapshot={runtime.get('manifest_path', args.source_snapshot)}")
            print(f"source_snapshot_id={manifest['source_snapshot_id']}")
            print(f"source_hash={manifest['source_hash']}")
            print(f"source_age_seconds={manifest.get('source_age_seconds_at_snapshot', 0)}")
            if runtime.get("report_path"):
                print(f"source_refresh_report={runtime['report_path']}")
            print(f"refresh_result={runtime.get('refresh_result', 'SNAPSHOT_REPLAY')}")
            print("router_contacted=false")
            print("openclash_touched=false")
            return 0

        if args.command == "probe":
            snapshot_manifest, source, _runtime = prepare_source_snapshot(
                source=args.source,
                workdir=args.workdir.expanduser().resolve(),
                refresh_adapter=args.refresh_adapter,
                no_refresh=args.no_refresh_source,
                source_snapshot=args.source_snapshot,
                identity_key_path=args.source_identity_key,
                refresh_timeout=args.refresh_timeout,
                min_node_retention_ratio=args.min_node_retention_ratio,
            )
            source_data = load_yaml(source)
            dynamic_probe_and_select(
                source_data,
                state_path=args.state_path,
                report_path=args.probe_report,
                core_path=args.probe_core,
                update_lkg=args.update_lkg,
                manual_results_path=args.manual_results,
                functional_results_paths=args.functional_results,
                snapshot_manifest=snapshot_manifest,
            )
            print_probe_summary(args.probe_report)
            print(f"lkg_updated={str(args.update_lkg).lower()}")
            print("router_contacted=false")
            return 0

        if args.command == "reconcile-probe":
            snapshot_manifest, source = verify_source_snapshot(args.source_snapshot)
            source_data = load_yaml(source)
            selections, _ = reconcile_existing_probe(
                source_data,
                state_path=args.state_path.expanduser().resolve(),
                probe_report_path=args.probe_report.expanduser().resolve(),
                manual_results_path=args.manual_results.expanduser().resolve(),
                functional_results_paths=args.functional_results,
                report_output_path=args.report_output.expanduser().resolve(),
                state_output_path=args.state_output.expanduser().resolve(),
                snapshot_manifest=snapshot_manifest,
            )
            output = args.output.expanduser().resolve()
            audit_output = (
                args.audit_output.expanduser().resolve() if args.audit_output else None
            )
            transform_file(source, output, audit_output, selections)
            print_summary(load_yaml(output), output, audit_output)
            print_probe_summary(args.report_output)
            print("network_probe_run=false")
            print("router_contacted=false")
            print("activated=false")
            return 0

        if args.command == "deploy":
            manifest, _ = verify_source_snapshot(args.source_snapshot)
            remote = deploy(
                args.file,
                host=args.host,
                remote_name=args.remote_name,
                core_path=args.core_path,
                activate=args.activate,
            )
            print(f"remote_config={remote}")
            print(f"source_snapshot_id={manifest['source_snapshot_id']}")
            print(f"activated={str(args.activate).lower()}")
            return 0

        if args.command == "upload-candidate":
            manifest, _ = verify_source_snapshot(args.source_snapshot)
            candidate = upload_candidate(
                args.file,
                host=args.host,
                remote_name=args.remote_name,
                core_path=args.core_path,
            )
            print(f"candidate_config={candidate.candidate_path}")
            print(f"production_config={candidate.production_path}")
            print(f"source_snapshot_id={manifest['source_snapshot_id']}")
            print("production_state_read=false")
            return 0

        if args.command == "probe-candidate":
            manifest, _ = verify_source_snapshot(args.source_snapshot)
            if args.candidate_path and not args.candidate_path.startswith(
                REMOTE_CANDIDATE_DIR + "/"
            ):
                raise ConfigError("--candidate-path must be in the candidate directory.")
            probe_uploaded_candidate(
                args.file,
                host=args.host,
                core_path=args.core_path,
                candidate_path=args.candidate_path,
            )
            print("candidate_probe=pass")
            print(f"source_snapshot_id={manifest['source_snapshot_id']}")
            print("production_state_changed=false")
            return 0

        if args.command == "activate":
            manifest, _ = verify_source_snapshot(args.source_snapshot)
            validate_snapshot_for_activation(
                manifest,
                freshness_ttl=args.source_freshness_ttl,
                allow_stale=args.allow_stale_source_activate,
            )
            production_name = args.production_name
            if "/" in production_name or production_name in {".", ".."}:
                raise ConfigError("--production-name must be a plain filename.")
            candidate_path = args.candidate_path
            if not candidate_path.startswith(REMOTE_CANDIDATE_DIR + "/"):
                raise ConfigError("--candidate-path must be in the candidate directory.")
            remote = activate_uploaded_candidate(
                UploadedCandidate(
                    candidate_path,
                    f"/etc/openclash/config/{production_name}",
                ),
                host=args.host,
                core_path=args.core_path,
            )
            print(f"remote_config={remote}")
            print(f"source_snapshot_id={manifest['source_snapshot_id']}")
            print("activated=true")
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
