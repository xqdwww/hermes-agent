---
name: research-decision-guarded-validation-operator
description: Use for scoped Hermes Research/Decision guarded validation, resume, closeout, artifact audit, and commit-readiness review with strict worktree and evidence guards.
version: 1.1.0
status: active
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    status: active
    executor: codex
    category: research-decision
    activation: explicit-or-contextual
    tags: [research-decision, guarded-validation, stage-records, closeout, operator-audit]
---

# Research/Decision Guarded Validation Operator

## purpose

Use this skill when operating or auditing a Hermes Research/Decision guarded validation run. The goal is to preserve source integrity, artifact integrity, and decision integrity. A structural PASS is not enough by itself: the operator must prove that the current run used the expected branch and HEAD, that required stage records and reports exist, that failures were not hidden, and that no source or test changes slipped into the validation scope.

This skill is an operator manual, not a run log. Do not encode one-time sample names, local incident details, or task-specific output paths as permanent rules.

## trigger conditions

Use this skill when the task asks for any of the following:

- Research/Decision guarded validation or closeout.
- Resume after an external executor, bridge, or model readiness interruption.
- StageRecord, convergence report, calibration report, or final-controller report audit.
- Validation artifact matrix creation.
- Commit or tag readiness review after a validation run.
- Distinguishing output artifacts from tracked source changes.

Do not use this skill for unrelated product workflows, code repair outside the declared scope, or bypassing a failed gate. If the task is about changing final-controller quality logic, use a dedicated quality-audit workflow before any commit decision.

## required inputs

Record these inputs before running, resuming, or closing out validation:

- Expected repository path.
- Expected branch.
- Expected HEAD, tag, or baseline commit if supplied.
- Allowed output root.
- Allowed modified files, if any.
- Required sample ids or run ids.
- Required stages and expected stage count.
- Required artifact list.
- Allowed executor and model policy.
- Explicit commit, tag, push, or no-commit instruction from the user.

If a required input is missing but the task can be safely audited from local state, proceed with a stated assumption. If the missing input affects source identity, branch identity, executor policy, or allowed write scope, stop and report.

## hard guard checklist

Run these checks before validation, resume, closeout, tag recommendation, or commit recommendation:

- `git rev-parse HEAD`
- `git branch --show-current`
- `git status --porcelain=v1 -uall`
- `git status --porcelain=v1 -uno`
- `git diff --name-only`
- `git diff --cached --name-only`

Stop immediately when:

- HEAD differs from the expected source commit and the user did not approve that change.
- Branch differs from the expected branch.
- Staged diff is not empty.
- Tracked diff exists outside the allowed scope.
- Untracked files exist outside the allowed output or skill-review scope.
- A requested validation would mix artifacts from different source commits.
- A required executor is unavailable and the approved resume path cannot recover it.
- A stage contract fails or a required artifact is missing.

Untracked `outputs/**` can be allowed only when the task declares output artifacts as uncommitted evidence. Never stage those outputs unless the user gives an explicit, separate instruction.

## allowed scope

A guarded validation task may read source, logs, StageRecords, summaries, and output artifacts. It may write only the output artifacts requested by the task. It must not modify production code, tests, skills, registries, router policy, model policy, bridge code, or executor configuration unless the user explicitly changes the task from validation to repair.

When a repair is requested, scope must be restated. Do not carry validation permissions into a source-editing task.

## forbidden actions

Never:

- Fabricate `PIPELINE_COMPLETE`, `decision_validation.valid=true`, stage counts, or StageRecords.
- Edit artifacts to make a failed run appear successful.
- Hide an original transient failure after a resume succeeds.
- Bypass the router, route lock, tool lock, or model policy to force a result.
- Replace a failed required executor with a different path without explicit approval.
- Treat terminal silence as failure while a stage may still be running.
- Treat a smoke gate as substantive quality proof.
- Expand sample scope to avoid closing out the requested scope.
- Commit when tests fail, when unrelated diff exists, or when production contains case-specific hacks.
- Push, tag, merge, or stage files unless the user explicitly asks for that exact action.

## operating flow

1. Preflight: record branch, HEAD, tracked diff, staged diff, untracked output classification, and allowed scope.
2. Run or resume only through the approved Research/Decision engine path. Do not directly call prohibited tools or bypass the router.
3. For each sample or run unit, collect stage summaries, StageRecords, executor metadata, convergence report, calibration report, final-controller report, and validation JSON.
4. If a stage fails, classify the failure before retrying. Preserve raw error, timestamp, run id, sample id, stage name, command, executor metadata, partial artifacts, branch, HEAD, and git status.
5. Resume only when the failure is transient and the configured executor path is available again. Do not change model or tool policy without approval.
6. After completion, audit artifacts directly. Do not rely on console text or a single PASS label.
7. Write a closeout report with matrices, failure notes, git cleanliness, and commit or tag recommendation.

## artifact audit checklist

For each completed run unit, verify:

- Research status and Decision status are present and successful under the run contract.
- Pipeline status is complete under the run contract.
- StageRecords exist for every required stage.
- Expected stage count matches the validation contract.
- `convergence_report.md` exists and is non-empty.
- `calibration_report.md` exists and is non-empty when calibration is required.
- `final_controller_report.md` exists and is non-empty.
- Summary or validation JSON exists and records a valid final decision.
- Executor metadata is present enough to explain which path ran.
- Any legacy-term or forbidden-term checks required by the task were run.
- Reports correspond to the current run id and expected output root.

If any item is absent, stop with an incomplete-artifact report. Do not infer missing stage success from the final answer.

## source diff and test selection

Before recommending commit or tag readiness, audit source state again:

- `git status --porcelain=v1 -uno` must be clean unless the task explicitly allows tracked source edits.
- `git diff --name-only` must match the allowed file list.
- `git diff --cached --name-only` must be empty unless the task explicitly requests staging.
- If tests are required, select the smallest relevant test set that covers the changed behavior.
- If a broad selector fails, report the failing tests before narrowing. Narrowing can clarify root cause, but it cannot hide a related failure.
- Skipped tests must be explained. A skipped required test means no commit recommendation unless the user accepts the residual risk.
- Mock, dummy, or manually edited artifacts cannot prove a guarded validation pass.

## stop conditions

Return a stop-with-report result when:

- Branch, HEAD, tracked diff, staged diff, or allowed scope is wrong.
- A required artifact or StageRecord is missing.
- A validation JSON or stage contract contradicts the human-readable report.
- An executor remains unavailable after approved readiness triage.
- Tests fail in the changed behavior area.
- The final answer depends on case-specific production hacks.
- The operator cannot determine whether artifacts belong to the current run.

A stop report must include observed HEAD, branch, dirty files, failing command or check, affected artifacts, and the next safe action.

## report contract

A guarded validation closeout report should include:

- `status`
- `repo_path`
- `head`
- `branch`
- `worktree_status`
- `allowed_scope`
- `samples_or_run_units_reviewed`
- `stage_completion_matrix`
- `artifact_presence_matrix`
- `executor_metadata`
- `transient_failure_notes`
- `source_diff_audit`
- `tests_run`
- `quality_notes`
- `remaining_risks`
- `commit_recommendation`
- `tag_or_release_recommendation`
- `next_engineering_target`

The report must separate structural validation from substantive answer quality. If final-controller quality is weak, say so even when the guarded pipeline contract passes.

## commit and tag eligibility

A commit can be recommended only when all of these are true:

- The task explicitly allows commit review.
- Allowed tracked files are the only tracked changes.
- Required tests passed or skipped tests are explicitly accepted by the user.
- No required output artifact is being committed by accident.
- Source diff contains no case-specific shortcut, fixture-only branch, or validation bypass.
- The report explains residual risk.

A tag can be recommended only when the source HEAD is known, tracked and staged diffs are clean, artifacts have been audited, and the user explicitly asks for a tag. Do not push any tag by default.

## outcome label guidance

Use closeout labels only after artifact review, not as substitutes for review:

- `PASS_CLOSEOUT_READY`: use only when the requested validation scope is complete, required artifacts are present, tracked and staged diffs satisfy the task guard, and remaining output artifacts are explicitly classified.
- `NOT_COMMITTED_OUTPUTS_ONLY`: use only when tracked and staged diffs are empty and the remaining untracked files are output artifacts that the task says not to commit.

These labels describe the audited repository and artifact state for a specific task. They are not permanent success conditions and must not override failed tests, missing artifacts, or dirty scope.

## anti-patterns

Reject these patterns:

- Calling a run complete because the last command printed a success-like line.
- Continuing after HEAD mismatch to save time.
- Treating untracked outputs as committed evidence.
- Converting a transient executor failure into a hidden success.
- Reusing a previous output root without checking run identity.
- Marking a final answer high quality because it is long or well formatted.
- Using a local incident, fixture, or one-time status as a permanent rule.
- Asking the user to manually verify facts that are available in local artifacts.
