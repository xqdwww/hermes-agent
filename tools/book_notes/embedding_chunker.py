"""Deterministic token-aware chunking for private book-note excerpts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from statistics import median
from typing import Any, Protocol, Sequence


class TokenCounter(Protocol):
    def count_tokens(self, text: str) -> int:
        ...

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        ...


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_max_tokens: int
    chunk_overlap_tokens: int = 0
    min_chunk_tokens: int = 0
    special_token_reserve: int = 0
    effective_model_token_limit: int | None = None

    def validate(self) -> None:
        if self.chunk_max_tokens <= 0:
            raise ValueError("chunk_max_tokens_must_be_positive")
        if self.chunk_overlap_tokens < 0:
            raise ValueError("chunk_overlap_tokens_must_be_non_negative")
        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError("chunk_overlap_must_be_less_than_chunk_max_tokens")
        if self.min_chunk_tokens < 0:
            raise ValueError("min_chunk_tokens_must_be_non_negative")
        if self.effective_model_token_limit is not None:
            if self.chunk_max_tokens + self.special_token_reserve > self.effective_model_token_limit:
                raise ValueError("chunk_limit_exceeds_effective_model_token_limit")

    def fingerprint(self) -> str:
        payload = {
            "chunk_max_tokens": self.chunk_max_tokens,
            "chunk_overlap_tokens": self.chunk_overlap_tokens,
            "min_chunk_tokens": self.min_chunk_tokens,
            "special_token_reserve": self.special_token_reserve,
            "effective_model_token_limit": self.effective_model_token_limit,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class ChunkPlanItem:
    index_record_id: str
    parent_record_id: str
    book_id: str
    section_id: str
    embedding_chunk_index: int
    embedding_chunk_count: int
    source_path: str
    source_sha256: str
    source_file_id: str
    section_start_offset: int
    section_end_offset: int
    section_text_sha256: str
    chunk_start_offset_in_section: int
    chunk_end_offset_in_section: int
    chunk_start_offset_in_source: int
    chunk_end_offset_in_source: int
    offset_unit: str
    chunk_text_sha256: str
    chunk_token_count: int
    chunk_character_count: int
    chunking_strategy: str
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    source_type: str
    content_type: str
    resolution_status: str
    text: str

    def public_row(self) -> dict[str, Any]:
        row = self.__dict__.copy()
        row.pop("text", None)
        return row


@dataclass(frozen=True)
class BatchPlan:
    batch_index: int
    item_count: int
    token_count: int
    first_index_record_id: str
    last_index_record_id: str
    start: int
    end: int

    def public_row(self) -> dict[str, Any]:
        return {
            "batch_index": self.batch_index,
            "item_count": self.item_count,
            "token_count": self.token_count,
            "first_index_record_id": self.first_index_record_id,
            "last_index_record_id": self.last_index_record_id,
        }


class SimpleTokenCounter:
    """Small deterministic tokenizer for synthetic tests.

    It treats each non-space character as one token, which makes offset checks
    precise without depending on external model files.
    """

    def count_tokens(self, text: str) -> int:
        return len([char for char in text if not char.isspace()])

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        return [(idx, idx + 1) for idx, char in enumerate(text) if not char.isspace()]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _spans_for_regex(text: str, pattern: str) -> list[tuple[int, int]]:
    spans = [(match.start(), match.end()) for match in re.finditer(pattern, text, flags=re.DOTALL)]
    return [(start, end) for start, end in spans if start < end and text[start:end].strip()]


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans = _spans_for_regex(text, r".+?(?:\n\s*\n|$)")
    return spans or ([(0, len(text))] if text else [])


def _sentence_spans(text: str, base_start: int, base_end: int) -> list[tuple[int, int]]:
    fragment = text[base_start:base_end]
    spans = _spans_for_regex(fragment, r".+?(?:[.!?。！？]\s+|[.!?。！？]|$)")
    return [(base_start + start, base_start + end) for start, end in spans] or [(base_start, base_end)]


def _token_window_spans(
    text: str,
    tokenizer: TokenCounter,
    start: int,
    end: int,
    config: ChunkingConfig,
) -> list[tuple[int, int, str]]:
    token_spans = tokenizer.token_spans(text[start:end])
    if not token_spans:
        return [(start, end, "token_window")]
    absolute = [(start + token_start, start + token_end) for token_start, token_end in token_spans]
    step = max(1, config.chunk_max_tokens - config.chunk_overlap_tokens)
    windows: list[tuple[int, int, str]] = []
    token_index = 0
    while token_index < len(absolute):
        window_tokens = absolute[token_index : token_index + config.chunk_max_tokens]
        windows.append((window_tokens[0][0], window_tokens[-1][1], "token_window"))
        if token_index + config.chunk_max_tokens >= len(absolute):
            break
        token_index += step
    return windows


def _split_oversized_unit(
    text: str,
    tokenizer: TokenCounter,
    start: int,
    end: int,
    config: ChunkingConfig,
) -> list[tuple[int, int, str]]:
    sentence_spans = _sentence_spans(text, start, end)
    if len(sentence_spans) > 1:
        return _pack_units(text, tokenizer, sentence_spans, config, default_strategy="sentence")
    return _token_window_spans(text, tokenizer, start, end, config)


def _overlap_start(text: str, tokenizer: TokenCounter, start: int, end: int, overlap_tokens: int) -> int:
    if overlap_tokens <= 0 or start <= 0:
        return start
    spans = tokenizer.token_spans(text[:start])
    if not spans:
        return start
    overlap = spans[max(0, len(spans) - overlap_tokens) :]
    return overlap[0][0] if overlap else start


def _pack_units(
    text: str,
    tokenizer: TokenCounter,
    units: Sequence[tuple[int, int]],
    config: ChunkingConfig,
    *,
    default_strategy: str,
) -> list[tuple[int, int, str]]:
    chunks: list[tuple[int, int, str]] = []
    current_start: int | None = None
    current_end: int | None = None
    for unit_start, unit_end in units:
        if tokenizer.count_tokens(text[unit_start:unit_end]) > config.chunk_max_tokens:
            if current_start is not None and current_end is not None:
                chunks.append((current_start, current_end, default_strategy))
                current_start = None
                current_end = None
            chunks.extend(_split_oversized_unit(text, tokenizer, unit_start, unit_end, config))
            continue
        if current_start is None:
            current_start = unit_start
            current_end = unit_end
            continue
        proposed = text[current_start:unit_end]
        if tokenizer.count_tokens(proposed) <= config.chunk_max_tokens:
            current_end = unit_end
        else:
            chunks.append((current_start, current_end or unit_start, default_strategy))
            current_start = _overlap_start(text, tokenizer, unit_start, unit_start, config.chunk_overlap_tokens)
            current_end = unit_end
            while tokenizer.count_tokens(text[current_start:current_end]) > config.chunk_max_tokens and current_start < unit_start:
                current_start += 1
    if current_start is not None and current_end is not None:
        chunks.append((current_start, current_end, default_strategy))
    return chunks


def chunk_section(
    record: dict[str, Any],
    section_text: str,
    tokenizer: TokenCounter,
    config: ChunkingConfig,
) -> list[ChunkPlanItem]:
    config.validate()
    section_start = int(record["section_start_offset"])
    section_end = int(record["section_end_offset"])
    raw_chunks = _pack_units(
        section_text,
        tokenizer,
        _paragraph_spans(section_text),
        config,
        default_strategy="paragraph",
    )
    if not raw_chunks and section_text:
        raw_chunks = [(0, len(section_text), "paragraph")]

    checked: list[tuple[int, int, str, int]] = []
    oversized_after = 0
    for start, end, strategy in raw_chunks:
        chunk_text = section_text[start:end]
        token_count = tokenizer.count_tokens(chunk_text)
        if token_count > config.chunk_max_tokens:
            oversized_after += 1
        if token_count > 0:
            checked.append((start, end, strategy, token_count))
    if oversized_after:
        raise ValueError(f"oversized_chunks_after_split={oversized_after}")

    total = len(checked)
    fingerprint = config.fingerprint()
    items: list[ChunkPlanItem] = []
    for index, (start, end, strategy, token_count) in enumerate(checked):
        chunk_text = section_text[start:end]
        chunk_hash = sha256_text(chunk_text)
        id_payload = "\0".join(
            [
                str(record["record_id"]),
                str(start),
                str(end),
                chunk_hash,
                fingerprint,
            ]
        )
        index_record_id = "chunk_" + hashlib.sha256(id_payload.encode("utf-8")).hexdigest()[:32]
        items.append(
            ChunkPlanItem(
                index_record_id=index_record_id,
                parent_record_id=str(record["record_id"]),
                book_id=str(record["book_id"]),
                section_id=str(record["section_id"]),
                embedding_chunk_index=index,
                embedding_chunk_count=total,
                source_path=str(record["source_path"]),
                source_sha256=str(record["source_sha256"]),
                source_file_id=str(record["source_file_id"]),
                section_start_offset=section_start,
                section_end_offset=section_end,
                section_text_sha256=str(record["section_text_sha256"]),
                chunk_start_offset_in_section=start,
                chunk_end_offset_in_section=end,
                chunk_start_offset_in_source=section_start + start,
                chunk_end_offset_in_source=section_start + end,
                offset_unit=str(record.get("offset_unit") or "unicode_codepoint"),
                chunk_text_sha256=chunk_hash,
                chunk_token_count=token_count,
                chunk_character_count=len(chunk_text),
                chunking_strategy=strategy,
                chunk_max_tokens=config.chunk_max_tokens,
                chunk_overlap_tokens=config.chunk_overlap_tokens,
                source_type=str(record.get("source_type") or "evernote_book_excerpt"),
                content_type=str(record.get("content_type") or "book_excerpt"),
                resolution_status=str(record.get("resolution_status") or "resolved"),
                text=chunk_text,
            )
        )
    return items


def summarize_plan(
    *,
    eligible_parent_records: int,
    quarantined_parent_records: int,
    chunks: Sequence[ChunkPlanItem],
) -> dict[str, Any]:
    token_counts = [chunk.chunk_token_count for chunk in chunks]
    chunk_counts_by_parent: dict[str, int] = {}
    for chunk in chunks:
        chunk_counts_by_parent[chunk.parent_record_id] = chunk.embedding_chunk_count
    parent_counts = list(chunk_counts_by_parent.values())
    total_tokens = sum(token_counts)
    return {
        "eligible_parent_records": eligible_parent_records,
        "quarantined_parent_records": quarantined_parent_records,
        "embedding_chunks": len(chunks),
        "total_tokens": total_tokens,
        "average_tokens_per_chunk": (total_tokens / len(chunks)) if chunks else 0,
        "median_tokens_per_chunk": median(token_counts) if token_counts else 0,
        "p95_tokens_per_chunk": _percentile(token_counts, 95),
        "maximum_tokens_per_chunk": max(token_counts) if token_counts else 0,
        "minimum_tokens_per_chunk": min(token_counts) if token_counts else 0,
        "sections_with_one_chunk": sum(1 for count in parent_counts if count == 1),
        "sections_with_multiple_chunks": sum(1 for count in parent_counts if count > 1),
        "maximum_chunks_per_section": max(parent_counts) if parent_counts else 0,
        "oversized_chunks_after_split": 0,
        "silent_truncation_allowed": False,
    }


def _percentile(values: Sequence[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1))))
    return ordered[index]


def plan_batches(
    chunks: Sequence[ChunkPlanItem],
    *,
    max_batch_tokens: int,
    max_batch_items: int,
) -> list[BatchPlan]:
    if max_batch_tokens <= 0 or max_batch_items <= 0:
        raise ValueError("batch_budgets_must_be_positive")
    batches: list[BatchPlan] = []
    start = 0
    token_total = 0
    for idx, chunk in enumerate(chunks):
        if chunk.chunk_token_count > max_batch_tokens:
            raise ValueError("chunk_exceeds_max_batch_tokens")
        item_count = idx - start
        would_exceed_tokens = token_total + chunk.chunk_token_count > max_batch_tokens
        would_exceed_items = item_count >= max_batch_items
        if item_count and (would_exceed_tokens or would_exceed_items):
            batch_chunks = chunks[start:idx]
            batches.append(
                BatchPlan(
                    batch_index=len(batches),
                    item_count=len(batch_chunks),
                    token_count=sum(item.chunk_token_count for item in batch_chunks),
                    first_index_record_id=batch_chunks[0].index_record_id,
                    last_index_record_id=batch_chunks[-1].index_record_id,
                    start=start,
                    end=idx,
                )
            )
            start = idx
            token_total = 0
        token_total += chunk.chunk_token_count
    if start < len(chunks):
        batch_chunks = chunks[start:]
        batches.append(
            BatchPlan(
                batch_index=len(batches),
                item_count=len(batch_chunks),
                token_count=sum(item.chunk_token_count for item in batch_chunks),
                first_index_record_id=batch_chunks[0].index_record_id,
                last_index_record_id=batch_chunks[-1].index_record_id,
                start=start,
                end=len(chunks),
            )
        )
    return batches
