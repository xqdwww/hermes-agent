# Hermes Clash Verge → OpenClash Static Skill

This bundle contains:

- `SKILL.md`: Hermes orchestration and safety contract.
- `scripts/clashverge_to_openclash.py`: deterministic implementation.
- `tests/test_clashverge_to_openclash.py`: synthetic contract tests.
- `requirements.txt`: Python dependency.

Quick start:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/clashverge_to_openclash.py all
```

Transform a specific file:

```bash
python3 scripts/clashverge_to_openclash.py transform \
  --input /path/to/clash-verge-effective.yaml \
  --output /path/to/clash-verge-static-openclash.yaml
```

Deploy after inspection:

```bash
python3 scripts/clashverge_to_openclash.py deploy \
  --file /path/to/clash-verge-static-openclash.yaml \
  --host root@192.168.10.1
```
