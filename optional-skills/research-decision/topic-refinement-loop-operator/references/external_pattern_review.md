# External Pattern Review

This review extracts transferable principles for a Hermes Research/Decision topic refinement loop. It is not a source of runtime requirements and does not copy public workflows into Hermes.

## sources_reviewed

- Anthropic / Claude Skills authoring best practices: <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices> and <https://docs.anthropic.com/en/docs/claude-code/skills>. Reviewed for skill authoring best practices, concise instructions, discoverable descriptions, workflow/checklist use, progressive disclosure, and realistic task testing.
- OpenAI prompt engineering guide: <https://developers.openai.com/api/docs/guides/prompt-engineering>. Reviewed for prompt iteration, task-specific tests, and the need to evaluate behavior instead of trusting one output.
- OpenAI evaluation best practices: <https://developers.openai.com/api/docs/guides/evaluation-best-practices> and OpenAI agent evaluation guidance at <https://developers.openai.com/api/docs/guides/agent-evals>. Reviewed for evaluation / tests, observable metrics, regression checks, and agent workflow quality gates.
- Self-Refine: <https://arxiv.org/abs/2303.17651>. Reviewed for initial output, feedback, refinement, and test-time iterative refinement without model training.
- Reflexion: <https://arxiv.org/abs/2303.11366> and <https://arxiv.org/abs/2303.17651> as adjacent iterative refinement work. Reviewed for reflection, reflective memory, verbalized failure feedback, and reuse of feedback across attempts.
- LangGraph workflow guidance: <https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph>. Reviewed for state object design, checkpoints, routing, retry policy, human feedback, and critique/revise loops.

## extracted_patterns

### Pattern 1

- pattern_name: concise_discoverable_skill
- source_family: Anthropic / Claude Skills authoring best practices
- mature_practice: Keep the main skill small, put triggering language in the description, and reserve the body for the operating workflow.
- why_it_matters: Skill discovery happens before the body is loaded. A verbose or vague skill can fail before the operator ever sees the instructions.
- how_to_adapt_to_research_decision: Put the same-topic targeted refinement trigger in frontmatter. Keep Research/Decision details in a short workflow and move the long external pattern review to this reference file.
- risks_if_overapplied: Over-compression can hide stop conditions and make the operator guess when the correct action is to stop.

### Pattern 2

- pattern_name: progressive_disclosure_with_workflow
- source_family: Anthropic / Claude Skills authoring best practices
- mature_practice: Use progressive disclosure for long material and use workflow/checklist structure when tasks are fragile.
- why_it_matters: Topic refinement must preserve artifacts, evidence boundaries, and caveats; a checklist prevents silent broad reruns or evidence upgrades.
- how_to_adapt_to_research_decision: Keep only the trigger, state model, failure mapping, modes, workflow, output contract, stops, and examples in `SKILL.md`. Load this review only when design rationale is needed.
- risks_if_overapplied: Too many linked references can scatter the operating contract and make the skill hard to execute under time pressure.

### Pattern 3

- pattern_name: eval_driven_prompt_iteration
- source_family: OpenAI prompt / eval best practices
- mature_practice: Treat prompts and agent workflows as non-deterministic systems that need evaluation suites, observable criteria, and regression checks.
- why_it_matters: A single fluent revised final can still be generic, overconfident, or disconnected from convergence and calibration artifacts.
- how_to_adapt_to_research_decision: Require quality review after each refinement and record failure type, changed sections, evidence reuse, caveats, confidence changes, and next action.
- risks_if_overapplied: A rigid test suite can reward keyword stuffing. Manual artifact-backed review remains necessary for semantic quality.

### Pattern 4

- pattern_name: iterative_feedback_refinement
- source_family: Self-Refine / iterative refinement
- mature_practice: Produce an initial output, generate or receive feedback, refine the output, and repeat while the loop has useful signal.
- why_it_matters: Research/Decision first-pass final is often a draft. The useful move is usually to repair a weak section or absorption pass, not restart the whole topic.
- how_to_adapt_to_research_decision: Model the first-pass final as version 1, convert quality failures or user feedback into a targeted next action, then write a revised final with a change log.
- risks_if_overapplied: Repeated self-feedback without new evidence, user feedback, or artifact-backed critique can amplify the model's own mistakes.

### Pattern 5

- pattern_name: reflective_feedback_memory
- source_family: Reflexion / feedback memory for agents
- mature_practice: Convert failure feedback into language reflections and make those reflections available to the next attempt in the same episode.
- why_it_matters: A topic should not forget that prior review found template-like language, weak priority ranking, thin evidence, or missing user obligations.
- how_to_adapt_to_research_decision: Store short-term reflections in `topic_refinement_state.refinement_history`, `quality_failures`, `preserved_caveats`, and `unresolved_evidence_gaps`.
- risks_if_overapplied: Short-term feedback should not become unconditional long-term memory. Reflections must stay scoped to the topic and must not override source evidence.

### Pattern 6

- pattern_name: stateful_checkpointed_workflow
- source_family: mature agent workflow patterns / LangGraph
- mature_practice: Make state explicit, route work through nodes, checkpoint between steps, and use retry policies for recoverable failures.
- why_it_matters: Refinement work crosses artifacts, quality review, user feedback, and final text. Explicit state prevents losing provenance.
- how_to_adapt_to_research_decision: Define `topic_refinement_state` with topic id, artifact paths, failures, feedback, history, caveats, evidence gaps, next action, and stop reason.
- risks_if_overapplied: Treating the operator skill like a new runtime graph would violate scope. This skill should guide manual/operator execution only.

### Pattern 7

- pattern_name: failure_to_next_action_routing
- source_family: mature agent workflow patterns / LangGraph and OpenAI agent eval guidance
- mature_practice: Route failures to specific next actions, including critique, revise, human feedback, checkpoint review, retry, or stop.
- why_it_matters: Different Research/Decision failures require different repair surfaces. Environment blockers are not answer-quality failures, and evidence gaps are not style problems.
- how_to_adapt_to_research_decision: Map each failure type to a minimal refinement mode such as `section_rewrite`, `final_absorption_pass`, `targeted_convergence_refinement`, `targeted_evidence_acquisition`, `user_feedback_refinement`, or `environment_triage`.
- risks_if_overapplied: Over-routing can hide judgment. If the artifact set is missing, the branch/head is wrong, or source acquisition is unauthorized, stop rather than choose a mode.

## what_to_adopt

- Use concise skill authoring best practices: a discoverable description, lean `SKILL.md`, and reference-based progressive disclosure.
- Treat first-pass final as a draft when artifact-backed review or user feedback shows a same-topic quality gap.
- Use a feedback loop: classify the failure, choose the smallest mode, refine only the affected surface, review quality, update topic state, and decide next action.
- Persist scoped reflective memory in the topic state, not in global memory.
- Preserve artifacts, caveats, thin-evidence boundaries, and provenance across versions.
- Use evaluation / tests and artifact-backed review rather than a single LLM self-score.
- Use stop conditions for dirty worktree, branch/head mismatch, missing artifacts, unsupported evidence needs, environment blockers, and topic changes.

## what_not_to_adopt

- Do not run an infinite self-reflection loop.
- Do not let a model self-reinforce without external evidence, user feedback, or artifact-backed critique.
- Do not make every failure trigger a full rerun.
- Do not pass refinement based only on LLM self-evaluation.
- Do not save short-term feedback as unconditional long-term memory.
- Do not put Travel-specific route/place logic into Research core.
- Do not make the skill too long, hard to discover, or overloaded with background.
- Do not treat environment failure as answer-quality failure.
- Do not upgrade thin evidence into strong evidence to make the revised final sound cleaner.

## implications_for_hermes_research_decision

- The topic refinement loop should be an operator skill first, not runtime integration.
- `topic_refinement_state` is the central checkpoint. It records what changed, what did not change, which artifacts were reused, and why the next action was selected.
- The default next action should be section-level or stage-level targeted continuation. Full topic rerun is a last resort when topic identity, domain anchoring, or source freshness is invalid.
- Quality review should become a routing signal: template-like final, low specificity, calibration absorption gap, convergence specificity loss, missing section, weak ranking, evidence gap, thin evidence, user feedback, or environment blocker.
- Evidence gaps need either targeted acquisition/full-text verification or explicitly preserved caveats. They should not be covered with fluent speculation.
- User feedback should be restated, scoped, and applied only to the affected parts unless the user asks for broader revision.

## open_questions

- What artifact path convention should become canonical for persisted `topic_refinement_state` once this operator skill graduates from manual use?
- Which quality gate should be considered authoritative when final quality review and user feedback disagree?
- How many refinement rounds should be allowed before requiring human review or fresh evidence acquisition?
- Which failure labels should be promoted into shared Research/Decision telemetry later, if any?
