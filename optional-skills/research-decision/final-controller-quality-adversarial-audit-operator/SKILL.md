---
name: research-decision-final-controller-quality-adversarial-audit-operator
description: Use for adversarial audit of Hermes Research/Decision final-controller answers, source diffs, quality gates, and tests before repair, commit review, or release readiness.
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
    tags: [research-decision, final-controller, adversarial-audit, evidence-calibration, product-quality]
---

# Research/Decision Final Controller Quality Adversarial Audit Operator

## purpose

Use this skill to review Research/Decision final-controller output as a user-facing product answer. The audit must begin from raw artifacts, raw final text, raw source diff, and negative examples. Do not trust a self-score, a validation JSON, a generated summary, or a success label as proof of product quality.

The goal is not to prove the hardening correct. The goal is to find where the answer still fails the user, where the gate can be gamed, where uncertainty was removed, or where production logic became case-specific.

## trigger conditions

Use this skill when the task asks for:

- Final-controller report quality review.
- Adversarial audit before commit or release.
- Repair review after final-controller hardening.
- Checking whether a final answer absorbed convergence and calibration artifacts.
- Checking whether evidence strength, caveats, contradictions, and missing considerations are represented correctly.
- Verifying that a quality gate resists obvious score gaming.
- Distinguishing product-quality pass from engineering robustness.

Do not use this skill to rubber-stamp a generated PASS label, to skip raw diff review, or to replace manual review with a gate score.

## core audit memory

- 不要相信自评分: self-scores, generated summaries, and gate JSON are audit targets, not audit evidence.
- Do not trust final_quality_gate_after.json valid=true.
- Do not trust PASS_HARDENING_COMPLETE.
- Do not trust self-scored PASS reports.
- Treat those as objects to audit, not evidence of quality.
- production 不能知道 golden case: diagnostic cases may live in tests or fixtures, but production final-controller logic must remain generic and input-driven.

`final_quality_gate_after.json valid=true`, `PASS_HARDENING_COMPLETE`, and self-scored PASS reports can be read only as audit materials. They cannot be used as the basis for commit, tag, or PASS decisions. A final-controller change may enter commit review only when raw final text, raw source diff, mutation tests, generic non-golden cases, broad selector results, and manual/adversarial audit all pass together.

This is the golden-case policy for this skill: a fixture can prove generic behavior, but it must not create a production branch, prompt template, or generated-answer shortcut.

## required inputs

Collect the current-run inputs before judging quality:

- Original user question or task prompt.
- Research evidence packet, if present.
- Convergence report.
- Calibration report and adjustment recommendations.
- Final-controller report.
- Stage summaries or StageRecords needed to prove artifact provenance.
- Source diff for any final-controller, quality-gate, prompt, or test changes.
- Test results, including broad selectors and adversarial selectors when applicable.
- Allowed files and explicit commit, push, tag, or no-commit instruction.

If the final answer cannot be tied to current-run artifacts, stop. A fluent answer without provenance is not acceptable evidence.

## hard guard and scope rules

Before audit, run normal repository guards: expected branch, expected HEAD, tracked diff, staged diff, and allowed file scope. Stop if unrelated tracked changes exist or if staged files are present without explicit approval.

During this skill:

- Do not commit, push, merge, tag, or stage files unless the user gives a separate explicit instruction.
- Do not modify production code unless the task is explicitly a repair task.
- Do not modify tests to weaken assertions.
- Do not treat skipped required tests as pass.
- Do not use output artifacts as a substitute for source diff review.
- Do not accept fixture-specific production branches, templates, or answer shortcuts.
- Do not let developer diagnostics, logs, or summaries define user-facing quality.

## product-quality contract

A final-controller answer is acceptable only when the user can use it without opening the internal artifacts. Check for these properties directly in the final text:

- It answers each explicit user question with substantive content.
- If the user lists numbered questions, each item receives a real answer, not a heading with filler.
- If the user requests Top K, there are K distinct, substantive items.
- If the user requests ordering, the answer gives an order, covers all requested objects, and explains why that order is appropriate.
- If the user requests evidence levels, key claims are tagged or described at claim level.
- It preserves relevant case anchors from the user prompt and uses them in reasoning rather than merely listing them.
- It includes uncertainty, caveats, disagreement, evidence weakness, and risk boundaries where artifacts support them.
- It distinguishes supported claims, reasonable inferences, and forward-looking hypotheses.
- It avoids medical, legal, financial, or other high-stakes overreach unless the task and evidence justify the wording.

Format completeness is not enough. Empty headings, repeated boilerplate, and generic advice are failures.

## convergence and calibration absorption

Read convergence and calibration before judging the final. The final must transform those artifacts into user-facing conclusions:

- Convergence drivers should appear as actual recommendations, tradeoffs, or risk explanations.
- Calibration caveats should narrow claims, change priorities, add uncertainty, or add explicit boundary conditions.
- External disagreement should remain visible when it affects the decision.
- Evidence gaps should be named when they change confidence.
- Missing considerations should become either new sections, caveats, or explicit non-goals.

Reject finals that merely say the calibration was considered, absorbed, implemented, or satisfied. Restating the existence of calibration is not implementation.

## raw final audit checklist

Review the final text manually before looking at any score:

- Does it answer the original question rather than the pipeline's internal goal?
- Are enumerated requirements answered one by one when present?
- Are Top K and ranking requirements satisfied with distinct items and reasons?
- Are evidence labels attached to concrete claims with enough context?
- Are speculative claims labeled as speculative rather than supported?
- Are uncertainty and caveats preserved instead of smoothed away?
- Are contradictions and risk points carried through?
- Are important missing considerations named?
- Are there empty sections, placeholder text, or repeated template paragraphs?
- Does the answer confuse calibration stage output with final-controller output?
- Does it expose internal process language in the user-facing body?

User-facing text must not read like a stage log, contract check, developer report, or model self-evaluation.

## internal-language screen

The user-facing final body should not contain internal process terms or field-style debug keys. Screen for exact terms and variants such as:

- stage output language.
- upstream or downstream report language.
- artifact or pipeline check language.
- executor, contract, or validation-gate language.
- statements that calibration was absorbed instead of implemented.
- field keys for evidence strength, controversy, or evidence gaps.

These terms can appear in diagnostic summaries, tests, logs, and audit reports. The guard applies to the final user-facing answer.

## adversarial mutation checks

Use negative and positive examples to test whether the gate can be gamed:

- Numbered-title-only: headings match the user questions but bodies are empty or generic; expected invalid.
- Anchor-stuffing: many prompt anchors are listed once, then ignored; expected invalid or quality risk.
- Calibration-restatement: the answer repeats adjustment instructions but does not change recommendations; expected invalid.
- Evidence-label-spam: labels appear repeatedly without concrete claims, mechanisms, or user actions; expected invalid.
- Internal-language-variant: exact forbidden strings are avoided, but process-flavored synonyms remain; expected invalid or quality risk.
- Generic enumerated good case: unrelated domain, multiple explicit questions, substantive answers; expected valid.
- Plain non-enumerated good case: no forced numbered structure; expected valid.
- Top K good and Top K title-only bad cases; expected valid and invalid respectively.

Passing these checks does not prove deep semantic quality. It only blocks obvious score-gaming paths.

## source diff audit

When code or tests changed, read raw diff. Confirm:

- Production logic has no fixture-specific branch, predicate, prompt template, or generated-answer shortcut.
- Case details live only in tests, fixtures, or explicit sample input.
- Query parsing, anchor extraction, Top K enforcement, ranking enforcement, calibration absorption, and evidence tagging are generic mechanisms.
- Internal-language checks apply only to user-facing final text, not to diagnostics, StageRecords, logs, tests, or developer reports.
- Router selection, model policy, bridge readiness, executor readiness, stage transition, and Research stages were not changed by a final-controller quality patch.
- The gate is not only keyword presence. It should check structure, distribution, substantive body length, non-repetition, and context where feasible.
- Large helper code remains understandable and localized. If complexity is high but acceptable, document residual risk instead of hiding it.

If the diff is too broad to audit confidently, return a blocked or repair-required result. Do not commit from uncertainty.

## stop conditions

Stop and report instead of passing when:

- The final answer is not traceable to current-run artifacts.
- The final omits explicit user requirements.
- Calibration or convergence is ignored, flattened, or merely restated.
- Speculative claims are presented as supported.
- Internal process language remains in the user-facing final.
- Negative mutation tests can pass by string gaming.
- Generic non-domain cases regress or are over-constrained by fixture-specific logic.
- Source diff changes router, executor policy, Research stages, or unrelated behavior.
- The audit cannot determine whether production logic is generic.

## report contract

An adversarial audit report should include:

- `status`
- `repo_path`
- `head`
- `branch`
- `files_reviewed`
- `raw_final_manual_review`
- `user_question_coverage_check`
- `convergence_absorption_check`
- `calibration_absorption_check`
- `evidence_and_uncertainty_check`
- `internal_language_check`
- `mutation_tests`
- `source_diff_findings`
- `generic_task_regression_risk`
- `string_gaming_risk`
- `remaining_risks`
- `required_repairs_before_commit`
- `commit_permission`

The report must distinguish useful synthesis, genuine insight, product-quality pass, and engineering robustness. A final can be useful while the gate remains heuristic. A gate can pass tests while still carrying residual semantic risk.

## anti-patterns

Reject these patterns:

- Treating a validation score as proof that the final answer is good.
- Calling basic coverage of user questions an insight.
- Calling calibration execution original thinking.
- Accepting long, polished, generic text as substantive.
- Hiding disagreement to make the final look cleaner.
- Moving case-specific answer logic into production to satisfy one diagnostic.
- Narrowing test selection after a related broad failure.
- Marking mutation tests as expected failures to avoid repair.
- Letting final-controller output imitate calibration notes or developer audit logs.

## outcome guidance

Use conservative outcomes:

- `PASS_PRECOMMIT_AUDIT` only when raw final, raw diff, generic cases, and adversarial checks all support commit review.
- `REPAIR_STILL_REQUIRED` when user requirements are missed, source logic is fixture-specific, or string gaming is obvious.
- `BLOCKED` when provenance, generic behavior, or regression risk cannot be determined.
- `DIRTY_SCOPE_REVIEW_REQUIRED` when worktree scope is wrong.

A cautious no-commit recommendation is better than a brittle pass.
