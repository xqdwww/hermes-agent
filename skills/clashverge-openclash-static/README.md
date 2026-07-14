# Hermes Clash Verge → OpenClash Static Skill — Regional Failover

Export Clash Verge's effective Mihomo config, convert it into a static OpenClash
configuration with per-node priority fallback wrappers for global, GPT, Gemini,
and Disney+ traffic.  Also supports calibration overrides for Gemini.

**Key design**: every select-able node gets a `fallback` wrapper that first tries
the preferred node, then falls through to the corresponding automatic group when
health checks fail.  The user's selection survives node failure; no manual
panel intervention needed to switch.

## Contents

| File | Purpose |
|---|---|
| `SKILL.md` | Hermes orchestration and safety contract |
| `scripts/clashverge_to_openclash.py` | Deterministic Python implementation |
| `tests/test_clashverge_to_openclash.py` | 81 synthetic contract tests |
| `requirements.txt` | Python dependency (PyYAML) |

## Quick start

```bash
python3 -m pip install -r requirements.txt

# Safe preview — no file writes, no SSH, no router contact
python3 scripts/clashverge_to_openclash.py dry-run --input /path/to/config.yaml

# Full pipeline: export + transform
python3 scripts/clashverge_to_openclash.py all
```

## Key features

- **Per-node priority wrappers**: every select-able node gets a `fallback`
  wrapper (`全局优先│<节点名>`, `GPT优先│<节点名>`, etc.) whose second
  member is the corresponding automatic group.  Preferred node recovers
  automatically when health checks pass again.
- **Regional fallback priority**: Japan → Taiwan → other for global/GPT/Disney;
  Japan → Taiwan → Hong Kong → Germany for Gemini.
- **Gemini US exclusion**: nodes containing `美国` or `🇺🇸` are excluded from
  Gemini groups (legacy, no-probe mode).  When probes are used, all nodes are
  considered and only PASS nodes enter the group.
- **Gemini manual calibration overrides**: exact node-name overrides (`PASS` /
  `FAIL`) take precedence over probe results — for nodes where probe
  classification is unreliable.  Mismatches print `PROBE_OVERRIDE_MISMATCH`.
- **Disney media detection**: nodes matching `流媒体` or `媒体流` are
  automatically added to Disney candidates.
- **Idempotent**: running twice on the same input produces identical output.
  Old wrappers are detected and removed.
- **Safe dry-run**: the `dry-run` subcommand never writes files, never calls
  SSH/SCP, and never contacts the router.
- **One-shot sync**: end-to-end pipeline with SHA-based no-change detection,
  optional probe, remote validation, backup, restart, health checks, and
  rollback.

## Group structure

### Global (always generated)

| Group | Type | Proxies |
|---|---|---|
| 默认代理 | select | 手动选择, 自动选择 |
| 手动选择 | select | 自动选择, then 全局优先│<all nodes> wrappers |
| 自动选择 | fallback | All static nodes (Japan → Taiwan → other) |

### GPT (only if GPT专用 exists in source)

| Group | Type | Proxies |
|---|---|---|
| GPT专用 | select | GPT手动, GPT自动 |
| GPT手动 | select | GPT自动, then GPT优先│<GPT nodes> wrappers |
| GPT自动 | fallback | GPT candidates (Japan → Taiwan → other) |

### Gemini (only if Gemini专用 exists)

| Group | Type | Proxies |
|---|---|---|
| Gemini专用 | select | Gemini手动, Gemini自动 |
| Gemini手动 | select | Gemini自动, then Gemini优先│<Gemini nodes> wrappers |
| Gemini自动 | fallback | Japan → Taiwan → Hong Kong → Germany nodes only |

When probe mode is active, the region filter is bypassed — the probe results
determine which nodes enter Gemini.  Manual calibration overrides can further
force specific nodes in or out.

### Disney (always generated when candidates exist)

| Group | Type | Proxies |
|---|---|---|
| 迪士尼 | select | 迪士尼手动, 迪士尼自动 |
| 迪士尼手动 | select | 迪士尼自动, then 迪士尼优先│<Disney nodes> wrappers |
| 迪士尼自动 | fallback | Disney candidates (Japan → Taiwan → other) |

### Priority wrapper example

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

**Always select a `优先│` wrapper, not a bare node.**  This ensures automatic
failover to the automatic group when your preferred node goes down, and
automatic recovery when it comes back.

## Manual selection guidance

- **Global**: open `手动选择` → pick a `全局优先│<节点名>` item.
- **GPT**: open `GPT手动` → pick a `GPT优先│<节点名>` item.
- **Gemini**: open `Gemini手动` → pick a `Gemini优先│<节点名>` item.
- **Disney**: open `迪士尼手动` → pick a `迪士尼优先│<节点名>` item.
- **Full auto**: select `自动选择`, `GPT自动`, `Gemini自动`, or `迪士尼自动`
  directly — the fallback group handles failover.

## Transform a specific file

```bash
python3 scripts/clashverge_to_openclash.py transform \
  --input /path/to/clash-verge-effective.yaml \
  --output /path/to/clash-verge-static-openclash.yaml
```

## Deploy after inspection

```bash
python3 scripts/clashverge_to_openclash.py deploy \
  --file /path/to/clash-verge-static-openclash.yaml \
  --host root@192.168.10.1
```

## Testing

```bash
python3 -m pytest tests/ -v
```

81 tests covering: group structure, region ordering, Gemini filtering, priority
wrapper generation, calibration overrides, idempotency, cycle detection, secret
safety, dry-run safety, and the end-to-end sync pipeline.

## Limitations

- The `generate_204` health check only detects basic network connectivity.
  A node may pass health checks but still be blocked for specific platforms.
- Gemini region filtering in legacy mode is based on node names, not IP
  geolocation.
- This skill is a static configuration generator, not a dynamic proxy manager.
