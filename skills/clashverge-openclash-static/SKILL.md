---
name: clashverge-openclash-static
description: Safely refresh and deploy static OpenClash profiles.
version: 2.5.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [clash, openclash, clash-verge, proxy, network, openwrt, mihomo, static-config, sidecar, rollback]
    category: networking
    related_skills: [hermes-a-share-ta-chain]
prerequisites:
  commands: []
---

# Clash Verge → OpenClash Static Configuration

Use this Skill when the user asks to update OpenClash from the current Clash Verge effective configuration.

## Source of truth

Always use:

```bash
python3 scripts/clashverge_to_openclash.py
```

Do not rebuild the YAML by hand and do not use the old node-level wrapper design.

Dependency:

```bash
python3 -m pip install PyYAML
```

## Upgrade record

The front-matter `version` field is the authoritative release-version source
for this Skill. Version 2.5.0 adds resumable candidate preparation from one
verified frozen snapshot and one complete RegionRestrictionCheck artifact. It
rejects snapshot manifests mistakenly passed as `--source`, audits source
coverage by exact stable IDs, adapts RRC output without a hand-written wrapper,
migrates manual/LKG evidence only by connection identity, journals every
candidate stage, reports bounded redacted subprocess output, and reaps only
expired sidecar leases with exact process/config matching. Activation remains a
separate command and is deliberately absent from `prepare-candidate`. Version
2.4.13 scopes official region policy strictly to exits
whose recorded country is the attributed policy region, so an unknown country
does not erase otherwise valid service evidence. It permits manual evidence to
move to a new snapshot only after full connection-identity HMAC equality and
permanently blocks activation of candidates explicitly rejected for a known
selection regression. Version 2.4.12 inserts a versioned official-service-region
policy between attributed probe evidence and candidate selection. It excludes
attributed Hong Kong exits from ChatGPT even after a screen pass, treats Hong
Kong as Gemini-supported when current transport is healthy and no manual
failure or evidence conflict exists, never infers country from a node name,
and preserves the raw RRC result beside the policy decision. Version 2.4.11
makes candidate-sidecar cleanup identify the
actual Mihomo child by exact executable and temporary config path instead of
trusting only the BusyBox `start-stop-daemon` pidfile, and verifies that no
matching process or owned temporary path remains. Its candidate health probe
also walks the temporary `PROBE` selector until one static node reaches the
204 endpoint, so a dead default node cannot reject an otherwise valid
candidate. Version 2.4.10 keeps
exact-identity, exact-snapshot functional
evidence valid when a later baseline reachability probe runs; that unrelated
probe no longer erases current RRC results. Version 2.4.9 treats a cross-connection masked-exit drift as
node-local attribution unavailable, with no service evidence, because it does
not prove proxy-path mismatch for rotating exit pools. Explicit selector or
proxy-path mismatches remain fail-closed. Version 2.4.8 first queries the same IPv4 exit endpoint used by
RegionRestrictionCheck's network-provider line, while preserving the
independent bounded fallback set. Version 2.4.7 confirms an unavailable-rate or consecutive-node
systemic signal against the calibrated sentinel exits before stopping the
whole run; an explicit exit mismatch remains fail-closed. Version 2.4.6
retries the complete control-backend set once
with fresh connections after a bounded pause before declaring node-local
attribution unavailable. Version 2.4.5 makes the post-selector discard request
best-effort and adds Cloudflare trace plus AWS check-IP fallbacks so a warm-up
timeout or endpoint-specific TLS failure cannot become false node attribution.
Version 2.4.4 queries bounded public-IPv4 control
backends and separates node-local `ATTRIBUTION_UNAVAILABLE` from an explicit
`ATTRIBUTION_MISMATCH`; isolated unavailable nodes remain unknown, while
confirmed mismatch and systematic control outages stop the run. Version 2.4.3
binds the RegionRestrictionCheck control query
and tool process to one runner-scoped sidecar proxy context, requires matching
run-keyed exit HMACs, gates a full run on two-node calibration, and checkpoints
only completely attributed node evidence. Version 2.4.1 makes activation and
rollback health checks honor enabled
OpenClash mixed-proxy authentication without exposing credentials, uses a real
bounded deadline with consecutive stable passes, and waits for the final restored
network state instead of treating an intermediate mismatch as rollback failure.
Version 2.4.0 made the router-installed RegionRestrictionCheck the formal
GPT/Gemini/Disney screening backend. Hermes freezes the source, orchestrates the
external tool through the isolated candidate sidecar, fuses snapshot-bound manual
and full-chain evidence, builds the candidate, and keeps activation as a separate
transaction. The browser probe remains historical experimental code and is not a
candidate or activation gate. Do not add Playwright or operate the dedicated
logged-in profile from this Skill.

## Accepted policy

The generated profile contains these 12 primary managed groups:

1. 默认代理
2. 手动选择
3. 自动选择
4. GPT专用
5. GPT手动
6. GPT候选
7. Gemini专用
8. Gemini手动
9. Gemini候选
10. 迪士尼
11. 迪士尼手动
12. 迪士尼候选

Identity-bound LKG-only members, when present, are exposed separately as
`GPT历史LKG`, `Gemini历史LKG`, or `迪士尼历史LKG`; they never enter a primary
candidate group merely because they passed historically.

Rules:

- Never generate `全局优先│...`, `GPT优先│...`, `Gemini优先│...`, `迪士尼优先│...`, or their full-width-bar variants.
- Manual groups list direct nodes. Their first item is the corresponding candidate group.
- Candidate groups are ordinary `fallback` groups; their size is never described as an automated probe-pass count.
- All fallback groups use `https://www.gstatic.com/generate_204`, interval 60, lazy true, timeout 5000, and max-failed-times 1.
- Global/GPT/Disney ordering is Japan → Taiwan → other nodes.
- Gemini ordering is Japan → Taiwan → Hong Kong → Germany → other nodes.
- Remove the placeholder node named `使用前先更新订阅`.
- The historical GPT/Gemini/Disney candidate sets seed last-known-good state on the first run. Do not restore the old binary GPT probe.
- Run the installed RegionRestrictionCheck through one temporary loopback Mihomo sidecar, serial selector switching, exact controller read-back, per-node connection reset, and explicit `-P` proxy binding. Never copy or update the external script.
- Use `MANUAL_FUNCTIONAL_PASS`, `MANUAL_FUNCTIONAL_FAIL`, `SCREEN_PASS`, `SCREEN_NEGATIVE`, `PASS_WITH_SCREEN_FALSE_NEGATIVE`, `LKG_FALLBACK`, and `UNKNOWN` as evidence semantics. Display conflicts and LKG-only membership separately.
- GPT candidates accept current `SCREEN_PASS` or current identity-bound manual functional PASS, but not an explicit current transport failure. Gemini candidates accept current `SCREEN_PASS`, current identity-bound manual functional PASS, or `PASS_WITH_SCREEN_FALSE_NEGATIVE`; exclude manual FAIL and conflicts. Disney candidates prefer current full-chain `PASS_SUPPORTED_REGION`; a full-chain hard failure outranks RegionRestrictionCheck.
- Never treat Google reachability, Gemini HTTP 200, a login redirect, an API response, old LKG, or an old override as definitive Gemini Web generation proof.
- Never treat a Disney homepage, TLS, CDN, or HTTP 200 response as Disney support proof.
- New UNKNOWN nodes may appear only at the tail of the corresponding manual group; they never enter the candidate group.
- If a primary service group is empty, stop candidate generation with `BLOCKED_NO_CURRENT_SERVICE_CANDIDATES`; never silently substitute LKG or default routing.
- Preserve ordinary source rules, rename the old target `顺畅网络` to `默认代理`, regenerate narrow GPT/Gemini/Disney rules, and finish with exactly `MATCH,默认代理`.
- Remove Clash Verge-only controller/listener/profile fields, temporary probe/controller fields, and `/tmp/verge` paths if present. Preserve a general top-level `tun` section because it may carry user network semantics.
- Validate group references, rule targets, cycles, duplicate names, and the final MATCH before writing or deploying.

## User phrases

### “更新 OpenClash 节点”

Export, transform, deploy, validate remotely, activate, and restart OpenClash:

```bash
python3 scripts/clashverge_to_openclash.py all \
  --refresh-adapter scripts/clash_verge_source_refresh_adapter.py \
  --deploy \
  --activate
```

Before generation, a deploying `all` run probes static nodes through a temporary
router-side Mihomo process. The process binds loopback only, runs as GID 65534,
and relies on OpenClash's existing `meta skgid 65534 return` rule to avoid nesting
inside production OpenClash. Only the explicit activation phase may change the
production service or data plane.

### “更新 OpenClash 节点，但不要启用”

Export, transform, upload, and remotely validate, but do not switch the active profile or restart:

```bash
python3 scripts/clashverge_to_openclash.py all \
  --refresh-adapter scripts/clash_verge_source_refresh_adapter.py \
  --deploy
```

This probes through the isolated router sidecar, uploads an immutable candidate,
and leaves UCI, the selected production YAML, service state, firewall, policy
routes, DNS, and TUN untouched. `--no-activate` is an equivalent explicit spelling.

For an already frozen snapshot and completed RRC run, use the resumable path.
It never refreshes, reruns RRC, or activates; rerunning the same command verifies
the journal binding and resumes safely after local generation, upload, or
candidate-sidecar interruption:

```bash
python3 scripts/clashverge_to_openclash.py prepare-candidate \
  --source-snapshot /private/path/snapshot_current.json \
  --rrc-results /private/path/regioncheck-full-current.json \
  --state-path ~/.hermes/state/clashverge-openclash-static/service-probe-lkg.json \
  --workdir /private/path/candidate-current \
  --upload
```

To audit and migrate old manual evidence during the same preparation, also pass
`--previous-source-snapshot` and `--previous-manual-results`. A stable-ID match
may survive a display-name change; changed or unprovable connection identity is
reported as `MANUAL_EVIDENCE_RETEST_REQUIRED` and is not inherited. The workdir
contains the private run journal, exact identity-coverage audit, migration audit,
reconciled report/state, candidate, and redacted audit YAML.

`--source` is exclusively the live Clash Verge effective YAML with its sibling
`profiles.yaml`. A frozen JSON manifest must always use `--source-snapshot`;
argument-type errors are reported as `STOP_SOURCE_ARGUMENT_ERROR`, not source
identity drift.

### “测试 OpenClash 节点”

Probe and refresh the diagnostic report without generating or deploying and without changing LKG:

```bash
python3 scripts/clashverge_to_openclash.py probe \
  --refresh-adapter scripts/clash_verge_source_refresh_adapter.py
```

Only an explicit request may update LKG in probe-only mode:

```bash
python3 scripts/clashverge_to_openclash.py probe \
  --refresh-adapter scripts/clash_verge_source_refresh_adapter.py \
  --update-lkg
```

Apply newer definitive human-use results to an existing report without a
network probe, router contact, or activation:

```bash
python3 scripts/clashverge_to_openclash.py reconcile-probe \
  --source-snapshot /path/to/source-snapshot.json \
  --probe-report /path/to/existing-report.json \
  --state-path /path/to/existing-lkg.json \
  --manual-results /path/to/manual-results.json \
  --report-output /tmp/reconciled-report.json \
  --state-output /tmp/reconciled-lkg.json \
  --output /tmp/openclash-reconciled.yaml \
  --audit-output /tmp/openclash-reconciled-audit.yaml
```

Each manual record contains `service`, exact `node`, `exact_node_id`,
`source_snapshot_id`, `result`, `tested_at`, and `method`. Accept only definitive
logged-in generation/playback methods. Never store cookies, tokens, prompts,
answers, or response bodies. Ignore stale results and any name, node identity,
service, method, or snapshot mismatch.

Run the external RegionRestrictionCheck screening backend through the fixed
router sidecar. Require installed version 1.0.1, record its script SHA-256 and
command path, and stop if explicit proxy support is unavailable:

```bash
python3 scripts/regioncheck_service_probe.py \
  --skill-script scripts/clashverge_to_openclash.py \
  --source-snapshot /path/to/source-snapshot.json \
  --node 'one-region-a-node' \
  --node 'one-region-b-node' \
  --calibration-only \
  --output /private/path/regioncheck-calibration.json

python3 scripts/regioncheck_service_probe.py \
  --skill-script scripts/clashverge_to_openclash.py \
  --source-snapshot /path/to/source-snapshot.json \
  --calibration-report /private/path/regioncheck-calibration.json \
  --output /private/path/regioncheck-functional-results.json
```

Resolve one proxy URL in the RegionRestrictionCheck runner's network namespace,
then pass it explicitly to the control query and
`regioncheck -M 4 -R 0 -E en -P <resolved-proxy-url>` non-interactively. Never
let either probe function derive a sidecar port. Strip ANSI output, BusyBox
fractional-sleep warnings, and promotional sections. Persist only structured
service results, tool metadata, country, and run-keyed control/post-tool
exit-IP HMACs. Require those HMACs to match and the tool's masked exit to match
before attributing results. Use `--resume` only with a v2 report whose snapshot,
stable node ID, selector read-back, tool hash, complete output, and both HMACs
all match. `Google Gemini: No` is
`SCREEN_NEGATIVE`, not a definitive failure. A current snapshot-bound manual Web
generation PASS may admit that node as `PASS_WITH_SCREEN_FALSE_NEGATIVE`.

Do not run `browser_service_probe.py` in the formal workflow. Keep the dedicated
profile untouched; it is not an activation prerequisite.

The Disney probe performs devices → token → GraphQL → supported-location → final
redirect. It stores neither transient credentials nor response bodies:

```bash
python3 scripts/disney_service_probe.py \
  --skill-script scripts/clashverge_to_openclash.py \
  --source-snapshot /path/to/source-snapshot.json \
  --output /private/path/disney-functional-results.json
```

Pass one or more result files to `all`, `probe`, or `reconcile-probe` with
repeatable `--functional-results`. Each result must match the snapshot ID/hash,
stable node ID, exact node name, service, timestamp, and method version.

### Local generation only

```bash
python3 scripts/clashverge_to_openclash.py all --no-refresh-source
```

With an explicit effective YAML:

```bash
python3 scripts/clashverge_to_openclash.py transform \
  --source-snapshot /path/to/source-snapshot.json \
  --output /tmp/openclash-simple-final.yaml \
  --audit-output /tmp/openclash-simple-final-audit.yaml
```

## Source refresh and snapshot contract

1. Run `REFRESH_SOURCE → VERIFY_SOURCE_REFRESH → FREEZE_SOURCE_SNAPSHOT` before discovery, probing, generation, or router access. A failure must report zero router contacts and zero OpenClash changes.
2. Bind only the active remote profile that produces the effective `clash-verge.yaml`. Never update all profiles, accept a URL from the caller, or manually edit subscription metadata, caches, URLs, or credentials; only Clash Verge's safe-save path may update the bound source and its metadata.
3. Clash Verge Rev 2.5.1 officially exposes refresh only as the internal Tauri command `update_profile(index, option)`; upstream has no external refresh CLI or localhost refresh route. This project adds a custom authenticated loopback bridge and an explicit source-only internal path that reuse the upstream download, parse, fallback, and safe-save semantics. Do not describe the bridge as an official JSON adapter, and do not substitute a fixed sleep or blind GUI clicks.
4. Accept `SUCCESS_CHANGED` and `SUCCESS_NOT_MODIFIED`. Fail closed on auth, transport, parse, timeout, identity, empty-result, identity-collision, or configurable node-retention gates. Verify the raw profile UID inside the authenticated request path, but report only a masked identity.
5. The custom Clash Verge build binds only `127.0.0.1`, writes a random mode-0600 bearer token, rejects replayed nonces, accepts no URL input, and exposes only ready, source update, and shutdown routes in source-only mode. Pin the app-data directory with `CLASH_VERGE_SOURCE_REFRESH_HOME` and the independently built binary with `CLASH_VERGE_SOURCE_REFRESH_BINARY`; never replace the installed app for a refresh.
6. Capture active profile, proxy mode, selected-node state, effective system proxy, TUN setting, Mihomo process state, and network exit before refresh. Require the same values afterward. When the app was stopped, wait for authenticated READY, refresh, freeze, request authenticated shutdown, and verify stopped again. Restore non-source config bytes even after success.
7. Store a mode-0600 private YAML payload plus a mode-0600 audit-safe JSON manifest. Include schema, timestamps, HMAC profile identity, source hash, normalized names, HMAC stable node IDs, protocols, node counts, diff summary, and refresh outcome. Never include subscription URLs, tokens, UUIDs, passwords, keys, or raw connection identities in the manifest.
8. Derive stable node IDs from an HMAC of normalized connection identity excluding the display name. The HMAC key is private and mode 0600. A same-name node with changed connection identity cannot inherit manual or LKG evidence.
9. After freezing, read only the private payload. Bind probe, candidate, and activation records to the same `source_snapshot_id` and `source_hash`. If live source changes, replay the frozen payload or stop; never mix sources.
10. `all` and `probe` refresh by default. Use `refresh-source` to refresh and freeze only, `snapshot-source` or explicit `--no-refresh-source` to mark `SOURCE_REFRESH_SKIPPED_EXPLICITLY`, and `--source-snapshot` for verified offline replay. A stale snapshot blocks activation after the configurable TTL unless `--allow-stale-source-activate` is explicitly supplied.

The refresh-adapter stdin/stdout protocol is JSON version 1. Input action is
`update_profile_source`. The wrapper sends the raw UID and a SHA-256 identity of
UID plus the stored URL only across the authenticated loopback channel. Output
contains a masked identity, verified hashes/counts, selected download path,
timestamps, nonce, and the path/hash of the one-time enhanced snapshot; it never
contains a URL, token, profile body, or exact UID. Hermes freezes that isolated
snapshot and deletes it instead of rereading stale `clash-verge.yaml`. An
unavailable adapter is `STOP_SOURCE_REFRESH_FAILED`, not a reason to fall back
to the live file.

## Output contract

The full output:

- contains real connection parameters;
- is written with mode 0600;
- must never be pasted into chat or logs.

The audit output:

- preserves node names, types, group membership, order, DNS, and rules;
- recursively redacts server, port, password, UUID, token, secret, SNI/servername, Reality keys and IDs, provider subscription URLs, and Authorization/Proxy-Authorization headers across the entire YAML object;
- may be used for manual review.

Report only paths and counts. Never print the YAML body or connection secrets.

## Dynamic service-probe contract

- Private state: `~/.hermes/state/clashverge-openclash-static/service-probe-lkg.json`, schema version 1, atomically written with mode 0600.
- Diagnostic report: `/tmp/openclash-service-probe-results.json`, atomically written with mode 0600.
- State and report contain snapshot ID/hash, exact names and HMAC node IDs, explicit evidence types, timestamps, LKG decisions, and redacted egress signatures only. They never contain node connection parameters or a full egress IP.
- The first state is seeded from the three service groups produced by the current baseline transform; no second hard-coded seed list exists.
- Selector PUT must be followed by controller GET and exact full-name confirmation. Unconfirmed selection is `NODE_SWITCH_UNCONFIRMED`, not service failure.
- For local-only probe commands, run the temporary core in `rule` mode with an independent `PROBE` selector and final `MATCH,PROBE`; bind it to active `en0`, or a verified active physical default interface when `en0` is unavailable. Treat this path as diagnostic because a router transparent proxy can still capture it.
- For every deploying `all` run, run the temporary core on the router instead: fixed loopback-only ports, no TUN/listeners/tunnels/routing mark, UID/GID 65534, and an SSH loopback tunnel for controller and mixed-port access. If production OpenClash is running, require the nft GID-65534 bypass before starting the sidecar. Hash production UCI/service/rule/table-354/nft/TUN state before and after and fail if it changes.
- Validate the temporary YAML with the selected Mihomo core before startup. After startup, confirm runtime mode and final rule through the controller and read `GLOBAL`; `GLOBAL.now=DIRECT` is harmless in rule mode because requests explicitly use the temporary mixed proxy and `MATCH` targets `PROBE`.
- Requests are serial per node, use a fresh curl process, connect timeout 3 seconds, total timeout 8 seconds, at most two attempts, and a 15-minute round deadline. The selector wait is 0.75 seconds.
- GPT 403 challenge evidence is `CHALLENGE_UNKNOWN`, never `FAIL_REGION` without explicit region text.
- Manual calibration requires exact raw name, exact HMAC node ID, exact service, exact source snapshot, test time, and method. Store these separately; newer definitive actual-use evidence takes precedence over older screening evidence.
- RegionRestrictionCheck is screening evidence. ChatGPT/Gemini `Yes` is `SCREEN_PASS`; Gemini `No` is `SCREEN_NEGATIVE`. Bind any manual override to the exact snapshot and stable node ID. Never require browser automation for candidate generation or activation.
- Resolve the RegionRestrictionCheck runner proxy once and use that same explicit loopback URL for every router-side control request and `regioncheck -M 4 -P`. Make the first post-selector request a best-effort connection discard with no evidence semantics. Then query the bounded ipify, ifconfig.co, ipinfo, Cloudflare trace, and AWS check-IP IPv4 backends in order with fresh curl processes; accept only a public IPv4 and persist only a run-keyed HMAC.
- Record `ATTRIBUTION_MATCH` only when the control and RegionRestrictionCheck exits are comparable and agree. A single node with no usable control backend or no comparable RegionRestrictionCheck provider is `ATTRIBUTION_UNAVAILABLE`: emit no service evidence and continue. Retry an explicit mismatch once, then stop with `STOP_RRC_PROXY_ATTRIBUTION_MISMATCH`. Stop systematic control failure only after three consecutive unavailable nodes, or after at least eight attempts when unavailable exceeds 25%.
- Disney probing must POST `/devices`, obtain an assertion, POST `/token`, distinguish `forbidden-location` and HTTP 403, POST `/graph/v1/device/graphql`, parse `countryCode` and `inSupportedLocation`, and reject final `disneyplus.com` redirects containing `preview` or `unavailable`. Persist no assertion, token, refresh token, or response body. Until that full chain runs, emit `UNKNOWN_INCOMPLETE_PROBE`, not PASS.
- Egress persistence is limited to country, ASN, and a run-keyed HMAC prefix. Mark `PROBABLE_TUN_OR_UPSTREAM_RECAPTURE` only when at least three `BASE_PASS` nodes span at least two declared regions and every eligible node has the same complete signature. Transport failures do not participate; a guarded run cannot change LKG or service groups.
- Temporary YAML, response bodies, headers, logs, Mihomo, PID, SSH tunnel, and lock are cleaned in `finally`. Candidate-probe failure must occur before the activation transaction and must never invoke production rollback.

## Deployment contract

1. Use SSH BatchMode; never use `sshpass` or embed a password.
2. Upload with `scp -O` for OpenWrt/Dropbear compatibility.
3. Write to a temporary remote path, validate its hash and Mihomo syntax, then move it to `/etc/openclash/config/.clashverge-candidates/`. This upload phase must not read production UCI/service state or start a rollback transaction.
4. Run the installed core:

```bash
/etc/openclash/core/clash_meta -t -d /etc/openclash -f <temporary-file>
```

5. Sidecar-test the candidate before activation. Its DNS and proxy listeners are loopback-only and it must not enable TUN, TPROXY, policy routing, firewall integration, or LAN access.
6. Activation is the transaction boundary. Only here read the real active YAML path from UCI and back up that active YAML, the destination state, `/etc/config/openclash`, `/etc/config/dhcp`, `/etc/config/firewall`, enabled/running/core state, and full diagnostic snapshots of IPv4/IPv6 rules, table 354, OpenClash nft state, and utun state.
7. Atomically copy the immutable candidate into the production config path, set UCI, enable OpenClash, and commit. Restart an originally running service, but treat the init-script exit code as advisory because procd may report `service delete: Not found`; check actual running state and issue one `start` fallback when needed. The bounded Layer 0–3 health checks remain authoritative.
8. After restart, poll once per second against a 110-second remote-health deadline and require two consecutive complete passes. Each pass verifies enabled/running service state, the core process, selected-config path and exact candidate bytes, Mihomo syntax, controller and mixed/HTTP listeners, router DNS and HTTP 204, and proxy HTTP 204. When an enabled OpenClash authentication section exists, read it only inside the remote shell and pipe an escaped curl-config line over stdin; never place credentials in argv, stdout, logs, or reports. Apply the same consecutive-pass rule to LAN egress.
9. On install, restart, or health failure, first stop OpenClash while its live DNS/firewall rollback bookkeeping still exists. In a rollback `finally` path, restore the destination and original active YAML states, OpenClash/DHCP/firewall UCI, reload firewall and dnsmasq, and restore the original enabled/running service state. A procd `service delete: Not found` must not skip later recovery steps. Capture absent rule/table/TUN state as an empty section instead of a shell error.
10. Post-rollback health is layered: actual OpenClash core process state (Layer 0), restored Mihomo config test (Layer 1), authentication-aware proxy listener/egress or absence of stale fwmark/table 354/nft redirect state (Layer 2), and transparent egress from the LAN machine running the deployment (Layer 3). Poll the restored network snapshot to a separate bounded deadline and judge the final stable state, not an intermediate firewall/dnsmasq reload state. Compare OpenClash nft snapshot lines in sorted order so firewall reload declaration reordering does not become a false rollback failure while rule-set additions/removals still fail. `curl --noproxy '*'` disables explicit proxy variables only; it is deliberately not claimed to bypass router transparent interception. Return an explicit `ROLLBACK_FAILED` status only if a required final state still fails at its deadline.
11. Never reboot the router.

## Stop conditions

Stop without deploying when:

- the source has no static `proxies:` list;
- none of the accepted GPT, Gemini, or Disney candidates exist in the current subscription;
- any group or rule target is missing;
- a group cycle or duplicate group name exists;
- the final MATCH is not exactly `MATCH,默认代理`;
- local or remote YAML/Mihomo validation fails.
