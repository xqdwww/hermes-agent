from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from tools.book_notes.build_book_notes_index import (
    INDEX_SCHEMA_VERSION,
    IndexBuildError,
    create_lancedb_index,
    load_section_text,
    model_fingerprint,
    validate_metadata_eligibility,
)


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
    source_root.mkdir()
    metadata_dir.mkdir()
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
    )
    assert summary["rows"] == 3
    import lancedb

    table = lancedb.connect(str(db_path)).open_table("synthetic_table")
    rows = table.search([30.0, 31.0, 32.0, 33.0]).where("book_id = 'book_1'").limit(1).to_list()
    assert rows[0]["record_id"] == "record_1"
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
        )
    import lancedb

    ids_a = sorted(row["record_id"] for row in lancedb.connect(str(db_a)).open_table("synthetic_table").to_lance().to_table().to_pylist())
    ids_b = sorted(row["record_id"] for row in lancedb.connect(str(db_b)).open_table("synthetic_table").to_lance().to_table().to_pylist())
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
    )
    after = {path.name: path.read_bytes() for path in source_root.glob("*.txt")}
    assert before == after
