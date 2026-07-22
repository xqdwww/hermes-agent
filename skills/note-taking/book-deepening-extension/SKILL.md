---
name: book-deepening-extension
description: "Use when the user wants to start discussing a saved book, explain it with a Feynman-style dialogue, connect it to books they previously saved, or explicitly enter a continuous guided book discussion. 中文名称：读后深潜与认知延伸。"
license: MIT
metadata:
  hermes:
    display_name: 读后深潜与认知延伸
    internal_design_id: KARPATHY_READING_LAB
    tags: [books, reading, feynman, reflection, connection, guided-discussion]
    category: note-taking
    related_skills: []
    requires_tools: [book_notes_retrieval, agy_book_dialogue]
---

# 读后深潜与认知延伸

Support a short, focused book discussion using saved excerpts when available,
model knowledge when they are not, or text the user provides for this session.
The only personal-excerpt retrieval tool for this skill is
`book_notes_retrieval`.

## Guided Meta Question Gate

While Guided Mode B is active, treat these as meta questions rather than book
answers: `你现在用的什么模型？`, `刚才调用了哪个工具？`,
`为什么没有找到书摘？`, `现在是什么模式？`, and `可以退出吗？` Answer the
meta question directly, pause automatic guided progression, do not call
`agy_book_dialogue` or `book_notes_retrieval`. In particular, do not call `agy_book_dialogue`,
do not repeat the previous reading question, and do not increment `effective_turns`.
Preserve the current stage and resume only when the user returns to book content. For model identity, explain
the controller and dialogue engine with exactly this sentence and nothing else:

```text
主会话控制器是 DeepSeek V4 Flash；引导式读书模式 B 的文学对谈轮次可由 AGY Gemini 3.1 Pro (High) 生成。本轮是元问题，没有调用 AGY。
```

Do not claim AGY is unavailable unless an AGY call actually failed on the
current turn. For any meta question, do not mention the saved focus question,
stage, active book, or an invitation to resume.

## Active Guided Turn Gate

This gate has priority over answering the book question. If an earlier message
in this conversation says the user entered `引导式读书模式`, contains the
`guided_mode_b` state marker below, or the user asks to continue it. In all cases,
treat `guided_mode.active` as true until a Close response explicitly
ends it. Reconstruct the small guided state from the current conversation before
responding; do not fall back to ordinary Mode A merely because the latest user
message omits the guided entrypoint.

While guided mode is active, never answer a newly supplied focus question before
the user has explained their present understanding. If the conversation contains
the focus question but no later user explanation, reply with exactly this one
sentence and nothing else:

```text
先不用追求完整。你用两三句话说说，你目前怎么理解这个问题？
```

Do not provide an analysis, examples, categories, a tentative answer, or a tool
call on that Explain turn. A question alone is not the user's explanation.

When a successful `agy_book_dialogue` result says
`delivery_mode: verbatim`, deliver the `response` field verbatim.
Do not summarize, rewrite, template, compress, or add a second question.
Remove only blank CLI wrapping or block an internal-path diagnostic; do not merge a
DeepSeek answer with the AGY answer.

An explicit guided exit phrase has the same priority. When the user says
`退出引导式读书模式`, `结束这轮读书讨论`, or `先聊到这里`, do not continue the
Probe or Connect loop. Return a short Close response containing these three
labels exactly once, in this order, and do not ask a new follow-up question:

```text
这轮你已经说清楚了：
仍然悬而未决的是：
最值得带走的一个问题：
```

## Hard Turn Contract

The start entrypoint must make exactly one `resolve_book` call. The Feynman and
cross-book entrypoints make exactly one `book_notes_retrieval` call only when
the mode-specific preconditions below require it. Once a call returns, do not
repeat, retry, or verify it in the same turn, even when its result is empty or
an error.

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
- `[MODEL_KNOWLEDGE]`: model knowledge used without a personal excerpt match.
- `[PROVIDED_TEXT]`: text actually supplied or successfully injected in this session.
- `[USER]`: something the user explicitly said in this conversation.
- `[INFERENCE]`: a relationship or interpretation inferred by the model.

Do not use `[MY_HIGHLIGHT]` for this data. Never relabel `[PROVIDED_TEXT]` as a
saved personal excerpt.

## Discussion Modes

Use exactly one current mode:

- `personal_excerpt_discussion`: `resolve_book.status` was `resolved`; saved
  excerpts may be retrieved with `[BOOK]`.
- `general_discussion`: the personal excerpt index did not resolve the book and
  no source text has been provided. Use `[MODEL_KNOWLEDGE]`, `[USER]`, and
  `[INFERENCE]` when attribution matters.
- `provided_text_discussion`: relevant text was pasted, uploaded and injected,
  or successfully read by an existing safe file capability. Use
  `[PROVIDED_TEXT]`, `[USER]`, and `[INFERENCE]`.

In general mode, say clearly that the discussion is not using the user's saved
excerpts. Model knowledge is allowed, but do not claim to know the user's exact
edition. State uncertainty about exact plot details, wording, translation, or
chapter placement. Never invent quotations, page numbers, or chapter locations.
Do not automatically call `current_book`, call `other_books`, search the web, or
start research. An explicit cross-book entrypoint with a clear concept may make
one bounded `other_books` call as described below.

## Retrieval Status Contract

Keep retrieval status separate from discussion mode and pass the exact status
to AGY:

```yaml
retrieval_status: resolved
personal_excerpt_available: true
retrieval_operational: true
---
retrieval_status: not_found
personal_excerpt_available: false
retrieval_operational: true
---
retrieval_status: unavailable
personal_excerpt_available: unknown
retrieval_operational: false
```

Never describe `unavailable` as `not_found`, or `not_found` as a temporarily
unavailable tool. An unavailable result leaves excerpt availability unknown and
must not become a claim about whether the user has notes.

## Session State

Maintain only this small state in the current conversation:

```yaml
active_book:
  book_id:
  title:
  author:
  resolution_status:
discussion_mode:
personal_excerpt_available:
retrieval_status:
retrieval_operational:
current_question:
last_retrieval_mode:
source_prompt_offered:
provided_source_type:
temporary_session_source:
guided_mode:
  active:
  mode:
  display_name:
  active_book:
    title:
    book_id:
    resolution_status:
  discussion_mode:
  stage:
  focus_question:
  effective_turns:
  retrieval_calls_this_turn:
  connection_used:
  dialogue_engine:
```

Do not create a disk checkpoint or write book state to a file. A new
conversation must begin again with `开始讨论《书名》`. If resolution is
ambiguous, do not set `active_book`. If it is `not_found`, keep only the title
the user supplied, set `book_id: null`, and continue in general mode without
current-book vector retrieval.

Sensitive tool results may omit `book_id` from later persisted turns. Within
the same conversation, a prior successful start turn plus its confirmed title
still establishes `active_book`. Do not ask the user to start again merely
because the identifier is no longer visible. Prefer `book_id` when present;
otherwise use the confirmed title as the tool's supported selector. Never print
or persist an internal `book_id` just to carry state forward.

## Guided Mode B

`guided_mode_b`（显示名：`引导式读书模式 B`）是本 Skill 内、仅存在于当前
conversation context 的会话引导模式，不是 Hermes 持久化 Workflow 或 DAG。
Set `guided_mode_created: true` and `formal_workflow_created: false` only as
behavioral facts; never create or modify a Workflow, router, TaskMode,
checkpoint, database, provider, index, background service, memory, or runtime
configuration. The registered `agy_book_dialogue` tool described below is the
only added executor for this mode; do not create any further platform feature.

Recognize only explicit guided entrypoints:

```text
进入引导式读书模式《书名》
用引导模式聊《书名》
开始连续聊《书名》
```

The three manual Mode A entrypoints below remain manual and must never activate
Guided Mode B. On a guided entrypoint, set `guided_mode.active: true`,
`guided_mode.mode: guided_mode_b`, `effective_turns: 0`,
`retrieval_calls_this_turn: 0`, and `connection_used: false`; then make exactly
one `resolve_book` call. Do not retrieve excerpts, summarize the book, introduce
the author, or connect books on this orient turn. Never call `agy_book_dialogue`
on the orient turn.

### AGY Dialogue Executor

Use this tool only for Guided Mode B literary turns:

```yaml
tool_name: agy_book_dialogue
action: respond
book:
  title: <active title>
  author: <known author or null>
  resolution_status: <resolved | not_found | unavailable>
  retrieval_status: <resolved | not_found | unavailable>
  personal_excerpt_available: <true | false | null>
  retrieval_operational: <true | false>
  discussion_mode: <current discussion mode>
guided_mode:
  stage: <explain | probe | connect | close>
  focus_question: <current focus>
  effective_turns: <0..6>
  next_action: <one action or null>
user:
  current_message: <latest book-content message only>
  current_explanation: <latest explicit explanation only>
evidence:
  current_book_excerpts: <at most 3 current excerpts>
  other_book_excerpts: <at most 3 books, one excerpt each>
  provided_text: <bounded current-session text or null>
limits:
  max_current_book_excerpts: 3
  max_other_books: 3
  max_excerpt_chars_each: 500
  max_context_chars: 10000
```

Never pass full session history, a whole book, arbitrary paths, credentials,
memory, tool logs, or unrelated dialogue. Per user turn:

```yaml
book_notes_retrieval_calls: 1
agy_calls_per_turn: 1
```

Stage routing is strict. orient: never call `agy_book_dialogue`. explain: use
the fixed local invitation by default, though one AGY call is allowed. probe: call `agy_book_dialogue` once by default
after at most one current-book call. connect: call `agy_book_dialogue` once after the bounded `other_books` call.
close: call `agy_book_dialogue` once for the short close. Never call AGY for a meta question.

On `status: ok`, set `dialogue_engine: agy_gemini_3_1_pro_high` and obey the
verbatim delivery gate. On `timeout`, `empty_output`, `auth_unavailable`,
`location_unsupported`, `model_unavailable`, `binary_missing`, or
`command_failed`, set `dialogue_engine: deepseek_fallback`, say at most once:
`这一轮 Gemini 对谈引擎暂时不可用，我先用当前模型继续。` Then continue under the existing Guided Mode B contract
with DeepSeek. Never call GPT Bridge, never retry AGY in the same turn, and never expose raw stderr.

### Orient And Explain

- `resolved`: set the guided active book, `personal_excerpt_discussion`, and
  `stage: orient`. Say: `已经进入《书名》的引导式读书模式。` Then ask exactly one
  focus question: `这一轮我们先只解决一个问题：你现在最想检验的观点、困惑或判断是什么？`
- `not_found`: keep the supplied title with `book_id: null`, set
  `general_discussion` and `stage: orient`, and continue. Say that the personal
  excerpt index did not match, so this round will not cite previously saved
  excerpts, but discussion can continue. Ask the same single focus question.
  Do not call `current_book`, browse, introduce the work, infer that the user
  has no notes, or repeatedly request a file.
- `ambiguous`: show at most five candidates and wait for the user's choice.
  Never choose automatically.

For either resolved or not-found orient responses, append this exact invisible
conversation-state marker after the focus question:

```html
<!-- guided_mode_b: active; stage=awaiting_focus_question; user_explanation_received=false -->
```

This marker is session context only. It is not a disk checkpoint, persisted
workflow state, telemetry, or a reason to expose any internal book identifier.
When the marker is present and the next user message is only a question, the
Active Guided Turn Gate applies without interpretation: a question is not an
explanation, even if it contains a tentative premise or contrast.

When the user supplies only a focus question, set `stage: explain` and ask only:
`先不用追求完整。你用两三句话说说，你目前怎么理解这个问题？` Do not answer
it first; the Active Guided Turn Gate requires that sentence and nothing else.
If the same turn already contains the user's own explanation, do not
ask again; proceed directly to Probe.

### Probe Short Loop

Set `stage: probe` and reset `retrieval_calls_this_turn: 0`. In
`personal_excerpt_discussion`, make at most one call with the existing helper:

```yaml
action: current_book
book_id: <guided_mode.active_book.book_id>
query: <short combination of focus_question and the user's explanation>
top_k: 3
candidate_k: 20
max_per_parent: 1
excerpt_max_chars: 500
include_text: true
```

Use the confirmed-title selector fallback already defined for Mode A when the
same-session identifier is unavailable. In `general_discussion`, do not call
`current_book`; use the user's explanation and bounded model knowledge while
stating that no personal excerpt was used. In `provided_text_discussion`, use
only text actually present and never label it as personal history unless the
user explicitly requests a later comparison.

After that bounded retrieval decision, make the one default AGY `probe` call
with the exact retrieval status and only the current turn's bounded evidence.
DeepSeek performs no literary analysis when AGY succeeds.

Each Probe reply performs exactly four actions: accurately restate the user's
understanding, add one most relevant point, identify one main gap, and ask one
main follow-up question. Allow at most one secondary question and one
counter-lens. Choose one primary lens from Feynman, Socratic, critic, connector,
or applier. Do not simulate a multi-agent discussion.

After each effective user answer, increment `effective_turns` once and choose
only one `next_action`: `clarify`, `deepen`, `connect`, or `close`. Clarify one
definition, premise, or causal link. Deepen exactly one of premise, mechanism,
boundary, counterexample, or application. Never present a list of simultaneous
paths.

### Connect

Enter `stage: connect` only when the user explicitly asks, or after at least one
completed Probe when the connection is clearly useful. Automatic connection is
allowed once per guided session; set `connection_used: true`. A later connection
requires another explicit request. Make at most one call:

```yaml
action: other_books
exclude_book_id: <guided_mode.active_book.book_id or omit when null>
query: <the clarified focus question>
top_k_books: 3
candidate_k: 40
max_chunks_per_book: 1
max_chunks_per_parent: 1
relationship_intent: null
excerpt_max_chars: 500
include_text: true
```

Select at most three books and one chunk per book. Label every model-assigned
`echo`, `tension`, `completion`, or `unclear` relationship with `[INFERENCE]`;
vector similarity does not establish that relationship. For each book give only
the title, relationship, connection point, and use for the current question.

Send those bounded results to the one AGY `connect` call; AGY, not the vector
store, assigns the `[INFERENCE]` relationship.

### Close, Pause, And Resume

The soft turn target is 4 and hard turn cap is 6. Close early when the user says
`退出引导式读书模式`, `结束这轮读书讨论`, or `先聊到这里`, or when the focus has a
clear conclusion. At 6 effective turns, closing is mandatory and no further
question is allowed. Set `stage: close`, then use the three exact Close labels
from the Active Guided Turn Gate to state what the user made clear, what remains
unresolved, and one question worth carrying forward; use at
most five short points. The final label records a takeaway question but must not invite another
turn. Finally set `guided_mode.active: false`.

Use one AGY `close` call before delivery. If it fails, DeepSeek applies the same
three-label close contract after the single fallback notice.

If the user changes topic, preserve the in-context state but pause automatic
progression. On `继续刚才的引导式读书`, resume the most recent stage only when the
state is coherent. If it is missing or inconsistent, say:
`刚才的引导状态已经不完整。书名可以保留，我们重新确认一下这轮最想讨论的问题。`
Do not create disk recovery. Close never creates a permanent Book Capsule,
report, user profile, checkpoint, vector record, or telemetry.

The guided retrieval budget is the same one-call budget as Mode A:

```yaml
current_book_results: 3
other_books: 3
chunks_per_other_book: 1
excerpt_max_chars: 500
retrieval_calls_per_turn: 1
automatic_connect_per_session: 1
soft_turn_target: 4
hard_turn_cap: 6
```

## Route Manual Mode A Entrypoints

Mode A does not require `agy_book_dialogue`; its three original entrypoints keep
their existing manual behavior unless the user explicitly enters Guided Mode B.

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
  `discussion_mode: personal_excerpt_discussion`,
  `personal_excerpt_available: true`, and
  `last_retrieval_mode: resolve_book`; briefly confirm the active book, then ask:
  `你现在最想讨论这本书里的哪个观点、困惑或判断？`
- `ambiguous`: show at most five returned candidates and ask the user to choose.
  Do not guess, rank one as the likely answer, or call another retrieval action.
- `not_found`: do not end the discussion. Set:

  ```yaml
  discussion_mode: general_discussion
  personal_excerpt_available: false
  active_book:
    title: <the title supplied by the user>
    book_id: null
    resolution_status: not_found
  last_retrieval_mode: resolve_book
  ```

  Say: `当前个人书摘索引中没有找到这本书的匹配记录，因此接下来的讨论暂时不会引用你以前保存的摘录。`
  Never turn that into a claim that the user has no notes, has not read the
  book, or cannot discuss it. Continue with themes, characters, style,
  Feynman explanation, the user's reactions, or close reading of supplied text.
  If the user already asked a concrete question, answer it directly. Otherwise
  ask at most one cut-in question.

  Offer source handoff no more than once per conversation by setting
  `source_prompt_offered: true`. This runtime can use pasted text or a supported
  text attachment, but it has no confirmed EPUB text extractor. Use this honest
  fallback: `如果希望紧贴原文，请上传系统支持读取的文件，或粘贴你想讨论的段落；默认只用于当前会话，不会自动加入长期书库。`
  Do not automatically search the web or broaden to fuzzy matching.

  Keep the default reply close to this short form, substituting only the title:

  ```text
  当前个人书摘索引中没有找到《书名》的匹配记录，所以接下来的讨论暂时不会引用你以前保存的摘录。

  这不影响我们继续聊。你可以直接说最想讨论的主题、人物或写法；如果希望紧贴原文，请上传系统支持读取的文件，或粘贴相关段落。默认只用于当前会话，不会自动加入长期书库。

  你现在最想从哪个故事、人物或主题开始？
  ```

  Do not replace the bounded status with any of these claims: `你没有笔记`,
  `你没读过这本书`, `书中没有你的笔记`, `无法讨论这本书`,
  `目前没有你的个人摘录`, or `没有你的已存笔记`. Do not infer facts from
  the title or immediately add a work overview, publication facts, or reviews.

- `unavailable` or `error`: do not reinterpret this as `not_found`. Preserve the
  actual resolution status and continue in `general_discussion` without saved
  excerpts. Briefly say the personal excerpt retrieval is temporarily
  unavailable, not that the index had no match. Include the same one-time source
  handoff and answer a concrete question directly; do not expose internal error
  codes or capability details.

Starting a discussion resolves identity only. Do not automatically retrieve a
large set of excerpts.

### 2. 费曼聊这本书

If `active_book` is absent, reply exactly enough to direct the next action:

```text
请先说“开始讨论《书名》”。
```

Do not call vector retrieval in that case.

When `discussion_mode` is `general_discussion`, store the user's concept or
claim as `current_question` and answer in a short Feynman loop from model
knowledge and the conversation. Explicitly avoid personal-excerpt retrieval and
external research. Do not ask the user to restart merely because `book_id` is
null.

When `discussion_mode` is `provided_text_discussion`, answer from the bounded
provided text and conversation. Do not call personal-excerpt retrieval.

Only when `discussion_mode` is `personal_excerpt_discussion`, store the user's
concept or claim as `current_question` and make exactly one default tool call:

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

For `personal_excerpt_discussion`, call the tool once:

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

For `general_discussion` or `provided_text_discussion`, the explicit cross-book
entrypoint may call the same `other_books` action once only when the concept is
clear, but omit both exclusion selectors because the active source has no
resolved personal-excerpt identity. Compare the returned saved excerpts with
the clearly attributed model knowledge or provided text; do not turn either
source into `[BOOK]`.

## Provided Text Handoff

Enter `provided_text_discussion` only after relevant text is actually present in
the conversation context. Set:

```yaml
discussion_mode: provided_text_discussion
provided_source_type: pasted_text | supported_attachment
temporary_session_source: true
personal_excerpt_available: false
```

Keep reads bounded to the current question and mark quotations or paraphrases
as `[PROVIDED_TEXT]`. Default to `permanent_import: false`; do not update the
Evernote index, create any new vector index, save a whole book, or create a
permanent Book Capsule.

A path string alone is not text. For `读取这个本地 EPUB：<path>`, do not use a
shell, expand permissions, traverse directories, or claim success from the
string. A file must pass the existing attachment/reference checks for existence,
allowed workspace, type, size/context budget, and sensitive paths, and actual
text extraction must succeed before saying it was read. Since this runtime has
no confirmed EPUB extractor, explain that ordinary discussion can continue and
ask for a supported text attachment or pasted passage. On any file failure,
state the bounded reason without unnecessarily echoing an internal absolute
path.

An uploaded file also does not establish success by itself. Enter provided-text
mode only when readable text is injected. If an attachment is binary or its
extractor is unavailable, do not claim it was read.

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
- General discussion does not imply that the user lacks notes or has not read the book.
- Provided text is temporary and is never labeled as saved personal history.
- The reply focuses on one concept and ends with no more than one main question.
