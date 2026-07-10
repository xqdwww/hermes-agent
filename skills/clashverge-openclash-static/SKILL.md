|---
name: clashverge-openclash-static
description: |-
  Export Clash Verge's effective Mihomo configuration, convert it into a static OpenClash configuration with manual/automatic selection groups, Disney-group media routing, and optional validated deployment. Supports local dry-run, scp upload without activation, and explicit opt-in activation over SSH.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [clash, openclash, clash-verge, proxy, network, openwrt, mihomo, static-config]
    category: networking
    related_skills: [hermes-a-share-ta-chain]
prerequisites:
  commands: []
---

# Clash Verge → OpenClash Static Configuration

Use this skill when the user asks to export a working Clash Verge configuration, preserve its static nodes and specialist routing groups, add global manual/automatic fallback groups, and install it into OpenClash.

## Core implementation

Always use:

```bash
python3 scripts/clashverge_to_openclash.py
```

The Python script is the source of truth. Do not hand-edit YAML unless the script reports a structural condition it cannot safely resolve.

Dependency:

```bash
python3 -m pip install PyYAML
```

## Default policy

The transformation must be minimal:

- Preserve all existing proxy definitions, specialist groups, DNS settings, and domain rules.
- Require a non-empty static `proxies:` list. A provider-only source is not accepted as an effective export.
- Add or replace `手动选择` as a `select` group containing `自动选择` first, followed by every static node.
- Add or replace `自动选择` as a `url-test` group containing every static node, using a 300-second interval and 50 ms tolerance by default.
- Preserve `GPT专用`, `Gemini专用`, and `迪士尼` when present.
- Add every node whose name contains `流媒体` or `媒体流` to `迪士尼`.
- Remove any pre-existing `MATCH,...` rule and append exactly `MATCH,手动选择` as the final fallback.
- Validate all group references before writing output.
- Never print node credentials, UUIDs, passwords, server addresses, or the YAML body in reports.

## Standard workflow

### 1. Export and transform locally

On macOS:

```bash
python3 scripts/clashverge_to_openclash.py all
```

Default source discovery includes Clash Verge Rev's usual effective-config path. Default work directory:

```text
~/Desktop/openclash-static-work
```

Default output:

```text
~/Desktop/openclash-static-work/clash-verge-static-openclash.yaml
```

For an explicit source:

```bash
python3 scripts/clashverge_to_openclash.py all \
  --source "/path/to/clash-verge.yaml"
```

### 2. Review the non-secret summary

Report only:

- exported copy path;
- output path;
- static node count;
- count of media-labelled nodes added to `迪士尼`;
- names of the default manual and automatic groups;
- whether deployment and activation occurred.

### 3. Deploy safely

Upload and remotely validate, but do not activate:

```bash
python3 scripts/clashverge_to_openclash.py deploy \
  --file ~/Desktop/openclash-static-work/clash-verge-static-openclash.yaml \
  --host root@192.168.10.1
```

The deployment contract is:

1. Keep any existing remote file as a timestamped backup.
2. Upload with legacy SCP mode (`scp -O`) for OpenWrt/Dropbear compatibility.
3. Validate the uploaded temporary file with:

```bash
/etc/openclash/core/clash_meta -t -d /etc/openclash -f <temporary-file>
```

4. Move it into `/etc/openclash/config/` only after validation passes.
5. Do not change the active OpenClash configuration unless the user explicitly requests activation.

Explicit activation:

```bash
python3 scripts/clashverge_to_openclash.py deploy \
  --file ~/Desktop/openclash-static-work/clash-verge-static-openclash.yaml \
  --host root@192.168.10.1 \
  --activate
```

Activation backs up `/etc/config/openclash`, sets `openclash.config.config_path`, enables OpenClash, commits UCI, and restarts the service.

## Safety boundaries

- Never delete the Clash Verge source.
- Never overwrite a remote configuration without preserving a timestamped backup.
- Never activate a configuration that failed Mihomo validation.
- Never assume `amd64-v2` or `amd64-v3`; use the already working OpenClash core and existing `core_version` setting.
- Never reboot the router as part of this workflow.
- Treat all YAML files as secrets.
- If the effective export has no `proxies:`, stop and ask for the merged/effective configuration rather than attempting to fetch subscriptions.

## Customization examples

Different group names:

```bash
python3 scripts/clashverge_to_openclash.py transform \
  --input input.yaml \
  --output output.yaml \
  --manual-group 手动选择 \
  --auto-group 自动选择 \
  --disney-group 迪士尼
```

Additional media keyword:

```bash
python3 scripts/clashverge_to_openclash.py transform \
  --input input.yaml \
  --output output.yaml \
  --media-keyword 流媒体 \
  --media-keyword 媒体流 \
  --media-keyword streaming
```
