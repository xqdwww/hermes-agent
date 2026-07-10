from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PENDING_STATUSES = {"pending", "queued", "running", "inflight", "in_progress"}
DONE_STATUSES = {"completed", "complete", "done", "success", "succeeded"}
REPORTABLE_RESULT_STATUSES = DONE_STATUSES | {"completed_with_blockers", "blocked", "failed", "error", "blocked_by_sandbox", "user_run_required"}
DEFAULT_STALE_SECONDS = 120
DEFAULT_REPEAT_SECONDS = 300
SUMMARY_STALE_SECONDS = 3600
SUMMARY_MAX_CHARS = 600


def _now() -> float:
    return time.time()


def _today_handoff_dir() -> Path:
    return Path.home() / "Documents" / "Codex" / time.strftime("%Y-%m-%d") / "hermes" / "handoff"


def _parse_time(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return 0.0
    raw = value.strip()
    if raw.isdigit():
        return float(raw)
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return 0.0


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).astimezone().isoformat(timespec="seconds")


def _result_completed(status_data: dict[str, Any]) -> bool:
    result_path = status_data.get("result_path")
    if not result_path:
        return False
    result = _load_json(Path(str(result_path)).expanduser())
    return str(result.get("status") or "").lower() in DONE_STATUSES


def _result_candidates(status_path: Path, status_data: dict[str, Any], base: str) -> list[Path]:
    candidates: list[Path] = []
    for key in ("result_path", "result_json_path", "result_md_path"):
        raw = status_data.get(key)
        if raw:
            candidates.append(Path(str(raw)).expanduser())
    candidates.extend(
        [
            status_path.with_name(f"{base}.result.json"),
            status_path.with_name(f"{base}.result.md"),
        ]
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        marker = str(path)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(path)
    return unique


def _normalize_result_receipt_status(
    status_path: Path,
    status_data: dict[str, Any],
    *,
    now: float,
    write: bool,
) -> bool:
    status = str(status_data.get("status") or "").lower()
    if status not in PENDING_STATUSES:
        return False

    base = str(status_data.get("handoff_base") or status_path.name.removesuffix(".status.json"))
    existing_results = [path for path in _result_candidates(status_path, status_data, base) if path.exists()]
    if not existing_results:
        return False

    result_json = next((path for path in existing_results if path.suffix == ".json"), None)
    result_md = next((path for path in existing_results if path.suffix == ".md"), None)
    result_data = _load_json(result_json) if result_json else {}
    result_status = str(result_data.get("status") or result_data.get("state") or "").lower()
    terminal_status = result_status if result_status in REPORTABLE_RESULT_STATUSES else "completed"

    if write:
        latest_result = max(existing_results, key=lambda path: path.stat().st_mtime)
        status_data["status"] = terminal_status
        status_data.setdefault("completed_at", _iso_from_timestamp(latest_result.stat().st_mtime))
        status_data["normalized_at"] = _iso_from_timestamp(now)
        status_data["watchdog_state"] = "result_receipt_observed"
        status_data["result_paths"] = [str(path) for path in existing_results]
        if result_json:
            status_data["result_path"] = str(result_json)
        if result_md:
            status_data["result_md_path"] = str(result_md)
        _write_json(status_path, status_data)

    return True


def _handoff_age_seconds(status_data: dict[str, Any], now: float) -> float:
    created = _parse_time(status_data.get("created_at"))
    if not created:
        return 0.0
    return max(0.0, now - created)


def scan_handoff_dir(
    handoff_dir: Path | None = None,
    *,
    stale_after_seconds: int | None = None,
    repeat_after_seconds: int | None = None,
    now: float | None = None,
    write: bool = True,
) -> list[dict[str, Any]]:
    handoff_dir = handoff_dir or _today_handoff_dir()
    stale_after_seconds = int(stale_after_seconds or os.getenv("HERMES_HANDOFF_STALE_SECONDS") or DEFAULT_STALE_SECONDS)
    repeat_after_seconds = int(repeat_after_seconds or os.getenv("HERMES_HANDOFF_REPEAT_SECONDS") or DEFAULT_REPEAT_SECONDS)
    now = float(now if now is not None else _now())
    if not handoff_dir.exists():
        return []

    alerts: list[dict[str, Any]] = []
    for status_path in sorted(handoff_dir.glob("*.status.json")):
        data = _load_json(status_path)
        status = str(data.get("status") or "").lower()
        if status not in PENDING_STATUSES:
            continue
        if _normalize_result_receipt_status(status_path, data, now=now, write=write):
            continue
        if _result_completed(data):
            continue
        age = _handoff_age_seconds(data, now)
        if age < stale_after_seconds:
            continue
        last_notice = _parse_time(data.get("watchdog_last_notice_at"))
        should_notice = not last_notice or now - last_notice >= repeat_after_seconds
        base = str(data.get("handoff_base") or status_path.name.removesuffix(".status.json"))
        alert = {
            "handoff_base": base,
            "status": status,
            "age_seconds": int(age),
            "status_path": str(status_path),
            "result_path": str(data.get("result_path") or ""),
            "result_md_path": str(data.get("result_md_path") or ""),
            "message": (
                f"Handoff {base} has been {status} for {int(age)}s without a result receipt. "
                "Hermes must report pending/blocked instead of promising future completion."
            ),
            "notify": should_notice,
        }
        alerts.append(alert)
        if write:
            data["watchdog_state"] = "stale_pending"
            data["watchdog_message"] = alert["message"]
            data["watchdog_checked_at"] = now
            if should_notice:
                data["watchdog_last_notice_at"] = now
            _write_json(status_path, data)
            _write_json(status_path.with_name(f"{base}.watchdog.json"), alert)
            status_path.with_name(f"{base}.watchdog.md").write_text(format_alert_md(alert) + "\n")
            _append_alert_log(alert)
    return alerts


def _append_alert_log(alert: dict[str, Any]) -> None:
    log_dir = Path.home() / ".hermes" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "handoff-watchdog-alerts.jsonl").open("a") as fh:
            fh.write(json.dumps(alert, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        return


def format_alert_md(alert: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Handoff Watchdog Alert",
            "",
            f"- handoff: `{alert.get('handoff_base', '')}`",
            f"- status: `{alert.get('status', '')}`",
            f"- age_seconds: `{alert.get('age_seconds', '')}`",
            f"- status_path: `{alert.get('status_path', '')}`",
            f"- result_path: `{alert.get('result_path', '')}`",
            "",
            str(alert.get("message") or ""),
        ]
    )


def format_notice(alerts: list[dict[str, Any]], *, limit: int = 3) -> str:
    if not alerts:
        return ""
    rows = alerts[:limit]
    lines = [
        "Handoff 看门狗提醒：有任务已经 pending 太久，还没有 result/status 回执，不能继续让用户等。",
    ]
    for alert in rows:
        lines.append(
            f"- `{alert.get('handoff_base')}`: {alert.get('status')} {alert.get('age_seconds')}s，"
            f"status: `{alert.get('status_path')}`"
        )
    if len(alerts) > limit:
        lines.append(f"- 还有 {len(alerts) - limit} 个类似卡住的 handoff。")
    return "\n".join(lines)


def scan_and_format_notice(
    handoff_dir: Path | None = None,
    *,
    stale_after_seconds: int | None = None,
    now: float | None = None,
) -> str:
    alerts = scan_handoff_dir(
        handoff_dir,
        stale_after_seconds=stale_after_seconds,
        now=now,
        write=True,
    )
    return format_notice(alerts)



def _reported_log_path() -> Path:
    return Path.home() / ".hermes" / "logs" / "watchdog-reported.jsonl"


def _load_reported_state(path: Path) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return state
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        base = str(row.get("handoff_base") or "")
        if base:
            state[base] = row
    return state


def _append_reported_log(path: Path, row: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        return


def _short_text(value: Any, limit: int = 96) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _result_path_for(status_path: Path, data: dict[str, Any], base: str) -> Path:
    raw = data.get("result_path")
    if raw:
        return Path(str(raw)).expanduser()
    return status_path.with_name(f"{base}.result.json")


def _result_status(result: dict[str, Any]) -> str:
    return str(result.get("status") or result.get("state") or "unknown")


def _result_summary(result: dict[str, Any]) -> str:
    for key in ("summary", "verdict", "recommendation", "next_single_task", "message"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.strip().split())
    return ""


def _terminal_report_state(kind: str, status: str) -> str:
    if kind == "pending":
        return "pending-reported"
    if kind == "stale":
        return "stale-suppressed"
    lowered = status.lower()
    if "block" in lowered or lowered in {"user_run_required", "user_action_required", "blocked"}:
        return "blocked-reported"
    return "completed-reported"


def get_watchdog_summary(
    handoff_dir: Path | None = None,
    max_items: int = 5,
    *,
    now: float | None = None,
    repeat_after_seconds: int | None = None,
    stale_after_seconds: int | None = None,
    reported_log_path: Path | None = None,
) -> str:
    """Read watchdog files and return a compact summary for user-facing injection.

    Returns "" if nothing should be reported to the active conversation.
    """
    handoff_dir = handoff_dir or _today_handoff_dir()
    now = float(now if now is not None else _now())
    repeat_after_seconds = int(repeat_after_seconds or os.getenv("HERMES_HANDOFF_REPORT_REPEAT_SECONDS") or DEFAULT_REPEAT_SECONDS)
    stale_after_seconds = int(stale_after_seconds or os.getenv("HERMES_HANDOFF_SUMMARY_STALE_SECONDS") or SUMMARY_STALE_SECONDS)
    reported_log_path = reported_log_path or _reported_log_path()
    if not handoff_dir.exists():
        return ""

    reported = _load_reported_state(reported_log_path)
    items: list[dict[str, Any]] = []
    seen_bases: set[str] = set()

    for watchdog_path in sorted(handoff_dir.glob("*.watchdog.json")):
        alert = _load_json(watchdog_path)
        base = str(alert.get("handoff_base") or watchdog_path.name.removesuffix(".watchdog.json"))
        if not base:
            continue
        seen_bases.add(base)

        status_path = Path(str(alert.get("status_path") or handoff_dir / f"{base}.status.json")).expanduser()
        status_data = _load_json(status_path)
        result_path = Path(str(alert.get("result_path") or _result_path_for(status_path, status_data, base))).expanduser()
        age = _handoff_age_seconds(status_data, now)
        if not age:
            age = float(alert.get("age_seconds") or 0)
        result = _load_json(result_path) if result_path.exists() else {}

        if result:
            result_status = _result_status(result)
            kind = "completed"
            line = f"- `{base}`: completed → status: {result_status}"
            result_note = _result_summary(result)
            if result_note:
                line = f"{line}; {_short_text(result_note, 140)}"
            sort_group = 1
        elif age > stale_after_seconds:
            result_status = str(alert.get("status") or status_data.get("status") or "pending")
            kind = "stale"
            line = f"- `{base}`: stale-suppressed after {int(age)}s, no result"
            sort_group = 2
        else:
            result_status = str(alert.get("status") or status_data.get("status") or "pending")
            kind = "pending"
            line = f"- `{base}`: pending {int(age)}s, no result"
            sort_group = 0

        previous = reported.get(base) or {}
        last_reported_at = _parse_time(previous.get("last_reported_at"))
        if last_reported_at and now - last_reported_at < repeat_after_seconds:
            continue

        terminal_state = _terminal_report_state(kind, result_status)
        _append_reported_log(
            reported_log_path,
            {
                "handoff_base": base,
                "last_reported_at": now,
                "result_path": str(result_path),
                "state": terminal_state,
                "status": result_status,
            },
        )
        if kind == "stale":
            continue
        items.append(
            {
                "age": int(age),
                "base": base,
                "line": line,
                "priority": sort_group,
            }
        )

    consumed_bases = set(reported) | seen_bases
    for status_path in sorted(handoff_dir.glob("*.status.json")):
        base = status_path.name.removesuffix(".status.json")
        if base in consumed_bases:
            continue
        status_data = _load_json(status_path)
        result_status = str(status_data.get("status") or "").lower()
        if result_status not in DONE_STATUSES:
            continue

        result_path = _result_path_for(status_path, status_data, base)
        result_md_path = Path(str(status_data.get("result_md_path") or status_path.with_name(f"{base}.result.md"))).expanduser()
        result_json_exists = result_path.exists()
        result_md_exists = result_md_path.exists()
        if not result_json_exists and not result_md_exists:
            continue

        age = _handoff_age_seconds(status_data, now)
        result = _load_json(result_path) if result_json_exists else {}
        display_status = _result_status(result) if result else result_status
        line = f"- `{base}`: completed → result ready to read"
        result_note = _result_summary(result)
        if result_note:
            line = f"- `{base}`: completed → status: {display_status}; {_short_text(result_note, 140)}"

        reported_result_path = result_path if result_json_exists else result_md_path
        _append_reported_log(
            reported_log_path,
            {
                "handoff_base": base,
                "last_reported_at": now,
                "result_path": str(reported_result_path),
                "state": "completed-reported",
                "status": display_status,
            },
        )
        items.append(
            {
                "age": int(age),
                "base": base,
                "line": line,
                "priority": 0,
            }
        )

    if not items:
        return ""

    items.sort(key=lambda row: (row["priority"], row["age"], row["base"]))
    shown = items[:max_items]
    lines = [str(row["line"]) for row in shown]
    if len(items) > max_items:
        lines.append(f"+{len(items) - max_items} more")
    summary = "\n".join(lines)
    if len(summary) <= SUMMARY_MAX_CHARS:
        return summary
    return summary[: SUMMARY_MAX_CHARS - 1].rstrip() + "…"

def notify(alerts: list[dict[str, Any]]) -> None:
    if os.getenv("HERMES_HANDOFF_WATCHDOG_OS_NOTIFY", "").lower() not in {"1", "true", "yes", "on"}:
        return
    for alert in alerts:
        if not alert.get("notify"):
            continue
        title = "Hermes handoff 卡住了"
        message = f"{alert.get('handoff_base')} pending {alert.get('age_seconds')}s，缺 result 回执"
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{message}" with title "{title}"',
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--handoff-dir", default="")
    parser.add_argument("--stale-after", type=int, default=None)
    parser.add_argument("--repeat-after", type=int, default=None)
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args(argv)
    handoff_dir = Path(args.handoff_dir).expanduser() if args.handoff_dir else None
    alerts = scan_handoff_dir(
        handoff_dir,
        stale_after_seconds=args.stale_after,
        repeat_after_seconds=args.repeat_after,
        write=True,
    )
    if args.notify:
        notify(alerts)
    if args.print:
        notice = format_notice(alerts)
        if notice:
            print(notice)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
