"""Bounded, read-only retrieval over the private book-notes LanceDB index."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from tools.book_notes.build_book_notes_index import HFTokenCounter, LocalSentenceTransformerEmbedder, model_fingerprint


SCHEMA_VERSION = "book_notes_retrieval_v1"
DEFAULT_EXCERPT_MAX_CHARS = 600
MAX_EXCERPT_MAX_CHARS = 1200
MAX_CANDIDATE_K = 200
MAX_TOP_K = 20
MAX_TOP_K_BOOKS = 20
ALLOWED_RELATIONSHIP_INTENTS = {None, "echo", "tension", "completion"}
REQUIRED_INDEX_FIELDS = {
    "index_record_id", "parent_record_id", "book_id", "section_id",
    "embedding_chunk_index", "embedding_chunk_count", "source_path",
    "source_sha256", "section_start_offset", "section_end_offset",
    "section_text_sha256", "chunk_start_offset_in_source",
    "chunk_end_offset_in_source", "chunk_text_sha256", "source_type",
    "content_type", "resolution_status", "embedding_model_identity",
    "embedding_dimension", "normalize_embeddings", "dtype", "vector",
}


class RetrievalError(RuntimeError):
    """A stable, privacy-safe retrieval contract error."""


class QueryEmbedder(Protocol):
    embedding_model_id: str
    embedding_dimension: int
    normalize_embeddings: bool
    dtype: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class RetrievalResponse:
    schema_version: str
    query_sha256: str
    mode: str
    relationship_intent: str | None
    raw_candidate_count: int
    result_count: int
    truncated: bool
    model_identity: str
    embedding_dimension: int
    index_manifest_sha256: str
    raw_metric_name: str
    results: list[dict[str, Any]]
    timings: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RetrievalError("index_manifest_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetrievalError("index_manifest_invalid") from exc
    if not isinstance(value, dict):
        raise RetrievalError("index_manifest_invalid")
    return value


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _bounded_int(name: str, value: int, *, maximum: int, minimum: int = 1) -> int:
    if value < minimum or value > maximum:
        raise RetrievalError(f"{name}_out_of_range")
    return value


class BookNotesRetriever:
    """A read-only retrieval facade; all vector filters are applied by LanceDB."""

    def __init__(
        self,
        *,
        db_path: Path,
        table_name: str,
        model_path: Path,
        source_root: Path,
        metadata_dir: Path | None = None,
        table: Any | None = None,
        embedder: QueryEmbedder | None = None,
        token_counter: Any | None = None,
        index_manifest: dict[str, Any] | None = None,
    ) -> None:
        self.db_path = db_path.resolve()
        self.table_name = table_name
        self.model_path = model_path.resolve()
        self.source_root = source_root.resolve()
        self.metadata_dir = metadata_dir.resolve() if metadata_dir else None
        manifest_path = self.db_path / "index_manifest.json"
        self.index_manifest = index_manifest or _read_json(manifest_path)
        self.index_manifest_sha256 = (
            _sha256_bytes(manifest_path.read_bytes()) if manifest_path.is_file()
            else _sha256_text(json.dumps(self.index_manifest, sort_keys=True))
        )
        self._validate_manifest()
        self.table = table or self._open_table_read_only()
        self._validate_table_schema()
        self.embedder = embedder or LocalSentenceTransformerEmbedder(
            model_path=self.model_path,
            expected_dimension=self.embedding_dimension,
            batch_size=1,
            normalize_embeddings=self.normalize_embeddings,
            local_files_only=True,
        )
        self.token_counter = token_counter or HFTokenCounter(self.model_path, local_files_only=True)
        self._validate_embedder()
        self.parent_metadata = self._load_parent_metadata()
        self._source_cache: dict[Path, tuple[bytes, str]] = {}

    @property
    def embedding_dimension(self) -> int:
        return int(self.index_manifest["embedding_dimension"])

    @property
    def normalize_embeddings(self) -> bool:
        return bool(self.index_manifest["normalize_embeddings"])

    def _validate_manifest(self) -> None:
        required = {
            "table_name", "embedding_model_identity", "embedding_dimension",
            "normalize_embeddings", "dtype", "source_text_stored",
            "effective_model_token_limit", "special_token_reserve",
        }
        if required - self.index_manifest.keys():
            raise RetrievalError("index_manifest_incomplete")
        if self.index_manifest["table_name"] != self.table_name:
            raise RetrievalError("index_manifest_table_mismatch")
        if self.index_manifest["source_text_stored"] is not False:
            raise RetrievalError("index_source_text_contract_violation")
        if self.model_path.is_dir():
            actual = model_fingerprint(self.model_path)["fingerprint"]
            if actual != self.index_manifest["embedding_model_identity"]:
                raise RetrievalError("model_fingerprint_mismatch")

    def _open_table_read_only(self) -> Any:
        import lancedb

        if not self.db_path.is_dir():
            raise RetrievalError("lancedb_path_missing")
        db = lancedb.connect(str(self.db_path))
        names = list(db.table_names())
        if names.count(self.table_name) != 1:
            raise RetrievalError("formal_table_ambiguous_or_missing")
        return db.open_table(self.table_name)

    def _validate_table_schema(self) -> None:
        names = set(self.table.schema.names)
        missing = REQUIRED_INDEX_FIELDS - names
        if missing:
            raise RetrievalError("table_schema_missing_fields:" + ",".join(sorted(missing)))
        if names & {"text", "chunk_text", "section_text", "excerpt", "body"}:
            raise RetrievalError("table_contains_source_text")

    def _validate_embedder(self) -> None:
        checks = {
            "embedding_model_id": self.index_manifest["embedding_model_identity"],
            "embedding_dimension": self.embedding_dimension,
            "normalize_embeddings": self.normalize_embeddings,
            "dtype": self.index_manifest["dtype"],
        }
        for field, expected in checks.items():
            if getattr(self.embedder, field, None) != expected:
                raise RetrievalError(f"query_embedder_{field}_mismatch")

    def _load_parent_metadata(self) -> dict[str, dict[str, Any]]:
        if self.metadata_dir is None:
            return {}
        path = self.metadata_dir / "manifest.jsonl"
        if not path.is_file():
            raise RetrievalError("metadata_manifest_missing")
        if _sha256_bytes(path.read_bytes()) != self.index_manifest.get("metadata_manifest_sha256"):
            raise RetrievalError("metadata_manifest_checksum_mismatch")
        output: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            output[str(row["record_id"])] = row
        return output

    def _embed_query(self, query: str) -> tuple[list[float], float]:
        if not query or not query.strip():
            raise RetrievalError("query_empty")
        limit = int(self.index_manifest["effective_model_token_limit"]) - int(
            self.index_manifest["special_token_reserve"]
        )
        if self.token_counter.count_tokens(query) > limit:
            raise RetrievalError("query_token_limit_exceeded")
        started = time.monotonic()
        vectors = self.embedder.embed_documents([query])
        elapsed = time.monotonic() - started
        if len(vectors) != 1 or len(vectors[0]) != self.embedding_dimension:
            raise RetrievalError("query_embedding_dimension_mismatch")
        vector = [float(value) for value in vectors[0]]
        if not all(math.isfinite(value) for value in vector):
            raise RetrievalError("query_embedding_non_finite")
        return vector, elapsed

    def _search(self, vector: list[float], *, filter_sql: str, candidate_k: int) -> tuple[list[dict[str, Any]], float]:
        started = time.monotonic()
        query = self.table.search(vector).where(filter_sql, prefilter=True).limit(candidate_k)
        if hasattr(query, "to_list"):
            rows = query.to_list()
        else:
            rows = query.to_arrow().to_pylist()
        elapsed = time.monotonic() - started
        for row in rows:
            if "_distance" not in row:
                raise RetrievalError("raw_metric_missing")
            if not math.isfinite(float(row["_distance"])):
                raise RetrievalError("raw_metric_non_finite")
        rows.sort(key=self._stable_key)
        return rows, elapsed

    @staticmethod
    def _stable_key(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            float(row["_distance"]), str(row["book_id"]),
            str(row["parent_record_id"]), str(row["index_record_id"]),
        )

    def _base_result(self, row: dict[str, Any], rank: int) -> dict[str, Any]:
        if (
            row["source_type"] != "evernote_book_excerpt"
            or row["content_type"] != "book_excerpt"
            or row["resolution_status"] != "resolved"
        ):
            raise RetrievalError("ineligible_or_quarantined_index_row")
        parent = self.parent_metadata.get(str(row["parent_record_id"]), {})
        if parent and (
            parent.get("book_id") != row["book_id"] or parent.get("section_id") != row["section_id"]
        ):
            raise RetrievalError("record_book_section_mismatch")
        return {
            "rank": rank,
            "book_id": row["book_id"],
            "book_title_normalized": parent.get("book_title_normalized"),
            "author_normalized": parent.get("author_normalized"),
            "parent_record_id": row["parent_record_id"],
            "section_id": row["section_id"],
            "index_record_id": row["index_record_id"],
            "embedding_chunk_index": int(row["embedding_chunk_index"]),
            "embedding_chunk_count": int(row["embedding_chunk_count"]),
            "raw_metric_name": "l2_distance",
            "raw_metric_value": float(row["_distance"]),
            "source_type": row["source_type"],
            "content_type": row["content_type"],
            "resolution_status": row["resolution_status"],
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "section_start_offset": int(row["section_start_offset"]),
            "section_end_offset": int(row["section_end_offset"]),
            "chunk_start_offset_in_source": int(row["chunk_start_offset_in_source"]),
            "chunk_end_offset_in_source": int(row["chunk_end_offset_in_source"]),
            "chunk_text_sha256": row["chunk_text_sha256"],
        }

    def _read_excerpt(
        self,
        row: dict[str, Any],
        *,
        excerpt_max_chars: int,
        context_chars: int,
    ) -> tuple[dict[str, Any], float]:
        started = time.monotonic()
        if row["source_type"] != "evernote_book_excerpt" or row["content_type"] != "book_excerpt":
            raise RetrievalError("source_semantics_mismatch")
        relative = Path(str(row["source_path"]))
        if relative.is_absolute():
            candidate = relative.resolve()
        else:
            candidate = (self.source_root / relative).resolve()
        try:
            candidate.relative_to(self.source_root)
        except ValueError as exc:
            raise RetrievalError("source_path_traversal") from exc
        if candidate not in self._source_cache:
            data = candidate.read_bytes()
            self._source_cache[candidate] = (data, data.decode("utf-8"))
        data, text = self._source_cache[candidate]
        if _sha256_bytes(data) != row["source_sha256"]:
            raise RetrievalError("source_checksum_mismatch")
        section_start, section_end = int(row["section_start_offset"]), int(row["section_end_offset"])
        chunk_start = int(row["chunk_start_offset_in_source"])
        chunk_end = int(row["chunk_end_offset_in_source"])
        if not (0 <= section_start <= chunk_start < chunk_end <= section_end <= len(text)):
            raise RetrievalError("provenance_offset_invalid")
        section_text = text[section_start:section_end]
        if _sha256_text(section_text) != row["section_text_sha256"]:
            raise RetrievalError("section_checksum_mismatch")
        chunk_text = text[chunk_start:chunk_end]
        if _sha256_text(chunk_text) != row["chunk_text_sha256"]:
            raise RetrievalError("chunk_checksum_mismatch")
        start = max(section_start, chunk_start - context_chars)
        end = min(section_end, chunk_end + context_chars)
        natural_start, natural_end = start, end
        if end - start > excerpt_max_chars:
            if len(chunk_text) >= excerpt_max_chars:
                start, end = chunk_start, chunk_start + excerpt_max_chars
            else:
                extra = excerpt_max_chars - len(chunk_text)
                start = max(section_start, chunk_start - extra // 2)
                end = min(section_end, start + excerpt_max_chars)
                start = max(section_start, end - excerpt_max_chars)
        return ({
            "excerpt": text[start:end],
            "excerpt_start_offset_in_source": start,
            "excerpt_end_offset_in_source": end,
            "excerpt_truncated": start > natural_start or end < natural_end or start > chunk_start or end < chunk_end,
            "exact_chunk_start_offset_in_source": chunk_start,
            "exact_chunk_end_offset_in_source": chunk_end,
            "excerpt_mode": "chunk_with_small_context" if context_chars else "exact_chunk",
        }, time.monotonic() - started)

    def search_current_book(
        self, query: str, book_id: str, *, top_k: int = 5, candidate_k: int = 40,
        max_per_parent: int = 2, excerpt_max_chars: int = DEFAULT_EXCERPT_MAX_CHARS,
        include_text: bool = True, context_chars: int = 0,
    ) -> RetrievalResponse:
        top_k = _bounded_int("top_k", top_k, maximum=MAX_TOP_K)
        candidate_k = _bounded_int("candidate_k", candidate_k, maximum=MAX_CANDIDATE_K)
        max_per_parent = _bounded_int("max_per_parent", max_per_parent, maximum=MAX_TOP_K)
        excerpt_max_chars = _bounded_int("excerpt_max_chars", excerpt_max_chars, maximum=MAX_EXCERPT_MAX_CHARS)
        if candidate_k <= top_k:
            raise RetrievalError("candidate_k_not_greater_than_top_k")
        vector, embedding_time = self._embed_query(query)
        rows, search_time = self._search(vector, filter_sql=f"book_id = {_sql_literal(book_id)}", candidate_k=candidate_k)
        selected: list[dict[str, Any]] = []
        parent_counts: dict[str, int] = {}
        for row in rows:
            if row["book_id"] != book_id:
                raise RetrievalError("db_book_filter_contract_violation")
            parent = str(row["parent_record_id"])
            if parent_counts.get(parent, 0) >= max_per_parent:
                continue
            selected.append(row)
            parent_counts[parent] = parent_counts.get(parent, 0) + 1
            if len(selected) == top_k:
                break
        results, provenance_time = self._materialize(selected, excerpt_max_chars, include_text, context_chars)
        return self._response(query, "current_book", None, rows, results, embedding_time, search_time, provenance_time)

    def search_other_books(
        self, query: str, *, exclude_book_id: str | None = None, top_k_books: int = 5,
        candidate_k: int = 80, max_chunks_per_book: int = 2, max_chunks_per_parent: int = 1,
        relationship_intent: str | None = None, excerpt_max_chars: int = DEFAULT_EXCERPT_MAX_CHARS,
        include_text: bool = True, context_chars: int = 0,
    ) -> RetrievalResponse:
        if relationship_intent not in ALLOWED_RELATIONSHIP_INTENTS:
            raise RetrievalError("relationship_intent_invalid")
        top_k_books = _bounded_int("top_k_books", top_k_books, maximum=MAX_TOP_K_BOOKS)
        candidate_k = _bounded_int("candidate_k", candidate_k, maximum=MAX_CANDIDATE_K)
        max_chunks_per_book = _bounded_int("max_chunks_per_book", max_chunks_per_book, maximum=MAX_TOP_K)
        max_chunks_per_parent = _bounded_int("max_chunks_per_parent", max_chunks_per_parent, maximum=MAX_TOP_K)
        excerpt_max_chars = _bounded_int("excerpt_max_chars", excerpt_max_chars, maximum=MAX_EXCERPT_MAX_CHARS)
        if candidate_k <= top_k_books:
            raise RetrievalError("candidate_k_not_greater_than_top_k_books")
        vector, embedding_time = self._embed_query(query)
        filter_sql = "book_id IS NOT NULL"
        if exclude_book_id is not None:
            filter_sql = f"book_id != {_sql_literal(exclude_book_id)}"
        rows, search_time = self._search(vector, filter_sql=filter_sql, candidate_k=candidate_k)
        books: dict[str, list[dict[str, Any]]] = {}
        parent_counts: dict[tuple[str, str], int] = {}
        for row in rows:
            book = str(row["book_id"])
            if exclude_book_id is not None and book == exclude_book_id:
                raise RetrievalError("db_book_exclusion_contract_violation")
            if book not in books and len(books) >= top_k_books:
                continue
            if len(books.get(book, [])) >= max_chunks_per_book:
                continue
            parent_key = (book, str(row["parent_record_id"]))
            if parent_counts.get(parent_key, 0) >= max_chunks_per_parent:
                continue
            books.setdefault(book, []).append(row)
            parent_counts[parent_key] = parent_counts.get(parent_key, 0) + 1
        flat = [row for rows_for_book in books.values() for row in rows_for_book]
        materialized, provenance_time = self._materialize(flat, excerpt_max_chars, include_text, context_chars)
        by_id = {item["index_record_id"]: item for item in materialized}
        grouped = []
        for rank, (book_id, chunks) in enumerate(books.items(), start=1):
            first = by_id[chunks[0]["index_record_id"]]
            grouped.append({
                "rank": rank, "book_id": book_id,
                "book_title_normalized": first["book_title_normalized"],
                "author_normalized": first["author_normalized"],
                "raw_metric_name": "l2_distance",
                "raw_metric_value": first["raw_metric_value"],
                "parent_record_ids": list(dict.fromkeys(str(row["parent_record_id"]) for row in chunks)),
                "chunks": [by_id[row["index_record_id"]] for row in chunks],
            })
        response = self._response(query, "other_books", relationship_intent, rows, grouped, embedding_time, search_time, provenance_time)
        return response

    def _materialize(self, rows: list[dict[str, Any]], excerpt_max_chars: int, include_text: bool, context_chars: int) -> tuple[list[dict[str, Any]], float]:
        output: list[dict[str, Any]] = []
        provenance_time = 0.0
        for rank, row in enumerate(rows, start=1):
            item = self._base_result(row, rank)
            if include_text:
                excerpt, elapsed = self._read_excerpt(row, excerpt_max_chars=excerpt_max_chars, context_chars=context_chars)
                item.update(excerpt)
                provenance_time += elapsed
            else:
                item.update({"excerpt": None, "excerpt_start_offset_in_source": None, "excerpt_end_offset_in_source": None, "excerpt_truncated": False})
            output.append(item)
        return output, provenance_time

    def _response(self, query: str, mode: str, intent: str | None, candidates: list[dict[str, Any]], results: list[dict[str, Any]], embedding_time: float, search_time: float, provenance_time: float) -> RetrievalResponse:
        return RetrievalResponse(
            schema_version=SCHEMA_VERSION, query_sha256=_sha256_text(query), mode=mode,
            relationship_intent=intent, raw_candidate_count=len(candidates), result_count=len(results),
            truncated=len(candidates) > len(results), model_identity=self.index_manifest["embedding_model_identity"],
            embedding_dimension=self.embedding_dimension, index_manifest_sha256=self.index_manifest_sha256,
            raw_metric_name="l2_distance", results=results,
            timings={"query_embedding_wall_seconds": embedding_time, "search_wall_seconds": search_time, "provenance_wall_seconds": provenance_time},
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only bounded retrieval for local book-note excerpts")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db-path", type=Path, required=True)
    common.add_argument("--table-name", required=True)
    common.add_argument("--model-path", type=Path, required=True)
    common.add_argument("--source-root", type=Path, required=True)
    common.add_argument("--metadata-dir", type=Path)
    common.add_argument("--query", required=True)
    common.add_argument("--candidate-k", type=int)
    common.add_argument("--excerpt-max-chars", type=int, default=DEFAULT_EXCERPT_MAX_CHARS)
    common.add_argument("--no-text", action="store_true")
    common.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="mode", required=True)
    current = sub.add_parser("current-book", parents=[common])
    current.add_argument("--book-id", required=True)
    current.add_argument("--top-k", type=int, default=5)
    current.add_argument("--max-per-parent", type=int, default=2)
    other = sub.add_parser("other-books", parents=[common])
    other.add_argument("--exclude-book-id")
    other.add_argument("--top-k-books", type=int, default=5)
    other.add_argument("--max-chunks-per-book", type=int, default=2)
    other.add_argument("--max-chunks-per-parent", type=int, default=1)
    other.add_argument("--relationship-intent", choices=["echo", "tension", "completion"])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        retriever = BookNotesRetriever(
            db_path=args.db_path, table_name=args.table_name, model_path=args.model_path,
            source_root=args.source_root, metadata_dir=args.metadata_dir,
        )
        if args.mode == "current-book":
            response = retriever.search_current_book(
                args.query, args.book_id, top_k=args.top_k, candidate_k=args.candidate_k or 40,
                max_per_parent=args.max_per_parent, excerpt_max_chars=args.excerpt_max_chars,
                include_text=not args.no_text,
            )
        else:
            response = retriever.search_other_books(
                args.query, exclude_book_id=args.exclude_book_id, top_k_books=args.top_k_books,
                candidate_k=args.candidate_k or 80, max_chunks_per_book=args.max_chunks_per_book,
                max_chunks_per_parent=args.max_chunks_per_parent,
                relationship_intent=args.relationship_intent, excerpt_max_chars=args.excerpt_max_chars,
                include_text=not args.no_text,
            )
        print(json.dumps(response.to_dict(), ensure_ascii=False, sort_keys=True, indent=2 if args.json else None))
        return 0
    except RetrievalError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
