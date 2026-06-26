# Hermes Source Acquisition Prompt Template

Project: {{project_name}}
Cases: {{case_ids}}
Current baseline / reference state: {{current_baseline}}

## Input Reports

Read these case prompt / gap reports first:

{{case_prompt_gap_report_paths}}

## Local Source Roots

Read-only pre-scan roots:

{{local_source_roots}}

## Raw / Context Output Root

If acquisition is explicitly authorized, save only source raw/context files under:

{{raw_context_output_root}}

## Report Output Directory

Write all acquisition reports under:

{{report_output_dir}}

## Forbidden Actions

{{forbidden_actions}}

At minimum: do not modify the repo, do not vectorize, do not run intake, do not run formal-ready, do not run controlled execution, do not update baseline, do not write production index.

## Per-Case Procedure

For each case:

1. Extract exact prompt, missing terms, missing axes, missing sections, banned terms, and caveats.
2. Pre-scan local roots for already available material.
3. Acquire or find source-backed material only for the missing terms/axes/sections.
4. Reject Cloudflare/interstitial, README, generated summary, title-only, very short, listing/booking/ticket noise, and wrong-context sources.
5. Record usable and rejected sources separately.
6. Emit a next-intake readiness decision.

## Per-Case Final Format

{{per_case_final_format}}

Required status values:

- `PASS_READY_FOR_CODEX_INTAKE`
- `PARTIAL_NEEDS_MORE_MATERIAL`
- `BLOCKED_POLICY_GATE_REQUIRED`
- `BLOCKED_EXACT_PROMPT_MISSING`
- `BLOCKED_ONLY_INVALID_OR_LISTING_SOURCES_FOUND`
