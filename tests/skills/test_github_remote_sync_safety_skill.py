from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = REPO_ROOT / "skills" / "github" / "github-repo-management" / "SKILL.md"


def test_github_remote_sync_safety_lesson_is_documented():
    text = SKILL_MD.read_text(encoding="utf-8")

    assert "Remote Sync Safety Gate" in text
    assert "Do not count `git ls-remote` success as write permission" in text
    assert "Do not assume `origin` is writable just because it is readable" in text
    assert "prior proven successful branch/tag pushes used `fork`, not `origin`" in text
    assert "use `fork` only when the user explicitly authorizes `fork`" in text
    assert "Local tag existence does not imply the tag exists on the remote" in text
    assert "Do not fallback between `origin`, `fork`, or `upstream` without explicit authorization" in text
    assert "ssh.github.com:443" in text
    assert "github.com:443` is not the GitHub SSH endpoint" in text
    assert "No force push by default" in text
    assert "git push <authorized-fork-remote> main" in text
