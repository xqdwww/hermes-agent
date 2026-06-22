# Controlled oMLX Service

Hermes E2E validation should use a single controlled local oMLX server:

- memory ceiling: 120GB
- model directory: `/Users/xqdwww/Workspace/AI_Core/mlx_models`
- base path: `/Users/xqdwww/.omlx`
- logs: `/Users/xqdwww/.omlx/logs`
- pidfile: `/Users/xqdwww/.omlx/hermes-controlled.pid`
- boot behavior: start idle server only; do not preload Nemotron

Before any S01 or S02-S10 E2E validation, run:

```bash
scripts/omlx_start_controlled.sh
scripts/omlx_nemotron_preflight.sh
```

The preflight verifies one oMLX server, 120GB ceiling, disk space, Nemotron load, a minimal Nemotron response, and then unloads Nemotron.

External model preflights still remain required:

- AGY real print-mode prompt preflight, with one retry for auth-like false negatives.
- GPT Bridge / external calibration bridge real prompt preflight, with one retry for first-call bridge readiness.

Install the LaunchAgent only when login startup is desired:

```bash
cp scripts/com.hermes.omlx-controlled.plist ~/Library/LaunchAgents/com.hermes.omlx-controlled.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.hermes.omlx-controlled.plist
launchctl enable "gui/$(id -u)/com.hermes.omlx-controlled"
```

Stop the controlled server with:

```bash
scripts/omlx_stop_controlled.sh
```
