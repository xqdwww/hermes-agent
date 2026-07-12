from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.book_notes.retrieve_book_notes import RetrievalError, RetrievalResponse
from tools.book_notes_retrieval_tool import (
    AMBIGUOUS_CANDIDATES_MAX,
    BOOK_NOTES_RETRIEVAL_SCHEMA,
    CURRENT_CANDIDATE_K_MAX,
    CURRENT_TOP_K_MAX,
    EXCERPT_MAX_CHARS_MAX,
    OTHER_CANDIDATE_K_MAX,
    OTHER_TOP_K_BOOKS_MAX,
    BookNotesToolConfig,
    BookResolver,
    RuntimeManager,
    handle_book_notes_retrieval,
)
from tools.registry import registry


class IdentityTable:
    def __init__(self, rows):
        self.rows = rows

    def identity_rows(self):
        return list(self.rows)


def write_catalog(path: Path, rows):
    path.mkdir(parents=True)
    (path / "books_catalog.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def config(tmp_path: Path):
    db = tmp_path / "db"; db.mkdir()
    (db / "index_manifest.json").write_text("{}")
    metadata = tmp_path / "metadata"
    source = tmp_path / "source"; source.mkdir()
    model = tmp_path / "model"; model.mkdir()
    return BookNotesToolConfig(db=db.resolve(), table="synthetic", metadata=metadata.resolve(), source=source.resolve(), model=model.resolve())


def catalog_rows():
    return [
        {"book_id": "book_a", "book_title_normalized": "Synthetic Alpha", "author_normalized": "Author One", "resolution_status": "resolved", "conflicts": []},
        {"book_id": "book_b", "book_title_normalized": "Synthetic Shared", "author_normalized": "Author One", "resolution_status": "resolved", "conflicts": []},
        {"book_id": "book_c", "book_title_normalized": "Synthetic Shared", "author_normalized": "Author Two", "resolution_status": "resolved", "conflicts": []},
        {"book_id": "book_conflict", "book_title_normalized": "Synthetic Conflict", "author_normalized": None, "resolution_status": "conflict", "conflicts": ["synthetic"]},
        {"book_id": "book_unindexed", "book_title_normalized": "Synthetic Unindexed", "author_normalized": None, "resolution_status": "resolved", "conflicts": []},
    ]


@pytest.fixture
def resolver_fixture(tmp_path):
    cfg = config(tmp_path)
    write_catalog(cfg.metadata, catalog_rows())
    table = IdentityTable([
        {"book_id": "book_a", "parent_record_id": "parent_a"},
        {"book_id": "book_a", "parent_record_id": "parent_b"},
        {"book_id": "book_b", "parent_record_id": "parent_c"},
        {"book_id": "book_c", "parent_record_id": "parent_d"},
        {"book_id": "book_conflict", "parent_record_id": "parent_e"},
    ])
    return cfg, BookResolver(cfg, table=table)


def test_registered_once_and_discovery_schema():
    entry = registry.get_entry("book_notes_retrieval")
    assert entry is not None
    assert registry.get_all_tool_names().count("book_notes_retrieval") == 1
    assert entry.is_async is True and entry.toolset == "book-notes"
    assert entry.schema is BOOK_NOTES_RETRIEVAL_SCHEMA


def test_schema_actions_limits_and_readonly_description():
    schema = BOOK_NOTES_RETRIEVAL_SCHEMA
    properties = schema["parameters"]["properties"]
    assert properties["action"]["enum"] == ["resolve_book", "current_book", "other_books"]
    assert properties["top_k"]["maximum"] == CURRENT_TOP_K_MAX == 8
    assert properties["top_k_books"]["maximum"] == OTHER_TOP_K_BOOKS_MAX == 8
    assert properties["candidate_k"]["maximum"] == OTHER_CANDIDATE_K_MAX == 120
    assert properties["excerpt_max_chars"]["maximum"] == EXCERPT_MAX_CHARS_MAX == 800
    description = schema["description"].lower()
    assert "read-only" in description and "does not imply endorsement" in description


def test_schema_has_no_arbitrary_path_or_table_parameters():
    forbidden = {"path", "db_path", "source_root", "model_path", "metadata_dir", "table_name"}
    properties = set(BOOK_NOTES_RETRIEVAL_SCHEMA["parameters"]["properties"])
    assert not properties & forbidden
    assert "additionalProperties" in BOOK_NOTES_RETRIEVAL_SCHEMA["parameters"]
    assert BOOK_NOTES_RETRIEVAL_SCHEMA["parameters"]["additionalProperties"] is False


def test_import_discovery_does_not_load_model_or_open_db(tmp_path):
    marker = tmp_path / "marker"
    code = (
        "import sys; from tools.registry import registry; "
        "import tools.book_notes_retrieval_tool; "
        "print(int('sentence_transformers' in sys.modules), int('lancedb' in sys.modules), "
        "registry.get_all_tool_names().count('book_notes_retrieval'))"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[3], text=True, capture_output=True)
    assert result.returncode == 0 and result.stdout.strip() == "0 0 1"
    assert not marker.exists()


def test_resolve_exact_normalized_title(resolver_fixture):
    result = resolver_fixture[1].resolve("# 《Synthetic Alpha》")
    assert result["status"] == "resolved" and result["book_id"] == "book_a"
    assert result["indexed_chunk_count"] == 2 and result["indexed_parent_count"] == 2


def test_resolve_title_and_author(resolver_fixture):
    result = resolver_fixture[1].resolve("Synthetic Shared", "Author Two")
    assert result["status"] == "resolved" and result["book_id"] == "book_c"


@pytest.mark.parametrize(
    ("title", "status"),
    [("No Such Synthetic Title", "not_found"), ("Synthetic Share", "not_found"), ("Synthetic Conflict", "not_found"), ("Synthetic Unindexed", "not_found")],
)
def test_resolve_not_found_no_fuzzy_or_ineligible(resolver_fixture, title, status):
    assert resolver_fixture[1].resolve(title)["status"] == status


def test_resolve_ambiguous_is_bounded(resolver_fixture):
    result = resolver_fixture[1].resolve("Synthetic Shared")
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 2 <= AMBIGUOUS_CANDIDATES_MAX


@dataclass
class FakeResolver:
    indexed: set[str]
    calls: int = 0

    def is_indexed(self, book_id):
        return book_id in self.indexed

    def resolve(self, title, author=None):
        self.calls += 1
        if title == "ambiguous":
            return {"status": "ambiguous", "candidates": [{"book_id": "a"}, {"book_id": "b"}]}
        if title == "missing":
            return {"status": "not_found", "candidates": []}
        return {"status": "resolved", "book_id": "book_a", "book_title_normalized": "Synthetic Alpha", "author_normalized": author, "indexed_chunk_count": 2, "indexed_parent_count": 1}


def chunk(book="book_a", parent="parent_a", index=0, excerpt="synthetic excerpt"):
    return {
        "rank": index + 1, "book_id": book, "book_title_normalized": "Synthetic Title", "author_normalized": None,
        "parent_record_id": parent, "section_id": f"section_{parent}", "index_record_id": f"chunk_{book}_{parent}_{index}",
        "embedding_chunk_index": index, "embedding_chunk_count": 2, "raw_metric_name": "l2_distance", "raw_metric_value": 0.1 + index,
        "source_type": "evernote_book_excerpt", "content_type": "book_excerpt", "source_path": "synthetic.txt",
        "section_start_offset": 10, "section_end_offset": 100, "chunk_start_offset_in_source": 20,
        "chunk_end_offset_in_source": 40, "chunk_text_sha256": "a" * 64, "excerpt": excerpt,
        "excerpt_truncated": False,
    }


class FakeRetriever:
    def __init__(self):
        self.current_calls = []
        self.other_calls = []
        self.fail = None

    def _response(self, mode, results, intent=None):
        return RetrievalResponse(
            schema_version="x", query_sha256="b" * 64, mode=mode, relationship_intent=intent,
            raw_candidate_count=9, result_count=len(results), truncated=True, model_identity="synthetic_model",
            embedding_dimension=4, index_manifest_sha256="c" * 64, raw_metric_name="l2_distance",
            results=results, timings={},
        )

    def search_current_book(self, query, book_id, **kwargs):
        self.current_calls.append((query, book_id, kwargs))
        if self.fail:
            raise RetrievalError(self.fail)
        results = [chunk(book_id, "parent_a", 0, None if not kwargs["include_text"] else "synthetic excerpt")]
        return self._response("current_book", results)

    def search_other_books(self, query, **kwargs):
        self.other_calls.append((query, kwargs))
        if self.fail:
            raise RetrievalError(self.fail)
        item = chunk("book_b", "parent_b", 0, None if not kwargs["include_text"] else "synthetic excerpt")
        grouped = [{"rank": 1, "book_id": "book_b", "book_title_normalized": "Synthetic B", "author_normalized": None,
                    "raw_metric_name": "l2_distance", "raw_metric_value": 0.1, "parent_record_ids": ["parent_b"], "chunks": [item]}]
        return self._response("other_books", grouped, kwargs["relationship_intent"])


class FakeManager:
    def __init__(self, cfg, resolver, retriever):
        self.cfg, self._resolver, self._retriever = cfg, resolver, retriever
        self.resolver_calls = 0
        self.retriever_calls = 0

    def resolver(self):
        self.resolver_calls += 1
        return self.cfg, self._resolver

    def retriever(self):
        self.retriever_calls += 1
        return self.cfg, self._resolver, self._retriever


@pytest.fixture
def manager_fixture(tmp_path):
    cfg = config(tmp_path)
    resolver = FakeResolver({"book_a", "book_b"})
    retriever = FakeRetriever()
    return FakeManager(cfg, resolver, retriever)


def call(manager, **args):
    return json.loads(handle_book_notes_retrieval(args, manager=manager))


def test_resolve_action_does_not_initialize_retriever(manager_fixture):
    result = call(manager_fixture, action="resolve_book", book_title="Synthetic Alpha")
    assert result["status"] == "resolved" and manager_fixture.retriever_calls == 0


@pytest.mark.parametrize("selector", [{"book_id": "book_a"}, {"book_title": "Synthetic Alpha"}])
def test_current_book_by_id_or_title(manager_fixture, selector):
    result = call(manager_fixture, action="current_book", query="synthetic query", **selector)
    assert result["status"] == "ok" and result["results"][0]["book_id"] == "book_a"
    assert manager_fixture._retriever.current_calls[-1][1] == "book_a"


def test_ambiguous_current_blocks_search(manager_fixture):
    result = call(manager_fixture, action="current_book", query="synthetic", book_title="ambiguous")
    assert result["status"] == "ambiguous" and result["error_code"] == "book_ambiguous"
    assert manager_fixture._retriever.current_calls == []
    assert manager_fixture.retriever_calls == 0


def test_current_limits_and_no_text_forwarded(manager_fixture):
    result = call(manager_fixture, action="current_book", query="synthetic", book_id="book_a", top_k=8,
                  candidate_k=CURRENT_CANDIDATE_K_MAX, max_per_parent=2, excerpt_max_chars=800, include_text=False)
    kwargs = manager_fixture._retriever.current_calls[-1][2]
    assert kwargs == {"top_k": 8, "candidate_k": 100, "max_per_parent": 2, "excerpt_max_chars": 800, "include_text": False}
    assert result["results"][0]["excerpt"] is None


@pytest.mark.parametrize("field,value", [("top_k", 9), ("candidate_k", 101), ("max_per_parent", 3), ("excerpt_max_chars", 801)])
def test_current_parameter_hard_limits(manager_fixture, field, value):
    result = call(manager_fixture, action="current_book", query="synthetic", book_id="book_a", **{field: value})
    assert result["status"] == "invalid_request" and result["error_code"] == "parameter_out_of_range"


@pytest.mark.parametrize("selector", [{"exclude_book_id": "book_a"}, {"exclude_book_title": "Synthetic Alpha"}])
def test_other_books_exclusion_by_id_or_title(manager_fixture, selector):
    result = call(manager_fixture, action="other_books", query="synthetic", include_text=False, **selector)
    assert result["status"] == "ok" and result["results"][0]["book_id"] == "book_b"
    assert manager_fixture._retriever.other_calls[-1][1]["exclude_book_id"] == "book_a"


def test_ambiguous_exclude_blocks_search(manager_fixture):
    result = call(manager_fixture, action="other_books", query="synthetic", exclude_book_title="ambiguous")
    assert result["status"] == "ambiguous" and manager_fixture._retriever.other_calls == []
    assert manager_fixture.retriever_calls == 0


@pytest.mark.parametrize("intent", ["echo", "tension", "completion", None])
def test_relationship_intent_is_only_forwarded(manager_fixture, intent):
    result = call(manager_fixture, action="other_books", query="synthetic", relationship_intent=intent)
    assert result["relationship_intent"] == intent
    assert result["relationship_classification_performed"] is False
    assert [book["book_id"] for book in result["results"]] == ["book_b"]


def test_invalid_relationship_intent(manager_fixture):
    result = call(manager_fixture, action="other_books", query="synthetic", relationship_intent="support")
    assert result["error_code"] == "invalid_relationship_intent"


def test_other_limits_forwarded(manager_fixture):
    call(manager_fixture, action="other_books", query="synthetic", top_k_books=8, candidate_k=120,
         max_chunks_per_book=3, max_chunks_per_parent=2, excerpt_max_chars=800)
    kwargs = manager_fixture._retriever.other_calls[-1][1]
    assert kwargs["top_k_books"] == 8 and kwargs["candidate_k"] == 120
    assert kwargs["max_chunks_per_book"] == 3 and kwargs["max_chunks_per_parent"] == 2


@pytest.mark.parametrize("field,value", [("top_k_books", 9), ("candidate_k", 121), ("max_chunks_per_book", 4), ("max_chunks_per_parent", 3)])
def test_other_parameter_hard_limits(manager_fixture, field, value):
    result = call(manager_fixture, action="other_books", query="synthetic", **{field: value})
    assert result["error_code"] == "parameter_out_of_range"


@pytest.mark.parametrize(
    ("args", "code"),
    [
        ({"action": "bad"}, "invalid_action"),
        ({"action": "current_book", "query": "", "book_id": "book_a"}, "missing_query"),
        ({"action": "current_book", "query": "x",}, "missing_book_selector"),
        ({"action": "current_book", "query": "x", "book_id": "missing"}, "book_not_indexed"),
        ({"action": "other_books", "query": "x" * 2001}, "query_too_long"),
    ],
)
def test_stable_request_errors(manager_fixture, args, code):
    output = handle_book_notes_retrieval(args, manager=manager_fixture)
    result = json.loads(output)
    assert result["error_code"] == code and "traceback" not in output.lower()
    if code == "query_too_long":
        assert "x" * 100 not in output


def test_output_guards_metrics_and_safe_relative_source(manager_fixture):
    output = call(manager_fixture, action="current_book", query="synthetic", book_id="book_a")
    item = output["results"][0]
    assert output["read_only"] is True and output["user_endorsement_inferred"] is False
    assert output["similarity_probability_claimed"] is False and output["raw_metric_name"] == "l2_distance"
    assert item["source_label"] == "MY_BOOK_EXCERPT"
    assert item["interpretation_guard"] == "saved_excerpt_not_user_endorsement"
    assert item["source_path"] == "synthetic.txt" and not Path(item["source_path"]).is_absolute()


def test_output_does_not_expose_controlled_paths(manager_fixture):
    output = handle_book_notes_retrieval({"action": "current_book", "query": "synthetic", "book_id": "book_a"}, manager=manager_fixture)
    assert str(manager_fixture.cfg.db) not in output
    assert str(manager_fixture.cfg.model) not in output
    assert str(manager_fixture.cfg.source) not in output


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        ("source_checksum_mismatch", "provenance_error", "provenance_validation_failed"),
        ("model_fingerprint_mismatch", "unavailable", "model_fingerprint_mismatch"),
        ("query_embedding_dimension_mismatch", "unavailable", "embedding_dimension_mismatch"),
    ],
)
def test_retrieval_errors_are_sanitized(manager_fixture, failure, status, code):
    manager_fixture._retriever.fail = failure
    output = handle_book_notes_retrieval({"action": "current_book", "query": "private synthetic query", "book_id": "book_a"}, manager=manager_fixture)
    result = json.loads(output)
    assert result["status"] == status and result["error_code"] == code
    assert "private synthetic query" not in output and "traceback" not in output.lower()


def test_runtime_manager_thread_safe_single_initialization(tmp_path):
    cfg = config(tmp_path)
    counts = {"resolver": 0, "retriever": 0}
    resolver = FakeResolver({"book_a"})
    retriever = FakeRetriever()

    def resolver_factory(_cfg):
        counts["resolver"] += 1; time.sleep(0.01); return resolver

    def retriever_factory(**_kwargs):
        counts["retriever"] += 1; time.sleep(0.01); return retriever

    manager = RuntimeManager(config_factory=lambda: cfg, resolver_factory=resolver_factory, retriever_factory=retriever_factory)
    threads = [threading.Thread(target=manager.retriever) for _ in range(8)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert counts == {"resolver": 1, "retriever": 1}


def test_failed_initialization_leaves_no_singleton_and_retries(tmp_path):
    cfg = config(tmp_path)
    calls = {"count": 0}

    def factory(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1: raise RuntimeError("synthetic failure")
        return FakeRetriever()

    manager = RuntimeManager(config_factory=lambda: cfg, resolver_factory=lambda _cfg: FakeResolver({"book_a"}), retriever_factory=factory)
    with pytest.raises(RuntimeError): manager.retriever()
    assert manager._retriever is None
    assert manager.retriever()[2] is not None and calls["count"] == 2


def test_cache_invalidates_when_manifest_changes(tmp_path):
    cfg = config(tmp_path)
    calls = {"count": 0}
    manager = RuntimeManager(config_factory=lambda: cfg, resolver_factory=lambda _cfg: FakeResolver({"book_a"}),
                             retriever_factory=lambda **_kwargs: (calls.update(count=calls["count"] + 1) or FakeRetriever()))
    first = manager.retriever()[2]
    (cfg.db / "index_manifest.json").write_text('{"changed": true}')
    second = manager.retriever()[2]
    assert first is not second and calls["count"] == 2


def test_cache_invalidates_when_model_fingerprint_changes(tmp_path):
    cfg = config(tmp_path)
    calls = {"count": 0}
    manager = RuntimeManager(config_factory=lambda: cfg, resolver_factory=lambda _cfg: FakeResolver({"book_a"}),
                             retriever_factory=lambda **_kwargs: (calls.update(count=calls["count"] + 1) or FakeRetriever()))
    first = manager.retriever()[2]
    (cfg.model / "config.json").write_text('{"synthetic": true}')
    second = manager.retriever()[2]
    assert first is not second and calls["count"] == 2


def test_resolve_after_search_preserves_matching_runtime(tmp_path):
    cfg = config(tmp_path)
    manager = RuntimeManager(config_factory=lambda: cfg, resolver_factory=lambda _cfg: FakeResolver({"book_a"}),
                             retriever_factory=lambda **_kwargs: FakeRetriever())
    first = manager.retriever()[2]
    manager.resolver()
    assert manager.retriever()[2] is first


def test_async_registry_handler_uses_async_contract(manager_fixture, monkeypatch):
    monkeypatch.setattr("tools.book_notes_retrieval_tool._runtime_manager", manager_fixture)
    entry = registry.get_entry("book_notes_retrieval")
    result = json.loads(asyncio.run(entry.handler({"action": "resolve_book", "book_title": "Synthetic Alpha"})))
    assert result["status"] == "resolved"


def test_registry_dispatch_bridges_async_handler(manager_fixture, monkeypatch):
    monkeypatch.setattr("tools.book_notes_retrieval_tool._runtime_manager", manager_fixture)
    result = json.loads(registry.dispatch(
        "book_notes_retrieval",
        {"action": "resolve_book", "book_title": "Synthetic Alpha"},
    ))
    assert result["status"] == "resolved" and result["read_only"] is True


def test_direct_calls_do_not_modify_synthetic_resources(manager_fixture):
    roots = [manager_fixture.cfg.db, manager_fixture.cfg.metadata, manager_fixture.cfg.source, manager_fixture.cfg.model]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for root in roots for p in root.rglob("*") if p.is_file()}
    call(manager_fixture, action="current_book", query="synthetic", book_id="book_a")
    call(manager_fixture, action="other_books", query="synthetic", exclude_book_id="book_a")
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for root in roots for p in root.rglob("*") if p.is_file()}
    assert before == after
