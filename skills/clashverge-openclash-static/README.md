# Hermes Clash Verge → OpenClash Static Skill — Regional Fallback

Export Clash Verge's effective Mihomo config, convert it into a static OpenClash configuration with simple regional fallback groups for global, GPT, Gemini, and Disney+ traffic.

**Designed for readability.** Each conversion generates exactly 12 fixed policy groups — no per-node priority wrappers. Manual-select groups list direct static nodes. Automatic groups handle failover.

## Contents

| File | Purpose |
|---|---|
| `SKILL.md` | Hermes orchestration and safety contract |
| `scripts/clashverge_to_openclash.py` | Deterministic Python implementation |
| `tests/test_clashverge_to_openclash.py` | 53 synthetic contract tests |
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

- **Simple, fixed groups**: 12 policy groups only (全局/自动/手动, GPT, Gemini, Disney) — no per-node wrappers.
- **Regional fallback in auto mode**: Japan → Taiwan → other for global/GPT/Disney; Japan → Taiwan → Hong Kong → Germany for Gemini.
- **Gemini US exclusion**: node names containing 美国 or 🇺🇸 are explicitly excluded from Gemini groups.
- **Disney media detection**: nodes matching "流媒体" or "媒体流" are automatically added to Disney candidates.
- **Idempotent**: running twice on the same input produces identical output — old wrapper groups are detected and removed.
- **Safe dry-run**: the `dry-run` subcommand never writes files, never calls SSH/SCP, and never contacts the router.
- **No credentials leaked**: the script never prints server addresses, passwords, UUIDs, or tokens.
- **One-shot sync**: end-to-end pipeline with SHA-based no-change detection, remote validation, backup, restart, health checks, and rollback.

## Behaviour

**Automatic mode (recommended):**
- Select an auto group (e.g. "自动选择", "GPT自动").
- Nodes fail over automatically within the group.
- Region priority order is respected.

**Manual mode:**
- Select a manual group (e.g. "手动选择", "GPT手动").
- First item is the corresponding auto group (restores automatic failover).
- Remaining items are direct static nodes.
- A manually selected node does NOT switch on failure — return to the first item to restore auto mode.
- This is a deliberate simplification for panel readability.

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

53 tests covering group structure, region ordering, Gemini filtering, wrapper cleanup, idempotency, cycle detection, secret safety, dry-run safety, and the end-to-end sync pipeline.
