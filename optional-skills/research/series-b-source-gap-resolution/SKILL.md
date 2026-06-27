---
name: series-b-source-gap-resolution
description: Gate Series B source-gap manifests.
version: 0.2.0
status: draft
hidden: true
executor: codex
purpose: resolve Series B hard-mode source/term/axis/provenance gaps through gated case-scoped workflow
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    status: draft
    hidden: true
    executor: codex
    category: research
    activation: explicit-only
    purpose: resolve Series B hard-mode source/term/axis/provenance gaps through gated case-scoped workflow
    tags: [series-b, source-gap, provenance, manifest, touched-eval, codex]
    related_skills: [llm-wiki, systematic-debugging]
---

# Series B Source Gap Resolution

This hidden draft skill is a Hermes shell for Series B hard-mode source gaps. It tells Hermes to treat these requests as gated, case-scoped source evidence workflows, not as ordinary Codex code repair tasks.

Historical note: this skill began when the official frozen Series B score was around `31/60`. Do not treat that historical score as current state. Current tasks may have later official baselines, including a post-60 state; always read the repo's official baseline and runtime metadata before acting.

Passing examples below are case-scoped approved-manifest harness passes only unless a separate candidate rerun, human review, official baseline write, runtime metadata update, smoke, and backup have already occurred. They are not production-default improvements, and the production builder does not automatically read these manifests.

## Post-60 Safety Boundary

If the project is already at a human-reviewed `60/60` official baseline with runtime metadata aligned, this skill is for audit, documentation, regression-test, or safety-rule hardening only unless the user explicitly opens a new validation scope. Do not chase more cases, run controlled execution, run candidate reruns, update official baseline files, update production metadata, push, tag-push, or release from this skill.

A final `60/60` result remains caveated. Preserve alias caveats, policy-constrained malformed-token caveats, anti-overclaim caveats, source-backed-body requirements, rejected-source exclusion, and candidate-only vs official-baseline separation in all reports.

## Trigger Conditions

Use this skill only when the user explicitly asks for Series B source-gap, professional-source, provenance, approved-manifest, or touched-case evidence work.

Strong triggers include:

- A named Series B case such as `nat_eco_039`, `obj_art_010`, or `hist_arch_024`.
- `missing_required_term`, `missing_required_axis`, or source-axis binding failures.
- A local professional source candidate that needs provenance, chunk, axis, or manifest review.
- A request to run a touched-case controlled eval from a case-scoped approved manifest.
- Open evidence, Wiki, ZIM, or API results being used only to anchor terms, disambiguate entities, or discover source leads.

Accept invocation phrases such as:

- `用 series-b-source-gap-resolution 处理 hist_arch_024`
- `只走 source-gap workflow，不修 builder`
- `给 obj_art_010 做 two-source approved manifest touched eval`

## Non-goals / Refusal Conditions

Refuse or redirect any attempt to use this skill for general repairs.

Do not:

- Modify the LonglyPlanet builder, audit, scoring, gate, cap, dataset, or source tables.
- Enable active P3 or public-retention repair paths.
- Run full Series B before local touched-case guardrails pass.
- Ingest, reindex, rebuild OCR, generate embeddings, download, scrape, buy, or copy new materials unless a later task explicitly authorizes that specific stage.
- Promote Wiki, ZIM, API, or other open evidence into a professional source axis.
- Treat `qyer`, `local_travel`, tourism, listing, current, or practical sources as satisfying `history_book`, `archaeology_book`, `art_architecture_book`, `nature_book`, `geography_book`, or `materials_book`.
- Let `food_book` metadata noise satisfy unrelated axes.
- Convert a passing case into a broad rule, alias, profile, or production default.

## Workflow Stages

Run one case at a time and stop at the first blocked gate.

1. Build the residual failure profile: exact term, required axis, current failure, forbidden axes, and expected source type.
2. Select source leads: local professional sources first; open evidence only for term anchoring, disambiguation, and source discovery.
3. Check term/context evidence: exact hit, object/context hit, chunk, page/chapter/heading, source path, authority, source_id, and axis.
4. Classify false positives and noisy evidence before accepting anything.
5. Pass the provenance gate before any approved manifest or touched eval.
6. Generate a case-scoped approved manifest with `production_default: false` and `case_scope_only: true`.
7. Run only the touched case in a controlled harness.
8. Report the final decision and stop. Do not continue to other cases without a new explicit user request.

## Provenance Gate

Human provenance/license confirmation is mandatory before approved manifest or touched-case controlled eval.

The provenance record must include:

- ownership or license status
- acquisition note or receipt path, if available
- original source file path, if available
- allowed use scope
- reviewer and review date
- source authority id and source id
- source path and source SHA-256
- case scope
- allowed axes and forbidden axes
- production use status

Allowed decisions:

- `PROVENANCE_CONFIRMED_READY_FOR_INGEST_PREP`
- `PROVENANCE_RECORD_INCOMPLETE_NEEDS_USER_DETAIL`
- `PROVENANCE_REJECTED_DO_NOT_USE`

## Approved Manifest Requirements

An approved manifest is evidence for one controlled case only. It must not be wired into the production default path by this skill.

Required fields:

- `case_id`
- `source_title`
- `source_authority_id`
- `source_id`
- `source_path`
- `source_sha256`
- `ownership_or_license_status`
- `review_date`
- `reviewer`
- `allowed_use_scope`
- `accepted_chunk_id` or case-specific accepted chunk list
- `accepted_axes`
- `forbidden_axes`
- `exact_term`
- `context_terms`
- `public_hygiene: clean`
- `production_default: false`
- `case_scope_only: true`
- `human_review_required: true` unless the current task explicitly records completed review

Reject the manifest if it requires source table writes, production builder wiring, open-evidence axis promotion, or non-case-scoped behavior.

## Single-Source Pattern

Use this pattern when one professional source can cover the required term and all required professional axes for one case.

Checklist:

- The source is local, legally/provenance confirmed, and stable by path and hash.
- The accepted chunk contains the exact term in the required domain context.
- The source axis matches the case, and noisy axes such as `food_book` are excluded.
- A touched-case eval can read the case-scoped manifest without production table writes.

Example pattern: `nat_eco_039` used `Glaciers and Glaciation` for `overdeepening` with `nature_book` and `geography_book`; the case-scoped accepted-manifest touched eval passed.

## Multi-Source / Multi-Axis Pattern

Use this pattern when a case needs different sources for different required axes or when one source should not be stretched across axes.

Checklist:

- Each source has its own role, authority, source_id, chunk evidence, allowed axis, and forbidden axes.
- The exact term source does not automatically satisfy a separate historical, archaeological, material, nature, or geography axis.
- The manifest explains why multiple sources are needed and keeps all sources case-scoped.
- The touched eval verifies that all required axes remain bound and no wrong-axis satisfaction appears.

Example pattern: `obj_art_010` used `Japanese Woodblock Prints` for `kento/kentō` plus `art_architecture_book`, and `Edo Culture` for the secondary `history_book` axis; the two-source controlled touched eval passed.

## Term Disambiguation / False-Positive Pattern

Use this pattern when a term has strong wrong-domain meanings.

Checklist:

- Define accepted context terms before searching.
- Define rejected context terms before searching.
- Quarantine false positives from open evidence and local sources.
- Accept only professional-source chunks whose context matches the case contract.

Example pattern: `hist_arch_024` resolved `fauces` as Roman domestic architecture, rejecting medical/anatomy/throat meanings; `Herculaneum: Past and Future` supplied the professional archaeology/history evidence and the controlled touched eval passed.

## Codex Handoff Template

When Hermes hands this to Codex, use this shape and keep the locks intact:

```text
Use hidden draft skill shell `series-b-source-gap-resolution`.

Case:
- case_id: <case_id>
- missing_required_term: <term and variants>
- missing_required_axis: <axis or axes>
- current_failure_reason: <reason>
- candidate_local_source: <title/path/source_id/chunk_id or none>
- expected_professional_source_type: <type>

Locks:
- One case only.
- Do not modify builder, audit, scoring, gate, cap, dataset, or source tables.
- Do not ingest/reindex, OCR, generate embeddings, or run full Series B.
- Do not enable P3.
- Do not use Wiki/ZIM/open evidence as a professional axis.
- Exclude qyer/local_travel from professional axes.
- Exclude food_book noise unless the case explicitly requires food_book.
- Require human provenance confirmation before approved manifest or touched eval.
- Stop after the requested stage and write Markdown/JSON outputs.

Requested stage:
<source acceptance prep | provenance record | approved manifest | touched-case controlled eval | final decision>
```

## Output / Acceptance Criteria

Every run must write stage-specific Markdown and JSON artifacts under an explicit `outputs/<case_or_stage>/` directory.

A touched-case pass requires:

- missing exact term resolved
- required professional axis or axes bound correctly
- forbidden axes excluded
- no public, listing, current, practical, tourism, qyer, or local-travel pollution
- no Wiki/ZIM/open evidence promoted to professional axis
- no wrong-axis satisfaction
- remaining quality failure, if any, explained as a separate blocker

Do not claim official Series B pass-count improvement from a touched-case manifest pass.

## Production Integration Boundary

This skill does not design or implement production integration.

Production builder integration requires a separate design review covering manifest loader scope, source authority overlay behavior, source table write policy, regression suite, public hygiene guardrails, and rollback. Until that review passes, approved manifests stay outside production-default behavior.

Full Series B should run only after local touched-case guardrails pass and the user explicitly authorizes a broader controlled regression.

## Known Passing Examples

These are compact patterns, not hard-coded repair rules.

| Case | Pattern | Term | Professional source | Accepted axis or axes | Result |
| --- | --- | --- | --- | --- | --- |
| `nat_eco_039` | Single-source nature/geography | `overdeepening` | `Glaciers and Glaciation` | `nature_book`, `geography_book` | Accepted manifest controlled touched eval PASS. |
| `obj_art_010` | Two-source multi-axis | `kento/kentō` | `Japanese Woodblock Prints`; `Edo Culture` | `art_architecture_book`; `history_book` | Two-source controlled touched eval PASS. |
| `hist_arch_024` | Disambiguation / false-positive rejection | `fauces` | `Herculaneum: Past and Future` | `archaeology_book` | Architectural fauces controlled touched eval PASS. |

Remember: these three passing cases are historical case-scoped harness evidence. They do not by themselves change any official Series B score, and they do not prove the production builder reads approved manifests. Official movement requires separate candidate rerun, human review, baseline write, runtime metadata alignment, smoke, and backup with caveats preserved.
