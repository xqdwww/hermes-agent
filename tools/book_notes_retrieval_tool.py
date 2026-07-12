"""Hermes-native, bounded read-only tool for private book-note retrieval."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tools.book_notes.prepare_evernote_metadata import normalize_author, normalize_book_title
from tools.book_notes.retrieve_book_notes import BookNotesRetriever, RetrievalError
from tools.book_notes.build_book_notes_index import model_fingerprint
from tools.registry import registry


TOOL_NAME = "book_notes_retrieval"
TOOL_SCHEMA_VERSION = "book_notes_retrieval_tool_v1"
SOURCE_SCOPE = "personal_evernote_book_excerpts"
SOURCE_LABEL = "MY_BOOK_EXCERPT"
INTERPRETATION_GUARD = "saved_excerpt_not_user_endorsement"
MAX_QUERY_CHARS = 2000
AMBIGUOUS_CANDIDATES_MAX = 5

CURRENT_TOP_K_DEFAULT = 5
CURRENT_TOP_K_MAX = 8
CURRENT_CANDIDATE_K_DEFAULT = 40
CURRENT_CANDIDATE_K_MAX = 100
CURRENT_MAX_PER_PARENT_DEFAULT = 1
CURRENT_MAX_PER_PARENT_MAX = 2

OTHER_TOP_K_BOOKS_DEFAULT = 5
OTHER_TOP_K_BOOKS_MAX = 8
OTHER_CANDIDATE_K_DEFAULT = 80
OTHER_CANDIDATE_K_MAX = 120
OTHER_MAX_CHUNKS_PER_BOOK_DEFAULT = 2
OTHER_MAX_CHUNKS_PER_BOOK_MAX = 3
OTHER_MAX_CHUNKS_PER_PARENT_DEFAULT = 1
OTHER_MAX_CHUNKS_PER_PARENT_MAX = 2

EXCERPT_MAX_CHARS_DEFAULT = 500
EXCERPT_MAX_CHARS_MAX = 800
RELATIONSHIP_INTENTS = {None, "echo", "tension", "completion"}


@dataclass(frozen=True)
class BookNotesToolConfig:
    db: Path
    table: str
    metadata: Path
    source: Path
    model: Path

    @classmethod
    def from_environment(cls) -> "BookNotesToolConfig":
        return cls(
            db=Path(os.environ.get(
                "HERMES_BOOK_NOTES_DB_PATH",
                "/Users/xqdwww/Workspace/AI_Core/user_profile/book_notes_index/lancedb",
            )).expanduser().resolve(),
            table=os.environ.get("HERMES_BOOK_NOTES_TABLE", "evernote_book_notes_v1"),
            metadata=Path(os.environ.get(
                "HERMES_BOOK_NOTES_METADATA_DIR",
                "/Users/xqdwww/Workspace/AI_Core/user_profile/book_notes_index/metadata_v1",
            )).expanduser().resolve(),
            source=Path(os.environ.get(
                "HERMES_BOOK_NOTES_SOURCE_ROOT",
                "/Users/xqdwww/Workspace/AI_Core/user_profile/evernote_chunks",
            )).expanduser().resolve(),
            model=Path(os.environ.get(
                "HERMES_BOOK_NOTES_MODEL_PATH",
                "/Users/xqdwww/Workspace/AI_Core/lp-knowledge/models/bge-m3",
            )).expanduser().resolve(),
        )

    def cache_key(self) -> tuple[str, ...]:
        manifest = self.db / "index_manifest.json"
        manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else "missing"
        return (str(self.db), self.table, str(self.metadata), str(self.source), str(self.model), manifest_hash)


class BookResolver:
    """Deterministic exact-title resolver over catalog and indexed identities."""

    def __init__(self, config: BookNotesToolConfig, *, table: Any | None = None) -> None:
        catalog_path = config.metadata / "books_catalog.jsonl"
        if not catalog_path.is_file():
            raise RuntimeError("catalog_unavailable")
        try:
            self.catalog = [json.loads(line) for line in catalog_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("catalog_invalid") from exc
        self.table = table or self._open_table(config)
        rows = self._identity_rows(self.table)
        self.chunk_counts = Counter(str(row["book_id"]) for row in rows)
        self.parent_sets: dict[str, set[str]] = {}
        for row in rows:
            self.parent_sets.setdefault(str(row["book_id"]), set()).add(str(row["parent_record_id"]))

    @staticmethod
    def _open_table(config: BookNotesToolConfig) -> Any:
        import lancedb

        if not config.db.is_dir():
            raise RuntimeError("index_unavailable")
        db = lancedb.connect(str(config.db))
        names = list(db.table_names())
        if names.count(config.table) != 1:
            raise RuntimeError("index_unavailable")
        return db.open_table(config.table)

    @staticmethod
    def _identity_rows(table: Any) -> list[dict[str, Any]]:
        if hasattr(table, "identity_rows"):
            return list(table.identity_rows())
        return table.to_arrow().select(["book_id", "parent_record_id"]).to_pylist()

    def is_indexed(self, book_id: str) -> bool:
        return self.chunk_counts.get(book_id, 0) > 0

    def resolve(self, book_title: str, author: str | None = None) -> dict[str, Any]:
        title = normalize_book_title(book_title)
        author_normalized = normalize_author(author)
        if not title:
            return {"status": "not_found", "candidates": []}
        candidates = []
        for row in self.catalog:
            if row.get("book_title_normalized") != title:
                continue
            if author is not None and row.get("author_normalized") != author_normalized:
                continue
            book_id = str(row.get("book_id") or "")
            if not self.is_indexed(book_id) or row.get("conflicts") or row.get("resolution_status") != "resolved":
                continue
            candidates.append({
                "book_id": book_id,
                "book_title_normalized": row.get("book_title_normalized"),
                "author_normalized": row.get("author_normalized"),
                "indexed_chunk_count": self.chunk_counts[book_id],
                "indexed_parent_count": len(self.parent_sets.get(book_id, set())),
            })
        candidates.sort(key=lambda item: (item["book_id"], item.get("author_normalized") or ""))
        if len(candidates) == 1:
            return {"status": "resolved", **candidates[0]}
        if candidates:
            return {"status": "ambiguous", "candidates": candidates[:AMBIGUOUS_CANDIDATES_MAX]}
        return {"status": "not_found", "candidates": []}


class RuntimeManager:
    """Thread-safe split cache: resolver is light; search runtime loads the model."""

    def __init__(
        self,
        *,
        config_factory: Callable[[], BookNotesToolConfig] = BookNotesToolConfig.from_environment,
        resolver_factory: Callable[[BookNotesToolConfig], BookResolver] = BookResolver,
        retriever_factory: Callable[..., BookNotesRetriever] = BookNotesRetriever,
    ) -> None:
        self.config_factory = config_factory
        self.resolver_factory = resolver_factory
        self.retriever_factory = retriever_factory
        self._lock = threading.RLock()
        self._resolver_key: tuple[str, ...] | None = None
        self._resolver: BookResolver | None = None
        self._retriever_key: tuple[str, ...] | None = None
        self._retriever: BookNotesRetriever | None = None

    def resolver(self) -> tuple[BookNotesToolConfig, BookResolver]:
        config = self.config_factory()
        key = config.cache_key()
        with self._lock:
            if self._resolver is not None and self._resolver_key == key:
                return config, self._resolver
            resolver = self.resolver_factory(config)
            self._resolver = resolver
            self._resolver_key = key
            if self._retriever_key is not None and self._retriever_key[:len(key)] != key:
                self._retriever = None
                self._retriever_key = None
            return config, resolver

    def retriever(self) -> tuple[BookNotesToolConfig, BookResolver, BookNotesRetriever]:
        config = self.config_factory()
        key = config.cache_key() + (model_fingerprint(config.model)["fingerprint"],)
        resolver_key = config.cache_key()
        with self._lock:
            if self._resolver is None or self._resolver_key != resolver_key:
                resolver = self.resolver_factory(config)
                self._resolver = resolver
                self._resolver_key = resolver_key
            if self._retriever is not None and self._retriever_key == key:
                return config, self._resolver, self._retriever
            retriever = self.retriever_factory(
                db_path=config.db,
                table_name=config.table,
                model_path=config.model,
                source_root=config.source,
                metadata_dir=config.metadata,
            )
            self._retriever = retriever
            self._retriever_key = key
            return config, self._resolver, retriever


_runtime_manager = RuntimeManager()


def _envelope(action: str, status: str, **payload: Any) -> dict[str, Any]:
    return {
        "schema_version": TOOL_SCHEMA_VERSION,
        "tool_name": TOOL_NAME,
        "action": action,
        "status": status,
        "source_scope": SOURCE_SCOPE,
        "read_only": True,
        "user_endorsement_inferred": False,
        **payload,
    }


def _error(action: str, status: str, code: str) -> str:
    return json.dumps(_envelope(action, status, error_code=code), ensure_ascii=False)


def _bounded(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("parameter_out_of_range")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("parameter_out_of_range") from exc
    if number < minimum or number > maximum:
        raise ValueError("parameter_out_of_range")
    return number


def _resolve_selector(resolver: BookResolver, *, book_id: Any, title: Any, author: Any) -> tuple[str | None, str | None, dict[str, Any] | None]:
    if book_id:
        value = str(book_id)
        if not resolver.is_indexed(value):
            return None, "book_not_indexed", None
        return value, None, None
    if not isinstance(title, str) or not title.strip():
        return None, "missing_book_selector", None
    resolution = resolver.resolve(title, author if isinstance(author, str) else None)
    if resolution["status"] == "ambiguous":
        return None, "book_ambiguous", resolution
    if resolution["status"] != "resolved":
        return None, "book_not_found", resolution
    return str(resolution["book_id"]), None, resolution


def _safe_source_path(config: BookNotesToolConfig, value: Any) -> str:
    path = Path(str(value))
    candidate = path.resolve() if path.is_absolute() else (config.source / path).resolve()
    try:
        return candidate.relative_to(config.source).as_posix()
    except ValueError as exc:
        raise RetrievalError("source_path_traversal") from exc


def _shape_chunk(config: BookNotesToolConfig, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": item["rank"],
        "source_label": SOURCE_LABEL,
        "interpretation_guard": INTERPRETATION_GUARD,
        "book_id": item["book_id"],
        "book_title_normalized": item.get("book_title_normalized"),
        "author_normalized": item.get("author_normalized"),
        "parent_record_id": item["parent_record_id"],
        "section_id": item["section_id"],
        "index_record_id": item["index_record_id"],
        "embedding_chunk_index": item["embedding_chunk_index"],
        "embedding_chunk_count": item["embedding_chunk_count"],
        "raw_metric_name": "l2_distance",
        "raw_metric_value": item["raw_metric_value"],
        "source_type": "evernote_book_excerpt",
        "content_type": "book_excerpt",
        "source_path": _safe_source_path(config, item["source_path"]),
        "section_start_offset": item["section_start_offset"],
        "section_end_offset": item["section_end_offset"],
        "chunk_start_offset_in_source": item["chunk_start_offset_in_source"],
        "chunk_end_offset_in_source": item["chunk_end_offset_in_source"],
        "chunk_text_sha256": item["chunk_text_sha256"],
        "excerpt": item.get("excerpt"),
        "excerpt_truncated": bool(item.get("excerpt_truncated", False)),
    }


def _search_payload(response: Any, *, query: str, relationship_intent: str | None, results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "query_character_count": len(query),
        "relationship_intent": relationship_intent,
        "raw_candidate_count": response.raw_candidate_count,
        "result_count": len(results),
        "truncated": response.truncated,
        "model_identity": response.model_identity,
        "embedding_dimension": response.embedding_dimension,
        "raw_metric_name": "l2_distance",
        "similarity_probability_claimed": False,
        "relationship_classification_performed": False,
        "results": results,
    }


def handle_book_notes_retrieval(args: dict[str, Any], *, manager: RuntimeManager | None = None) -> str:
    manager = manager or _runtime_manager
    action = str(args.get("action") or "")
    if action not in {"resolve_book", "current_book", "other_books"}:
        return _error(action, "invalid_request", "invalid_action")
    try:
        if action == "resolve_book":
            title = args.get("book_title")
            if not isinstance(title, str) or not title.strip():
                return _error(action, "invalid_request", "missing_book_selector")
            _, resolver = manager.resolver()
            result = resolver.resolve(title, args.get("author") if isinstance(args.get("author"), str) else None)
            return json.dumps(_envelope(action, result["status"], **{k: v for k, v in result.items() if k != "status"}), ensure_ascii=False)

        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return _error(action, "invalid_request", "missing_query")
        if len(query) > MAX_QUERY_CHARS:
            return _error(action, "invalid_request", "query_too_long")
        if action == "current_book":
            config, resolver = manager.resolver()
            book_id, error, resolution = _resolve_selector(
                resolver, book_id=args.get("book_id"), title=args.get("book_title"), author=args.get("author"),
            )
            if error:
                status = "ambiguous" if error == "book_ambiguous" else "not_found" if error in {"book_not_found", "book_not_indexed"} else "invalid_request"
                extra = {"candidates": resolution.get("candidates", [])} if resolution else {}
                return json.dumps(_envelope(action, status, error_code=error, **extra), ensure_ascii=False)
            config, resolver, retriever = manager.retriever()
            response = retriever.search_current_book(
                query, book_id,
                top_k=_bounded(args.get("top_k"), default=CURRENT_TOP_K_DEFAULT, minimum=1, maximum=CURRENT_TOP_K_MAX),
                candidate_k=_bounded(args.get("candidate_k"), default=CURRENT_CANDIDATE_K_DEFAULT, minimum=2, maximum=CURRENT_CANDIDATE_K_MAX),
                max_per_parent=_bounded(args.get("max_per_parent"), default=CURRENT_MAX_PER_PARENT_DEFAULT, minimum=1, maximum=CURRENT_MAX_PER_PARENT_MAX),
                excerpt_max_chars=_bounded(args.get("excerpt_max_chars"), default=EXCERPT_MAX_CHARS_DEFAULT, minimum=1, maximum=EXCERPT_MAX_CHARS_MAX),
                include_text=bool(args.get("include_text", True)),
            )
            results = [_shape_chunk(config, item) for item in response.results]
            status = "ok" if results else "no_results"
            return json.dumps(_envelope(action, status, **_search_payload(response, query=query, relationship_intent=None, results=results)), ensure_ascii=False)

        intent = args.get("relationship_intent")
        if intent not in RELATIONSHIP_INTENTS:
            return _error(action, "invalid_request", "invalid_relationship_intent")
        if args.get("exclude_book_id") or args.get("exclude_book_title"):
            config, resolver = manager.resolver()
            excluded_id, error, resolution = _resolve_selector(
                resolver, book_id=args.get("exclude_book_id"), title=args.get("exclude_book_title"), author=args.get("exclude_author"),
            )
        else:
            excluded_id, error, resolution = None, None, None
        if error:
            status = "ambiguous" if error == "book_ambiguous" else "not_found" if error in {"book_not_found", "book_not_indexed"} else "invalid_request"
            extra = {"candidates": resolution.get("candidates", [])} if resolution else {}
            return json.dumps(_envelope(action, status, error_code=error, **extra), ensure_ascii=False)
        config, resolver, retriever = manager.retriever()
        response = retriever.search_other_books(
            query,
            exclude_book_id=excluded_id,
            top_k_books=_bounded(args.get("top_k_books"), default=OTHER_TOP_K_BOOKS_DEFAULT, minimum=1, maximum=OTHER_TOP_K_BOOKS_MAX),
            candidate_k=_bounded(args.get("candidate_k"), default=OTHER_CANDIDATE_K_DEFAULT, minimum=2, maximum=OTHER_CANDIDATE_K_MAX),
            max_chunks_per_book=_bounded(args.get("max_chunks_per_book"), default=OTHER_MAX_CHUNKS_PER_BOOK_DEFAULT, minimum=1, maximum=OTHER_MAX_CHUNKS_PER_BOOK_MAX),
            max_chunks_per_parent=_bounded(args.get("max_chunks_per_parent"), default=OTHER_MAX_CHUNKS_PER_PARENT_DEFAULT, minimum=1, maximum=OTHER_MAX_CHUNKS_PER_PARENT_MAX),
            relationship_intent=intent,
            excerpt_max_chars=_bounded(args.get("excerpt_max_chars"), default=EXCERPT_MAX_CHARS_DEFAULT, minimum=1, maximum=EXCERPT_MAX_CHARS_MAX),
            include_text=bool(args.get("include_text", True)),
        )
        grouped = []
        for book in response.results:
            chunks = [_shape_chunk(config, item) for item in book["chunks"]]
            grouped.append({
                "rank": book["rank"], "book_id": book["book_id"],
                "book_title_normalized": book.get("book_title_normalized"),
                "author_normalized": book.get("author_normalized"),
                "raw_metric_name": "l2_distance", "raw_metric_value": book["raw_metric_value"],
                "parent_record_ids": book["parent_record_ids"], "chunks": chunks,
            })
        status = "ok" if grouped else "no_results"
        return json.dumps(_envelope(action, status, **_search_payload(response, query=query, relationship_intent=intent, results=grouped)), ensure_ascii=False)
    except ValueError:
        return _error(action, "invalid_request", "parameter_out_of_range")
    except RetrievalError as exc:
        code = str(exc)
        if "provenance" in code or "checksum" in code or "source_path" in code:
            return _error(action, "provenance_error", "provenance_validation_failed")
        if "fingerprint" in code:
            return _error(action, "unavailable", "model_fingerprint_mismatch")
        if "dimension" in code:
            return _error(action, "unavailable", "embedding_dimension_mismatch")
        if "model" in code:
            return _error(action, "unavailable", "model_unavailable")
        if "manifest" in code:
            return _error(action, "unavailable", "index_manifest_invalid")
        return _error(action, "unavailable", "index_unavailable")
    except Exception:
        return _error(action, "unavailable", "internal_error")


async def _async_handler(args: dict[str, Any], **_kwargs: Any) -> str:
    return await asyncio.to_thread(handle_book_notes_retrieval, args)


BOOK_NOTES_RETRIEVAL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Strictly read-only retrieval over the user's saved Evernote book excerpts. "
        "Resolve an exact book title, search within that book, or find related excerpts "
        "in other books. A saved excerpt is not the user's own view and does not imply "
        "endorsement. Semantic distance does not establish echo, tension, or completion."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["resolve_book", "current_book", "other_books"]},
            "book_title": {"type": "string", "minLength": 1, "maxLength": 300},
            "author": {"type": ["string", "null"], "maxLength": 200},
            "book_id": {"type": ["string", "null"], "maxLength": 100},
            "exclude_book_title": {"type": ["string", "null"], "maxLength": 300},
            "exclude_author": {"type": ["string", "null"], "maxLength": 200},
            "exclude_book_id": {"type": ["string", "null"], "maxLength": 100},
            "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_CHARS},
            "top_k": {"type": "integer", "minimum": 1, "maximum": CURRENT_TOP_K_MAX, "default": CURRENT_TOP_K_DEFAULT},
            "top_k_books": {"type": "integer", "minimum": 1, "maximum": OTHER_TOP_K_BOOKS_MAX, "default": OTHER_TOP_K_BOOKS_DEFAULT},
            "candidate_k": {"type": "integer", "minimum": 2, "maximum": OTHER_CANDIDATE_K_MAX},
            "max_per_parent": {"type": "integer", "minimum": 1, "maximum": CURRENT_MAX_PER_PARENT_MAX, "default": CURRENT_MAX_PER_PARENT_DEFAULT},
            "max_chunks_per_book": {"type": "integer", "minimum": 1, "maximum": OTHER_MAX_CHUNKS_PER_BOOK_MAX, "default": OTHER_MAX_CHUNKS_PER_BOOK_DEFAULT},
            "max_chunks_per_parent": {"type": "integer", "minimum": 1, "maximum": OTHER_MAX_CHUNKS_PER_PARENT_MAX, "default": OTHER_MAX_CHUNKS_PER_PARENT_DEFAULT},
            "excerpt_max_chars": {"type": "integer", "minimum": 1, "maximum": EXCERPT_MAX_CHARS_MAX, "default": EXCERPT_MAX_CHARS_DEFAULT},
            "include_text": {"type": "boolean", "default": True},
            "relationship_intent": {"type": ["string", "null"], "enum": ["echo", "tension", "completion", None]},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}


registry.register(
    name=TOOL_NAME,
    toolset="book-notes",
    schema=BOOK_NOTES_RETRIEVAL_SCHEMA,
    handler=_async_handler,
    is_async=True,
    description=BOOK_NOTES_RETRIEVAL_SCHEMA["description"],
    max_result_size_chars=20_000,
)
