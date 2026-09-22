# Hermes Clash Verge → OpenClash Static Skill — Regional Fallback

Current recovery policy (2.7.3): GPT/Gemini dedicated selectors include the
explicit manual **AI应急（未验证）** group with all current nodes. It never adds
unverified nodes to curated pools or becomes an automatic fallback. Desktop
Clash Verge must remain untouched when it is the user's working recovery path.
The historical fixed-group descriptions below are superseded by this optional
recovery group plus the accepted history groups.


Export Clash Verge's effective Mihomo config, convert it into a static OpenClash
configuration with exactly **12 fixed policy groups** — no per-node priority
wrappers.  Supports probe-based service filtering, manual calibration overrides
for Gemini, and one-shot sync with SHA-based no-change detection.

**Key design**: manual-select groups list direct static nodes.  Automatic groups
use standard `fallback` for health-check-based failover.  The panel stays
readable with a fixed, small number of groups.

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

- **Fixed 12-group structure**: exactly 12 skill-managed groups — no per-node
  wrappers.  Manual groups list direct static nodes; automatic groups use
  standard `fallback` with health checks.
- **Regional fallback priority**: Japan → Taiwan → other for global/GPT/Disney;
  Japan → Taiwan → Hong Kong → Germany for Gemini.
- **Gemini manual calibration overrides**: exact node-name overrides (`PASS` /
  `FAIL`) take precedence over probe results — for nodes where probe
  classification is unreliable.  Mismatches print `PROBE_OVERRIDE_MISMATCH`.
- **Probe-based service filtering**: run an isolated Mihomo instance to test
  each node for GPT, Gemini, and Disney+ reachability.  Only PASS nodes enter
  the corresponding groups.
- **Gemini US handling**: when probes are available, US nodes can enter Gemini
  if they pass the probe and are not overridden.  In legacy (no-probe) mode,
  US nodes are excluded via region-name filtering.
- **Antigravity routing**: the production, daily, and daily-sandbox CloudCode
  hostnames use exact `Gemini专用` rules.  No broad `googleapis.com` suffix is
  captured.
- **Disney media detection**: nodes matching `流媒体` or `媒体流` are
  automatically added to Disney candidates.
- **Idempotent**: running twice on the same input produces identical output.
  Old skill-generated groups (including legacy wrappers) are detected and removed.
- **Safe dry-run**: the `dry-run` subcommand never writes files, never calls
  SSH/SCP, and never contacts the router.
- **One-shot sync**: end-to-end pipeline with SHA-based no-change detection,
  optional probe, remote validation, backup, restart, health checks, and
  rollback.

## Group structure

**The skill manages exactly 12 groups** (when all specialist candidate sets
exist).  No per-node wrapper groups are generated.

### Global (always generated)

| Group | Type | Content |
|---|---|---|
| 默认代理 | select | 手动选择, 自动选择 |
| 手动选择 | select | 自动选择, then all static nodes (Japan → Taiwan → other) |
| 自动选择 | fallback | All static nodes, sorted: Japan → Taiwan → other. Health check every 60 s. |

### GPT (only if GPT专用 exists in source)

| Group | Type | Content |
|---|---|---|
| GPT专用 | select | GPT手动, GPT自动 |
| GPT手动 | select | GPT自动, then GPT candidate nodes (Japan → Taiwan → other) |
| GPT自动 | fallback | GPT candidate nodes, sorted: Japan → Taiwan → other. |

GPT candidates come from the original GPT专用 group (intersected with static
proxies).  When probes are used, only PASS nodes are included.

### Gemini (only if Gemini专用 exists in source)

| Group | Type | Content |
|---|---|---|
| Gemini专用 | select | Gemini手动, Gemini自动 |
| Gemini手动 | select | Functionally filtered concrete nodes first, then Gemini自动 as an explicit transport-only fallback |
| Gemini自动 | fallback | Only Japan, Taiwan, Hong Kong, Germany nodes. Sorted: Japan → Taiwan → Hong Kong → Germany. |

When probes are active, all nodes are considered — only PASS nodes enter the
group.  Manual calibration overrides can force specific nodes in or out.

### Disney (always generated when candidates exist)

| Group | Type | Content |
|---|---|---|
| 迪士尼 | select | 迪士尼手动, 迪士尼自动 |
| 迪士尼手动 | select | 迪士尼自动, then Disney candidate nodes (Japan → Taiwan → other) |
| 迪士尼自动 | fallback | Disney candidates, sorted: Japan → Taiwan → other. |

Disney candidates = original 迪士尼 group static nodes + nodes matching
`流媒体` or `媒体流`, then filtered by probe results (when available).

### Behaviour

**Automatic mode:**
- Select an automatic group (e.g. `自动选择`, `GPT自动`, `Gemini自动`,
  `迪士尼自动`).
- Nodes within the automatic group are checked in order via standard `fallback`.
  If a node fails health checks, the next node in the list is used automatically.
- The order respects region priority: Japan first, then Taiwan, then other
  regions (or Japan → Taiwan → Hong Kong → Germany for Gemini).
- Gemini automatic mode is transport-only and is not the default manual-group
  selection. A real authenticated pass/fail result is required to establish
  location eligibility.

**Manual mode:**
- Select a manual group (e.g. `手动选择`, `GPT手动`, `Gemini手动`,
  `迪士尼手动`).
- Each manual group lists its auto group first, followed by direct static nodes.
- Choose a specific static node to fix traffic to that node.
- When using manual mode, **the selected node is used as-is** — it will NOT
  automatically switch on failure.
- Return to the first item (the auto group) to restore automatic failover.
- **This is a deliberate simplification**: the panel stays readable with a
  fixed number of groups, at the cost of no per-node automatic fallback in
  manual mode.

## Manual selection guidance

- **Global**: open `手动选择` → pick a specific node or `自动选择` for failover.
- **GPT**: open `GPT手动` → pick a specific node or `GPT自动` for failover.
- **Gemini**: open `Gemini手动` → pick a specific node or `Gemini自动` for failover.
- **Disney**: open `迪士尼手动` → pick a specific node or `迪士尼自动` for failover.
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

81 tests covering: group structure, region ordering, zero-wrapper verification,
Gemini filtering, calibration overrides, idempotency, cycle detection, secret
safety, dry-run safety, and the end-to-end sync pipeline.

## Limitations

- The Gemini fallback probes the Antigravity daily CloudCode host, but a
  `generate_204` health check still proves transport only.  It cannot prove
  account/location eligibility; authenticated functional evidence and the LKG
  candidate set remain authoritative for that distinction.
- Gemini region filtering in legacy (no-probe) mode is based on node names,
  not IP geolocation.
- Manual mode does NOT provide per-node automatic failover — this is a
  deliberate design trade-off for panel readability.
- This skill is a static configuration generator, not a dynamic proxy manager.


## Saved verified service pools (2.6.7)

The default inter-node RegionRestrictionCheck cooldown is now zero for clean,
complete attributed probes, saving 3 seconds per clean fresh node. Unknown,
incomplete, or transport-uncertain outcomes retain the original 3-second safety
floor, and explicit `--rrc-node-interval` overrides remain available. Each node
still resets connections and completes its selector, stabilization, preflight,
attribution, and retry checks, so total runtime will not necessarily improve in
direct proportion to the removed wait.

The default `~/.hermes/state/clashverge-openclash-static/verified-service-registry.json`
is consumed automatically by transform and reconciliation. It stores only HMAC
connection identities, service scope, original test time, enabled state, and
preferred/manual tiers. `OPENCLASH_VERIFIED_REGISTRY_PATH` overrides its path.
Missing registry retains legacy behavior; malformed data or missing identity key
fails closed. Same-name changed connections cannot inherit evidence; renamed
unchanged connections can. Saved positive evidence has no automatic age expiry.
Newer explicit actual-use failures, transport failures and recapture safeguards
remain authoritative. The report distinguishes reused proof from a fresh test.

For the current 2026-09-08 registry, GPT has 15 ChatGPT anonymous-generation
preferred nodes; Gemini has 12 Antigravity/CloudCode-generation preferred nodes
and 19 manually selectable successful but less consistent candidates. These
counts are baseline evidence, not promises of permanent availability. Do not
label CloudCode proof as Gemini Web or AI Studio proof, or guest ChatGPT proof
as proof of paid models, Codex or authenticated OpenAI API.

Exact registry matches may bypass the old `流媒体` name exclusion. Unverified
nodes retain that exclusion. Prefer registry order and a concrete first node
for GPT/Gemini manual selectors. Keep transport-only fallback available as an
explicit choice; an HTTP health response is not actual model eligibility.

Antigravity Manager connects to OpenClash through its native HTTP proxy pool;
its gateway entry is `OpenClash · Gemini 已验证节点池`. Airport VLESS/Hysteria2
credentials stay in OpenClash. The gateway follows the existing narrow
CloudCode rules, so updating this shared routing pool updates the reverse
proxy's usable choices without duplicating airport subscriptions in Manager.

## 2.7.0: name-based incremental updates

Ordinary updates replace same-name node parameters without service retesting,
remove deleted nodes, and test only added names. `--full-retest` is the explicit
full diagnostic option. With no additions, no RRC or Disney service probe runs.
Existing candidate validation, activation health checks and rollback remain.

GPT/Gemini manual selectors now show only their curated pool; unknown/failed
manual tails and AI historical fallback groups are removed. Hong Kong-labelled
entries are conservatively excluded (labels are not measured exit countries).
Screening success never promotes a new AI node as actual-use verified. Carrying
a same-name existing selection is recorded as untested policy reuse, including
when its connection parameters change; saved actual-use evidence is not rewritten.
