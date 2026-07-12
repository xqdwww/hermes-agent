#!/usr/bin/env python3
"""Offline builder for the private Evernote book-notes embedding index.

The builder is explicit and local-only. It validates metadata eligibility,
loads section text through provenance offsets, embeds eligible sections, writes a
LanceDB table, and emits an index manifest. It never stores full section text in
the vector table.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence


INDEX_SCHEMA_VERSION = "book_notes_lancedb_index_v1"
INDEX_MANIFEST_SCHEMA_VERSION = "book_notes_index_manifest_v1"
DEFAULT_TABLE_NAME = "evernote_book_notes_v1"
DEFAULT_EXPECTED_DIMENSION = 1024

TEXT_FIELD_NAMES = {"section_text", "excerpt_text", "body_text", "full_text", "content"}
STANCE_FIELD_NAMES = {"personal_reflection", "user_opinion", "user_stance", "belief", "endorsement"}


class IndexBuildError(RuntimeError):
    """Raised for safe, non-content-leaking index build failures."""


class Embedder(Protocol):
    embedding_model_id: str
    embedding_provider: str
    embedding_dimension: int
    normalize_embeddings: bool
    batch_size: int
    device: str
    dtype: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        ...


@dataclass(frozen=True)
class EligibilityResult:
    manifest_records: int
    eligible_records: list[dict[str, Any]]
    quarantined_records: list[dict[str, Any]]
    conflict_book_ids: set[str]
    validation_counts: dict[str, int]
    review_items: int
    unique_books: int

    def summary(self) -> dict[str, Any]:
        return {
            "manifest_records": self.manifest_records,
            "eligible_records": len(self.eligible_records),
            "quarantined_records": len(self.quarantined_records),
            "conflict_books": len(self.conflict_book_ids),
            "review_items": self.review_items,
            "unique_books": self.unique_books,
            **self.validation_counts,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def path_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def require_metadata_files(metadata_dir: Path) -> dict[str, Path]:
    expected = {
        "manifest": metadata_dir / "manifest.jsonl",
        "catalog": metadata_dir / "books_catalog.jsonl",
        "review": metadata_dir / "review_queue.jsonl",
        "duplicates": metadata_dir / "duplicates.jsonl",
        "stats": metadata_dir / "metadata_stats.json",
        "config": metadata_dir / "manifest_config.json",
        "readme": metadata_dir / "README.md",
    }
    missing = [str(path) for path in expected.values() if not path.is_file()]
    if missing:
        raise IndexBuildError(f"metadata_files_missing: {missing}")
    return expected


def resolve_source_path(source_root: Path, source_path: str, record_id: str) -> Path:
    raw = Path(source_path)
    if raw.is_absolute() or ".." in raw.parts:
        raise IndexBuildError(f"source_path_rejected record_id={record_id} path={source_path}")
    root = source_root.resolve()
    resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise IndexBuildError(f"source_path_outside_root record_id={record_id} path={source_path}") from exc
    return resolved


def load_section_text(record: dict[str, Any], source_root: Path) -> str:
    record_id = str(record.get("record_id") or "<missing>")
    relative_path = str(record.get("source_path") or "")
    path = resolve_source_path(source_root, relative_path, record_id)
    if not path.is_file():
        raise IndexBuildError(f"source_missing record_id={record_id} path={relative_path}")
    data = path.read_bytes()
    if sha256_bytes(data) != record.get("source_sha256"):
        raise IndexBuildError(f"source_sha256_mismatch record_id={record_id} path={relative_path}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IndexBuildError(f"source_decode_error record_id={record_id} path={relative_path}") from exc
    start = int(record.get("section_start_offset"))
    end = int(record.get("section_end_offset"))
    if not (0 <= start < end <= len(text)):
        raise IndexBuildError(f"section_offset_invalid record_id={record_id} path={relative_path}")
    section = text[start:end]
    if sha256_text(section) != record.get("section_text_sha256"):
        raise IndexBuildError(f"section_sha256_mismatch record_id={record_id} path={relative_path}")
    return section


def validate_vector(vector: Sequence[float], expected_dimension: int, record_id: str) -> list[float]:
    if len(vector) != expected_dimension:
        raise IndexBuildError(
            f"embedding_dimension_mismatch record_id={record_id} expected={expected_dimension} actual={len(vector)}"
        )
    out: list[float] = []
    for value in vector:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise IndexBuildError(f"embedding_non_finite record_id={record_id}")
        out.append(numeric)
    return out


def validate_metadata_eligibility(metadata_dir: Path, source_root: Path) -> EligibilityResult:
    files = require_metadata_files(metadata_dir)
    manifest = read_jsonl(files["manifest"])
    catalog = read_jsonl(files["catalog"])
    reviews = read_jsonl(files["review"])
    duplicates = read_jsonl(files["duplicates"])

    record_ids = [record.get("record_id") for record in manifest]
    duplicate_record_ids = len(record_ids) - len(set(record_ids))
    if duplicate_record_ids:
        raise IndexBuildError(f"duplicate_record_id count={duplicate_record_ids}")

    catalog_by_book = {row.get("book_id"): row for row in catalog}
    catalog_record_ids = {record_id for row in catalog for record_id in row.get("record_ids", [])}
    missing_catalog_refs = [record.get("record_id") for record in manifest if record.get("record_id") not in catalog_record_ids]
    if missing_catalog_refs:
        raise IndexBuildError(f"catalog_record_reference_missing count={len(missing_catalog_refs)}")

    duplicate_reference_failures = 0
    record_id_set = set(record_ids)
    source_file_ids = {record.get("source_file_id") for record in manifest}
    for row in duplicates:
        ids = [row.get("canonical_record_id"), *row.get("duplicate_record_ids", [])]
        if row.get("duplicate_type") == "source_file_sha256":
            duplicate_reference_failures += sum(1 for item in ids if item not in source_file_ids)
        else:
            duplicate_reference_failures += sum(1 for item in ids if item not in record_id_set)
    if duplicate_reference_failures:
        raise IndexBuildError(f"duplicate_reference_missing count={duplicate_reference_failures}")

    conflict_book_ids = {row["book_id"] for row in catalog if row.get("conflicts")}
    eligible: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    validation_counts = {
        "source_checksum_failures": 0,
        "section_checksum_failures": 0,
        "offset_failures": 0,
        "catalog_reference_failures": 0,
        "text_field_failures": 0,
        "stance_field_failures": 0,
    }

    for record in manifest:
        record_id = str(record.get("record_id") or "<missing>")
        if TEXT_FIELD_NAMES & set(record):
            validation_counts["text_field_failures"] += 1
            raise IndexBuildError(f"manifest_text_field_present record_id={record_id}")
        if STANCE_FIELD_NAMES & set(record):
            validation_counts["stance_field_failures"] += 1
            raise IndexBuildError(f"manifest_stance_field_present record_id={record_id}")
        if record.get("book_id") not in catalog_by_book:
            validation_counts["catalog_reference_failures"] += 1
            raise IndexBuildError(f"book_catalog_missing record_id={record_id}")
        try:
            load_section_text(record, source_root)
        except IndexBuildError as exc:
            message = str(exc)
            if "source_sha256_mismatch" in message:
                validation_counts["source_checksum_failures"] += 1
            elif "section_sha256_mismatch" in message:
                validation_counts["section_checksum_failures"] += 1
            elif "section_offset_invalid" in message:
                validation_counts["offset_failures"] += 1
            raise

        is_eligible = (
            record.get("resolution_status") == "resolved"
            and record.get("content_type") == "book_excerpt"
            and bool(record.get("book_id"))
            and record.get("book_id") not in conflict_book_ids
        )
        if is_eligible:
            eligible.append(record)
        else:
            quarantined.append(record)

    return EligibilityResult(
        manifest_records=len(manifest),
        eligible_records=eligible,
        quarantined_records=quarantined,
        conflict_book_ids=conflict_book_ids,
        validation_counts=validation_counts,
        review_items=len(reviews),
        unique_books=len(catalog),
    )


def model_fingerprint(model_path: Path) -> dict[str, Any]:
    if not model_path.is_dir():
        raise IndexBuildError(f"embedding_model_path_missing path={model_path}")
    checksum_files = [
        "config.json",
        "config_sentence_transformers.json",
        "modules.json",
        "sentence_bert_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
    ]
    checksums = {
        name: path_sha256(model_path / name)
        for name in checksum_files
        if (model_path / name).is_file()
    }
    weight_inventory = [
        {"name": path.relative_to(model_path).as_posix(), "size": path.stat().st_size}
        for path in sorted(model_path.rglob("*"))
        if path.is_file() and path.suffix in {".bin", ".safetensors", ".pt"}
    ]
    identity_payload = {
        "model_dir_name": model_path.name,
        "config_checksums": checksums,
        "weight_inventory": weight_inventory,
    }
    digest = sha256_text(json.dumps(identity_payload, ensure_ascii=False, sort_keys=True))
    return {"fingerprint": digest, **identity_payload}


class LocalSentenceTransformerEmbedder:
    def __init__(
        self,
        *,
        model_path: Path,
        expected_dimension: int,
        batch_size: int = 8,
        normalize_embeddings: bool = True,
        device: str | None = None,
        local_files_only: bool = True,
    ) -> None:
        if not model_path.is_dir():
            raise IndexBuildError(f"embedding_model_path_missing path={model_path}")
        from sentence_transformers import SentenceTransformer

        self.model_path = model_path
        self.expected_dimension = expected_dimension
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        self.device = device or "auto"
        self.embedding_provider = "sentence-transformers"
        self.embedding_model_id = model_fingerprint(model_path)["fingerprint"]
        self.embedding_dimension = expected_dimension
        self.dtype = "float32"
        self._model = SentenceTransformer(
            str(model_path),
            device=device,
            local_files_only=local_files_only,
            trust_remote_code=False,
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        rows = vectors.astype("float32").tolist()
        return [validate_vector(vector, self.expected_dimension, f"batch_{idx}") for idx, vector in enumerate(rows)]


def make_lancedb_row(record: dict[str, Any], vector: list[float], embedder: Embedder) -> dict[str, Any]:
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "record_id": record["record_id"],
        "book_id": record["book_id"],
        "book_title_normalized": record.get("book_title_normalized"),
        "author_normalized": record.get("author_normalized"),
        "source_type": record.get("source_type"),
        "content_type": record.get("content_type"),
        "source_root_id": record.get("source_root_id"),
        "source_path": record.get("source_path"),
        "source_sha256": record.get("source_sha256"),
        "source_file_id": record.get("source_file_id"),
        "section_id": record.get("section_id"),
        "section_index": int(record.get("section_index")),
        "section_start_offset": int(record.get("section_start_offset")),
        "section_end_offset": int(record.get("section_end_offset")),
        "offset_unit": record.get("offset_unit"),
        "section_text_sha256": record.get("section_text_sha256"),
        "resolution_status": record.get("resolution_status"),
        "embedding_model_id": embedder.embedding_model_id,
        "embedding_dimension": embedder.embedding_dimension,
        "vector": vector,
    }


def build_index_manifest(
    *,
    metadata_dir: Path,
    builder_commit: str | None,
    builder_path: Path,
    eligibility: EligibilityResult,
    embedder: Embedder,
    model_path: Path,
    db_path: Path,
    table_name: str,
    build_mode: str,
) -> dict[str, Any]:
    files = require_metadata_files(metadata_dir)
    return {
        "schema_version": INDEX_MANIFEST_SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "builder_commit": builder_commit,
        "builder_path": str(builder_path),
        "metadata_manifest_sha256": path_sha256(files["manifest"]),
        "books_catalog_sha256": path_sha256(files["catalog"]),
        "manifest_record_count": eligibility.manifest_records,
        "eligible_record_count": len(eligibility.eligible_records),
        "quarantined_record_count": len(eligibility.quarantined_records),
        "embedding_provider": embedder.embedding_provider,
        "embedding_model_path": str(model_path),
        "embedding_model_identity": embedder.embedding_model_id,
        "embedding_dimension": embedder.embedding_dimension,
        "normalize_embeddings": embedder.normalize_embeddings,
        "batch_size": embedder.batch_size,
        "device": embedder.device,
        "dtype": embedder.dtype,
        "vector_store_type": "lancedb",
        "db_path": str(db_path),
        "table_name": table_name,
        "record_schema_version": INDEX_SCHEMA_VERSION,
        "source_text_stored": False,
        "build_mode": build_mode,
        "build_complete": True,
        "validation_complete": True,
    }


def connect_lancedb(path: Path):
    import lancedb

    return lancedb.connect(str(path))


def validate_lancedb_table(db_path: Path, table_name: str, expected_rows: int) -> dict[str, Any]:
    db = connect_lancedb(db_path)
    table = db.open_table(table_name)
    schema_names = set(table.schema.names)
    missing = {"record_id", "book_id", "source_type", "resolution_status", "vector"} - schema_names
    if missing:
        raise IndexBuildError(f"lancedb_schema_missing fields={sorted(missing)}")
    if TEXT_FIELD_NAMES & schema_names:
        raise IndexBuildError("lancedb_text_field_present")
    rows = table.count_rows()
    if rows != expected_rows:
        raise IndexBuildError(f"lancedb_row_count_mismatch expected={expected_rows} actual={rows}")
    return {"rows": rows, "schema_fields": sorted(schema_names)}


def create_lancedb_index(
    *,
    metadata_dir: Path,
    source_root: Path,
    db_path: Path,
    table_name: str,
    model_path: Path,
    embedder: Embedder,
    expected_dimension: int,
    max_records: int | None = None,
    rebuild: bool = False,
    builder_commit: str | None = None,
    builder_path: Path | None = None,
) -> dict[str, Any]:
    if db_path.exists() and not rebuild:
        raise IndexBuildError(f"db_path_exists_without_rebuild path={db_path}")
    eligibility = validate_metadata_eligibility(metadata_dir, source_root)
    records = eligibility.eligible_records[:max_records] if max_records is not None else eligibility.eligible_records
    texts = [load_section_text(record, source_root) for record in records]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), embedder.batch_size):
        batch_texts = texts[start : start + embedder.batch_size]
        batch_records = records[start : start + embedder.batch_size]
        batch_vectors = embedder.embed_documents(batch_texts)
        if len(batch_vectors) != len(batch_texts):
            raise IndexBuildError("embedding_count_mismatch")
        for record, vector in zip(batch_records, batch_vectors):
            vectors.append(validate_vector(vector, expected_dimension, str(record["record_id"])))

    rows = [make_lancedb_row(record, vector, embedder) for record, vector in zip(records, vectors)]
    tmp_path = db_path.with_name(f".{db_path.name}.tmp_build")
    rollback_path = db_path.with_name(f".{db_path.name}.rollback")
    for path in (tmp_path, rollback_path):
        if path.exists():
            shutil.rmtree(path)
    try:
        tmp_path.mkdir(parents=True)
        db = connect_lancedb(tmp_path)
        db.create_table(table_name, data=rows, mode="overwrite")
        manifest = build_index_manifest(
            metadata_dir=metadata_dir,
            builder_commit=builder_commit,
            builder_path=builder_path or Path(__file__),
            eligibility=eligibility,
            embedder=embedder,
            model_path=model_path,
            db_path=db_path,
            table_name=table_name,
            build_mode="rebuild" if rebuild else "create",
        )
        write_json(tmp_path / "index_manifest.json", manifest)
        validation = validate_lancedb_table(tmp_path, table_name, len(rows))
        if db_path.exists():
            os.replace(db_path, rollback_path)
        os.replace(tmp_path, db_path)
        if rollback_path.exists():
            shutil.rmtree(rollback_path)
        return {
            "build_complete": True,
            "table_name": table_name,
            "rows": len(rows),
            "eligible_records": len(eligibility.eligible_records),
            "quarantined_records": len(eligibility.quarantined_records),
            "validation": validation,
        }
    except Exception:
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        if rollback_path.exists() and not db_path.exists():
            os.replace(rollback_path, db_path)
        raise


def git_head(cwd: Path) -> str | None:
    try:
        import subprocess

        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd, text=True).strip()
    except Exception:
        return None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or validate the offline Evernote book-notes LanceDB index.")
    parser.add_argument("--metadata-dir", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--table-name", default=DEFAULT_TABLE_NAME)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--expected-dimension", type=int, default=DEFAULT_EXPECTED_DIMENSION)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--local-files-only", action="store_true", default=True)
    parser.add_argument("--normalize-embeddings", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--device", default=None)
    parser.add_argument("--model-smoke", action="store_true")
    parser.add_argument("--json-summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        eligibility = validate_metadata_eligibility(args.metadata_dir, args.source_root)
        fingerprint = model_fingerprint(args.model_path)
        if args.dry_run and not args.model_smoke:
            summary = {
                "dry_run": True,
                "model_loaded": False,
                "embedding_model_identity": fingerprint["fingerprint"],
                **eligibility.summary(),
            }
        else:
            embedder = LocalSentenceTransformerEmbedder(
                model_path=args.model_path,
                expected_dimension=args.expected_dimension,
                batch_size=args.batch_size,
                normalize_embeddings=args.normalize_embeddings,
                device=args.device,
                local_files_only=args.local_files_only,
            )
            if args.dry_run and args.model_smoke:
                smoke_vectors = embedder.embed_documents(
                    [
                        "Synthetic sentence about careful reading.",
                        "人工合成的读书笔记测试句子。",
                        "Synthetic bilingual retrieval smoke test.",
                    ]
                )
                summary = {
                    "dry_run": True,
                    "model_loaded": True,
                    "model_smoke_vectors": len(smoke_vectors),
                    "embedding_dimension": len(smoke_vectors[0]) if smoke_vectors else 0,
                    **eligibility.summary(),
                }
            else:
                summary = create_lancedb_index(
                    metadata_dir=args.metadata_dir,
                    source_root=args.source_root,
                    db_path=args.db_path,
                    table_name=args.table_name,
                    model_path=args.model_path,
                    embedder=embedder,
                    expected_dimension=args.expected_dimension,
                    max_records=args.max_records,
                    rebuild=args.rebuild,
                    builder_commit=git_head(Path.cwd()),
                    builder_path=Path(__file__).resolve(),
                )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2 if args.json_summary else None))
        return 0
    except IndexBuildError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
