from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = REPO_ROOT / "skills" / "github" / "github-repo-management" / "SKILL.md"
CODEX_SKILL = REPO_ROOT / "skills" / "autonomous-ai-agents" / "codex" / "SKILL.md"


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


def test_upstream_contribution_boundary_lesson_is_documented():
    text = SKILL_MD.read_text(encoding="utf-8")

    assert "Self-Use vs Upstream PR Decision Gate" in text
    assert "classify the user goal" in text
    assert "`self_use_local`" in text
    assert "`fork_sync`" in text
    assert "`upstream_contribution`" in text
    assert "`maintainer_policy`" in text
    assert "Upstream contribution must be explicit, not inferred" in text
    assert "stop after the local/fork branch is validated and pushed" in text
    assert "do not create an upstream PR" in text
    assert "do not chase contributor policy" in text
    assert "Origin read access is not origin write access" in text
    assert "Fork push success is not upstream mergeability" in text
    assert "target discovery before PR creation" in text
    assert "verify target branch prerequisites" in text
    assert "verify diff scope" in text
    assert "only after explicit authorization" in text
    assert "do not drag unrelated history into the PR" in text
    assert "Contributor policy, AUTHOR_MAP, base branch policy, branch protection, and maintainer approval" in text
    assert "produce a maintainer action note" in text
    assert "Do not fold AUTHOR_MAP or contributor-policy fixes into feature PRs" in text
    assert "Do not interpret read access, CI rerun success, or local test success as mergeability" in text
    assert "Do not keep retrying stale merge refs" in text
    assert "Do not retarget stacked passive PRs to upstream main until prerequisites are merged" in text
    assert "If base branch policy blocks merge, stop" in text
    assert "No force push, admin merge, or branch-protection bypass by default" in text


def test_codex_handoff_stops_at_local_goal_and_permission_boundary():
    text = CODEX_SKILL.read_text(encoding="utf-8")

    assert "Codex Handoff and Permission Boundaries" in text
    assert "Before giving a Codex prompt, summarize the current situation and next safe action" in text
    assert "local/fork improvement or upstream contribution" in text
    assert "stop after local/fork validation" in text
    assert "do not continue long upstream PR or contributor-policy workflows" in text
    assert "Stop at permission boundary" in text
    assert "origin write, upstream mergeability, contributor policy, AUTHOR_MAP, branch protection" in text
    assert "Do not turn a successful fork/local implementation into an upstream contribution workflow by inference" in text
