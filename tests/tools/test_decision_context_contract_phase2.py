from pathlib import Path

from tools.task_engine_contracts import CANONICAL_STAGES, ENGINE_DECISION
from tools.task_engine_executors import (
    _decision_external_calibration_prompt,
    _decision_stage_prompt,
    _prepare_decision_context_contract,
)
from tools.task_engine_runner import _decision_full_real_dry_intercept_response


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


def _write_stage_a_fixture(tmp_path: Path) -> dict[str, Path]:
    run_dir = tmp_path / ".hermes_task_engine_runs" / "1782891050_research_research_l1_l5"
    l5_dir = run_dir / "L5_deepseek_acceptance"
    l2_5_dir = run_dir / "L2_5_codex_evidence_organizer"
    l5_dir.mkdir(parents=True)
    l2_5_dir.mkdir(parents=True)
    packet = l5_dir / "research_evidence_packet.md"
    sources = l2_5_dir / "sources.csv"
    evidence = l2_5_dir / "evidence.csv"
    claims = l2_5_dir / "claims.md"
    gaps = l2_5_dir / "gaps.md"
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
    sources.write_text("source_id,title,url\nS1,ADHD and AI,https://example.test/source\n", encoding="utf-8")
    evidence.write_text("evidence_id,source_id,claim_id,evidence_tier\nE1,S1,C1,evidence_supported\n", encoding="utf-8")
    claims.write_text(
        "ADHD 注意力波动\n兴趣驱动\n执行功能\n内在走神\nAI 信息环境\n知识获取成本下降\n儿童长期发展\n"
        "知识获取能力\n问题选择能力\n验证能力\n收束能力\n延迟反馈耐受\n身体反馈系统\n",
        encoding="utf-8",
    )
    gaps.write_text("full text evidence gap remains visible.\n", encoding="utf-8")
    return {"run_dir": run_dir, "packet": packet}


def _contract_context(tmp_path: Path):
    paths = _write_stage_a_fixture(tmp_path)
    context = _prepare_decision_context_contract(
        query=ADHD_AI_QUERY,
        research_packet_path=paths["packet"],
        base_dir=tmp_path / "decision_run",
    )
    return paths, context


def test_decision_full_input_prep_creates_contract_artifact_from_stage_a_packet(tmp_path):
    paths, context = _contract_context(tmp_path)

    json_path = Path(context["decision_context_contract_json_path"])
    md_path = Path(context["decision_context_contract_md_path"])

    assert json_path.exists()
    assert md_path.exists()
    assert context["contract"]["source_provenance"]["research_packet_path"] == str(paths["packet"])
    assert context["contract"]["source_provenance"]["stage_a_artifact_dir"] == str(paths["run_dir"])


def test_convergence_prompt_input_includes_contract(tmp_path):
    _paths, context = _contract_context(tmp_path)
    stage = CANONICAL_STAGES[ENGINE_DECISION][7]

    prompt = _decision_stage_prompt(
        stage,
        [],
        query=ADHD_AI_QUERY,
        base_dir=tmp_path / "decision_run",
        research_packet_path=context["contract"]["source_provenance"]["research_packet_path"],
        decision_context_contract=context["contract"],
    )

    assert "## decision_context_contract" in prompt
    assert context["contract_id"] in prompt
    assert "AI 信息环境下 ADHD 儿童特征结构性反转" in prompt
    assert "IQ 124" in prompt
    assert "长期柔术训练" in prompt
    assert "知识获取能力" in prompt


def test_external_calibration_prompt_input_includes_contract(tmp_path):
    _paths, context = _contract_context(tmp_path)

    prompt = _decision_external_calibration_prompt(
        [],
        query=ADHD_AI_QUERY,
        base_dir=tmp_path / "decision_run",
        research_packet_path=context["contract"]["source_provenance"]["research_packet_path"],
        decision_context_contract=context["contract"],
    )

    assert "## decision_context_contract" in prompt
    assert context["contract_id"] in prompt
    assert "Do not switch the object of analysis to pipeline execution" in prompt


def test_decision_dry_intercept_generates_contract_and_enables_checks(tmp_path):
    paths = _write_stage_a_fixture(tmp_path)

    payload = _decision_full_real_dry_intercept_response(
        artifact_dir=tmp_path / "decision_dry",
        query=ADHD_AI_QUERY,
        research_packet_path=str(paths["packet"]),
    )

    assert payload["decision_context_contract_generated"] is True
    assert Path(payload["decision_context_contract_path"]).exists()
    assert payload["convergence_receives_decision_context_contract"] is True
    assert payload["external_calibration_receives_decision_context_contract"] is True
    assert payload["meta_drift_checks_enabled"] is True
    assert payload["real_executor_calls"] == []
    assert payload["model_or_network_calls"] == []
