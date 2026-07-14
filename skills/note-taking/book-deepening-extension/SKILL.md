---
name: book-deepening-extension
description: "Use when the user wants to start discussing a saved book, explain it with a Feynman-style dialogue, or connect it to books they previously saved. 中文名称：读后深潜与认知延伸。"
license: MIT
metadata:
  hermes:
    display_name: 读后深潜与认知延伸
    internal_design_id: KARPATHY_READING_LAB
    tags: [books, reading, feynman, reflection, connection]
    category: note-taking
    related_skills: []
    requires_tools: [book_notes_retrieval]
---

# 读后深潜与认知延伸

Use the user's saved book excerpts to support a short, focused discussion. The
only retrieval tool for this skill is `book_notes_retrieval`.

## Hard Turn Contract

After this skill is loaded, an entrypoint turn whose preconditions are met must
make exactly one `book_notes_retrieval` call. Once that call returns, do not
repeat, retry, or verify it in the same turn, even when its result is empty or
an error; explain the bounded failure and ask the user what to do next.

Do not substitute `session_search`, `scope_recall_search`, `search_files`,
`read_file`, web search, or research for the required Book Notes action. Text
after the colon in either follow-up entrypoint is already a user-supplied
concept or claim; do not ask the user to restate it before retrieval.

## Interpretation Boundary

保存过的书摘只代表曾被收集或注意，不代表用户认可其中观点。

- Never treat an excerpt as the user's writing, belief, value judgment, or changed position.
- Never describe vector proximity as proof that two books agree, conflict, or complement each other.
- Do not expose absolute paths or internal storage locations.
- Do not print the excerpt library, reconstruct a whole book, or return long sections.

Use these source labels when source attribution helps:

- `[BOOK]`: an excerpt from the active book.
- `[OTHER_BOOK]`: an excerpt from another saved book.
- `[USER]`: something the user explicitly said in this conversation.
- `[INFERENCE]`: a relationship or interpretation inferred by the model.

Do not use `[MY_HIGHLIGHT]` for this data.

## Session State

Maintain only this small state in the current conversation:

```yaml
active_book:
  book_id:
  title:
  author:
  resolution_status:
current_question:
last_retrieval_mode:
```

Do not create a disk checkpoint or write book state to a file. A new
conversation must begin again with `开始讨论《书名》`. If resolution fails or is
ambiguous, do not set `active_book` and do not continue to vector retrieval.

Sensitive tool results may omit `book_id` from later persisted turns. Within
the same conversation, a prior successful start turn plus its confirmed title
still establishes `active_book`. Do not ask the user to start again merely
because the identifier is no longer visible. Prefer `book_id` when present;
otherwise use the confirmed title as the tool's supported selector. Never print
or persist an internal `book_id` just to carry state forward.

## Route The Three Entrypoints

### 1. 开始讨论《书名》

Recognize forms such as:

```text
开始讨论《书名》
开始讨论“书名”
开始讨论 书名
```

Call the tool once:

```yaml
action: resolve_book
book_title: <parsed title>
```

An author may be supplied only when the user supplied one.

- `resolved`: set `active_book` from the tool result, set
  `last_retrieval_mode: resolve_book`, briefly confirm the active book, then ask:
  `你现在最想讨论这本书里的哪个观点、困惑或判断？`
- `ambiguous`: show at most five returned candidates and ask the user to choose.
  Do not guess, rank one as the likely answer, or call another retrieval action.
- `not_found`: say the saved excerpt library has no safe match. Do not search the
  web, start research, or broaden to fuzzy matching.

Starting a discussion resolves identity only. Do not automatically retrieve a
large set of excerpts.

### 2. 费曼聊这本书

If `active_book` is absent, reply exactly enough to direct the next action:

```text
请先说“开始讨论《书名》”。
```

Do not call vector retrieval in that case.

When an active book exists, store the user's concept or claim as
`current_question` and make exactly one default tool call:

```yaml
action: current_book
book_id: <active_book.book_id>
query: <current_question>
top_k: 3
candidate_k: 20
max_per_parent: 1
excerpt_max_chars: 500
include_text: true
```

If the same-session history retains the confirmed title but not `book_id`,
replace only the selector line with:

```yaml
book_title: <active_book.title>
```

Set `last_retrieval_mode: current_book`. Keep the loop short:

1. Treat the text after the entrypoint colon as the user's explanation in their
   own words. Do not ask for a restatement before the tool call.
2. Complete the one bounded `current_book` call.
3. Use up to three bounded excerpts to identify one important gap or tension.
4. Ask one follow-up question; never ask more than two questions in a row.

Choose one primary lens from Feynman, Socratic, critic, connector, or applier.
Use at most one counter-lens. Do not simulate multiple agents or explain an
entire chapter. Do not search other books unless the user invokes the
cross-book entrypoint.

A natural response may use:

```text
你的理解：
书中相关点：
目前最关键的缺口：
一个追问：
```

### 3. 把这本书和我以前读过的书连接起来

Require both an `active_book` and a user-supplied concept, question, or claim.
If either is missing, ask for it and do not call retrieval.

Call the tool once:

```yaml
action: other_books
exclude_book_id: <active_book.book_id>
query: <current_question>
top_k_books: 3
candidate_k: 40
max_chunks_per_book: 1
max_chunks_per_parent: 1
relationship_intent: null
excerpt_max_chars: 500
include_text: true
```

If the same-session history retains the confirmed title but not `book_id`,
replace only the exclusion selector with:

```yaml
exclude_book_title: <active_book.title>
```

Set `last_retrieval_mode: other_books`. Select at most three returned books.
After reading each bounded excerpt, classify the relationship as `echo`,
`tension`, `completion`, or `unclear`. Prefix that judgment with `[INFERENCE]`:
it is the model's interpretation, not a vector-store fact.

For each book, state the connection point and why it may be worth thinking
about. End with one connection question. Never claim the user endorses either
book's excerpt.

## Retrieval Budget

The default per-turn budget is:

```yaml
current_book_results: 3
other_books: 3
chunks_per_other_book: 1
excerpt_max_chars: 500
retrieval_calls_per_turn: 1
```

Do not make a second call automatically. If the result is clearly insufficient,
say so and let the user request another bounded retrieval in a later turn.
Never automatically scan all rows, read a whole section, combine multiple
retrieval strategies, trigger external research, or cross books without the
cross-book entrypoint.

## Response Check

Before replying after retrieval, verify:

- Every excerpt is within the requested character bound.
- Current-book results match `active_book.book_id`.
- Cross-book results exclude `active_book.book_id` and use at most one chunk per book.
- No absolute path is present in the answer.
- Excerpts and user statements carry the correct semantic boundary.
- The reply focuses on one concept and ends with no more than one main question.
