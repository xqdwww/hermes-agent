"""Deterministic dispatch policy for book-deepening Guided Mode B."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import re
from typing import Any, Iterable


logger = logging.getLogger(__name__)

AGY_TOOL_NAME = "agy_book_dialogue"
BOOK_NOTES_TOOL_NAME = "book_notes_retrieval"
GUIDED_ACTIVE_MARKER = "<!-- guided_mode_b: active;"
FALLBACK_NOTICE = "这一轮 Gemini 对谈引擎暂时不可用，我先用当前模型继续。"
DISPATCH_BLOCKED_NOTICE = (
    "这一轮 AGY 文学对谈没有成功启动。为避免当前模型越过调度直接回答，"
    "本轮已停止，请稍后重试。"
)

_GUIDED_ENTRY_RE = re.compile(
    r"(?:进入引导式读书模式|用引导模式聊|开始连续聊)"
)
_GUIDED_EXIT_RE = re.compile(
    r"^\s*(?:退出引导式读书模式|结束这轮读书讨论|先聊到这里)[。！!？?\s]*$"
)
_ACTIVE_BOOK_RE = re.compile(
    r"已经进入[^《\n]{0,200}《(?P<title>[^》]{1,300})》"
    r"(?:[（(](?P<author>[^）)]{1,200})[）)])?"
)
_CONNECT_RE = re.compile(
    r"(?:连接|联系|比较|对照|相似|冲突|补充).{0,18}(?:其他书|以前读过|另一本|别的书)"
    r"|(?:其他书|以前读过|另一本|别的书).{0,18}(?:连接|联系|比较|对照|相似|冲突|补充)"
)
_META_PATTERNS = (
    re.compile(r"(?:现在|刚才|这一轮).{0,12}(?:用|是).{0,8}(?:哪个|什么).{0,4}模型"),
    re.compile(r"(?:哪个|什么)模型.{0,10}(?:讨论|回答|聊天)"),
    re.compile(r"(?:刚才|这一轮).{0,12}(?:调用|使用|用了).{0,8}工具"),
    re.compile(r"(?:为什么|为何).{0,12}(?:没有|找不到|不可用).{0,6}书摘"),
    re.compile(r"(?:现在|当前).{0,8}(?:是什么|哪种).{0,4}模式"),
    re.compile(r"AGY.{0,10}(?:调用|使用|运行)|(?:调用|使用|运行).{0,10}AGY", re.I),
    re.compile(r"(?:怎么|如何|怎样).{0,6}退出"),
)
_UNRELATED_PATTERNS = (
    re.compile(r"^\s*(?:帮我|请|你能否?|麻烦).{0,12}(?:写代码|改代码|查天气|订票|发邮件|建日程|打开网页)"),
    re.compile(r"^\s*(?:今天|明天|后天).{0,8}天气"),
    re.compile(r"^\s*(?:运行|执行).{0,8}(?:命令|脚本|测试)"),
)
_META_FOLLOWUP_RE = re.compile(
    r"(?:要|想|需要|可以|是否|还要|接下来).{0,40}"
    r"(?:继续|深入|接着|回到|聊|讨论)"
    r"|(?:继续|接着|回到).{0,40}(?:吗|吧|[？?])"
)


@dataclass(frozen=True)
class GuidedDispatchDecision:
    guided_mode_active: bool
    guided_stage: str | None
    turn_kind: str
    dispatch_policy: str
    agy_required: bool
    agy_attempted: bool
    agy_tool_available: bool
    forced_tool_name: str | None
    turn_key: str

    def evidence(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "agy_succeeded": False,
                "agy_failure_class": None,
                "fallback_used": False,
                "final_answer_engine": None,
            }
        )
        return data


@dataclass(frozen=True)
class AgyDelivery:
    succeeded: bool
    status: str
    response: str | None
    failure_class: str | None


@dataclass(frozen=True)
class GuidedPredispatchPlan:
    decision: GuidedDispatchDecision
    book_title: str
    author: str | None
    retrieval_status: str
    current_message: str
    focus_question: str
    effective_turns: int
    retrieval_args: dict[str, Any] | None


def _log_evidence(evidence: dict[str, Any]) -> None:
    logger.info(
        "guided_book_dispatch guided_mode_active=%s guided_stage=%s "
        "turn_kind=%s dispatch_policy=%s agy_required=%s agy_attempted=%s "
        "agy_succeeded=%s agy_failure_class=%s fallback_used=%s "
        "final_answer_engine=%s",
        evidence.get("guided_mode_active"),
        evidence.get("guided_stage"),
        evidence.get("turn_kind"),
        evidence.get("dispatch_policy"),
        evidence.get("agy_required"),
        evidence.get("agy_attempted"),
        evidence.get("agy_succeeded"),
        evidence.get("agy_failure_class"),
        evidence.get("fallback_used"),
        evidence.get("final_answer_engine"),
    )


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _tool_names(tools: Iterable[dict[str, Any]] | None) -> set[str]:
    names: set[str] = set()
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.add(function["name"])
        elif isinstance(tool.get("name"), str):
            names.add(tool["name"])
    return names


def _tool_call_name(tool_call: Any) -> str:
    if isinstance(tool_call, dict):
        function = tool_call.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or "")
        return str(tool_call.get("name") or "")
    function = getattr(tool_call, "function", None)
    return str(getattr(function, "name", None) or getattr(tool_call, "name", "") or "")


def _agy_attempted_after(messages: list[dict[str, Any]], user_index: int) -> bool:
    for message in messages[user_index + 1 :]:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        if any(
            _tool_call_name(tool_call) == AGY_TOOL_NAME
            for tool_call in message.get("tool_calls") or []
        ):
            return True
    return False


def _is_meta_question(text: str) -> bool:
    return any(pattern.search(text) for pattern in _META_PATTERNS)


def _is_unrelated(text: str) -> bool:
    return any(pattern.search(text) for pattern in _UNRELATED_PATTERNS)


def sanitize_guided_meta_response(content: str) -> str:
    """Remove a model-added discussion prompt from a guided meta answer."""
    text = str(content or "").strip()
    if not text:
        return text
    paragraphs = re.split(r"\n\s*\n", text)
    while (
        len(paragraphs) > 1
        and ("?" in paragraphs[-1] or "？" in paragraphs[-1])
        and _META_FOLLOWUP_RE.search(paragraphs[-1])
    ):
        paragraphs.pop()
    return "\n\n".join(paragraphs).strip()


def guided_meta_runtime_note(
    messages: list[dict[str, Any]],
) -> str:
    """Describe the most recent AGY delivery without exposing its payload."""
    user_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], dict)
            and messages[index].get("role") == "user"
        ),
        -1,
    )
    if user_index < 0:
        return ""
    agy_index = -1
    for index in range(user_index - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        if any(
            _tool_call_name(tool_call) == AGY_TOOL_NAME
            for tool_call in message.get("tool_calls") or []
        ):
            agy_index = index
            break
    if agy_index < 0:
        return ""
    final_text = ""
    for message in messages[agy_index + 1 : user_index]:
        if isinstance(message, dict) and message.get("role") == "assistant":
            candidate = _message_text(message).strip()
            if candidate:
                final_text = candidate
    if final_text.startswith(FALLBACK_NOTICE):
        status = "failed and the controller model supplied the explicit fallback"
    elif final_text:
        status = "succeeded and its Gemini response was delivered as the literary answer"
    else:
        status = "was attempted, but no completed literary answer is visible"
    return (
        "The most recent agy_book_dialogue call "
        f"{status}. Book-notes retrieval availability is a separate status "
        "and must not be used to infer whether AGY succeeded."
    )


def _looks_like_question(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith(("?", "？")):
        return True
    return bool(re.match(r"^(?:为什么|为何|怎么|如何|是否|是不是|能否|什么|哪)", stripped))


def _active_book_context(
    messages: list[dict[str, Any]],
    user_index: int,
) -> tuple[str, str | None, str, str, int] | None:
    marker_index = -1
    marker_text = ""
    for index in range(user_index - 1, -1, -1):
        message = messages[index]
        if (
            isinstance(message, dict)
            and message.get("role") == "assistant"
            and GUIDED_ACTIVE_MARKER in _message_text(message)
        ):
            marker_index = index
            marker_text = _message_text(message)
            break
    if marker_index < 0:
        return None

    match = _ACTIVE_BOOK_RE.search(marker_text)
    if not match:
        return None
    title = match.group("title").strip()
    author = (match.group("author") or "").strip() or None
    if author is None:
        for message in reversed(messages[:marker_index]):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            entry_text = _message_text(message)
            if not _GUIDED_ENTRY_RE.search(entry_text):
                continue
            cleaned = _GUIDED_ENTRY_RE.sub("", entry_text, count=1).strip()
            explicit_author = re.search(r"^([^《》\n]{1,200}?)\s*的《", cleaned)
            if explicit_author:
                author = explicit_author.group(1).strip() or None
            break

    if (
        any(token in marker_text for token in ("暂时不可用", "暂时无法访问"))
        or "unavailable" in marker_text.lower()
    ):
        retrieval_status = "unavailable"
    elif any(token in marker_text for token in ("未匹配", "没有匹配", "未找到")):
        retrieval_status = "not_found"
    else:
        retrieval_status = "resolved"

    focus_question = "你现在最想检验的观点、困惑或判断是什么？"
    effective_turns = 0
    for message in messages[marker_index + 1 : user_index + 1]:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = _message_text(message)
        if _is_meta_question(text) or _is_unrelated(text):
            continue
        effective_turns += 1
    return (
        title,
        author,
        retrieval_status,
        focus_question,
        min(effective_turns, 6),
    )


def _relationship_intent(text: str) -> str:
    if any(token in text for token in ("冲突", "矛盾", "张力", "反驳")):
        return "tension"
    if any(token in text for token in ("补充", "完善", "延伸")):
        return "completion"
    return "echo"


def build_guided_predispatch_plan(
    messages: list[dict[str, Any]],
    tools: Iterable[dict[str, Any]] | None,
) -> GuidedPredispatchPlan | None:
    decision = resolve_guided_book_dispatch(messages, tools)
    if not decision.agy_required or decision.agy_attempted:
        return None

    user_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], dict)
            and messages[index].get("role") == "user"
        ),
        -1,
    )
    if user_index < 0:
        return None
    context = _active_book_context(messages, user_index)
    if context is None:
        return None
    title, author, retrieval_status, focus_question, effective_turns = context
    current_message = _message_text(messages[user_index]).strip()[:1_500]

    retrieval_args: dict[str, Any] | None = None
    if retrieval_status == "resolved" and decision.guided_stage == "probe":
        retrieval_args = {
            "action": "current_book",
            "book_title": title,
            "author": author,
            "query": current_message[:1_000],
            "top_k": 3,
            "max_per_parent": 1,
            "excerpt_max_chars": 500,
            "include_text": True,
        }
    elif retrieval_status == "resolved" and decision.guided_stage == "connect":
        retrieval_args = {
            "action": "other_books",
            "exclude_book_title": title,
            "exclude_author": author,
            "query": current_message[:1_000],
            "top_k_books": 3,
            "max_chunks_per_book": 1,
            "max_chunks_per_parent": 1,
            "relationship_intent": _relationship_intent(current_message),
            "excerpt_max_chars": 500,
            "include_text": True,
        }
    return GuidedPredispatchPlan(
        decision=decision,
        book_title=title,
        author=author,
        retrieval_status=retrieval_status,
        current_message=current_message,
        focus_question=focus_question,
        effective_turns=effective_turns,
        retrieval_args=retrieval_args,
    )


def _retrieval_evidence(
    plan: GuidedPredispatchPlan,
    raw_result: str | None,
) -> tuple[str, list[dict[str, str]], list[dict[str, Any]]]:
    if raw_result is None:
        return plan.retrieval_status, [], []
    try:
        payload = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return "unavailable", [], []
    if not isinstance(payload, dict):
        return "unavailable", [], []
    status = str(payload.get("status") or "")
    if status == "unavailable":
        return "unavailable", [], []
    if status in {"not_found", "ambiguous"}:
        return "not_found", [], []
    if status not in {"ok", "no_results"}:
        return "unavailable", [], []

    results = payload.get("results")
    rows = results if isinstance(results, list) else []
    if plan.decision.guided_stage == "probe":
        excerpts = [
            {"excerpt": str(row.get("excerpt") or "")[:500]}
            for row in rows[:3]
            if isinstance(row, dict) and row.get("excerpt")
        ]
        return plan.retrieval_status, excerpts, []

    other_books: list[dict[str, Any]] = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        chunks = row.get("chunks")
        chunk = chunks[0] if isinstance(chunks, list) and chunks else {}
        if not isinstance(chunk, dict) or not chunk.get("excerpt"):
            continue
        other_books.append(
            {
                "book_title": str(row.get("book_title_normalized") or "")[:300],
                "author": row.get("author_normalized"),
                "excerpt": str(chunk.get("excerpt") or "")[:500],
            }
        )
    return plan.retrieval_status, [], other_books


def build_agy_predispatch_args(
    plan: GuidedPredispatchPlan,
    retrieval_result: str | None,
) -> dict[str, Any]:
    retrieval_status, current_excerpts, other_excerpts = _retrieval_evidence(
        plan, retrieval_result
    )
    available_by_status = {
        "resolved": (True, True, "personal_excerpt_discussion"),
        "not_found": (False, True, "general_discussion"),
        "unavailable": (None, False, "general_discussion"),
    }
    personal_available, operational, discussion_mode = available_by_status[
        retrieval_status
    ]
    next_action = {
        "probe": "deepen",
        "connect": "close",
        "close": None,
    }.get(plan.decision.guided_stage)
    return {
        "action": "respond",
        "book": {
            "title": plan.book_title,
            "author": plan.author,
            "resolution_status": retrieval_status,
            "retrieval_status": retrieval_status,
            "personal_excerpt_available": personal_available,
            "retrieval_operational": operational,
            "discussion_mode": discussion_mode,
        },
        "guided_mode": {
            "stage": plan.decision.guided_stage,
            "focus_question": plan.focus_question,
            "effective_turns": plan.effective_turns,
            "next_action": next_action,
        },
        "user": {
            "current_message": plan.current_message,
            "current_explanation": plan.current_message,
        },
        "evidence": {
            "current_book_excerpts": current_excerpts,
            "other_book_excerpts": other_excerpts,
            "provided_text": None,
        },
        "limits": {
            "max_current_book_excerpts": 3,
            "max_other_books": 3,
            "max_excerpt_chars_each": 500,
            "max_context_chars": 10_000,
        },
    }


def resolve_guided_book_dispatch(
    messages: list[dict[str, Any]],
    tools: Iterable[dict[str, Any]] | None,
) -> GuidedDispatchDecision:
    user_indexes = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, dict) and message.get("role") == "user"
    ]
    if not user_indexes:
        return GuidedDispatchDecision(
            False, None, "unrelated_topic", "not_guided", False, False,
            AGY_TOOL_NAME in _tool_names(tools), None, "",
        )

    user_index = user_indexes[-1]
    current_text = _message_text(messages[user_index])
    turn_key = hashlib.sha256(
        f"{user_index}\0{current_text}".encode("utf-8")
    ).hexdigest()[:16]
    available = AGY_TOOL_NAME in _tool_names(tools)

    if _GUIDED_ENTRY_RE.search(current_text):
        return GuidedDispatchDecision(
            True, "orient", "mode_control", "orient_bypass", False, False,
            available, None, turn_key,
        )

    marker_indexes = [
        index
        for index, message in enumerate(messages[:user_index])
        if isinstance(message, dict)
        and message.get("role") == "assistant"
        and GUIDED_ACTIVE_MARKER in _message_text(message)
    ]
    if not marker_indexes:
        return GuidedDispatchDecision(
            False, None, "unrelated_topic", "not_guided", False, False,
            available, None, turn_key,
        )

    marker_index = marker_indexes[-1]
    prior_exit = any(
        isinstance(message, dict)
        and message.get("role") == "user"
        and _GUIDED_EXIT_RE.match(_message_text(message))
        for message in messages[marker_index + 1 : user_index]
    )
    if prior_exit:
        return GuidedDispatchDecision(
            False, None, "unrelated_topic", "guided_already_closed", False,
            False, available, None, turn_key,
        )

    if _is_meta_question(current_text):
        return GuidedDispatchDecision(
            True, None, "meta_question", "meta_bypass", False, False,
            available, None, turn_key,
        )
    if _is_unrelated(current_text):
        return GuidedDispatchDecision(
            True, None, "unrelated_topic", "unrelated_bypass", False, False,
            available, None, turn_key,
        )

    if _GUIDED_EXIT_RE.match(current_text):
        stage = "close"
        turn_kind = "literary_discussion"
    elif _CONNECT_RE.search(current_text):
        stage = "connect"
        turn_kind = "literary_discussion"
    else:
        user_turns_after_marker = sum(
            1
            for message in messages[marker_index + 1 : user_index]
            if isinstance(message, dict) and message.get("role") == "user"
        )
        if user_turns_after_marker == 0 and _looks_like_question(current_text):
            return GuidedDispatchDecision(
                True, "explain", "literary_discussion", "explain_bypass",
                False, False, available, None, turn_key,
            )
        stage = "probe"
        turn_kind = "literary_discussion"

    attempted = _agy_attempted_after(messages, user_index)
    if attempted:
        policy = "agy_already_attempted"
        forced_tool_name = None
    elif available:
        policy = "guided_pre_dispatch"
        forced_tool_name = None
    else:
        policy = "blocked_tool_unavailable"
        forced_tool_name = None
    return GuidedDispatchDecision(
        True, stage, turn_kind, policy, True, attempted, available,
        forced_tool_name, turn_key,
    )


def record_predispatch_start(
    agent: Any,
    decision: GuidedDispatchDecision,
) -> None:
    previous = getattr(agent, "_guided_book_dispatch_evidence", None)
    if not isinstance(previous, dict) or previous.get("turn_key") != decision.turn_key:
        evidence = decision.evidence()
    else:
        evidence = {**previous, **asdict(decision)}
    agent._guided_book_dispatch_evidence = evidence
    _log_evidence(evidence)


def cap_guided_tool_calls(
    decision: GuidedDispatchDecision,
    tool_calls: list[Any] | None,
) -> list[Any] | None:
    if not tool_calls or not decision.guided_mode_active:
        return tool_calls
    if not decision.agy_required:
        return tool_calls
    if not decision.agy_attempted:
        for tool_call in tool_calls:
            if _tool_call_name(tool_call) == AGY_TOOL_NAME:
                return [tool_call]
        return []

    kept: list[Any] = []
    retrieval_kept = False
    for tool_call in tool_calls:
        name = _tool_call_name(tool_call)
        if name == AGY_TOOL_NAME:
            continue
        if name == BOOK_NOTES_TOOL_NAME:
            if retrieval_kept:
                continue
            retrieval_kept = True
        kept.append(tool_call)
    return kept


def read_agy_delivery(
    messages: list[dict[str, Any]],
    tool_call_ids: set[str],
) -> AgyDelivery:
    raw: Any = None
    for message in reversed(messages):
        if (
            isinstance(message, dict)
            and message.get("role") == "tool"
            and message.get("tool_call_id") in tool_call_ids
        ):
            raw = message.get("content")
            break
    if not isinstance(raw, str):
        return AgyDelivery(False, "invalid_result", None, "invalid_result")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return AgyDelivery(False, "invalid_result", None, "invalid_result")
    if not isinstance(payload, dict):
        return AgyDelivery(False, "invalid_result", None, "invalid_result")
    status = str(payload.get("status") or "invalid_result")
    response = payload.get("response")
    if (
        status == "ok"
        and payload.get("delivery_mode") == "verbatim"
        and isinstance(response, str)
        and response.strip()
    ):
        return AgyDelivery(True, status, response.strip(), None)
    return AgyDelivery(False, status, None, status)


def record_agy_delivery(agent: Any, delivery: AgyDelivery) -> None:
    evidence = getattr(agent, "_guided_book_dispatch_evidence", None)
    if not isinstance(evidence, dict):
        evidence = {}
    evidence.update(
        {
            "agy_attempted": True,
            "agy_succeeded": delivery.succeeded,
            "agy_failure_class": delivery.failure_class,
            "fallback_used": False,
            "final_answer_engine": "agy_gemini" if delivery.succeeded else None,
        }
    )
    agent._guided_book_dispatch_evidence = evidence
    _log_evidence(evidence)


def should_block_direct_answer(agent: Any) -> bool:
    evidence = getattr(agent, "_guided_book_dispatch_evidence", None)
    return bool(
        isinstance(evidence, dict)
        and evidence.get("agy_required")
        and not evidence.get("agy_attempted")
    )


def apply_agy_failure_fallback(agent: Any, content: str) -> str:
    evidence = getattr(agent, "_guided_book_dispatch_evidence", None)
    if not (
        isinstance(evidence, dict)
        and evidence.get("agy_required")
        and evidence.get("agy_attempted")
        and not evidence.get("agy_succeeded")
    ):
        if (
            isinstance(evidence, dict)
            and evidence.get("guided_mode_active")
            and evidence.get("final_answer_engine") is None
        ):
            evidence["final_answer_engine"] = "deepseek"
            _log_evidence(evidence)
        return content
    evidence["fallback_used"] = True
    evidence["final_answer_engine"] = "deepseek_fallback"
    _log_evidence(evidence)
    if content.strip().startswith(FALLBACK_NOTICE):
        return content
    return f"{FALLBACK_NOTICE}\n\n{content}".strip()


def record_dispatch_block(agent: Any) -> None:
    evidence = getattr(agent, "_guided_book_dispatch_evidence", None)
    if not isinstance(evidence, dict):
        evidence = {}
    evidence.update(
        {
            "agy_attempted": False,
            "agy_succeeded": False,
            "agy_failure_class": "dispatch_not_honored",
            "fallback_used": False,
            "final_answer_engine": "dispatch_blocked",
        }
    )
    agent._guided_book_dispatch_evidence = evidence
    _log_evidence(evidence)
