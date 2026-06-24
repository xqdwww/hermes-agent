---
name: research-decision-academic-literature-review-writer
description: Use for turning scholarly corpora, PDFs, BibTeX/Zotero exports, Research evidence packets, or user-provided academic sources into rigorous academic literature reviews with claim-level citation grounding.
version: 1.0.0
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
    tags: [research-decision, academic-review, literature-review, scholarly-synthesis, citation-grounding]
---

# Academic Literature Review Writer

## purpose

Use this skill to convert local papers, PDFs, BibTeX files, Zotero exports, Research evidence packets, or a user-provided scholarly corpus into a strict academic literature review.

The core objective is synthesis of scholarly literature with claim-level citation grounding. The output must be a high-quality academic review with a research question, review scope, theoretical structure, thematic synthesis, methodological comparison, evidence-strength appraisal, controversy handling, gap analysis, limitations, and traceable citations for key claims.

This skill is not a normal Research final answer, a Decision report, or a source collage. It must not produce:

- A quick concept summary.
- An encyclopedia-style explanation.
- An annotated bibliography by default.
- A paper-by-paper summary.
- A decision recommendation.
- A marketing white paper.
- A report stitched together from search snippets.

The minimum target is an academic review draft that would score at least 80/100 under the `academic_review_rubric` in this skill.

## when_to_use

Use this skill when the user asks for any of the following:

- A literature review, academic review, scholarly review, or 文献综述.
- A review built from a supplied set of papers, PDFs, BibTeX entries, Zotero exports, or research notes.
- A synthesis of a Research evidence packet into an academic literature review.
- A comparison of theoretical lineages, method evolution, evidence strength, disagreements, or future research gaps in a scholarly field.
- A state-of-the-field review, scoping review, theoretical review, methodological review, systematic-style review, mini-review, or preliminary academic review.

Use this skill when the requested deliverable needs academic synthesis rather than answer generation. The central unit of work is the claim-source relationship, not fluent prose alone.

## when_not_to_use

Do not use this skill when:

- The user only wants a fast explanation of a concept.
- The user asks for news, latest policy changes, live prices, market data, or other time-sensitive current information.
- The user asks for investment, business, travel, engineering, product, or operational decisions; route those to Decision or the appropriate skill instead.
- There are no citable sources.
- The available material is only search snippets or metadata but the user asks for strong academic conclusions.
- The user explicitly asks for an annotated bibliography rather than synthesis, unless they also requests a synthesis-style review.

If the corpus cannot support academic claims, return an appropriate blocked or downgraded outcome instead of pretending that a review is complete.

## hermes_invocation_protocol

When Hermes receives a user request to write an academic literature review, literature review, scholarly review, or 文献综述, Hermes must first enter intake mode.

If the user has not provided complete inputs, Hermes must not directly write `literature_review.md`, summarize papers, or start a full review draft. The first response must be a structured intake form that collects the minimum academic review parameters and source availability needed for claim-level citation grounding.

Hermes may proceed to writing and validation only after the intake form satisfies `minimum_required_fields`. If the intake shows that sources are missing or too weak, Hermes must return a blocked or downgraded planning outcome rather than inventing an academic review.

## two_step_execution_rule

Use a two-step execution flow for Hermes-facing requests.

### Step 1: intake_and_scope_confirmation

Collect and confirm:

- `topic_or_title`: research topic or provisional title.
- `research_question`: the central research question.
- `review_type`: one supported review type.
- `target_audience`: intended reader or submission context.
- `output_language`: Chinese, English, bilingual notes, or another user-specified language.
- `target_length`: target length or document scale.
- `citation_style`: requested citation format.
- `source_corpus`: local PDFs, file paths, BibTeX, Zotero export, existing Research evidence packet, or an explicit declaration that the corpus is not ready.
- `expected_source_count`: expected number of papers or user-provided corpus size.
- `full_text_availability`: full text, partial full text, abstract only, metadata only, or mixed.
- `date_range`: publication-year scope when relevant.
- `inclusion_criteria`: source inclusion logic.
- `exclusion_criteria`: source exclusion logic.
- `required_sections`: user-required sections.
- `output_package_requirement`: whether the user wants the full output package or a narrower artifact set.

### Step 2: write_and_validate

Only after Step 1 satisfies `minimum_required_fields`, proceed to:

- Extract paper-level evidence.
- Build `evidence_matrix.csv`.
- Synthesize literature by theme, theory, method, debate, and gap.
- Write `literature_review.md`.
- Produce `claim_citation_table.md`.
- Run the deterministic `academic_literature_review_contract` validator when an output package is produced.
- Return `quality_gate_report.md` with score, failure codes, caveats, and revision requirements.

## intake_form

Hermes must present an intake form before writing. Divide fields into required, recommended, and optional.

### Required fields

1. `topic_or_title`: The topic or provisional title.
2. `research_question`: The core research question. Without a research question, do not directly write the review.
3. `review_type`: One of `narrative_review`, `scoping_review`, `systematic_style_review`, `theoretical_review`, `methodological_review`, `state_of_the_field_review`, `mini_review`, or `preliminary_review`.
4. `target_length`: Examples include `1500 words`, `3000 words`, `5000 words`, `8000 words`, or `journal-style long review`.
5. `citation_style`: Examples include APA, MLA, Chicago, Vancouver, GB/T 7714, author-year, or numeric.
6. `source_corpus`: Literature source, such as local PDF directory, file paths, BibTeX, Zotero export, existing Research evidence packet, or explicit statement that corpus is not ready.
7. `expected_source_count`: Expected source count, such as 5, 10-20, 30-50, or user-provided corpus only.
8. `full_text_availability`: One of all full text available, partial full text, abstract only, metadata only, or mixed.
9. `target_audience`: Examples include undergraduate, graduate seminar, journal submission draft, thesis chapter, or internal research memo.
10. `output_language`: Examples include Chinese, English, or bilingual notes.

### Recommended fields

11. `discipline_or_field`: Discipline or field.
12. `date_range`: Publication-year range.
13. `inclusion_criteria`: Inclusion criteria.
14. `exclusion_criteria`: Exclusion criteria.
15. `key_theories_or_frameworks`: Theories or frameworks to cover.
16. `key_methods_or_study_designs`: Methods or study designs to compare.
17. `must_cover_themes`: Required themes.
18. `known_debates_or_contradictions`: Known debates or contradictions.
19. `required_sections`: User-specified sections.
20. `quality_threshold`: Default is 80/100.

### Optional fields

21. `preferred_journals_or_venues`
22. `geographic_scope`
23. `population_or_sample_scope`
24. `methodological_preference`
25. `whether_to_include_tables`
26. `whether_to_include_gap_map`
27. `whether_to_include_method_taxonomy`
28. `whether_to_include_debate_map`
29. `whether_to_generate_bibliography_bib`
30. `final_output_format`

## minimum_required_fields

Hermes must not begin formal review writing unless at least these fields are present:

- `topic_or_title`
- `research_question`
- `review_type`
- `target_length`
- `citation_style`
- `source_corpus` or an explicit `corpus_missing` declaration.
- `expected_source_count`
- `full_text_availability`
- `target_audience`
- `output_language`

If `source_corpus` is missing, Hermes may only return `BLOCKED_NO_SOURCES` or a preliminary planning / source acquisition checklist. It must not generate a formal `literature_review.md`.

## default_intake_response

Default Chinese first response:

```text
请先填写下面信息，我再开始写文献综述：

必填：
1. 题目 / 暂定题目：
2. 核心研究问题：
3. 综述类型：
4. 目标篇幅：
5. 引用格式：
6. 文献来源 / 文件路径：
7. 预计文献数量：
8. full text 状态：
9. 目标读者：
10. 输出语言：

建议填写：
11. 学科领域：
12. 文献年份范围：
13. 纳入标准：
14. 排除标准：
15. 必须覆盖的理论 / 框架：
16. 必须比较的方法：
17. 必须覆盖的主题：
18. 已知争议：
19. 指定章节：
20. 质量门槛：

可选：
21. 是否要 evidence_matrix.csv：
22. 是否要 debate_map.md：
23. 是否要 method_taxonomy.md：
24. 是否要 bibliography.bib：
25. 最终格式：
```

## no_direct_write_without_intake

If the user only says "write a literature review", "帮我写文献综述", or gives an equivalent underspecified request without source corpus and key parameters, Hermes must return the intake form first. This is a no direct write without intake rule: 不得直接写正式文献综述正文、不得生成 `literature_review.md`、不得 present a source summary as the final review.

Failure code: `FAIL_DIRECT_WRITE_WITHOUT_INTAKE`.

## hermes_runtime_boundary

This skill may be invoked by Hermes as a passive optional skill, but it must not modify Research/Decision routing and must not create a new TaskMode.

Hermes may surface the intake form and later call the writer / validator flow manually after the user supplies the required inputs. Research engine runtime behavior must remain unchanged. Do not add automatic Research pipeline invocation, task-engine routing, or Decision integration unless a later explicit task asks for runtime integration.

## input_contract

Accept these fields when available. Missing fields must be inferred conservatively or recorded in `quality_gate_report.md`.

| field | required | meaning |
| --- | --- | --- |
| `research_question` | required | The question, problem, construct, hypothesis space, or field relationship the review addresses. |
| `review_type` | required | One of `narrative_review`, `scoping_review`, `systematic_style_review`, `theoretical_review`, `methodological_review`, `state_of_the_field_review`, `mini_review`, or `preliminary_review`. |
| `corpus` | required unless supplied by paths or packet | The set of scholarly sources to review, including papers, reports, chapters, theses, or structured evidence records. |
| `source_paths` | optional | Local paths for PDFs, text extracts, markdown notes, CSVs, BibTeX files, Zotero exports, or evidence artifacts. |
| `bibliography` | optional | BibTeX, CSL JSON, RIS, Zotero export, or citation metadata. |
| `evidence_packet` | optional | Hermes Research evidence packet with source ids, claim ids, evidence tiers, anchors, defects, and gap records. |
| `target_audience` | optional | Intended academic audience, such as graduate seminar, journal review draft, thesis chapter, grant background, or interdisciplinary audience. |
| `citation_style` | optional | APA, MLA, Chicago, IEEE, Vancouver, author-year, numeric, or another user-specified style. |
| `length_target` | optional | Desired length, such as 1,500 words, 5 pages, thesis chapter section, or concise mini-review. |
| `required_sections` | optional | User-required sections in addition to the default structure. |
| `exclusion_rules` | optional | Source types, date ranges, venues, disciplines, geographies, methods, or evidence tiers to exclude. |
| `freshness_requirement` | optional | Date sensitivity, publication cutoff, or requirement to include the newest available literature. |
| `allowed_evidence_tiers` | optional | Evidence tiers allowed for substantive claims. Defaults to full text and partial full text only for strong claims. |
| `claim_granularity` | optional | Level at which claims must be traced, such as paragraph-level, sentence-level, table-row-level, or key-claim-level. |
| `minimum_corpus_size` | optional | Minimum number of usable scholarly sources required for the requested review type. |
| `full_text_requirement` | optional | Whether strong claims, field claims, or all included papers require full-text verification. |

If `research_question` is missing but the user supplies a corpus and clear topic, draft a narrow research question and record it as an assumption. If neither question nor corpus is clear, return `BLOCKED_NO_SOURCES` or request clarification.

## evidence_tiers

Every source must receive one evidence tier. The tier constrains what claims may be made.

| evidence_tier | definition | allowed use |
| --- | --- | --- |
| `full_text_verified` | The full source text was read or parsed enough to verify method, findings, limitations, and context. | May support strong scholarly claims when source anchors and quality notes are present. |
| `full_text_partial` | Part of the full text was available, such as selected sections, tables, or OCR excerpts. | May support limited claims only within the verified sections; boundaries must be stated. |
| `abstract_only` | Only the abstract was read. | May support preliminary characterization but not strong conclusions, consensus claims, or detailed method appraisal. |
| `metadata_only` | Only title, authors, year, venue, DOI, keywords, or citation metadata is available. | May support indexing, chronology, and corpus description only; must not support substantive scholarly claims. |
| `search_snippet_only` | Only search result snippets or preview fragments are available. | Must not support scholarly claims. Use only to identify retrieval needs or downgrade confidence. |
| `secondary_summary` | A summary by another author, database, model, review, or non-original source. | Must be labeled as secondary evidence and must not be represented as primary research evidence. |

Hard evidence rules:

- Only `full_text_verified` sources may support strong scholarly claims.
- `full_text_partial` sources may support limited claims, but the claim must name the verified boundary.
- `abstract_only` sources may only support preliminary characterization.
- `metadata_only` must not support substantive scholarly claims.
- `search_snippet_only` must not support scholarly claims.
- `secondary_summary` must be labeled as secondary and cannot be used as if it were original evidence.
- Consensus, field-level, causal, mechanism, intervention, effectiveness, or theory-change claims require multiple relevant sources and source anchors unless the claim is explicitly framed as narrow or source-specific.

## review_types

Select and enforce one review type. The type determines scope, allowable claims, and required caveats.

| review_type | required emphasis | constraints |
| --- | --- | --- |
| `narrative_review` | Theoretical lineage, thematic synthesis, interpretive structure, and controversy explanation. | Must not become a paper-by-paper summary. |
| `scoping_review` | Scope, classification, literature map, construct boundaries, methods landscape, and gaps. | Must not claim systematic-review certainty unless a protocol and complete search path exist. |
| `systematic_style_review` | Inclusion/exclusion criteria, search path, screening logic, evidence matrix, and transparent appraisal. | Must not claim to be a formal systematic review unless the user supplies a complete protocol and adequate corpus. |
| `theoretical_review` | Concepts, theoretical frameworks, explanatory models, assumptions, and theoretical tensions. | Must distinguish theory claims from empirical findings. |
| `methodological_review` | Research design, data sources, measurement, sampling, validity threats, and method evolution. | Must include method taxonomy and evidence-appraisal limits. |
| `state_of_the_field_review` | Field consensus, live controversies, research frontier, and future directions. | Requires sufficient corpus coverage; otherwise downgrade to mini or preliminary review. |
| `mini_review` | Focused synthesis from a small but usable corpus. | Appropriate for 3-5 full-text papers; must not claim field-level coverage. |
| `preliminary_review` | Early synthesis when full text is incomplete or corpus coverage is weak. | Must lower claim strength and label conclusions as preliminary. |

## extraction_schema

For each paper or scholarly source, extract at least these fields before synthesis:

| field | meaning |
| --- | --- |
| `paper_id` | Stable local identifier for the source. |
| `citation_key` | BibTeX or generated citation key used in review text. |
| `title` | Source title. |
| `authors` | Author list or first author plus et al. |
| `year` | Publication year. |
| `venue` | Journal, conference, publisher, thesis program, repository, or venue metadata. |
| `DOI/URL if available` | DOI, URL, ISBN, arXiv id, PubMed id, or other stable locator when available. |
| `source_path` | Local path or packet pointer used for verification. |
| `evidence_tier` | One of the evidence tiers defined above. |
| `research_question` | Question or subquestion addressed by the source. |
| `theoretical_framework` | Theory, model, construct, or conceptual lens used by the source. |
| `method` | Research design, analytic method, intervention, model, or review method. |
| `data_or_sample` | Dataset, sample, population, corpus, case set, or empirical setting. |
| `measurement_or_variables` | Key measures, operationalizations, variables, instruments, or coding scheme. |
| `core_findings` | Findings that are directly supported by the source. |
| `limitations` | Stated and inferred limitations relevant to the review question. |
| `claims_supported` | Review-level claims this source can support. |
| `claims_contradicted` | Review-level claims this source challenges, narrows, or contradicts. |
| `applicability_boundary` | Conditions under which the finding or theory is likely applicable. |
| `source_anchors` | Page, section, table, figure, quote location, claim id, or packet anchor used for traceability. |
| `notes_on_quality` | Appraisal notes on design strength, threats to validity, sample weakness, relevance, and citation reliability. |

Do not synthesize until extraction is complete enough to trace the major claims. If anchors are missing for important claims, return `BLOCKED_CITATION_TRACE_MISSING` or downgrade those claims.

## synthesis_schema

The review must generate these synthesis artifacts or sections:

| component | requirement |
| --- | --- |
| `field_overview` | Define the domain, review scope, and why the question matters. |
| `concept_definition_table` | Map key constructs, competing definitions, source clusters, and boundaries. |
| `chronology_or_intellectual_lineage` | Explain how the field, theory, or methods developed over time. |
| `theme_clusters` | Group literature by higher-order themes, not by individual papers. |
| `theoretical_framework_map` | Map theories, constructs, mechanisms, assumptions, and tensions. |
| `method_taxonomy` | Classify designs, data, samples, measures, analytic strategies, and validity limits. |
| `evidence_strength_map` | Appraise strength by theme, method, source tier, sample, replication, and limitations. |
| `debate_map` | Present disagreements, counter-evidence, rival explanations, and boundary conditions. |
| `consensus_points` | Identify claims supported across multiple credible sources. |
| `disagreement_points` | Identify claims where sources diverge or evidence is mixed. |
| `unresolved_questions` | Identify questions the current literature does not settle. |
| `research_gaps` | Identify missing populations, methods, theory links, measures, settings, or causal tests. |
| `future_research_directions` | Translate gaps into concrete research directions. |
| `limitations_of_this_review` | State corpus, access, method, evidence-tier, freshness, and citation limitations. |

## output_contract

Produce these files unless the user explicitly asks for a narrower artifact set. If any required file cannot be produced, explain why in `quality_gate_report.md`.

| output file | required content |
| --- | --- |
| `literature_review.md` | Formal review body with the required structure and claim-level citations. |
| `claim_citation_table.md` | Table mapping each key claim to `citation_key`, `paper_id`, `source_anchor`, `evidence_tier`, and `claim_strength`. |
| `evidence_matrix.csv` | Machine-readable evidence table with at least `paper_id`, `citation_key`, `theme`, `method`, `sample`, `finding`, `limitation`, `evidence_tier`, and `source_anchor`. |
| `paper_index.md` | Source inventory with citation metadata, evidence tier, availability, and inclusion rationale. |
| `method_taxonomy.md` | Method classification, data/sample comparison, measurement notes, and validity limitations. |
| `debate_map.md` | Debate, disagreement, counter-evidence, rival explanations, and applicability boundaries. |
| `gap_and_future_work.md` | Research gaps, unresolved questions, and future research directions. |
| `bibliography.bib` | BibTeX bibliography when source metadata makes it possible. |
| `provenance.json` | Machine-readable provenance with inputs, source paths, evidence tiers, extraction status, anchors, defects, review type, and generated outputs. |
| `quality_gate_report.md` | Academic quality rubric score, pass/fail status, patchwork risk, gate results, defects, and revision requirements. |

`literature_review.md` is the formal review. `claim_citation_table.md` is the traceability spine and must include every key claim. `evidence_matrix.csv` must be valid CSV and usable by downstream tooling. `quality_gate_report.md` must include `academic_review_rubric` scoring and a clear PASS or failure code.

## academic_quality_standard

The minimum acceptable target is an academic review that scores at least 80/100 under the rubric below.

A score of 80 or higher means the review has:

- A clear research question and review scope.
- Explicit corpus selection logic.
- Field structure and theoretical lineage.
- Thematic synthesis rather than sequential paper summaries.
- Method comparison and evidence appraisal.
- Debate, counter-evidence, and unresolved questions.
- Gap analysis and future research directions.
- Claim-level citation grounding.
- Review limitations.
- Academic prose, coherent argumentation, and disciplined claim strength.

If the total score is below 80, `quality_gate_report.md` must set the final status to `FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD`. Do not mark the review PASS.

## anti_patchwork_rule

Patchwork literature reviews are forbidden.

Do not:

- Copy and paste sentences from papers as a substitute for synthesis.
- Extract one sentence from each paper and mechanically join them.
- Write the whole review in an "Author A says, Author B says, Author C says" sequence.
- Produce only an annotated bibliography.
- Dump citations without explaining relationships among sources.
- Use synonym rewriting to disguise summary as synthesis.
- Treat source summaries as the literature review itself.

If the output is mainly paper-by-paper summary, citation dumping, source collage, or lacks cross-literature synthesis, mark it:

`FAIL_PATCHWORK_REVIEW`

## synthesis_requirement

Every major thematic paragraph must perform synthesis, not just summary. A core theme paragraph should do at least one of the following:

- Compare theoretical positions across sources.
- Explain why findings align or conflict.
- Distinguish method-driven differences in results.
- Abstract a higher-order theme from multiple studies.
- Connect early work, recent work, and current debate.
- Judge evidence strength and applicability boundaries.
- Identify a question that the literature has not resolved.

The review should use individual studies as evidence inside a larger argument. It must not let the source order determine the review structure unless the section is explicitly chronological.

## paragraph_quality_rule

A qualified review paragraph generally should not rely on a single paper.

Allowed exceptions:

- Introducing a seminal work.
- Introducing a key theoretical source.
- Describing the only available evidence source.
- Writing an explicitly labeled source-specific note.

Each major argumentative paragraph should include:

- A topic claim.
- A supporting literature cluster.
- The relationship among sources.
- Evidence strength or limitations.
- A transition to the next issue.

Single-source paragraphs must be justified by function and must not be used to inflate apparent synthesis.

## structure_requirement

Unless the user explicitly supplies a different academic structure, `literature_review.md` must include at least:

1. Introduction: research question, scope, and importance.
2. Review method / corpus note.
3. Conceptual and theoretical background.
4. Thematic synthesis sections.
5. Methodological patterns and evidence quality.
6. Areas of consensus.
7. Areas of disagreement or uncertainty.
8. Gaps and future research directions.
9. Limitations of the review.
10. Conclusion.

Sections may be renamed for journal style, but the functions cannot be omitted.

## literature_review_vs_annotated_bibliography

Annotated bibliography:

- Introduces sources one by one.
- Emphasizes source summary.
- Has weak relationships among sources.
- Helps inventory literature but does not by itself establish a field argument.

High-quality literature review:

- Organizes by question, theory, theme, method, debate, and gap.
- Uses sources as evidence in an argument.
- Emphasizes synthesis, evaluation, and positioning.
- Explains what the field knows, what it does not know, why it does not know it, and what should be studied next.

This skill defaults to high-quality literature review. It may produce annotated-bibliography components only as supporting artifacts, not as the main deliverable, unless the user explicitly requests that format.

## quality_gates

Run these hard gates before marking the review PASS:

| gate | pass condition | failure behavior |
| --- | --- | --- |
| `no_uncited_key_claims` | Every key scholarly claim has a citation key and source anchor. | Revise or fail with citation-trace defect. |
| `no_fake_citations` | No citation key, author, title, or year is invented. | Remove or fail. |
| `no_fake_doi` | DOI/URL fields are present only when verified from metadata or source files. | Remove or fail. |
| `no_unsupported_consensus_claim` | Consensus claims require multiple credible sources and evidence-tier support. | Downgrade or fail. |
| `no_snippet_based_scholarly_claim` | Search snippets are not used to support scholarly claims. | Fail or downgrade to retrieval note. |
| `no_overgeneralization_from_single_study` | Single-study findings are not framed as field consensus. | Revise claim strength. |
| `claim_source_traceability_required` | Key claims map to source ids, citation keys, anchors, evidence tiers, and claim strength. | Fail with `BLOCKED_CITATION_TRACE_MISSING`. |
| `counter_evidence_required` | Relevant contradictions, null findings, or rival explanations are represented. | Fail unless corpus lacks counter-evidence and this is stated. |
| `limitations_required` | Review limitations and source limitations are explicit. | Fail or revise. |
| `evidence_tier_labels_required` | Evidence tiers appear in paper index, claim table, matrix, provenance, and quality report. | Fail. |
| `output_files_complete` | Required outputs exist or omissions are justified. | Fail. |
| `no_patchwork_review` | The review is not a paper-by-paper collage. | Fail with `FAIL_PATCHWORK_REVIEW`. |
| `cross_source_synthesis_required` | Main theme sections integrate multiple sources or justify exceptions. | Fail with `FAIL_NO_CROSS_SOURCE_SYNTHESIS`. |
| `academic_quality_score_at_least_80` | Rubric score is 80/100 or higher. | Fail with `FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD`. |

Quality gates must be recorded in `quality_gate_report.md` with pass/fail values and evidence.

## academic_review_rubric

Score the review on a 100-point scale. A score below 80 cannot PASS.

| category | points | scoring focus |
| --- | ---: | --- |
| Research question and scope clarity | 10 | Question is explicit, bounded, important, and reflected in section structure. |
| Corpus relevance and coverage | 10 | Sources are relevant, selection logic is transparent, and coverage limits are stated. |
| Conceptual/theoretical framing | 15 | Constructs, theories, assumptions, lineage, and conceptual tensions are mapped. |
| Cross-literature synthesis quality | 20 | Themes integrate sources, explain relationships, and build an argument beyond summaries. |
| Methodological comparison and evidence appraisal | 15 | Methods, samples, measures, validity, evidence tiers, and limitations are compared. |
| Debate, contradiction, and counter-evidence handling | 10 | Conflicting findings and rival explanations are included and interpreted. |
| Gap analysis and future research directions | 10 | Gaps are specific, justified by the synthesis, and translated into research directions. |
| Citation rigor and claim-source traceability | 10 | Key claims have accurate citations, anchors, evidence tiers, and claim-strength labels. |

Score interpretation:

- 90-100: publishable or near-publishable review draft.
- 80-89: strong academic review draft; requires editing but is structurally sound.
- 70-79: usable summary but insufficient synthesis.
- 60-69: patchy review with weak structure.
- Below 60: not an academic literature review.

`quality_gate_report.md` must include:

- `rubric_score`
- `score_by_category`
- `pass_or_fail`
- `deduction_reasons`
- `patchwork_risk`
- `strongest_sections`
- `weakest_sections`
- `required_revision_before_submission`

If `rubric_score < 80`, set final status to `FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD`.

## failure_modes

Use these outcome labels when the contract cannot be satisfied:

| failure mode | meaning |
| --- | --- |
| `BLOCKED_NO_SOURCES` | No usable citable scholarly sources are available. |
| `BLOCKED_NO_FULL_TEXT_FOR_STRONG_CLAIMS` | Strong claims are requested but no full-text-verified evidence supports them. |
| `BLOCKED_CITATION_TRACE_MISSING` | Key claims cannot be traced to citation keys, paper ids, anchors, or evidence tiers. |
| `BLOCKED_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS` | Corpus is too small or narrow for field-level claims. |
| `BLOCKED_CONTRADICTORY_EVIDENCE_UNRESOLVED` | Contradictions are material but cannot be represented or interpreted from available evidence. |
| `BLOCKED_BIBLIOGRAPHY_INCOMPLETE` | Required citation metadata is too incomplete to produce a responsible bibliography. |
| `FAIL_PATCHWORK_REVIEW` | Output is a source collage, citation dump, or paper-by-paper review rather than synthesis. |
| `FAIL_ANNOTATED_BIBLIOGRAPHY_ONLY` | Output is only an annotated bibliography when a synthesis review was required. |
| `FAIL_NO_THEORETICAL_STRUCTURE` | Review lacks conceptual or theoretical framing. |
| `FAIL_NO_METHOD_COMPARISON` | Review lacks method taxonomy or methodological comparison when required. |
| `FAIL_NO_EVIDENCE_APPRAISAL` | Review does not evaluate evidence strength, limitations, or evidence tiers. |
| `FAIL_NO_CROSS_SOURCE_SYNTHESIS` | Main sections do not integrate literature across sources. |
| `FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD` | Rubric score is below 80/100. |

Failure labels must be propagated to the final response and `quality_gate_report.md`.

## corpus_size_policy

Corpus coverage determines allowable claims.

- A thin corpus must not be described as a completed field-level literature review.
- 3-5 full-text papers can support at most a `mini_review`.
- Abstract-only or partial-text corpora can support only a `preliminary_review`.
- Without `full_text_verified` evidence, do not make strong consensus claims.
- Field-level reviews require adequate corpus coverage across the relevant theories, methods, time periods, and subdomains; otherwise label coverage limitations prominently.
- If `minimum_corpus_size` is supplied and unmet, block or downgrade the review type.
- If the available corpus is too small for the user's requested scope, use `BLOCKED_CORPUS_TOO_SMALL_FOR_FIELD_CLAIMS` or downgrade to `mini_review` with explicit user-visible limitations.

## writing_rules

Follow these writing rules:

- Use academic tone without hiding uncertainty.
- Synthesize before evaluating.
- Do not stack paper summaries.
- Do not write a sequential paper-by-paper narrative unless a short source-specific subsection is explicitly needed.
- Within each theme paragraph, connect multiple sources whenever possible.
- Important judgments must have citation keys.
- Distinguish `consensus`, `contested`, `emerging`, and `speculative` claims.
- Preserve caveats and applicability boundaries.
- Do not present an author's interpretation as objective fact.
- Do not present a single-paper finding as field consensus.
- Do not use polished language to mask insufficient evidence.
- Prefer precise claim strength over rhetorical confidence.
- Use quotations sparingly and only when the exact wording matters; paraphrase with citation grounding by default.

## integration_with_research_decision

This skill can consume Hermes Research evidence packets and may reuse guarded-validation discipline from Research/Decision workflows.

Integration rules:

- Consume Research evidence packets when they contain claim ids, source ids, evidence tiers, source anchors, defects, and gap records.
- Borrow guarded validation principles: preserve provenance, do not hide source defects, and do not let fluent final prose override evidence limits.
- Do not call Decision or produce a final choice unless the user explicitly asks to make a decision based on the review.
- If the Research packet lacks `claim_id`, `source_id`, `evidence_tier`, or `source_anchor` for key claims, return or downgrade to `BLOCKED_CITATION_TRACE_MISSING`.
- Propagate Research-stage source defects, L4/L5 defects, evidence gaps, calibration caveats, and external disagreement into `quality_gate_report.md`.
- Do not smooth over weak evidence, missing full text, citation defects, or unresolved contradictions from earlier Research stages.

## operating_flow

Use this workflow:

1. Confirm the review question, review type, target audience, citation style, and required scope.
2. Inventory sources and assign `paper_id`, `citation_key`, source path, metadata, and evidence tier.
3. Extract source records using `extraction_schema`.
4. Reject or downgrade claims that exceed evidence tier limits.
5. Build concept definitions, theoretical map, method taxonomy, theme clusters, evidence-strength map, debate map, and gap map.
6. Draft `literature_review.md` around synthesis functions, not source order.
7. Generate `claim_citation_table.md`, `evidence_matrix.csv`, `paper_index.md`, `method_taxonomy.md`, `debate_map.md`, `gap_and_future_work.md`, `bibliography.bib` when possible, and `provenance.json`.
8. Run `quality_gates` and score `academic_review_rubric`.
9. If score is below 80, patchwork risk is high, or traceability fails, return the appropriate failure mode instead of PASS.
10. Final response must summarize score, output type, evidence strength, risks, and output paths.

## acceptance_tests

Use these tests to validate the skill behavior.

### A. small_full_text_corpus_mini_review

Given 5 full-text papers on a focused research question, the skill may generate `mini_review`. It must not claim coverage of the entire field, and `quality_gate_report.md` must state the corpus-size limitation.

Expected outcome: PASS only if synthesis, traceability, and rubric score are adequate for a mini-review.

### B. contradictory_findings_debate_map

Given studies with conflicting findings, the skill must generate `debate_map.md` and explain whether disagreement may arise from theoretical framework, sample, measurement, study design, data setting, analysis strategy, or applicability boundary.

Expected outcome: PASS only if contradictions appear in both the review and debate map.

### C. abstract_only_corpus_blocks_strong_claims

Given a corpus with abstracts only, the skill must prohibit strong scholarly claims and downgrade output to `preliminary_review` or `preliminary_evidence_summary`.

Expected outcome: `BLOCKED_NO_FULL_TEXT_FOR_STRONG_CLAIMS` if the user requires strong claims; otherwise preliminary output with explicit limits.

### D. search_snippet_downgrade

Given sources that include search snippets, the snippets must not support scholarly claims. The skill must warn in `quality_gate_report.md` and `provenance.json`.

Expected outcome: downgrade evidence tier and omit snippet-supported claims.

### E. cross_disciplinary_method_taxonomy

Given a cross-disciplinary corpus, the skill must generate `method_taxonomy.md`, identify method families, and record `applicability_boundary` for claims that do not transfer cleanly across disciplines.

Expected outcome: PASS only if method differences shape the synthesis.

### F. patchwork_negative_test

Given 8 paper abstracts or excerpts, if the output is mainly "Smith argues..., Jones finds..., Wang notes..." without cross-source synthesis, the skill must fail.

Expected outcome: `FAIL_PATCHWORK_REVIEW`.

### G. academic_rubric_threshold_test

Given a small but complete corpus, the skill must generate `literature_review.md` and `quality_gate_report.md`, then self-score using `academic_review_rubric`.

Expected outcome: If the score is below 80, the output cannot be marked PASS and must return `FAIL_ACADEMIC_QUALITY_BELOW_THRESHOLD`.

## final_response_policy

The final response to the user must not merely say that the literature review is complete. It must include:

- Academic quality score.
- Whether the review reached the 80+ threshold.
- Whether patchwork risk remains.
- Strongest synthesis sections.
- Weakest sections needing human revision.
- Output type: `literature_review`, `annotated_bibliography`, `mini_review`, or `preliminary_evidence_summary`.
- Main output paths.
- Evidence strength summary.
- Which conclusions are `supported`, `plausible`, `speculative`, or `unresolved`.

If the review is blocked or downgraded, state the exact failure mode and the minimum source or citation work needed to continue.
