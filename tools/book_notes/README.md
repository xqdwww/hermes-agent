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
Slice A metadata remains section-level: one manifest record is one resolved
book section. The embedding index is chunk-level: one manifest record produces
one or more deterministic embedding chunks and each chunk becomes one LanceDB
row.

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
they do not store full section text, chunk text, or previews.

Chunking is deterministic and does not use an LLM. It packs paragraphs first,
splits oversized paragraphs on sentence boundaries, and uses token-window
fallback only when a single sentence still exceeds the configured chunk token
limit. `--chunk-max-tokens` sets the per-chunk token ceiling and
`--chunk-overlap-tokens` sets fixed overlap for fallback/continuation windows.
The builder reads the local tokenizer/model limits, reserves special-token
space, and verifies every chunk before embedding. Silent tokenizer/model
truncation is not allowed.

Plan-only mode validates provenance and writes private-free chunk metadata
without loading the embedding model or creating LanceDB:

```text
python tools/book_notes/build_book_notes_index.py \
  --metadata-dir <metadata_v1> \
  --source-root <evernote_chunks> \
  --db-path <target-lancedb-dir> \
  --table-name evernote_book_notes_v1 \
  --model-path <local-bge-m3> \
  --plan-only \
  --chunk-max-tokens 768 \
  --chunk-overlap-tokens 64 \
  --json-summary
```

Embedding batches are controlled by both token and item budgets:
`--max-batch-tokens` caps the sum of chunk tokens in a batch and
`--max-batch-items` caps the number of chunks. The builder must satisfy both
limits; it no longer batches only by parent section count.

Progress is observable through `build_progress.json` and `build_events.jsonl`.
Use `--progress-path` and `--events-path` to put those ledgers in a stable
location; otherwise they live in the temporary build workspace. The progress
file is atomically replaced and includes total/completed chunks, tokens,
batches, last progress time, heartbeat time, current batch start time, RSS, and
resume status. If heartbeat timestamps keep updating while completed counts do
not change, the current batch is still active. If heartbeat and progress both
stop updating beyond an operational threshold, treat the build as a stale
candidate. If the process exits with `resumable: true`, continue with
`--resume`.

`--stop-after-seconds` performs a graceful stop at a safe boundary, keeps the
temporary workspace, and records a resumable checkpoint. `--resume` refuses to
continue unless metadata hashes, model fingerprint, chunking config fingerprint,
builder schema, expected dimension, table name, chunk plan, and completed row
IDs still match. It does not silently rebuild or mix incompatible outputs.

Normal builds write to a temporary directory and atomically publish the verified
index. Before publish, the builder writes final completed progress and
`index_manifest.json`; after publish it must not recreate the temporary
workspace. Existing index directories are not overwritten unless `--rebuild` is
provided. Stopped or failed resumable builds keep their temporary workspace so a
later `--resume` can verify and continue.

Future retrieval must treat vector hits as embedding chunks, then deduplicate or
limit by parent section and book. A retrieval adapter should read local text
only through chunk offsets when needed, not return many adjacent chunks from
one parent by default. Book Capsule aggregation can happen at parent section or
book level; echo/tension/completion judgments remain model-level reasoning, not
raw vector-store labels.

## Bounded Local Retrieval

`retrieve_book_notes.py` is the Slice C1 read-only helper and CLI. Canonical
metadata remains one record per book section, while the formal index stores one
row per embedding chunk. `current-book` applies a LanceDB-level `book_id`
include filter. `other-books` applies a LanceDB-level exclusion filter, groups
hits by book, and enforces both parent-section and per-book caps.

The raw metric is LanceDB L2 distance (`l2_distance`): lower values rank first.
It is not a probability, confidence, endorsement signal, or relationship
classification. `relationship_intent` only carries a caller's requested future
analysis mode. Vector retrieval finds semantically related material; a later
dialogue model must determine whether material is echo, tension, or completion.

The LanceDB table stores no source text. By default, the helper verifies source,
section, and chunk checksums before reading only the matched chunk range. Context
is clamped to the owning section and excerpts have a hard length cap. `--no-text`
returns provenance metadata without opening source files. Paths are constrained
to the approved source root, and empty or overlong queries are rejected rather
than silently truncated.

```text
python tools/book_notes/retrieve_book_notes.py current-book \
  --db-path <lancedb> --table-name evernote_book_notes_v1 \
  --model-path <local-bge-m3> --source-root <evernote_chunks> \
  --metadata-dir <metadata_v1> --book-id <book-id> \
  --query <query> --top-k 5 --no-text --json
```

```text
python tools/book_notes/retrieve_book_notes.py other-books \
  --db-path <lancedb> --table-name evernote_book_notes_v1 \
  --model-path <local-bge-m3> --source-root <evernote_chunks> \
  --metadata-dir <metadata_v1> --exclude-book-id <book-id> \
  --query <query> --top-k-books 5 --relationship-intent echo \
  --no-text --json
```

C1 is a helper/CLI, not a registered Hermes tool or book skill. A future tool
must call this public helper instead of copying its filtering, capping, metric,
or provenance logic.

## Hermes Read-Only Tool Registration

Slice C2 registers one native tool, `book_notes_retrieval`, with exactly three
actions: `resolve_book`, `current_book`, and `other_books`. It is strictly
read-only. Local database, metadata, source, model, and table settings come only
from controlled configuration and are not model-callable parameters. The model
cannot provide arbitrary paths.

`resolve_book` applies the metadata parser's deterministic title and author
normalization, then requires an exact catalog match that is present in the
formal index. It never uses fuzzy matching, semantic title search, author
guessing, an LLM, or the network. Ambiguous titles return at most five candidates
and do not proceed to search.

`current_book` retains C1's LanceDB-level include filter and parent cap.
`other_books` retains its DB-level exclusion filter plus per-book and per-parent
caps. Tool excerpts default to 500 characters and cannot exceed 800. Every hit
uses source label `MY_BOOK_EXCERPT` and guard
`saved_excerpt_not_user_endorsement`: saved source material is not the user's own
view and does not imply endorsement. L2 distance is not a probability, and a
relationship intent is only context for later dialogue, not a finding.

Discovery imports only the schema and registration. Configuration, catalog,
LanceDB, and BGE-M3 are initialized lazily on the first relevant direct call;
`resolve_book` does not load the embedding model. Search initialization is
thread-safe and the synchronous local embedding/search work runs through the
framework's async tool bridge on a controlled thread. C2 registers source code
only: runtime restart and real Hermes invocation are reserved for C2.1. A future
Book Skill must call this tool and must not copy its resolution or retrieval
logic.

`book-notes` is also declared in the canonical built-in `TOOLSETS` catalog.
The static declaration owns enabled-toolset resolution and lists only
`book_notes_retrieval`; the native registry continues to own its schema and
lazy handler. This preserves normal allowlisting: enabling `book-notes` exposes
the tool, while registry presence alone does not bypass toolset filtering.
