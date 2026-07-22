from __future__ import annotations

from pathlib import Path

from agent.skill_utils import extract_skill_conditions, parse_frontmatter
from tools.skills_sync import _discover_bundled_skills


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "note-taking" / "book-deepening-extension"
SKILL_PATH = SKILL_DIR / "SKILL.md"
CATEGORY_DESCRIPTION_PATH = REPO_ROOT / "skills" / "note-taking" / "DESCRIPTION.md"


def load_skill() -> tuple[dict, str, str]:
    source = SKILL_PATH.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(source)
    return frontmatter, body, source


def test_skill_is_bundled_and_has_expected_identity():
    discovered = dict(_discover_bundled_skills(REPO_ROOT / "skills"))
    assert discovered["book-deepening-extension"] == SKILL_DIR
    frontmatter, body, _ = load_skill()
    assert frontmatter["name"] == "book-deepening-extension"
    assert frontmatter["metadata"]["hermes"]["display_name"] == "读后深潜与认知延伸"
    assert frontmatter["metadata"]["hermes"]["internal_design_id"] == "KARPATHY_READING_LAB"
    assert "读后深潜与认知延伸" in body


def test_category_discovery_description_exposes_all_three_entrypoints():
    description = CATEGORY_DESCRIPTION_PATH.read_text(encoding="utf-8")
    assert "book-deepening-extension" in description
    assert "开始讨论《书名》, load book-deepening-extension and call resolve_book once" in description
    assert "费曼聊这本书, load it and call current_book once" in description
    assert "把这本书和我以前读过的书连接起来, load it and call other_books once" in description


def test_skill_requires_book_notes_retrieval_and_agy_dialogue_tools():
    frontmatter, body, _ = load_skill()
    conditions = extract_skill_conditions(frontmatter)
    assert conditions["requires_tools"] == ["book_notes_retrieval", "agy_book_dialogue"]
    assert conditions["requires_toolsets"] == []
    assert "only personal-excerpt retrieval tool" in body


def test_start_discussion_resolves_without_guessing_or_research():
    _, body, _ = load_skill()
    assert "开始讨论《书名》" in body
    assert "action: resolve_book" in body
    assert "at most five returned candidates" in body
    assert "Do not guess" in body
    assert "Do not automatically search the web" in body
    assert "If resolution is\nambiguous, do not set `active_book`" in body


def test_feynman_entry_requires_active_book_and_uses_bounded_parameters():
    _, body, _ = load_skill()
    assert "请先说“开始讨论《书名》”。" in body
    assert "Do not call vector retrieval in that case" in body
    for contract in (
        "action: current_book",
        "top_k: 3",
        "candidate_k: 20",
        "max_per_parent: 1",
        "excerpt_max_chars: 500",
        "include_text: true",
    ):
        assert contract in body
    assert "make exactly one default tool call" in body
    assert "Do not ask for a restatement before the tool call" in body
    assert "Complete the one bounded `current_book` call" in body
    assert "one important gap" in body


def test_cross_book_entry_excludes_active_book_and_is_bounded():
    _, body, _ = load_skill()
    for contract in (
        "action: other_books",
        "exclude_book_id: <active_book.book_id>",
        "top_k_books: 3",
        "candidate_k: 40",
        "max_chunks_per_book: 1",
        "max_chunks_per_parent: 1",
        "relationship_intent: null",
    ):
        assert contract in body
    assert "Select at most three returned books" in body
    assert "it is the model's interpretation, not a vector-store fact" in body


def test_source_labels_and_endorsement_boundary_are_explicit():
    _, body, _ = load_skill()
    for label in (
        "[BOOK]",
        "[OTHER_BOOK]",
        "[MODEL_KNOWLEDGE]",
        "[PROVIDED_TEXT]",
        "[USER]",
        "[INFERENCE]",
    ):
        assert label in body
    assert "[MY_HIGHLIGHT]" in body and "Do not use" in body
    assert "保存过的书摘只代表曾被收集或注意，不代表用户认可其中观点。" in body
    assert "Never treat an excerpt as the user's writing, belief" in body


def test_state_is_session_only_and_no_platform_features_are_created():
    _, body, _ = load_skill()
    assert "Maintain only this small state in the current conversation" in body
    assert "Do not create a disk checkpoint" in body
    assert "conversation must begin again" in body
    assert "a prior successful start turn plus its confirmed title" in body
    assert "Never print\nor persist an internal `book_id`" in body
    assert sorted(path.name for path in SKILL_DIR.iterdir()) == ["SKILL.md"]
    lowered = body.lower()
    assert "do not simulate multiple agents" in lowered
    assert "external research" in lowered


def test_skill_keeps_one_call_default_and_does_not_copy_retrieval_logic():
    _, body, source = load_skill()
    assert "retrieval_calls_per_turn: 1" in body
    assert "make exactly one `book_notes_retrieval` call" in body
    assert "do not\nrepeat, retry, or verify it in the same turn" in body
    assert "Do not make a second call automatically" in body
    assert "session_search" in body and "scope_recall_search" in body
    assert "Never automatically scan all" in body
    assert "BookNotesRetriever" not in source
    assert "lancedb" not in source.lower()
    assert "embedding" not in source.lower()


def test_response_contract_hides_absolute_paths_and_limits_questions():
    _, body, _ = load_skill()
    assert "Do not expose absolute paths" in body
    assert "No absolute path is present in the answer" in body
    assert "never ask more than two questions in a row" in body
    assert "End with one connection question" in body


def test_same_session_title_fallback_does_not_require_an_identifier_checkpoint():
    _, body, _ = load_skill()
    assert "book_id: <active_book.book_id>" in body
    assert "book_title: <active_book.title>" in body
    assert "exclude_book_id: <active_book.book_id>" in body
    assert "exclude_book_title: <active_book.title>" in body
    assert "Sensitive tool results may omit `book_id`" in body


def test_dependency_extra_is_pinned_for_reproducible_runtime():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'book-notes = ["sentence-transformers==5.6.0", "torch==2.12.0", "lancedb[pylance]==0.34.0"]' in pyproject


def test_not_found_switches_to_general_mode_and_keeps_discussion_open():
    _, body, _ = load_skill()
    assert "`not_found`: do not end the discussion" in body
    assert "discussion_mode: general_discussion" in body
    assert "personal_excerpt_available: false" in body
    assert "book_id: null" in body
    assert "Continue with themes, characters, style" in body


def test_not_found_states_personal_excerpt_absence_without_user_inference():
    _, body, _ = load_skill()
    assert "当前个人书摘索引中没有找到这本书的匹配记录，因此接下来的讨论暂时不会引用你以前保存的摘录。" in body
    assert "Never turn that into a claim that the user has no notes" in body
    assert "has not read the\n  book" in body
    assert "or cannot discuss it" in body
    for forbidden_claim in (
        "你没有笔记",
        "你没读过这本书",
        "书中没有你的笔记",
        "无法讨论这本书",
        "目前没有你的个人摘录",
        "没有你的已存笔记",
    ):
        assert forbidden_claim in body
    assert "Do not replace the bounded status with any of these claims" in body


def test_not_found_default_reply_is_short_and_includes_source_handoff():
    _, body, _ = load_skill()
    assert "Keep the default reply close to this short form" in body
    assert "当前个人书摘索引中没有找到《书名》的匹配记录" in body
    assert "这不影响我们继续聊" in body
    assert "请上传系统支持读取的文件，或粘贴相关段落" in body
    assert "默认只用于当前会话，不会自动加入长期书库" in body
    assert "Do not infer facts from\n  the title" in body


def test_unavailable_is_not_reinterpreted_as_not_found():
    _, body, _ = load_skill()
    assert "`unavailable` or `error`: do not reinterpret this as `not_found`" in body
    assert "Preserve the\n  actual resolution status" in body
    assert "personal excerpt retrieval is temporarily\n  unavailable" in body
    assert "do not expose internal error\n  codes or capability details" in body


def test_general_mode_supports_feynman_without_personal_retrieval_or_web():
    _, body, _ = load_skill()
    assert "When `discussion_mode` is `general_discussion`" in body
    assert "answer in a short Feynman loop from model\nknowledge" in body
    assert "Explicitly avoid personal-excerpt retrieval and\nexternal research" in body
    assert "Do not automatically call `current_book`" in body
    assert "search the web" in body


def test_source_handoff_is_once_and_skips_redundant_cut_in_question():
    _, body, _ = load_skill()
    assert "Offer source handoff no more than once per conversation" in body
    assert "source_prompt_offered: true" in body
    assert "If the user already asked a concrete question, answer it directly" in body
    assert "Otherwise\n  ask at most one cut-in question" in body


def test_provided_text_mode_requires_actual_text_and_is_session_only():
    _, body, _ = load_skill()
    assert "Enter `provided_text_discussion` only after relevant text is actually present" in body
    assert "discussion_mode: provided_text_discussion" in body
    assert "provided_source_type: pasted_text | supported_attachment" in body
    assert "temporary_session_source: true" in body
    assert "permanent_import: false" in body
    assert "never labeled as saved personal history" in body


def test_local_path_and_epub_claims_require_real_safe_extraction():
    _, body, _ = load_skill()
    assert "A path string alone is not text" in body
    assert "do not use a\nshell" in body
    for check in ("existence", "allowed workspace", "type", "size/context budget", "sensitive paths"):
        assert check in body
    assert "actual\ntext extraction must succeed before saying it was read" in body
    assert "this runtime has\nno confirmed EPUB extractor" in body
    assert "If an attachment is binary or its\nextractor is unavailable, do not claim it was read" in body


def test_provided_source_does_not_create_persistent_book_infrastructure():
    _, body, source = load_skill()
    assert "do not update the\nEvernote index" in body
    assert "create any new vector index" in body
    assert "permanent Book Capsule" in body
    assert "Do not create a disk checkpoint" in body
    assert "never create or modify a Workflow, router, TaskMode" in source
    assert "formal_workflow_created: false" in source


def test_guided_mode_entrypoints_are_discoverable_without_replacing_mode_a():
    _, body, _ = load_skill()
    description = CATEGORY_DESCRIPTION_PATH.read_text(encoding="utf-8")
    for entrypoint in (
        "进入引导式读书模式《书名》",
        "用引导模式聊《书名》",
        "开始连续聊《书名》",
    ):
        assert entrypoint in body
        assert entrypoint in description
    assert "Route Manual Mode A Entrypoints" in body
    assert "manual Mode A entrypoints" in body
    assert "must never activate\nGuided Mode B" in body


def test_guided_mode_is_explicitly_not_a_formal_workflow_or_dag():
    _, body, _ = load_skill()
    assert "`guided_mode_b`" in body
    assert "`引导式读书模式 B`" in body
    assert "不是 Hermes 持久化 Workflow 或 DAG" in body
    assert "guided_mode_created: true" in body
    assert "formal_workflow_created: false" in body
    assert "never create or modify a Workflow, router, TaskMode" in body


def test_guided_state_is_small_and_session_only():
    _, body, _ = load_skill()
    for field in (
        "guided_mode:",
        "active_book:",
        "discussion_mode:",
        "stage:",
        "focus_question:",
        "effective_turns:",
        "retrieval_calls_this_turn:",
        "connection_used:",
    ):
        assert field in body
    assert "conversation context 的会话引导模式" in body
    assert "Do not create disk recovery" in body


def test_guided_orient_calls_resolve_once_and_does_not_retrieve_excerpts():
    _, body, _ = load_skill()
    guided = body.split("## Guided Mode B", 1)[1].split("## Route Manual Mode A", 1)[0]
    assert "make exactly\none `resolve_book` call" in guided
    assert "Do not retrieve excerpts, summarize the book, introduce\nthe author, or connect books on this orient turn" in guided
    assert "stage: orient" in guided
    assert "effective_turns: 0" in guided


def test_guided_resolved_not_found_and_ambiguous_routes_are_bounded():
    _, body, _ = load_skill()
    guided = body.split("### Orient And Explain", 1)[1].split("### Probe Short Loop", 1)[0]
    assert "`resolved`: set the guided active book, `personal_excerpt_discussion`" in guided
    assert "`not_found`: keep the supplied title with `book_id: null`" in guided
    assert "`general_discussion` and `stage: orient`" in guided
    assert "discussion can continue" in guided
    assert "Do not call `current_book`, browse" in guided
    assert "`ambiguous`: show at most five candidates" in guided
    assert "Never choose automatically" in guided


def test_guided_user_explains_first_but_is_not_asked_twice():
    _, body, _ = load_skill()
    assert "## Active Guided Turn Gate" in body
    assert "This gate has priority over answering the book question" in body
    assert "treat `guided_mode.active` as true until a Close response explicitly\nends it" in body
    assert "先不用追求完整。你用两三句话说说，你目前怎么理解这个问题？" in body
    assert "reply with exactly this one\nsentence and nothing else" in body
    assert "A question alone is not the user's explanation" in body
    assert "<!-- guided_mode_b: active; stage=awaiting_focus_question; user_explanation_received=false -->" in body
    assert "This marker is session context only. It is not a disk checkpoint" in body
    assert "the\nActive Guided Turn Gate applies without interpretation" in body
    assert "Do not answer\nit first; the Active Guided Turn Gate" in body
    assert "already contains the user's own explanation, do not\nask again" in body


def test_guided_exit_uses_the_exact_short_close_contract():
    _, body, _ = load_skill()
    gate = body.split("## Active Guided Turn Gate", 1)[1].split("## Hard Turn Contract", 1)[0]
    for label in (
        "这轮你已经说清楚了：",
        "仍然悬而未决的是：",
        "最值得带走的一个问题：",
    ):
        assert label in gate
    assert "containing these three\nlabels exactly once, in this order" in gate
    assert "do not ask a new follow-up question" in gate


def test_guided_personal_probe_reuses_only_bounded_book_notes_action():
    frontmatter, body, source = load_skill()
    guided = body.split("### Probe Short Loop", 1)[1].split("### Connect", 1)[0]
    for contract in (
        "action: current_book",
        "top_k: 3",
        "candidate_k: 20",
        "max_per_parent: 1",
        "excerpt_max_chars: 500",
        "include_text: true",
    ):
        assert contract in guided
    assert "make at most one call with the existing helper" in guided
    assert "In `general_discussion`, do not call\n`current_book`" in guided
    assert "never label it as personal history" in guided
    assert extract_skill_conditions(frontmatter)["requires_tools"] == [
        "book_notes_retrieval",
        "agy_book_dialogue",
    ]
    assert "BookNotesRetriever" not in source


def test_guided_probe_has_one_gap_one_main_question_and_one_action():
    _, body, _ = load_skill()
    guided = body.split("### Probe Short Loop", 1)[1].split("### Connect", 1)[0]
    assert "identify one main gap, and ask one\nmain follow-up question" in guided
    assert "at most one secondary question and one\ncounter-lens" in guided
    assert "choose\nonly one `next_action`" in guided
    assert "Deepen exactly one of premise, mechanism,\nboundary, counterexample, or application" in guided
    assert "Do not simulate a multi-agent discussion" in guided


def test_guided_connect_requires_probe_and_is_bounded_and_inferred():
    _, body, _ = load_skill()
    guided = body.split("### Connect", 1)[1].split("### Close, Pause, And Resume", 1)[0]
    assert "after at least one\ncompleted Probe" in guided
    assert "Automatic connection is\nallowed once per guided session" in guided
    for contract in (
        "action: other_books",
        "top_k_books: 3",
        "candidate_k: 40",
        "max_chunks_per_book: 1",
        "max_chunks_per_parent: 1",
        "relationship_intent: null",
        "excerpt_max_chars: 500",
    ):
        assert contract in guided
    assert "Select at most three books and one chunk per book" in guided
    assert "relationship with `[INFERENCE]`" in guided


def test_guided_turn_caps_early_exit_and_close_are_nonpersistent():
    _, body, _ = load_skill()
    guided = body.split("### Close, Pause, And Resume", 1)[1].split("The guided retrieval budget", 1)[0]
    assert "soft turn target is 4 and hard turn cap is 6" in guided
    for exit_phrase in ("退出引导式读书模式", "结束这轮读书讨论", "先聊到这里"):
        assert exit_phrase in guided
    assert "At 6 effective turns, closing is mandatory" in guided
    assert "guided_mode.active: false" in guided
    assert "at\nmost five short points" in guided
    assert "permanent Book Capsule" in guided
    assert "checkpoint, vector record, or telemetry" in guided


def test_guided_pause_resume_and_light_reset_are_conversation_local():
    _, body, _ = load_skill()
    assert "继续刚才的引导式读书" in body
    assert "resume the most recent stage only when the\nstate is coherent" in body
    assert "刚才的引导状态已经不完整。书名可以保留，我们重新确认一下这轮最想讨论的问题。" in body
    assert "preserve the in-context state but pause automatic\nprogression" in body


def test_guided_budget_and_forbidden_platform_changes_are_explicit():
    _, body, source = load_skill()
    for contract in (
        "current_book_results: 3",
        "other_books: 3",
        "chunks_per_other_book: 1",
        "excerpt_max_chars: 500",
        "retrieval_calls_per_turn: 1",
        "automatic_connect_per_session: 1",
        "soft_turn_target: 4",
        "hard_turn_cap: 6",
    ):
        assert contract in body
    assert "background service, memory, or runtime\nconfiguration" in body
    assert "external research" in body
    assert "lancedb" not in source.lower()
    assert "embedding" not in source.lower()


def test_guided_probe_connect_and_close_route_once_through_agy():
    frontmatter, body, _ = load_skill()
    assert extract_skill_conditions(frontmatter)["requires_tools"] == [
        "book_notes_retrieval",
        "agy_book_dialogue",
    ]
    assert "tool_name: agy_book_dialogue" in body
    assert "action: respond" in body
    assert "probe: call `agy_book_dialogue` once by default" in body
    assert "connect: call `agy_book_dialogue` once after the bounded `other_books` call" in body
    assert "close: call `agy_book_dialogue` once for the short close" in body
    assert "orient: never call `agy_book_dialogue`" in body
    assert "agy_calls_per_turn: 1" in body


def test_agy_success_is_delivered_verbatim_without_a_second_question():
    _, body, _ = load_skill()
    assert "delivery_mode: verbatim" in body
    assert "deliver the `response` field verbatim" in body
    assert "Do not summarize, rewrite, template, compress, or add a second question" in body
    assert "Remove only blank CLI wrapping" in body


def test_meta_question_pauses_guided_progress_without_agy_or_repeated_prompt():
    _, body, _ = load_skill()
    gate = body.split("## Guided Meta Question Gate", 1)[1].split("## Active Guided Turn Gate", 1)[0]
    for question in (
        "你现在用的什么模型？",
        "刚才调用了哪个工具？",
        "为什么没有找到书摘？",
        "现在是什么模式？",
        "可以退出吗？",
    ):
        assert question in gate
    assert "do not call `agy_book_dialogue`" in gate
    assert "do not repeat the previous reading question" in gate
    assert "do not increment `effective_turns`" in gate
    assert "DeepSeek V4 Flash" in gate and "Gemini 3.1 Pro (High)" in gate
    assert (
        "主会话控制器是 DeepSeek V4 Flash；引导式读书模式 B 的文学对谈轮次可由 "
        "AGY Gemini 3.1 Pro (High) 生成。本轮是元问题，没有调用 AGY。"
    ) in gate
    assert "do not mention the saved focus question" in gate
    assert "Do not claim AGY is unavailable" in gate


def test_not_found_and_unavailable_retrieval_states_are_distinct_for_agy():
    _, body, _ = load_skill()
    assert "retrieval_status: resolved" in body
    assert "personal_excerpt_available: true" in body
    assert "retrieval_status: not_found" in body
    assert "personal_excerpt_available: false" in body
    assert "retrieval_operational: true" in body
    assert "retrieval_status: unavailable" in body
    assert "personal_excerpt_available: unknown" in body
    assert "retrieval_operational: false" in body
    assert "Never describe `unavailable` as `not_found`" in body


def test_agy_failure_degrades_once_to_deepseek_without_gpt_bridge():
    _, body, _ = load_skill()
    assert "dialogue_engine: deepseek_fallback" in body
    assert "这一轮 Gemini 对谈引擎暂时不可用，我先用当前模型继续。" in body
    assert "Then continue under the existing Guided Mode B contract" in body
    assert "Never call GPT Bridge" in body
    assert "never retry AGY in the same turn" in body


def test_manual_mode_a_does_not_force_agy():
    _, body, _ = load_skill()
    manual = body.split("## Route Manual Mode A Entrypoints", 1)[1]
    assert "Mode A does not require `agy_book_dialogue`" in manual
