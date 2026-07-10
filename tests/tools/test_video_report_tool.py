"""Tests for the video_report_passthrough tool module."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from tools.video_report_tool import (
    video_report_passthrough,
    _is_allowed,
    _find_latest_report,
    _list_reports,
    _REPORT_DIR,
    _REPORT_PREFIX,
    _REPORT_SUFFIX,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_report_dir(tmp_path: Path):
    """Create a temporary OS_Core/output-like directory with test reports."""
    report_dir = tmp_path / "OS_Core" / "output"
    report_dir.mkdir(parents=True)
    return report_dir


@pytest.fixture
def sample_report(temp_report_dir: Path):
    """Create a sample video_summary report and return its path."""
    report = temp_report_dir / f"{_REPORT_PREFIX}test_video{_REPORT_SUFFIX}"
    report.write_text(
        "# Video Summary: Test Video\n\n"
        "This is the full video summary content.\n\n"
        "## Key Points\n"
        "- Point one\n"
        "- Point two\n"
        "- Point three\n"
    )
    return report


# ── Path validation tests ────────────────────────────────────────────────────

class TestIsAllowed:
    def test_allows_correct_path(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        p = str(temp_report_dir / f"{_REPORT_PREFIX}test.md")
        assert _is_allowed(p) is True

    def test_rejects_wrong_directory(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        p = str(temp_report_dir.parent / "other.md")
        assert _is_allowed(p) is False

    def test_rejects_wrong_prefix(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        p = str(temp_report_dir / "other_report.md")
        assert _is_allowed(p) is False

    def test_rejects_wrong_suffix(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        p = str(temp_report_dir / f"{_REPORT_PREFIX}test.txt")
        assert _is_allowed(p) is False

    def test_rejects_subdirectory_within_allowed(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        nested = str(temp_report_dir / "sub" / "video_summary_test.md")
        assert _is_allowed(nested) is False

    def test_rejects_wrong_parent_directory(self, temp_report_dir: Path, monkeypatch):
        """File must be directly in the report dir, not a subdirectory."""
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        wrong = str(temp_report_dir.parent / "video_summary_test.md")
        assert _is_allowed(wrong) is False


# ── Auto-discovery tests ─────────────────────────────────────────────────────

class TestFindLatestReport:
    def test_finds_most_recent(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        old = temp_report_dir / f"{_REPORT_PREFIX}old{_REPORT_SUFFIX}"
        old.write_text("old content")
        new = temp_report_dir / f"{_REPORT_PREFIX}new{_REPORT_SUFFIX}"
        new.write_text("new content")
        # Touch new to be newer
        new.touch()
        found = _find_latest_report()
        assert found == new

    def test_returns_none_when_empty(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        assert _find_latest_report() is None


class TestListReports:
    def test_lists_sorted(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        (temp_report_dir / f"{_REPORT_PREFIX}b1{_REPORT_SUFFIX}").write_text("b")
        (temp_report_dir / f"{_REPORT_PREFIX}a2{_REPORT_SUFFIX}").write_text("a")
        assert _list_reports() == [
            f"{_REPORT_PREFIX}a2{_REPORT_SUFFIX}",
            f"{_REPORT_PREFIX}b1{_REPORT_SUFFIX}",
        ]


# ── Tool handler tests ───────────────────────────────────────────────────────

class TestVideoReportPassthrough:
    def test_returns_content_with_explicit_path(self, sample_report: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", sample_report.parent)
        result = video_report_passthrough(path=str(sample_report))
        assert "# Video Summary: Test Video" in result
        assert "Point one" in result
        assert result.endswith("- Point three\n")

    def test_auto_discovers_latest(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        r1 = temp_report_dir / f"{_REPORT_PREFIX}a{_REPORT_SUFFIX}"
        r1.write_text("report a")
        r2 = temp_report_dir / f"{_REPORT_PREFIX}b{_REPORT_SUFFIX}"
        r2.write_text("report b")
        r2.touch()  # make it newer
        result = video_report_passthrough(path=None)
        assert result == "report b"

    def test_error_on_nonexistent_path(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        result = video_report_passthrough(path=str(temp_report_dir / "nonexistent.md"))
        parsed = json.loads(result)
        assert "error" in parsed

    def test_error_on_disallowed_path(self, monkeypatch):
        result = video_report_passthrough(path="/etc/passwd")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_error_no_reports_when_empty(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        result = video_report_passthrough(path=None)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "No video-summary report found" in parsed["error"]

    def test_error_on_empty_file(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        r = temp_report_dir / f"{_REPORT_PREFIX}empty{_REPORT_SUFFIX}"
        r.write_text("")
        result = video_report_passthrough(path=str(r))
        parsed = json.loads(result)
        assert "error" in parsed
        assert "empty" in parsed["error"].lower()

    def test_error_on_directory_instead_of_file(self, temp_report_dir: Path, monkeypatch):
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", temp_report_dir)
        d = temp_report_dir / f"{_REPORT_PREFIX}dir{_REPORT_SUFFIX}"
        d.mkdir()
        result = video_report_passthrough(path=str(d))
        parsed = json.loads(result)
        assert "error" in parsed
        assert "not a regular file" in parsed["error"].lower()

    def test_path_with_tilde_expansion(self, sample_report: Path, monkeypatch):
        """Verify ~ is expanded correctly in the _is_allowed check."""
        monkeypatch.setattr("tools.video_report_tool._REPORT_DIR", sample_report.parent)
        # Use home-relative path to test tilde expansion
        home = Path.home()
        rel = sample_report.relative_to(home) if home in sample_report.parents else None
        if rel:
            tilde_path = f"~/{rel}"
            assert _is_allowed(tilde_path) is True


# ── Registry registration test ───────────────────────────────────────────────

class TestRegistryRegistration:
    def test_registered_under_correct_name(self):
        from tools.registry import registry
        entry = registry.get_entry("video_report_passthrough")
        assert entry is not None
        assert entry.name == "video_report_passthrough"
        assert entry.toolset == "video_report"
        assert entry.emoji == "📹"

    def test_schema_has_optional_path(self):
        from tools.registry import registry
        entry = registry.get_entry("video_report_passthrough")
        schema = entry.schema
        params = schema.get("parameters", {}).get("properties", {})
        assert "path" in params
        assert params["path"]["type"] == "string"
        # path is optional
        assert "path" not in schema.get("parameters", {}).get("required", [])
