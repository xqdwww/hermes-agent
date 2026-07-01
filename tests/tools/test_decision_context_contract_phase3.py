import json
from pathlib import Path

import pytest

from tools.decision_context_contract import (
    generate_decision_context_contract,
    validate_final_report_contract_rendering,
    write_decision_context_contract_artifacts,
)
from tools.task_engine_contracts import ENGINE_DECISION
from tools.task_engine_executors import (
    _decision_final_controller_packet,
    _final_controller_report_from_packet,
)


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

INTERNAL_TERMS = [
    "research packet",
    "Stage",
    "pipeline",
    "artifact",
    "convergence report",
    "external calibration",
    "evidence packet",
    "runner",
    "controller",
    "validation gate",
]

GENERIC_RESIDUE_HEADINGS = [
    "用户画像与约束如何进入判断",
    "逐题回答",
    "证据支持",
    "合理推断",
    "前瞻假设",
    "情景分叉",
    "观察指标与反证信号",
    "最终决策含义",
    "证据边界",
]


def _write_stage_a_fixture(tmp_path: Path) -> dict[str, Path]:
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
    return {"run_dir": run_dir, "packet": packet}


def _contract(tmp_path: Path) -> dict:
    paths = _write_stage_a_fixture(tmp_path)
    return generate_decision_context_contract(
        original_query=ADHD_AI_QUERY,
        research_packet_path=paths["packet"],
    )


def _packet_with_contract(tmp_path: Path) -> dict:
    contract = _contract(tmp_path)
    return {
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


def _render(tmp_path: Path) -> tuple[str, dict]:
    packet = _packet_with_contract(tmp_path)
    text = _final_controller_report_from_packet(packet)
    return text, packet["decision_context_contract"]


def test_final_controller_receives_contract_from_decision_run_artifact(tmp_path):
    contract = _contract(tmp_path)
    decision_dir = tmp_path / "decision_run"
    write_decision_context_contract_artifacts(contract, base_dir=decision_dir)
    convergence = decision_dir / "convergence_report" / "convergence_report.md"
    calibration = decision_dir / "external_calibration" / "external_calibration.md"
    convergence.parent.mkdir(parents=True)
    calibration.parent.mkdir(parents=True)
    convergence.write_text("validated convergence text", encoding="utf-8")
    calibration.write_text("validated calibration text", encoding="utf-8")
    stages = [
        {"stage_name": "convergence_report", "owner": "R1", "model": "R1", "executor_model": "R1", "artifact_path": str(convergence)},
        {"stage_name": "external_calibration", "owner": "External", "model": "GPT", "executor_model": "GPT", "artifact_path": str(calibration)},
    ]

    packet = _decision_final_controller_packet(
        stages,
        query=ADHD_AI_QUERY,
        base_dir=decision_dir,
        decision_context_required=True,
    )

    assert packet["decision_context_contract"]["contract_id"] == contract["contract_id"]
    assert packet["decision_context_contract_path"].endswith("decision_context_contract/decision_context_contract.json")


def test_missing_contract_blocks_final_controller(tmp_path):
    packet = {
        "mode": ENGINE_DECISION,
        "query": ADHD_AI_QUERY,
        "decision_context_contract_required": True,
        "excerpts": {"convergence_report": "ok", "external_calibration": "ok"},
    }

    with pytest.raises(RuntimeError, match="FINAL_CONTROLLER_MISSING_DECISION_CONTEXT_CONTRACT"):
        _final_controller_report_from_packet(packet)


def test_final_report_sections_exactly_follow_contract(tmp_path):
    text, contract = _render(tmp_path)

    section_lines = [line.removeprefix("## ").strip() for line in text.splitlines() if line.startswith("## ")]
    assert section_lines == contract["user_output_contract"]["required_sections"]


def test_top5_item_fields_exactly_present(tmp_path):
    text, contract = _render(tmp_path)

    assert validate_final_report_contract_rendering(text, contract) == []
    assert text.count("当前优势 / 当前缺陷") >= 10
    assert text.count("触发条件") >= 10
    assert text.count("中间机制") >= 10
    assert text.count("反转后的陷阱 / 反转后的优势") >= 10
    assert text.count("失效条件") >= 10
    assert text.count("确定性等级") >= 10


def test_iq_bjj_moderators_retained_as_reasoning_modifiers(tmp_path):
    text, _contract = _render(tmp_path)

    assert text.count("IQ 124") >= 5
    assert text.count("长期柔术训练") >= 5
    assert text.count("调节变量") >= 2


def test_six_dimensions_retained(tmp_path):
    text, _contract = _render(tmp_path)

    for term in ["知识获取能力", "问题选择能力", "验证能力", "收束能力", "延迟反馈耐受", "身体反馈系统"]:
        assert term in text


def test_evidence_tiers_per_item_retained(tmp_path):
    text, _contract = _render(tmp_path)

    assert text.count("证据层级") >= 10
    assert "证据支持" in text
    assert "合理推断" in text
    assert "前瞻假设" in text


def test_internal_language_absent(tmp_path):
    text, _contract = _render(tmp_path)

    lowered = text.lower()
    for term in INTERNAL_TERMS:
        assert term.lower() not in lowered


def test_template_residue_absent(tmp_path):
    text, _contract = _render(tmp_path)

    for heading in GENERIC_RESIDUE_HEADINGS:
        assert f"## {heading}" not in text


def test_paragraph_only_fields_fail_contract_rendering(tmp_path):
    contract = _contract(tmp_path)
    bad = "\n".join(f"## {section}\n这里只写一段泛化文字，没有显式字段。" for section in contract["user_output_contract"]["required_sections"])

    errors = validate_final_report_contract_rendering(bad, contract)

    assert any(error.startswith("missing_item_field:未来优势变陷阱 Top5") for error in errors)


def test_dry_regeneration_from_contract_convergence_calibration_without_upstream_rerun(tmp_path):
    text, contract = _render(tmp_path)

    assert validate_final_report_contract_rendering(text, contract) == []
    assert "未来优势变陷阱 Top5" in text
    assert "未来缺陷变优势 Top5" in text
    upstream_rerun = False
    model_or_network_calls = []
    assert upstream_rerun is False
    assert model_or_network_calls == []
