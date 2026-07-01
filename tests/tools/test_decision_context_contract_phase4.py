import re
from pathlib import Path

from tools.decision_context_contract import (
    FINAL_VALIDATION_MISSING_DECISION_CONTEXT_CONTRACT,
    FINAL_VALIDATION_MISSING_MODERATOR_RETENTION,
    generate_decision_context_contract,
    validate_final_report_against_decision_context_contract,
    write_decision_context_contract_artifacts,
)
from tools.task_engine_contracts import (
    CANONICAL_STAGES,
    ENGINE_DECISION,
    make_stage_record,
    planned_outputs,
    validate_pipeline,
)
from tools.task_engine_executors import _final_controller_report_from_packet


ADHD_AI_QUERY = """
AI 信息环境下，ADHD 儿童特征的未来结构性反转与长期发展决策。
男孩，7岁半，IQ 124，明显 ADHD 倾向，注意力波动、兴趣驱动、内在走神明显，长期柔术训练。
未来10年 AI 持续降低知识获取、解释、反馈、规划和个性化学习成本。
必须关注 ADHD 注意力波动、兴趣驱动、执行功能、内在走神、AI 信息环境、知识获取成本下降、儿童长期发展、
IQ 124、长期柔术训练、知识获取能力、问题选择能力、验证能力、收束能力、延迟反馈耐受、身体反馈系统。
最终输出必须包含：未来优势变陷阱 Top5、未来缺陷变优势 Top5、最危险的错误培养路径、最反直觉但值得追踪的假设、danger_flag。
每条 Top5 必须包含：当前优势 / 当前缺陷、触发条件、中间机制、反转后的陷阱 / 反转后的优势、失效条件、确定性等级。
禁止输出医学诊断、治疗建议、家长建议、培养计划。
"""


def _write_stage_a_fixture(tmp_path: Path) -> Path:
    run_dir = tmp_path / ".hermes_task_engine_runs" / "1782891050_research_research_l1_l5"
    l5_dir = run_dir / "L5_deepseek_acceptance"
    l2_5_dir = run_dir / "L2_5_codex_evidence_organizer"
    l5_dir.mkdir(parents=True)
    l2_5_dir.mkdir(parents=True)
    packet = l5_dir / "research_evidence_packet.md"
    packet.write_text(
        "\n".join(
            [
                "current_run_id: 1782891050_research_research_l1_l5",
                "current_query_hash: sha256:562c0abf92bb922eb40377211ac481ebadd0eafc5ff549feae62074a03ba5438",
                f"current_artifact_dir: {run_dir}",
                "ADHD 注意力波动, 兴趣驱动, 执行功能, 内在走神, AI 信息环境, 知识获取成本下降, 儿童长期发展.",
                "IQ 124 and 长期柔术训练 moderate 身体反馈系统 and 延迟反馈耐受.",
            ]
        ),
        encoding="utf-8",
    )
    (l2_5_dir / "sources.csv").write_text("source_id,title,url\nS1,ADHD and AI,https://example.test/source\n", encoding="utf-8")
    (l2_5_dir / "evidence.csv").write_text("evidence_id,source_id,claim_id,evidence_tier\nE1,S1,C1,evidence_supported\n", encoding="utf-8")
    (l2_5_dir / "claims.md").write_text(
        "ADHD 注意力波动\n兴趣驱动\n执行功能\n内在走神\nAI 信息环境\n知识获取成本下降\n儿童长期发展\n"
        "知识获取能力\n问题选择能力\n验证能力\n收束能力\n延迟反馈耐受\n身体反馈系统\n",
        encoding="utf-8",
    )
    (l2_5_dir / "gaps.md").write_text("full text evidence gap remains visible.\n", encoding="utf-8")
    return packet


def _contract(tmp_path: Path) -> dict:
    return generate_decision_context_contract(
        original_query=ADHD_AI_QUERY,
        research_packet_path=_write_stage_a_fixture(tmp_path),
    )


def _valid_final(tmp_path: Path) -> tuple[str, dict]:
    contract = _contract(tmp_path)
    packet = {
        "mode": ENGINE_DECISION,
        "query": ADHD_AI_QUERY,
        "decision_context_contract_required": True,
        "decision_context_contract": contract,
        "excerpts": {
            "convergence_report": (
                f"decision_context_contract_id: {contract['contract_id']}\n"
                f"task_topic: {contract['task_topic']['title']}\n"
                "ADHD 注意力波动 兴趣驱动 执行功能 内在走神 AI 信息环境 知识获取成本下降 儿童长期发展 "
                "IQ 124 长期柔术训练 知识获取能力 问题选择能力 验证能力 收束能力 延迟反馈耐受 身体反馈系统 "
                "evidence_supported plausible_inference forward_looking_hypothesis"
            ),
            "external_calibration": (
                f"decision_context_contract_id: {contract['contract_id']}\n"
                f"task_topic: {contract['task_topic']['title']}\n"
                "calibration_verdict: calibrated against user decision evidence strength. "
                "ADHD 注意力波动 兴趣驱动 执行功能 内在走神 AI 信息环境 知识获取成本下降 儿童长期发展 "
                "IQ 124 长期柔术训练 知识获取能力 问题选择能力 验证能力 收束能力 延迟反馈耐受 身体反馈系统 "
                "evidence_supported plausible_inference forward_looking_hypothesis"
            ),
        },
    }
    return _final_controller_report_from_packet(packet), contract


def _decision_run(base_dir: Path, final_text: str) -> dict:
    stages = []
    for spec in CANONICAL_STAGES[ENGINE_DECISION]:
        outputs = planned_outputs(spec, base_dir)
        for output in outputs.values():
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("validated stage output\n", encoding="utf-8")
        if spec.stage_name == "final_controller_report":
            Path(outputs["final_decision_report.md"]).write_text(final_text, encoding="utf-8")
        record = make_stage_record(
            spec,
            base_dir=base_dir,
            created=True,
            valid=True,
            status="real",
            outputs=outputs,
        )
        stages.append(record.__dict__)
    return {"mode": ENGINE_DECISION, "execution_mode": "production-decision-full", "stages": stages}


def _errors_for(text: str, contract: dict) -> list[str]:
    return validate_final_report_against_decision_context_contract(text, contract)


def test_valid_contract_driven_adhd_final_passes_phase4_gate(tmp_path):
    text, contract = _valid_final(tmp_path)

    assert _errors_for(text, contract) == []


def test_production_pipeline_final_validation_passes_with_contract(tmp_path):
    text, contract = _valid_final(tmp_path)
    decision_dir = tmp_path / "decision_run"
    write_decision_context_contract_artifacts(contract, base_dir=decision_dir)

    validation = validate_pipeline(
        ENGINE_DECISION,
        _decision_run(decision_dir, text),
        base_dir=decision_dir,
        production=True,
    )

    assert validation["valid"] is True
    assert validation["production_valid_fresh_packet"] is True


def test_missing_contract_blocks_production_final_validation(tmp_path):
    text, _contract = _valid_final(tmp_path)
    decision_dir = tmp_path / "decision_run"

    validation = validate_pipeline(
        ENGINE_DECISION,
        _decision_run(decision_dir, text),
        base_dir=decision_dir,
        production=True,
    )

    assert validation["valid"] is False
    assert FINAL_VALIDATION_MISSING_DECISION_CONTEXT_CONTRACT in validation["errors"]


def test_missing_section_blocks(tmp_path):
    text, contract = _valid_final(tmp_path)
    bad = text.replace("## danger_flag", "## dangerflag", 1)

    assert "missing_required_section:danger_flag" in _errors_for(bad, contract)


def test_top5_count_mismatch_blocks(tmp_path):
    text, contract = _valid_final(tmp_path)
    bad = re.sub(r"(?ms)^5\.\s+.*?(?=^## 未来缺陷变优势 Top5)", "", text, count=1)

    assert any(error.startswith("required_count_mismatch:未来优势变陷阱 Top5:5:4") for error in _errors_for(bad, contract))


def test_missing_item_field_blocks(tmp_path):
    text, contract = _valid_final(tmp_path)
    bad = text.replace("触发条件：", "触发：", 1)

    assert any("missing_item_field:未来优势变陷阱 Top5:1:触发条件" in error for error in _errors_for(bad, contract))


def test_paragraph_only_item_blocks(tmp_path):
    _text, contract = _valid_final(tmp_path)
    sections = contract["user_output_contract"]["required_sections"]
    bad = "\n".join(f"## {section}\n1. 这里只写一段泛化文字。" for section in sections)

    assert any(error.startswith("paragraph_only_item:未来优势变陷阱 Top5:1") for error in _errors_for(bad, contract))


def test_missing_iq_moderator_blocks(tmp_path):
    text, contract = _valid_final(tmp_path)
    bad = text.replace("IQ 124", "高智商")

    assert f"{FINAL_VALIDATION_MISSING_MODERATOR_RETENTION}:iq_124" in _errors_for(bad, contract)


def test_missing_bjj_body_feedback_blocks(tmp_path):
    text, contract = _valid_final(tmp_path)
    bad = text.replace("长期柔术训练", "长期运动训练").replace("身体反馈系统", "运动反馈").replace("身体反馈", "运动反馈")

    errors = _errors_for(bad, contract)
    assert f"{FINAL_VALIDATION_MISSING_MODERATOR_RETENTION}:long_term_bjj_training" in errors
    assert f"{FINAL_VALIDATION_MISSING_MODERATOR_RETENTION}:long_term_bjj_training:missing_body_feedback_logic" in errors


def test_missing_required_dimension_blocks(tmp_path):
    text, contract = _valid_final(tmp_path)
    bad = text.replace("收束能力", "整理能力")

    assert "missing_required_dimension:convergence_ability" in _errors_for(bad, contract)


def test_missing_evidence_tier_blocks(tmp_path):
    text, contract = _valid_final(tmp_path)
    bad = text.replace("证据层级：证据支持", "证据类型：证据支持", 2)

    assert any(error.startswith("missing_evidence_tier_field:未来优势变陷阱 Top5:1") for error in _errors_for(bad, contract))


def test_forbidden_internal_term_blocks(tmp_path):
    text, contract = _valid_final(tmp_path)
    bad = text + "\n\npipeline"

    assert "forbidden_internal_term:pipeline" in _errors_for(bad, contract)


def test_template_residue_blocks(tmp_path):
    text, contract = _valid_final(tmp_path)
    bad = text + "\n\n## 证据边界\n泛化边界段落。"

    assert "generic_template_residue:证据边界" in _errors_for(bad, contract)


def test_generic_final_blocks(tmp_path):
    _text, contract = _valid_final(tmp_path)
    bad = "\n".join(
        [
            "## 未来优势变陷阱 Top5",
            "1. 当前优势 / 当前缺陷：泛化能力。触发条件：泛化条件。中间机制：泛化机制。反转后的陷阱 / 反转后的优势：泛化结果。失效条件：泛化失效。确定性等级：中；证据层级：合理推断。",
            "## 未来缺陷变优势 Top5",
            "1. 当前优势 / 当前缺陷：泛化能力。触发条件：泛化条件。中间机制：泛化机制。反转后的陷阱 / 反转后的优势：泛化结果。失效条件：泛化失效。确定性等级：中；证据层级：合理推断。",
            "## 最危险的错误培养路径",
            "泛化段落。",
            "## 最反直觉但值得追踪的假设",
            "泛化段落。",
            "## danger_flag",
            "泛化段落。",
        ]
    )

    assert "topic_drift_or_generic_final" in _errors_for(bad, contract)
