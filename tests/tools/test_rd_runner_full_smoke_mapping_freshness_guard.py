from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.task_engine_runner as runner
import tools.task_engine_executors as executors
from tools.task_engine_contracts import (
    CANONICAL_STAGES,
    ENGINE_RESEARCH,
    ENGINE_RESEARCH_DECISION,
    PIPELINE_BLOCKED,
    PIPELINE_COMPLETE,
    make_stage_record,
    planned_outputs,
    validate_pipeline,
)


DAILY_ADHD_PROMPT = """这是一个 RESEARCH_DECISION 任务。请走 task_engine_runner full。

任务主题：
AI 信息环境下，ADHD 儿童特征的未来结构性反转与长期发展决策。

执行要求：
* mode=RESEARCH_DECISION
* full-run
* 必须按 canonical 16 stages 执行
* 不要输出 ROUTE_CARD
* 不要等待二次确认
"""


def _load(payload: str) -> dict:
    return json.loads(payload)


def _accepted_packet_text(root: Path, *, provenance: bool = True) -> str:
    lines = [
        "research_evidence_packet",
        "verdict: ACCEPTED",
        "accepted: true",
        "checked_stages: [L1_gemini_search, L2_ddgs_supplement, L2_5_codex_evidence_organizer, L3_r1_synthesis, L4_gemini_audit]",
        "missing_or_invalid_artifacts: []",
        "critical_defects: []",
        "noncritical_defects: []",
        "verification_required: []",
        "evidence_gaps: [long_horizon_transfer_gap]",
        "handoff_caveats: []",
        "audit_summary: L4 audit accepted the compact evidence packet.",
        "evidence_packet_ready_for_decision: true",
    ]
    if provenance:
        lines.extend(
            [
                "current_run_id: run-20260630-fixture",
                "current_query_hash: sha256:fixture-query-hash",
                f"current_artifact_dir: {root.resolve()}",
            ]
        )
    lines.extend(
        [
            "",
            "## evidence_strength",
            "Evidence strength is bounded to current research artifacts and audited synthesis, with long-horizon claims downgraded.",
            "",
            "## claim_table",
            "- claim_id: C1",
            "  claim_text: Verified source-backed claim about stable mechanism boundaries and decision constraints.",
            "  epistemic_tier: evidence_supported",
            "  evidence_strength: medium",
            "  source_anchors: S1 (full_text_verified; peer_reviewed_source; https://example.test/source)",
            "  applicability_boundary: Applies within the source population and measurement context.",
            "  counter_signal_or_failure_condition: Failed transfer or contradictory passages should downgrade it.",
            "  evidence_gap: measurement_context_gap",
            "  decision_use: can_support_decision",
            "",
            "## controversy",
            "Controversy depends on population differences, measurement choices, context, and mechanism transfer limits.",
            "",
            "## evidence_gap",
            "Evidence gap remains for direct individual longitudinal evidence and exact future-environment evidence.",
            "",
            "## evidence_supported",
            "Evidence supported claims are bounded to current research artifacts and audited synthesis only.",
            "",
            "## reasonable_inference",
            "Reasonable inference connects evidence to decisions through explicit mechanisms and uncertainty boundaries.",
            "",
            "## foresight_hypothesis",
            "Foresight hypotheses are conditional and require counter-signals and failure conditions.",
            "",
            "scope: acceptance gate plus compact evidence packet; no raw dump and no user-facing advice.",
        ]
    )
    return "\n".join(lines)


def _write_outputs(spec, root: Path, body: str) -> dict[str, str]:
    outputs = planned_outputs(spec, root)
    for output in outputs.values():
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return outputs


def _production_run(
    root: Path,
    *,
    execution_mode: str = "production-research-decision-two-stage",
    l2_5_status: str = "real",
    packet_provenance: bool = True,
) -> dict:
    stages = []
    for spec in CANONICAL_STAGES[ENGINE_RESEARCH_DECISION]:
        if spec.stage_name == "L5_deepseek_acceptance":
            body = _accepted_packet_text(root, provenance=packet_provenance)
            status = "accepted"
        else:
            body = f"{spec.stage_name} production fixture output"
            status = l2_5_status if spec.stage_name == "L2_5_codex_evidence_organizer" else "real"
        outputs = _write_outputs(spec, root, body)
        stages.append(
            make_stage_record(
                spec,
                base_dir=root,
                created=True,
                valid=True,
                status=status,
                outputs=outputs,
            ).__dict__
        )
    return {"mode": ENGINE_RESEARCH_DECISION, "execution_mode": execution_mode, "stages": stages}


def _research_run(
    root: Path,
    *,
    execution_mode: str = "production-research-full",
    l2_5_status: str = "real",
    packet_provenance: bool = True,
) -> dict:
    stages = []
    for spec in CANONICAL_STAGES[ENGINE_RESEARCH]:
        if spec.stage_name == "L5_deepseek_acceptance":
            body = _accepted_packet_text(root, provenance=packet_provenance)
            status = "accepted"
        else:
            body = f"{spec.stage_name} production fixture output"
            status = l2_5_status if spec.stage_name == "L2_5_codex_evidence_organizer" else "real"
        outputs = _write_outputs(spec, root, body)
        stages.append(
            make_stage_record(
                spec,
                base_dir=root,
                created=True,
                valid=True,
                status=status,
                outputs=outputs,
            ).__dict__
        )
    return {"mode": ENGINE_RESEARCH, "execution_mode": execution_mode, "stages": stages}


def test_research_decision_full_default_does_not_map_to_smoke(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "run_research_decision_l1_l16_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("production full must not enter smoke")),
    )

    result = _load(
        runner.task_engine_runner(
            query=DAILY_ADHD_PROMPT,
            mode=ENGINE_RESEARCH_DECISION,
            action="full",
            base_dir=str(tmp_path / "daily"),
        )
    )

    dumped = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "blocked"
    assert result["BLOCKED_STATUS"] == PIPELINE_BLOCKED
    assert result["blocked_reason"] == runner.RESEARCH_DECISION_COMBINED_FULL_REQUIRES_FRESH_TWO_STAGE
    assert result["full_run_request"]["effective_action"] == "archived-research-decision"
    assert result["artifact_dir"] == str(tmp_path / "daily")
    assert "real-smoke-research-decision-final" not in dumped
    assert "smoke-research-decision-final" not in result["full_run_request"]["effective_action"]


def test_research_full_does_not_map_to_smoke_l1_l5(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "run_research_l1_l5_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("RESEARCH full must not enter smoke")),
    )

    result = _load(
        runner.task_engine_runner(
            query="RESEARCH production full-run. Do not run smoke, fixtures, cached evidence, or old packets.",
            mode=ENGINE_RESEARCH,
            action="full",
            base_dir=str(tmp_path / "research"),
        )
    )

    dumped = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "blocked"
    assert result["pipeline_status"] == PIPELINE_BLOCKED
    assert result["full_run_request"]["effective_action"] != "smoke-research-l1-l5"
    assert "real-smoke-l1-l5" not in dumped
    assert "smoke-research-l1-l5" not in result["full_run_request"]["effective_action"]


def test_research_full_blocks_when_l2_5_real_not_implemented(tmp_path: Path) -> None:
    result = _load(
        runner.task_engine_runner(
            query="RESEARCH production full-run with no smoke intent.",
            mode=ENGINE_RESEARCH,
            action="full",
            base_dir=str(tmp_path / "research"),
        )
    )

    assert result["status"] == "blocked"
    assert result["BLOCKED_STATUS"] == PIPELINE_BLOCKED
    assert result["blocked_stage"] == "L2_5_codex_evidence_organizer"
    assert runner.RESEARCH_FULL_REAL_L2_5_NOT_IMPLEMENTED in result["blocked_reason"]
    assert result["production_valid_fresh_packet"] is False
    assert result["recommended_next_step"] == (
        "implement real L2.5 evidence organizer or explicitly run non-production smoke test"
    )


def test_allow_archived_requires_explicit_smoke_intent(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_smoke(query: str, *, base_dir: str | Path) -> dict:
        calls.append((query, Path(base_dir)))
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_COMPLETE,
            "run": {
                "mode": ENGINE_RESEARCH_DECISION,
                "execution_mode": "real-smoke-research-decision-final",
                "stages": [],
            },
            "full_pipeline_validation": {"valid": True},
        }

    monkeypatch.setattr(runner, "run_research_decision_l1_l16_smoke", fake_smoke)

    blocked = _load(
        runner.task_engine_runner(
            query=DAILY_ADHD_PROMPT,
            mode=ENGINE_RESEARCH_DECISION,
            action="full",
            base_dir=str(tmp_path / "full"),
            allow_archived_research_decision=True,
        )
    )
    assert blocked["status"] == "blocked"
    assert blocked["blocked_reason"] == runner.UNSAFE_ARCHIVED_RESEARCH_DECISION_OVERRIDE_FOR_PRODUCTION
    assert calls == []

    allowed_smoke = _load(
        runner.task_engine_runner(
            query="integration smoke fixture",
            mode=ENGINE_RESEARCH_DECISION,
            action="smoke-research-decision-final",
            base_dir=str(tmp_path / "smoke"),
            allow_archived_research_decision=True,
        )
    )
    assert allowed_smoke["status"] == "ok"
    assert allowed_smoke["pipeline_status"] == runner.PIPELINE_COMPLETE_NON_PRODUCTION_SMOKE
    assert allowed_smoke["structural_pipeline_status"] == PIPELINE_COMPLETE
    assert allowed_smoke["non_production_smoke_run"] is True
    assert allowed_smoke["production_run"] is False
    assert allowed_smoke["production_valid"] is False
    assert allowed_smoke["evidence_freshness_valid"] is False
    assert allowed_smoke["smoke_run_policy"]["allow_as_production_full_run"] is False
    assert calls == [("integration smoke fixture", tmp_path / "smoke")]


def test_l5_acceptance_rejects_handoff_smoke_in_production(tmp_path: Path) -> None:
    run = _research_run(tmp_path, l2_5_status="handoff-smoke")

    with pytest.raises(RuntimeError, match="L2_5_codex_evidence_organizer.*non-real production input"):
        executors._require_fresh_prior_for_l5(
            run["stages"][:5],
            base_dir=tmp_path,
            production=True,
        )


def test_validate_pipeline_rejects_non_real_stage_for_production(tmp_path: Path) -> None:
    run = _research_run(tmp_path, l2_5_status="handoff-smoke")

    validation = validate_pipeline(ENGINE_RESEARCH, run, base_dir=tmp_path, production=True)

    assert validation["pipeline_status"] == PIPELINE_BLOCKED
    assert validation["production_valid_fresh_packet"] is False
    assert validation["non_smoke_evidence_organizer"] is False
    assert "production_freshness:L2_5_codex_evidence_organizer:handoff_smoke_not_allowed" in validation["errors"]
    assert any(
        error.startswith(
            "production_freshness:L2_5_codex_evidence_organizer:non_real_stage_status_not_allowed:handoff-smoke"
        )
        for error in validation["errors"]
    )


def test_current_run_fresh_not_equal_production_valid(tmp_path: Path) -> None:
    run = _research_run(tmp_path, l2_5_status="handoff-smoke")

    validation = validate_pipeline(ENGINE_RESEARCH, run, base_dir=tmp_path, production=True)

    assert validation["current_run_artifact"] is True
    assert validation["non_smoke_evidence_organizer"] is False
    assert validation["production_valid_fresh_packet"] is False
    assert validation["pipeline_status"] == PIPELINE_BLOCKED


def test_explicit_smoke_research_l1_l5_still_non_production(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_smoke(query: str, *, base_dir: str | Path) -> dict:
        calls.append((query, Path(base_dir)))
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_COMPLETE,
            "run": {
                "mode": ENGINE_RESEARCH,
                "execution_mode": "real-smoke-l1-l5",
                "stages": [],
            },
            "full_pipeline_validation": {"valid": True},
        }

    monkeypatch.setattr(runner, "run_research_l1_l5_smoke", fake_smoke)

    result = _load(
        runner.task_engine_runner(
            query="explicit integration smoke for RESEARCH L1-L5",
            mode=ENGINE_RESEARCH,
            action="smoke-research-l1-l5",
            base_dir=str(tmp_path / "smoke"),
            execution_intent="integration_smoke",
            explicit_smoke_intent=True,
        )
    )

    assert result["pipeline_status"] == runner.PIPELINE_COMPLETE_NON_PRODUCTION_SMOKE
    assert result["structural_pipeline_status"] == PIPELINE_COMPLETE
    assert result["non_production_smoke_run"] is True
    assert result["production_valid"] is False
    assert result["evidence_freshness_valid"] is False
    assert calls == [("explicit integration smoke for RESEARCH L1-L5", tmp_path / "smoke")]


def test_production_disallows_l2_5_handoff_smoke(tmp_path: Path) -> None:
    run = _production_run(tmp_path, l2_5_status="handoff-smoke")

    validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=tmp_path, production=True)

    assert validation["pipeline_status"] == PIPELINE_BLOCKED
    assert validation["production_freshness_valid"] is False
    assert "production_freshness:L2_5_codex_evidence_organizer:handoff_smoke_not_allowed" in validation["errors"]


def test_production_disallows_l5_old_accepted_packet(tmp_path: Path) -> None:
    run = _production_run(tmp_path, packet_provenance=False)

    validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=tmp_path, production=True)

    assert validation["pipeline_status"] == PIPELINE_BLOCKED
    assert validation["production_freshness_valid"] is False
    assert "production_freshness:L5_deepseek_acceptance:missing_provenance:current_run_id" in validation["errors"]
    assert "production_freshness:L5_deepseek_acceptance:missing_provenance:current_query_hash" in validation["errors"]
    assert "production_freshness:L5_deepseek_acceptance:missing_provenance:current_artifact_dir" in validation["errors"]


def test_production_pipeline_complete_requires_freshness(tmp_path: Path) -> None:
    production_run = _production_run(tmp_path / "production")

    validation = validate_pipeline(
        ENGINE_RESEARCH_DECISION,
        production_run,
        base_dir=tmp_path / "production",
        production=True,
    )

    assert validation["pipeline_status"] == PIPELINE_COMPLETE
    assert validation["production_freshness_valid"] is True
    assert validation["production_freshness_errors"] == []

    smoke_run = _production_run(
        tmp_path / "smoke",
        execution_mode="real-smoke-research-decision-final",
    )
    smoke_validation = validate_pipeline(
        ENGINE_RESEARCH_DECISION,
        smoke_run,
        base_dir=tmp_path / "smoke",
        production=True,
    )
    assert smoke_validation["pipeline_status"] == PIPELINE_BLOCKED
    assert any("execution_mode_smoke_not_allowed" in error for error in smoke_validation["errors"])


def test_daily_adhd_prompt_dry_intercept_no_smoke(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "run_research_decision_l1_l16_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("daily prompt must not run smoke")),
    )

    result = _load(
        runner.task_engine_runner(
            query=DAILY_ADHD_PROMPT,
            mode="AUTO",
            action="full",
            artifact_dir=str(tmp_path / "daily_artifacts"),
        )
    )

    dumped = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "blocked"
    assert result["blocked_reason"] == runner.RESEARCH_DECISION_COMBINED_FULL_REQUIRES_FRESH_TWO_STAGE
    assert result["artifact_dir"] == str(tmp_path / "daily_artifacts")
    assert "real-smoke-research-decision-final" not in dumped
    assert "handoff-smoke" not in dumped
    assert result["recommended_next_step"].startswith("Run RESEARCH full")


def test_gate_artifact_dir_or_base_dir_not_silently_ignored(tmp_path: Path) -> None:
    same = _load(
        runner.task_engine_runner(
            query=DAILY_ADHD_PROMPT,
            mode=ENGINE_RESEARCH_DECISION,
            action="full",
            base_dir=str(tmp_path / "same"),
            artifact_dir=str(tmp_path / "same"),
        )
    )
    assert same["artifact_dir"] == str(tmp_path / "same")

    conflict = _load(
        runner.task_engine_runner(
            query=DAILY_ADHD_PROMPT,
            mode=ENGINE_RESEARCH_DECISION,
            action="full",
            base_dir=str(tmp_path / "base"),
            artifact_dir=str(tmp_path / "artifact"),
        )
    )
    assert conflict["status"] == "blocked"
    assert conflict["blocked_stage"] == "artifact_dir_policy"
    assert conflict["blocked_reason"] == "base_dir_artifact_dir_conflict"
