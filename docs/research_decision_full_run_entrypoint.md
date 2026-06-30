# Research/Decision Full-Run Entrypoint Contract

Explicit `task_engine_runner full` requests must resolve to the current repo runner, `tools.task_engine_runner.task_engine_runner`.

For executable `RESEARCH` and `DECISION` full runs, the runner may proceed directly into the current runner action. For archived combined `RESEARCH_DECISION` full runs, the runner must block with `BLOCKED_STATUS`, `blocked_stage`, `blocked_reason`, and `artifact_dir`.

The runner response must not be a confirmation card and must not require a second confirmation. Legacy hybrid engine commands and legacy decision-engine prompt paths are not valid generated commands for current task-engine full-run requests.

Route, contract, dry-run, and preflight responses are still allowed when the user asks for route/preflight information rather than execution. Those responses must be marked as not executed.

The evidence-backed runner sidecar remains explicit opt-in only. It can emit status/scaffold artifacts, but it must not become a default, change the final answer, mutate `runner_result`, acquire sources, or execute topic refinement.
