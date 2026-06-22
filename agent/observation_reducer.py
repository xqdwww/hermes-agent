"""Observation reducer for tool-result context injection.

The reducer keeps full tool outputs outside the conversation and injects a
small Evidence Card instead.  It is deliberately conservative: if anything
goes wrong, callers get the original output back.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_OBS_BASE_DIR = Path("/tmp/hermes/observations")
_RUN_ID = os.getenv("HERMES_RUN_ID") or os.getenv("HERMES_CURRENT_RUN_ID") or (
    "run_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}"
)
_OBS_DIR = _OBS_BASE_DIR / _RUN_ID
_COUNTER_LOCK = threading.Lock()
_COUNTER = 0
_CONFIG_LOCK = threading.Lock()
_CONFIG_ENABLED: bool | None = None
_CODE_EXTENSIONS = {
    ".astro",
    ".bash",
    ".c",
    ".cc",
    ".cjs",
    ".cpp",
    ".cs",
    ".css",
    ".cts",
    ".cu",
    ".cuh",
    ".dart",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".jl",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".lua",
    ".m",
    ".mm",
    ".mjs",
    ".mts",
    ".php",
    ".pl",
    ".pm",
    ".py",
    ".pyi",
    ".r",
    ".rb",
    ".rs",
    ".scala",
    ".scss",
    ".sh",
    ".sql",
    ".svelte",
    ".swift",
    ".tsx",
    ".ts",
    ".vue",
    ".zsh",
}
_CODE_LINE_RE = re.compile(
    r"^\s*(?:"
    r"import\s+|export\s+|from\s+\S+\s+import\s+|def\s+\w+|class\s+\w+|"
    r"function\s+\w+|async\s+function\s+|const\s+\w+|let\s+\w+|var\s+\w+|"
    r"if\s*\(|for\s*\(|while\s*\(|try\s*\{|catch\s*\(|return\b|"
    r"interface\s+\w+|type\s+\w+\s*=|enum\s+\w+|package\s+\w+|"
    r"use\s+\w|namespace\s+\w|#include\b|using\s+namespace\b|"
    r"public:|private:|protected:|</?\w+|[}\])];\s*$"
    r")"
)
_HIGH_FIDELITY_TEXT_RE = re.compile(
    r"合同|协议|条款|论文|学术论文|政策|法律|法规|法条|判决书|起诉状|答辩状|校对|"
    r"proofread|proofreading|contract|agreement|legal|law|statute|regulation|"
    r"policy|paper|thesis|dissertation",
    re.IGNORECASE,
)


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
        return default
    return bool(value)


def _observation_reducer_enabled() -> bool:
    global _CONFIG_ENABLED
    if _CONFIG_ENABLED is not None:
        return _CONFIG_ENABLED
    with _CONFIG_LOCK:
        if _CONFIG_ENABLED is not None:
            return _CONFIG_ENABLED
        try:
            from hermes_cli.config import load_config

            cfg = load_config() or {}
            section = cfg.get("observation_reducer") if isinstance(cfg, dict) else None
            if isinstance(section, dict):
                enabled = _coerce_bool(section.get("enabled"), True)
            else:
                enabled = _coerce_bool(section, True)
        except Exception:
            enabled = True
        _CONFIG_ENABLED = enabled
        return enabled


def _reset_observation_reducer_config_cache() -> None:
    global _CONFIG_ENABLED
    with _CONFIG_LOCK:
        _CONFIG_ENABLED = None


def reduce_observation(
    tool_name: str,
    raw_output: str,
    exit_code: int | None = None,
    command: str | None = None,
) -> tuple[str, str | None]:
    """
    Returns: (evidence_card: str, raw_ref_path: str | None)

    Any reducer failure returns the original raw_output unchanged.
    """
    try:
        tool = str(tool_name or "").strip()
        raw = raw_output if isinstance(raw_output, str) else str(raw_output)
        if not raw:
            return raw, None
        if not _observation_reducer_enabled():
            return raw, None

        if tool == "terminal":
            return _reduce_terminal(tool, raw, exit_code=exit_code, command=command)
        if tool == "read_file":
            return _reduce_read_file(tool, raw)
        if tool == "skill_view":
            return _reduce_skill_view(tool, raw)
        if tool == "web_extract" or tool.startswith("browser"):
            return _reduce_web_or_browser(tool, raw)
        return raw, None
    except Exception:
        return raw_output if isinstance(raw_output, str) else str(raw_output), None


def _next_stem(tool_name: str) -> str:
    global _COUNTER
    safe_tool = re.sub(r"[^A-Za-z0-9_.-]+", "_", tool_name or "tool").strip("_") or "tool"
    with _COUNTER_LOCK:
        _COUNTER += 1
        return f"{_COUNTER:04d}_{safe_tool}"


def _write_text(path: Path, text: str) -> None:
    _OBS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="replace")


def _try_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return str(value)


def _lines(text: str) -> list[str]:
    return text.splitlines()


def _head_tail(lines: list[str], head: int, tail: int) -> tuple[list[str], bool]:
    if len(lines) <= head + tail:
        return lines, False
    return lines[:head] + [f"... truncated {len(lines) - head - tail} lines ..."] + lines[-tail:], True


def _first_nonempty_line(text: str, fallback: str = "") -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:240]
    return fallback


def _is_code_path(path: str | None) -> bool:
    if not path:
        return False
    return Path(path).suffix.lower() in _CODE_EXTENSIONS


def _looks_like_code(content: str) -> bool:
    lines = [line.rstrip() for line in content.splitlines() if line.strip()]
    if len(lines) < 4:
        return False
    code_lines = sum(1 for line in lines if _CODE_LINE_RE.search(line))
    indented_lines = sum(1 for line in lines if re.match(r"^\s{2,}\S", line))
    brace_or_semicolon_lines = sum(1 for line in lines if re.search(r"[{};]\s*$", line))
    code_signals = code_lines + min(indented_lines, 6) + min(brace_or_semicolon_lines, 6)
    return code_lines >= 3 and code_signals / len(lines) >= 0.35


def _is_high_fidelity_text(path: str | None, content: str) -> bool:
    haystack = f"{path or ''}\n{content[:4000]}"
    return bool(_HIGH_FIDELITY_TEXT_RE.search(haystack))


def _terminal_summary(output: str, stderr: str, exit_code: int | None) -> str:
    error_lines = [
        line.strip()
        for line in (stderr or output).splitlines()
        if re.search(r"\b(error|failed|failure|traceback|exception|warn|warning)\b", line, re.IGNORECASE)
    ]
    if error_lines:
        return "; ".join(error_lines[:3])[:500]
    if exit_code not in (None, 0):
        return f"command exited with code {exit_code}"
    return _first_nonempty_line(output, "command completed")[:500]


def _reduce_terminal(
    tool_name: str,
    raw: str,
    *,
    exit_code: int | None,
    command: str | None,
) -> tuple[str, str | None]:
    parsed = _try_json(raw)
    stdout = raw
    stderr = ""
    if isinstance(parsed, dict):
        stdout = _stringify(parsed.get("stdout") or parsed.get("output") or parsed.get("result") or "")
        stderr = _stringify(parsed.get("stderr") or parsed.get("error") or "")
        if exit_code is None and isinstance(parsed.get("exit_code"), int):
            exit_code = parsed.get("exit_code")
        if command is None and isinstance(parsed.get("command"), str):
            command = parsed.get("command")

    stem = _next_stem(tool_name)
    stdout_path = _OBS_DIR / f"{stem}.stdout.log"
    stderr_path = _OBS_DIR / f"{stem}.stderr.log"
    raw_path = _OBS_DIR / f"{stem}.raw.json"
    _write_text(stdout_path, stdout)
    _write_text(stderr_path, stderr)
    if isinstance(parsed, dict):
        _write_text(raw_path, raw)

    stderr_preview = "\n".join(_lines(stderr)[:10]).strip()
    stdout_tail = "\n".join(_lines(stdout)[-20:]).strip()
    summary = _terminal_summary(stdout, stderr, exit_code)
    body_parts = []
    if stderr_preview:
        body_parts.append("stderr_head:\n" + stderr_preview)
    if stdout_tail:
        body_parts.append("stdout_tail:\n" + stdout_tail)
    body = "\n".join(body_parts).strip()
    header = f"[OBSERVATION:terminal] exit={exit_code if exit_code is not None else 'unknown'}"
    if command:
        header += f" | cmd: {command}"
    card = f"{header}\nsummary: {summary}\nfull: {_OBS_DIR}"
    if body:
        card += f"\n\n{body}"
    return card, str(_OBS_DIR)


def _read_file_payload(raw: str) -> tuple[str | None, str, int | None, int | None, int | None]:
    parsed = _try_json(raw)
    if not isinstance(parsed, dict):
        return None, raw, None, None, None
    content = _stringify(parsed.get("content") or parsed.get("message") or parsed)
    path = parsed.get("path")
    offset = parsed.get("offset")
    total_lines = parsed.get("total_lines")
    if not isinstance(offset, int):
        offset = None
    if not isinstance(total_lines, int):
        total_lines = None
    return str(path) if path else None, content, offset, total_lines, len(content.splitlines())


def _reduce_read_file(tool_name: str, raw: str) -> tuple[str, str | None]:
    path, content, offset, total_lines, observed_lines = _read_file_payload(raw)
    lines = _lines(content)
    if len(lines) <= 200:
        return raw, None
    if _is_high_fidelity_text(path, content):
        return raw, None
    if _is_code_path(path) or _looks_like_code(content):
        return raw, None

    stem = _next_stem(tool_name)
    raw_path = _OBS_DIR / f"{stem}.txt"
    _write_text(raw_path, raw)
    kept, _ = _head_tail(lines, 30, 30)
    start_line = offset or 1
    end_line = start_line + len(lines) - 1
    total = total_lines or observed_lines or len(lines)
    summary = _first_nonempty_line("\n".join(lines), "file content reduced")
    card = (
        f"[OBSERVATION:read_file] path: {path or 'unknown'} | "
        f"lines: {start_line}-{end_line}/{total} | truncated: true\n"
        f"summary: {summary}\n"
        f"full: {_OBS_DIR}\n\n"
        + "\n".join(kept)
    )
    return card, str(_OBS_DIR)


_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _extract_sections(content: str) -> list[tuple[str, int, int]]:
    matches = list(_SECTION_RE.finditer(content))
    sections: list[tuple[str, int, int]] = []
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        sections.append((title, match.start(), end))
    return sections


def _reduce_skill_view(tool_name: str, raw: str) -> tuple[str, str | None]:
    parsed = _try_json(raw)
    if not isinstance(parsed, dict):
        return raw, None
    content = _stringify(parsed.get("content") or "")
    if not content:
        return raw, None
    sections = _extract_sections(content)
    if not sections:
        return raw, None

    stem = _next_stem(tool_name)
    raw_path = _OBS_DIR / f"{stem}.json"
    _write_text(raw_path, raw)

    selected_title, selected_start, selected_end = sections[0]
    for title, start, end in sections:
        if title.strip().upper() == "COMMANDS":
            selected_title, selected_start, selected_end = title, start, end
            break

    section_names = ", ".join(title for title, _, _ in sections)
    selected = content[selected_start:selected_end].strip()
    skill_name = parsed.get("name") or "unknown"
    summary = f"sections: {section_names}"[:500]
    card = (
        f"[OBSERVATION:skill_view] skill: {skill_name} | section: {selected_title}\n"
        f"summary: {summary}\n"
        f"full: {_OBS_DIR}\n\n"
        f"{selected}"
    )
    return card, str(_OBS_DIR)


def _extract_web_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        for key in ("results", "data", "items"):
            child = value.get(key)
            if isinstance(child, list):
                return [item for item in child if isinstance(item, dict)]
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _reduce_web_or_browser(tool_name: str, raw: str) -> tuple[str, str | None]:
    parsed = _try_json(raw)
    stem = _next_stem(tool_name)
    raw_path = _OBS_DIR / f"{stem}.json" if parsed is not None else _OBS_DIR / f"{stem}.txt"
    _write_text(raw_path, raw)

    title = ""
    url = ""
    content = raw
    items = _extract_web_items(parsed)
    if items:
        first = items[0]
        title = _stringify(first.get("title") or first.get("window_title") or first.get("name") or "").strip()
        url = _stringify(first.get("url") or first.get("href") or first.get("source_url") or "").strip()
        content = _stringify(first.get("content") or first.get("text") or first.get("markdown") or first)
    elif isinstance(parsed, dict):
        title = _stringify(parsed.get("title") or parsed.get("window_title") or "").strip()
        url = _stringify(parsed.get("url") or "").strip()
        content = _stringify(parsed.get("content") or parsed.get("text") or parsed)

    preview = content[:500]
    header = f"[OBSERVATION:{tool_name}]"
    meta = []
    if title:
        meta.append(f"title: {title[:200]}")
    if url:
        meta.append(f"url: {url[:300]}")
    if meta:
        header += " " + " | ".join(meta)
    card = f"{header}\nsummary: {preview}\nfull: {_OBS_DIR}"
    return card, str(_OBS_DIR)


__all__ = ["reduce_observation"]
