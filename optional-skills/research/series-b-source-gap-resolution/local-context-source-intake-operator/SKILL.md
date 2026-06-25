---
name: local-context-source-intake-operator
description: Use for Series B travel background dossier cases where professional source readiness is already present but the wiki_or_zim, context_sources, or encyclopedia_context axis is missing and must be completed from local ZIM, encyclopedia, glossary, or article dumps without internet, download, generated article text, formal-ready review, controlled dry-run, or production integration.
version: 0.1.0
status: draft
owner_scope: Hermes travel Series B background dossier source-gap resolution
allowed_worktrees:
  - /Users/xqdwww/Workspace/AI_Core/hermes-agent-travel-series-b
forbidden_worktrees:
  - /Users/xqdwww/Workspace/AI_Core/hermes-agent
  - /Users/xqdwww/Workspace/AI_Core/hermes-agent-research-decision
trigger_conditions:
  - professional source and chunk readiness already exists
  - blocker is missing wiki_or_zim, context_sources, or encyclopedia_context coverage
  - local ZIM, encyclopedia, glossary, wiki export, or article dump may already exist
  - user explicitly allows local source handling
  - no internet, download, or article generation is required
non_goals:
  - formal-ready review
  - controlled dry-run
  - official baseline update
  - full Series B execution
  - production default integration
  - production vector index writes
  - commit, push, or tag creation
---

# Local Context Source Intake Operator

## 1. Purpose

Use this Skill when a Series B travel background dossier case already has professional source coverage, but still has missing `wiki_or_zim`, missing `context_sources`, or missing `encyclopedia_context`. The job is local context source extraction and readiness completion only: find existing local ZIM, encyclopedia, glossary, wiki export, HTML, Markdown, TXT, JSON, JSONL, or XML article dumps; extract real source text; normalize it; chunk it; run sandbox vectorization and guards; then decide whether the context axis is now ready for formal-ready review.

Do not use this Skill to write source content, replace missing evidence with generated text, run formal-ready review, run a controlled dry-run, update official baseline data, or connect anything to production defaults.

## 2. Trigger Conditions

Start only when all of these are true:

- The case has completed professional source and professional chunk readiness.
- The active blocker is context-axis missing evidence: `wiki_or_zim`, `context_sources`, or `encyclopedia_context`.
- The machine already has, or may already have, a local ZIM, encyclopedia, glossary, dictionary, wiki export, or article dump.
- The user explicitly allows processing local source material.
- The task needs no internet, no download, and no generated article body.

If any condition is absent, stop with `BLOCKED` and report the missing prerequisite.

## 3. Hard Boundaries

- no internet
- no download
- no LLM-generated article text
- no paraphrased encyclopedia body
- no fake ZIM/context source
- no controlled dry-run
- no formal-ready review
- no official baseline update
- no full Series B
- no production default integration
- no push
- no production vector index
- no unrelated case

Treat these as integrity boundaries. A readiness completion can only say the case is ready for the next review stage; it cannot claim a controlled pass or production readiness.

## 4. Local Source Discovery

Search only local storage and already mounted project/data paths for context sources. Candidate source types include:

- ZIM files.
- Local HTML, MD, TXT, JSON, JSONL, and XML dumps.
- Encyclopedia article exports.
- Glossary or dictionary entries.
- Local wiki exports.

For every discovered candidate that is used or rejected, record:

- discovered source path
- extraction method
- tool used
- source hash
- article title
- locator

Stop codes:

- `ZIM_FOUND_EXTRACTOR_MISSING`: a ZIM source exists, but there is no available local extractor capable of reading it.
- `CONTEXT_SOURCE_NOT_FOUND`: no local source can be found for the target context axis.
- `CONTEXT_INSUFFICIENT`: available sources are too weak, title-only, wrong-domain, listing-like, or do not cover the required target process/topic.

## 5. Extraction Rules

- Extract existing article text only.
- Preserve title.
- Preserve section headings.
- Preserve local locator.
- Preserve extraction timestamp.
- Preserve source hash.
- Do not summarize.
- Do not rewrite.
- Do not invent missing paragraphs.
- Do not replace a missing article with generated content.

The extractor may clean transport format such as HTML tags, navigation, boilerplate, or markup, but the body text must remain faithful to the local source. If an article is a redirect, record the redirect and only use the resolved article when the resolved local content is actually available.

## 6. Context Binding

Local encyclopedia and dump sources are usually not true page-bound sources. Bind them honestly:

- `CONTEXT_ENTRY_BOUND` for an article or glossary entry.
- `CONTEXT_SECTION_BOUND` for a named section inside a local entry.

Do not present local entry-bound or section-bound evidence as true page-bound evidence. Preserve the source path, article title, section heading, locator, and text hash so reviewers can re-open the local evidence.

## 7. Chunking And Vectorization

Prefer entry and section structure over arbitrary slicing. Chunking guidance:

- Keep chunks close to a single section, subtopic, or definitional unit.
- Prefer moderate chunks that preserve enough context for evidence review.
- Use small overlap only where a term or process definition crosses a boundary.
- Avoid title-only, heading-only, navigation-only, citation-only, and query-echo chunks.

Each chunk must keep:

- `source_id`
- `article_title`
- section heading
- locator
- source hash
- text hash
- binding type

Vectorization is sandbox-only. Set `production_default_enabled: false` for any candidate manifest or registry output produced by this operator. Do not write to a production index and do not integrate with any production default manifest.

## 8. Wrong-Domain And Listing Guard

Run a strict wrong-domain and listing guard before promotion. Exclude or quarantine:

- sports
- hotel
- restaurant
- ticket
- opening hours
- booking
- phone
- map
- getting around
- food/drink
- generic travel listing
- generic term without target process
- wrong-domain science term
- title-only
- query echo
- generated echo

Promotion requires real target-domain context, not a page that merely mentions a matching word.

## 9. Merge Professional + Context Readiness

When context chunks are reviewed:

- Read existing professional promoted chunks.
- Read new context promoted chunks.
- Confirm professional coverage remains valid.
- Confirm the context axis is now covered.
- Confirm no wrong-domain or listing noise was promoted.
- Output a readiness completion decision.

Legal decisions:

- `READY_FOR_FORMAL_READY_REVIEW`
- `NEEDS_WIKI_OR_ZIM_CONTEXT`
- `CONTEXT_EVIDENCE_WEAK`
- `CONTEXT_WRONG_DOMAIN`
- `NEEDS_RECHUNK`
- `BLOCKED`

If the decision is `READY_FOR_FORMAL_READY_REVIEW`, this is only readiness completion. The next action is formal-ready review, not controlled dry-run.

## 10. Output Contract

Every run must emit a report with these fields:

- status
- repo_path
- branch
- head
- context_source_discovery
- context_sources_extracted
- context_sources_processed
- context_chunks_created
- context_chunks_reviewed
- context_chunks_promoted
- context_chunks_excluded_or_weak
- context_axis_coverage
- professional_axis_coverage
- term_coverage
- section_coverage
- wrong_domain_guard_result
- previous_case_decision
- new_case_decision
- readiness_completion
- official_baseline_update_performed: false
- full_series_b_run_performed: false
- production_default_manifest_integration_performed: false
- controlled_regression_execution_performed: false
- repo_modified
- commit_created: false
- push_performed: false
- recommended_next_action

## 11. Anti-patterns

- using LLM to write missing context article
- treating generated summaries as wiki_or_zim
- treating entry-bound context as page-bound
- allowing travel/listing content into context source
- treating context readiness as controlled pass
- updating official baseline after readiness completion
- mixing local evidence with official score
- hardcoding one case's terms into the Skill
