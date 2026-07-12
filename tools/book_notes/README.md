# Book Notes Metadata Preparation

This package contains the Slice A1 deterministic parser for Evernote book-note
exports. It prepares metadata only. It does not create embeddings, LanceDB
collections, Hermes skills, runtime tools, or state files.

## Semantics

When a decoded source range is assigned to a detected book heading, the range is
treated as a saved book excerpt:

```yaml
source_type: evernote_book_excerpt
content_type: book_excerpt
```

Saving an excerpt is not treated as user endorsement, user belief, user stance,
or user-written prose. Only explicit future dialogue can create
`source_type: user_response`.

## Supported Heading Rules

The parser accepts only high-confidence headings:

- Markdown headings on their own line, such as `# <book title>`.
- Chinese book-title marks on their own line, such as `<book title in title marks>`.
- Short standalone title lines when isolated by structure and followed by body
  text.

Inline mentions inside prose are not section headings. Catalog-like lines,
numbered lists, ambiguous short lines, and malformed structures are routed to
the review queue instead of being guessed.

Unresolved heading candidates, such as catalog-like lines or ambiguous short
lines, that fall fully inside a resolved section range are retained as part of
that section's `book_excerpt` text and are not duplicated into the review queue.
Those candidates are only reviewed when they are not safely owned by a resolved
book section.

## Offsets

Offsets use Python decoded string indexes and are recorded as:

```yaml
offset_unit: unicode_codepoint
```

The section offset range excludes the heading line. It starts at the first
non-blank character after the heading and ends at the last non-blank character
before the next detected heading or end of file. Tests assert that slicing the
decoded source text with `section_start_offset:section_end_offset` reproduces
the section text used for `section_text_sha256`.

## Stable IDs

All IDs are deterministic and avoid absolute paths:

- `source_file_id`: SHA-256 over `source-file-v1` and the path relative to
  `--input-root`.
- `section_id`: SHA-256 over `section-v1`, `source_file_id`, `section_index`,
  normalized book title, and section offsets.
- `record_id`: SHA-256 over `record-v1`, `section_id`, and
  `section_text_sha256`.
- `book_id`: SHA-256 over `book-v1`, normalized book title, and normalized
  author. If no explicit author is present, the author token is `__NO_AUTHOR__`.

The parser never guesses authors. Same-title records with conflicting explicit
authors are sent to the review queue.

## CLI

```text
python tools/book_notes/prepare_evernote_metadata.py \
  --input-root <path> \
  --output-dir <path> \
  --dry-run \
  --pretty-stats
```

`--dry-run` prints only aggregate stats and does not create output files.
Without `--dry-run`, the CLI writes `manifest.jsonl` and `review_queue.jsonl`.
Neither file contains section text; they contain metadata, offsets, and
checksums only.

## Offline Index Builder

`build_book_notes_index.py` is an explicit offline step for a private local
LanceDB index. It is not a Hermes runtime tool and it never runs automatically.

Dry-run eligibility validation:

```text
python tools/book_notes/build_book_notes_index.py \
  --metadata-dir <metadata_v1> \
  --source-root <evernote_chunks> \
  --db-path <target-lancedb-dir> \
  --table-name evernote_book_notes_v1 \
  --model-path <local-bge-m3> \
  --dry-run \
  --json-summary
```

The builder only indexes records that are resolved `book_excerpt` sections with
valid provenance and no catalog identity conflict. Conflicted records are
quarantined. The LanceDB rows store metadata, checksums, offsets, and vectors;
they do not store full section text. Future retrieval must use provenance
offsets to read source text from the private Evernote chunks.

Normal builds write to a temporary directory and atomically publish the verified
index. Existing index directories are not overwritten unless `--rebuild` is
provided. Slice B1 tests this mechanism with synthetic data only; formal
embedding of real eligible records belongs to a later explicit slice.
