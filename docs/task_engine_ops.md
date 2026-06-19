# Hermes Task Engine Ops

## Current Status

- `RESEARCH`: PASS in WebUI full-run.
- `DECISION`: PASS in WebUI full-run.
- `RESEARCH_DECISION`: PASS in WebUI full-run.
- Deterministic intercept is active for explicit research, decision, and research-decision tasks.
- Ordinary chat is not routed through `task_engine_runner` and should continue to use the normal chat path.

## Daily Regression

Run the lightweight checks before changing task-engine routing, contracts, or adapters:

```bash
python -m py_compile tools/task_engine_contracts.py tools/task_engine_executors.py tools/task_engine_runner.py
pytest -q tests/tools/test_task_engine_contracts.py
python work/check_task_engine_health.py
```

The health check does not run a real full pipeline. It covers compile, regression tests, AGY preflight, OMLX preflight, ChatGPT App Bridge health, and dry/simulated contract matrix checks.

## Stage Scope Matrix

`RESEARCH` has 6 stages and stops at `research_evidence_packet.md`:

- `L1_gemini_search`
- `L2_ddgs_supplement`
- `L2_5_codex_evidence_organizer`
- `L3_r1_synthesis`
- `L4_gemini_audit`
- `L5_deepseek_acceptance`

`RESEARCH` must not run Decision stages such as `intelligence_layer`, `supplementary_search`, divergence roles, `convergence_report`, `external_calibration`, or `final_controller_report`.

`DECISION` has 10 stages and does not run the L1-L5 research phase:

- `intelligence_layer`
- `supplementary_search`
- `structure_mapper`
- `evidence_judge`
- `premise_auditor`
- `alternative_generator`
- `insight_harvester`
- `convergence_report`
- `external_calibration`
- `final_controller_report`

`DECISION` must not create `source_candidates.json`, `ddgs_gap_sources.json`, `r1_synthesis.md`, `gemini_audit_report.md`, or `research_evidence_packet.md`.

`RESEARCH_DECISION` has 16 stages. It must run the complete `RESEARCH` phase first, require an accepted research evidence packet, and only then run the `DECISION` phase. It must not skip directly to Decision or treat a partial research packet as accepted.

## WebUI Intercept Regression

Runner dry-run and simulated-run checks are not the same as testing the real WebUI `/chat-run` entry. When deterministic intercept, WebUI bridge code, installed dist files, or task-mode routing changes, run the real WebUI dry/sim matrix.

Explicit research, decision, and research-decision prompts must show:

- `deterministic_intercept=true`
- `model_bypassed=true`
- `intercepted_mode=<RESEARCH|DECISION|RESEARCH_DECISION>`
- no `ROUTE_CARD` confirmation loop
- no legacy `engine.py --route=hybrid`
- no Flash or default Controller direct answer for the explicit task

Ordinary chat prompts must not trigger deterministic intercept.

## When To Run Full-Run

Run a WebUI full-run only when one of these changes:

- deterministic intercept or WebUI bridge code
- stage executor wiring
- model alias mapping
- external dependency configuration
- artifact validation or final rendering
- after a previously blocked external dependency is fixed

Do not use full-run as a routine smoke test. Prefer dry-run, simulated-run, and preflight first.

## AGY Login State

AGY is required for Gemini-backed stages:

- `L1_gemini_search`: `Gemini 3.5 Flash (High)`
- `L4_gemini_audit`: `Gemini 3.1 Pro (High)`
- `intelligence_layer`: `Gemini 3.5 Flash (High)`
- Gemini fallback for `external_calibration`, if GPT Bridge is unavailable

Check AGY with:

```bash
agy models
```

Required models:

- `Gemini 3.5 Flash (High)`
- `Gemini 3.1 Pro (High)`

If AGY asks for browser authorization or an authorization code, the user must complete it manually. Do not read browser state, Keychain tokens, or logs for tokens.

## AGY Model Alias Nuance

Some AGY logs may show an early message about defaulting to CCPA before the selected model override is propagated. That early CCPA line alone is not enough to fail the run if the same call later shows selected-model override or successful resolution for the requested Gemini model.

Allowed sequence:

- early `defaulting to CCPA`
- later `Resolving model Gemini ...`, selected model override propagation, or successful Gemini auth/use

Blocked sequence:

- `defaulting to CCPA`
- no later selected-model override
- final auth/model timeout or failed call

Never accept a completed stage whose actual executor fell back to CCPA.

## AGY Keychain False-Negative

Known symptom:

- CLI output says `You are not logged into Antigravity`
- the same log later shows one of:
  - `authenticated via keyring`
  - `OAuth: authenticated successfully`
  - `silent auth succeeded`

This is treated as `AGY_KEYCHAIN_TIMEOUT_FALSE_NEGATIVE` and receives one retry after a short sleep. If the second attempt fails, the run must stay blocked. Do not run `agy auth login` from automation, and do not fall back to CCPA or another model alias.

## OMLX Auth And Config

OMLX is required for R1, Qwen72B, Nemotron-120B, Llama70B, and Gemma-4-31B stages.

The runner loads OMLX configuration from the process environment and `~/.hermes/.env`. The key must not be printed.

Lightweight check:

```bash
python - <<'PY'
from tools.task_engine_runner import task_engine_runner
print(task_engine_runner(query="health", mode="RESEARCH_DECISION", action="omlx-preflight"))
PY
```

Expected:

- `status=OMLX_OK`
- `actual_r1_model=DeepSeek-R1-Distill-Qwen-32B-MLX-8Bit`
- `model_visible=true`

If WebUI fails but CLI succeeds, compare whether the WebUI process inherited the same env/config source. Do not hard-code the key into source.

## OMLX Model Load Failures

Triage order:

1. Confirm `omlx-preflight` succeeds.
2. Confirm the actual model id, not the canonical alias, is used.
3. Check whether another large model is already loaded.
4. Confirm admin login succeeds before chat completions.
5. Confirm chat uses the bearer key path and admin load/unload uses the admin session path.

Canonical to actual mappings currently used:

- `R1-32B` -> `DeepSeek-R1-Distill-Qwen-32B-MLX-8Bit`
- `Qwen72B` -> `Qwen2.5-72B-Instruct-abliterated-mlx-4Bit`
- `Nemotron-120B` -> `NVIDIA-Nemotron-3-Super-120B-A12B-5bit`
- `Llama70B` -> `Llama-3.3-70B-Instruct-abliterated-8bit-mlx`
- `Gemma-4-31B` -> `gemma-4-31B-it-qat-8bit`

Do not substitute 9B, Flash, Controller, or another loaded model.

## DDGS Backend Instability

DDGS is required for:

- `L2_ddgs_supplement`
- Decision `supplementary_search`

The default backend list should prefer:

- `duckduckgo`
- `brave`
- `yahoo`

`startpage` is not a default backend because it has shown timeout and redirect instability. If one backend times out, the adapter may try the next allowed backend. The stage blocks only when all allowed DDGS backends fail to produce fresh results. Never use `web_search` or generic search as a fallback.

## Codex Handoff Protocol

`L2_5_codex_evidence_organizer` must use the file-based Hermes-Codex handoff protocol. It must not be replaced by `delegate_task` or an in-memory summary.

Required inputs:

- `source_candidates.json`
- `ddgs_gap_sources.json`
- `evidence_runner_*.request.md`
- `evidence_runner_*.request.json`

Required outputs:

- `sources.csv`
- `evidence.csv`
- `claims.md`
- `gaps.md`

The stage is valid only when these files are created in the current run and pass the pipeline artifact checks.

## ChatGPT App Bridge Health

`external_calibration` uses GPT Bridge first. The existing formal executor is:

- worker: `/Users/Shared/OpenClaw/chatgpt_app_bridge_worker_main.py`
- wrapper: `/Users/Shared/OpenClaw/chatgpt_app_bridge_http_cli.py`
- health: `http://127.0.0.1:18890/health`
- LaunchAgent: `/Users/xqdwww/Library/LaunchAgents/com.hermes.chatgpt-app-main-worker.plist`

Health check:

```bash
curl -sS --max-time 5 http://127.0.0.1:18890/health
```

The wrapper handles its own token. Do not read, print, or write the token.

## GPT Bridge Official Executor Discovery

The formal ChatGPT App Bridge executor is the wrapper:

```text
/Users/Shared/OpenClaw/chatgpt_app_bridge_http_cli.py
```

The worker health endpoint is:

```text
http://127.0.0.1:18890/health
```

Discovery should not rely only on `HERMES_GPT_BRIDGE_CMD` or `HERMES_GPT_BRIDGE_URL`. If those env vars are absent, the runner should discover the existing official wrapper before declaring `GPT_BRIDGE_NOT_CONFIGURED`.

The wrapper and LaunchAgent handle the token. The runner must not read, print, copy, or persist bridge tokens. If the wrapper is unavailable or fails, Gemini 3.1 Pro via AGY is the allowed fallback for `external_calibration`; Nemotron, R1, Controller, Qwen, Llama, and Gemma are not allowed substitutes.

## Artifact Quality Gate

The artifact quality gate prevents execution errors from being treated as valid stage output. Obvious executor-error text near the artifact head blocks the stage, for example:

- `Error: timed out waiting for response`
- `[ERROR:`
- `Traceback`
- `authentication timed out`
- `You are not logged into Antigravity`
- `OMLX_AUTH_BLOCKED`
- `AGY_CALL_BLOCKED`
- `DDGS returned no fresh hits`
- `GPT_BRIDGE_NOT_CONFIGURED`
- `returned empty stdout`

Normal content that discusses timeout risk as a topic should not be blocked.

## Final Render Constraints

For `RESEARCH_DECISION` and `DECISION`, the final markdown body must come from `final_decision_report.md`. The renderer must not expose raw persona output, raw convergence output, or intermediate model transcripts as the final user-facing body.

The final markdown for a complete task must include machine markers:

- `entered_engine_run_pipeline=true`
- `pipeline_status=PIPELINE_COMPLETE`
- `pipeline_validation.valid=true`
- `delegation_used=false`

It must also include a compact pipeline trace with the expected stage count:

- `RESEARCH`: 6 stages
- `DECISION`: 10 stages
- `RESEARCH_DECISION`: 16 stages

Do not leak pseudo-tool plans or raw strings such as `web_search`, `api_call`, or `codex_exec` as if they were executed toolchains. If these appear in an intermediate model artifact for a constrained stage, the output must be cleaned or blocked according to the stage gate.

## Do Not Do

- Do not fall back to CCPA or an unauthorized Gemini alias.
- Do not use `web_search` or generic search instead of DDGS.
- Do not use `delegate_task` instead of the Codex handoff protocol.
- Do not relax the validator to make a run pass.
- Do not let Flash or the default Controller directly answer explicit `RESEARCH`, `DECISION`, or `RESEARCH_DECISION` tasks.
- Do not mark blocked as complete.
- Do not generate a final report unless the relevant pipeline validates completely.
