---
name: series-b-score-improvement-pipeline
description: Use when Travel / Series B or a comparable evaluation track needs a guarded score-improvement cycle from failed-case triage through source acquisition, Codex intake/formal-ready handoff, case-scoped controlled execution, no-write candidate rerun, human review, separately authorized official baseline write, runtime metadata alignment, smoke, backup, and remaining-queue planning.
---

# Series B Score Improvement Pipeline

## Purpose

Use this skill to run a safe, staged score-improvement cycle for Series B-style evaluation work. The skill defines sequencing, ownership, report contracts, and stop conditions. It does not itself authorize source acquisition, controlled execution, baseline writes, runtime metadata updates, pushes, or releases.

## Post-60 Closure Rule

When a track has reached a human-reviewed `60/60` official baseline with caveats and runtime metadata is aligned, stop case chasing by default. Future work should be release-readiness planning, skill hardening, documentation, regression-test cleanup, or explicitly scoped refactor only. Do not start new source acquisition, intake, formal-ready review, controlled execution, candidate rerun, or baseline movement unless the user opens a new validation scope.

A `60/60` baseline must be described as human-reviewed with caveats, not as caveat-free absolute success. Preserve the final caveat registry in release notes, runtime docs, and backup manifests.

## When To Use

Use this skill when a failed/deferred case queue needs disciplined progression from evidence gaps to candidate-score review, or when the user asks to plan, execute, audit, or document a Series B score-improvement batch.

## When Not To Use

Do not use this skill for ordinary code repair, one-off source acquisition only, local context-axis intake only, production/runtime metadata repair only, or baseline writing without prior no-write candidate rerun and human review. For pure material acquisition, use `source-gap-acquisition` instead.

## Executor Split

- Hermes: source acquisition only, when explicitly authorized. Hermes may save raw/context material and source-acquisition reports, but must not modify the repo, vectorize, formal-ready, controlled-run, baseline-write, push, or tag.
- Codex: engineering, intake, normalization, chunking, sandbox vectorization, readiness, formal-ready review, handoff, harness patching, tests, controlled execution, candidate no-write rerun, reports, and skill maintenance.
- Human/user: policy confirmation for adversarial cases and approval before any official baseline write.

## Pipeline State Model

Use explicit state names and never skip state transitions:

- `FAILED_OR_DEFERRED`: official baseline still fails or defers the case.
- `SOURCE_ACQUIRED`: Hermes has produced source acquisition reports and usable/rejected source validation.
- `INTAKE_READY`: Codex has validated source inputs as safe for local intake.
- `FORMAL_READY`: Codex has approved formal-ready evidence with caveats.
- `HANDOFF_GENERATED`: controlled execution handoff exists and locks production/baseline/full-run flags off.
- `CONTROLLED_PASS`: case-scoped controlled dry-run passed and archive exists.
- `CANDIDATE_PASS`: no-write candidate rerun counts the controlled pass as candidate-only delta.
- `HUMAN_REVIEWED`: human-review audit accepts or rejects candidate countability.
- `BASELINE_WRITTEN`: separately authorized commit updates official current/ledger only.
- `RUNTIME_ALIGNED`: separately authorized runtime/production metadata update and smoke pass.
- `SEALED_BACKUP`: local bundle, reports, smoke, and optional allowed fork backup are complete.

## Batch Selection Rules

Select a batch only when the blocker type is known, disk space is sufficient, source/policy prerequisites are clear, and unrelated cases are out of scope. Prefer cases with clear material gaps, usable source leads, low policy ambiguity, and likely candidate-score impact. Defer adversarial or ambiguous cases until policy exists.

## Source-Gap Branch

When source/material/provenance is the blocker, invoke the `source-gap-acquisition` workflow. Require exact case prompt, missing terms, missing axes, missing sections, usable/rejected source criteria, output dirs, and explicit no-repo/no-vector/no-formal-ready/no-controlled/no-baseline locks. Treat source acquisition PASS as acquisition only, not controlled evidence.

## Adversarial / Policy-Gated Branch

For malformed tokens, typo traps, booking/listing contamination, ambiguous aliases, pricing/ticket traps, or adversarial scoring, define policy before acquisition. Stop if policy is absent. Never count policy-gated cases without policy, source validation, formal-ready approval, controlled pass, candidate rerun, and human review.

## Codex Intake / Formal-Ready / Handoff Branch

Run this branch only after source acquisition or local inventory is ready. Start with disk-space guard and repo-clean guard. Audit source inputs against source-gap rules. Normalize, page-map, chunk, and sandbox-vectorize only case-scoped derived outputs. Do not modify raw source. Run readiness and formal-ready review. Generate handoff only for approved cases. Stop before controlled execution.

## Controlled Execution Branch

Run controlled execution in a separate task. Process cases sequentially. For each case: validate handoff, write safe API design, patch case-scoped tools/tests only, run tests, commit one guarded case, run post-commit guard, execute one real controlled dry-run, and archive if PASS. Stop on first FAIL, PARTIAL, BLOCKED, test failure, or dirty scope. Roll up evidence only if all selected cases PASS.

## Candidate Rerun Branch

After a controlled evidence rollup, run a no-write candidate rerun or candidate scoring audit. The result is candidate-only. It must clearly state current official baseline, candidate score, delta cases, remaining failed/deferred cases, no-write flags, and that no official score moved.

## Candidate Human-Review Branch

Human review is mandatory before baseline writes. Review every delta case for source-backed body, caveat preservation, rejected source exclusion, axis overclaim, contamination, artifact completeness, and whether it should count officially. Allowed decisions include approved, approved with caveat, needs more evidence, and rejected.

If human review is partial, inconclusive, or scoped to only some delta cases, narrow the baseline-write target to the accepted scope or stop. Do not promote candidate-only deltas that were outside the review scope; require a focused human-review task before counting them officially.

## Official Baseline Write Branch

Baseline write is a separate authorized task. It may modify only official current/ledger files unless the user explicitly widens scope. It must preserve caveats, list newly countable cases, list remaining failed/deferred cases, validate JSON, pass scope guard, commit baseline files only, and never update runtime metadata in the same commit unless separately authorized.

## Runtime Metadata Update Branch

Runtime or production metadata updates happen only after the baseline commit exists. Update expected score/metadata, preserve caveats, rerun non-destructive sanity and runtime smoke, commit runtime metadata separately, and do not modify official baseline files.

## Smoke / Sanity / Backup Branch

Before intake, vectorization, or bundle work, check disk space. For release closure, run non-destructive tests and smoke, create local bundle, verify bundle, write reports, and use local-only fallback if external push is blocked. Never push origin, force-push, or push all tags.

Release planning is not release execution. A release plan may list what would be pushed if authorized, what must not be pushed, rollback from bundle, and exact future authorization wording. It must not push branches, push tags, create remote releases, or contact origin without explicit authorization.

## Remaining Queue Planning Branch

After each score cycle, write a remaining queue matrix with blocker type, material gap, policy gap, local source signals, priority, risk, recommended executor, and next action. Do not start another batch inside the same task unless explicitly authorized.

## Hard Prohibitions

- Never update official baseline from candidate-only result.
- Never combine controlled execution with formal-ready intake in the same task.
- Never combine baseline write with human review unless separately authorized.
- Never run production/runtime metadata update before baseline commit exists.
- Never push origin or force-push.
- Never count policy-gated adversarial cases without policy, controlled pass, and human review.
- Never treat source acquisition PASS as controlled evidence.
- Never treat controlled evidence as official score without candidate rerun and human review.
- Never mutate source raw during Codex intake.
- Never write production vector indexes during sandbox intake.
- Always stop on dirty scope or unexpected tracked file changes.
- Always keep caveats attached to candidate, human-review, baseline, and runtime reports.
- Always check disk space before intake, vectorization, or bundle generation.

## Stop Conditions

Stop with a blocked or partial status when any of these occur: wrong branch/head, dirty scope, low disk, invalid source, missing policy, handoff mismatch, test failure, pycache/pyc artifact, controlled result not PASS, candidate runner cannot safely consume inputs, human review rejects a delta, baseline scope drift, runtime smoke failure, remote tag mismatch, non-fast-forward remote, or approval-layer push block.

## Status Enums

Use precise enums such as:

- `PIPELINE_PREFLIGHT_BLOCKED`
- `SOURCE_GAP_ACQUISITION_READY`
- `POLICY_GATED_NEEDS_HUMAN_CONFIRMATION`
- `INTAKE_READY_FOR_FORMAL_REVIEW`
- `FORMAL_READY_APPROVED_WITH_CAVEAT`
- `CONTROLLED_EXECUTION_PASS`
- `CONTROLLED_EXECUTION_BLOCKED`
- `CANDIDATE_RERUN_PASS_NO_WRITE`
- `HUMAN_REVIEW_APPROVED_WITH_CAVEAT`
- `BASELINE_WRITE_READY_WITH_CAVEATS`
- `BASELINE_WRITE_NOT_READY`
- `RUNTIME_METADATA_ALIGNED`
- `SEALED_BACKUP_PASS`

## Required Report Contracts

Each stage must write Markdown and JSON reports under explicit repo-outside output dirs. Reports must include repo path, branch, head, official baseline current, candidate-only status where relevant, cases attempted, cases passed/blocked, caveats, no-write attestations, scope guard, tests/smoke run, and recommended next action.

## Templates

Use bundled templates as starting points:

- `templates/failed_case_triage_matrix.md`
- `templates/codex_intake_authorization_prompt.md`
- `templates/controlled_execution_queue_prompt.md`
- `templates/candidate_human_review_prompt.md`
- `templates/baseline_write_authorization_prompt.md`
- `templates/runtime_metadata_update_prompt.md`
- `templates/release_backup_and_smoke_prompt.md`

## Examples Only

For an illustrative Travel / Series B case study, read `examples/travel_series_b_44_to_50_pipeline_case_study.md`. Treat that file as a historical example only. Do not use its scores, commit hashes, case ids, or paths as fixed assumptions for other tasks.
