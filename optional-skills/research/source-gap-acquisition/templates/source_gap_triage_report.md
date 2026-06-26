# Source Gap Triage Report Template

status: <PASS | PARTIAL | BLOCKED>
project_name: <project>
case_id: <case_id>

## Blocker Classification

material_gap_vs_code_runtime_policy: <SOURCE_GAP | MATERIAL_GAP | PROVENANCE_GAP | POLICY_GATED | CODE_OR_RUNNER_GAP | SCORING_GAP | UNCERTAIN>
current_fail_reason: <reason>
not_a_source_gap_reason: <reason or none>

## Case Contract

exact_case_prompt: <prompt or ADV_NEEDS_EXACT_CASE_PROMPT>
missing_terms:
- <term>
missing_axes:
- <axis>
missing_sections:
- <section>
banned_or_rejected_terms:
- <term>
caveats:
- <caveat>

## Local Source Signals

existing_source_found: <true | false | uncertain>
candidate_paths:
- <path>
obvious_bad_signals:
- <README | Cloudflare | title_only | generated_summary | locator_only | listing_noise | wrong_context>

## Acquisition Readiness

source_acquisition_readiness: <READY | PARTIAL | BLOCKED>
policy_gate_decision: <not_required | required_missing | policy_defined>
hermes_acquisition_recommended: <true | false>
codex_local_intake_can_start_now: <true | false>

## Next Action

recommended_next_action: <action>
stop_reason_if_blocked: <reason>
