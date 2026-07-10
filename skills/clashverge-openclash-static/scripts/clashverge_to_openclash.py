#!/usr/bin/env python3
"""Export, transform, validate, and optionally deploy a Clash Verge effective config to OpenClash.

The transformation is intentionally minimal and deterministic:
- preserve all existing nodes, groups, and rules;
- add/update a manual group containing every static node;
- add/update an automatic url-test group containing every static node;
- add media-labelled nodes to the Disney group;
- make the final MATCH rule use the manual group.

The script never prints proxy credentials or the YAML body.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

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


class ConfigError(RuntimeError):
    """Raised when the source configuration cannot be transformed safely."""


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
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
    matches = sorted(base.glob("*clash-verge*/**/clash-verge.yaml")) if base.exists() else []
    for match in matches:
        if match.is_file():
            return match

    searched = "\n".join(f"  - {p}" for p in DEFAULT_VERGE_CANDIDATES)
    raise ConfigError(
        "Could not find the Clash Verge effective configuration. Checked:\n"
        f"{searched}\nPass --source explicitly."
    )


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Cannot read source file: {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("The YAML root must be a mapping/object.")
    return data


def dump_yaml(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=4096,
    )
    path.write_text(text, encoding="utf-8")


def ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def static_node_names(data: dict[str, Any]) -> list[str]:
    proxies = data.get("proxies")
    if not isinstance(proxies, list) or not proxies:
        raise ConfigError(
            "No static nodes were found under 'proxies:'. Export the Clash Verge effective/merged "
            "configuration rather than a provider-only subscription."
        )

    names: list[str] = []
    for index, proxy in enumerate(proxies):
        if not isinstance(proxy, dict):
            raise ConfigError(f"proxies[{index}] is not an object.")
        name = proxy.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"proxies[{index}] has no valid name.")
        names.append(name)

    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"Duplicate proxy names detected: {', '.join(duplicates)}")
    return names


def ensure_group_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    groups = data.setdefault("proxy-groups", [])
    if not isinstance(groups, list):
        raise ConfigError("'proxy-groups' must be a list.")
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ConfigError(f"proxy-groups[{index}] is not an object.")
    return groups


def upsert_group(groups: list[dict[str, Any]], group: dict[str, Any], *, position: int | None = None) -> None:
    name = group["name"]
    existing_index = next((i for i, item in enumerate(groups) if item.get("name") == name), None)
    if existing_index is not None:
        groups[existing_index] = group
        if position is not None and existing_index != position:
            item = groups.pop(existing_index)
            groups.insert(min(position, len(groups)), item)
        return
    if position is None:
        groups.append(group)
    else:
        groups.insert(min(position, len(groups)), group)


def update_disney_group(
    groups: list[dict[str, Any]],
    node_names: list[str],
    disney_group: str,
    media_keywords: list[str],
) -> list[str]:
    group = next((item for item in groups if item.get("name") == disney_group), None)
    if group is None:
        group = {"name": disney_group, "type": "select", "proxies": []}
        groups.append(group)

    proxies = group.get("proxies", [])
    if not isinstance(proxies, list):
        raise ConfigError(f"Group '{disney_group}' has a non-list proxies field.")

    matched = [
        name
        for name in node_names
        if any(keyword.casefold() in name.casefold() for keyword in media_keywords)
    ]
    group["proxies"] = ordered_unique([str(item) for item in proxies] + matched)
    return matched


def ensure_final_match(data: dict[str, Any], manual_group: str) -> None:
    rules = data.setdefault("rules", [])
    if not isinstance(rules, list):
        raise ConfigError("'rules' must be a list.")

    new_rules: list[Any] = []
    for rule in rules:
        if isinstance(rule, str) and rule.strip().upper().startswith("MATCH,"):
            continue
        new_rules.append(rule)
    new_rules.append(f"MATCH,{manual_group}")
    data["rules"] = new_rules


def validate_references(data: dict[str, Any], node_names: list[str]) -> None:
    groups = data.get("proxy-groups", [])
    group_names = {
        item.get("name")
        for item in groups
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    valid_targets = set(node_names) | group_names | {"DIRECT", "REJECT", "REJECT-DROP", "PASS"}

    errors: list[str] = []
    for group in groups:
        name = group.get("name", "<unnamed>")
        refs = group.get("proxies", [])
        if refs is None:
            continue
        if not isinstance(refs, list):
            errors.append(f"group '{name}' has a non-list proxies field")
            continue
        for ref in refs:
            if isinstance(ref, str) and ref not in valid_targets:
                errors.append(f"group '{name}' references missing target '{ref}'")

    if errors:
        raise ConfigError("Reference validation failed:\n- " + "\n- ".join(errors))


def transform(
    data: dict[str, Any],
    *,
    manual_group: str,
    auto_group: str,
    disney_group: str,
    media_keywords: list[str],
    test_url: str,
    interval: int,
    tolerance: int,
) -> dict[str, Any]:
    node_names = static_node_names(data)
    groups = ensure_group_list(data)

    auto = {
        "name": auto_group,
        "type": "url-test",
        "proxies": node_names.copy(),
        "url": test_url,
        "interval": interval,
        "tolerance": tolerance,
        "lazy": True,
    }
    manual = {
        "name": manual_group,
        "type": "select",
        "proxies": [auto_group] + node_names,
    }

    # Manual first, automatic second, then the user's specialist groups.
    upsert_group(groups, manual, position=0)
    upsert_group(groups, auto, position=1)
    matched_media = update_disney_group(groups, node_names, disney_group, media_keywords)
    ensure_final_match(data, manual_group)
    validate_references(data, node_names)

    return data


def export_source(source: Path | None, workdir: Path) -> Path:
    source = source or find_default_source()
    if not source.is_file():
        raise ConfigError(f"Source does not exist: {source}")
    workdir.mkdir(parents=True, exist_ok=True)
    destination = workdir / f"clash-verge-effective-{now_stamp()}.yaml"
    shutil.copy2(source, destination)
    return destination


def quote_remote(path: str) -> str:
    return shlex.quote(path)


def ssh_command(host: str, command: str, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["ssh", host, command], capture=capture)


def deploy(
    local_file: Path,
    *,
    host: str,
    remote_name: str | None,
    core_path: str,
    activate: bool,
) -> str:
    if not local_file.is_file():
        raise ConfigError(f"Output file does not exist: {local_file}")

    filename = remote_name or local_file.name
    if "/" in filename or filename in {".", ".."}:
        raise ConfigError("--remote-name must be a plain filename.")

    remote_dir = "/etc/openclash/config"
    remote_path = f"{remote_dir}/{filename}"
    stamp = now_stamp()
    remote_backup = f"{remote_path}.bak.{stamp}"
    remote_tmp = f"/tmp/{filename}.upload.{stamp}"

    ssh_command(
        host,
        "set -e; "
        f"mkdir -p {quote_remote(remote_dir)}; "
        f"if [ -f {quote_remote(remote_path)} ]; then cp -p {quote_remote(remote_path)} {quote_remote(remote_backup)}; fi",
    )

    run(["scp", "-O", str(local_file), f"{host}:{remote_tmp}"])

    test_cmd = (
        "set -e; "
        f"chmod 600 {quote_remote(remote_tmp)}; "
        f"{quote_remote(core_path)} -t -d /etc/openclash -f {quote_remote(remote_tmp)}; "
        f"mv -f {quote_remote(remote_tmp)} {quote_remote(remote_path)}; "
        f"chmod 600 {quote_remote(remote_path)}"
    )
    try:
        ssh_command(host, test_cmd)
    except subprocess.CalledProcessError as exc:
        ssh_command(host, f"rm -f {quote_remote(remote_tmp)}", capture=True)
        raise ConfigError("Remote Mihomo validation failed; the active configuration was not changed.") from exc

    if activate:
        activate_cmd = (
            "set -e; "
            "cp -p /etc/config/openclash "
            f"/etc/config/openclash.bak.{stamp}; "
            f"uci set openclash.config.config_path={quote_remote(remote_path)}; "
            "uci set openclash.config.enable='1'; "
            "uci commit openclash; "
            "/etc/init.d/openclash restart"
        )
        ssh_command(host, activate_cmd)

    return remote_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a Clash Verge effective YAML into a static OpenClash configuration."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser("export", help="Copy the current Clash Verge effective YAML to a work directory.")
    export_p.add_argument("--source", type=Path)
    export_p.add_argument("--workdir", type=Path, default=Path.home() / "Desktop/openclash-static-work")

    transform_p = sub.add_parser("transform", help="Transform an exported/effective YAML.")
    transform_p.add_argument("--input", type=Path, required=True)
    transform_p.add_argument("--output", type=Path, required=True)
    add_transform_args(transform_p)

    all_p = sub.add_parser("all", help="Export, transform, and optionally deploy in one command.")
    all_p.add_argument("--source", type=Path)
    all_p.add_argument("--workdir", type=Path, default=Path.home() / "Desktop/openclash-static-work")
    all_p.add_argument("--output-name", default="clash-verge-static-openclash.yaml")
    add_transform_args(all_p)
    add_deploy_args(all_p)

    deploy_p = sub.add_parser("deploy", help="Upload an existing YAML and validate it remotely before installation.")
    deploy_p.add_argument("--file", type=Path, required=True)
    add_deploy_args(deploy_p)

    return parser


def add_transform_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manual-group", default="手动选择")
    parser.add_argument("--auto-group", default="自动选择")
    parser.add_argument("--disney-group", default="迪士尼")
    parser.add_argument(
        "--media-keyword",
        action="append",
        dest="media_keywords",
        help="Node-name keyword added to the Disney group. Repeatable. Defaults: 流媒体, 媒体流.",
    )
    parser.add_argument("--test-url", default="https://www.gstatic.com/generate_204")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--tolerance", type=int, default=50)


def add_deploy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--deploy", action="store_true", help="For 'all': upload after transformation.")
    parser.add_argument("--host", default="root@192.168.10.1")
    parser.add_argument("--remote-name")
    parser.add_argument("--core-path", default="/etc/openclash/core/clash_meta")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="After remote validation, select this config through UCI and restart OpenClash. Opt-in only.",
    )


def transform_file(args: argparse.Namespace, input_path: Path, output_path: Path) -> dict[str, Any]:
    data = load_yaml(input_path)
    keywords = args.media_keywords or ["流媒体", "媒体流"]
    transformed = transform(
        data,
        manual_group=args.manual_group,
        auto_group=args.auto_group,
        disney_group=args.disney_group,
        media_keywords=keywords,
        test_url=args.test_url,
        interval=args.interval,
        tolerance=args.tolerance,
    )
    dump_yaml(transformed, output_path)
    return transformed


def print_summary(data: dict[str, Any], output: Path, args: argparse.Namespace) -> None:
    node_names = static_node_names(data)
    keywords = args.media_keywords or ["流媒体", "媒体流"]
    media_count = sum(
        1
        for name in node_names
        if any(keyword.casefold() in name.casefold() for keyword in keywords)
    )
    print(f"output={output}")
    print(f"static_nodes={len(node_names)}")
    print(f"media_nodes_added={media_count}")
    print(f"default_group={args.manual_group}")
    print(f"auto_group={args.auto_group}")
    print("secrets_printed=false")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "export":
            exported = export_source(args.source, args.workdir.expanduser())
            print(f"exported={exported}")
            return 0

        if args.command == "transform":
            input_path = args.input.expanduser().resolve()
            output_path = args.output.expanduser().resolve()
            data = transform_file(args, input_path, output_path)
            print_summary(data, output_path, args)
            return 0

        if args.command == "deploy":
            remote = deploy(
                args.file.expanduser().resolve(),
                host=args.host,
                remote_name=args.remote_name,
                core_path=args.core_path,
                activate=args.activate,
            )
            print(f"remote_config={remote}")
            print(f"activated={str(args.activate).lower()}")
            return 0

        if args.command == "all":
            workdir = args.workdir.expanduser().resolve()
            exported = export_source(args.source, workdir)
            output = workdir / args.output_name
            data = transform_file(args, exported, output)
            print(f"source_copy={exported}")
            print_summary(data, output, args)
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
