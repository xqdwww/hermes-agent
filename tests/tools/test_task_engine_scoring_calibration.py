from __future__ import annotations

from pathlib import Path

from tools import task_engine_scoring_calibration as calibration
from tools import task_engine_executors as executors
from tools.task_engine_contracts import CANONICAL_STAGES, ENGINE_RESEARCH_DECISION


VALID_FINAL_REPORT = "\n".join(
    [
        "# 研究决策最终报告",
        "",
        "## 核心结论",
        "结论保持条件化，只在当前证据边界内使用。",
        "",
        "## 证据强度、争议和缺口",
        "evidence_strength: strong for bounded current evidence; medium for mechanism transfer; weak for long-horizon extrapolation.",
        "controversy: applicability depends on organizational context, governance, and measurement choices.",
        "evidence_gap: direct longitudinal evidence for the exact future scenario remains unavailable.",
        "",
        "## 证据分层",
        "### evidence_supported",
        "判断：当前材料只支持边界清楚的低风险结论。",
        "触发条件：证据来源、适用场景和反证信号都可复核。",
        "中间机制：输入变量是可靠证据；中介机制是校准；输出变量是条件化判断。",
        "失效条件或反证信号：如果关键材料缺失，则不得升级为确定建议。",
        "certainty_level：medium",
        "evidence_tier：evidence_supported",
        "decision_use：只用于限定判断范围。",
        "",
        "### reasonable_inference",
        "判断：可以做有限推断，但必须保留条件。",
        "触发条件：当前证据和任务场景一致。",
        "中间机制：输入变量是证据；中介机制是推断；输出变量是可执行边界。",
        "失效条件或反证信号：如果场景不一致，则降级。",
        "certainty_level：medium",
        "evidence_tier：reasonable_inference",
        "decision_use：用于制定下一步验证。",
        "",
        "### foresight_hypothesis",
        "判断：长期判断只是追踪假设。",
        "触发条件：未来变量持续变化。",
        "中间机制：输入变量是趋势；中介机制是不确定性；输出变量是假设。",
        "失效条件或反证信号：若反证信号出现，则撤回。",
        "certainty_level：low",
        "evidence_tier：foresight_hypothesis",
        "decision_use：不得当成生产结论。",
    ]
)


def _packet(query: str) -> dict:
    return {
        "mode": ENGINE_RESEARCH_DECISION,
        "query": query,
        "output_quality_profile": [executors.PROFILE_EVIDENCE_GROUNDED],
        "excerpts": {
            "L5_deepseek_acceptance": "evidence packet",
            "convergence_report": "convergence report",
            "external_calibration": "calibration verdict",
        },
    }


def _packet_with_current_run_trace(tmp_path: Path) -> dict:
    base_dir = tmp_path / "current_run"
    base_dir.mkdir()
    trace = []
    for index, spec in enumerate(CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][:-1], start=1):
        artifact = base_dir / spec.stage_name / "artifact.md"
        artifact.parent.mkdir()
        artifact.write_text("ok", encoding="utf-8")
        trace.append(
            {
                "stage_name": spec.stage_name,
                "artifact_path": str(artifact.relative_to(base_dir)),
                "created_in_current_run": True,
                "legacy_contaminated": False,
                "valid_for_pipeline": True,
                "stage_index": index,
            }
        )
    packet = _packet("普通研究决策任务")
    packet["base_dir"] = str(base_dir)
    packet["stage_trace"] = trace
    return packet


def test_old_5_baseline_compatibility_uses_sample_independent_rules():
    queries = [
        "ADHD 儿童最新研究进展和治疗方案，需要判断主动干预程度。",
        "未来10年 AI 降低法律检索和合同起草成本后，法律角色是否结构性反转？",
        "未来10年 AI 降低审计底稿和合规报告成本后，审计角色是否结构性反转？",
        "一家工业服务公司是否应该进入越南北部电动车电池回收产业链？",
        "SaaS 数据平台是否应该从 PostgreSQL 单体迁移到事件驱动 lakehouse？",
    ]

    for query in queries:
        executors._assert_final_controller_packet_quality(_packet(query), VALID_FINAL_REPORT)
        result = calibration.assess_final_controller_packet(_packet(query), VALID_FINAL_REPORT)
        assert result.passed


def test_round2_generalization_compatibility_preserves_distinct_buckets():
    legal_packet = {
        "mode": ENGINE_RESEARCH_DECISION,
        "query": "未来10年 AI 降低法律检索、合同起草、案例摘要和合规解释成本后，初级律师和企业法务分析师是否结构性反转？",
        "output_quality_profile": [
            executors.PROFILE_EVIDENCE_GROUNDED,
            executors.PROFILE_FORESIGHT_MECHANISM,
        ],
        "excerpts": {
            "L5_deepseek_acceptance": "legal evidence packet",
            "convergence_report": "mechanism_chain supports partial reversal",
            "external_calibration": "Final calibration sentence: partial reversal is plausible; broad reversal is speculative.",
        },
    }
    audit_packet = {
        **legal_packet,
        "query": "未来10年 AI 降低审计底稿整理、财务异常检测、合规报告生成和管理层讨论分析草稿成本后，初级审计员和企业财务分析师是否结构性反转？",
        "excerpts": {
            "L5_deepseek_acceptance": "audit finance evidence packet",
            "convergence_report": "mechanism_chain supports audit finance role shift",
            "external_calibration": "职业整体反转证据不足，应降调为条件性判断。",
        },
    }
    vietnam_packet = {
        "mode": ENGINE_RESEARCH_DECISION,
        "query": "未来 3 年，一家中型工业服务公司是否应该进入越南北部电动车电池回收与梯次利用产业链？",
        "output_quality_profile": [executors.PROFILE_EVIDENCE_GROUNDED],
        "excerpts": {
            "L5_deepseek_acceptance": "market and regulatory evidence.",
            "convergence_report": "entry should be staged and conditional.",
            "external_calibration": "calibration_verdict: plausible only as pilot entry; not full heavy-asset entry.",
        },
    }

    legal_text = executors._final_controller_report_from_packet(legal_packet)
    audit_text = executors._final_controller_report_from_packet(audit_packet)
    vietnam_text = executors._final_controller_report_from_packet(vietnam_packet)

    assert calibration.classify_compliance_domain(legal_packet["query"]) == "legal_compliance"
    assert calibration.classify_compliance_domain(audit_packet["query"]) == "audit_finance_compliance"
    assert "初级律师" in legal_text
    assert "初级审计员" in audit_text
    assert "律师" not in audit_text
    assert "越南北部电动车电池回收" in vietnam_text
    for text, packet in ((legal_text, legal_packet), (audit_text, audit_packet), (vietnam_text, vietnam_packet)):
        executors._assert_final_controller_packet_quality(packet, text)


def test_stale_final_negative_blocks_raw_or_old_run_artifact_dump():
    stale_final = VALID_FINAL_REPORT + "\n\nartifact_path: /tmp/old_run/final_controller_report/final_decision_report.md\ncreated_in_current_run: false"

    result = calibration.assess_final_controller_text(stale_final, query="普通研究决策任务")

    assert result.blocked
    assert result.reason in {"stale_final_or_raw_intermediate_dump", "stale_final_old_run_path"}


def test_stale_decision_negative_blocks_non_current_stage(tmp_path: Path):
    outside = tmp_path / "outside" / "external_calibration.md"
    outside.parent.mkdir()
    outside.write_text("stale", encoding="utf-8")
    stage_records = [
        {
            "stage_name": "external_calibration",
            "artifact_path": str(outside),
            "created_in_current_run": False,
            "legacy_contaminated": False,
            "valid_for_pipeline": True,
            "outputs": {},
        }
    ]

    result = calibration.assess_stage_freshness(stage_records, base_dir=tmp_path / "current")

    assert result.blocked
    assert result.reason == "stale_decision_not_current_run"


def test_final_controller_current_run_stage_trace_passes(tmp_path: Path):
    packet = _packet_with_current_run_trace(tmp_path)

    result = calibration.assess_final_controller_packet(packet, VALID_FINAL_REPORT)

    assert result.passed


def test_final_controller_missing_current_run_metadata_still_blocks(tmp_path: Path):
    packet = _packet_with_current_run_trace(tmp_path)
    del packet["stage_trace"][0]["created_in_current_run"]

    result = calibration.assess_final_controller_packet(packet, VALID_FINAL_REPORT)

    assert result.blocked
    assert result.reason == "stale_decision_not_current_run"
    assert result.details == ("L1_gemini_search",)


def test_final_controller_false_current_run_metadata_still_blocks(tmp_path: Path):
    packet = _packet_with_current_run_trace(tmp_path)
    packet["stage_trace"][0]["created_in_current_run"] = False

    result = calibration.assess_final_controller_packet(packet, VALID_FINAL_REPORT)

    assert result.blocked
    assert result.reason == "stale_decision_not_current_run"


def test_final_controller_legacy_contaminated_metadata_still_blocks(tmp_path: Path):
    packet = _packet_with_current_run_trace(tmp_path)
    packet["stage_trace"][0]["legacy_contaminated"] = True

    result = calibration.assess_final_controller_packet(packet, VALID_FINAL_REPORT)

    assert result.blocked
    assert result.reason == "stale_decision_legacy_contaminated"


def test_final_controller_artifact_outside_current_run_still_blocks(tmp_path: Path):
    packet = _packet_with_current_run_trace(tmp_path)
    outside = tmp_path / "other_run" / "artifact.md"
    outside.parent.mkdir()
    outside.write_text("old", encoding="utf-8")
    packet["stage_trace"][0]["artifact_path"] = str(outside)

    result = calibration.assess_final_controller_packet(packet, VALID_FINAL_REPORT)

    assert result.blocked
    assert result.reason == "stale_decision_path_outside_current_run"


def test_legal_compliance_misbucket_regression_keeps_audit_finance_out_of_legal():
    assert calibration.classify_compliance_domain(
        "未来10年 AI 降低审计底稿整理、财务异常检测、合规报告生成和管理层讨论分析草稿成本"
    ) == "audit_finance_compliance"
    assert calibration.classify_compliance_domain(
        "未来10年 AI 降低法律检索、合同起草、案例摘要和合规解释成本"
    ) == "legal_compliance"
    assert calibration.classify_compliance_domain("普通安全合规运营流程是否应该自动化？") == "general_compliance"


def test_production_readiness_over_broad_regression_blocks_unbounded_pass():
    over_broad = "\n".join(
        [
            "# Final",
            "production_readiness: PASS",
            "ready for production without further review",
            "source_consumption_check: research_evidence_packet=yes; convergence_report=no; external_calibration=no",
        ]
    )

    result = calibration.assess_final_controller_text(
        over_broad,
        query="法律检索、合同起草和合规解释系统是否可以上线？",
    )

    assert result.blocked
    assert result.reason == "production_readiness_over_broad"
