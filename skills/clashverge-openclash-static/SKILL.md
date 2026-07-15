---
name: clashverge-openclash-static
summary: Convert Clash Verge's effective Mihomo configuration into the user's accepted simple static OpenClash profile and deploy it safely.
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
- GPT uses the previously working candidate set intersected with the current subscription. Do not run or trust the old GPT service probe.
- Gemini and Disney use the accepted candidate sets intersected with the current subscription.
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

### “更新 OpenClash 节点，但不要启用”

Export, transform, upload, and remotely validate, but do not switch the active profile or restart:

```bash
python3 scripts/clashverge_to_openclash.py all \
  --deploy
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
