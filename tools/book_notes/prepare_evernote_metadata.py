#!/usr/bin/env python3
"""Deterministic Evernote book-section metadata preparation.

This module intentionally builds metadata only. It does not embed text, build a
vector index, register a Hermes tool, or write runtime state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "book_notes_metadata_v1"
REVIEW_SCHEMA_VERSION = "book_notes_review_v1"
SOURCE_ROOT_ID = "evernote_chunks_v1"
SOURCE_TYPE = "evernote_book_excerpt"
CONTENT_TYPE = "book_excerpt"
OFFSET_UNIT = "unicode_codepoint"
NO_AUTHOR_TOKEN = "__NO_AUTHOR__"

GENERIC_TITLE_SUFFIXES = ("读书笔记", "摘录", "书摘")
REVIEW_HEADING_MAX_CHARS = 120


@dataclass(frozen=True)
class LineSpan:
    index: int
    start: int
    end: int
    body_start: int
    body_end: int
    text: str


@dataclass(frozen=True)
class NoteMetadata:
    note_title_raw: str | None = None
    tags: tuple[str, ...] = ()
    created_at: str | None = None
    updated_at: str | None = None
    content_start_offset: int = 0


@dataclass(frozen=True)
class HeadingCandidate:
    line_index: int
    start_offset: int
    end_offset: int
    raw_heading: str
    normalized_heading: str
    book_title_raw: str
    book_title_normalized: str
    author_raw: str | None
    author_normalized: str | None
    method: str
    status: str
    reason: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class BookSection:
    heading: HeadingCandidate
    section_index: int
    text_start: int
    text_end: int
    section_text: str


@dataclass
class PreparedMetadata:
    manifest_records: list[dict[str, Any]] = field(default_factory=list)
    review_records: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_hash(parts: Iterable[Any], length: int = 20) -> str:
    encoded = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:length]


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def strip_outer_book_marks(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("《") and stripped.endswith("》"):
        return stripped[1:-1].strip()
    return stripped


def normalize_book_title(text: str) -> str:
    """Apply conservative deterministic book-title normalization."""
    value = unicodedata.normalize("NFKC", text or "")
    value = normalize_space(value)
    value = re.sub(r"^#{1,6}\s*", "", value).strip()
    for suffix in GENERIC_TITLE_SUFFIXES:
        value = re.sub(rf"(?:\s*[-—:：]\s*)?{re.escape(suffix)}$", "", value).strip()
    value = strip_outer_book_marks(value)
    for suffix in GENERIC_TITLE_SUFFIXES:
        value = re.sub(rf"(?:\s*[-—:：]\s*)?{re.escape(suffix)}$", "", value).strip()
    value = strip_outer_book_marks(value)
    return normalize_space(value)


def normalize_author(text: str | None) -> str | None:
    if text is None:
        return None
    value = normalize_space(unicodedata.normalize("NFKC", text))
    return value or None


def line_spans(text: str) -> list[LineSpan]:
    spans: list[LineSpan] = []
    offset = 0
    for index, raw in enumerate(text.splitlines(keepends=True)):
        end = offset + len(raw)
        body = raw[:-2] if raw.endswith("\r\n") else raw.rstrip("\n\r")
        spans.append(
            LineSpan(
                index=index,
                start=offset,
                end=end,
                body_start=offset,
                body_end=offset + len(body),
                text=body,
            )
        )
        offset = end
    if not text:
        return []
    if text and not text.endswith(("\n", "\r")):
        # splitlines(keepends=True) already accounted for the final line.
        return spans
    return spans


def parse_note_metadata(text: str) -> NoteMetadata:
    """Parse the canonical Evernote chunk preamble when it is present.

    The preamble is only consumed when a leading markdown title is followed by a
    metadata-looking line or blank separator. A bare top-of-file markdown book
    heading remains available to the section parser.
    """
    spans = line_spans(text)
    if not spans:
        return NoteMetadata()
    first = spans[0].text.strip()
    if not re.match(r"^#\s+\S", first):
        return NoteMetadata()
    lookahead = [span.text.strip() for span in spans[1:5]]
    has_metadata_marker = any(
        item.startswith(("标签:", "创建:", "更新:", "笔记本:")) for item in lookahead
    )
    has_blank_separator = "" in lookahead
    if not (has_metadata_marker and has_blank_separator):
        return NoteMetadata()

    note_title = re.sub(r"^#\s+", "", first).strip() or None
    tags: list[str] = []
    created_at: str | None = None
    updated_at: str | None = None
    content_start = spans[1].start if len(spans) > 1 else len(text)
    for span in spans[1:8]:
        stripped = span.text.strip()
        content_start = span.end
        if stripped == "":
            break
        if stripped.startswith("标签:"):
            raw_tags = stripped.split(":", 1)[1]
            tags = [item.strip() for item in raw_tags.split(",") if item.strip()]
        elif stripped.startswith("创建:"):
            created_at = stripped.split(":", 1)[1].strip() or None
        elif stripped.startswith("更新:"):
            updated_at = stripped.split(":", 1)[1].strip() or None
    return NoteMetadata(
        note_title_raw=note_title,
        tags=tuple(tags),
        created_at=created_at,
        updated_at=updated_at,
        content_start_offset=content_start,
    )


def is_blank_line(span: LineSpan | None) -> bool:
    return span is None or not span.text.strip()


def has_sentence_shape(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) > 72:
        return True
    if re.search(r"[。！？!?；;.]$", stripped):
        return True
    if re.search(r"(提到|认为|说道|写道|因为|所以|但是|然而|如果|我们|他们|作者在)", stripped):
        return True
    return False


def looks_like_catalog_or_list(text: str) -> bool:
    stripped = text.strip()
    if len(re.findall(r"《[^》]{1,80}》", stripped)) >= 2:
        return True
    if re.match(r"^(\d+[\).、]|\-|\*|•)\s+", stripped):
        return True
    separators = stripped.count("、") + stripped.count(";") + stripped.count("；")
    return separators >= 3 and len(stripped) < 120


def _extract_author(raw: str) -> tuple[str, str | None]:
    """Return title text and explicit author text when the heading says so."""
    patterns = [
        r"^(?P<title>.+?)\s*[（(]\s*(?:作者|著者|作者:|作者：)?\s*(?P<author>[^（）()]{1,40})\s*[）)]$",
        r"^(?P<title>.+?)\s*(?:作者|著者|著|by)\s*[:：]?\s*(?P<author>[^:：—\-]{1,40})$",
    ]
    for pattern in patterns:
        match = re.match(pattern, raw, flags=re.IGNORECASE)
        if match:
            title = match.group("title").strip()
            author = match.group("author").strip()
            if title and author:
                return title, author
    return raw, None


def _candidate_from_heading(
    *,
    span: LineSpan,
    raw_heading: str,
    method: str,
    status: str,
    reason: str | None = None,
    warnings: tuple[str, ...] = (),
) -> HeadingCandidate:
    raw_clean = normalize_space(raw_heading)
    raw_clean = re.sub(r"^#{1,6}\s*", "", raw_clean).strip()
    raw_clean = strip_outer_book_marks(raw_clean)
    title_raw, author_raw = _extract_author(raw_clean)
    normalized_heading = normalize_book_title(raw_clean)
    book_title_normalized = normalize_book_title(title_raw)
    author_normalized = normalize_author(author_raw)
    return HeadingCandidate(
        line_index=span.index,
        start_offset=span.body_start,
        end_offset=span.body_end,
        raw_heading=raw_heading.strip(),
        normalized_heading=normalized_heading,
        book_title_raw=title_raw,
        book_title_normalized=book_title_normalized,
        author_raw=author_raw,
        author_normalized=author_normalized,
        method=method,
        status=status,
        reason=reason,
        warnings=warnings,
    )


def detect_heading_candidate(
    span: LineSpan,
    *,
    previous_span: LineSpan | None = None,
    next_span: LineSpan | None = None,
) -> HeadingCandidate | None:
    """Detect high-confidence book-section headings on one isolated line."""
    stripped = span.text.strip()
    if not stripped:
        return None
    if looks_like_catalog_or_list(stripped):
        return _candidate_from_heading(
            span=span,
            raw_heading=stripped[:REVIEW_HEADING_MAX_CHARS],
            method="catalog_or_list",
            status="unresolved",
            reason="possible_catalog_or_book_list",
        )

    markdown = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
    if markdown:
        heading = markdown.group(2)
        if has_sentence_shape(heading):
            return _candidate_from_heading(
                span=span,
                raw_heading=heading,
                method="markdown_heading",
                status="unresolved",
                reason="ambiguous_heading",
            )
        return _candidate_from_heading(
            span=span,
            raw_heading=heading,
            method="markdown_heading",
            status="resolved",
        )

    bracketed = re.match(r"^《([^》]{1,80})》(.*)$", stripped)
    if bracketed:
        tail = bracketed.group(2).strip()
        if tail and not re.match(r"^(?:[（(].{1,50}[）)]|[-—]\s*.{1,50}|作者[:：].{1,40}|著者[:：].{1,40})$", tail):
            return _candidate_from_heading(
                span=span,
                raw_heading=stripped,
                method="book_title_marks",
                status="unresolved",
                reason="ambiguous_heading",
            )
        return _candidate_from_heading(
            span=span,
            raw_heading=stripped,
            method="book_title_marks",
            status="resolved",
        )

    isolated = is_blank_line(previous_span) and not is_blank_line(next_span)
    reasonable_length = 2 <= len(stripped) <= 40
    if isolated and reasonable_length and not has_sentence_shape(stripped):
        if not re.search(r"[，,。！？!?；;]", stripped):
            return _candidate_from_heading(
                span=span,
                raw_heading=stripped,
                method="standalone_line_heading",
                status="resolved",
            )

    if isolated and reasonable_length:
        return _candidate_from_heading(
            span=span,
            raw_heading=stripped,
            method="standalone_line_heading",
            status="unresolved",
            reason="ambiguous_heading",
        )
    return None


def relative_source_path(path: Path, input_root: Path) -> str:
    try:
        return path.resolve().relative_to(input_root.resolve()).as_posix()
    except ValueError:
        return path.name


def infer_notebook_from_relative_path(relative_path: str) -> str | None:
    name = Path(relative_path).name
    if "__" in name:
        return name.split("__", 1)[0] or None
    return None


def infer_note_title_from_relative_path(relative_path: str) -> str | None:
    stem = Path(relative_path).stem
    parts = stem.split("__", 2)
    if len(parts) == 3:
        return parts[2] or None
    return stem or None


def infer_language(text: str) -> str:
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    if has_latin:
        return "en"
    return "unknown"


def trim_text_range(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start] in " \t\r\n":
        start += 1
    while end > start and text[end - 1] in " \t\r\n":
        end -= 1
    return start, end


def build_review_record(
    *,
    source_path: str,
    source_file_id: str,
    start: int,
    end: int,
    candidate_heading: str | None,
    reason: str,
    neighboring_section_ids: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    candidate = normalize_space(candidate_heading or "")
    if len(candidate) > REVIEW_HEADING_MAX_CHARS:
        candidate = candidate[: REVIEW_HEADING_MAX_CHARS - 3] + "..."
    review_id = "review_" + stable_hash(
        ["review-v1", source_file_id, start, end, reason, candidate], length=20
    )
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "review_id": review_id,
        "source_path": source_path,
        "source_file_id": source_file_id,
        "candidate_start_offset": start,
        "candidate_end_offset": end,
        "offset_unit": OFFSET_UNIT,
        "candidate_heading": candidate or None,
        "reason": reason,
        "neighboring_section_ids": neighboring_section_ids or [],
        "warnings": warnings or [],
    }


def review_is_within_section(review: dict[str, Any], section: BookSection) -> bool:
    return (
        section.text_start
        <= int(review["candidate_start_offset"])
        <= int(review["candidate_end_offset"])
        <= section.text_end
    )


def should_keep_review_record(review: dict[str, Any], sections: list[BookSection]) -> bool:
    """Keep only review records that are not safely owned by a resolved section."""
    if review.get("reason") not in {"ambiguous_heading", "possible_catalog_or_book_list"}:
        return True
    return not any(review_is_within_section(review, section) for section in sections)


def book_id_for(title_normalized: str, author_normalized: str | None) -> str:
    author_part = author_normalized or NO_AUTHOR_TOKEN
    return "book_" + stable_hash(["book-v1", title_normalized, author_part], length=16)


def build_manifest_record(
    *,
    source_root_id: str,
    source_path: str,
    source_sha256: str,
    source_size_bytes: int,
    source_file_id: str,
    note: NoteMetadata,
    notebook: str | None,
    section: BookSection,
    language: str,
) -> dict[str, Any]:
    section_text_sha = sha256_text(section.section_text)
    section_id = "section_" + stable_hash(
        [
            "section-v1",
            source_file_id,
            section.section_index,
            section.heading.book_title_normalized,
            section.text_start,
            section.text_end,
        ],
        length=20,
    )
    record_id = "record_" + stable_hash(
        ["record-v1", section_id, section_text_sha], length=20
    )
    book_id = book_id_for(section.heading.book_title_normalized, section.heading.author_normalized)
    note_id = "note_" + source_file_id
    warnings = list(section.heading.warnings)
    if section.heading.author_normalized is None:
        warnings.append("author_missing_not_inferred")
    title_source = (
        "note_title_header"
        if section.heading.method == "note_title_header"
        else "section_heading"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "source_type": SOURCE_TYPE,
        "content_type": CONTENT_TYPE,
        "source_root_id": source_root_id,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "source_size_bytes": source_size_bytes,
        "source_file_id": source_file_id,
        "note_id": note_id,
        "note_title_raw": note.note_title_raw or infer_note_title_from_relative_path(source_path),
        "notebook": notebook,
        "tags": list(note.tags),
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "language": language,
        "section_id": section_id,
        "section_index": section.section_index,
        "section_heading_raw": section.heading.raw_heading,
        "section_heading_normalized": section.heading.normalized_heading,
        "section_start_offset": section.text_start,
        "section_end_offset": section.text_end,
        "offset_unit": OFFSET_UNIT,
        "section_text_sha256": section_text_sha,
        "book_title_raw": section.heading.book_title_raw,
        "book_title_normalized": section.heading.book_title_normalized,
        "author_raw": section.heading.author_raw,
        "author_normalized": section.heading.author_normalized,
        "book_id": book_id,
        "resolution_status": "resolved",
        "resolution_confidence": 1.0,
        "heading_detection_method": section.heading.method,
        "metadata_sources": {
            "book_title": title_source,
            "author": title_source if section.heading.author_raw else None,
            "note_id": "deterministic_surrogate",
            "notebook": "filename_prefix" if notebook else None,
            "tags": "source_header" if note.tags else None,
            "created_at": "source_header" if note.created_at else None,
        },
        "warnings": warnings,
    }


def segment_book_sections(
    text: str,
    *,
    source_path: str,
    source_file_id: str,
    content_start_offset: int = 0,
) -> tuple[list[BookSection], list[dict[str, Any]]]:
    spans = [span for span in line_spans(text) if span.end > content_start_offset]
    reviews: list[dict[str, Any]] = []
    candidates: list[HeadingCandidate] = []
    for pos, span in enumerate(spans):
        previous_span = spans[pos - 1] if pos > 0 else None
        next_span = spans[pos + 1] if pos + 1 < len(spans) else None
        candidate = detect_heading_candidate(
            span,
            previous_span=previous_span,
            next_span=next_span,
        )
        if not candidate:
            continue
        if candidate.status == "resolved":
            candidates.append(candidate)
        else:
            reviews.append(
                build_review_record(
                    source_path=source_path,
                    source_file_id=source_file_id,
                    start=candidate.start_offset,
                    end=candidate.end_offset,
                    candidate_heading=candidate.raw_heading,
                    reason=candidate.reason or "ambiguous_heading",
                    warnings=list(candidate.warnings),
                )
            )

    resolved = sorted(candidates, key=lambda item: item.start_offset)
    sections: list[BookSection] = []
    if not resolved:
        if text[content_start_offset:].strip():
            reviews.append(
                build_review_record(
                    source_path=source_path,
                    source_file_id=source_file_id,
                    start=content_start_offset,
                    end=len(text),
                    candidate_heading=None,
                    reason="unassigned_text",
                )
            )
        else:
            reviews.append(
                build_review_record(
                    source_path=source_path,
                    source_file_id=source_file_id,
                    start=0,
                    end=len(text),
                    candidate_heading=None,
                    reason="malformed_structure",
                    warnings=["empty_or_metadata_only_file"],
                )
            )
        return sections, reviews

    preamble_start, preamble_end = trim_text_range(text, content_start_offset, resolved[0].start_offset)
    if preamble_start < preamble_end:
        reviews.append(
            build_review_record(
                source_path=source_path,
                source_file_id=source_file_id,
                start=preamble_start,
                end=preamble_end,
                candidate_heading=None,
                reason="preamble_without_book_heading",
                neighboring_section_ids=[],
            )
        )

    for index, heading in enumerate(resolved):
        next_heading = resolved[index + 1] if index + 1 < len(resolved) else None
        raw_start = heading.end_offset
        raw_end = next_heading.start_offset if next_heading else len(text)
        start, end = trim_text_range(text, raw_start, raw_end)
        if start >= end:
            reason = "consecutive_headings" if next_heading else "empty_section"
            reviews.append(
                build_review_record(
                    source_path=source_path,
                    source_file_id=source_file_id,
                    start=raw_start,
                    end=raw_end,
                    candidate_heading=heading.raw_heading,
                    reason=reason,
                    warnings=["resolved_heading_without_excerpt_body"],
                )
            )
            continue
        sections.append(
            BookSection(
                heading=heading,
                section_index=len(sections),
                text_start=start,
                text_end=end,
                section_text=text[start:end],
            )
        )
    reviews = [review for review in reviews if should_keep_review_record(review, sections)]
    return sections, reviews


def build_note_title_section_fallback(text: str, note: NoteMetadata) -> BookSection | None:
    """Use a trusted Evernote note title as the section heading for one-book notes."""
    if not note.note_title_raw:
        return None
    title = note.note_title_raw.strip()
    if looks_like_catalog_or_list(title) or has_sentence_shape(title):
        return None
    spans = line_spans(text)
    if not spans:
        return None
    start, end = trim_text_range(text, note.content_start_offset, len(text))
    if start >= end:
        return None
    heading = _candidate_from_heading(
        span=spans[0],
        raw_heading=title,
        method="note_title_header",
        status="resolved",
        warnings=("book_title_from_evernote_note_title",),
    )
    if not heading.book_title_normalized:
        return None
    return BookSection(
        heading=heading,
        section_index=0,
        text_start=start,
        text_end=end,
        section_text=text[start:end],
    )


def prepare_source_text(
    *,
    text: str,
    source_bytes: bytes,
    source_path: str,
    source_file_id: str,
    source_root_id: str = SOURCE_ROOT_ID,
) -> PreparedMetadata:
    note = parse_note_metadata(text)
    sections, reviews = segment_book_sections(
        text,
        source_path=source_path,
        source_file_id=source_file_id,
        content_start_offset=note.content_start_offset,
    )
    if not sections:
        fallback = build_note_title_section_fallback(text, note)
        if fallback is not None:
            sections = [fallback]
            reviews = [
                review
                for review in reviews
                if review.get("reason") not in {"unassigned_text", "malformed_structure"}
            ]
    reviews = [review for review in reviews if should_keep_review_record(review, sections)]
    source_sha = sha256_bytes(source_bytes)
    notebook = infer_notebook_from_relative_path(source_path)
    language = infer_language(text)
    records = [
        build_manifest_record(
            source_root_id=source_root_id,
            source_path=source_path,
            source_sha256=source_sha,
            source_size_bytes=len(source_bytes),
            source_file_id=source_file_id,
            note=note,
            notebook=notebook,
            section=section,
            language=language,
        )
        for section in sections
    ]
    return PreparedMetadata(
        manifest_records=records,
        review_records=reviews,
        stats={
            "sources": 1,
            "manifest_records": len(records),
            "review_records": len(reviews),
            "decode_errors": 0,
        },
    )


def read_utf8_source(path: Path) -> tuple[str, bytes]:
    data = path.read_bytes()
    try:
        return data.decode("utf-8"), data
    except UnicodeDecodeError as exc:
        raise UnicodeDecodeError(exc.encoding, exc.object, exc.start, exc.end, f"UTF-8 decode failed for {path.name}") from exc


def prepare_file(
    path: Path,
    *,
    input_root: Path,
    source_root_id: str = SOURCE_ROOT_ID,
    fail_on_decode_error: bool = False,
) -> PreparedMetadata:
    relative_path = relative_source_path(path, input_root)
    source_file_id = "source_" + stable_hash(["source-file-v1", relative_path], length=20)
    try:
        text, data = read_utf8_source(path)
    except UnicodeDecodeError:
        if fail_on_decode_error:
            raise
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        review = build_review_record(
            source_path=relative_path,
            source_file_id=source_file_id,
            start=0,
            end=0,
            candidate_heading=None,
            reason="decode_error",
            warnings=["utf8_decode_failed"],
        )
        return PreparedMetadata(
            review_records=[review],
            stats={"sources": 1, "manifest_records": 0, "review_records": 1, "decode_errors": 1},
        )
    return prepare_source_text(
        text=text,
        source_bytes=data,
        source_path=relative_path,
        source_file_id=source_file_id,
        source_root_id=source_root_id,
    )


def iter_input_files(input_root: Path, max_files: int | None = None) -> list[Path]:
    files = sorted(path for path in input_root.rglob("*.txt") if path.is_file())
    if max_files is not None:
        return files[: max(0, max_files)]
    return files


def combine_prepared(items: Iterable[PreparedMetadata]) -> PreparedMetadata:
    combined = PreparedMetadata()
    decode_errors = 0
    sources = 0
    for item in items:
        combined.manifest_records.extend(item.manifest_records)
        combined.review_records.extend(item.review_records)
        sources += int(item.stats.get("sources") or 0)
        decode_errors += int(item.stats.get("decode_errors") or 0)
    _append_conflict_reviews(combined)
    combined.stats = {
        "sources": sources,
        "manifest_records": len(combined.manifest_records),
        "review_records": len(combined.review_records),
        "decode_errors": decode_errors,
        "book_ids": len({record["book_id"] for record in combined.manifest_records}),
    }
    return combined


def _append_conflict_reviews(prepared: PreparedMetadata) -> None:
    by_title: dict[str, list[dict[str, Any]]] = {}
    for record in prepared.manifest_records:
        by_title.setdefault(record["book_title_normalized"], []).append(record)
    for title, records in by_title.items():
        authors = {record.get("author_normalized") for record in records}
        non_null_authors = {author for author in authors if author}
        if len(non_null_authors) <= 1:
            continue
        for record in records:
            prepared.review_records.append(
                build_review_record(
                    source_path=record["source_path"],
                    source_file_id=record["source_file_id"],
                    start=record["section_start_offset"],
                    end=record["section_end_offset"],
                    candidate_heading=record["section_heading_raw"],
                    reason="same_title_author_conflict",
                    neighboring_section_ids=[record["section_id"]],
                    warnings=[f"same normalized title has conflicting explicit authors: {title}"],
                )
            )


def prepare_metadata(
    *,
    input_root: Path,
    output_dir: Path | None = None,
    dry_run: bool = True,
    fail_on_decode_error: bool = False,
    max_files: int | None = None,
) -> PreparedMetadata:
    files = iter_input_files(input_root, max_files=max_files)
    prepared = combine_prepared(
        prepare_file(
            path,
            input_root=input_root,
            fail_on_decode_error=fail_on_decode_error,
        )
        for path in files
    )
    if not dry_run:
        if output_dir is None:
            raise ValueError("output_dir is required when dry_run is false")
        output_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(output_dir / "manifest.jsonl", prepared.manifest_records)
        write_jsonl(output_dir / "review_queue.jsonl", prepared.review_records)
    return prepared


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def stats_for_stdout(prepared: PreparedMetadata, *, dry_run: bool, input_root: Path, output_dir: Path | None) -> dict[str, Any]:
    methods: dict[str, int] = {}
    review_reasons: dict[str, int] = {}
    for record in prepared.manifest_records:
        method = str(record.get("heading_detection_method") or "")
        methods[method] = methods.get(method, 0) + 1
    for record in prepared.review_records:
        reason = str(record.get("reason") or "")
        review_reasons[reason] = review_reasons.get(reason, 0) + 1
    return {
        "dry_run": dry_run,
        "input_root_name": input_root.name,
        "output_dir": str(output_dir) if output_dir and not dry_run else None,
        **prepared.stats,
        "heading_methods": methods,
        "review_reasons": review_reasons,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare deterministic Evernote book-section metadata without embeddings or vector stores."
    )
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Do not create manifest/review output files.")
    parser.add_argument("--fail-on-decode-error", action="store_true")
    parser.add_argument("--max-files", type=int, default=None)
    parser.add_argument("--pretty-stats", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    prepared = prepare_metadata(
        input_root=args.input_root,
        output_dir=args.output_dir,
        dry_run=bool(args.dry_run),
        fail_on_decode_error=bool(args.fail_on_decode_error),
        max_files=args.max_files,
    )
    stats = stats_for_stdout(
        prepared,
        dry_run=bool(args.dry_run),
        input_root=args.input_root,
        output_dir=args.output_dir,
    )
    if args.pretty_stats:
        print(json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
