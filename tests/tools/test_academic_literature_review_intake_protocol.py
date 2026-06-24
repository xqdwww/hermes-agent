from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = (
    REPO_ROOT
    / "optional-skills"
    / "research-decision"
    / "academic-literature-review-writer"
    / "SKILL.md"
)


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_hermes_invocation_protocol_declared():
    text = _skill_text()

    for section in [
        "hermes_invocation_protocol",
        "two_step_execution_rule",
        "intake_form",
        "minimum_required_fields",
        "no_direct_write_without_intake",
        "hermes_runtime_boundary",
    ]:
        assert f"## {section}" in text


def test_required_intake_fields_declared():
    text = _skill_text()

    for field in [
        "topic_or_title",
        "research_question",
        "review_type",
        "target_length",
        "citation_style",
        "source_corpus",
        "expected_source_count",
        "full_text_availability",
        "target_audience",
        "output_language",
    ]:
        assert f"`{field}`" in text


def test_default_chinese_intake_form_present():
    text = _skill_text()

    for phrase in [
        "请先填写下面信息",
        "题目 / 暂定题目",
        "核心研究问题",
        "综述类型",
        "目标篇幅",
        "引用格式",
        "文献来源 / 文件路径",
        "预计文献数量",
        "full text 状态",
        "目标读者",
        "输出语言",
    ]:
        assert phrase in text


def test_no_runtime_integration_boundary_locked():
    text = _skill_text()

    for phrase in [
        "passive optional skill",
        "must not modify Research/Decision routing",
        "must not create a new TaskMode",
        "Research engine runtime behavior must remain unchanged",
    ]:
        assert phrase in text


def test_direct_write_without_intake_failure_locked():
    text = _skill_text()
    lowered = text.lower()

    assert "FAIL_DIRECT_WRITE_WITHOUT_INTAKE" in text
    assert "no direct write without intake" in lowered or "不得直接写" in text
