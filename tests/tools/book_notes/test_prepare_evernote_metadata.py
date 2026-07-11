from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.book_notes.prepare_evernote_metadata import (
    CONTENT_TYPE,
    SOURCE_TYPE,
    detect_heading_candidate,
    line_spans,
    normalize_book_title,
    prepare_metadata,
    prepare_source_text,
    segment_book_sections,
)


def _source_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _prepared(text: str, source_path: str = "reading__0001__synthetic.txt"):
    return prepare_source_text(
        text=text,
        source_bytes=_source_bytes(text),
        source_path=source_path,
        source_file_id="source_fixture",
    )


def test_one_file_one_book_with_bracket_heading():
    text = "《虚构之书甲》\n第一段人工摘录。\n第二段人工摘录。\n"
    prepared = _prepared(text)
    assert len(prepared.manifest_records) == 1
    record = prepared.manifest_records[0]
    assert record["book_title_normalized"] == "虚构之书甲"
    assert record["source_type"] == SOURCE_TYPE
    assert record["content_type"] == CONTENT_TYPE


def test_one_file_three_books_produces_three_records():
    text = (
        "《虚构之书甲》\n甲的人工摘录。\n\n"
        "《虚构之书乙》\n乙的人工摘录。\n\n"
        "《虚构之书丙》\n丙的人工摘录。\n"
    )
    prepared = _prepared(text)
    assert [r["book_title_normalized"] for r in prepared.manifest_records] == [
        "虚构之书甲",
        "虚构之书乙",
        "虚构之书丙",
    ]


def test_markdown_heading_delimits_sections():
    text = "# Synthetic Book One\nExcerpt one.\n\n## Synthetic Book Two\nExcerpt two.\n"
    prepared = _prepared(text)
    assert len(prepared.manifest_records) == 2
    assert {r["heading_detection_method"] for r in prepared.manifest_records} == {"markdown_heading"}


def test_evernote_note_title_can_define_one_book_section():
    text = "# Synthetic Note Title Book\n标签: synthetic\n\nArtificial excerpt body.\n"
    prepared = _prepared(text)
    assert len(prepared.manifest_records) == 1
    record = prepared.manifest_records[0]
    assert record["book_title_normalized"] == "Synthetic Note Title Book"
    assert record["heading_detection_method"] == "note_title_header"
    assert record["metadata_sources"]["book_title"] == "note_title_header"
    sliced = text[record["section_start_offset"] : record["section_end_offset"]]
    assert sliced == "Artificial excerpt body."


def test_standalone_heading_delimits_section():
    text = "Synthetic Book One\nExcerpt one follows on a new line.\n"
    prepared = _prepared(text)
    assert len(prepared.manifest_records) == 1
    assert prepared.manifest_records[0]["heading_detection_method"] == "standalone_line_heading"


def test_same_book_across_two_source_files_shares_book_id(tmp_path: Path):
    root = tmp_path / "input"
    root.mkdir()
    (root / "a.txt").write_text("《Shared Synthetic Book》\nExcerpt A.\n", encoding="utf-8")
    (root / "b.txt").write_text("《Shared Synthetic Book》\nExcerpt B.\n", encoding="utf-8")
    prepared = prepare_metadata(input_root=root, output_dir=tmp_path / "out", dry_run=True)
    book_ids = {record["book_id"] for record in prepared.manifest_records}
    assert len(book_ids) == 1


def test_inline_book_title_mention_is_not_heading():
    text = "《Synthetic Book》\nThe author mentions 《Inline Other Book》 in this artificial sentence.\nMore excerpt.\n"
    prepared = _prepared(text)
    assert len(prepared.manifest_records) == 1
    assert prepared.manifest_records[0]["section_heading_normalized"] == "Synthetic Book"


def test_preamble_before_first_heading_enters_review_queue():
    text = "orphan artificial preface\n\n《Synthetic Book》\nExcerpt.\n"
    prepared = _prepared(text)
    assert len(prepared.manifest_records) == 1
    assert any(r["reason"] == "preamble_without_book_heading" for r in prepared.review_records)


def test_consecutive_headings_create_review_for_empty_section():
    text = "《Synthetic Book Empty》\n《Synthetic Book Body》\nExcerpt.\n"
    prepared = _prepared(text)
    assert len(prepared.manifest_records) == 1
    assert prepared.manifest_records[0]["book_title_normalized"] == "Synthetic Book Body"
    assert any(r["reason"] == "consecutive_headings" for r in prepared.review_records)


def test_same_title_different_authors_create_conflict_review(tmp_path: Path):
    root = tmp_path / "input"
    root.mkdir()
    (root / "a.txt").write_text("《Same Synthetic Title》(Author Alpha)\nExcerpt A.\n", encoding="utf-8")
    (root / "b.txt").write_text("《Same Synthetic Title》(Author Beta)\nExcerpt B.\n", encoding="utf-8")
    prepared = prepare_metadata(input_root=root, output_dir=tmp_path / "out", dry_run=True)
    assert any(r["reason"] == "same_title_author_conflict" for r in prepared.review_records)


def test_missing_author_is_not_guessed():
    prepared = _prepared("《Authorless Synthetic Book》\nExcerpt.\n")
    record = prepared.manifest_records[0]
    assert record["author_raw"] is None
    assert record["author_normalized"] is None
    assert "author_missing_not_inferred" in record["warnings"]


def test_normal_section_content_type_fixed_and_not_personal_reflection():
    prepared = _prepared("《Synthetic Book》\nArtificial excerpt.\n")
    payload = json.dumps(prepared.manifest_records, ensure_ascii=False)
    assert '"content_type": "book_excerpt"' in payload
    assert "personal_reflection" not in payload


def test_section_offset_round_trips_to_original_text():
    text = "《Synthetic Book》\n\nFirst artificial excerpt.\nSecond artificial excerpt.\n"
    prepared = _prepared(text)
    record = prepared.manifest_records[0]
    sliced = text[record["section_start_offset"] : record["section_end_offset"]]
    assert sliced == "First artificial excerpt.\nSecond artificial excerpt."


def test_repeated_run_stable_ids_and_checksums():
    text = "《Stable Synthetic Book》\nStable artificial excerpt.\n"
    first = _prepared(text).manifest_records[0]
    second = _prepared(text).manifest_records[0]
    keys = ["section_id", "record_id", "section_text_sha256", "source_sha256"]
    assert {key: first[key] for key in keys} == {key: second[key] for key in keys}


def test_utf8_chinese_and_english_mixed_content():
    prepared = _prepared("《中英 Synthetic Book》\n中文 artificial excerpt with English words.\n")
    assert prepared.manifest_records[0]["language"] == "mixed"


def test_crlf_offsets_round_trip():
    text = "《CRLF Synthetic Book》\r\nFirst line.\r\nSecond line.\r\n"
    prepared = _prepared(text)
    record = prepared.manifest_records[0]
    assert text[record["section_start_offset"] : record["section_end_offset"]] == "First line.\r\nSecond line."


def test_empty_file_enters_review_queue():
    prepared = _prepared("")
    assert prepared.manifest_records == []
    assert prepared.review_records[0]["reason"] == "malformed_structure"


def test_file_without_trusted_heading_enters_review_queue():
    prepared = _prepared("This artificial paragraph has no heading.\nIt remains unassigned.\n")
    assert prepared.manifest_records == []
    assert any(r["reason"] == "unassigned_text" for r in prepared.review_records)


def test_catalog_line_is_not_section_heading():
    prepared = _prepared("《Catalog A》 《Catalog B》 《Catalog C》\n")
    assert prepared.manifest_records == []
    assert any(r["reason"] == "possible_catalog_or_book_list" for r in prepared.review_records)


def test_checksum_changes_when_source_changes():
    first = _prepared("《Checksum Synthetic Book》\nExcerpt A.\n").manifest_records[0]
    second = _prepared("《Checksum Synthetic Book》\nExcerpt B.\n").manifest_records[0]
    assert first["source_sha256"] != second["source_sha256"]
    assert first["section_text_sha256"] != second["section_text_sha256"]


def test_absolute_root_change_does_not_change_stable_identity(tmp_path: Path):
    root_a = tmp_path / "a" / "root"
    root_b = tmp_path / "b" / "root"
    root_a.mkdir(parents=True)
    root_b.mkdir(parents=True)
    rel = Path("nested") / "file.txt"
    (root_a / rel.parent).mkdir()
    (root_b / rel.parent).mkdir()
    text = "《Portable Synthetic Book》\nExcerpt.\n"
    (root_a / rel).write_text(text, encoding="utf-8")
    (root_b / rel).write_text(text, encoding="utf-8")
    a = prepare_metadata(input_root=root_a, output_dir=tmp_path / "out-a", dry_run=True).manifest_records[0]
    b = prepare_metadata(input_root=root_b, output_dir=tmp_path / "out-b", dry_run=True).manifest_records[0]
    assert a["source_file_id"] == b["source_file_id"]
    assert a["section_id"] == b["section_id"]
    assert a["record_id"] == b["record_id"]


def test_dry_run_does_not_create_output_files(tmp_path: Path):
    root = tmp_path / "input"
    out = tmp_path / "out"
    root.mkdir()
    (root / "file.txt").write_text("《Dry Run Synthetic Book》\nExcerpt.\n", encoding="utf-8")
    prepare_metadata(input_root=root, output_dir=out, dry_run=True)
    assert not out.exists()


def test_cli_stdout_does_not_contain_section_body(tmp_path: Path):
    root = tmp_path / "input"
    out = tmp_path / "out"
    root.mkdir()
    body = "UNIQUE_SYNTHETIC_SECTION_BODY_SHOULD_NOT_PRINT"
    (root / "file.txt").write_text(f"《CLI Synthetic Book》\n{body}\n", encoding="utf-8")
    script = Path("tools/book_notes/prepare_evernote_metadata.py")
    result = subprocess.run(
        [sys.executable, str(script), "--input-root", str(root), "--output-dir", str(out), "--dry-run", "--pretty-stats"],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        check=True,
    )
    assert body not in result.stdout
    assert not out.exists()


def test_malformed_decode_error_enters_review_queue(tmp_path: Path):
    root = tmp_path / "input"
    root.mkdir()
    bad = root / "bad.txt"
    bad.write_bytes(b"\xff\xfe\xfa")
    prepared = prepare_metadata(input_root=root, output_dir=tmp_path / "out", dry_run=True)
    assert prepared.manifest_records == []
    assert prepared.review_records[0]["reason"] == "decode_error"


def test_fail_on_decode_error_raises(tmp_path: Path):
    root = tmp_path / "input"
    root.mkdir()
    (root / "bad.txt").write_bytes(b"\xff\xfe\xfa")
    with pytest.raises(UnicodeDecodeError):
        prepare_metadata(
            input_root=root,
            output_dir=tmp_path / "out",
            dry_run=True,
            fail_on_decode_error=True,
        )


def test_normalize_book_title_removes_generic_suffix():
    assert normalize_book_title("《Synthetic Book》 读书笔记") == "Synthetic Book"


def test_detect_heading_candidate_rejects_sentence_shape():
    spans = line_spans("作者在《Inline Book》中提到一个人工观点。\n")
    assert detect_heading_candidate(spans[0], previous_span=None, next_span=None) is None
