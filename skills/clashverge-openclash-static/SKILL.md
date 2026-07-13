|---
name: clashverge-openclash-static
description: |-
  Export Clash Verge's effective Mihomo configuration, convert it into a static OpenClash configuration with regional failover — global, GPT, Gemini, and Disney groups each get select/manual wrappers with per-node priority fallback. Supports local dry-run, scp upload without activation, and explicit opt-in activation over SSH.
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [clash, openclash, clash-verge, proxy, network, openwrt, mihomo, static-config, failover, region]
    category: networking
    related_skills: [hermes-a-share-ta-chain]
prerequisites:
  commands: []
---

# Clash Verge → OpenClash Static Configuration with Regional Failover

Use this skill when the user asks to export a working Clash Verge configuration, preserve its static nodes and specialist routing groups, and add per-node priority fallback wrappers that automatically switch to a regional fallback group when the preferred node fails health checks.

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

## Generated group structure

Each conversion creates the following fixed groups in order:

### Global groups (always generated)

| Group | Type | Content |
|---|---|---|
| 默认代理 | select | 手动选择, 自动选择 |
| 手动选择 | select | 自动选择, then 全局优先│<全部静态节点> wrappers |
| 自动选择 | fallback | All static nodes, sorted: Japan → Taiwan → other regions. Health check every 60 s. |

### GPT groups (only if GPT专用 exists in source)

| Group | Type | Content |
|---|---|---|
| GPT专用 | select | GPT手动, GPT自动 |
| GPT手动 | select | GPT自动, then GPT优先│<GPT candidate nodes> wrappers |
| GPT自动 | fallback | GPT candidate nodes, sorted: Japan → Taiwan → other. |

GPT candidate nodes are taken from the original GPT专用 group (intersected with static proxies).

### Gemini groups (only if Gemini专用 exists in source)

| Group | Type | Content |
|---|---|---|
| Gemini专用 | select | Gemini手动, Gemini自动 |
| Gemini手动 | select | Gemini自动, then Gemini优先│<Gemini candidate nodes> wrappers |
| Gemini自动 | fallback | Only Japan, Taiwan, Hong Kong, Germany nodes. Excludes US nodes. Sorted: Japan → Taiwan → Hong Kong → Germany. |

Gemini candidate nodes are region-filtered: only node names containing 日本/🇯🇵, 台湾/🇹🇼, 香港/🇭🇰, or 德国/🇩🇪. US nodes (美国/🇺🇸) are explicitly excluded.

### Disney groups (always generated when candidate nodes exist)

| Group | Type | Content |
|---|---|---|
| 迪士尼 | select | 迪士尼手动, 迪士尼自动 |
| 迪士尼手动 | select | 迪士尼自动, then 迪士尼优先│<Disney candidate nodes> wrappers |
| 迪士尼自动 | fallback | Disney candidates, sorted: Japan → Taiwan → other. |

Disney candidates = original 迪士尼 group static nodes + nodes matching "流媒体" or "媒体流".

### Priority wrapper behaviour

Each selectable node gets a dedicated fallback wrapper, for example:

```yaml
- name: 全局优先│🇯🇵日本测试01
  type: fallback
  proxies:
    - 🇯🇵日本测试01
    - 自动选择
  url: https://www.gstatic.com/generate_204
  interval: 60
  lazy: true
  timeout: 5000
  max-failed-times: 1
```

- When the user selects a "优先│node" wrapper in the manual group:
  1. The primary node is used while it passes health checks.
  2. If health checks fail, traffic falls through to the corresponding automatic group.
  3. The preferred node automatically recovers when it passes health checks again.

- **Do not select bare static nodes manually** — always select the corresponding "优先│node" wrapper so automatic failover works.

- Selecting an automatic group directly (e.g., "自动选择", "GPT自动") also works: all nodes in that group are tried in region-priority order, with full failover coverage.

### Final MATCH rule

Exactly one MATCH rule exists:

```yaml
MATCH,默认代理
```

All previous MATCH rules are removed during conversion.

## Manual selection guidance

When a user manually selects a proxy in the OpenClash panel:

- **Global routing**: select from "手动选择" → pick a "全局优先│<节点名>" item.
- **GPT-specific**: select from "GPT手动" → pick a "GPT优先│<节点名>" item.
- **Gemini-specific**: select from "Gemini手动" → pick a "Gemini优先│<节点名>" item.
- **Disney-specific**: select from "迪士尼手动" → pick a "迪士尼优先│<节点名>" item.

Never select a bare node directly; always use the priority wrapper so failover is active.

## Safety boundaries

- Does NOT connect to the router unless `deploy` or `all --deploy` subcommands are used.
- The `dry-run` subcommand never writes files, never runs SSH/SCP, and never modifies the router.
- Never prints proxy credentials (server, password, UUID, token) or the full YAML body.
- Treat all YAML files as secrets.
- If the effective export has no `proxies:`, stop and ask for the merged/effective configuration.
- Never delete the Clash Verge source.
- Never overwrite a remote configuration without preserving a timestamped backup.
- Never activate a configuration that failed Mihomo validation.

## Limitations

- The automatic health check (`generate_204`) only detects basic connectivity, not whether GPT, Gemini, or Disney+ is accessible through a node.
- A node may pass health checks but still fail specific platform access due to IP-based geo-blocking.
- Gemini region filtering is based on node names, not actual IP geolocation.
- This skill is a static configuration generator, not a dynamic proxy management framework.

## Natural-language trigger examples

- "更新 OpenClash 静态配置"
- "生成日本优先、台湾第二的自动容灾配置"
- "Gemini 排除美国节点，只用日本、台湾、香港、德国"
- "给手选节点增加失效自动切换"
- "生成并上传但不要启用"

## Standard workflow

### 1. Dry-run first (safe, no file write, no SSH)

```bash
python3 scripts/clashverge_to_openclash.py dry-run --input config.yaml
```

### 2. Export and transform locally

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

### 3. Review the non-secret summary

Report only:

- output path;
- static node count;
- group count;
- count of media-labelled nodes added to Disney;
- group names;
- whether deployment and activation occurred.

### 4. Deploy safely

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
  --media-keyword 媒体流
```

## Idempotency

Running the transformation twice on the same input produces identical output. The script:

1. Detects and removes all groups it previously generated before rebuilding.
2. Extracts GPT/Gemini/Disney candidates from the original (user-provided) groups or from the script's own automatic groups on re-processing.
3. Never nests priority wrappers inside each other.
4. Never duplicates group names or node references.
