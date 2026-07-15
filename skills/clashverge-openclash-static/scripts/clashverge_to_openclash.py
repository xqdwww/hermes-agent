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
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
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


def transform(data: dict[str, Any]) -> dict[str, Any]:
    output = remove_clash_verge_runtime(deepcopy(data))
    proxies = static_proxy_objects(output)
    output["proxies"] = proxies
    names = [str(proxy["name"]) for proxy in proxies]
    source_order = {name: index for index, name in enumerate(names)}

    all_nodes = stable_region_sort(names, source_order)
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

    output["proxy-groups"] = build_groups(all_nodes, gpt_nodes, gemini_nodes, disney_nodes)
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


def transform_file(input_path: Path, output_path: Path, audit_output: Path | None) -> dict[str, Any]:
    transformed = transform(load_yaml(input_path))
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
    add_deploy_args(all_p)

    deploy_p = sub.add_parser("deploy", help="Validate and install an existing full YAML.")
    deploy_p.add_argument("--file", type=Path, required=True)
    add_deploy_args(deploy_p)

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
            data = transform_file(exported, output, audit_output)
            print(f"source_copy={exported}")
            print_summary(data, output, audit_output)
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
