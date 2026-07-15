---
name: clashverge-openclash-static
summary: Probe imported Clash Verge nodes, merge calibrated last-known-good service candidates, generate the accepted simple static OpenClash profile, and deploy it safely.
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

## Accepted policy

The generated profile must contain exactly these 12 managed groups:

1. 默认代理
2. 手动选择
3. 自动选择
4. GPT专用
5. GPT手动
6. GPT自动
7. Gemini专用
8. Gemini手动
9. Gemini自动
10. 迪士尼
11. 迪士尼手动
12. 迪士尼自动

Rules:

- Never generate `全局优先│...`, `GPT优先│...`, `Gemini优先│...`, `迪士尼优先│...`, or their full-width-bar variants.
- Manual groups list direct nodes. Their first item is the corresponding automatic group.
- Automatic groups are ordinary `fallback` groups.
- All fallback groups use `https://www.gstatic.com/generate_204`, interval 60, lazy true, timeout 5000, and max-failed-times 1.
- Global/GPT/Disney ordering is Japan → Taiwan → other nodes.
- Gemini ordering is Japan → Taiwan → Hong Kong → Germany → other nodes.
- Remove the placeholder node named `使用前先更新订阅`.
- The historical GPT/Gemini/Disney candidate sets seed last-known-good state on the first run. Do not restore the old binary GPT probe.
- New imports use one temporary loopback Mihomo instance, serial selector switching with controller read-back, multi-signal service probes, exact manual calibration, and LKG merging.
- `PASS` and manual PASS enter automatic and manual groups. Existing LKG survives challenge, auth uncertainty, unknown, and a single transport failure. Explicit region failure or manual FAIL removes it.
- New UNKNOWN nodes may appear only at the tail of the corresponding manual group; they never enter the automatic group.
- If a service has no LKG nodes, stop with `BLOCKED_NO_LKG_<SERVICE>_NODES`; never delete its group or rules and never silently route it through the default group.
- Preserve ordinary source rules, rename the old target `顺畅网络` to `默认代理`, regenerate narrow GPT/Gemini/Disney rules, and finish with exactly `MATCH,默认代理`.
- Remove Clash Verge-only controller/listener/profile fields, temporary probe/controller fields, and `/tmp/verge` paths if present. Preserve a general top-level `tun` section because it may carry user network semantics.
- Validate group references, rule targets, cycles, duplicate names, and the final MATCH before writing or deploying.

## User phrases

### “更新 OpenClash 节点”

Export, transform, deploy, validate remotely, activate, and restart OpenClash:

```bash
python3 scripts/clashverge_to_openclash.py all \
  --deploy \
  --activate
```

Before generation, `all` probes current static nodes locally and updates the private LKG state. Deployment still uses the existing validated backup/health/rollback path.

### “更新 OpenClash 节点，但不要启用”

Export, transform, upload, and remotely validate, but do not switch the active profile or restart:

```bash
python3 scripts/clashverge_to_openclash.py all \
  --deploy
```

This still performs the local probe and LKG merge, but remote activation and restart remain disabled.

### “测试 OpenClash 节点”

Probe and refresh the diagnostic report without generating or deploying and without changing LKG:

```bash
python3 scripts/clashverge_to_openclash.py probe
```

Only an explicit request may update LKG in probe-only mode:

```bash
python3 scripts/clashverge_to_openclash.py probe --update-lkg
```

### Local generation only

```bash
python3 scripts/clashverge_to_openclash.py all
```

With an explicit effective YAML:

```bash
python3 scripts/clashverge_to_openclash.py transform \
  --input /path/to/clash-verge-effective.yaml \
  --output /tmp/openclash-simple-final.yaml \
  --audit-output /tmp/openclash-simple-final-audit.yaml
```

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
- State and report contain node names, polymorphic service results, timestamps, LKG decisions, and redacted egress signatures only. They never contain node connection parameters or a full egress IP.
- The first state is seeded from the three service groups produced by the current baseline transform; no second hard-coded seed list exists.
- Selector PUT must be followed by controller GET and exact full-name confirmation. Unconfirmed selection is `NODE_SWITCH_UNCONFIRMED`, not service failure.
- Run the temporary core in `rule` mode with an independent `PROBE` selector and final `MATCH,PROBE`; bind it to active `en0`, or a verified active physical default interface when `en0` is unavailable. Reject loopback, `utun`, and virtual interfaces with `BLOCKED_NO_PHYSICAL_INTERFACE`.
- Validate the temporary YAML with the selected Mihomo core before startup. After startup, confirm runtime mode and final rule through the controller and read `GLOBAL`; `GLOBAL.now=DIRECT` is harmless in rule mode because requests explicitly use the temporary mixed proxy and `MATCH` targets `PROBE`.
- Requests are serial per node, use a fresh curl process, connect timeout 3 seconds, total timeout 8 seconds, at most two attempts, and a 15-minute round deadline. The selector wait is 0.75 seconds.
- GPT 403 challenge evidence is `CHALLENGE_UNKNOWN`, never `FAIL_REGION` without explicit region text.
- Manual calibration matches only an exact raw node name or the exact name after removing a leading flag and spaces.
- Egress persistence is limited to country, ASN, and a run-keyed HMAC prefix. Mark `PROBABLE_TUN_OR_UPSTREAM_RECAPTURE` only when at least three `BASE_PASS` nodes span at least two declared regions and every eligible node has the same complete signature. Transport failures do not participate; a guarded run cannot change LKG or service groups.
- Temporary YAML, response bodies, headers, logs, and Mihomo are cleaned in `finally`. The probe never changes Clash Verge, TUN, system proxy, OpenClash, or router state.

## Deployment contract

1. Use SSH BatchMode; never use `sshpass` or embed a password.
2. Upload with `scp -O` for OpenWrt/Dropbear compatibility.
3. Write to a temporary remote path.
4. Run the installed core:

```bash
/etc/openclash/core/clash_meta -t -d /etc/openclash -f <temporary-file>
```

5. Before upload or replacement, read the real active YAML path from UCI. If it cannot be read, stop without guessing. Back up that active YAML when it exists, the destination YAML state, `/etc/config/openclash`, and the original enabled/running service state.
6. Only after validation passes, atomically replace the remote YAML.
7. Activation is opt-in. When requested, set the UCI config path, enable OpenClash, commit UCI, and restart the service.
8. After restart, retry health at most three times with a two-second interval. Each attempt verifies the service, validates the YAML currently selected by UCI with the installed core, discovers the mixed/HTTP proxy port from OpenClash UCI or the running/active YAML, verifies that port is listening, and requests `https://www.gstatic.com/generate_204` through that proxy with a three-second connect timeout and eight-second total timeout.
9. On install, restart, or health failure, restore the destination and original active YAML states, UCI, and enabled/running service state. Re-read and validate the restored active YAML and service state; return an explicit `ROLLBACK_FAILED` status if restoration or verification fails.
10. Never reboot the router.

## Stop conditions

Stop without deploying when:

- the source has no static `proxies:` list;
- none of the accepted GPT, Gemini, or Disney candidates exist in the current subscription;
- any group or rule target is missing;
- a group cycle or duplicate group name exists;
- the final MATCH is not exactly `MATCH,默认代理`;
- local or remote YAML/Mihomo validation fails.
