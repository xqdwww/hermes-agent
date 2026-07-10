"""
Payload diagnostics for LLM API calls.

Injected right before the final API call to surface:
- Per-message token estimates with content hashes
- Duplicate block detection (system prompt, skills, context files, etc.)
- Hard diagnostic guard when overhead is suspiciously large
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from agent.compression_safety import diagnose_payload_reduction

logger = logging.getLogger(__name__)

# ── Token estimation (rough: chars / 4, same as existing code) ─────────

def _estimate_tokens(text: str) -> int:
    """Rough token count — chars ÷ 4, clamped to ≥ 0."""
    return max(0, len(text or "") // 4)


def _message_to_text(msg: Dict[str, Any]) -> str:
    """Extract the text content of a message for hashing/estimation."""
    content = msg.get("content", "")
    if content is None:
        content = ""
    if isinstance(content, list):
        # Multi-part content (images, etc.) — join text parts
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        content = " ".join(parts)
    return str(content)


def _compute_hash(text: str) -> str:
    """SHA-256 hex digest (first 12 chars for readability)."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


# ── Duplicate block detection ─────────────────────────────────────────

# Marker strings for key blocks — the diagnostic scans system prompt + user
# messages for these patterns to identify what's been injected.
_BLOCK_MARKERS: Dict[str, str] = {
    "输出格式规范": "# 输出格式规范",
    "skills_prompt": "<available_skills>",
    "context_files/AGENTS.md": "AGENTS.md",
    "context_files/DEVELOPMENT.md": "DEVELOPMENT.md",
    "context_files/ARCHITECTURE.md": "ARCHITECTURE.md",
    "memory_block": "══════════════════════════\nMEMORY",
    "user_profile_block": "══════════════════════════\nUSER PROFILE",
    "project_context": "# Project Context",
    "tool_use_enforcement": "# Tool-use enforcement",
    "hermes_output_format": "<!--BLOCK:hermes-output-format-v1-->",
}


def _count_block_occurrences(text: str, marker: str) -> int:
    """Count how many times a marker appears in text."""
    if not marker:
        return 0
    return text.count(marker)


def detect_duplicate_blocks(api_messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Scan the full message payload for duplicate key blocks.

    Returns:
        Dict with duplicate_hashes, duplicate_count, duplicated_token_estimate,
        and a per-block breakdown.
    """
    # Join all message text for scanning
    all_text = ""
    msg_texts: List[str] = []
    for msg in api_messages:
        text = _message_to_text(msg)
        all_text += text + "\n"
        msg_texts.append(text)

    # Also extract the system prompt separately
    system_text = ""
    if api_messages and api_messages[0].get("role") == "system":
        system_text = _message_to_text(api_messages[0])

    # Check each block marker
    duplicates: Dict[str, Dict[str, Any]] = {}
    total_dup_tokens = 0
    duplicate_count = 0

    for block_name, marker in _BLOCK_MARKERS.items():
        if not marker:
            continue
        count = _count_block_occurrences(all_text, marker)
        if count > 1:
            # Estimate wasted tokens: (count - 1) * estimate per block
            # The block estimate is rough — we measure the text between markers
            block_estimate = _estimate_block_tokens(all_text, marker, count)
            wasted = block_estimate * (count - 1)
            duplicates[block_name] = {
                "occurrences": count,
                "marker": marker[:60],
                "estimated_block_tokens": block_estimate,
                "wasted_tokens": wasted,
            }
            total_dup_tokens += wasted
            duplicate_count += 1

    # Also compute content hashes of each message and find exact duplicates
    msg_hashes: Dict[str, List[int]] = {}
    for idx, text in enumerate(msg_texts):
        h = _compute_hash(text)
        msg_hashes.setdefault(h, []).append(idx)

    hash_duplicates = {h: idxs for h, idxs in msg_hashes.items() if len(idxs) > 1}

    return {
        "duplicate_hashes": hash_duplicates,
        "duplicate_count": duplicate_count,
        "duplicated_token_estimate": total_dup_tokens,
        "block_breakdown": duplicates,
    }


def _estimate_block_tokens(full_text: str, marker: str, count: int) -> int:
    """Estimate token count for a block by analyzing text around markers."""
    # Find the first occurrence and measure a generous chunk
    idx = full_text.find(marker)
    if idx == -1:
        return 0
    # Take 8000 chars after the marker as an estimate of the block size
    chunk = full_text[idx : idx + 8000]
    return _estimate_tokens(chunk)


# ── Payload breakdown ─────────────────────────────────────────────────

def payload_breakdown(
    api_messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    current_user_input: str = "",
) -> Dict[str, Any]:
    """Produce a detailed breakdown of the API payload.

    Args:
        api_messages: The full message list (system prompt + history)
        tools: Tool definitions passed to the API
        current_user_input: The user's current message (to detect bloat)
    """
    breakdown: Dict[str, Any] = {
        "message_count": len(api_messages),
        "messages": [],
        "system_prompt_token_estimate": 0,
        "tools_schema_token_estimate": 0,
        "conversation_history_token_estimate": 0,
        "context_files_prompt_token_estimate": 0,
        "skills_prompt_token_estimate": 0,
        "memory_profile_token_estimate": 0,
        "final_total_token_estimate": 0,
        "current_user_input_tokens": _estimate_tokens(current_user_input),
    }

    for idx, msg in enumerate(api_messages):
        role = msg.get("role", "?")
        content = _message_to_text(msg)
        sha = _compute_hash(content)
        token_est = _estimate_tokens(content)
        preview = content[:120].replace("\n", "\\n")

        msg_info = {
            "index": idx,
            "role": role,
            "token_estimate": token_est,
            "content_preview_120": preview,
            "content_hash": sha,
        }
        breakdown["messages"].append(msg_info)

        # Classify by position/role
        if role == "system":
            breakdown["system_prompt_token_estimate"] += token_est

            # Sub-breakdown of system prompt
            if "skills_prompt" not in breakdown:
                skills_marker = "<available_skills>"
                skills_idx = content.find(skills_marker)
                if skills_idx != -1:
                    breakdown["skills_prompt_token_estimate"] = _estimate_tokens(
                        content[skills_idx : skills_idx + 6000]
                    )

            if "context_files" not in breakdown:
                ctx_marker = "AGENTS.md"
                ctx_idx = content.find(ctx_marker)
                if ctx_idx == -1:
                    ctx_marker = "# Project Context"
                    ctx_idx = content.find(ctx_marker)
                if ctx_idx != -1:
                    breakdown["context_files_prompt_token_estimate"] = _estimate_tokens(
                        content[ctx_idx : ctx_idx + 8000]
                    )

            if "memory" not in breakdown:
                mem_marker = "══════════════════════════\nMEMORY"
                mem_idx = content.find(mem_marker)
                if mem_idx != -1:
                    mem_end = content.find("\n\n", mem_idx + 2000)
                    if mem_end == -1:
                        mem_end = min(mem_idx + 3000, len(content))
                    breakdown["memory_profile_token_estimate"] = _estimate_tokens(
                        content[mem_idx:mem_end]
                    )
                else:
                    prof_marker = "USER PROFILE"
                    prof_idx = content.find(prof_marker)
                    if prof_idx != -1:
                        prof_end = content.find("\n\n", prof_idx + 2000)
                        if prof_end == -1:
                            prof_end = min(prof_idx + 3000, len(content))
                        breakdown["memory_profile_token_estimate"] = max(
                            breakdown["memory_profile_token_estimate"],
                            _estimate_tokens(content[prof_idx:prof_end]),
                        )

        elif role in ("user", "assistant"):
            breakdown["conversation_history_token_estimate"] += token_est

    # Tools estimate
    if tools:
        tools_text = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
        breakdown["tools_schema_token_estimate"] = _estimate_tokens(tools_text)

    # Total
    breakdown["final_total_token_estimate"] = (
        breakdown["system_prompt_token_estimate"]
        + breakdown["tools_schema_token_estimate"]
        + breakdown["conversation_history_token_estimate"]
    )

    # Duplicate block detection
    dup_info = detect_duplicate_blocks(api_messages)
    breakdown["duplicate_blocks"] = dup_info

    breakdown["context_reducer_diagnostics"] = diagnose_payload_reduction(
        [_message_to_text(msg) for msg in api_messages],
        [_message_to_text(msg) for msg in api_messages],
    )

    return breakdown


# ── Hard diagnostic guard ─────────────────────────────────────────────

def hard_diagnostic_guard(
    breakdown: Dict[str, Any],
    api_messages: List[Dict[str, Any]],
) -> Optional[str]:
    """If overhead is suspicious, log a diagnostic warning.

    Returns None (never blocks) — the default is warn-only mode.
    The diagnostic is still logged for debugging.

    Conditions:
        - final_total_token_estimate > 40,000
        - current user input < 2,000 tokens
    """
    total = breakdown.get("final_total_token_estimate", 0)
    user_input_tokens = breakdown.get("current_user_input_tokens", 0)

    if total <= 40000 or user_input_tokens >= 2000:
        return None

    # Build a diagnostic dump
    lines = [
        "=" * 70,
        "⚠️  HARD DIAGNOSTIC GUARD TRIGGERED (WARN-ONLY, NOT BLOCKING)",
        f"    total={total:,} tokens > 40,000 threshold",
        f"    current user input: {user_input_tokens:,} tokens (< 2,000 threshold)",
        f"    messages: {breakdown['message_count']}",
        "=" * 70,
        "",
        "Top 10 largest messages/blocks:",
    ]

    sorted_msgs = sorted(breakdown["messages"], key=lambda m: m["token_estimate"], reverse=True)
    for m in sorted_msgs[:10]:
        lines.append(
            f"  [{m['index']:3d}] {m['role']:10s} ~{m['token_estimate']:>6,d} tokens  "
            f"hash={m['content_hash']}  "
            f"preview={m['content_preview_120'][:100]}"
        )

    lines.append("")
    lines.append("Sub-breakdown:")
    lines.append(f"  system_prompt:          {breakdown['system_prompt_token_estimate']:>8,d} tokens")
    lines.append(f"    skills_prompt:        {breakdown['skills_prompt_token_estimate']:>8,d} tokens")
    lines.append(f"    context_files:        {breakdown['context_files_prompt_token_estimate']:>8,d} tokens")
    lines.append(f"    memory/profile:       {breakdown['memory_profile_token_estimate']:>8,d} tokens")
    lines.append(f"  tools_schema:           {breakdown['tools_schema_token_estimate']:>8,d} tokens")
    lines.append(f"  conversation_history:   {breakdown['conversation_history_token_estimate']:>8,d} tokens")
    lines.append(f"  TOTAL:                  {breakdown['final_total_token_estimate']:>8,d} tokens")

    dup = breakdown.get("duplicate_blocks", {})
    if dup.get("duplicate_count", 0) > 0:
        lines.append("")
        lines.append(f"⚠️  DUPLICATE BLOCKS DETECTED ({dup['duplicate_count']}):")
        for name, info in dup.get("block_breakdown", {}).items():
            lines.append(
                f"  {name}: {info['occurrences']}x, "
                f"~{info['wasted_tokens']:,} tokens wasted"
            )

    lines.append("")
    lines.append("ACTION: WARN-ONLY — API call proceeding. Review diagnostics above.")
    lines.append("=" * 70)

    report = "\n".join(lines)
    logger.warning(report)
    return None  # Warn-only: never block


# ── Payload summary log (always logged, even when guard doesn't fire) ─

def log_payload_summary(breakdown: Dict[str, Any]) -> None:
    """Emit a concise payload summary as an INFO log line."""
    dup = breakdown.get("duplicate_blocks", {})
    lines = [
        f"Payload summary: msgs={breakdown['message_count']} "
        f"total=~{breakdown['final_total_token_estimate']:,}t "
        f"sys=~{breakdown['system_prompt_token_estimate']:,}t "
        f"tools=~{breakdown['tools_schema_token_estimate']:,}t "
        f"hist=~{breakdown['conversation_history_token_estimate']:,}t "
        f"skills=~{breakdown['skills_prompt_token_estimate']:,}t "
        f"ctx=~{breakdown['context_files_prompt_token_estimate']:,}t "
        f"mem=~{breakdown['memory_profile_token_estimate']:,}t "
        f"dups={dup.get('duplicate_count', 0)} "
        f"dup_tokens=~{dup.get('duplicated_token_estimate', 0):,}",
    ]

    # Top 5 largest messages
    sorted_msgs = sorted(breakdown["messages"], key=lambda m: m["token_estimate"], reverse=True)
    for m in sorted_msgs[:5]:
        lines.append(
            f"  top5 [{m['index']:3d}] {m['role']:10s} "
            f"~{m['token_estimate']:>6,d}t  {m['content_preview_120'][:80]}"
        )

    reducer = breakdown.get("context_reducer_diagnostics", {})
    if reducer:
        lines.append(
            "  reducer: "
            f"bypass={reducer.get('bypass_blocks', 0)} "
            f"prose={reducer.get('compressed_prose_blocks', 0)} "
            f"fallback={reducer.get('fallback_blocks', 0)} "
            f"safe_for_replacement={reducer.get('safe_for_replacement', False)}"
        )

    logger.info("\n".join(lines))
