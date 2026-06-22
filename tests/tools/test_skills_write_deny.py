"""Regression tests for generic file-write denial under ~/.hermes/skills."""

from __future__ import annotations

from unittest.mock import patch


VALID_SKILL = """\
---
name: direct-skill
description: Verifies skill manager writes.
---

# Direct Skill

Use this in tests.
"""


def test_generic_write_denies_active_skills_dir(tmp_path, monkeypatch):
    import agent.file_safety as fs

    hermes_home = tmp_path / "hermes"
    skills_dir = hermes_home / "skills"
    monkeypatch.setattr(fs, "_hermes_home_path", lambda: hermes_home)
    monkeypatch.setattr(fs, "_hermes_root_path", lambda: hermes_home)

    assert fs.is_write_denied(str(skills_dir / "evil" / "SKILL.md")) is True


def test_skill_manage_create_still_writes_via_own_path(tmp_path):
    from tools.skill_manager_tool import _create_skill

    skills_dir = tmp_path / "hermes" / "skills"
    with patch("tools.skill_manager_tool.SKILLS_DIR", skills_dir), patch(
        "agent.skill_utils.get_all_skills_dirs", return_value=[skills_dir]
    ):
        result = _create_skill("direct-skill", VALID_SKILL)

    assert result["success"] is True
    assert (skills_dir / "direct-skill" / "SKILL.md").exists()
