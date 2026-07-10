#!/usr/bin/env python3
"""
video_report_passthrough — deterministic video-summary report delivery.

When a cached summarizer report exists at
  ~/OS_Core/output/video_summary_*.md
this tool reads and returns the complete file content as its result.

The conversation loop detects this tool's result and uses it as the
*final_response* directly, bypassing the secondary summarization the
model (DeepSeek, etc.) would otherwise apply.  This guarantees the
deterministic report is delivered verbatim.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from tools.registry import registry

logger = logging.getLogger(__name__)

# ── Path constraints ─────────────────────────────────────────────────────────
# Only actual video-summary report files are allowed.
_REPORT_DIR = Path.home() / "OS_Core" / "output"
_REPORT_PREFIX = "video_summary_"
_REPORT_SUFFIX = ".md"
# Canonical form used in error messages.
_CANONICAL_GLOB = "~/OS_Core/output/video_summary_*.md"


# ── Schema ───────────────────────────────────────────────────────────────────
VIDEO_REPORT_PASSTHROUGH_SCHEMA = {
    "name": "video_report_passthrough",
    "description": (
        "Read a cached video-summary report and return its complete content "
        "verbatim.  The report is then used as the agent's final response "
        "directly — the agent will NOT reformat or re-summarise it.\n\n"
        "Use this tool ONLY after you have already run the summariser "
        "pipeline and confirmed a video_summary_*.md file exists, OR when "
        "you find a matching report at ~/OS_Core/output/video_summary_*.md\n\n"
        "The path parameter is optional — when omitted the tool searches "
        "the report directory and reads the most recent matching file.  "
        "When provided explicitly, only paths under "
        "~/OS_Core/output/video_summary_*.md are accepted.\n\n"
        "Call this tool INSTEAD of read_file when you already know the "
        "report exists.  Calling read_file on a video_summary report will "
        "still trigger the normal agent summarisation path."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Optional absolute path to the report file.  When "
                    "omitted the tool auto-discovers the most recent "
                    "report.  Only paths matching "
                    "~/OS_Core/output/video_summary_*.md are accepted."
                ),
            },
        },
        "required": [],
    },
}


# ── Validation helpers ───────────────────────────────────────────────────────

def _expand_path(path: str) -> str:
    """Expand ``~`` to the user's home directory."""
    return os.path.expanduser(path)


def _is_allowed(video_report_path: str) -> bool:
    """Return True when *video_report_path* is directly under the allowed directory."""
    resolved = Path(_expand_path(video_report_path)).resolve()
    allowed = _REPORT_DIR.resolve()
    return (
        resolved.parent == allowed
        and resolved.name.startswith(_REPORT_PREFIX)
        and resolved.suffix == _REPORT_SUFFIX
    )


def _find_latest_report() -> Path | None:
    """Return the most recent matching report file, or None."""
    candidates = sorted(_REPORT_DIR.glob(f"{_REPORT_PREFIX}*{_REPORT_SUFFIX}"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _list_reports() -> list[str]:
    """Return a sorted list of matching report filenames."""
    return sorted(
        str(p.relative_to(_REPORT_DIR))
        for p in _REPORT_DIR.glob(f"{_REPORT_PREFIX}*{_REPORT_SUFFIX}")
    )


# ── Tool handler ─────────────────────────────────────────────────────────────

def video_report_passthrough(
    args: dict,
    **kwargs,
) -> str:
    """Read a video-summary report and return its full content.

    The registry dispatches tools as ``entry.handler(args_dict, **extra_kwargs)``
    where *args* is the JSON-decoded function-arguments dict containing the
    named parameter ``"path"``.  We unpack it here.

    Args:
        args: Tool-call arguments dict.  May contain ``"path"`` (optional
              explicit file path).  When omitted, discovers the most recent
              report.

    Returns:
        Full report content as a string, or a JSON error dict.
    """
    path: str | None = None
    if isinstance(args, dict):
        path = args.get("path")
    report_path: Path | None = None

    if path:
        # Explicit path — validate before reading.
        expanded = _expand_path(path)
        if not _is_allowed(expanded):
            available = _list_reports()
            hint = ""
            if available:
                hint = (
                    f" Available reports:\n" + "\n".join(f"  ️ {a}" for a in available)
                )
            return json.dumps({
                "error": (
                    f"Path '{path}' is not a valid video-summary report location. "
                    f"Only files matching {_CANONICAL_GLOB} are allowed.{hint}"
                ),
            }, ensure_ascii=False)
        report_path = Path(expanded)
    else:
        # Auto-discover most recent.
        found = _find_latest_report()
        if found is None:
            return json.dumps({
                "error": (
                    f"No video-summary report found. "
                    f"No files matching {_CANONICAL_GLOB} exist. "
                    f"Run the summariser pipeline first."
                ),
            }, ensure_ascii=False)
        report_path = found

    # ── File existence & readability ──────────────────────────────────────
    if not report_path.exists():
        return json.dumps({
            "error": f"Report file not found: {report_path}",
        }, ensure_ascii=False)

    if not report_path.is_file():
        return json.dumps({
            "error": f"Not a regular file: {report_path}",
        }, ensure_ascii=False)

    try:
        content = report_path.read_text(encoding="utf-8")
    except Exception as exc:
        return json.dumps({
            "error": f"Failed to read report: {exc}",
        }, ensure_ascii=False)

    if not content.strip():
        return json.dumps({
            "error": f"Report file is empty: {report_path}",
        }, ensure_ascii=False)

    # ── Success: return the full raw content ───────────────────────────────
    # The conversation loop will detect this and use it as final_response.
    # We do NOT wrap it in JSON — the raw markdown is what the user needs.
    return content


# ── Availability check ───────────────────────────────────────────────────────

def _check_video_report_requirements() -> bool:
    """The tool is always available when the report directory exists."""
    return _REPORT_DIR.is_dir()


# ── Registry registration ────────────────────────────────────────────────────

registry.register(
    name="video_report_passthrough",
    toolset="video_report",
    schema=VIDEO_REPORT_PASSTHROUGH_SCHEMA,
    handler=video_report_passthrough,
    check_fn=_check_video_report_requirements,
    emoji="📹",
    max_result_size_chars=500_000,  # reports can be large
)
