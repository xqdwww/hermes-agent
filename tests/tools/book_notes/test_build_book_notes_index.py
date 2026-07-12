from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from tools.book_notes.build_book_notes_index import (
    INDEX_SCHEMA_VERSION,
    DEFAULT_CHUNK_OVERLAP_TOKENS,
    IndexBuildError,
    build_chunk_plan,
    create_lancedb_index,
    load_section_text,
    model_fingerprint,
    validate_metadata_eligibility,
)
from tools.book_notes.embedding_chunker import SimpleTokenCounter, plan_batches


class FakeEmbedder:
    embedding_model_id = "fake_synthetic_model"
    embedding_provider = "fake"
    embedding_dimension = 4
    normalize_embeddings = True
    batch_size = 2
    device = "cpu"
    dtype = "float32"

    def __init__(self, vectors: list[list[float]] | None = None):
        self.vectors = vectors
        self.seen_texts: list[str] = []

    def embed_documents(self, texts):
        self.seen_texts.extend(texts)
        if self.vectors is not None:
            start = len(self.seen_texts) - len(texts)
            return self.vectors[start : start + len(texts)]
        output = []
        for index, text in enumerate(texts):
            base = float(len(text) + index)
            output.append([base, base + 1.0, base + 2.0, base + 3.0])
        return output


def _token_kwargs(**overrides):
    kwargs = {
        "tokenizer": SimpleTokenCounter(),
        "token_info": {
            "effective_model_token_limit": 8192,
            "special_token_reserve": 2,
            "silent_truncation_allowed": False,
        },
        "chunk_max_tokens": 64,
        "chunk_overlap_tokens": 0,
        "max_batch_tokens": 128,
        "max_batch_items": 2,
    }
    kwargs.update(overrides)
    return kwargs


def _sha_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def _make_record(
    *,
    record_id: str,
    book_id: str,
    source_path: str,
    source_text: str,
    section_text: str,
    start: int,
    source_sha: str,
    content_type: str = "book_excerpt",
    resolution_status: str = "resolved",
) -> dict:
    end = start + len(section_text)
    return {
        "schema_version": "book_notes_metadata_v1",
        "record_id": record_id,
        "source_type": "evernote_book_excerpt",
        "content_type": content_type,
        "source_root_id": "synthetic_sources",
        "source_path": source_path,
        "source_sha256": source_sha,
        "source_size_bytes": len(source_text.encode("utf-8")),
        "source_file_id": f"source_{source_path}",
        "note_id": f"note_{source_path}",
        "note_title_raw": "Synthetic Note",
        "notebook": "synthetic",
        "tags": [],
        "created_at": None,
        "updated_at": None,
        "language": "en",
        "section_id": f"section_{record_id}",
        "section_index": 0,
        "section_heading_raw": "Synthetic Book",
        "section_heading_normalized": "Synthetic Book",
        "section_start_offset": start,
        "section_end_offset": end,
        "offset_unit": "unicode_codepoint",
        "section_text_sha256": _sha_text(section_text),
        "book_title_raw": f"Synthetic {book_id}",
        "book_title_normalized": f"Synthetic {book_id}",
        "author_raw": None,
        "author_normalized": None,
        "book_id": book_id,
        "resolution_status": resolution_status,
        "resolution_confidence": 1.0,
        "heading_detection_method": "synthetic_heading",
        "metadata_sources": {},
        "warnings": [],
    }


def synthetic_metadata(tmp_path: Path, *, include_problem: str | None = None):
    source_root = tmp_path / "sources"
    metadata_dir = tmp_path / "metadata"
    source_root.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)
    records = []
    catalog_rows = []
    source_texts = {
        "one.txt": "Synthetic Book One\nAlpha synthetic excerpt body.\n",
        "two.txt": "Synthetic Book Two\nBeta synthetic excerpt body.\n",
        "three.txt": "Synthetic Book Three\nGamma synthetic excerpt body.\n",
        "conflict.txt": "Synthetic Conflict\nConflict synthetic excerpt body.\n",
        "unresolved.txt": "Synthetic Unresolved\nUnresolved synthetic excerpt body.\n",
        "wrongtype.txt": "Synthetic Wrong Type\nWrong type synthetic excerpt body.\n",
        "missingbook.txt": "Synthetic Missing Book\nMissing book synthetic excerpt body.\n",
    }
    for name, text in source_texts.items():
        (source_root / name).write_text(text, encoding="utf-8")
    specs = [
        ("record_1", "book_1", "one.txt", "Alpha synthetic excerpt body."),
        ("record_2", "book_2", "two.txt", "Beta synthetic excerpt body."),
        ("record_3", "book_3", "three.txt", "Gamma synthetic excerpt body."),
        ("record_conflict", "book_conflict", "conflict.txt", "Conflict synthetic excerpt body."),
        ("record_unresolved", "book_unresolved", "unresolved.txt", "Unresolved synthetic excerpt body."),
        ("record_wrongtype", "book_wrongtype", "wrongtype.txt", "Wrong type synthetic excerpt body."),
        ("record_missingbook", "", "missingbook.txt", "Missing book synthetic excerpt body."),
    ]
    for record_id, book_id, source_path, section_text in specs:
        source_text = source_texts[source_path]
        record = _make_record(
            record_id=record_id,
            book_id=book_id,
            source_path=source_path,
            source_text=source_text,
            section_text=section_text,
            start=source_text.index(section_text),
            source_sha=_sha_bytes(source_text.encode("utf-8")),
            content_type="summary" if record_id == "record_wrongtype" else "book_excerpt",
            resolution_status="unresolved" if record_id == "record_unresolved" else "resolved",
        )
        records.append(record)
    if include_problem == "duplicate_record_id":
        records.append(dict(records[0]))
    if include_problem == "source_checksum":
        records[0]["source_sha256"] = "0" * 64
    if include_problem == "section_checksum":
        records[0]["section_text_sha256"] = "0" * 64
    if include_problem == "offset":
        records[0]["section_end_offset"] = 99999
    if include_problem == "path_traversal":
        records[0]["source_path"] = "../outside.txt"

    for record in records:
        conflicts = [{"conflict_type": "synthetic_conflict"}] if record["book_id"] == "book_conflict" else []
        if include_problem == "catalog_missing" and record["record_id"] == "record_1":
            record_ids = []
        else:
            record_ids = [record["record_id"]]
        catalog_rows.append(
            {
                "schema_version": "book_notes_books_catalog_v1",
                "book_id": record["book_id"],
                "book_title_normalized": record["book_title_normalized"],
                "book_title_variants": [record["book_title_normalized"]],
                "author_normalized": None,
                "author_variants": [],
                "record_count": 1,
                "source_file_count": 1,
                "total_excerpt_characters": record["section_end_offset"] - record["section_start_offset"],
                "first_seen_created_at": None,
                "last_seen_updated_at": None,
                "resolution_status": "conflict" if conflicts else "resolved",
                "conflicts": conflicts,
                "record_ids": record_ids,
            }
        )
    _write_jsonl(metadata_dir / "manifest.jsonl", records)
    _write_jsonl(metadata_dir / "books_catalog.jsonl", catalog_rows)
    _write_jsonl(metadata_dir / "review_queue.jsonl", [])
    _write_jsonl(metadata_dir / "duplicates.jsonl", [])
    (metadata_dir / "metadata_stats.json").write_text(json.dumps({"sections_total": len(records)}), encoding="utf-8")
    (metadata_dir / "manifest_config.json").write_text("{}", encoding="utf-8")
    (metadata_dir / "README.md").write_text("Synthetic metadata only.\n", encoding="utf-8")
    return source_root, metadata_dir


def synthetic_metadata_for_sections(tmp_path: Path, sections: list[tuple[str, str, str]]):
    source_root = tmp_path / "sources_custom"
    metadata_dir = tmp_path / "metadata_custom"
    source_root.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    records = []
    catalog_rows = []
    for index, (record_id, book_id, section_text) in enumerate(sections):
        source_path = f"{record_id}.txt"
        source_text = f"Heading {index}\n{section_text}\n"
        (source_root / source_path).write_text(source_text, encoding="utf-8")
        record = _make_record(
            record_id=record_id,
            book_id=book_id,
            source_path=source_path,
            source_text=source_text,
            section_text=section_text,
            start=source_text.index(section_text),
            source_sha=_sha_bytes(source_text.encode("utf-8")),
        )
        record["section_id"] = f"section_{record_id}"
        record["section_index"] = index
        records.append(record)
        catalog_rows.append(
            {
                "schema_version": "book_notes_books_catalog_v1",
                "book_id": book_id,
                "book_title_normalized": f"Synthetic {book_id}",
                "book_title_variants": [f"Synthetic {book_id}"],
                "author_normalized": None,
                "author_variants": [],
                "record_count": 1,
                "source_file_count": 1,
                "total_excerpt_characters": len(section_text),
                "first_seen_created_at": None,
                "last_seen_updated_at": None,
                "resolution_status": "resolved",
                "conflicts": [],
                "record_ids": [record_id],
            }
        )
    _write_jsonl(metadata_dir / "manifest.jsonl", records)
    _write_jsonl(metadata_dir / "books_catalog.jsonl", catalog_rows)
    _write_jsonl(metadata_dir / "review_queue.jsonl", [])
    _write_jsonl(metadata_dir / "duplicates.jsonl", [])
    (metadata_dir / "metadata_stats.json").write_text(json.dumps({"sections_total": len(records)}), encoding="utf-8")
    (metadata_dir / "manifest_config.json").write_text("{}", encoding="utf-8")
    (metadata_dir / "README.md").write_text("Synthetic metadata only.\n", encoding="utf-8")
    return source_root, metadata_dir


def _plan_for_sections(tmp_path: Path, sections: list[tuple[str, str, str]], **overrides):
    source_root, metadata_dir = synthetic_metadata_for_sections(tmp_path, sections)
    kwargs = _token_kwargs(**overrides)
    plan = build_chunk_plan(
        metadata_dir=metadata_dir,
        source_root=source_root,
        tokenizer=kwargs["tokenizer"],
        token_info=kwargs["token_info"],
        chunk_max_tokens=kwargs["chunk_max_tokens"],
        chunk_overlap_tokens=kwargs["chunk_overlap_tokens"],
        min_chunk_tokens=0,
    )
    return source_root, metadata_dir, plan


def test_eligibility_selects_three_records_and_quarantines_others(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    result = validate_metadata_eligibility(metadata_dir, source_root)
    assert [record["record_id"] for record in result.eligible_records] == ["record_1", "record_2", "record_3"]
    assert len(result.quarantined_records) == 4


@pytest.mark.parametrize("problem", ["source_checksum", "section_checksum", "offset", "path_traversal", "duplicate_record_id", "catalog_missing"])
def test_invalid_metadata_blocks_indexing(tmp_path: Path, problem: str):
    source_root, metadata_dir = synthetic_metadata(tmp_path, include_problem=problem)
    with pytest.raises(IndexBuildError):
        validate_metadata_eligibility(metadata_dir, source_root)


def test_load_section_text_returns_provenance_slice(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    result = validate_metadata_eligibility(metadata_dir, source_root)
    text = load_section_text(result.eligible_records[0], source_root)
    assert text == "Alpha synthetic excerpt body."


def test_fake_embedding_builds_lancedb_without_section_text(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    db_path = tmp_path / "synthetic_index.lancedb"
    summary = create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=db_path,
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        **_token_kwargs(),
    )
    assert summary["rows"] == 3
    import lancedb

    table = lancedb.connect(str(db_path)).open_table("synthetic_table")
    rows = table.search([30.0, 31.0, 32.0, 33.0]).where("book_id = 'book_1'").limit(1).to_list()
    assert rows[0]["parent_record_id"] == "record_1"
    assert rows[0]["record_id"] == rows[0]["index_record_id"]
    assert "section_text" not in rows[0]
    assert rows[0]["schema_version"] == INDEX_SCHEMA_VERSION
    assert (db_path / "index_manifest.json").is_file()


def test_quarantined_record_not_in_table(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    db_path = tmp_path / "synthetic_index.lancedb"
    create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=db_path,
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        **_token_kwargs(),
    )
    import lancedb

    rows = lancedb.connect(str(db_path)).open_table("synthetic_table").search([1, 2, 3, 4]).where("book_id = 'book_conflict'").limit(1).to_list()
    assert rows == []


def test_bad_embedding_dimension_and_non_finite_are_rejected(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    with pytest.raises(IndexBuildError):
        create_lancedb_index(
            metadata_dir=metadata_dir,
            source_root=source_root,
            db_path=tmp_path / "bad_dim.lancedb",
            table_name="synthetic_table",
            model_path=tmp_path,
            embedder=FakeEmbedder(vectors=[[1.0, 2.0]]),
            expected_dimension=4,
            **_token_kwargs(),
        )
    with pytest.raises(IndexBuildError):
        create_lancedb_index(
            metadata_dir=metadata_dir,
            source_root=source_root,
            db_path=tmp_path / "bad_nan.lancedb",
            table_name="synthetic_table",
            model_path=tmp_path,
            embedder=FakeEmbedder(vectors=[[1.0, math.nan, 3.0, 4.0]]),
            expected_dimension=4,
            **_token_kwargs(),
        )


def test_default_refuses_existing_db_and_rebuild_replaces_atomically(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    db_path = tmp_path / "synthetic_index.lancedb"
    create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=db_path,
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        **_token_kwargs(),
    )
    with pytest.raises(IndexBuildError):
        create_lancedb_index(
            metadata_dir=metadata_dir,
            source_root=source_root,
            db_path=db_path,
            table_name="synthetic_table",
            model_path=tmp_path,
            embedder=FakeEmbedder(),
            expected_dimension=4,
            **_token_kwargs(),
        )
    create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=db_path,
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        rebuild=True,
        **_token_kwargs(),
    )
    assert db_path.exists()
    assert not db_path.with_name(".synthetic_index.lancedb.tmp_build").exists()
    assert not db_path.with_name(".synthetic_index.lancedb.rollback").exists()


def test_failed_rebuild_preserves_old_index_and_cleans_temp(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    db_path = tmp_path / "synthetic_index.lancedb"
    create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=db_path,
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        **_token_kwargs(),
    )
    old_manifest = (db_path / "index_manifest.json").read_text(encoding="utf-8")
    with pytest.raises(IndexBuildError):
        create_lancedb_index(
            metadata_dir=metadata_dir,
            source_root=source_root,
            db_path=db_path,
            table_name="synthetic_table",
            model_path=tmp_path,
            embedder=FakeEmbedder(vectors=[[1.0, 2.0]]),
            expected_dimension=4,
            rebuild=True,
            **_token_kwargs(),
        )
    assert (db_path / "index_manifest.json").read_text(encoding="utf-8") == old_manifest
    assert not db_path.with_name(".synthetic_index.lancedb.tmp_build").exists()


def test_index_manifest_records_metadata_checksum_and_model_fingerprint_changes(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    model_a = tmp_path / "model_a"
    model_b = tmp_path / "model_b"
    model_a.mkdir()
    model_b.mkdir()
    (model_a / "config.json").write_text('{"hidden_size":4}', encoding="utf-8")
    (model_b / "config.json").write_text('{"hidden_size":5}', encoding="utf-8")
    assert model_fingerprint(model_a)["fingerprint"] != model_fingerprint(model_b)["fingerprint"]
    db_path = tmp_path / "synthetic_index.lancedb"
    create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=db_path,
        table_name="synthetic_table",
        model_path=model_a,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        **_token_kwargs(),
    )
    manifest = json.loads((db_path / "index_manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata_manifest_sha256"]
    assert manifest["source_text_stored"] is False


def test_repeated_build_has_stable_record_set(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    db_a = tmp_path / "a.lancedb"
    db_b = tmp_path / "b.lancedb"
    for db_path in (db_a, db_b):
        create_lancedb_index(
            metadata_dir=metadata_dir,
            source_root=source_root,
            db_path=db_path,
            table_name="synthetic_table",
            model_path=tmp_path,
            embedder=FakeEmbedder(),
            expected_dimension=4,
            **_token_kwargs(),
        )
    import lancedb

    ids_a = sorted(row["parent_record_id"] for row in lancedb.connect(str(db_a)).open_table("synthetic_table").to_lance().to_table().to_pylist())
    ids_b = sorted(row["parent_record_id"] for row in lancedb.connect(str(db_b)).open_table("synthetic_table").to_lance().to_table().to_pylist())
    assert ids_a == ids_b == ["record_1", "record_2", "record_3"]


def test_cli_dry_run_does_not_create_db_or_print_body(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    db_path = tmp_path / "dry_run.lancedb"
    result = subprocess.run(
        [
            sys.executable,
            "tools/book_notes/build_book_notes_index.py",
            "--metadata-dir",
            str(metadata_dir),
            "--source-root",
            str(source_root),
            "--db-path",
            str(db_path),
            "--model-path",
            str(tmp_path),
            "--expected-dimension",
            "4",
            "--dry-run",
            "--json-summary",
            "--synthetic-tokenizer",
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Alpha synthetic excerpt body" not in result.stdout
    assert "Alpha synthetic excerpt body" not in result.stderr
    assert not db_path.exists()
    assert json.loads(result.stdout)["eligible_records"] == 3


def test_source_data_not_modified(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata(tmp_path)
    before = {path.name: path.read_bytes() for path in source_root.glob("*.txt")}
    create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=tmp_path / "synthetic_index.lancedb",
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        **_token_kwargs(),
    )
    after = {path.name: path.read_bytes() for path in source_root.glob("*.txt")}
    assert before == after


def test_short_section_generates_one_chunk(tmp_path: Path):
    _, _, plan = _plan_for_sections(tmp_path, [("r1", "b1", "short excerpt")], chunk_max_tokens=64)
    assert plan.stats["embedding_chunks"] == 1
    assert plan.chunks[0].embedding_chunk_index == 0
    assert plan.chunks[0].embedding_chunk_count == 1
    assert plan.chunks[0].parent_record_id == "r1"


def test_long_section_generates_multiple_chunks_without_crossing_section(tmp_path: Path):
    long_text = "a" * 130
    _, _, plan = _plan_for_sections(tmp_path, [("r1", "b1", long_text), ("r2", "b2", "b" * 20)], chunk_max_tokens=50)
    assert plan.stats["embedding_chunks"] >= 4
    assert {chunk.parent_record_id for chunk in plan.chunks if chunk.book_id == "b1"} == {"r1"}
    assert {chunk.book_id for chunk in plan.chunks if chunk.parent_record_id == "r2"} == {"b2"}
    assert max(chunk.chunk_token_count for chunk in plan.chunks) <= 50


def test_paragraph_first_chunking_prefers_paragraph_boundaries(tmp_path: Path):
    text = "a" * 20 + "\n\n" + "b" * 20 + "\n\n" + "c" * 20
    _, _, plan = _plan_for_sections(tmp_path, [("r1", "b1", text)], chunk_max_tokens=45)
    assert len(plan.chunks) == 2
    assert plan.chunks[0].text.endswith("\n\n")
    assert plan.chunks[0].chunking_strategy == "paragraph"


def test_oversized_paragraph_splits_on_sentence_boundary(tmp_path: Path):
    text = "a" * 20 + ". " + "b" * 20 + ". " + "c" * 20 + "."
    _, _, plan = _plan_for_sections(tmp_path, [("r1", "b1", text)], chunk_max_tokens=45)
    assert len(plan.chunks) == 2
    assert {chunk.chunking_strategy for chunk in plan.chunks} == {"sentence"}
    assert all(chunk.chunk_token_count <= 45 for chunk in plan.chunks)


def test_oversized_sentence_uses_token_window_fallback(tmp_path: Path):
    text = "x" * 121
    _, _, plan = _plan_for_sections(tmp_path, [("r1", "b1", text)], chunk_max_tokens=40, chunk_overlap_tokens=5)
    assert len(plan.chunks) >= 4
    assert {chunk.chunking_strategy for chunk in plan.chunks} == {"token_window"}
    assert all(chunk.chunk_token_count <= 40 for chunk in plan.chunks)
    assert plan.chunks[1].chunk_start_offset_in_section < plan.chunks[0].chunk_end_offset_in_section


def test_chunk_offsets_and_checksums_roundtrip_to_source(tmp_path: Path):
    source_root, _, plan = _plan_for_sections(tmp_path, [("r1", "b1", "alpha\n\nbeta" * 10)], chunk_max_tokens=30)
    for chunk in plan.chunks:
        source = (source_root / chunk.source_path).read_text(encoding="utf-8")
        sliced = source[chunk.chunk_start_offset_in_source : chunk.chunk_end_offset_in_source]
        assert sliced == chunk.text
        assert _sha_text(sliced) == chunk.chunk_text_sha256
        assert chunk.offset_unit == "unicode_codepoint"


def test_chunk_ids_and_config_fingerprint_are_stable(tmp_path: Path):
    sections = [("r1", "b1", "abc" * 80)]
    _, _, plan_a = _plan_for_sections(tmp_path / "a", sections, chunk_max_tokens=50)
    _, _, plan_b = _plan_for_sections(tmp_path / "b", sections, chunk_max_tokens=50)
    _, _, plan_c = _plan_for_sections(tmp_path / "c", sections, chunk_max_tokens=60)
    assert [chunk.index_record_id for chunk in plan_a.chunks] == [chunk.index_record_id for chunk in plan_b.chunks]
    assert plan_a.config.fingerprint() != plan_c.config.fingerprint()
    assert [chunk.parent_record_id for chunk in plan_a.chunks] == ["r1"] * len(plan_a.chunks)


def test_chunk_indexes_are_contiguous_and_counts_are_correct(tmp_path: Path):
    _, _, plan = _plan_for_sections(tmp_path, [("r1", "b1", "z" * 125)], chunk_max_tokens=30)
    indexes = [chunk.embedding_chunk_index for chunk in plan.chunks]
    assert indexes == list(range(len(plan.chunks)))
    assert {chunk.embedding_chunk_count for chunk in plan.chunks} == {len(plan.chunks)}


def test_plan_rows_do_not_include_excerpt_text(tmp_path: Path):
    _, _, plan = _plan_for_sections(tmp_path, [("r1", "b1", "private synthetic body")], chunk_max_tokens=64)
    row = plan.chunks[0].public_row()
    assert "text" not in row
    assert "private synthetic body" not in json.dumps(row, ensure_ascii=False)


def test_token_budget_batching_respects_token_and_item_limits(tmp_path: Path):
    _, _, plan = _plan_for_sections(tmp_path, [("r1", "b1", "a" * 100), ("r2", "b2", "b" * 60)], chunk_max_tokens=25)
    batches = plan_batches(plan.chunks, max_batch_tokens=50, max_batch_items=2)
    assert batches
    assert all(batch.token_count <= 50 for batch in batches)
    assert all(batch.item_count <= 2 for batch in batches)
    assert batches[0].public_row()["first_index_record_id"]


def test_plan_only_cli_writes_private_free_plan_and_no_lancedb(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata_for_sections(tmp_path, [("r1", "b1", "secret synthetic excerpt")])
    db_path = tmp_path / "no_db.lancedb"
    plan_dir = tmp_path / "plan"
    result = subprocess.run(
        [
            sys.executable,
            "tools/book_notes/build_book_notes_index.py",
            "--metadata-dir",
            str(metadata_dir),
            "--source-root",
            str(source_root),
            "--db-path",
            str(db_path),
            "--model-path",
            str(tmp_path),
            "--plan-only",
            "--plan-output-dir",
            str(plan_dir),
            "--chunk-max-tokens",
            "64",
            "--chunk-overlap-tokens",
            "0",
            "--synthetic-tokenizer",
            "--json-summary",
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        check=True,
    )
    assert not db_path.exists()
    assert (plan_dir / "chunk_plan.jsonl").is_file()
    combined = result.stdout + result.stderr + (plan_dir / "chunk_plan.jsonl").read_text(encoding="utf-8")
    assert "secret synthetic excerpt" not in combined


def test_progress_events_and_stop_are_resumable_without_publishing(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata_for_sections(tmp_path, [("r1", "b1", "a" * 100)])
    db_path = tmp_path / "stopped.lancedb"
    progress_path = tmp_path / "progress.json"
    events_path = tmp_path / "events.jsonl"
    summary = create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=db_path,
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        progress_path=progress_path,
        events_path=events_path,
        stop_after_seconds=0,
        **_token_kwargs(chunk_max_tokens=25, max_batch_tokens=25, max_batch_items=1),
    )
    assert summary["stopped"] is True
    assert not db_path.exists()
    assert db_path.with_name(".stopped.lancedb.tmp_build").exists()
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["status"] == "stopped"
    assert progress["resumable"] is True
    assert "secret" not in progress_path.read_text(encoding="utf-8")
    assert all(json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines())


def test_resume_completes_without_duplicate_rows_and_matches_uninterrupted(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata_for_sections(tmp_path, [("r1", "b1", "a" * 100)])
    kwargs = _token_kwargs(chunk_max_tokens=25, max_batch_tokens=25, max_batch_items=1)
    uninterrupted = tmp_path / "uninterrupted.lancedb"
    resumed = tmp_path / "resumed.lancedb"
    create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=uninterrupted,
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        **kwargs,
    )
    create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=resumed,
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        stop_after_seconds=0,
        **kwargs,
    )
    create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=resumed,
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        resume=True,
        **kwargs,
    )
    import lancedb

    rows_a = sorted(
        lancedb.connect(str(uninterrupted)).open_table("synthetic_table").to_lance().to_table().to_pylist(),
        key=lambda row: row["index_record_id"],
    )
    rows_b = sorted(
        lancedb.connect(str(resumed)).open_table("synthetic_table").to_lance().to_table().to_pylist(),
        key=lambda row: row["index_record_id"],
    )
    assert [row["index_record_id"] for row in rows_a] == [row["index_record_id"] for row in rows_b]
    assert [row["vector"] for row in rows_a] == [row["vector"] for row in rows_b]


def test_resume_rejects_metadata_model_chunk_and_builder_mismatch(tmp_path: Path):
    source_root, metadata_dir = synthetic_metadata_for_sections(tmp_path, [("r1", "b1", "a" * 100)])
    db_path = tmp_path / "resume_guard.lancedb"
    kwargs = _token_kwargs(chunk_max_tokens=25, max_batch_tokens=25, max_batch_items=1)
    create_lancedb_index(
        metadata_dir=metadata_dir,
        source_root=source_root,
        db_path=db_path,
        table_name="synthetic_table",
        model_path=tmp_path,
        embedder=FakeEmbedder(),
        expected_dimension=4,
        stop_after_seconds=0,
        **kwargs,
    )
    checkpoint = db_path.with_name(".resume_guard.lancedb.tmp_build") / "build_checkpoint.json"
    original = checkpoint.read_text(encoding="utf-8")
    for field, value in [
        ("metadata_manifest_sha256", "bad"),
        ("embedding_model_identity", "bad"),
        ("chunking_config_fingerprint", "bad"),
        ("builder_schema_version", "bad"),
    ]:
        payload = json.loads(original)
        payload[field] = value
        checkpoint.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(IndexBuildError):
            create_lancedb_index(
                metadata_dir=metadata_dir,
                source_root=source_root,
                db_path=db_path,
                table_name="synthetic_table",
                model_path=tmp_path,
                embedder=FakeEmbedder(),
                expected_dimension=4,
                resume=True,
                **kwargs,
            )
        checkpoint.write_text(original, encoding="utf-8")
