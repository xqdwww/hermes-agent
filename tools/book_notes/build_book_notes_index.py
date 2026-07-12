#!/usr/bin/env python3
"""Offline builder for the private Evernote book-notes embedding index.

The builder validates canonical Slice A metadata, derives deterministic
embedding chunks, writes chunk-level LanceDB rows, and emits progress/checkpoint
state for observable and resumable local builds. It never stores excerpt text in
the vector table.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import platform
import resource
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

try:
    from tools.book_notes.embedding_chunker import (
        BatchPlan,
        ChunkPlanItem,
        ChunkingConfig,
        SimpleTokenCounter,
        TokenCounter,
        chunk_section,
        plan_batches,
        sha256_text,
        summarize_plan,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.book_notes.embedding_chunker import (
        BatchPlan,
        ChunkPlanItem,
        ChunkingConfig,
        SimpleTokenCounter,
        TokenCounter,
        chunk_section,
        plan_batches,
        sha256_text,
        summarize_plan,
    )


INDEX_SCHEMA_VERSION = "book_notes_lancedb_chunk_index_v1"
INDEX_MANIFEST_SCHEMA_VERSION = "book_notes_index_manifest_v2"
PROGRESS_SCHEMA_VERSION = "book_notes_index_progress_v1"
CHECKPOINT_SCHEMA_VERSION = "book_notes_index_checkpoint_v1"
BUILDER_SCHEMA_VERSION = "book_notes_chunked_builder_v1"
DEFAULT_TABLE_NAME = "evernote_book_notes_v1"
DEFAULT_EXPECTED_DIMENSION = 1024
DEFAULT_CHUNK_MAX_TOKENS = 768
DEFAULT_CHUNK_OVERLAP_TOKENS = 64
DEFAULT_MIN_CHUNK_TOKENS = 64
DEFAULT_MAX_BATCH_TOKENS = 3072
DEFAULT_MAX_BATCH_ITEMS = 8

TEXT_FIELD_NAMES = {"section_text", "excerpt_text", "body_text", "full_text", "content", "chunk_text", "preview"}
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


@dataclass(frozen=True)
class PlanResult:
    eligibility: EligibilityResult
    chunks: list[ChunkPlanItem]
    stats: dict[str, Any]
    config: ChunkingConfig
    tokenizer_info: dict[str, Any]
    metadata_hashes: dict[str, str]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    write_json(tmp_path, payload)
    os.replace(tmp_path, path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
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


def metadata_hashes(metadata_dir: Path) -> dict[str, str]:
    files = require_metadata_files(metadata_dir)
    return {f"{name}_sha256": path_sha256(path) for name, path in files.items()}


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


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _usable_limit(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if 0 < number < 1_000_000:
        return number
    return None


class HFTokenCounter:
    def __init__(self, model_path: Path, *, local_files_only: bool = True) -> None:
        if not model_path.is_dir():
            raise IndexBuildError(f"embedding_model_path_missing path={model_path}")
        from transformers import AutoConfig, AutoTokenizer

        self.model_path = model_path
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(model_path),
            local_files_only=local_files_only,
            trust_remote_code=False,
            use_fast=True,
        )
        config = AutoConfig.from_pretrained(
            str(model_path),
            local_files_only=local_files_only,
            trust_remote_code=False,
        )
        st_config = _read_json_if_exists(model_path / "sentence_bert_config.json")
        limits = {
            "tokenizer_model_max_length": _usable_limit(getattr(self.tokenizer, "model_max_length", None)),
            "model_max_position_embeddings": _usable_limit(getattr(config, "max_position_embeddings", None)),
            "sentence_transformers_max_seq_length": _usable_limit(st_config.get("max_seq_length")),
        }
        valid_limits = [value for value in limits.values() if value]
        if not valid_limits:
            raise IndexBuildError("model_token_limit_unresolved")
        self.effective_model_token_limit = min(valid_limits)
        self.special_token_reserve = int(self.tokenizer.num_special_tokens_to_add(pair=False))
        self.info = {
            **limits,
            "effective_model_token_limit": self.effective_model_token_limit,
            "special_token_reserve": self.special_token_reserve,
            "tokenizer_class": self.tokenizer.__class__.__name__,
            "tokenizer_is_fast": bool(getattr(self.tokenizer, "is_fast", False)),
            "silent_truncation_allowed": False,
        }

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False, truncation=False))

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        encoded = self.tokenizer(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        offsets = encoded.get("offset_mapping") or []
        return [(int(start), int(end)) for start, end in offsets if int(end) > int(start)]


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


def make_chunking_config(
    *,
    chunk_max_tokens: int,
    chunk_overlap_tokens: int,
    min_chunk_tokens: int,
    token_info: dict[str, Any],
    special_token_reserve: int | None = None,
) -> ChunkingConfig:
    reserve = int(token_info.get("special_token_reserve", 0) if special_token_reserve is None else special_token_reserve)
    config = ChunkingConfig(
        chunk_max_tokens=chunk_max_tokens,
        chunk_overlap_tokens=chunk_overlap_tokens,
        min_chunk_tokens=min_chunk_tokens,
        special_token_reserve=reserve,
        effective_model_token_limit=int(token_info["effective_model_token_limit"]),
    )
    try:
        config.validate()
    except ValueError as exc:
        raise IndexBuildError(str(exc)) from exc
    return config


def build_chunk_plan(
    *,
    metadata_dir: Path,
    source_root: Path,
    tokenizer: TokenCounter,
    token_info: dict[str, Any],
    chunk_max_tokens: int,
    chunk_overlap_tokens: int,
    min_chunk_tokens: int = DEFAULT_MIN_CHUNK_TOKENS,
    max_records: int | None = None,
) -> PlanResult:
    eligibility = validate_metadata_eligibility(metadata_dir, source_root)
    config = make_chunking_config(
        chunk_max_tokens=chunk_max_tokens,
        chunk_overlap_tokens=chunk_overlap_tokens,
        min_chunk_tokens=min_chunk_tokens,
        token_info=token_info,
    )
    records = eligibility.eligible_records[:max_records] if max_records is not None else eligibility.eligible_records
    chunks: list[ChunkPlanItem] = []
    oversized_before = 0
    for record in records:
        section = load_section_text(record, source_root)
        if tokenizer.count_tokens(section) > config.chunk_max_tokens:
            oversized_before += 1
        chunks.extend(chunk_section(record, section, tokenizer, config))
    stats = summarize_plan(
        eligible_parent_records=len(records),
        quarantined_parent_records=len(eligibility.quarantined_records),
        chunks=chunks,
    )
    stats.update(
        {
            "schema_version": "book_notes_chunk_plan_stats_v1",
            "chunking_config_fingerprint": config.fingerprint(),
            "configured_chunk_token_limit": config.chunk_max_tokens,
            "chunk_overlap_tokens": config.chunk_overlap_tokens,
            "special_token_reserve": config.special_token_reserve,
            "effective_model_token_limit": config.effective_model_token_limit,
            "oversized_chunks_before_split": oversized_before,
            "oversized_chunks_after_split": 0,
            "silent_truncation_allowed": False,
        }
    )
    return PlanResult(
        eligibility=eligibility,
        chunks=chunks,
        stats=stats,
        config=config,
        tokenizer_info=token_info,
        metadata_hashes=metadata_hashes(metadata_dir),
    )


def write_chunk_plan(output_dir: Path, plan: PlanResult) -> None:
    write_jsonl(output_dir / "chunk_plan.jsonl", [chunk.public_row() for chunk in plan.chunks])
    write_json(output_dir / "chunk_plan_stats.json", plan.stats)


def make_lancedb_row(chunk: ChunkPlanItem, vector: list[float], embedder: Embedder) -> dict[str, Any]:
    row = chunk.public_row()
    row.update(
        {
            "record_schema_version": INDEX_SCHEMA_VERSION,
            "schema_version": INDEX_SCHEMA_VERSION,
            "record_id": chunk.index_record_id,
            "embedding_model_identity": embedder.embedding_model_id,
            "embedding_model_id": embedder.embedding_model_id,
            "embedding_provider": embedder.embedding_provider,
            "embedding_dimension": embedder.embedding_dimension,
            "normalize_embeddings": embedder.normalize_embeddings,
            "device": embedder.device,
            "dtype": embedder.dtype,
            "vector": vector,
        }
    )
    return row


def build_index_manifest(
    *,
    metadata_dir: Path,
    builder_commit: str | None,
    builder_path: Path,
    plan: PlanResult,
    embedder: Embedder,
    model_path: Path,
    db_path: Path,
    table_name: str,
    build_mode: str,
    batches: Sequence[BatchPlan],
) -> dict[str, Any]:
    hashes = metadata_hashes(metadata_dir)
    return {
        "schema_version": INDEX_MANIFEST_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "builder_commit": builder_commit,
        "builder_path": str(builder_path),
        "builder_schema_version": BUILDER_SCHEMA_VERSION,
        "metadata_manifest_sha256": hashes["manifest_sha256"],
        "books_catalog_sha256": hashes["catalog_sha256"],
        "manifest_record_count": plan.eligibility.manifest_records,
        "eligible_parent_record_count": len(plan.eligibility.eligible_records),
        "quarantined_parent_record_count": len(plan.eligibility.quarantined_records),
        "embedding_chunk_count": len(plan.chunks),
        "embedding_provider": embedder.embedding_provider,
        "embedding_model_path": str(model_path),
        "embedding_model_identity": embedder.embedding_model_id,
        "embedding_dimension": embedder.embedding_dimension,
        "normalize_embeddings": embedder.normalize_embeddings,
        "batch_size": embedder.batch_size,
        "max_batch_tokens": max((batch.token_count for batch in batches), default=0),
        "device": embedder.device,
        "dtype": embedder.dtype,
        "vector_store_type": "lancedb",
        "db_path": str(db_path),
        "table_name": table_name,
        "record_schema_version": INDEX_SCHEMA_VERSION,
        "chunking_config_fingerprint": plan.config.fingerprint(),
        "chunk_max_tokens": plan.config.chunk_max_tokens,
        "chunk_overlap_tokens": plan.config.chunk_overlap_tokens,
        "source_text_stored": False,
        "build_mode": build_mode,
        "build_complete": True,
        "validation_complete": True,
        "silent_truncation_allowed": False,
    }


def connect_lancedb(path: Path):
    import lancedb

    return lancedb.connect(str(path))


def _table_names(db: Any) -> set[str]:
    return set(db.table_names())


def _table_rows(table: Any) -> list[dict[str, Any]]:
    return table.to_lance().to_table().to_pylist()


def validate_lancedb_table(db_path: Path, table_name: str, expected_rows: int) -> dict[str, Any]:
    db = connect_lancedb(db_path)
    table = db.open_table(table_name)
    schema_names = set(table.schema.names)
    missing = {"index_record_id", "parent_record_id", "book_id", "source_type", "resolution_status", "vector"} - schema_names
    if missing:
        raise IndexBuildError(f"lancedb_schema_missing fields={sorted(missing)}")
    if TEXT_FIELD_NAMES & schema_names:
        raise IndexBuildError("lancedb_text_field_present")
    rows = table.count_rows()
    if rows != expected_rows:
        raise IndexBuildError(f"lancedb_row_count_mismatch expected={expected_rows} actual={rows}")
    records = _table_rows(table)
    ids = [row["index_record_id"] for row in records]
    duplicate_ids = len(ids) - len(set(ids))
    if duplicate_ids:
        raise IndexBuildError(f"duplicate_index_record_id count={duplicate_ids}")
    return {"rows": rows, "schema_fields": sorted(schema_names), "duplicate_index_record_ids": 0}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def current_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Darwin":
        return int(usage)
    return int(usage) * 1024


class ProgressLedger:
    def __init__(
        self,
        *,
        progress_path: Path,
        events_path: Path,
        build_id: str,
        chunks_total: int,
        tokens_total: int,
        batches_total: int,
        parent_records_total: int,
    ) -> None:
        self.progress_path = progress_path
        self.events_path = events_path
        self.build_id = build_id
        self.started_monotonic = time.monotonic()
        self.started_at = utc_now()
        self.chunks_total = chunks_total
        self.tokens_total = tokens_total
        self.batches_total = batches_total
        self.parent_records_total = parent_records_total
        self.last_payload: dict[str, Any] = {}

    def event(self, event_type: str, **payload: Any) -> None:
        append_jsonl(self.events_path, {"ts": utc_now(), "build_id": self.build_id, "event_type": event_type, **payload})

    def update(
        self,
        *,
        status: str,
        chunks_completed: int,
        tokens_completed: int,
        batches_completed: int,
        current_batch_index: int | None,
        last_completed_index_record_id: str | None,
        stop_requested: bool = False,
        resumable: bool = True,
        error_type: str | None = None,
        current_batch_started_at: str | None = None,
    ) -> None:
        elapsed = max(0.001, time.monotonic() - self.started_monotonic)
        now = utc_now()
        payload = {
            "schema_version": PROGRESS_SCHEMA_VERSION,
            "build_id": self.build_id,
            "status": status,
            "started_at": self.started_at,
            "updated_at": now,
            "parent_records_total": self.parent_records_total,
            "parent_records_planned": self.parent_records_total,
            "chunks_total": self.chunks_total,
            "chunks_completed": chunks_completed,
            "chunks_remaining": max(0, self.chunks_total - chunks_completed),
            "tokens_total": self.tokens_total,
            "tokens_completed": tokens_completed,
            "tokens_remaining": max(0, self.tokens_total - tokens_completed),
            "batches_total": self.batches_total,
            "batches_completed": batches_completed,
            "current_batch_index": current_batch_index,
            "last_completed_index_record_id": last_completed_index_record_id,
            "last_progress_at": now,
            "last_heartbeat_at": now,
            "current_batch_started_at": current_batch_started_at,
            "elapsed_seconds": elapsed,
            "records_per_second": chunks_completed / elapsed,
            "tokens_per_second": tokens_completed / elapsed,
            "peak_rss_bytes": current_rss_bytes(),
            "current_rss_bytes": current_rss_bytes(),
            "stop_requested": stop_requested,
            "resumable": resumable,
            "error_type": error_type,
        }
        write_json_atomic(self.progress_path, payload)
        self.last_payload = payload


def checkpoint_payload(
    *,
    metadata_dir: Path,
    model_path: Path,
    plan: PlanResult,
    table_name: str,
    expected_dimension: int,
) -> dict[str, Any]:
    hashes = metadata_hashes(metadata_dir)
    model = model_fingerprint(model_path)
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "builder_schema_version": BUILDER_SCHEMA_VERSION,
        "metadata_manifest_sha256": hashes["manifest_sha256"],
        "books_catalog_sha256": hashes["catalog_sha256"],
        "embedding_model_identity": model["fingerprint"],
        "chunking_config_fingerprint": plan.config.fingerprint(),
        "table_name": table_name,
        "expected_dimension": expected_dimension,
        "chunks_total": len(plan.chunks),
        "chunk_plan_sha256": sha256_text(
            "\n".join(json.dumps(chunk.public_row(), ensure_ascii=False, sort_keys=True) for chunk in plan.chunks)
        ),
    }


def validate_resume_checkpoint(checkpoint_path: Path, expected: dict[str, Any]) -> None:
    if not checkpoint_path.is_file():
        raise IndexBuildError("resume_checkpoint_missing")
    actual = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    keys = [
        "schema_version",
        "builder_schema_version",
        "metadata_manifest_sha256",
        "books_catalog_sha256",
        "embedding_model_identity",
        "chunking_config_fingerprint",
        "table_name",
        "expected_dimension",
        "chunks_total",
        "chunk_plan_sha256",
    ]
    for key in keys:
        if actual.get(key) != expected.get(key):
            raise IndexBuildError(f"resume_checkpoint_mismatch field={key}")


def completed_ids_from_tmp(tmp_path: Path, table_name: str) -> set[str]:
    if not tmp_path.exists():
        return set()
    db = connect_lancedb(tmp_path)
    if table_name not in _table_names(db):
        return set()
    table = db.open_table(table_name)
    return {str(row["index_record_id"]) for row in _table_rows(table)}


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
    tokenizer: TokenCounter | None = None,
    token_info: dict[str, Any] | None = None,
    chunk_max_tokens: int = DEFAULT_CHUNK_MAX_TOKENS,
    chunk_overlap_tokens: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
    min_chunk_tokens: int = DEFAULT_MIN_CHUNK_TOKENS,
    max_batch_tokens: int = DEFAULT_MAX_BATCH_TOKENS,
    max_batch_items: int = DEFAULT_MAX_BATCH_ITEMS,
    heartbeat_seconds: float = 10.0,
    progress_path: Path | None = None,
    events_path: Path | None = None,
    stop_after_seconds: float | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    if db_path.exists() and not rebuild and not resume:
        raise IndexBuildError(f"db_path_exists_without_rebuild path={db_path}")
    tmp_path = db_path.with_name(f".{db_path.name}.tmp_build")
    rollback_path = db_path.with_name(f".{db_path.name}.rollback")
    if tokenizer is None:
        tokenizer = HFTokenCounter(model_path)
    if token_info is None:
        token_info = getattr(tokenizer, "info", None) or {
            "effective_model_token_limit": chunk_max_tokens + 2,
            "special_token_reserve": 2,
            "silent_truncation_allowed": False,
        }
    plan = build_chunk_plan(
        metadata_dir=metadata_dir,
        source_root=source_root,
        tokenizer=tokenizer,
        token_info=token_info,
        chunk_max_tokens=chunk_max_tokens,
        chunk_overlap_tokens=chunk_overlap_tokens,
        min_chunk_tokens=min_chunk_tokens,
        max_records=max_records,
    )
    batches = plan_batches(plan.chunks, max_batch_tokens=max_batch_tokens, max_batch_items=max_batch_items)
    expected_checkpoint = checkpoint_payload(
        metadata_dir=metadata_dir,
        model_path=model_path,
        plan=plan,
        table_name=table_name,
        expected_dimension=expected_dimension,
    )
    checkpoint_path = tmp_path / "build_checkpoint.json"
    if resume:
        validate_resume_checkpoint(checkpoint_path, expected_checkpoint)
    else:
        for path in (tmp_path, rollback_path):
            if path.exists():
                shutil.rmtree(path)
        tmp_path.mkdir(parents=True)
        write_chunk_plan(tmp_path, plan)
        write_json(checkpoint_path, expected_checkpoint)
    progress_path = progress_path or (tmp_path / "build_progress.json")
    events_path = events_path or (tmp_path / "build_events.jsonl")
    build_id = sha256_text(f"{db_path}\0{table_name}\0{time.time()}")[:16]
    ledger = ProgressLedger(
        progress_path=progress_path,
        events_path=events_path,
        build_id=build_id,
        chunks_total=len(plan.chunks),
        tokens_total=int(plan.stats["total_tokens"]),
        batches_total=len(batches),
        parent_records_total=int(plan.stats["eligible_parent_records"]),
    )
    completed_ids = completed_ids_from_tmp(tmp_path, table_name) if resume else set()
    chunk_by_id = {chunk.index_record_id: chunk for chunk in plan.chunks}
    if len(completed_ids - set(chunk_by_id)) > 0:
        raise IndexBuildError("resume_completed_id_not_in_plan")
    completed_chunks = [chunk_by_id[item] for item in completed_ids]
    chunks_completed = len(completed_chunks)
    tokens_completed = sum(chunk.chunk_token_count for chunk in completed_chunks)
    batches_completed = 0
    last_completed = sorted(completed_ids)[-1] if completed_ids else None
    ledger.event("build_started", resume=resume, chunks_total=len(plan.chunks), batches_total=len(batches))
    ledger.update(
        status="running",
        chunks_completed=chunks_completed,
        tokens_completed=tokens_completed,
        batches_completed=batches_completed,
        current_batch_index=None,
        last_completed_index_record_id=last_completed,
    )
    db = connect_lancedb(tmp_path)
    table = db.open_table(table_name) if table_name in _table_names(db) else None
    start_time = time.monotonic()
    try:
        for batch in batches:
            batch_chunks = [chunk for chunk in plan.chunks[batch.start : batch.end] if chunk.index_record_id not in completed_ids]
            if not batch_chunks:
                batches_completed += 1
                continue
            batch_started_at = utc_now()
            batch_started_monotonic = time.monotonic()
            heartbeat_stop = threading.Event()

            def heartbeat_loop() -> None:
                while not heartbeat_stop.wait(max(0.1, heartbeat_seconds)):
                    ledger.update(
                        status="running",
                        chunks_completed=chunks_completed,
                        tokens_completed=tokens_completed,
                        batches_completed=batches_completed,
                        current_batch_index=batch.batch_index,
                        last_completed_index_record_id=last_completed,
                        current_batch_started_at=batch_started_at,
                    )

            ledger.update(
                status="running",
                chunks_completed=chunks_completed,
                tokens_completed=tokens_completed,
                batches_completed=batches_completed,
                current_batch_index=batch.batch_index,
                last_completed_index_record_id=last_completed,
                current_batch_started_at=batch_started_at,
            )
            heartbeat_thread: threading.Thread | None = None
            if heartbeat_seconds > 0:
                heartbeat_thread = threading.Thread(target=heartbeat_loop, name="book-notes-build-heartbeat", daemon=True)
                heartbeat_thread.start()
            try:
                vectors = embedder.embed_documents([chunk.text for chunk in batch_chunks])
            finally:
                heartbeat_stop.set()
                if heartbeat_thread is not None:
                    heartbeat_thread.join(timeout=1.0)
            if len(vectors) != len(batch_chunks):
                raise IndexBuildError("embedding_count_mismatch")
            rows = [
                make_lancedb_row(chunk, validate_vector(vector, expected_dimension, chunk.index_record_id), embedder)
                for chunk, vector in zip(batch_chunks, vectors)
            ]
            if table is None:
                table = db.create_table(table_name, data=rows, mode="overwrite")
            else:
                table.add(rows)
            for chunk in batch_chunks:
                completed_ids.add(chunk.index_record_id)
                chunks_completed += 1
                tokens_completed += chunk.chunk_token_count
                last_completed = chunk.index_record_id
            batches_completed += 1
            ledger.event("batch_completed", batch_elapsed_seconds=time.monotonic() - batch_started_monotonic, **batch.public_row())
            ledger.update(
                status="running",
                chunks_completed=chunks_completed,
                tokens_completed=tokens_completed,
                batches_completed=batches_completed,
                current_batch_index=batch.batch_index,
                last_completed_index_record_id=last_completed,
                current_batch_started_at=batch_started_at,
            )
            if stop_after_seconds is not None and time.monotonic() - start_time >= stop_after_seconds:
                ledger.event("build_stopped", stop_after_seconds=stop_after_seconds)
                ledger.update(
                    status="stopped",
                    chunks_completed=chunks_completed,
                    tokens_completed=tokens_completed,
                    batches_completed=batches_completed,
                    current_batch_index=batch.batch_index,
                    last_completed_index_record_id=last_completed,
                    stop_requested=True,
                    resumable=True,
                    current_batch_started_at=batch_started_at,
                )
                return {
                    "build_complete": False,
                    "stopped": True,
                    "resumable": True,
                    "temporary_db_path": str(tmp_path),
                    "rows": chunks_completed,
                    "chunks_total": len(plan.chunks),
                    "eligible_parent_records": int(plan.stats["eligible_parent_records"]),
                    "quarantined_parent_records": int(plan.stats["quarantined_parent_records"]),
                    "progress_path": str(progress_path),
                    "events_path": str(events_path),
                }
        manifest = build_index_manifest(
            metadata_dir=metadata_dir,
            builder_commit=builder_commit,
            builder_path=builder_path or Path(__file__),
            plan=plan,
            embedder=embedder,
            model_path=model_path,
            db_path=db_path,
            table_name=table_name,
            build_mode="resume" if resume else ("rebuild" if rebuild else "create"),
            batches=batches,
        )
        write_json(tmp_path / "index_manifest.json", manifest)
        validation = validate_lancedb_table(tmp_path, table_name, len(plan.chunks))
        ledger.event("build_completed", rows=len(plan.chunks))
        ledger.update(
            status="completed",
            chunks_completed=len(plan.chunks),
            tokens_completed=int(plan.stats["total_tokens"]),
            batches_completed=len(batches),
            current_batch_index=None,
            last_completed_index_record_id=last_completed,
            resumable=False,
        )
        if db_path.exists():
            os.replace(db_path, rollback_path)
        os.replace(tmp_path, db_path)
        if rollback_path.exists():
            shutil.rmtree(rollback_path)
        return {
            "build_complete": True,
            "table_name": table_name,
            "rows": len(plan.chunks),
            "eligible_parent_records": int(plan.stats["eligible_parent_records"]),
            "quarantined_parent_records": int(plan.stats["quarantined_parent_records"]),
            "embedding_chunks": len(plan.chunks),
            "total_tokens": int(plan.stats["total_tokens"]),
            "chunking_config_fingerprint": plan.config.fingerprint(),
            "validation": validation,
            "progress_path": str(progress_path),
            "events_path": str(events_path),
        }
    except Exception as exc:
        ledger.event("build_failed", error_type=exc.__class__.__name__)
        ledger.update(
            status="failed",
            chunks_completed=chunks_completed,
            tokens_completed=tokens_completed,
            batches_completed=batches_completed,
            current_batch_index=None,
            last_completed_index_record_id=last_completed,
            resumable=tmp_path.exists(),
            error_type=exc.__class__.__name__,
        )
        if not resume and tmp_path.exists() and not completed_ids:
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


def compare_chunk_configs(
    *,
    metadata_dir: Path,
    source_root: Path,
    tokenizer: TokenCounter,
    token_info: dict[str, Any],
    limits: Sequence[int],
    overlap_tokens: int,
    min_chunk_tokens: int,
    max_records: int | None,
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for limit in limits:
        overlap = min(overlap_tokens, max(0, limit // 4))
        plan = build_chunk_plan(
            metadata_dir=metadata_dir,
            source_root=source_root,
            tokenizer=tokenizer,
            token_info=token_info,
            chunk_max_tokens=limit,
            chunk_overlap_tokens=overlap,
            min_chunk_tokens=min_chunk_tokens,
            max_records=max_records,
        )
        comparisons.append(
            {
                "chunk_max_tokens": limit,
                "overlap_tokens": overlap,
                "embedding_chunks": plan.stats["embedding_chunks"],
                "total_tokens": plan.stats["total_tokens"],
                "avg_tokens": plan.stats["average_tokens_per_chunk"],
                "median_tokens": plan.stats["median_tokens_per_chunk"],
                "p95_tokens": plan.stats["p95_tokens_per_chunk"],
                "max_tokens": plan.stats["maximum_tokens_per_chunk"],
                "max_chunks_per_section": plan.stats["maximum_chunks_per_section"],
                "oversized_chunks_after_split": plan.stats["oversized_chunks_after_split"],
                "estimated_vector_storage_bytes": plan.stats["embedding_chunks"] * DEFAULT_EXPECTED_DIMENSION * 4,
                "chunking_config_fingerprint": plan.config.fingerprint(),
            }
        )
    return comparisons


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or validate the offline Evernote book-notes LanceDB index.")
    parser.add_argument("--metadata-dir", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--table-name", default=DEFAULT_TABLE_NAME)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--expected-dimension", type=int, default=DEFAULT_EXPECTED_DIMENSION)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_MAX_BATCH_ITEMS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--plan-output-dir", type=Path, default=None)
    parser.add_argument("--compare-chunk-token-limits", default=None)
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--max-chunks", type=int, default=None, help="Synthetic/benchmark guard: embed at most this many chunks.")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--local-files-only", action="store_true", default=True)
    parser.add_argument("--normalize-embeddings", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--device", default=None)
    parser.add_argument("--model-smoke", action="store_true")
    parser.add_argument("--json-summary", action="store_true")
    parser.add_argument("--chunk-max-tokens", type=int, default=DEFAULT_CHUNK_MAX_TOKENS)
    parser.add_argument("--chunk-overlap-tokens", type=int, default=DEFAULT_CHUNK_OVERLAP_TOKENS)
    parser.add_argument("--min-chunk-tokens", type=int, default=DEFAULT_MIN_CHUNK_TOKENS)
    parser.add_argument("--max-batch-tokens", type=int, default=DEFAULT_MAX_BATCH_TOKENS)
    parser.add_argument("--max-batch-items", type=int, default=DEFAULT_MAX_BATCH_ITEMS)
    parser.add_argument("--heartbeat-seconds", type=float, default=10.0)
    parser.add_argument("--progress-path", type=Path, default=None)
    parser.add_argument("--events-path", type=Path, default=None)
    parser.add_argument("--stop-after-seconds", type=float, default=None)
    parser.add_argument("--synthetic-tokenizer", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        fingerprint = model_fingerprint(args.model_path)
        if args.synthetic_tokenizer:
            tokenizer: TokenCounter = SimpleTokenCounter()
            token_info = {
                "effective_model_token_limit": 8192,
                "special_token_reserve": 2,
                "tokenizer_class": "SimpleTokenCounter",
                "tokenizer_is_fast": True,
                "silent_truncation_allowed": False,
            }
        else:
            tokenizer = HFTokenCounter(args.model_path, local_files_only=args.local_files_only)
            token_info = tokenizer.info
        if args.dry_run and not args.plan_only and not args.model_smoke:
            eligibility = validate_metadata_eligibility(args.metadata_dir, args.source_root)
            summary = {
                "dry_run": True,
                "model_loaded": False,
                "embedding_model_identity": fingerprint["fingerprint"],
                **token_info,
                **eligibility.summary(),
            }
        elif args.plan_only:
            if args.compare_chunk_token_limits:
                limits = [int(item) for item in args.compare_chunk_token_limits.split(",") if item.strip()]
                comparisons = compare_chunk_configs(
                    metadata_dir=args.metadata_dir,
                    source_root=args.source_root,
                    tokenizer=tokenizer,
                    token_info=token_info,
                    limits=limits,
                    overlap_tokens=args.chunk_overlap_tokens,
                    min_chunk_tokens=args.min_chunk_tokens,
                    max_records=args.max_records,
                )
                summary = {
                    "plan_only": True,
                    "model_loaded": False,
                    "embedding_model_identity": fingerprint["fingerprint"],
                    "candidate_chunk_configs": comparisons,
                    **token_info,
                }
            else:
                plan = build_chunk_plan(
                    metadata_dir=args.metadata_dir,
                    source_root=args.source_root,
                    tokenizer=tokenizer,
                    token_info=token_info,
                    chunk_max_tokens=args.chunk_max_tokens,
                    chunk_overlap_tokens=args.chunk_overlap_tokens,
                    min_chunk_tokens=args.min_chunk_tokens,
                    max_records=args.max_records,
                )
                if args.plan_output_dir:
                    write_chunk_plan(args.plan_output_dir, plan)
                summary = {
                    "plan_only": True,
                    "model_loaded": False,
                    "embedding_model_identity": fingerprint["fingerprint"],
                    **token_info,
                    **plan.stats,
                }
        else:
            embedder = LocalSentenceTransformerEmbedder(
                model_path=args.model_path,
                expected_dimension=args.expected_dimension,
                batch_size=args.max_batch_items,
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
                eligibility = validate_metadata_eligibility(args.metadata_dir, args.source_root)
                summary = {
                    "dry_run": True,
                    "model_loaded": True,
                    "model_smoke_vectors": len(smoke_vectors),
                    "embedding_dimension": len(smoke_vectors[0]) if smoke_vectors else 0,
                    **token_info,
                    **eligibility.summary(),
                }
            else:
                max_records = args.max_records
                summary = create_lancedb_index(
                    metadata_dir=args.metadata_dir,
                    source_root=args.source_root,
                    db_path=args.db_path,
                    table_name=args.table_name,
                    model_path=args.model_path,
                    embedder=embedder,
                    expected_dimension=args.expected_dimension,
                    max_records=max_records,
                    rebuild=args.rebuild,
                    builder_commit=git_head(Path.cwd()),
                    builder_path=Path(__file__).resolve(),
                    tokenizer=tokenizer,
                    token_info=token_info,
                    chunk_max_tokens=args.chunk_max_tokens,
                    chunk_overlap_tokens=args.chunk_overlap_tokens,
                    min_chunk_tokens=args.min_chunk_tokens,
                    max_batch_tokens=args.max_batch_tokens,
                    max_batch_items=args.max_batch_items,
                    heartbeat_seconds=args.heartbeat_seconds,
                    progress_path=args.progress_path,
                    events_path=args.events_path,
                    stop_after_seconds=args.stop_after_seconds,
                    resume=args.resume,
                )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2 if args.json_summary else None))
        return 0
    except (IndexBuildError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
