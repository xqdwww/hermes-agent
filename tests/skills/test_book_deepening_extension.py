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


def test_skill_requires_only_the_book_notes_retrieval_tool():
    frontmatter, body, _ = load_skill()
    conditions = extract_skill_conditions(frontmatter)
    assert conditions["requires_tools"] == ["book_notes_retrieval"]
    assert conditions["requires_toolsets"] == []
    assert "only retrieval tool" in body


def test_start_discussion_resolves_without_guessing_or_research():
    _, body, _ = load_skill()
    assert "开始讨论《书名》" in body
    assert "action: resolve_book" in body
    assert "at most five returned candidates" in body
    assert "Do not guess" in body
    assert "Do not search the\n  web, start research" in body
    assert "do not set `active_book`" in body


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
    for label in ("[BOOK]", "[OTHER_BOOK]", "[USER]", "[INFERENCE]"):
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
