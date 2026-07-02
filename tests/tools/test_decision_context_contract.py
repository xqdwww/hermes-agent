from pathlib import Path

from tools.decision_context_contract import (
    DEFAULT_EVIDENCE_TIERS,
    DEFAULT_FORBIDDEN_INTERNAL_TERMS,
    RUNTIME_INTEGRATION_ENABLED,
    compute_contract_hash,
    generate_decision_context_contract,
    normalize_convergence_contract_output,
    render_convergence_contract_preamble,
    split_convergence_contract_preamble,
    validate_calibration_object,
    validate_contract_schema,
    validate_convergence_contract_alignment,
    validate_evidence_tiers_present,
    validate_no_meta_execution_drift,
    validate_provenance,
    validate_required_dimensions_present,
    validate_required_fields,
    validate_required_variables_present,
)


ADHD_AI_QUERY = """
AI 信息环境下，ADHD 儿童特征的未来结构性反转与长期发展决策。

背景：
男孩，7岁半，IQ 124，明显 ADHD 倾向，注意力波动、兴趣驱动、内在走神明显，长期柔术训练。
未来10年 AI 持续降低知识获取、解释、反馈、规划和个性化学习成本。

核心问题：
1. 哪些今天被认为是 ADHD 的优势，未来会变成陷阱？
2. 哪些今天被认为是 ADHD 的缺陷，未来会变成优势？

必须关注：
ADHD 注意力波动、兴趣驱动、执行功能、内在走神、AI 信息环境、知识获取成本下降、儿童长期发展、
IQ 124、长期柔术训练、知识获取能力、问题选择能力、验证能力、收束能力、延迟反馈耐受、身体反馈系统。

最终输出必须包含：
未来优势变陷阱 Top5
未来缺陷变优势 Top5
最危险的错误培养路径
最反直觉但值得追踪的假设
danger_flag

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
                "",
                "# ADHD x AI evidence packet",
                "",
                "evidence_supported: ADHD 注意力波动 and executive function constraints.",
                "plausible_inference: IQ 124 changes validation load under AI information environments.",
                "forward_looking_hypothesis: 长期柔术训练 may moderate 身体反馈系统 and 延迟反馈耐受.",
            ]
        ),
        encoding="utf-8",
    )
    sources.write_text("source_id,title,url\nS1,ADHD and AI,https://example.test/source\n", encoding="utf-8")
    evidence.write_text("evidence_id,source_id,claim_id,evidence_tier\nE1,S1,C1,evidence_supported\n", encoding="utf-8")
    claims.write_text(
        "# Claims\n\n- ADHD 注意力波动\n- 兴趣驱动\n- 执行功能\n- 内在走神\n"
        "- AI 信息环境\n- 知识获取成本下降\n- 儿童长期发展\n"
        "- 知识获取能力\n- 问题选择能力\n- 验证能力\n- 收束能力\n- 延迟反馈耐受\n- 身体反馈系统\n",
        encoding="utf-8",
    )
    gaps.write_text("# Gaps\n\n- full text gap remains visible.\n", encoding="utf-8")
    return {
        "run_dir": run_dir,
        "packet": packet,
        "sources": sources,
        "evidence": evidence,
        "claims": claims,
        "gaps": gaps,
    }


def _generate(tmp_path: Path):
    paths = _write_stage_a_fixture(tmp_path)
    return generate_decision_context_contract(
        original_query=ADHD_AI_QUERY,
        research_packet_path=paths["packet"],
    )


def test_adhd_ai_contract_contains_required_five_sections(tmp_path):
    contract = _generate(tmp_path)

    sections = contract["user_output_contract"]["required_sections"]
    assert sections == [
        "未来优势变陷阱 Top5",
        "未来缺陷变优势 Top5",
        "最危险的错误培养路径",
        "最反直觉但值得追踪的假设",
        "danger_flag",
    ]
    assert validate_required_fields(contract) == []


def test_adhd_structural_reversal_brief_query_gets_required_five_sections(tmp_path):
    paths = _write_stage_a_fixture(tmp_path)
    contract = generate_decision_context_contract(
        original_query="AI 信息环境下，ADHD 儿童特征的未来结构性反转与长期发展决策",
        research_packet_path=paths["packet"],
    )

    assert contract["user_output_contract"]["required_sections"] == [
        "未来优势变陷阱 Top5",
        "未来缺陷变优势 Top5",
        "最危险的错误培养路径",
        "最反直觉但值得追踪的假设",
        "danger_flag",
    ]
    assert validate_required_fields(contract) == []


def test_adhd_structural_reversal_brief_query_gets_six_ability_dimensions(tmp_path):
    paths = _write_stage_a_fixture(tmp_path)
    contract = generate_decision_context_contract(
        original_query="AI 信息环境下，ADHD 儿童特征的未来结构性反转与长期发展决策",
        research_packet_path=paths["packet"],
    )

    labels = {dimension["label"] for dimension in contract["required_dimensions"]}
    assert {
        "知识获取能力",
        "问题选择能力",
        "验证能力",
        "收束能力",
        "延迟反馈耐受",
        "身体反馈系统",
    } <= labels
    assert validate_required_fields(contract) == []


def test_generic_alternatives_stakeholders_are_not_required_for_adhd_structural_reversal(tmp_path):
    paths = _write_stage_a_fixture(tmp_path)
    contract = generate_decision_context_contract(
        original_query="AI 信息环境下，ADHD 儿童特征的未来结构性反转与长期发展决策",
        research_packet_path=paths["packet"],
    )

    sections = set(contract["user_output_contract"]["required_sections"])
    assert not (sections & {"Alternatives", "Evaluation Criteria", "Stakeholders"})


def test_generic_decision_without_output_contract_uses_generic_fallback_schema(tmp_path):
    missing_packet = tmp_path / "missing" / "research_evidence_packet.md"
    contract = generate_decision_context_contract(
        original_query="This is a decision task: should we choose option A or option B?",
        research_packet_path=missing_packet,
    )

    assert contract["user_output_contract"]["required_sections"] == [
        "Alternatives",
        "Evaluation Criteria",
        "Stakeholders",
        "Recommendation",
        "Risks and Uncertainties",
    ]
    dimension_labels = {dimension["label"] for dimension in contract["required_dimensions"]}
    assert {"Alternatives", "Evaluation Criteria", "Stakeholders"} <= dimension_labels
    assert "missing_required_sections" not in validate_required_fields(contract)
    assert "missing_required_dimensions" not in validate_required_fields(contract)


def test_top5_item_fields_enter_contract(tmp_path):
    contract = _generate(tmp_path)

    field_ids = {field["id"] for field in contract["user_output_contract"]["required_item_fields"]}
    assert {
        "current_advantage_or_defect",
        "trigger_condition",
        "mediating_mechanism",
        "reversal_outcome",
        "failure_condition",
        "certainty_level",
        "evidence_tier",
    } <= field_ids


def test_iq_124_and_bjj_enter_moderator_variables(tmp_path):
    contract = _generate(tmp_path)

    labels = {moderator["label"] for moderator in contract["moderator_variables"]}
    assert "IQ 124" in labels
    assert "长期柔术训练" in labels


def test_six_ability_dimensions_enter_required_dimensions(tmp_path):
    contract = _generate(tmp_path)

    labels = {dimension["label"] for dimension in contract["required_dimensions"]}
    assert {
        "知识获取能力",
        "问题选择能力",
        "验证能力",
        "收束能力",
        "延迟反馈耐受",
        "身体反馈系统",
    } <= labels


def test_evidence_tiers_and_claim_strength_policy_enter_contract(tmp_path):
    contract = _generate(tmp_path)

    assert contract["evidence_tiers"]["allowed"] == DEFAULT_EVIDENCE_TIERS
    assert contract["evidence_tiers"]["required_per_core_item"] is True
    assert contract["claim_strength_policy"]["snippet_only_sources_must_be_low_or_conditional"] is True
    assert contract["claim_strength_policy"]["full_text_gap_must_remain_visible"] is True


def test_forbidden_content_and_internal_terms_enter_contract(tmp_path):
    contract = _generate(tmp_path)

    forbidden_labels = {item["label"] for item in contract["forbidden_content"]}
    assert {"医学诊断", "治疗建议", "家长建议", "培养计划"} <= forbidden_labels
    assert set(DEFAULT_FORBIDDEN_INTERNAL_TERMS) <= set(contract["forbidden_internal_terms"])


def test_provenance_contains_packet_hash_run_id_artifact_dir_and_l2_5_paths(tmp_path):
    paths = _write_stage_a_fixture(tmp_path)
    contract = generate_decision_context_contract(
        original_query=ADHD_AI_QUERY,
        research_packet_path=paths["packet"],
    )
    provenance = contract["source_provenance"]

    assert provenance["research_packet_path"] == str(paths["packet"])
    assert provenance["research_packet_hash"].startswith("sha256:")
    assert provenance["stage_a_run_id"] == "1782891050_research_research_l1_l5"
    assert provenance["stage_a_artifact_dir"] == str(paths["run_dir"])
    assert provenance["l2_5_sources_path"] == str(paths["sources"])
    assert provenance["l2_5_evidence_path"] == str(paths["evidence"])
    assert provenance["l2_5_claims_path"] == str(paths["claims"])
    assert provenance["l2_5_gaps_path"] == str(paths["gaps"])
    assert validate_provenance(contract) == []


def test_missing_packet_path_warns_and_fails_provenance(tmp_path):
    missing_packet = tmp_path / "missing" / "research_evidence_packet.md"

    contract = generate_decision_context_contract(
        original_query=ADHD_AI_QUERY,
        research_packet_path=missing_packet,
    )

    assert "research_packet_missing" in contract["contract_warnings"]
    errors = validate_provenance(contract)
    assert "missing_provenance:research_packet_hash" in errors
    assert "missing_provenance_file:research_packet_path" in errors


def test_same_input_produces_same_contract_hash(tmp_path):
    paths = _write_stage_a_fixture(tmp_path)

    contract_a = generate_decision_context_contract(
        original_query=ADHD_AI_QUERY,
        research_packet_path=paths["packet"],
    )
    contract_b = generate_decision_context_contract(
        original_query=ADHD_AI_QUERY,
        research_packet_path=paths["packet"],
    )

    assert contract_a == contract_b
    assert contract_a["contract_id"] == contract_b["contract_id"]
    assert contract_a["contract_id"] == compute_contract_hash(contract_a)


def test_generator_does_not_need_external_calls(monkeypatch, tmp_path):
    import socket

    def fail_network(*_args, **_kwargs):
        raise AssertionError("network call attempted")

    monkeypatch.setattr(socket, "create_connection", fail_network)

    contract = _generate(tmp_path)

    assert validate_contract_schema(contract) == []


def test_generator_does_not_modify_input_artifacts(tmp_path):
    paths = _write_stage_a_fixture(tmp_path)
    tracked = [paths["packet"], paths["sources"], paths["evidence"], paths["claims"], paths["gaps"]]
    before = {path: (path.stat().st_mtime_ns, path.read_bytes()) for path in tracked}

    generate_decision_context_contract(
        original_query=ADHD_AI_QUERY,
        research_packet_path=paths["packet"],
    )

    after = {path: (path.stat().st_mtime_ns, path.read_bytes()) for path in tracked}
    assert after == before


def test_phase1_does_not_integrate_with_runner_runtime():
    assert RUNTIME_INTEGRATION_ENABLED is False


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
        ]
    )


def _semantic_convergence_body():
    return "\n".join(
        [
            "## semantic_contract_coverage",
            "- key_variable ADHD 注意力波动: ADHD 注意力波动决定AI反馈密度何时帮助聚焦、何时放大切换。",
            "- key_variable 兴趣驱动: 兴趣驱动会把低成本知识探索推向高价值问题或低价值漫游。",
            "- key_variable 执行功能: 执行功能决定能否从AI生成内容中形成闭环。",
            "- key_variable 内在走神: 内在走神会影响问题重组，也可能削弱收束。",
            "- key_variable AI 信息环境: AI 信息环境降低反馈成本，也放大选择和验证负担。",
            "- key_variable 知识获取成本下降: 知识获取成本下降把瓶颈从获取转向选择、验证和收束。",
            "- key_variable 儿童长期发展: 儿童长期发展需要看十年尺度的能力迁移，而非短期表现。",
            "- moderator IQ 124: IQ 124 调节抽象吸收速度和验证负荷。",
            "- moderator 长期柔术训练: 长期柔术训练通过身体反馈系统调节延迟反馈耐受。",
            "- required_dimension 知识获取能力: 知识获取能力会从找资料转向筛选和整合。",
            "- required_dimension 问题选择能力: 问题选择能力决定探索是否变成低价值漫游。",
            "- required_dimension 验证能力: 验证能力约束AI幻觉和自我确认。",
            "- required_dimension 收束能力: 收束能力决定是否能从多路径中完成一个路径。",
            "- required_dimension 延迟反馈耐受: 延迟反馈耐受决定是否能承受慢变量学习。",
            "- required_dimension 身体反馈系统: 身体反馈系统提供非数字化的校准信号。",
            "evidence_tiers: evidence_supported, plausible_inference, forward_looking_hypothesis, unsupported_or_speculative",
            "## key_drivers",
            "ADHD x AI structural reversal remains centered on the user decision.",
        ]
    )


def test_convergence_deterministic_contract_header_and_valid_body_passes(tmp_path):
    contract = _generate(tmp_path)
    normalized, errors = normalize_convergence_contract_output(_semantic_convergence_body(), contract)

    assert errors == []
    assert validate_convergence_contract_alignment(normalized, contract) == []
    preamble, body = split_convergence_contract_preamble(normalized)
    assert contract["contract_id"] in preamble
    assert contract["task_topic"]["title"] in preamble
    assert "moderator_variables: IQ 124; 长期柔术训练" in preamble
    assert "儿童长期发展" in body


def test_convergence_header_only_does_not_satisfy_semantic_body(tmp_path):
    contract = _generate(tmp_path)
    text = render_convergence_contract_preamble(contract) + "\n\n## body\nOnly generic synthesis."

    errors = validate_convergence_contract_alignment(text, contract)

    assert "missing_key_variable:child_long_term_development" in errors
    assert "missing_required_dimension:problem_selection_ability" in errors


def test_convergence_body_missing_key_variable_blocks_even_with_header(tmp_path):
    contract = _generate(tmp_path)
    body = _semantic_convergence_body().replace("儿童长期发展", "成长轨迹")
    text = render_convergence_contract_preamble(contract) + "\n\n" + body

    errors = validate_convergence_contract_alignment(text, contract)

    assert "missing_key_variable:child_long_term_development" in errors


def test_convergence_body_missing_required_dimension_blocks_even_with_header(tmp_path):
    contract = _generate(tmp_path)
    body = _semantic_convergence_body().replace("问题选择能力", "选题偏好")
    text = render_convergence_contract_preamble(contract) + "\n\n" + body

    errors = validate_convergence_contract_alignment(text, contract)

    assert "missing_required_dimension:problem_selection_ability" in errors


def test_convergence_body_missing_moderator_blocks_even_with_header(tmp_path):
    contract = _generate(tmp_path)
    body = _semantic_convergence_body().replace("IQ 124", "高抽象能力")
    text = render_convergence_contract_preamble(contract) + "\n\n" + body

    errors = validate_convergence_contract_alignment(text, contract)

    assert "missing_moderator_variable:iq_124" in errors


def test_convergence_normalizer_rejects_contradictory_model_metadata(tmp_path):
    contract = _generate(tmp_path)
    raw = "\n".join(
        [
            f"decision_context_contract_id: {contract['contract_id']}",
            "task_topic: unrelated rollout readiness",
            _semantic_convergence_body(),
        ]
    )

    _normalized, errors = normalize_convergence_contract_output(raw, contract)

    assert "contradictory_contract_metadata:task_topic" in errors


def test_convergence_normalizer_preserves_canonical_contract_fields_for_generic_contract(tmp_path):
    missing_packet = tmp_path / "missing.md"
    contract = generate_decision_context_contract(
        original_query="This is a decision task: should we choose option A or option B?",
        research_packet_path=missing_packet,
    )
    body = "Alternatives and Evaluation Criteria shape the recommendation. Stakeholders remain relevant."
    normalized, errors = normalize_convergence_contract_output(body, contract)

    assert errors == []
    preamble, _body = split_convergence_contract_preamble(normalized)
    assert contract["contract_id"] in preamble
    assert "Alternatives" in preamble
    assert "Evaluation Criteria" in preamble
    assert "ADHD" not in preamble


def test_convergence_with_adhd_ai_contract_content_passes(tmp_path):
    contract = _generate(tmp_path)

    assert validate_convergence_contract_alignment(_aligned_convergence_text(contract), contract) == []


def test_convergence_missing_child_long_term_development_blocks(tmp_path):
    contract = _generate(tmp_path)
    text = _aligned_convergence_text(contract).replace("儿童长期发展", "成长路径")

    errors = validate_required_variables_present(text, contract)

    assert "missing_key_variable:child_long_term_development" in errors


def test_convergence_containing_child_long_term_development_passes_key_variable_check(tmp_path):
    contract = _generate(tmp_path)

    assert "missing_key_variable:child_long_term_development" not in validate_required_variables_present(
        _aligned_convergence_text(contract),
        contract,
    )


def test_convergence_missing_task_topic_blocks(tmp_path):
    contract = _generate(tmp_path)
    text = _aligned_convergence_text(contract).replace(
        f"task_topic: {contract['task_topic']['title']}",
        "task_topic: generic ADHD and AI essay",
    )

    assert "missing_task_topic" in validate_convergence_contract_alignment(text, contract)


def test_convergence_with_execution_readiness_meta_content_blocks(tmp_path):
    contract = _generate(tmp_path)
    text = (
        f"decision_context_contract_id: {contract['contract_id']}\n"
        "production readiness and schema rollout are ready. "
        "pipeline execution, task-engine implementation, tool availability, and pilot rollout should proceed."
    )

    errors = validate_no_meta_execution_drift(text, contract)

    assert any(error.startswith("meta_execution_drift") for error in errors)


def test_missing_iq_124_moderator_blocks_for_adhd_contract(tmp_path):
    contract = _generate(tmp_path)
    text = _aligned_convergence_text(contract).replace("IQ 124, ", "")

    errors = validate_required_variables_present(text, contract)

    assert "missing_moderator_variable:iq_124" in errors


def test_missing_bjj_body_feedback_moderator_blocks_for_adhd_contract(tmp_path):
    contract = _generate(tmp_path)
    text = _aligned_convergence_text(contract).replace("长期柔术训练, ", "")

    errors = validate_required_variables_present(text, contract)

    assert "missing_moderator_variable:long_term_bjj_training" in errors


def test_missing_six_ability_dimensions_block(tmp_path):
    contract = _generate(tmp_path)
    text = (
        _aligned_convergence_text(contract)
        .replace("身体反馈系统", "身体调节变量")
        .replace(
            "知识获取能力, 问题选择能力, 验证能力, 收束能力, 延迟反馈耐受, 身体调节变量",
            "只保留主题，不列维度",
        )
    )

    errors = validate_required_dimensions_present(text, contract)

    assert "missing_required_dimension:knowledge_acquisition_ability" in errors
    assert "missing_required_dimension:problem_selection_ability" in errors
    assert "missing_required_dimension:validation_ability" in errors
    assert "missing_required_dimension:convergence_ability" in errors
    assert "missing_required_dimension:delayed_feedback_tolerance" in errors
    assert "missing_required_dimension:body_feedback_system" in errors


def test_missing_evidence_tiers_blocks(tmp_path):
    contract = _generate(tmp_path)
    text = _aligned_convergence_text(contract).replace(
        "evidence_tiers: evidence_supported, plausible_inference, forward_looking_hypothesis, unsupported_or_speculative",
        "evidence_tiers: absent",
    )

    assert "missing_evidence_tiers" in validate_evidence_tiers_present(text, contract)


def test_calibration_of_adhd_ai_convergence_passes(tmp_path):
    contract = _generate(tmp_path)
    text = _aligned_convergence_text(contract) + "\ncalibration_verdict: calibrated against user decision evidence strength."

    assert validate_calibration_object(text, contract) == []


def test_calibration_of_pipeline_readiness_blocks(tmp_path):
    contract = _generate(tmp_path)
    text = (
        f"decision_context_contract_id: {contract['contract_id']}\n"
        "calibration_verdict: production readiness, schema readiness, pipeline execution, and tool availability are calibrated."
    )

    errors = validate_calibration_object(text, contract)

    assert any(error.startswith("meta_execution_drift") for error in errors)
