from __future__ import annotations

import json
from pathlib import Path

from agent.handoff_watchdog import format_notice, get_watchdog_summary, scan_handoff_dir


def _write_status(path: Path, **data):
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n")


def _write_watchdog(path: Path, **data):
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n")


def _read_report_states(path: Path) -> dict[str, str]:
    states: dict[str, str] = {}
    for line in path.read_text().splitlines():
        item = json.loads(line)
        states[item["handoff_base"]] = item["state"]
    return states


def test_handoff_watchdog_marks_stale_pending_without_result(tmp_path):
    status = tmp_path / "x.status.json"
    result = tmp_path / "x.result.json"
    _write_status(
        status,
        handoff_base="x",
        status="pending",
        created_at=1000,
        result_path=str(result),
        result_md_path=str(tmp_path / "x.result.md"),
    )

    alerts = scan_handoff_dir(tmp_path, stale_after_seconds=60, repeat_after_seconds=60, now=1201)

    assert len(alerts) == 1
    assert alerts[0]["handoff_base"] == "x"
    updated = json.loads(status.read_text())
    assert updated["status"] == "pending"
    assert updated["watchdog_state"] == "stale_pending"
    assert (tmp_path / "x.watchdog.json").exists()
    assert (tmp_path / "x.watchdog.md").exists()


def test_handoff_watchdog_ignores_completed_result(tmp_path):
    status = tmp_path / "x.status.json"
    result = tmp_path / "x.result.json"
    result.write_text(json.dumps({"status": "completed"}) + "\n")
    _write_status(status, handoff_base="x", status="pending", created_at=1000, result_path=str(result))

    alerts = scan_handoff_dir(tmp_path, stale_after_seconds=60, now=1201)

    assert alerts == []
    assert not (tmp_path / "x.watchdog.json").exists()


def test_handoff_watchdog_normalizes_pending_with_sibling_result(tmp_path):
    status = tmp_path / "x.status.json"
    result_md = tmp_path / "x.result.md"
    result_json = tmp_path / "x.result.json"
    result_md.write_text("done\n")
    result_json.write_text(json.dumps({"status": "completed", "summary": "done"}) + "\n")
    _write_status(status, handoff_base="x", status="pending", created_at=1000)

    alerts = scan_handoff_dir(tmp_path, stale_after_seconds=60, now=1201)

    assert alerts == []
    updated = json.loads(status.read_text())
    assert updated["status"] == "completed"
    assert updated["watchdog_state"] == "result_receipt_observed"
    assert updated["result_path"] == str(result_json)
    assert updated["result_md_path"] == str(result_md)
    assert set(updated["result_paths"]) == {str(result_md), str(result_json)}
    assert not (tmp_path / "x.watchdog.json").exists()


def test_handoff_watchdog_normalizes_pending_with_blocker_result(tmp_path):
    status = tmp_path / "x.status.json"
    result = tmp_path / "x.result.json"
    result.write_text(json.dumps({"status": "completed_with_blockers"}) + "\n")
    _write_status(status, handoff_base="x", status="pending", created_at=1000)

    alerts = scan_handoff_dir(tmp_path, stale_after_seconds=60, now=1201)

    assert alerts == []
    updated = json.loads(status.read_text())
    assert updated["status"] == "completed_with_blockers"
    assert updated["watchdog_state"] == "result_receipt_observed"
    assert updated["result_path"] == str(result)


def test_handoff_watchdog_notice_is_user_visible(tmp_path):
    alerts = [
        {
            "handoff_base": "auto-diagnosis-1",
            "status": "pending",
            "age_seconds": 300,
            "status_path": "/tmp/auto-diagnosis-1.status.json",
        }
    ]

    notice = format_notice(alerts)

    assert "Handoff 看门狗提醒" in notice
    assert "auto-diagnosis-1" in notice
    assert "result/status 回执" in notice


def test_handoff_watchdog_summary_reports_completed_with_blockers(tmp_path):
    status = tmp_path / "a0.status.json"
    result = tmp_path / "a0.result.json"
    result.write_text(json.dumps({
        "status": "completed_with_blockers",
        "next_single_task": "apply pipe fix",
    }) + "\n")
    _write_status(
        status,
        handoff_base="a0",
        status="pending",
        created_at=1000,
        result_path=str(result),
    )
    _write_watchdog(
        tmp_path / "a0.watchdog.json",
        handoff_base="a0",
        status="pending",
        status_path=str(status),
        result_path=str(result),
    )
    report_log = tmp_path / "reported.jsonl"

    notice = get_watchdog_summary(
        tmp_path,
        now=1201,
        reported_log_path=report_log,
    )

    assert "a0" in notice
    assert "completed_with_blockers" in notice
    assert "apply pipe fix" in notice
    assert _read_report_states(report_log) == {"a0": "blocked-reported"}


def test_handoff_watchdog_summary_suppresses_repeat_reports(tmp_path):
    status = tmp_path / "x.status.json"
    result = tmp_path / "x.result.json"
    result.write_text(json.dumps({"status": "completed", "next_single_task": "done"}) + "\n")
    _write_status(status, handoff_base="x", status="pending", created_at=1000, result_path=str(result))
    _write_watchdog(
        tmp_path / "x.watchdog.json",
        handoff_base="x",
        status="pending",
        status_path=str(status),
        result_path=str(result),
    )
    report_log = tmp_path / "reported.jsonl"

    first = get_watchdog_summary(tmp_path, now=1201, repeat_after_seconds=300, reported_log_path=report_log)
    second = get_watchdog_summary(tmp_path, now=1250, repeat_after_seconds=300, reported_log_path=report_log)

    assert "x" in first
    assert second == ""


def test_handoff_watchdog_summary_reports_fresh_pending(tmp_path):
    status = tmp_path / "x.status.json"
    result = tmp_path / "x.result.json"
    _write_status(status, handoff_base="x", status="pending", created_at=1000, result_path=str(result))
    _write_watchdog(
        tmp_path / "x.watchdog.json",
        handoff_base="x",
        status="pending",
        status_path=str(status),
        result_path=str(result),
    )
    report_log = tmp_path / "reported.jsonl"

    notice = get_watchdog_summary(
        tmp_path,
        now=1201,
        reported_log_path=report_log,
    )

    assert "`x`: pending 201s, no result" in notice
    assert _read_report_states(report_log) == {"x": "pending-reported"}


def test_handoff_watchdog_summary_suppresses_stale_pending(tmp_path):
    status = tmp_path / "old.status.json"
    result = tmp_path / "old.result.json"
    _write_status(status, handoff_base="old", status="pending", created_at=1000, result_path=str(result))
    _write_watchdog(
        tmp_path / "old.watchdog.json",
        handoff_base="old",
        status="pending",
        status_path=str(status),
        result_path=str(result),
    )
    report_log = tmp_path / "reported.jsonl"

    notice = get_watchdog_summary(
        tmp_path,
        now=5000,
        reported_log_path=report_log,
    )

    assert notice == ""
    assert _read_report_states(report_log) == {"old": "stale-suppressed"}
    assert get_watchdog_summary(tmp_path, now=5050, reported_log_path=report_log) == ""
    assert len(report_log.read_text().splitlines()) == 1


def test_handoff_watchdog_summary_summarizes_a0_pilot_style_result(tmp_path):
    result = tmp_path / "a0-pilot.result.json"
    result.write_text(json.dumps({
        "status": "completed_with_blockers",
        "recommendation": "Do not proceed to P0-2b design as clean.",
        "baseline": {"large": "nested result ignored by compact summary"},
    }) + "\n")
    _write_watchdog(
        tmp_path / "a0-pilot.watchdog.json",
        handoff_base="a0-pilot",
        result_path=str(result),
    )

    notice = get_watchdog_summary(tmp_path, now=1201, reported_log_path=tmp_path / "reported.jsonl")

    assert "a0-pilot" in notice
    assert "completed_with_blockers" in notice
    assert "Do not proceed to P0-2b design as clean." in notice
    assert len(notice) <= 600
