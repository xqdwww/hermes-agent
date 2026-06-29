---
name: research-decision-topic-refinement-loop
description: Use when a Research/Decision first-pass final, quality review, or user feedback shows the same topic needs targeted refinement rather than a full rerun.
---

# Research/Decision Topic Refinement Loop

Use this as an operator skill. It does not integrate with runtime, change the main pipeline, or modify final controller, evidence packet, convergence, or calibration code. For design rationale, read `references/external_pattern_review.md`.

## Purpose

- Treat the first-pass final as a draft, not the endpoint.
- Use the loop shape `first_pass_final -> feedback -> refinement -> quality review -> revised_final`.
- Convert quality review into a concrete next action.
- Prefer section-level or stage-level targeted continuation.
- Do not treat full rerun as default.
- Preserve the same topic context, artifacts, caveats, and evidence boundaries.

## Trigger / When to use

Use when the user says "not satisfied", "too templated", "not specific enough", "continue this topic", "only fill this part", or "rewrite part N".

Use when final quality review shows `template_like_final`, `low_specificity`, `calibration_absorption_gap`, `convergence_to_final_specificity_loss`, `missing_section`, `weak_priority_ranking`, `evidence_gap`, `thin evidence`, or a same-topic request for deeper answer.

Use when the pipeline completed but the final is not good enough and the user wants improved output, not fresh full research.

## When not to use

- DDGS, OMLX, executor, dependency, or resource blockers.
- Wrong branch, branch-head mismatch, dirty worktree, or dirty scope.
- `evidence_judge` resource exhausted.
- User changed topic or asks for blind validation.
- Source materials are stale or missing and acquisition must happen first.
- Safety or policy issue requires refusal or separate handling.

## Required inputs

- `topic_id` or `run_id`
- `original_user_question`
- `first_pass_final`
- `case_quality_review` or `final_quality_gate` result
- `convergence_report`
- `calibration_report`
- `research_evidence_packet`, if available
- `user_feedback`
- known blockers / environment status
- current allowed scope

## topic_refinement_state

Maintain this state for each topic:

```yaml
topic_refinement_state:
  topic_id:
  original_question:
  current_final_version:
  final_versions:
    final_v1:
    refinement_v1:
    revised_final_v2:
  artifact_paths:
  quality_failures:
  user_feedback:
  refinement_history:
  prior_failure_types:
  preserved_caveats:
  unresolved_evidence_gaps:
  iteration_count:
  next_action:
  stop_reason:
```

Never overwrite a previous final. Append each refinement as a new version such as `final_v1`, `refinement_v1`, and `revised_final_v2`, and record the changed sections plus what stayed unchanged. Keep short-term feedback scoped to this topic state; do not write it to global or long-term memory by default.

## Failure taxonomy

- `final_template_fallback`
- `low_domain_specificity`
- `missing_user_obligation`
- `weak_priority_ranking`
- `generic_topn_items`
- `calibration_absorption_gap`
- `convergence_to_final_specificity_loss`
- `evidence_gap_needs_acquisition`
- `evidence_gap_needs_full_text_verification`
- `thin_evidence_must_remain_conditional`
- `raw_internal_metadata_leakage`
- `wrong_domain_or_stale_output`
- `executor_or_environment_blocker`
- `user_feedback_requests_deeper_specificity`

## Failure-to-next-action mapping

| failure_type | next action |
| --- | --- |
| `final_template_fallback` | Run `section_rewrite` or `final_absorption_pass`; do not restart the full topic. |
| `low_domain_specificity` | Require concrete domain units, examples, triggers, counter-signals, and decision implications. |
| `missing_user_obligation` | Answer only the missing obligation, then merge it into the current final. |
| `weak_priority_ranking` | Reconstruct ranking from explicit decision criteria, tradeoffs, and evidence strength. |
| `generic_topn_items` | Replace generic items with distinct topic-grounded items and reasons. |
| `calibration_absorption_gap` | Rerun final absorption using calibration; do not start new evidence search. |
| `convergence_to_final_specificity_loss` | Rebuild final from convergence judgments, not from loose question anchors. |
| `evidence_gap_needs_acquisition` | Do targeted source acquisition or full-text verification before rewriting. |
| `evidence_gap_needs_full_text_verification` | Verify full text before upgrading any claim; snippets are insufficient. |
| `thin_evidence_must_remain_conditional` | Preserve caveats and do not upgrade thin evidence. |
| `raw_internal_metadata_leakage` | Clean up or regenerate user-facing final; do not redo research. |
| `wrong_domain_or_stale_output` | Stop and rerun from domain-anchor guard if authorized. |
| `executor_or_environment_blocker` | Run environment triage; do not repair prompts or rewrite answers. |
| `user_feedback_requests_deeper_specificity` | Restate feedback and refine only the requested area. |

## Selection tie-breaker

Use this order when failures overlap:

1. Environment, dependency, branch/head, dirty scope, missing artifacts, or unauthorized acquisition -> stop or `environment_triage`; do not rewrite the answer.
2. Topic changed, domain is wrong, or sources are stale/missing -> stop; full rerun is only allowed after explicit authorization.
3. Evidence gap or full-text verification gap affects a claim -> `targeted_evidence_acquisition` if authorized; otherwise stop or keep the claim conditional.
4. Calibration/convergence is present but not absorbed across the final -> `final_absorption_pass`.
5. Only one section is weak or missing -> `section_rewrite`.
6. User feedback requests deeper specificity -> `user_feedback_refinement`, bounded by evidence and artifact constraints.

When `section_rewrite` and `final_absorption_pass` both seem possible, choose `section_rewrite` for local defects and choose `final_absorption_pass` for whole-final failures in calibration, convergence, confidence, or decision boundaries.

## Refinement modes

### section_rewrite

- Rewrite only low-quality sections.
- Do not change unrelated sections.
- Preserve evidence boundaries and caveats.
- Output a before/after diff summary.

### final_absorption_pass

- Rebuild the final from convergence and calibration.
- Do not redo evidence acquisition.
- Improve specificity and calibration absorption.

### targeted_convergence_refinement

- Use when convergence lacks judgment units such as PMF signals, evidence boundaries, or stop/pause conditions.
- Do not use for final style or tone problems.

### targeted_evidence_acquisition

- Use when a true evidence gap changes the conclusion.
- Mark the exact source need.
- Do not treat snippets as full-text verification.
- Require authorization before acquisition or full-text verification.
- If acquisition is unavailable, stop or write only a conditional rewrite that preserves the evidence gap.

### user_feedback_refinement

- Use when the user identifies a specific dissatisfaction.
- Restate the feedback before editing.
- Modify only the relevant part unless the user asks for wider revision.
- User preference can change emphasis, ordering, and specificity, but cannot override evidence boundaries or make thin evidence stronger.

### environment_triage

- Use for DDGS, OMLX, dependency, executor, or resource issues.
- Do not rewrite the answer while the environment blocker is unresolved.
- Do not treat environment blockers as prompt repair or answer quality failures.

## Confidence and evidence rules

- Confidence cannot increase without new evidence or stronger artifact support.
- Thin evidence must remain conditional.
- Calibration can decrease or qualify confidence without new evidence.
- Full-text verification is required before upgrading snippet-only support.
- User feedback cannot remove caveats, erase uncertainty, or strengthen unsupported claims.

## Refinement workflow checklist

- [ ] Load `topic_refinement_state`.
- [ ] Verify branch/head/worktree if repo work is involved.
- [ ] Read `refinement_history` and prior failure types before choosing the next action.
- [ ] Classify failure.
- [ ] Choose the minimal refinement mode.
- [ ] Preserve artifacts and caveats.
- [ ] Perform refinement.
- [ ] Run quality review.
- [ ] Run the output quality gate.
- [ ] Update `topic_refinement_state`.
- [ ] Append the revised final as a new version; do not overwrite previous final text.
- [ ] Write what changed / what did not change.
- [ ] Decide next action.

## Refinement output contract

Each refinement must output:

- `refinement_scope`
- `failure_type`
- `selected_refinement_mode`
- `previous_final_version`
- `new_final_version`
- `preserved_artifacts`
- `changed_sections`
- `new_or_reused_evidence`
- `source_need`
- `confidence_changes`
- `revised_final`
- `caveats_preserved`
- `what_was_not_changed`
- `output_quality_gate`
- `next_recommended_action`

## Output quality gate

Before accepting a refinement, check:

- changed sections are traceable to the selected failure type.
- unchanged sections are named and intentionally preserved.
- `new_or_reused_evidence` states whether evidence was reused, newly acquired, or unavailable.
- `confidence_changes` states no increase unless new evidence or stronger artifact support exists.
- caveats and thin-evidence boundaries are preserved.
- the same failure did not repeat without improvement.

## Stop conditions

Stop and ask before continuing when:

- dirty worktree, staged files, or dirty scope appears.
- branch-head mismatch or wrong branch appears.
- required artifacts are missing.
- source acquisition is required but not authorized.
- full-text verification is required but unavailable.
- DDGS, OMLX, dependency, executor, or resource blocker appears.
- user changed topic.
- the same failure repeats after two refinement attempts.
- quality review shows no material improvement after two attempts.
- user feedback conflicts with evidence boundaries.
- proposed change would alter runtime, tools, final controller, evidence packet, convergence, or calibration.
- output would require unsupported inference or speculation.

## Anti-patterns

- Treating full rerun as the default action.
- Overwriting an old final with a new final without recording changes.
- Replacing `final_v1` instead of appending `revised_final_v2`.
- Deleting caveats to sound more certain.
- Upgrading thin evidence into strong evidence.
- Increasing confidence without new evidence or stronger artifact support.
- Changing headings while leaving generic content intact.
- Adding more anchors instead of improving reasoning.
- Hard-coding case-specific answers.
- Letting Travel-specific route/place logic leak into Research core.
- Treating environment failure as an answer quality issue.
- Treating environment failure as prompt repair.
- Letting user feedback override evidence boundaries.
- Running an infinite self-reflection loop without external signal.
- Passing only by self-score with no artifact-backed review.
- Claiming this operator is already connected to runtime.

## Example workflows

- case03 architecture final too generic -> classify `low_domain_specificity`; use `section_rewrite` or `final_absorption_pass`; add concrete architecture units, triggers, and counter-signals without inventing new evidence.
- case05 travel priority copied prompt order -> classify `weak_priority_ranking`; use `section_rewrite`; rebuild priority from decision criteria and tradeoffs without adding route/place logic to Research core.
- case06 education research support too generic -> classify `calibration_absorption_gap`; use `final_absorption_pass`; preserve claim-bound caveats and do not upgrade thin evidence.
- case04 business convergence missing PMF signals -> classify `convergence_to_final_specificity_loss`; use `targeted_convergence_refinement`; add missing PMF signals, evidence boundaries, and stop/pause conditions before final rewrite.
- User says "继续这个话题，把第 2 部分做实" -> classify `user_feedback_requests_deeper_specificity`; use `user_feedback_refinement`; restate the request and revise only section 2.

## Handoff prompt template

```text
Use the Research/Decision topic refinement loop operator.

Current topic artifacts:
- topic_id or run_id:
- original_user_question:
- first_pass_final:
- final_versions / refinement_history:
- case_quality_review or final_quality_gate:
- convergence_report:
- calibration_report:
- research_evidence_packet:
- user_feedback:
- known blockers / environment status:

Failure type:
Desired refinement mode:
Constraints:
- Preserve artifacts, caveats, and evidence boundaries.
- Do not default to a full rerun.
- Do not change runtime, tools, final controller, evidence packet, convergence, or calibration.
- No code change unless explicitly authorized.
- Allowed files:
- Output paths:

Return:
- refined section or revised final
- quality review
- topic_refinement_state update
- output quality gate
- summary of what changed and what did not change
```
