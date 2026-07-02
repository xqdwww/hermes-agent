from pathlib import Path

from tools.task_engine_contracts import CANONICAL_STAGES, ENGINE_DECISION
from tools.task_engine_executors import (
    LocalTaskEngineExecutor,
    _decision_external_calibration_prompt,
    _decision_stage_prompt,
    _prepare_decision_context_contract,
    run_decision_full_real,
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
    assert "## convergence contract output schema" in prompt
    assert f"task_topic: {context['contract']['task_topic']['title']}" in prompt
    assert (
        "key_variables: ADHD 注意力波动; 兴趣驱动; 执行功能; 内在走神; "
        "AI 信息环境; 知识获取成本下降; 儿童长期发展"
    ) in prompt
    assert "evidence_tiers: evidence_supported / 证据支持" in prompt
    assert "plausible_inference / 合理推断" in prompt
    assert "forward_looking_hypothesis / 前瞻假设" in prompt
    assert "unsupported_or_speculative / 不支持或推测" in prompt


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


def _aligned_convergence_text(contract):
    return "\n".join(
        [
            f"decision_context_contract_id: {contract['contract_id']}",
            f"task_topic: {contract['task_topic']['title']}",
            "key_variables: ADHD 注意力波动, 兴趣驱动, 执行功能, 内在走神, AI 信息环境, 知识获取成本下降, 儿童长期发展",
            "moderator_variables: IQ 124, 长期柔术训练, 身体反馈系统",
            "required_dimensions: 知识获取能力, 问题选择能力, 验证能力, 收束能力, 延迟反馈耐受, 身体反馈系统",
            "user_output_contract_intent: 未来优势变陷阱 Top5; 未来缺陷变优势 Top5; danger_flag",
            "evidence_tiers: evidence_supported, plausible_inference, forward_looking_hypothesis, unsupported_or_speculative",
            "convergence: 结构性反转必须围绕 ADHD x AI 的用户决策问题，而不是执行准备。",
            "## key_drivers",
            "AI feedback cost, ADHD attention variability, IQ 124, and long-term BJJ body feedback.",
            "## mechanism_chain",
            "input variable -> mediating mechanism -> reversal result.",
            "## scenario_branches",
            "Scenario A keeps verification; Scenario B outsources verification.",
            "## counter_signals",
            "falsification_signals: observable signal shows no decline in validation behavior.",
            "## certainty_levels",
            "high / medium / low.",
            "## uncertainty_boundary",
            "evidence stops at current ADHD and learning-support research.",
        ]
    )


def test_convergence_contract_retry_regenerates_instead_of_reusing_stale_failed_output(tmp_path):
    paths, context = _contract_context(tmp_path)
    contract = context["contract"]
    convergence_prompts = []

    class FakeExecutor(LocalTaskEngineExecutor):
        def __init__(self):
            super().__init__()
            self.last_executor_models = {}

        def run_agy_gemini(self, stage, prompt, model):
            self.last_executor_models[stage.stage_name] = model
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            self.last_executor_models[stage.stage_name] = stage.model
            return [{"title": "ADHD AI structural reversal", "url": "https://example.test/adhd-ai"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = model
            if stage.stage_name == "evidence_judge":
                return "evidence_quality_map\nstrength_by_claim\napplicability_to_user_context\nuncertainty_and_limits"
            if stage.stage_name == "convergence_report":
                convergence_prompts.append(prompt)
                if len(convergence_prompts) == 1:
                    return "\n".join(
                        [
                            f"decision_context_contract_id: {contract['contract_id']}",
                            "missing topic and tiers",
                            "## key_drivers",
                            "AI feedback cost and ADHD attention variability.",
                            "## mechanism_chain",
                            "input variable -> mediating mechanism -> reversal result.",
                            "## scenario_branches",
                            "Scenario A; Scenario B.",
                            "## counter_signals",
                            "falsification_signals: observable signal.",
                            "## certainty_levels",
                            "high / medium / low.",
                            "## uncertainty_boundary",
                            "evidence stops at current ADHD and learning-support research.",
                        ]
                    )
                return _aligned_convergence_text(contract)
            return (
                "ADHD AI 结构性反转 IQ 124 长期柔术训练 身体反馈系统 "
                "知识获取能力 问题选择能力 验证能力 收束能力 延迟反馈耐受 "
                "evidence_supported plausible_inference forward_looking_hypothesis unsupported_or_speculative"
            )

        def run_external_calibration(self, stage, packet):
            self.last_executor_models[stage.stage_name] = "GPT Bridge"
            return "calibration_verdict: production readiness and pipeline execution are calibrated."

    result = run_decision_full_real(
        ADHD_AI_QUERY,
        base_dir=tmp_path / "decision_run",
        executor=FakeExecutor(),
        research_packet_path=paths["packet"],
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "external_calibration"
    assert len(convergence_prompts) == 2
    assert "Contract retry instructions" in convergence_prompts[1]
    assert (
        "key_variables: ADHD 注意力波动; 兴趣驱动; 执行功能; 内在走神; "
        "AI 信息环境; 知识获取成本下降; 儿童长期发展"
    ) in convergence_prompts[1]
    invalid_path = tmp_path / "decision_run" / "convergence_report" / "convergence_report.contract_retry_source.invalid.md"
    convergence_path = tmp_path / "decision_run" / "convergence_report" / "convergence_report.md"
    assert invalid_path.exists()
    assert convergence_path.exists()
    convergence_text = convergence_path.read_text(encoding="utf-8")
    assert "missing topic and tiers" not in convergence_text
    assert f"task_topic: {contract['task_topic']['title']}" in convergence_text
    assert "evidence_tiers: evidence_supported" in convergence_text
