from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from tools.book_notes.retrieve_book_notes import (
    BookNotesRetriever,
    MAX_CANDIDATE_K,
    RetrievalError,
    RetrievalResponse,
    main,
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Schema:
    def __init__(self, names):
        self.names = names


class FakeQuery:
    def __init__(self, table, rows):
        self.table = table
        self.rows = list(rows)

    def where(self, expression, prefilter=False):
        self.table.filters.append((expression, prefilter))
        if " != " in expression:
            value = expression.split(" != ", 1)[1].strip("'").replace("''", "'")
            self.rows = [row for row in self.rows if row["book_id"] != value]
        elif " = " in expression:
            value = expression.split(" = ", 1)[1].strip("'").replace("''", "'")
            self.rows = [row for row in self.rows if row["book_id"] == value]
        return self

    def limit(self, count):
        self.table.limits.append(count)
        self.rows = self.rows[:count]
        return self

    def to_list(self):
        return [dict(row) for row in self.rows]


class FakeTable:
    def __init__(self, rows, fields=None):
        from tools.book_notes.retrieve_book_notes import REQUIRED_INDEX_FIELDS

        self.rows = rows
        self.schema = Schema(fields or sorted(REQUIRED_INDEX_FIELDS))
        self.filters = []
        self.limits = []
        self.searches = 0

    def search(self, vector):
        self.searches += 1
        return FakeQuery(self, sorted(self.rows, key=lambda row: row["_distance"]))


class FakeEmbedder:
    embedding_model_id = "synthetic_model"
    embedding_dimension = 4
    normalize_embeddings = True
    dtype = "float32"

    def __init__(self, vector=None):
        self.vector = vector or [1.0, 0.0, 0.0, 0.0]

    def embed_documents(self, texts):
        return [self.vector]


class FakeTokens:
    def count_tokens(self, text):
        return len(text)


def manifest(**overrides):
    value = {
        "table_name": "synthetic_notes",
        "embedding_model_identity": "synthetic_model",
        "embedding_dimension": 4,
        "normalize_embeddings": True,
        "dtype": "float32",
        "source_text_stored": False,
        "effective_model_token_limit": 64,
        "special_token_reserve": 2,
    }
    value.update(overrides)
    return value


def make_row(source_path: str, source_text: str, chunk_text: str, *, book="book_a", parent="parent_a", section="section_a", index=0, distance=0.1):
    chunk_start = source_text.index(chunk_text)
    chunk_end = chunk_start + len(chunk_text)
    section_start = source_text.index("Synthetic section")
    section_end = len(source_text)
    return {
        "index_record_id": f"chunk_{book}_{parent}_{index}",
        "parent_record_id": parent,
        "book_id": book,
        "section_id": section,
        "embedding_chunk_index": index,
        "embedding_chunk_count": 3,
        "source_path": source_path,
        "source_sha256": sha(source_text),
        "section_start_offset": section_start,
        "section_end_offset": section_end,
        "section_text_sha256": sha(source_text[section_start:section_end]),
        "chunk_start_offset_in_source": chunk_start,
        "chunk_end_offset_in_source": chunk_end,
        "chunk_text_sha256": sha(chunk_text),
        "source_type": "evernote_book_excerpt",
        "content_type": "book_excerpt",
        "resolution_status": "resolved",
        "embedding_model_identity": "synthetic_model",
        "embedding_dimension": 4,
        "normalize_embeddings": True,
        "dtype": "float32",
        "vector": [1.0, 0.0, 0.0, 0.0],
        "_distance": distance,
    }


@pytest.fixture
def fixture(tmp_path: Path):
    root = tmp_path / "sources"
    root.mkdir()
    text_a = "Heading A\nSynthetic section alpha one two three."
    text_b = "Heading B\nSynthetic section beta four five six."
    (root / "a.txt").write_text(text_a)
    (root / "b.txt").write_text(text_b)
    rows = [
        make_row("a.txt", text_a, "alpha", index=0, distance=0.10),
        make_row("a.txt", text_a, "one", index=1, distance=0.11),
        make_row("a.txt", text_a, "two", parent="parent_b", section="section_b", index=0, distance=0.12),
        make_row("b.txt", text_b, "beta", book="book_b", parent="parent_c", section="section_c", index=0, distance=0.13),
        make_row("b.txt", text_b, "four", book="book_b", parent="parent_c", section="section_c", index=1, distance=0.14),
        make_row("b.txt", text_b, "five", book="book_c", parent="parent_d", section="section_d", index=0, distance=0.15),
    ]
    table = FakeTable(rows)
    retriever = BookNotesRetriever(
        db_path=tmp_path / "db", table_name="synthetic_notes", model_path=tmp_path / "model",
        source_root=root, table=table, embedder=FakeEmbedder(), token_counter=FakeTokens(),
        index_manifest=manifest(),
    )
    return retriever, table, rows, root


def test_current_book_db_filter_and_only_requested_book(fixture):
    retriever, table, _, _ = fixture
    response = retriever.search_current_book("topic", "book_a", include_text=False)
    assert {row["book_id"] for row in response.results} == {"book_a"}
    assert table.filters[-1] == ("book_id = 'book_a'", True)


def test_other_books_db_exclusion_and_grouping(fixture):
    retriever, table, _, _ = fixture
    response = retriever.search_other_books("topic", exclude_book_id="book_a", include_text=False)
    assert {row["book_id"] for row in response.results} == {"book_b", "book_c"}
    assert table.filters[-1] == ("book_id != 'book_a'", True)
    assert all(len(book["chunks"]) <= 2 for book in response.results)


def test_parent_and_book_caps(fixture):
    retriever, _, _, _ = fixture
    current = retriever.search_current_book("topic", "book_a", max_per_parent=1, include_text=False)
    assert len({row["parent_record_id"] for row in current.results}) == len(current.results)
    other = retriever.search_other_books("topic", max_chunks_per_book=1, max_chunks_per_parent=1, include_text=False)
    assert all(len(book["chunks"]) == 1 for book in other.results)


def test_top_k_books_and_candidate_pool(fixture):
    retriever, table, _, _ = fixture
    response = retriever.search_other_books("topic", top_k_books=1, candidate_k=6, include_text=False)
    assert response.result_count == 1
    assert table.limits[-1] == 6
    assert response.raw_candidate_count > response.result_count


@pytest.mark.parametrize("intent", ["echo", "tension", "completion", None])
def test_relationship_intent_is_context_only(fixture, intent):
    retriever, _, _, _ = fixture
    response = retriever.search_other_books("topic", relationship_intent=intent, include_text=False)
    assert response.relationship_intent == intent
    assert "relationship" not in json.dumps(response.results)


def test_invalid_relationship_intent(fixture):
    with pytest.raises(RetrievalError, match="relationship_intent_invalid"):
        fixture[0].search_other_books("topic", relationship_intent="agreement")


def test_raw_distance_not_probability(fixture):
    response = fixture[0].search_current_book("topic", "book_a", include_text=False)
    assert response.raw_metric_name == "l2_distance"
    assert all(row["raw_metric_name"] == "l2_distance" for row in response.results)
    assert "probability" not in json.dumps(response.to_dict())


def test_stable_tie_break_and_repeat(fixture):
    retriever, _, rows, _ = fixture
    for row in rows:
        row["_distance"] = 0.5
    first = retriever.search_other_books("topic", include_text=False).to_dict()
    second = retriever.search_other_books("topic", include_text=False).to_dict()
    assert [x["book_id"] for x in first["results"]] == [x["book_id"] for x in second["results"]]
    assert [x["book_id"] for x in first["results"]] == sorted(x["book_id"] for x in first["results"])


def test_exact_chunk_provenance(fixture):
    result = fixture[0].search_current_book("topic", "book_a", top_k=1).results[0]
    assert result["excerpt"] == "alpha"
    assert result["excerpt_mode"] == "exact_chunk"


def test_context_clamped_to_section_and_excerpt_cap(fixture):
    result = fixture[0].search_current_book("topic", "book_a", top_k=1, context_chars=999, excerpt_max_chars=10).results[0]
    assert len(result["excerpt"]) <= 10
    assert result["excerpt_start_offset_in_source"] >= result["section_start_offset"]
    assert result["excerpt_end_offset_in_source"] <= result["section_end_offset"]
    assert result["excerpt_truncated"] is True


def test_no_text_does_not_open_source(fixture):
    retriever, _, _, root = fixture
    before = {p: p.stat().st_mtime_ns for p in root.iterdir()}
    response = retriever.search_current_book("topic", "book_a", include_text=False)
    assert all(row["excerpt"] is None for row in response.results)
    assert retriever._source_cache == {}
    assert before == {p: p.stat().st_mtime_ns for p in root.iterdir()}


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("source_sha256", "0" * 64, "source_checksum_mismatch"),
        ("section_text_sha256", "0" * 64, "section_checksum_mismatch"),
        ("chunk_text_sha256", "0" * 64, "chunk_checksum_mismatch"),
        ("chunk_end_offset_in_source", 9999, "provenance_offset_invalid"),
    ],
)
def test_provenance_failures_reject_text(fixture, field, value, error):
    fixture[2][0][field] = value
    with pytest.raises(RetrievalError, match=error):
        fixture[0].search_current_book("topic", "book_a", top_k=1)


def test_path_traversal_rejected(fixture, tmp_path):
    fixture[2][0]["source_path"] = "../outside.txt"
    with pytest.raises(RetrievalError, match="source_path_traversal"):
        fixture[0].search_current_book("topic", "book_a", top_k=1)


def test_record_book_section_mismatch(tmp_path):
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    row = {"record_id": "parent_a", "book_id": "wrong", "section_id": "section_a"}
    data = json.dumps(row) + "\n"
    (metadata / "manifest.jsonl").write_text(data)
    root = tmp_path / "sources"; root.mkdir()
    text = "Synthetic section alpha"; (root / "a").write_text(text)
    index_row = make_row("a", text, "alpha")
    with pytest.raises(RetrievalError, match="record_book_section_mismatch"):
        retriever = BookNotesRetriever(
            db_path=tmp_path / "db", table_name="synthetic_notes", model_path=tmp_path / "model",
            source_root=root, metadata_dir=metadata, table=FakeTable([index_row]), embedder=FakeEmbedder(),
            token_counter=FakeTokens(), index_manifest=manifest(metadata_manifest_sha256=sha(data)),
        )
        retriever.search_current_book("topic", "book_a", top_k=1, include_text=False)


def test_schema_missing_field(tmp_path):
    fields = {"vector"}
    with pytest.raises(RetrievalError, match="table_schema_missing_fields"):
        BookNotesRetriever(db_path=tmp_path, table_name="synthetic_notes", model_path=tmp_path / "m", source_root=tmp_path, table=FakeTable([], fields), embedder=FakeEmbedder(), token_counter=FakeTokens(), index_manifest=manifest())


@pytest.mark.parametrize(
    ("embedder", "error"),
    [
        (type("Bad", (FakeEmbedder,), {"embedding_model_id": "wrong"})(), "embedding_model_id_mismatch"),
        (type("Bad", (FakeEmbedder,), {"embedding_dimension": 3})(), "embedding_dimension_mismatch"),
        (type("Bad", (FakeEmbedder,), {"normalize_embeddings": False})(), "normalize_embeddings_mismatch"),
    ],
)
def test_embedder_contract_mismatch(tmp_path, embedder, error):
    with pytest.raises(RetrievalError, match=error):
        BookNotesRetriever(db_path=tmp_path, table_name="synthetic_notes", model_path=tmp_path / "m", source_root=tmp_path, table=FakeTable([]), embedder=embedder, token_counter=FakeTokens(), index_manifest=manifest())


def test_index_manifest_missing(tmp_path):
    with pytest.raises(RetrievalError, match="index_manifest_missing"):
        BookNotesRetriever(db_path=tmp_path, table_name="x", model_path=tmp_path, source_root=tmp_path)


@pytest.mark.parametrize("vector", [[math.nan, 0, 0, 0], [math.inf, 0, 0, 0]])
def test_query_non_finite(fixture, vector):
    fixture[0].embedder.vector = vector
    with pytest.raises(RetrievalError, match="query_embedding_non_finite"):
        fixture[0].search_current_book("topic", "book_a")


def test_query_dimension_wrong(fixture):
    fixture[0].embedder.vector = [1, 2]
    with pytest.raises(RetrievalError, match="query_embedding_dimension_mismatch"):
        fixture[0].search_current_book("topic", "book_a")


@pytest.mark.parametrize(("query", "error"), [("", "query_empty"), ("x" * 63, "query_token_limit_exceeded")])
def test_query_validation(fixture, query, error):
    with pytest.raises(RetrievalError, match=error):
        fixture[0].search_current_book(query, "book_a")


def test_hard_limits(fixture):
    with pytest.raises(RetrievalError, match="candidate_k_out_of_range"):
        fixture[0].search_current_book("topic", "book_a", candidate_k=MAX_CANDIDATE_K + 1)
    with pytest.raises(RetrievalError, match="excerpt_max_chars_out_of_range"):
        fixture[0].search_other_books("topic", excerpt_max_chars=1201)
    with pytest.raises(RetrievalError, match="candidate_k_not_greater_than_top_k"):
        fixture[0].search_current_book("topic", "book_a", top_k=5, candidate_k=5)
    with pytest.raises(RetrievalError, match="candidate_k_not_greater_than_top_k_books"):
        fixture[0].search_other_books("topic", top_k_books=5, candidate_k=5)


def test_empty_results_success(fixture):
    response = fixture[0].search_current_book("topic", "missing", include_text=False)
    assert response.results == [] and response.result_count == 0


def test_semantic_labels_and_provenance_fields(fixture):
    result = fixture[0].search_current_book("topic", "book_a", top_k=1, include_text=False).results[0]
    assert result["source_type"] == "evernote_book_excerpt"
    assert result["content_type"] == "book_excerpt"
    required = {"source_path", "source_sha256", "section_start_offset", "section_end_offset", "chunk_start_offset_in_source", "chunk_end_offset_in_source", "chunk_text_sha256"}
    assert required <= result.keys()


def test_helper_does_not_modify_table_or_sources(fixture):
    retriever, table, rows, root = fixture
    rows_before = json.dumps(rows, sort_keys=True)
    files_before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()}
    retriever.search_other_books("topic", include_text=True)
    assert json.dumps(rows, sort_keys=True) == rows_before
    assert files_before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()}
    assert not hasattr(table, "add")


def test_response_contains_query_checksum_not_query_text(fixture):
    response = fixture[0].search_current_book("private synthetic query", "book_a", include_text=False).to_dict()
    assert response["query_sha256"] == sha("private synthetic query")
    assert "query" not in response


def test_sql_literal_escaping(fixture):
    fixture[0].search_current_book("topic", "book'quoted", include_text=False)
    assert fixture[1].filters[-1][0] == "book_id = 'book''quoted'"


def test_quarantined_row_rejected_in_no_text_mode(fixture):
    fixture[2][0]["resolution_status"] = "quarantined"
    with pytest.raises(RetrievalError, match="ineligible_or_quarantined_index_row"):
        fixture[0].search_current_book("topic", "book_a", top_k=1, include_text=False)


class FakeCliRetriever:
    calls = []

    def __init__(self, **kwargs):
        self.calls.append(("init", kwargs))

    @staticmethod
    def _response(mode, intent=None):
        return RetrievalResponse(
            schema_version="book_notes_retrieval_v1", query_sha256="a" * 64,
            mode=mode, relationship_intent=intent, raw_candidate_count=0,
            result_count=0, truncated=False, model_identity="synthetic_model",
            embedding_dimension=4, index_manifest_sha256="b" * 64,
            raw_metric_name="l2_distance", results=[], timings={},
        )

    def search_current_book(self, query, book_id, **kwargs):
        self.calls.append(("current", query, book_id, kwargs))
        return self._response("current_book")

    def search_other_books(self, query, **kwargs):
        self.calls.append(("other", query, kwargs))
        return self._response("other_books", kwargs["relationship_intent"])


def cli_args(mode):
    return [mode, "--db-path", "/synthetic/db", "--table-name", "synthetic_notes",
            "--model-path", "/synthetic/model", "--source-root", "/synthetic/source",
            "--query", "synthetic query", "--no-text", "--json"]


def test_cli_current_book_json_and_no_text(monkeypatch, capsys):
    FakeCliRetriever.calls.clear()
    monkeypatch.setattr("tools.book_notes.retrieve_book_notes.BookNotesRetriever", FakeCliRetriever)
    assert main(cli_args("current-book") + ["--book-id", "book_a"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "current_book"
    assert FakeCliRetriever.calls[-1][-1]["include_text"] is False


def test_cli_other_books_json_intent_and_no_text(monkeypatch, capsys):
    FakeCliRetriever.calls.clear()
    monkeypatch.setattr("tools.book_notes.retrieve_book_notes.BookNotesRetriever", FakeCliRetriever)
    args = cli_args("other-books") + ["--exclude-book-id", "book_a", "--relationship-intent", "tension"]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "other_books" and payload["relationship_intent"] == "tension"
    assert FakeCliRetriever.calls[-1][-1]["include_text"] is False


def test_cli_output_does_not_echo_query(monkeypatch, capsys):
    monkeypatch.setattr("tools.book_notes.retrieve_book_notes.BookNotesRetriever", FakeCliRetriever)
    main(cli_args("current-book") + ["--book-id", "book_a"])
    captured = capsys.readouterr()
    assert "synthetic query" not in captured.out + captured.err
