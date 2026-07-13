# Hermes Clash Verge → OpenClash Static Skill — Regional Failover

Export Clash Verge's effective Mihomo config, convert it into a static OpenClash configuration with per-node priority fallback wrappers for global, GPT, Gemini, and Disney+ traffic — with automatic failover to regional automatic groups.

## Contents

| File | Purpose |
|---|---|
| `SKILL.md` | Hermes orchestration and safety contract |
| `scripts/clashverge_to_openclash.py` | Deterministic Python implementation |
| `tests/test_clashverge_to_openclash.py` | 33 synthetic contract tests |
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

- **Per-node priority wrappers**: each selectable node gets a `fallback` wrapper (e.g. `全局优先│🇯🇵日本测试01`). The primary node is used while healthy; on failure, traffic flows to the corresponding auto group automatically.
- **Regional ordering**: Japan → Taiwan → other regions for global, GPT, and Disney groups. Japan → Taiwan → Hong Kong → Germany for Gemini.
- **Gemini US exclusion**: node names containing 美国 or 🇺🇸 are explicitly excluded from Gemini groups.
- **Disney media detection**: nodes matching "流媒体" or "媒体流" are automatically added to Disney candidates.
- **Idempotent**: running twice on the same input produces identical output — old wrapper groups are detected and rebuilt cleanly.
- **Safe dry-run**: the `dry-run` subcommand never writes files, never calls SSH/SCP, and never contacts the router.
- **No credentials leaked**: the script never prints server addresses, passwords, UUIDs, or tokens.

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

33 tests covering group structure, region ordering, Gemini filtering, wrapper behaviour, idempotency, cycle detection, secret safety, and dry-run safety.
