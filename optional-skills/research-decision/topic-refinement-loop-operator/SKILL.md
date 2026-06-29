---
name: research-decision-topic-refinement-loop
description: Use when a Research/Decision first-pass final, quality review, or user feedback shows the same topic needs targeted refinement rather than a full rerun.
---

# Research/Decision Topic Refinement Loop

Use this as an operator skill. It does not integrate with runtime, change the main pipeline, or modify final controller, evidence packet, convergence, or calibration code. For design rationale, read `references/external_pattern_review.md`.

## Purpose

- Treat the first-pass final as a draft, not the endpoint.
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
  artifact_paths:
  quality_failures:
  user_feedback:
  refinement_history:
  preserved_caveats:
  unresolved_evidence_gaps:
  next_action:
  stop_reason:
```

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

### user_feedback_refinement

- Use when the user identifies a specific dissatisfaction.
- Restate the feedback before editing.
- Modify only the relevant part unless the user asks for wider revision.

### environment_triage

- Use for DDGS, OMLX, dependency, executor, or resource issues.
- Do not rewrite the answer while the environment blocker is unresolved.

## Refinement workflow checklist

- [ ] Load `topic_refinement_state`.
- [ ] Verify branch/head/worktree if repo work is involved.
- [ ] Classify failure.
- [ ] Choose the minimal refinement mode.
- [ ] Preserve artifacts and caveats.
- [ ] Perform refinement.
- [ ] Run quality review.
- [ ] Update `topic_refinement_state`.
- [ ] Write revised final.
- [ ] Write what changed / what did not change.
- [ ] Decide next action.

## Refinement output contract

Each refinement must output:

- `refinement_scope`
- `failure_type`
- `selected_refinement_mode`
- `preserved_artifacts`
- `changed_sections`
- `new_or_reused_evidence`
- `confidence_changes`
- `revised_final`
- `caveats_preserved`
- `what_was_not_changed`
- `next_recommended_action`

## Stop conditions

Stop and ask before continuing when:

- dirty worktree, staged files, or dirty scope appears.
- branch-head mismatch or wrong branch appears.
- required artifacts are missing.
- source acquisition is required but not authorized.
- full-text verification is required but unavailable.
- DDGS, OMLX, dependency, executor, or resource blocker appears.
- user changed topic.
- proposed change would alter runtime, tools, final controller, evidence packet, convergence, or calibration.
- output would require unsupported inference or speculation.

## Anti-patterns

- Treating full rerun as the default action.
- Overwriting an old final with a new final without recording changes.
- Deleting caveats to sound more certain.
- Upgrading thin evidence into strong evidence.
- Changing headings while leaving generic content intact.
- Adding more anchors instead of improving reasoning.
- Hard-coding case-specific answers.
- Letting Travel-specific route/place logic leak into Research core.
- Treating environment failure as an answer quality issue.
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
- summary of what changed and what did not change
```
