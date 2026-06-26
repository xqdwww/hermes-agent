---
name: source-gap-acquisition
description: Use when a research or evaluation case fails because required source material, terms, axes, sections, or provenance are missing and Codex must triage the gap, generate a Hermes-facing source acquisition task, validate usable vs rejected sources, and prepare a later Codex intake/formal-ready/handoff contract without running controlled execution or updating baselines.
metadata:
  status: draft
  hidden: true
  executor: codex-hermes-split
  purpose: reusable source/material-gap acquisition workflow before Codex intake and formal handoff
---

# Source Gap Acquisition Workflow

## Purpose

Use this skill to turn a source or material gap into a controlled acquisition package. The workflow separates diagnosis, Hermes source acquisition, source validation, and Codex intake handoff. It is not a repair runner and it is not a baseline-update workflow.

## When To Use

Use when a case fails because required evidence is missing or weak:

- missing required terms, axes, sections, source-backed body, or provenance
- local inventory may already contain usable material but readiness is unknown
- Hermes needs a precise source acquisition prompt
- Codex later needs a validated input contract for intake, readiness, formal-ready review, or handoff
- adversarial or malformed-token cases need a policy gate before acquisition

## When Not To Use

Do not use this skill when the blocker is primarily:

- code, runner, harness, CLI, runtime metadata, production target, or manifest loader failure
- scoring policy disagreement without a material gap
- official baseline writing or candidate rerun
- controlled execution, production integration, vector index writing, or source data mutation by Codex
- a case where the exact prompt, missing terms, or missing axes cannot be recovered and no uncertainty caveat is allowed

## Executor Split

- Codex owns and maintains this skill.
- Hermes executes source acquisition when explicitly authorized.
- Codex consumes Hermes outputs later for local intake, readiness review, formal-ready review, and handoff.
- Hermes must not modify the repo, run vectorization, run formal-ready, run controlled execution, or update baselines.
- Codex must not perform acquisition during a skill-creation or planning task unless explicitly authorized in a separate task.

## Source Gap Triage

Before acquisition, prove the blocker is a material/source gap:

1. Read the latest failed-case review, candidate matrix, human review, and source inventory reports.
2. Extract exact case prompt, missing terms, missing axes, missing sections, banned terms, current fail reason, and caveats.
3. Classify blocker type: `SOURCE_GAP`, `MATERIAL_GAP`, `PROVENANCE_GAP`, `POLICY_GATED`, `CODE_OR_RUNNER_GAP`, `SCORING_GAP`, or `UNCERTAIN`.
4. Stop if the blocker is code/runtime/scoring-only. Do not mask non-source problems with acquisition.
5. Stop if exact case prompt or required terms are unavailable and acquisition would rely on guessing.

## Required Input Reports

Prefer these inputs when available:

- official case dataset or case registry
- failed-case review
- candidate delta matrix
- human review notes
- current baseline or release scope manifest
- local source inventory scan
- previous acquisition validation reports
- policy report for adversarial or malformed-token cases

## Prompt And Gap Extraction Rules

- Must not guess prompt, missing terms, missing axes, or missing sections.
- Preserve original spelling, diacritics, aliases, trap terms, and malformed tokens.
- Separate legitimate domain topics from contaminated surface terms.
- Preserve banned terms and source-type exclusions.
- Record uncertainty explicitly instead of filling missing fields from inference.

## Local Source Inventory Scan

Scan local source roots before asking Hermes for acquisition. Record:

- existing candidate paths
- source type and file size
- readability and text extractability
- obvious bad signals: README, Cloudflare/interstitial, title-only, generated summary, locator-only, listing/noise
- whether available material is enough for intake: `true`, `false`, or `uncertain`

The inventory scan is read-only. It must not normalize, chunk, vectorize, delete, move, or rewrite source files.

## Acquisition Eligibility

Proceed to Hermes acquisition only when:

- the blocker is a real source/material/provenance gap
- exact prompt and required gaps are known
- local inventory is insufficient or needs external/source-finding completion
- policy-gated cases have an explicit policy defining allowed normalization and source admissibility

Do not proceed when the case requires human policy confirmation first, uses ambiguous aliases without policy, or would require booking/listing pages as concept evidence.

## Usable Source Criteria

A usable source must include:

- readable source-backed body
- stable file path and source hash
- source origin and source type
- support for one or more required terms, axes, or sections
- clear caveats for locator-only, context-only, ZIM/wiki/API, or supplementary sources
- no overclaim beyond the source role

## Rejected Source Criteria

Reject or quarantine:

- Cloudflare/interstitial pages
- README or generated summaries
- title-only, very short, citation-only, or query-echo files
- wrong-context or wrong-domain sources
- booking, ticket, hotel, restaurant, map, price-list, or listing pages unless explicitly allowed as locator-only
- sources that only support a banned term or contaminated surface
- open/context evidence being overclaimed as a dedicated professional book/PDF axis

## Adversarial / Malformed Token Policy Gate

For malformed, adversarial, typo, alias, trap, booking, ticket, or listing-overfit cases:

1. Define the normalization policy before acquisition.
2. State what must not be normalized into a fake entity.
3. State what source types are admissible, supplementary, locator-only, or rejected.
4. Define pass, partial, blocked, invalid-source, and overclaim conditions.
5. Stop ordinary acquisition if the policy is absent.

## Output Directory Convention

Use explicit repo-outside output directories for reports. For acquired or found raw/context files, use the project-approved data root and case-specific raw/context directory only when the user authorizes acquisition.

Recommended report package:

- `<case_id>_case_prompt_and_gap_extraction.md`
- `<case_id>_downloaded_or_found_file_manifest.json`
- `<case_id>_usable_source_validation.json`
- `<case_id>_rejected_source_validation.json`
- `<case_id>_source_acquisition_report.md`
- `<case_id>_source_acquisition.json`
- `<case_id>_next_intake_ready_file_list.md`

## Per-Case Validation Contract

For each source candidate, record:

- `case_id`
- `source_file`
- `source_origin`
- `source_type`
- `source_hash`
- `file_size`
- `readable`
- `text_extractable`
- `is_cloudflare_or_interstitial`
- `is_readme_summary`
- `title_only`
- `very_short`
- `generated_summary`
- `has_source_backed_body`
- `supports_required_terms`
- `supports_required_axes`
- `supports_required_sections`
- `usable_or_rejected`
- `rejection_reason`
- `caveats`

## Batch Manifest Contract

A batch manifest must include:

- batch id and project name
- case ids and per-case status
- exact prompts and extracted gaps
- raw/context output roots
- usable source count and rejected source count per case
- per-case readiness decision
- source acquisition blockers
- next Codex intake readiness queue
- confirmation that no repo, vector, production, formal-ready, controlled execution, or baseline action was performed

## Codex Intake Handoff Contract

Hermes outputs are not controlled evidence. Codex must later run a separate local intake task that:

- reads Hermes reports and raw/context files
- validates source-backed bodies again
- normalizes, chunks, and sandbox-vectorizes only if authorized
- runs readiness and formal-ready review
- creates controlled handoff only after approval
- stops on invalid, weak, or policy-violating sources

## Hard Prohibitions

- Do not run controlled execution.
- Do not run official candidate rerun.
- Do not update official baseline or ledger.
- Do not modify production target/runtime metadata.
- Do not write production vector index.
- Do not treat locator-only, booking, ticket, or listing pages as concept evidence unless an explicit policy permits locator-only use.
- Do not count generated summaries, README files, title-only pages, or Cloudflare/interstitial pages.
- Do not hard-code one case's answer into the workflow.

## Final Status Enums

Use these generic decisions:

- `SOURCE_GAP_ACQUISITION_READY`
- `SOURCE_GAP_LOCAL_INVENTORY_SUFFICIENT`
- `SOURCE_GAP_NEEDS_HERMES_ACQUISITION`
- `SOURCE_GAP_POLICY_GATED`
- `SOURCE_GAP_NEEDS_EXACT_PROMPT`
- `SOURCE_GAP_NEEDS_HUMAN_CONFIRMATION`
- `SOURCE_GAP_BLOCKED_NOT_A_SOURCE_PROBLEM`
- `SOURCE_GAP_BLOCKED_INVALID_SOURCE`
- `SOURCE_GAP_READY_FOR_CODEX_INTAKE`
- `SOURCE_GAP_PARTIAL_NEEDS_MORE_MATERIAL`

## Examples Only

Travel / Series B examples are illustrative only:

- `cross_route_053`: a successful acquisition after karst/hydrology and chultun/cistern/swamp gaps; rejected locator-only sources were not counted as formal axis evidence.
- `adv_trap_059`: a malformed-token/listing-noise case that required adversarial normalization policy before acquisition.
- A six-case batch can be handled by a batch prompt, but Codex intake must remain a separate later task.

Do not treat example baselines, case ids, or source paths as fixed assumptions for other projects.

## Failure Behavior

Fail closed. If evidence is ambiguous, policy is missing, local files are weak, or acquisition could admit contaminated sources, report the blocker and stop. A partial acquisition is acceptable; an overclaimed pass is not.
