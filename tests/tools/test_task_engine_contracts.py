from __future__ import annotations

import json
import http.client
import os
from pathlib import Path

from tools.task_engine_contracts import (
    CANONICAL_STAGES,
    CONTROLLER_ACCEPTANCE,
    ENGINE_DECISION,
    ENGINE_RESEARCH,
    ENGINE_RESEARCH_DECISION,
    FINAL_CONTROLLER,
    GEMINI_HIGH,
    GEMINI_PRO_HIGH,
    GEMMA431B,
    LLAMA70B,
    NEMOTRON120B,
    PIPELINE_BLOCKED,
    PIPELINE_COMPLETE,
    QWEN72B,
    R1_32B,
    StageSpec,
    build_engine_contract,
    detect_task_engine_mode,
    render_final_markdown,
    validate_pipeline,
)
from tools.task_engine_executors import (
    GEMMA431B_ACTUAL_MODEL_DEFAULT,
    LLAMA70B_ACTUAL_MODEL_DEFAULT,
    LocalTaskEngineExecutor,
    NEMOTRON120B_ACTUAL_MODEL_DEFAULT,
    QWEN72B_ACTUAL_MODEL_DEFAULT,
    R1_ACTUAL_MODEL_DEFAULT,
    resolve_gemma431b_omlx_model_alias,
    resolve_llama70b_omlx_model_alias,
    resolve_agy_model_alias,
    resolve_nemotron120b_omlx_model_alias,
    resolve_qwen72b_omlx_model_alias,
    resolve_r1_omlx_model_alias,
    run_decision_final_smoke,
    run_agy_preflight,
    run_omlx_preflight,
    run_research_decision_alternative_generator_smoke,
    run_research_decision_convergence_smoke,
    run_research_decision_evidence_judge_smoke,
    run_research_decision_external_calibration_smoke,
    run_research_decision_final_controller_smoke,
    run_research_decision_intelligence_smoke,
    run_research_decision_insight_harvester_smoke,
    run_research_decision_l1_l10_smoke,
    run_research_decision_l1_l11_smoke,
    run_research_decision_l1_l12_smoke,
    run_research_decision_l1_l13_smoke,
    run_research_decision_l1_l14_smoke,
    run_research_decision_l1_l15_smoke,
    run_research_decision_l1_l16_smoke,
    run_research_decision_l1_l7_smoke,
    run_research_decision_l1_l8_smoke,
    run_research_decision_l1_l9_smoke,
    run_research_decision_premise_auditor_smoke,
    run_research_decision_structure_mapper_smoke,
    run_research_decision_supplementary_search_smoke,
    run_research_l2_5_codex_handoff_smoke,
    run_research_l1_l3_smoke,
    run_research_l1_l4_smoke,
    run_research_l1_l5_smoke,
    run_research_l3_synthesis_smoke,
    run_research_l4_gemini_audit_smoke,
    run_research_l5_acceptance_smoke,
    run_research_l1_l2_smoke,
)
from tools.research_pipeline_runner import research_pipeline_runner
from tools.registry import registry
from tools.task_mode_runtime import TaskModeRuntime, TaskModeState
from tools.task_engine_runner import task_engine_runner
from toolsets import resolve_toolset
from work import nightly_task_engine_runner as nightly_runner
from work import stress_task_engine_adhd as stress_runner


ADHD_PROMPT = """这是一个研究决策任务。

ADHD 儿童最新的研究进展和治疗方案；
与我儿子情况相匹配的梳理；
一些建议，以及长期发展的路线。
我想知道是否要主动干预，要主动干预到什么程度？
"""


def test_research_decision_schema_has_exact_16_stage_order():
    names = [stage.stage_name for stage in CANONICAL_STAGES[ENGINE_RESEARCH_DECISION]]
    assert names == [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
        "supplementary_search",
        "structure_mapper",
        "evidence_judge",
        "premise_auditor",
        "alternative_generator",
        "insight_harvester",
        "convergence_report",
        "external_calibration",
        "final_controller_report",
    ]


def test_auto_detection_keeps_ordinary_chat_out_of_engine_modes():
    assert detect_task_engine_mode(ADHD_PROMPT) == ENGINE_RESEARCH_DECISION
    assert detect_task_engine_mode("帮我改一下这个按钮的颜色") is None

    result = json.loads(task_engine_runner(query="帮我改一下这个按钮的颜色", mode="AUTO"))
    assert result["status"] == "not_applicable"
    assert result["ordinary_chat_model_replaced"] is False


def test_legacy_research_runner_blocks_heavy_task_modes():
    result = json.loads(research_pipeline_runner(ADHD_PROMPT))
    assert result["pipeline_status"] == "PIPELINE_BLOCKED"
    assert result["required_tool"] == "task_engine_runner"
    assert result["detected_mode"] == ENGINE_RESEARCH_DECISION


def test_task_engine_runner_is_available_for_real_entrypoint():
    definitions = registry.get_definitions({"task_engine_runner"}, quiet=True)

    assert len(definitions) == 1
    assert definitions[0]["function"]["name"] == "task_engine_runner"


def test_hermes_cli_toolset_exposes_task_engine_but_not_legacy_runner():
    tools = set(resolve_toolset("hermes-cli"))

    assert "task_engine_runner" in tools
    assert "research_pipeline_runner" not in tools


def test_research_decision_entry_uses_task_engine_runner_without_route_card_loop(tmp_path: Path):
    result = json.loads(
        task_engine_runner(
            query=ADHD_PROMPT,
            mode="AUTO",
            action="dry-run",
            base_dir=str(tmp_path / "entry"),
        )
    )

    assert detect_task_engine_mode(ADHD_PROMPT) == ENGINE_RESEARCH_DECISION
    assert result["status"] == "ok"
    assert result["mode"] == ENGINE_RESEARCH_DECISION
    assert result["plan"]["stage_count"] == 16
    serialized = json.dumps(result, ensure_ascii=False)
    assert "ROUTE_CARD_NOT_CONFIRMED" not in serialized
    assert "route_card" not in serialized.lower()
    assert "deepseek-v4-flash" not in serialized.lower()
    assert "final_controller_report" in serialized


def test_task_mode_gate_allows_task_engine_and_blocks_legacy_paths():
    runtime = TaskModeRuntime()
    runtime._state = TaskModeState.INIT_LOCKED

    assert runtime.preflight("task_engine_runner") is None
    legacy_block = runtime.preflight("research_pipeline_runner")
    web_block = runtime.preflight("web_search")
    assert legacy_block and "task_engine_runner" in legacy_block
    assert web_block and "task_engine_runner" in web_block

    runtime._state = TaskModeState.ROUTE_CARD_SUBMITTED
    assert runtime.preflight("task_engine_runner") is None
    route_card_legacy_block = runtime.preflight("research_pipeline_runner")
    assert route_card_legacy_block and "task_engine_runner" in route_card_legacy_block


def test_ordinary_chat_does_not_trigger_task_engine_runner():
    result = json.loads(task_engine_runner(query="帮我改一下这个按钮的颜色", mode="AUTO"))

    assert detect_task_engine_mode("帮我改一下这个按钮的颜色") is None
    assert result["status"] == "not_applicable"
    assert result["ordinary_chat_model_replaced"] is False


def test_contract_is_72b_first_but_not_global_chat_replacement():
    contract = build_engine_contract(ENGINE_DECISION, "是否应该主动干预")
    assert contract["controller"]["model"] == "Qwen72B"
    assert contract["controller"]["must_not_replace_ordinary_chat"] is True
    assert contract["schema"]["ordinary_chat_model_replaced"] is False


def test_dry_run_generates_canonical_stage_record_plans_for_all_modes(tmp_path: Path):
    expected_counts = {
        ENGINE_RESEARCH: 6,
        ENGINE_DECISION: 10,
        ENGINE_RESEARCH_DECISION: 16,
    }
    for mode, expected_count in expected_counts.items():
        result = json.loads(
            task_engine_runner(
                query=ADHD_PROMPT,
                mode=mode,
                action="dry-run",
                base_dir=str(tmp_path / mode),
            )
        )
        stages = result["plan"]["stages"]
        assert result["status"] == "ok"
        assert result["plan"]["model_calls_made"] is False
        assert len(stages) == expected_count
        assert [stage["stage_name"] for stage in stages] == [
            spec.stage_name for spec in CANONICAL_STAGES[mode]
        ]
        assert [stage["model"] for stage in stages] == [
            spec.model for spec in CANONICAL_STAGES[mode]
        ]
        assert all(stage["created_in_current_run"] is False for stage in stages)
        assert all(stage["valid_for_pipeline"] is False for stage in stages)


def test_structure_mapper_canonical_binding_and_output(tmp_path: Path):
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][8]
    evidence_stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][9]
    premise_stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][10]
    alternative_stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][11]
    insight_stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][12]
    convergence_stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][13]
    calibration_stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][14]
    final_stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][15]

    assert stage.stage_name == "structure_mapper"
    assert stage.owner == QWEN72B
    assert stage.model == QWEN72B
    assert stage.required_outputs == ("structure_mapper.md",)
    assert evidence_stage.stage_name == "evidence_judge"
    assert evidence_stage.owner == NEMOTRON120B
    assert evidence_stage.model == NEMOTRON120B
    assert evidence_stage.required_outputs == ("evidence_judge.md",)
    assert premise_stage.stage_name == "premise_auditor"
    assert premise_stage.owner == LLAMA70B
    assert premise_stage.model == LLAMA70B
    assert premise_stage.required_outputs == ("premise_auditor.md",)
    assert alternative_stage.stage_name == "alternative_generator"
    assert alternative_stage.owner == GEMMA431B
    assert alternative_stage.model == GEMMA431B
    assert alternative_stage.required_outputs == ("alternative_generator.md",)
    assert insight_stage.stage_name == "insight_harvester"
    assert insight_stage.owner == GEMMA431B
    assert insight_stage.model == GEMMA431B
    assert insight_stage.required_outputs == ("insight_harvester.md",)
    assert convergence_stage.stage_name == "convergence_report"
    assert convergence_stage.owner == R1_32B
    assert convergence_stage.model == R1_32B
    assert convergence_stage.required_outputs == ("convergence_report.md",)
    assert calibration_stage.stage_name == "external_calibration"
    assert calibration_stage.owner == "GPT Bridge or Gemini/agy"
    assert calibration_stage.model == "GPT Bridge or Gemini/agy"
    assert calibration_stage.required_outputs == ("external_calibration.md",)
    assert final_stage.stage_name == "final_controller_report"
    assert final_stage.owner == "Controller"
    assert final_stage.model == FINAL_CONTROLLER
    assert final_stage.required_outputs == ("final_decision_report.md",)

    research = json.loads(
        task_engine_runner(
            query=ADHD_PROMPT,
            mode=ENGINE_RESEARCH,
            action="dry-run",
            base_dir=str(tmp_path / "research"),
        )
    )
    l1 = research["plan"]["stages"][0]
    l2 = research["plan"]["stages"][1]
    handoff = research["plan"]["stages"][2]
    l4 = research["plan"]["stages"][4]
    assert l1["owner"] == GEMINI_HIGH
    assert l1["model"] == GEMINI_HIGH
    assert l1["executor_model"] == GEMINI_HIGH
    assert l4["stage_name"] == "L4_gemini_audit"
    assert l4["owner"] == GEMINI_PRO_HIGH
    assert l4["model"] == GEMINI_PRO_HIGH
    assert l4["executor_model"] == GEMINI_PRO_HIGH
    assert l1["artifact_path"].endswith("L1_gemini_search/source_candidates.json")
    assert l2["artifact_path"].endswith("L2_ddgs_supplement/ddgs_gap_sources.json")
    assert research["plan"]["stages"][5]["artifact_path"].endswith(
        "L5_deepseek_acceptance/research_evidence_packet.md"
    )
    assert "evidence_runner_001.request.json" in "\n".join(handoff["outputs"].values())

    research_decision = json.loads(
        task_engine_runner(
            query=ADHD_PROMPT,
            mode=ENGINE_RESEARCH_DECISION,
            action="dry-run",
            base_dir=str(tmp_path / "research_decision"),
        )
    )
    rd_l4 = research_decision["plan"]["stages"][4]
    assert rd_l4["stage_name"] == "L4_gemini_audit"
    assert rd_l4["owner"] == GEMINI_PRO_HIGH
    assert rd_l4["model"] == GEMINI_PRO_HIGH


def test_simulated_run_validates_and_renders_all_modes(tmp_path: Path):
    for mode in (ENGINE_RESEARCH, ENGINE_DECISION, ENGINE_RESEARCH_DECISION):
        result = json.loads(
            task_engine_runner(
                query=ADHD_PROMPT,
                mode=mode,
                action="simulated-run",
                base_dir=str(tmp_path / mode),
            )
        )
        assert result["status"] == "ok"
        assert result["pipeline_status"] == PIPELINE_COMPLETE
        assert result["validation"]["valid"] is True
        assert result["validation"]["stage_count"] == len(CANONICAL_STAGES[mode])
        assert "pipeline_status=PIPELINE_COMPLETE" in result["markdown"]
        if mode == ENGINE_RESEARCH:
            assert "research_evidence_packet" in result["markdown"]
            assert "accepted: true" in result["markdown"]
        else:
            assert "FINAL CONTROLLER BODY" in result["markdown"]


def test_complete_research_decision_run_validates_and_renders_only_final(tmp_path: Path):
    run = _make_run(tmp_path, ENGINE_RESEARCH_DECISION)
    validation = validate_pipeline(ENGINE_RESEARCH_DECISION, run, base_dir=tmp_path)

    assert validation["valid"] is True
    assert validation["pipeline_status"] == PIPELINE_COMPLETE
    assert validation["divergence_unique_model_count"] == 4

    markdown = render_final_markdown(ENGINE_RESEARCH_DECISION, run, validation, base_dir=tmp_path)
    assert "entered_engine_run_pipeline=true" in markdown
    assert "pipeline_status=PIPELINE_COMPLETE" in markdown
    assert "pipeline_validation.valid=true" in markdown
    assert "delegation_used=false" in markdown
    assert "FINAL CONTROLLER BODY" in markdown
    assert "R1 CONVERGENCE BODY" not in markdown
    assert "Compact Pipeline Trace:" in markdown


def test_wrong_divergence_model_fails_closed(tmp_path: Path):
    run = _make_run(tmp_path, ENGINE_DECISION)
    for stage in run["stages"]:
        if stage["stage_name"] == "structure_mapper":
            stage["model"] = "R1-32B"
            break

    validation = validate_pipeline(ENGINE_DECISION, run, base_dir=tmp_path)

    assert validation["valid"] is False
    assert validation["pipeline_status"] == PIPELINE_BLOCKED
    assert any("structure_mapper:model_mismatch" in error for error in validation["errors"])
    assert any("structure_mapper:r1_forbidden_here" in error for error in validation["errors"])


def test_codex_handoff_requires_request_json_and_outputs(tmp_path: Path):
    run = _make_run(tmp_path, ENGINE_RESEARCH)
    request_json = tmp_path / "L2_5_codex_evidence_organizer" / "evidence_runner_001.request.json"
    request_json.unlink()

    validation = validate_pipeline(ENGINE_RESEARCH, run, base_dir=tmp_path)

    assert validation["valid"] is False
    assert any(
        "L2_5_codex_evidence_organizer:required_output_missing:evidence_runner_*.request.json"
        in error
        for error in validation["errors"]
    )


def test_legacy_or_missing_artifacts_fail_closed(tmp_path: Path):
    run = _make_run(tmp_path, ENGINE_RESEARCH)
    run["stages"][0]["created_in_current_run"] = False
    run["stages"][1]["legacy_contaminated"] = True
    Path(run["stages"][3]["artifact_path"]).unlink()

    validation = validate_pipeline(ENGINE_RESEARCH, run, base_dir=tmp_path)

    assert validation["valid"] is False
    assert any("created_in_current_run_not_true" in error for error in validation["errors"])
    assert any("legacy_contaminated_not_false" in error for error in validation["errors"])
    assert any("artifact_path_not_found" in error for error in validation["errors"])


def test_final_renderer_blocks_pseudo_tool_chain_leakage(tmp_path: Path):
    run = _make_run(tmp_path, ENGINE_RESEARCH_DECISION)
    final_artifact = tmp_path / "final_controller_report" / "final_decision_report.md"
    final_artifact.write_text("FINAL CONTROLLER BODY\nweb_search should not leak", encoding="utf-8")

    markdown = render_final_markdown(ENGINE_RESEARCH_DECISION, run, base_dir=tmp_path)

    assert "pipeline_status=PIPELINE_BLOCKED" in markdown
    assert "final_markdown_forbidden_tokens:web_search" in markdown


def test_l1_l2_smoke_can_complete_subset_but_full_pipeline_stays_incomplete(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            assert stage.stage_name == "L1_gemini_search"
            assert model == "Gemini 3.5 Flash (High)"
            return {"source_candidates": [{"title": "fake", "url": "https://example.test"}]}

        def run_ddgs(self, stage, queries):
            assert stage.stage_name == "L2_ddgs_supplement"
            assert queries
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs", "snippet": "ok"}]

    result = run_research_l1_l2_smoke(
        ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    assert [stage["stage_name"] for stage in result["run"]["stages"]] == [
        "L1_gemini_search",
        "L2_ddgs_supplement",
    ]
    assert result["run"]["stages"][0]["owner"] == "Gemini 3.5 Flash (High)"
    assert result["run"]["stages"][0]["executor_model"] == "Gemini 3.5 Flash (High)"
    assert all(stage["created_in_current_run"] is True for stage in result["run"]["stages"])
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:L2_5_codex_evidence_organizer" in error for error in result["full_pipeline_validation"]["errors"])


def test_l1_l2_smoke_fails_closed_on_first_real_adapter_error(tmp_path: Path):
    class FailingExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            raise RuntimeError("agy unavailable")

    result = run_research_l1_l2_smoke(
        ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FailingExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["pipeline_status"] == PIPELINE_BLOCKED
    assert result["blocked_stage"] == "L1_gemini_search"
    assert result["run"]["stages"][0]["created_in_current_run"] is False
    assert result["run"]["stages"][0]["valid_for_pipeline"] is False


def test_ddgs_startpage_timeout_does_not_block_when_duckduckgo_has_results(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    def fake_search(query, *, backend, timeout_s, max_results):
        calls.append((backend, timeout_s, max_results))
        if backend == "startpage":
            raise TimeoutError("startpage timed out")
        if backend == "duckduckgo":
            return [{"title": "CDC", "href": "https://www.cdc.gov/adhd/", "body": "parent training"}]
        return []

    monkeypatch.setenv("HERMES_DDGS_BACKENDS", "startpage,duckduckgo")
    monkeypatch.setenv("HERMES_DDGS_QUERY_TIMEOUT_S", "3")
    monkeypatch.setattr(executors, "_ddgs_search_once", fake_search)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH][1]
    hits = LocalTaskEngineExecutor().run_ddgs(stage, ["ADHD parent training children"])

    assert hits == [
        {
            "query": "ADHD parent training children",
            "title": "CDC",
            "url": "https://www.cdc.gov/adhd/",
            "snippet": "parent training",
        }
    ]
    assert ("startpage", 3, 5) in calls
    assert ("duckduckgo", 3, 5) in calls


def test_ddgs_blocks_only_after_all_allowed_backends_have_no_fresh_results(monkeypatch):
    import tools.task_engine_executors as executors

    monkeypatch.setenv("HERMES_DDGS_BACKENDS", "duckduckgo,yahoo")
    monkeypatch.setattr(executors, "_ddgs_search_once", lambda *args, **kwargs: [])

    stage = CANONICAL_STAGES[ENGINE_RESEARCH][1]
    try:
        LocalTaskEngineExecutor().run_ddgs(stage, ["ADHD parent training children"])
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("DDGS should fail closed when all allowed backends are empty")

    assert "DDGS returned no fresh hits" in message
    assert "backends=duckduckgo,yahoo" in message


def test_ddgs_default_backend_list_uses_duckduckgo_brave_yahoo(monkeypatch):
    import tools.task_engine_executors as executors

    monkeypatch.delenv("HERMES_DDGS_BACKENDS", raising=False)

    assert executors._ddgs_backend_list() == ["duckduckgo", "brave", "yahoo"]
    assert "startpage" not in executors._ddgs_backend_list()
    assert "web_search" not in executors._ddgs_backend_list()
    assert "generic_web_search" not in executors._ddgs_backend_list()


def test_ddgs_rejects_web_search_fallback(monkeypatch):
    monkeypatch.setenv("HERMES_DDGS_BACKENDS", "duckduckgo,web_search")

    stage = CANONICAL_STAGES[ENGINE_RESEARCH][1]
    try:
        LocalTaskEngineExecutor().run_ddgs(stage, ["ADHD parent training children"])
    except RuntimeError as exc:
        assert "cannot include web_search fallback" in str(exc)
    else:
        raise AssertionError("web_search must not be accepted as a DDGS fallback")


def test_ddgs_uses_broad_first_adhd_queries():
    import tools.task_engine_executors as executors

    queries = executors._ddgs_queries(ADHD_PROMPT)

    assert queries[0] == "ADHD parent training children"
    assert all(len(query) < 120 for query in queries)


def test_agy_alias_resolver_rejects_forbidden_ccpa(monkeypatch):
    monkeypatch.setenv("HERMES_AGY_GEMINI_HIGH_MODEL", "CCPA")
    try:
        resolve_agy_model_alias(GEMINI_HIGH)
    except RuntimeError as exc:
        assert "forbidden CCPA" in str(exc)
    else:
        raise AssertionError("CCPA alias should be rejected")

    monkeypatch.delenv("HERMES_AGY_GEMINI_HIGH_MODEL", raising=False)
    monkeypatch.setenv("HERMES_AGY_GEMINI_PRO_HIGH_MODEL", "CCPA")
    try:
        resolve_agy_model_alias(GEMINI_PRO_HIGH)
    except RuntimeError as exc:
        assert "forbidden CCPA" in str(exc)
    else:
        raise AssertionError("CCPA alias should be rejected for Pro High")


def test_agy_alias_resolver_supports_flash_and_pro_high(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("HERMES_AGY_GEMINI_HIGH_MODEL", raising=False)
    monkeypatch.delenv("HERMES_AGY_GEMINI_PRO_HIGH_MODEL", raising=False)
    monkeypatch.setenv("HERMES_AGY_MODEL_ALIAS_ENV", str(tmp_path / "missing.env"))

    assert resolve_agy_model_alias(GEMINI_HIGH) == GEMINI_HIGH
    assert resolve_agy_model_alias(GEMINI_PRO_HIGH) == GEMINI_PRO_HIGH


def test_agy_adapter_matches_legacy_call_shape(monkeypatch, tmp_path: Path):
    import tools.task_engine_executors as executors

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "forced failure"})()

    monkeypatch.setenv("HERMES_AGY_MODEL_ALIAS_ENV", str(tmp_path / "missing.env"))
    monkeypatch.setattr(executors.shutil, "which", lambda name: "/opt/homebrew/bin/agy")
    monkeypatch.setattr(executors.subprocess, "run", fake_run)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH][0]
    executor = LocalTaskEngineExecutor()
    try:
        executor.run_agy_gemini(stage, "prompt", GEMINI_HIGH)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("forced AGY failure should raise")

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:2] == ["/opt/homebrew/bin/agy", "--log-file"]
    assert command[2].startswith("/private/tmp/agy-")
    assert command[3:8] == ["--model", GEMINI_HIGH, "-p", "prompt", "--print-timeout"]
    assert command[8] == "240s"
    assert kwargs["timeout"] == 270
    assert "canonical_model='Gemini 3.5 Flash (High)'" in message
    assert "actual_model='Gemini 3.5 Flash (High)'" in message
    assert "log_file='/private/tmp/agy-" in message
    assert "elapsed_seconds=" in message
    assert "command=" in message
    assert "forced failure" in message

    monkeypatch.setenv("HERMES_AGY_GEMINI_HIGH_MODEL", GEMINI_HIGH)
    monkeypatch.setenv("HERMES_AGY_GEMINI_PRO_HIGH_MODEL", GEMINI_PRO_HIGH)
    assert resolve_agy_model_alias(GEMINI_HIGH) == GEMINI_HIGH
    assert resolve_agy_model_alias(GEMINI_PRO_HIGH) == GEMINI_PRO_HIGH


def test_agy_keychain_false_negative_classification():
    import tools.task_engine_executors as executors

    false_negative = "\n".join(
        [
            "You are not logged into Antigravity.",
            "OAuth: authenticated successfully",
        ]
    )
    truly_logged_out = "You are not logged into Antigravity."

    assert executors._classify_agy_preflight_block(false_negative, "") == "AGY_KEYCHAIN_TIMEOUT_FALSE_NEGATIVE"
    assert executors._classify_agy_preflight_block("", truly_logged_out) == "AGY_AUTH_REQUIRES_USER"


def test_agy_preflight_retries_keychain_false_negative_once(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            return type(
                "Result",
                (),
                {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "You are not logged into Antigravity.\nOAuth: authenticated successfully",
                },
            )()
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "Gemini 3.5 Flash (High)\nGemini 3.1 Pro (High)\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(executors.shutil, "which", lambda name: "/opt/homebrew/bin/agy")
    monkeypatch.setattr(executors.subprocess, "run", fake_run)
    monkeypatch.setattr(executors.time, "sleep", lambda seconds: None)

    result = run_agy_preflight()

    assert result["status"] == "AGY_OK"
    assert len(calls) == 2
    assert all("auth" not in command and "login" not in command for command in calls)


def test_agy_preflight_does_not_retry_true_logged_out(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type(
            "Result",
            (),
            {
                "returncode": 1,
                "stdout": "",
                "stderr": "You are not logged into Antigravity.",
            },
        )()

    monkeypatch.setattr(executors.shutil, "which", lambda name: "/opt/homebrew/bin/agy")
    monkeypatch.setattr(executors.subprocess, "run", fake_run)
    monkeypatch.setattr(executors.time, "sleep", lambda seconds: None)

    result = run_agy_preflight()

    assert result["status"] == "BLOCKED_STATUS"
    assert result["blocked_reason"] == "AGY_AUTH_REQUIRES_USER"
    assert len(calls) == 1


def test_run_agy_gemini_retries_keychain_false_negative_then_succeeds(monkeypatch, tmp_path: Path):
    import tools.task_engine_executors as executors

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        log_file = Path(command[2])
        if len(calls) == 1:
            log_file.write_text("You are not logged into Antigravity.\nauthenticated via keyring\n", encoding="utf-8")
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        log_file.write_text("Resolving model Gemini 3.5 Flash (High)\n", encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": "fresh AGY output", "stderr": ""})()

    monkeypatch.setenv("HERMES_AGY_MODEL_ALIAS_ENV", str(tmp_path / "missing.env"))
    monkeypatch.setattr(executors.shutil, "which", lambda name: "/opt/homebrew/bin/agy")
    monkeypatch.setattr(executors.subprocess, "run", fake_run)
    monkeypatch.setattr(executors.time, "sleep", lambda seconds: None)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH][0]
    executor = LocalTaskEngineExecutor()

    assert executor.run_agy_gemini(stage, "prompt", GEMINI_HIGH) == "fresh AGY output"
    assert len(calls) == 2
    assert all("auth" not in command and "login" not in command for command in calls)


def test_run_agy_gemini_retries_keychain_false_negative_only_once(monkeypatch, tmp_path: Path):
    import tools.task_engine_executors as executors

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        Path(command[2]).write_text(
            "You are not logged into Antigravity.\nsilent auth succeeded\n",
            encoding="utf-8",
        )
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()

    monkeypatch.setenv("HERMES_AGY_MODEL_ALIAS_ENV", str(tmp_path / "missing.env"))
    monkeypatch.setattr(executors.shutil, "which", lambda name: "/opt/homebrew/bin/agy")
    monkeypatch.setattr(executors.subprocess, "run", fake_run)
    monkeypatch.setattr(executors.time, "sleep", lambda seconds: None)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH][0]
    executor = LocalTaskEngineExecutor()
    try:
        executor.run_agy_gemini(stage, "prompt", GEMINI_HIGH)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("AGY retry failure should block")

    assert len(calls) == 2
    assert "AGY_KEYCHAIN_TIMEOUT_FALSE_NEGATIVE" in message
    assert "token" not in message.lower()


def test_l2_5_codex_handoff_smoke_writes_protocol_files(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            return {"source_candidates": [{"title": "fake"}]}

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

    l1_l2 = run_research_l1_l2_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    assert l1_l2["status"] == "ok"

    result = run_research_l2_5_codex_handoff_smoke(
        l1_l2["run"],
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages] == [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
    ]
    handoff_dir = tmp_path / "L2_5_codex_evidence_organizer"
    for name in (
        "source_candidates.json",
        "ddgs_gap_sources.json",
        "evidence_runner_001.request.md",
        "evidence_runner_001.request.json",
        "sources.csv",
        "evidence.csv",
        "claims.md",
        "gaps.md",
    ):
        assert (handoff_dir / name).exists()
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:L3_r1_synthesis" in error for error in result["full_pipeline_validation"]["errors"])


def test_l1_l3_smoke_writes_r1_synthesis_and_stops_before_l4(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            return {"source_candidates": [{"title": "fake"}]}

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            assert stage.stage_name == "L3_r1_synthesis"
            assert stage.owner == R1_32B
            assert model == R1_32B
            assert "L1_gemini_search" in prompt
            assert "L2_ddgs_supplement" in prompt
            assert "L2_5_codex_evidence_organizer" in prompt
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_l1_l3_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages] == [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
    ]
    l3 = stages[-1]
    assert l3["owner"] == R1_32B
    assert l3["model"] == R1_32B
    assert l3["executor_model"] == R1_ACTUAL_MODEL_DEFAULT
    assert l3["artifact_path"].endswith("L3_r1_synthesis/r1_synthesis.md")
    assert l3["created_in_current_run"] is True
    assert l3["legacy_contaminated"] is False
    assert l3["valid_for_pipeline"] is True
    assert Path(l3["artifact_path"]).read_text(encoding="utf-8") == "R1 synthesis body"
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:L4_gemini_audit" in error for error in result["full_pipeline_validation"]["errors"])


def test_l3_requires_fresh_l1_l2_l2_5_artifacts(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            return {"source_candidates": [{"title": "fake"}]}

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            return "should not run"

    l1_l2 = run_research_l1_l2_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    l2_5 = run_research_l2_5_codex_handoff_smoke(l1_l2["run"], base_dir=tmp_path, executor=FakeExecutor())
    l2_5["run"]["stages"][0]["created_in_current_run"] = False

    result = run_research_l3_synthesis_smoke(l2_5["run"], base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "L3_r1_synthesis"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "not created_in_current_run" in result["run"]["stages"][-1]["error"]


def test_l3_rejects_legacy_artifacts(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            return {"source_candidates": [{"title": "fake"}]}

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            return "should not run"

    l1_l2 = run_research_l1_l2_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    l2_5 = run_research_l2_5_codex_handoff_smoke(l1_l2["run"], base_dir=tmp_path, executor=FakeExecutor())
    l2_5["run"]["stages"][1]["legacy_contaminated"] = True

    result = run_research_l3_synthesis_smoke(l2_5["run"], base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "L3_r1_synthesis"
    assert "legacy contaminated" in result["run"]["stages"][-1]["error"]


def test_l3_r1_model_mismatch_is_blocked_before_omlx_call():
    stage = CANONICAL_STAGES[ENGINE_RESEARCH][3]
    try:
        LocalTaskEngineExecutor().run_omlx_model(stage, "Qwen72B", "prompt")
    except RuntimeError as exc:
        assert "R1 model binding mismatch" in str(exc)
    else:
        raise AssertionError("L3 must reject non-R1 model bindings")


def test_l3_omlx_uses_actual_r1_model_and_legacy_admin_path(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    class FakeAdmin:
        def __init__(self, base_url, api_key):
            calls.append(("admin_init", base_url, bool(api_key)))

        def login(self):
            calls.append(("login",))
            return True

        def unload_all(self):
            calls.append(("unload_all",))

        def load_model(self, model_id):
            calls.append(("load_model", model_id))
            return {"success": True}

        def unload_model(self, model_id):
            calls.append(("unload_model", model_id))
            return {"success": True}

    def fake_chat(model, messages, *, api_key, timeout, max_tokens):
        calls.append(("chat", model, bool(api_key), timeout, max_tokens))
        return {"choices": [{"message": {"content": "R1 actual output"}}]}

    monkeypatch.setenv("OMLX_API_KEY", "omlx-test-key")
    monkeypatch.setattr(executors, "_OmlxAdmin", FakeAdmin)
    monkeypatch.setattr(executors, "_omlx_chat_completion", fake_chat)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH][3]
    executor = LocalTaskEngineExecutor()
    output = executor.run_omlx_model(stage, R1_32B, "prompt")

    assert output == "R1 actual output"
    assert resolve_r1_omlx_model_alias(R1_32B) == R1_ACTUAL_MODEL_DEFAULT
    assert ("load_model", R1_ACTUAL_MODEL_DEFAULT) in calls
    assert ("load_model", R1_32B) not in calls
    assert any(call[0] == "chat" and call[1] == R1_ACTUAL_MODEL_DEFAULT for call in calls)
    assert ("unload_all",) in calls
    assert ("unload_model", R1_ACTUAL_MODEL_DEFAULT) in calls
    assert executor.last_executor_models["L3_r1_synthesis"] == R1_ACTUAL_MODEL_DEFAULT


def test_convergence_report_omlx_uses_actual_r1_model_and_legacy_admin_path(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    class FakeAdmin:
        def __init__(self, base_url, api_key):
            calls.append(("admin_init", base_url, bool(api_key)))

        def login(self):
            calls.append(("login",))
            return True

        def unload_all(self):
            calls.append(("unload_all",))

        def load_model(self, model_id):
            calls.append(("load_model", model_id))
            return {"success": True}

        def unload_model(self, model_id):
            calls.append(("unload_model", model_id))
            return {"success": True}

    def fake_chat(model, messages, *, api_key, timeout, max_tokens):
        calls.append(("chat", model, bool(api_key), timeout, max_tokens))
        return {"choices": [{"message": {"content": "divergence_role_summary\nconvergence_decision_framework"}}]}

    monkeypatch.setenv("OMLX_API_KEY", "omlx-test-key")
    monkeypatch.setattr(executors, "_OmlxAdmin", FakeAdmin)
    monkeypatch.setattr(executors, "_omlx_chat_completion", fake_chat)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][13]
    executor = LocalTaskEngineExecutor()
    output = executor.run_omlx_model(stage, R1_32B, "prompt")

    assert "convergence_decision_framework" in output
    assert resolve_r1_omlx_model_alias(R1_32B) == R1_ACTUAL_MODEL_DEFAULT
    assert ("load_model", R1_ACTUAL_MODEL_DEFAULT) in calls
    assert ("load_model", R1_32B) not in calls
    assert any(call[0] == "chat" and call[1] == R1_ACTUAL_MODEL_DEFAULT for call in calls)
    assert ("unload_all",) in calls
    assert ("unload_model", R1_ACTUAL_MODEL_DEFAULT) in calls
    assert executor.last_executor_models["convergence_report"] == R1_ACTUAL_MODEL_DEFAULT


def test_l3_omlx_auth_missing_blocks_without_key_leak(monkeypatch):
    import tools.task_engine_executors as executors

    monkeypatch.delenv("OMLX_API_KEY", raising=False)
    monkeypatch.setattr(executors, "_hermes_env_value", lambda key: "")
    stage = CANONICAL_STAGES[ENGINE_RESEARCH][3]

    try:
        LocalTaskEngineExecutor().run_omlx_model(stage, R1_32B, "prompt")
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("missing OMLX auth should block L3")

    assert "OMLX_AUTH_BLOCKED" in message
    assert "omlx-" not in message


def test_structure_mapper_omlx_uses_actual_qwen72b_model_and_legacy_admin_path(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    class FakeAdmin:
        def __init__(self, base_url, api_key):
            calls.append(("admin_init", base_url, bool(api_key)))

        def login(self):
            calls.append(("login",))
            return True

        def unload_all(self):
            calls.append(("unload_all",))

        def load_model(self, model_id):
            calls.append(("load_model", model_id))
            return {"success": True}

        def unload_model(self, model_id):
            calls.append(("unload_model", model_id))
            return {"success": True}

    def fake_chat(model, messages, *, api_key, timeout, max_tokens):
        calls.append(("chat", model, bool(api_key), timeout, max_tokens))
        return {"choices": [{"message": {"content": "problem_axes\nactor_map\ndecision_questions"}}]}

    monkeypatch.setenv("OMLX_API_KEY", "omlx-test-key")
    monkeypatch.delenv("HERMES_OMLX_QWEN72B_MODEL", raising=False)
    monkeypatch.setattr(executors, "_OmlxAdmin", FakeAdmin)
    monkeypatch.setattr(executors, "_omlx_chat_completion", fake_chat)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][8]
    executor = LocalTaskEngineExecutor()
    output = executor.run_omlx_model(stage, QWEN72B, "prompt")

    assert "problem_axes" in output
    assert resolve_qwen72b_omlx_model_alias(QWEN72B) == QWEN72B_ACTUAL_MODEL_DEFAULT
    assert ("load_model", QWEN72B_ACTUAL_MODEL_DEFAULT) in calls
    assert ("load_model", QWEN72B) not in calls
    assert any(call[0] == "chat" and call[1] == QWEN72B_ACTUAL_MODEL_DEFAULT for call in calls)
    assert ("unload_all",) in calls
    assert ("unload_model", QWEN72B_ACTUAL_MODEL_DEFAULT) in calls
    assert executor.last_executor_models["structure_mapper"] == QWEN72B_ACTUAL_MODEL_DEFAULT


def test_structure_mapper_rejects_forbidden_actual_model_alias(monkeypatch):
    monkeypatch.setenv("HERMES_OMLX_QWEN72B_MODEL", "Qwen2.5-9B-Instruct-mlx")

    try:
        resolve_qwen72b_omlx_model_alias(QWEN72B)
    except RuntimeError as exc:
        assert "forbidden Qwen72B actual model alias" in str(exc)
    else:
        raise AssertionError("structure_mapper must reject 9B actual model aliases")

    monkeypatch.setenv("HERMES_OMLX_QWEN72B_MODEL", R1_ACTUAL_MODEL_DEFAULT)
    try:
        resolve_qwen72b_omlx_model_alias(QWEN72B)
    except RuntimeError as exc:
        assert "forbidden Qwen72B actual model alias" in str(exc)
    else:
        raise AssertionError("structure_mapper must reject R1 actual model aliases")


def test_evidence_judge_omlx_uses_actual_nemotron_and_retries_incomplete_read(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    class FakeAdmin:
        def __init__(self, base_url, api_key):
            calls.append(("admin_init", base_url, bool(api_key)))

        def login(self):
            calls.append(("login",))
            return True

        def unload_all(self):
            calls.append(("unload_all",))

        def load_model(self, model_id):
            calls.append(("load_model", model_id))
            return {"success": True}

        def unload_model(self, model_id):
            calls.append(("unload_model", model_id))
            return {"success": True}

    def fake_chat(model, messages, *, api_key, timeout, max_tokens):
        calls.append(("chat", model, bool(api_key), timeout, max_tokens))
        if len([call for call in calls if call[0] == "chat"]) == 1:
            raise http.client.IncompleteRead(b"partial")
        return {"choices": [{"message": {"content": "evidence_quality_map\nstrength_by_claim\nuncertainty_and_limits"}}]}

    monkeypatch.setenv("OMLX_API_KEY", "omlx-test-key")
    monkeypatch.delenv("HERMES_OMLX_NEMOTRON120B_MODEL", raising=False)
    monkeypatch.setattr(executors, "_OmlxAdmin", FakeAdmin)
    monkeypatch.setattr(executors, "_omlx_chat_completion", fake_chat)
    monkeypatch.setattr(executors.time, "sleep", lambda seconds: None)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][9]
    executor = LocalTaskEngineExecutor()
    output = executor.run_omlx_model(stage, NEMOTRON120B, "prompt")

    assert "evidence_quality_map" in output
    assert resolve_nemotron120b_omlx_model_alias(NEMOTRON120B) == NEMOTRON120B_ACTUAL_MODEL_DEFAULT
    assert ("load_model", NEMOTRON120B_ACTUAL_MODEL_DEFAULT) in calls
    assert ("load_model", NEMOTRON120B) not in calls
    assert len([call for call in calls if call[0] == "chat"]) == 2
    assert any(call[0] == "chat" and call[1] == NEMOTRON120B_ACTUAL_MODEL_DEFAULT for call in calls)
    assert ("unload_all",) in calls
    assert ("unload_model", NEMOTRON120B_ACTUAL_MODEL_DEFAULT) in calls
    assert executor.last_executor_models["evidence_judge"] == NEMOTRON120B_ACTUAL_MODEL_DEFAULT


def test_evidence_judge_rejects_forbidden_actual_model_alias(monkeypatch):
    for bad in ["Qwen2.5-72B-Instruct-mlx", "Qwen2.5-9B-Instruct-mlx", R1_ACTUAL_MODEL_DEFAULT, "DeepSeek Controller"]:
        monkeypatch.setenv("HERMES_OMLX_NEMOTRON120B_MODEL", bad)
        try:
            resolve_nemotron120b_omlx_model_alias(NEMOTRON120B)
        except RuntimeError as exc:
            assert "forbidden Nemotron-120B actual model alias" in str(exc)
        else:
            raise AssertionError(f"evidence_judge must reject forbidden actual model alias: {bad}")


def test_premise_auditor_omlx_uses_actual_llama70b_and_retries_incomplete_read(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    class FakeAdmin:
        def __init__(self, base_url, api_key):
            calls.append(("admin_init", base_url, bool(api_key)))

        def login(self):
            calls.append(("login",))
            return True

        def unload_all(self):
            calls.append(("unload_all",))

        def load_model(self, model_id):
            calls.append(("load_model", model_id))
            return {"success": True}

        def unload_model(self, model_id):
            calls.append(("unload_model", model_id))
            return {"success": True}

    def fake_chat(model, messages, *, api_key, timeout, max_tokens):
        calls.append(("chat", model, bool(api_key), timeout, max_tokens))
        if len([call for call in calls if call[0] == "chat"]) == 1:
            raise http.client.IncompleteRead(b"partial")
        return {"choices": [{"message": {"content": "implicit_premises\npremise_risks\ncounterexamples"}}]}

    monkeypatch.setenv("OMLX_API_KEY", "omlx-test-key")
    monkeypatch.delenv("HERMES_OMLX_LLAMA70B_MODEL", raising=False)
    monkeypatch.setattr(executors, "_OmlxAdmin", FakeAdmin)
    monkeypatch.setattr(executors, "_omlx_chat_completion", fake_chat)
    monkeypatch.setattr(executors.time, "sleep", lambda seconds: None)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][10]
    executor = LocalTaskEngineExecutor()
    output = executor.run_omlx_model(stage, LLAMA70B, "prompt")

    assert "implicit_premises" in output
    assert resolve_llama70b_omlx_model_alias(LLAMA70B) == LLAMA70B_ACTUAL_MODEL_DEFAULT
    assert ("load_model", LLAMA70B_ACTUAL_MODEL_DEFAULT) in calls
    assert ("load_model", LLAMA70B) not in calls
    assert len([call for call in calls if call[0] == "chat"]) == 2
    assert any(call[0] == "chat" and call[1] == LLAMA70B_ACTUAL_MODEL_DEFAULT for call in calls)
    assert ("unload_all",) in calls
    assert ("unload_model", LLAMA70B_ACTUAL_MODEL_DEFAULT) in calls
    assert executor.last_executor_models["premise_auditor"] == LLAMA70B_ACTUAL_MODEL_DEFAULT


def test_premise_auditor_rejects_forbidden_actual_model_alias(monkeypatch):
    for bad in [
        QWEN72B_ACTUAL_MODEL_DEFAULT,
        NEMOTRON120B_ACTUAL_MODEL_DEFAULT,
        "Qwen2.5-9B-Instruct-mlx",
        R1_ACTUAL_MODEL_DEFAULT,
        "DeepSeek Controller",
    ]:
        monkeypatch.setenv("HERMES_OMLX_LLAMA70B_MODEL", bad)
        try:
            resolve_llama70b_omlx_model_alias(LLAMA70B)
        except RuntimeError as exc:
            assert "forbidden Llama70B actual model alias" in str(exc)
        else:
            raise AssertionError(f"premise_auditor must reject forbidden actual model alias: {bad}")


def test_alternative_generator_omlx_uses_actual_gemma431b_model(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    class FakeAdmin:
        def __init__(self, base_url, api_key):
            calls.append(("admin_init", base_url, bool(api_key)))

        def login(self):
            calls.append(("login",))
            return True

        def unload_all(self):
            calls.append(("unload_all",))

        def load_model(self, model_id):
            calls.append(("load_model", model_id))
            return {"success": True}

        def unload_model(self, model_id):
            calls.append(("unload_model", model_id))
            return {"success": True}

    def fake_chat(model, messages, *, api_key, timeout, max_tokens):
        calls.append(("chat", model, bool(api_key), timeout, max_tokens))
        return {"choices": [{"message": {"content": "mutually_exclusive_alternatives\nintervention_intensity_paths"}}]}

    monkeypatch.setenv("OMLX_API_KEY", "omlx-test-key")
    monkeypatch.delenv("HERMES_OMLX_GEMMA431B_MODEL", raising=False)
    monkeypatch.setattr(executors, "_OmlxAdmin", FakeAdmin)
    monkeypatch.setattr(executors, "_omlx_chat_completion", fake_chat)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][11]
    executor = LocalTaskEngineExecutor()
    output = executor.run_omlx_model(stage, GEMMA431B, "prompt")

    assert "mutually_exclusive_alternatives" in output
    assert resolve_gemma431b_omlx_model_alias(GEMMA431B) == GEMMA431B_ACTUAL_MODEL_DEFAULT
    assert ("load_model", GEMMA431B_ACTUAL_MODEL_DEFAULT) in calls
    assert ("load_model", GEMMA431B) not in calls
    assert any(call[0] == "chat" and call[1] == GEMMA431B_ACTUAL_MODEL_DEFAULT for call in calls)
    assert ("unload_all",) in calls
    assert ("unload_model", GEMMA431B_ACTUAL_MODEL_DEFAULT) in calls
    assert executor.last_executor_models["alternative_generator"] == GEMMA431B_ACTUAL_MODEL_DEFAULT


def test_alternative_generator_rejects_forbidden_actual_model_alias(monkeypatch):
    for bad in [
        LLAMA70B_ACTUAL_MODEL_DEFAULT,
        QWEN72B_ACTUAL_MODEL_DEFAULT,
        NEMOTRON120B_ACTUAL_MODEL_DEFAULT,
        "Qwen2.5-9B-Instruct-mlx",
        R1_ACTUAL_MODEL_DEFAULT,
        "DeepSeek Controller",
    ]:
        monkeypatch.setenv("HERMES_OMLX_GEMMA431B_MODEL", bad)
        try:
            resolve_gemma431b_omlx_model_alias(GEMMA431B)
        except RuntimeError as exc:
            assert "forbidden Gemma-4-31B actual model alias" in str(exc)
        else:
            raise AssertionError(f"alternative_generator must reject forbidden actual model alias: {bad}")


def test_insight_harvester_omlx_uses_same_actual_gemma431b_model(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    class FakeAdmin:
        def __init__(self, base_url, api_key):
            calls.append(("admin_init", base_url, bool(api_key)))

        def login(self):
            calls.append(("login",))
            return True

        def unload_all(self):
            calls.append(("unload_all",))

        def load_model(self, model_id):
            calls.append(("load_model", model_id))
            return {"success": True}

        def unload_model(self, model_id):
            calls.append(("unload_model", model_id))
            return {"success": True}

    def fake_chat(model, messages, *, api_key, timeout, max_tokens):
        calls.append(("chat", model, bool(api_key), timeout, max_tokens))
        return {"choices": [{"message": {"content": "cross_model_insights\nconflicts_and_tensions"}}]}

    monkeypatch.setenv("OMLX_API_KEY", "omlx-test-key")
    monkeypatch.delenv("HERMES_OMLX_GEMMA431B_MODEL", raising=False)
    monkeypatch.setattr(executors, "_OmlxAdmin", FakeAdmin)
    monkeypatch.setattr(executors, "_omlx_chat_completion", fake_chat)

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][12]
    executor = LocalTaskEngineExecutor()
    output = executor.run_omlx_model(stage, GEMMA431B, "prompt")

    assert "cross_model_insights" in output
    assert resolve_gemma431b_omlx_model_alias(GEMMA431B) == GEMMA431B_ACTUAL_MODEL_DEFAULT
    assert ("load_model", GEMMA431B_ACTUAL_MODEL_DEFAULT) in calls
    assert ("load_model", GEMMA431B) not in calls
    assert any(call[0] == "chat" and call[1] == GEMMA431B_ACTUAL_MODEL_DEFAULT for call in calls)
    assert ("unload_model", GEMMA431B_ACTUAL_MODEL_DEFAULT) in calls
    assert executor.last_executor_models["insight_harvester"] == GEMMA431B_ACTUAL_MODEL_DEFAULT


def test_l3_artifact_missing_blocks_validation(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            return {"source_candidates": [{"title": "fake"}]}

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_l1_l3_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    Path(result["run"]["stages"][-1]["artifact_path"]).unlink()

    validation = validate_pipeline(ENGINE_RESEARCH, result["run"], base_dir=tmp_path)

    assert validation["valid"] is False
    assert any("L3_r1_synthesis:artifact_path_not_found" in error for error in validation["errors"])


def test_l1_l4_smoke_writes_gemini_audit_and_stops_before_l5(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                assert model == GEMINI_HIGH
                return {"source_candidates": [{"title": "fake"}]}
            assert stage.stage_name == "L4_gemini_audit"
            assert stage.owner == GEMINI_PRO_HIGH
            assert stage.model == GEMINI_PRO_HIGH
            assert model == GEMINI_PRO_HIGH
            assert model != GEMINI_HIGH
            assert "L3_r1_synthesis" in prompt
            assert "Gemini 3.1 Pro (High)" in prompt
            self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
            return "Gemini audit body"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_l1_l4_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages] == [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
    ]
    l4 = stages[-1]
    assert l4["owner"] == GEMINI_PRO_HIGH
    assert l4["model"] == GEMINI_PRO_HIGH
    assert l4["executor_model"] == GEMINI_PRO_HIGH
    assert l4["executor_model"] != GEMINI_HIGH
    assert l4["artifact_path"].endswith("L4_gemini_audit/gemini_audit_report.md")
    assert l4["created_in_current_run"] is True
    assert l4["legacy_contaminated"] is False
    assert l4["valid_for_pipeline"] is True
    assert Path(l4["artifact_path"]).read_text(encoding="utf-8") == "Gemini audit body"
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:L5_deepseek_acceptance" in error for error in result["full_pipeline_validation"]["errors"])


def test_l4_cannot_run_when_l3_missing(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            return "should not run"

    result = run_research_l4_gemini_audit_smoke({"stages": []}, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "L4_gemini_audit"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "requires fresh L1/L2/L2_5/L3 stages" in result["run"]["stages"][-1]["error"]


def test_l4_rejects_legacy_l3_artifact(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            return "should not run"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    l1_l3 = run_research_l1_l3_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    l1_l3["run"]["stages"][3]["legacy_contaminated"] = True
    result = run_research_l4_gemini_audit_smoke(l1_l3["run"], base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "L4_gemini_audit"
    assert "legacy contaminated" in result["run"]["stages"][-1]["error"]


def test_l4_artifact_missing_blocks_validation(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
            return "Gemini audit body"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_l1_l4_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    Path(result["run"]["stages"][-1]["artifact_path"]).unlink()

    validation = validate_pipeline(ENGINE_RESEARCH, result["run"], base_dir=tmp_path)

    assert validation["valid"] is False
    assert any("L4_gemini_audit:artifact_path_not_found" in error for error in validation["errors"])


def test_l5_cannot_run_when_l4_missing(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_controller_acceptance(self, stage, packet):
            return "should not run"

    result = run_research_l5_acceptance_smoke({"stages": []}, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "L5_deepseek_acceptance"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "requires fresh L1/L2/L2_5/L3/L4 stages" in result["run"]["stages"][-1]["error"]


def test_l1_l5_smoke_accepts_research_packet_and_stops_before_decision(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            assert stage.stage_name == "L4_gemini_audit"
            self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
            return "Gemini audit body"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_l1_l5_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert result["full_pipeline_validation"]["valid"] is True
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages] == [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
    ]
    l5 = stages[-1]
    assert l5["owner"] == CONTROLLER_ACCEPTANCE
    assert l5["model"] == CONTROLLER_ACCEPTANCE
    assert l5["executor_model"] == CONTROLLER_ACCEPTANCE
    assert l5["artifact_path"].endswith("L5_deepseek_acceptance/research_evidence_packet.md")
    assert l5["created_in_current_run"] is True
    assert l5["legacy_contaminated"] is False
    assert l5["valid_for_pipeline"] is True
    packet = Path(l5["artifact_path"]).read_text(encoding="utf-8")
    assert "verdict: ACCEPTED" in packet
    assert "accepted: true" in packet
    assert "L4_gemini_audit" in packet
    assert "evidence_packet_ready_for_decision: true" in packet
    assert "final_controller_report" not in packet
    assert "final report" not in packet.lower()
    assert "最终建议" not in packet


def test_l5_accepted_research_decision_still_incomplete(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
            return "Gemini audit body"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_l1_l5_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    validation = validate_pipeline(ENGINE_RESEARCH_DECISION, result["run"], base_dir=tmp_path)

    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert validation["valid"] is False
    assert validation["pipeline_status"] == PIPELINE_BLOCKED
    assert any("missing_stage:intelligence_layer" in error for error in validation["errors"])


def test_l5_rejected_does_not_complete(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
            return "verdict: REJECTED\naccepted: false\ninsufficient evidence"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    l1_l4 = run_research_l1_l4_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_l5_acceptance_smoke(l1_l4["run"], base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "blocked"
    assert result["pipeline_status"] == PIPELINE_BLOCKED
    assert result["blocked_stage"] == "L5_deepseek_acceptance"
    l5 = result["run"]["stages"][-1]
    assert l5["status"] == "rejected"
    assert l5["valid_for_pipeline"] is False
    assert result["full_pipeline_validation"]["valid"] is False


def test_l5_artifact_missing_blocks_validation(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
            return "Gemini audit body"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_l1_l5_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    Path(result["run"]["stages"][-1]["artifact_path"]).unlink()

    validation = validate_pipeline(ENGINE_RESEARCH, result["run"], base_dir=tmp_path)

    assert validation["valid"] is False
    assert any("L5_deepseek_acceptance:artifact_path_not_found" in error for error in validation["errors"])


def test_l5_output_does_not_contain_final_report_terms(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
            return "Gemini audit body"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_l1_l5_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    packet = Path(result["run"]["stages"][-1]["artifact_path"]).read_text(encoding="utf-8")

    assert "final_controller_report" not in packet
    assert "FINAL CONTROLLER BODY" not in packet
    assert "final report" not in packet.lower()
    assert "最终建议" not in packet
    assert "长期发展的路线" not in packet


def test_research_decision_intelligence_uses_gemini_high_and_stops_before_stage8(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                assert model == GEMINI_HIGH
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                assert model == GEMINI_PRO_HIGH
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            assert stage.stage_name == "intelligence_layer"
            assert stage.owner == GEMINI_HIGH
            assert stage.model == GEMINI_HIGH
            assert model == GEMINI_HIGH
            assert "research_evidence_packet.md" in prompt
            assert ADHD_PROMPT in prompt
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "intelligence mapping only"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_decision_l1_l7_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages] == [
        "L1_gemini_search",
        "L2_ddgs_supplement",
        "L2_5_codex_evidence_organizer",
        "L3_r1_synthesis",
        "L4_gemini_audit",
        "L5_deepseek_acceptance",
        "intelligence_layer",
    ]
    intelligence = stages[-1]
    assert intelligence["owner"] == GEMINI_HIGH
    assert intelligence["model"] == GEMINI_HIGH
    assert intelligence["executor_model"] == GEMINI_HIGH
    assert intelligence["artifact_path"].endswith("intelligence_layer/intelligence_layer_report.md")
    assert Path(intelligence["artifact_path"]).read_text(encoding="utf-8") == "intelligence mapping only"
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:supplementary_search" in error for error in result["full_pipeline_validation"]["errors"])


def test_intelligence_layer_does_not_run_without_accepted_l5(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "verdict: REJECTED\naccepted: false"
            return "should not run"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    l1_l5 = run_research_l1_l5_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_intelligence_smoke(
        l1_l5["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "intelligence_layer"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "accepted research packet validation failed" in result["run"]["stages"][-1]["error"]


def test_intelligence_layer_artifact_missing_blocks_validation(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "intelligence mapping only"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_decision_l1_l7_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    Path(result["run"]["stages"][-1]["artifact_path"]).unlink()

    validation = validate_pipeline(ENGINE_RESEARCH_DECISION, result["run"], base_dir=tmp_path)

    assert validation["valid"] is False
    assert any("intelligence_layer:artifact_path_not_found" in error for error in validation["errors"])


def test_intelligence_layer_output_forbidden_final_terms_blocked(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "final_controller_report\n最终建议"

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    l1_l5 = run_research_l1_l5_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_intelligence_smoke(
        l1_l5["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "intelligence_layer"
    assert "forbidden final-output tokens" in result["run"]["stages"][-1]["error"]


def test_intelligence_layer_constraint_echo_does_not_block(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nDo not produce final report.\nThis is not a final recommendation."

        def run_ddgs(self, stage, queries):
            return [{"title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_decision_l1_l7_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["blocked_stage"] if "blocked_stage" in result else "" == ""
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"


def test_intelligence_layer_structural_final_report_blocks():
    import tools.task_engine_executors as executors

    assert "final_report_heading" in executors._intelligence_output_forbidden_tokens("# Final Controller Report\nbody")
    assert "pipeline_status=PIPELINE_COMPLETE" in executors._intelligence_output_forbidden_tokens(
        "pipeline_status=PIPELINE_COMPLETE"
    )
    assert "action_plan_recommendation_direct_advice" in executors._intelligence_output_forbidden_tokens(
        "# Action Plan\n## Recommendation\nYou should start this plan tomorrow."
    )
    assert "chinese_final_advice_heading" in executors._intelligence_output_forbidden_tokens(
        "## 行动建议\n建议你从今天开始执行。"
    )


def test_agy_alias_log_allows_early_ccpa_noise_when_override_succeeds():
    import tools.task_engine_executors as executors

    output = "\n".join(
        [
            "Model ID Gemini 3.5 Flash (High) not in local config, defaulting to CCPA",
            "Resolving model Gemini 3.5 Flash (High)",
            'Propagating selected model override to backend: label="Gemini 3.5 Flash (High)"',
            "Print mode: silent auth succeeded",
        ]
    )

    assert executors._agy_model_alias_failed(output, GEMINI_HIGH) is False


def test_agy_alias_log_blocks_ccpa_without_override():
    import tools.task_engine_executors as executors

    output = "Model ID Gemini 3.5 Flash (High) not in local config, defaulting to CCPA"

    assert executors._agy_model_alias_failed(output, GEMINI_HIGH) is True


def test_agy_preflight_success_lists_required_models(monkeypatch):
    import tools.task_engine_executors as executors

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "Gemini 3.5 Flash (High)\nGemini 3.1 Pro (High)\nOther Model\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(executors.shutil, "which", lambda name: "/opt/homebrew/bin/agy")
    monkeypatch.setattr(executors.subprocess, "run", fake_run)

    result = run_agy_preflight(timeout_s=12)

    assert result["status"] == "AGY_OK"
    assert result["blocked_stage"] == ""
    assert result["blocked_reason"] == ""
    assert result["command"] == ["/opt/homebrew/bin/agy", "models"]
    assert result["required_models"] == [GEMINI_HIGH, GEMINI_PRO_HIGH]
    assert result["missing_models"] == []
    assert GEMINI_HIGH in result["models"]
    assert GEMINI_PRO_HIGH in result["models"]
    assert calls[0][1]["timeout"] == 12


def test_agy_preflight_blocks_auth_required(monkeypatch):
    import tools.task_engine_executors as executors

    def fake_run(command, **kwargs):
        return type(
            "Result",
            (),
            {
                "returncode": 1,
                "stdout": "",
                "stderr": "You are not logged into Antigravity. Please login in your browser.",
            },
        )()

    monkeypatch.setattr(executors.shutil, "which", lambda name: "/opt/homebrew/bin/agy")
    monkeypatch.setattr(executors.subprocess, "run", fake_run)

    result = run_agy_preflight()

    assert result["status"] == "BLOCKED_STATUS"
    assert result["blocked_stage"] == "agy_preflight"
    assert result["blocked_reason"] == "AGY_AUTH_REQUIRES_USER"
    assert "not logged into Antigravity" in result["stderr_tail"]
    assert result["authorization_code_note"] == "authorization code must be entered by user manually"


def test_agy_preflight_blocks_authorization_code_required(monkeypatch):
    import tools.task_engine_executors as executors

    def fake_run(command, **kwargs):
        return type(
            "Result",
            (),
            {
                "returncode": 1,
                "stdout": "Open the browser and enter authorization code ABC123",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(executors.shutil, "which", lambda name: "/opt/homebrew/bin/agy")
    monkeypatch.setattr(executors.subprocess, "run", fake_run)

    result = run_agy_preflight()

    assert result["status"] == "BLOCKED_STATUS"
    assert result["blocked_stage"] == "agy_preflight"
    assert result["blocked_reason"] == "AGY_AUTH_REQUIRES_USER"
    assert "authorization code" in result["stdout_tail"]
    assert result["authorization_code_note"] == "authorization code must be entered by user manually"


def test_agy_preflight_blocks_silent_auth_timeout(monkeypatch):
    import tools.task_engine_executors as executors

    def fake_run(command, **kwargs):
        return type(
            "Result",
            (),
            {
                "returncode": 1,
                "stdout": "",
                "stderr": "Print mode: not authenticated, trying silent auth\nPrint mode: timed out after 1195 polls",
            },
        )()

    monkeypatch.setattr(executors.shutil, "which", lambda name: "/opt/homebrew/bin/agy")
    monkeypatch.setattr(executors.subprocess, "run", fake_run)

    result = run_agy_preflight()

    assert result["status"] == "BLOCKED_STATUS"
    assert result["blocked_stage"] == "agy_preflight"
    assert result["blocked_reason"] == "AGY_AUTH_TIMEOUT"


def test_agy_preflight_blocks_missing_required_models(monkeypatch):
    import tools.task_engine_executors as executors

    def fake_run(command, **kwargs):
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "Gemini 3.5 Flash (High)\nCCPA\n",
                "stderr": "",
            },
        )()

    monkeypatch.setattr(executors.shutil, "which", lambda name: "/opt/homebrew/bin/agy")
    monkeypatch.setattr(executors.subprocess, "run", fake_run)

    result = run_agy_preflight()

    assert result["status"] == "BLOCKED_STATUS"
    assert result["blocked_stage"] == "agy_preflight"
    assert result["blocked_reason"] == "AGY_MODEL_LIST_MISSING_REQUIRED"
    assert result["missing_models"] == [GEMINI_PRO_HIGH]


def test_stress_runner_preflight_fail_does_not_call_l1(monkeypatch, tmp_path: Path):
    calls = []

    def fake_runner_json(action, base_dir):
        calls.append(action)
        if action == "dry-run":
            return {"status": "ok", "plan": {"stage_count": 16}}
        if action == "simulated-run":
            return {
                "status": "ok",
                "pipeline_status": PIPELINE_COMPLETE,
                "validation": {"valid": True, "stage_count": 16},
            }
        if action == "agy-preflight":
            return {
                "status": "BLOCKED_STATUS",
                "blocked_stage": "agy_preflight",
                "blocked_reason": "AGY_AUTH_REQUIRES_USER",
            }
        if action == "smoke-research-l1-l2":
            raise AssertionError("L1 must not run when AGY preflight blocks")
        raise AssertionError(f"unexpected action: {action}")

    monkeypatch.setattr(stress_runner, "_run_pytest", lambda: {"passed": True, "returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(stress_runner, "_runner_json", fake_runner_json)
    monkeypatch.setattr(stress_runner, "_git_diff_summary", lambda: "")
    monkeypatch.setattr(stress_runner.sys, "argv", ["stress", "--max-rounds", "1", "--out", str(tmp_path)])

    assert stress_runner.main() == 0

    summary = json.loads((tmp_path / "round_01" / "summary.json").read_text(encoding="utf-8"))
    assert calls == ["dry-run", "simulated-run", "agy-preflight"]
    assert summary["blocked_stage"] == "agy_preflight"
    assert summary["blocked_reason"] == "AGY_AUTH_REQUIRES_USER"
    assert summary["agy_preflight"]["status"] == "BLOCKED_STATUS"
    assert summary["smoke_l1_l2"]["status"] == "skipped"
    assert not (tmp_path / "round_01" / "real_l1_l2").exists()


def test_stress_runner_preflight_success_permits_l1(monkeypatch, tmp_path: Path):
    calls = []

    def fake_runner_json(action, base_dir):
        calls.append(action)
        if action == "dry-run":
            return {"status": "ok", "plan": {"stage_count": 16}}
        if action == "simulated-run":
            return {
                "status": "ok",
                "pipeline_status": PIPELINE_COMPLETE,
                "validation": {"valid": True, "stage_count": 16},
            }
        if action == "agy-preflight":
            return {"status": "AGY_OK", "blocked_stage": "", "blocked_reason": ""}
        if action == "smoke-research-l1-l2":
            return {
                "status": "blocked",
                "pipeline_status": PIPELINE_BLOCKED,
                "blocked_stage": "L1_gemini_search",
                "error": "forced stop after verifying L1 was called",
            }
        raise AssertionError(f"unexpected action: {action}")

    monkeypatch.setattr(stress_runner, "_run_pytest", lambda: {"passed": True, "returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(stress_runner, "_runner_json", fake_runner_json)
    monkeypatch.setattr(stress_runner, "_git_diff_summary", lambda: "")
    monkeypatch.setattr(stress_runner.sys, "argv", ["stress", "--max-rounds", "1", "--out", str(tmp_path)])

    assert stress_runner.main() == 0

    summary = json.loads((tmp_path / "round_01" / "summary.json").read_text(encoding="utf-8"))
    assert calls == ["dry-run", "simulated-run", "agy-preflight", "smoke-research-l1-l2"]
    assert summary["agy_preflight"]["status"] == "AGY_OK"
    assert summary["blocked_stage"] == "L1_gemini_search"
    assert summary["blocked_reason"] == "forced stop after verifying L1 was called"


def test_omlx_preflight_blocks_when_key_missing(monkeypatch, tmp_path: Path):
    import tools.task_engine_executors as executors

    monkeypatch.delenv("OMLX_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(executors, "_decision_engine_api_config", lambda: {"api_key_env": "OMLX_API_KEY", "base_url": "http://127.0.0.1:8000/v1"})

    result = run_omlx_preflight()

    assert result["status"] == "BLOCKED_STATUS"
    assert result["blocked_stage"] == "omlx_preflight"
    assert result["blocked_reason"] == "OMLX_API_KEY_MISSING"
    assert result["key_fingerprint"] == {"present": False, "length": 0, "sha256_12": ""}


def test_omlx_preflight_loads_key_from_hermes_env_without_leaking(monkeypatch, tmp_path: Path):
    import tools.task_engine_executors as executors

    secret = "test-omlx-secret-value"
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / ".env").write_text(f"OMLX_API_KEY={secret}\n", encoding="utf-8")

    class FakeAdmin:
        def __init__(self, base_url, api_key):
            self.base_url = base_url
            self.api_key = api_key

        def login(self):
            assert self.api_key == secret
            return True

        def get_models(self):
            return [{"id": R1_ACTUAL_MODEL_DEFAULT}]

    monkeypatch.delenv("OMLX_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(executors, "_decision_engine_api_config", lambda: {"api_key_env": "OMLX_API_KEY", "base_url": "http://127.0.0.1:8000/v1"})
    monkeypatch.setattr(executors, "_OmlxAdmin", FakeAdmin)

    result = run_omlx_preflight()
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["status"] == "OMLX_OK"
    assert result["blocked_stage"] == ""
    assert result["key_source"] == str(hermes_dir / ".env")
    assert result["key_fingerprint"]["present"] is True
    assert result["key_fingerprint"]["length"] == len(secret)
    assert result["model_visible"] is True
    assert secret not in serialized
    assert "OMLX_API_KEY" in result["configured_key_env"]
    assert os.environ["OMLX_API_KEY"] == secret


def test_task_engine_runner_omlx_preflight_uses_same_config_source(monkeypatch, tmp_path: Path):
    import tools.task_engine_executors as executors

    secret = "runner-env-file-secret"
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / ".env").write_text(f"OMLX_API_KEY={secret}\n", encoding="utf-8")

    class FakeAdmin:
        def __init__(self, base_url, api_key):
            self.api_key = api_key

        def login(self):
            return self.api_key == secret

        def get_models(self):
            return [{"id": R1_ACTUAL_MODEL_DEFAULT}]

    monkeypatch.delenv("OMLX_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(executors, "_decision_engine_api_config", lambda: {"api_key_env": "OMLX_API_KEY", "base_url": "http://127.0.0.1:8000/v1"})
    monkeypatch.setattr(executors, "_OmlxAdmin", FakeAdmin)

    result = json.loads(task_engine_runner(query=ADHD_PROMPT, mode=ENGINE_RESEARCH_DECISION, action="omlx-preflight"))

    assert result["status"] == "OMLX_OK"
    assert result["key_source"] == str(hermes_dir / ".env")
    assert secret not in json.dumps(result, ensure_ascii=False)


def test_l3_omlx_auth_fail_does_not_fallback_to_other_models(monkeypatch):
    import tools.task_engine_executors as executors

    class FakeAdmin:
        def __init__(self, base_url, api_key):
            self.api_key = api_key

        def login(self):
            return False

    monkeypatch.setenv("OMLX_API_KEY", "bad-secret")
    monkeypatch.setattr(executors, "_OmlxAdmin", FakeAdmin)
    executor = LocalTaskEngineExecutor()
    stage = StageSpec("L3_r1_synthesis", R1_32B, R1_32B, ("r1_synthesis.md",))

    try:
        executor.run_omlx_model(stage, R1_32B, "prompt")
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("L3 must fail closed when OMLX admin auth fails")

    assert "OMLX_AUTH_BLOCKED" in message
    assert executor.last_executor_models["L3_r1_synthesis"] == R1_ACTUAL_MODEL_DEFAULT
    assert "Controller" not in message
    assert "Flash" not in message
    assert "Qwen72B" not in message


def test_supplementary_search_uses_ddgs_and_stops_before_structure_mapper(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map\ndecision_dimensions_for_later_stages\nopen_items_for_stage8"

        def run_ddgs(self, stage, queries):
            if stage.stage_name == "L2_ddgs_supplement":
                return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]
            assert stage.stage_name == "supplementary_search"
            assert stage.owner == "DDGS"
            assert stage.model == "DDGS"
            assert queries[:2] == [
                "ADHD parent training children",
                "behavioral parent training ADHD inattentive children",
            ]
            return [
                {
                    "query": queries[0],
                    "title": "CDC parent training",
                    "url": "https://example.test/parent-training",
                    "snippet": "Parent training evidence.",
                }
            ]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_decision_l1_l8_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages][-2:] == ["intelligence_layer", "supplementary_search"]
    supplementary = stages[-1]
    assert supplementary["owner"] == "DDGS"
    assert supplementary["model"] == "DDGS"
    assert supplementary["executor_model"] == "DDGS"
    assert supplementary["artifact_path"].endswith("supplementary_search/parent_training_supplement.md")
    report = Path(supplementary["artifact_path"]).read_text(encoding="utf-8")
    assert "https://example.test/parent-training" in report
    assert "final_controller_report" not in report
    assert "# Final Controller Report" not in report
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:structure_mapper" in error for error in result["full_pipeline_validation"]["errors"])


def test_supplementary_search_blocks_web_search_fallback(monkeypatch):
    monkeypatch.setenv("HERMES_DDGS_BACKENDS", "duckduckgo,generic_web_search")
    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][7]

    try:
        LocalTaskEngineExecutor().run_ddgs(stage, ["ADHD parent training children"])
    except RuntimeError as exc:
        assert "cannot include web_search fallback" in str(exc)
    else:
        raise AssertionError("supplementary_search must not accept generic web_search fallback")


def test_supplementary_search_blocks_without_intelligence_layer(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_ddgs(self, stage, queries):
            return [{"title": "should not run", "url": "https://example.test"}]

    result = run_research_decision_supplementary_search_smoke(
        {"stages": []},
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "supplementary_search"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "requires fresh L1-L5 plus intelligence_layer" in result["run"]["stages"][-1]["error"]


def test_supplementary_search_no_fresh_result_blocks(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            if stage.stage_name == "L2_ddgs_supplement":
                return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]
            return []

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    l1_l7 = run_research_decision_l1_l7_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_supplementary_search_smoke(
        l1_l7["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "supplementary_search"
    assert "DDGS returned no fresh result URLs" in result["run"]["stages"][-1]["error"]


def test_supplementary_search_artifact_missing_blocks_validation(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "R1 synthesis body"

    result = run_research_decision_l1_l8_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    Path(result["run"]["stages"][-1]["artifact_path"]).unlink()

    validation = validate_pipeline(ENGINE_RESEARCH_DECISION, result["run"], base_dir=tmp_path)

    assert validation["valid"] is False
    assert any("supplementary_search:artifact_path_not_found" in error for error in validation["errors"])


def test_structure_mapper_uses_qwen72b_and_stops_before_evidence_judge(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map\ndecision_dimensions_for_later_stages"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            assert stage.stage_name == "structure_mapper"
            assert stage.owner == QWEN72B
            assert stage.model == QWEN72B
            assert model == QWEN72B
            assert "parent_training_supplement.md" in prompt
            self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
            return "problem_axes\nactor_map\ndecision_questions\nevidence_slots\nunknowns_for_later_stages"

    result = run_research_decision_l1_l9_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages][-2:] == ["supplementary_search", "structure_mapper"]
    structure = stages[-1]
    assert structure["owner"] == QWEN72B
    assert structure["model"] == QWEN72B
    assert structure["executor_model"] == QWEN72B_ACTUAL_MODEL_DEFAULT
    assert structure["artifact_path"].endswith("structure_mapper/structure_mapper.md")
    report = Path(structure["artifact_path"]).read_text(encoding="utf-8")
    assert "problem_axes" in report
    assert "final_controller_report" not in report
    assert "convergence" not in report.lower()
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:evidence_judge" in error for error in result["full_pipeline_validation"]["errors"])


def test_structure_mapper_blocks_without_supplementary_search(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_omlx_model(self, stage, model, prompt):
            raise AssertionError("structure_mapper must not run without supplementary_search")

    result = run_research_decision_structure_mapper_smoke(
        {"stages": []},
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "structure_mapper"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "requires fresh L1-L8 stages" in result["run"]["stages"][-1]["error"]


def test_structure_mapper_output_forbidden_final_or_later_stage_terms_blocked(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
            return "# Final Controller Report\nconvergence_report\nfinal_controller_report"

    l1_l8 = run_research_decision_l1_l8_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_structure_mapper_smoke(
        l1_l8["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "structure_mapper"
    assert "forbidden later-stage/final tokens" in result["run"]["stages"][-1]["error"]


def test_evidence_judge_uses_nemotron_and_stops_before_premise_auditor(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes\nactor_map\ndecision_questions\nevidence_slots"
            assert stage.stage_name == "evidence_judge"
            assert stage.owner == NEMOTRON120B
            assert stage.model == NEMOTRON120B
            assert model == NEMOTRON120B
            assert "structure_mapper.md" in prompt
            self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
            return "evidence_quality_map\nstrength_by_claim\napplicability_to_user_context\nuncertainty_and_limits"

    result = run_research_decision_l1_l10_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages][-2:] == ["structure_mapper", "evidence_judge"]
    evidence = stages[-1]
    assert evidence["owner"] == NEMOTRON120B
    assert evidence["model"] == NEMOTRON120B
    assert evidence["executor_model"] == NEMOTRON120B_ACTUAL_MODEL_DEFAULT
    assert evidence["artifact_path"].endswith("evidence_judge/evidence_judge.md")
    report = Path(evidence["artifact_path"]).read_text(encoding="utf-8")
    assert "evidence_quality_map" in report
    assert "final_controller_report" not in report
    assert "convergence_report" not in report.lower()
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:premise_auditor" in error for error in result["full_pipeline_validation"]["errors"])


def test_evidence_judge_blocks_without_structure_mapper(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_omlx_model(self, stage, model, prompt):
            raise AssertionError("evidence_judge must not run without structure_mapper")

    result = run_research_decision_evidence_judge_smoke(
        {"stages": []},
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "evidence_judge"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "requires fresh L1-L9 stages" in result["run"]["stages"][-1]["error"]


def test_evidence_judge_output_forbidden_final_or_later_stage_terms_blocked(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes\nactor_map\ndecision_questions\nevidence_slots"
            self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
            return "# Final Controller Report\nconvergence_report\nfinal_controller_report"

    l1_l9 = run_research_decision_l1_l9_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_evidence_judge_smoke(
        l1_l9["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "evidence_judge"
    assert "forbidden later-stage/final tokens" in result["run"]["stages"][-1]["error"]


def test_premise_auditor_uses_llama70b_and_stops_before_alternative_generator(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes\nactor_map\ndecision_questions\nevidence_slots"
            if stage.stage_name == "evidence_judge":
                self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
                return "evidence_quality_map\nstrength_by_claim\nuncertainty_and_limits"
            assert stage.stage_name == "premise_auditor"
            assert stage.owner == LLAMA70B
            assert stage.model == LLAMA70B
            assert model == LLAMA70B
            assert "evidence_judge.md" in prompt
            self.last_executor_models[stage.stage_name] = LLAMA70B_ACTUAL_MODEL_DEFAULT
            return "implicit_premises\npremise_risks\ncounterexamples\nculture_and_school_system_differences"

    result = run_research_decision_l1_l11_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages][-2:] == ["evidence_judge", "premise_auditor"]
    premise = stages[-1]
    assert premise["owner"] == LLAMA70B
    assert premise["model"] == LLAMA70B
    assert premise["executor_model"] == LLAMA70B_ACTUAL_MODEL_DEFAULT
    assert premise["artifact_path"].endswith("premise_auditor/premise_auditor.md")
    report = Path(premise["artifact_path"]).read_text(encoding="utf-8")
    assert "implicit_premises" in report
    assert "final_controller_report" not in report
    assert "convergence_report" not in report.lower()
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:alternative_generator" in error for error in result["full_pipeline_validation"]["errors"])


def test_premise_auditor_blocks_without_evidence_judge(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_omlx_model(self, stage, model, prompt):
            raise AssertionError("premise_auditor must not run without evidence_judge")

    result = run_research_decision_premise_auditor_smoke(
        {"stages": []},
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "premise_auditor"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "requires fresh L1-L10 stages" in result["run"]["stages"][-1]["error"]


def test_premise_auditor_output_forbidden_final_or_later_stage_terms_blocked(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes\nactor_map\ndecision_questions\nevidence_slots"
            if stage.stage_name == "evidence_judge":
                self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
                return "evidence_quality_map\nstrength_by_claim\nuncertainty_and_limits"
            self.last_executor_models[stage.stage_name] = LLAMA70B_ACTUAL_MODEL_DEFAULT
            return "# Final Controller Report\nconvergence_report\nfinal_controller_report"

    l1_l10 = run_research_decision_l1_l10_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_premise_auditor_smoke(
        l1_l10["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "premise_auditor"
    assert "forbidden later-stage/final tokens" in result["run"]["stages"][-1]["error"]


def test_alternative_generator_uses_gemma431b_and_stops_before_insight_harvester(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes\nactor_map\ndecision_questions\nevidence_slots"
            if stage.stage_name == "evidence_judge":
                self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
                return "evidence_quality_map\nstrength_by_claim\nuncertainty_and_limits"
            if stage.stage_name == "premise_auditor":
                self.last_executor_models[stage.stage_name] = LLAMA70B_ACTUAL_MODEL_DEFAULT
                return "implicit_premises\npremise_risks\ncounterexamples"
            assert stage.stage_name == "alternative_generator"
            assert stage.owner == GEMMA431B
            assert stage.model == GEMMA431B
            assert model == GEMMA431B
            assert "premise_auditor.md" in prompt
            self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
            return "mutually_exclusive_alternatives\nintervention_intensity_paths\nrisk_assumption_branches"

    result = run_research_decision_l1_l12_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages][-2:] == ["premise_auditor", "alternative_generator"]
    alternative = stages[-1]
    assert alternative["owner"] == GEMMA431B
    assert alternative["model"] == GEMMA431B
    assert alternative["executor_model"] == GEMMA431B_ACTUAL_MODEL_DEFAULT
    assert alternative["artifact_path"].endswith("alternative_generator/alternative_generator.md")
    report = Path(alternative["artifact_path"]).read_text(encoding="utf-8")
    assert "mutually_exclusive_alternatives" in report
    assert "final_controller_report" not in report
    assert "convergence_report" not in report.lower()
    assert "insight_harvester" not in report.lower()
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:insight_harvester" in error for error in result["full_pipeline_validation"]["errors"])


def test_alternative_generator_blocks_without_premise_auditor(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_omlx_model(self, stage, model, prompt):
            raise AssertionError("alternative_generator must not run without premise_auditor")

    result = run_research_decision_alternative_generator_smoke(
        {"stages": []},
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "alternative_generator"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "requires fresh L1-L11 stages" in result["run"]["stages"][-1]["error"]


def test_alternative_generator_output_forbidden_final_or_later_stage_terms_blocked(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes\nactor_map\ndecision_questions\nevidence_slots"
            if stage.stage_name == "evidence_judge":
                self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
                return "evidence_quality_map\nstrength_by_claim\nuncertainty_and_limits"
            if stage.stage_name == "premise_auditor":
                self.last_executor_models[stage.stage_name] = LLAMA70B_ACTUAL_MODEL_DEFAULT
                return "implicit_premises\npremise_risks\ncounterexamples"
            self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
            return "# Final Controller Report\ninsight_harvester\nconvergence_report\nfinal_controller_report"

    l1_l11 = run_research_decision_l1_l11_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_alternative_generator_smoke(
        l1_l11["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "alternative_generator"
    assert "forbidden later-stage/final tokens" in result["run"]["stages"][-1]["error"]


def test_insight_harvester_uses_gemma431b_and_stops_before_convergence_report(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes\nactor_map\ndecision_questions\nevidence_slots"
            if stage.stage_name == "evidence_judge":
                self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
                return "evidence_quality_map\nstrength_by_claim\nuncertainty_and_limits"
            if stage.stage_name == "premise_auditor":
                self.last_executor_models[stage.stage_name] = LLAMA70B_ACTUAL_MODEL_DEFAULT
                return "implicit_premises\npremise_risks\ncounterexamples"
            if stage.stage_name == "alternative_generator":
                self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
                return "mutually_exclusive_alternatives\nintervention_intensity_paths\nrisk_assumption_branches"
            assert stage.stage_name == "insight_harvester"
            assert stage.owner == GEMMA431B
            assert stage.model == GEMMA431B
            assert model == GEMMA431B
            assert "alternative_generator.md" in prompt
            self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
            return "cross_model_insights\nconflicts_and_tensions\noutliers\ndecision_turning_points"

    result = run_research_decision_l1_l13_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages][-2:] == ["alternative_generator", "insight_harvester"]
    alternative = stages[-2]
    insight = stages[-1]
    assert insight["owner"] == GEMMA431B
    assert insight["model"] == GEMMA431B
    assert insight["executor_model"] == GEMMA431B_ACTUAL_MODEL_DEFAULT
    assert insight["artifact_path"].endswith("insight_harvester/insight_harvester.md")
    assert insight["artifact_path"] != alternative["artifact_path"]
    assert Path(insight["artifact_path"]).read_text(encoding="utf-8") != Path(alternative["artifact_path"]).read_text(encoding="utf-8")
    report = Path(insight["artifact_path"]).read_text(encoding="utf-8")
    assert "cross_model_insights" in report
    assert "final_controller_report" not in report
    assert "convergence_report" not in report.lower()
    assert "pipeline_status=PIPELINE_COMPLETE" not in report
    assert result["full_pipeline_validation"]["valid"] is False
    assert result["full_pipeline_validation"]["divergence_unique_model_count"] == 4
    assert any("missing_stage:convergence_report" in error for error in result["full_pipeline_validation"]["errors"])
    divergence_roles = {
        "structure_mapper",
        "evidence_judge",
        "premise_auditor",
        "alternative_generator",
        "insight_harvester",
    }
    by_name = {stage["stage_name"]: stage for stage in stages}
    assert all(by_name[role]["valid_for_pipeline"] is True for role in divergence_roles)
    assert len({by_name[role]["model"] for role in divergence_roles}) == 4


def test_insight_harvester_blocks_without_alternative_generator(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_omlx_model(self, stage, model, prompt):
            raise AssertionError("insight_harvester must not run without alternative_generator")

    result = run_research_decision_insight_harvester_smoke(
        {"stages": []},
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "insight_harvester"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "requires fresh L1-L12 stages" in result["run"]["stages"][-1]["error"]


def test_insight_harvester_output_forbidden_final_or_later_stage_terms_blocked(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes\nactor_map\ndecision_questions\nevidence_slots"
            if stage.stage_name == "evidence_judge":
                self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
                return "evidence_quality_map\nstrength_by_claim\nuncertainty_and_limits"
            if stage.stage_name == "premise_auditor":
                self.last_executor_models[stage.stage_name] = LLAMA70B_ACTUAL_MODEL_DEFAULT
                return "implicit_premises\npremise_risks\ncounterexamples"
            if stage.stage_name == "alternative_generator":
                self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
                return "mutually_exclusive_alternatives\nintervention_intensity_paths"
            self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
            return "# Final Controller Report\nconvergence_report\nfinal_controller_report\npipeline_status=PIPELINE_COMPLETE"

    l1_l12 = run_research_decision_l1_l12_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_insight_harvester_smoke(
        l1_l12["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "insight_harvester"
    assert "forbidden later-stage/final tokens" in result["run"]["stages"][-1]["error"]


def test_convergence_report_uses_r1_and_stops_before_external_calibration(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes\nactor_map\ndecision_questions\nevidence_slots"
            if stage.stage_name == "evidence_judge":
                self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
                return "evidence_quality_map\nstrength_by_claim\nuncertainty_and_limits"
            if stage.stage_name == "premise_auditor":
                self.last_executor_models[stage.stage_name] = LLAMA70B_ACTUAL_MODEL_DEFAULT
                return "implicit_premises\npremise_risks\ncounterexamples"
            if stage.stage_name == "alternative_generator":
                self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
                return "mutually_exclusive_alternatives\nintervention_intensity_paths"
            if stage.stage_name == "insight_harvester":
                self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
                return "cross_model_insights\nconflicts_and_tensions\ndecision_turning_points"
            assert stage.stage_name == "convergence_report"
            assert stage.owner == R1_32B
            assert stage.model == R1_32B
            assert model == R1_32B
            assert "insight_harvester.md" in prompt
            assert "r1_synthesis.md" in prompt
            assert "web_search" in prompt
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "divergence_role_summary\nconflicts_to_resolve\nconvergence_decision_framework\nuncertainty_boundaries"

    result = run_research_decision_l1_l14_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages][-2:] == ["insight_harvester", "convergence_report"]
    l3 = stages[3]
    convergence = stages[-1]
    assert convergence["owner"] == R1_32B
    assert convergence["model"] == R1_32B
    assert convergence["executor_model"] == R1_ACTUAL_MODEL_DEFAULT
    assert convergence["artifact_path"].endswith("convergence_report/convergence_report.md")
    assert convergence["artifact_path"] != l3["artifact_path"]
    report = Path(convergence["artifact_path"]).read_text(encoding="utf-8")
    assert "convergence_decision_framework" in report
    assert "final_controller_report" not in report
    assert "pipeline_status=PIPELINE_COMPLETE" not in report
    assert "web_search" not in report
    assert result["full_pipeline_validation"]["valid"] is False
    assert result["full_pipeline_validation"]["divergence_unique_model_count"] == 4
    assert any("missing_stage:external_calibration" in error for error in result["full_pipeline_validation"]["errors"])


def test_convergence_report_blocks_without_all_divergence_roles(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_omlx_model(self, stage, model, prompt):
            raise AssertionError("convergence_report must not run without all divergence roles")

    result = run_research_decision_convergence_smoke(
        {"stages": []},
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "convergence_report"
    assert result["run"]["stages"][-1]["created_in_current_run"] is False
    assert "requires fresh L1-L13 stages" in result["run"]["stages"][-1]["error"]


def test_convergence_report_blocks_when_unique_divergence_models_less_than_four(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes"
            if stage.stage_name == "evidence_judge":
                self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
                return "evidence_quality_map"
            if stage.stage_name == "premise_auditor":
                self.last_executor_models[stage.stage_name] = LLAMA70B_ACTUAL_MODEL_DEFAULT
                return "implicit_premises"
            if stage.stage_name == "alternative_generator":
                self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
                return "mutually_exclusive_alternatives"
            if stage.stage_name == "insight_harvester":
                self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
                return "cross_model_insights"
            raise AssertionError("convergence_report should be blocked before OMLX call")

    l1_l13 = run_research_decision_l1_l13_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    by_name = {stage["stage_name"]: stage for stage in l1_l13["run"]["stages"]}
    by_name["evidence_judge"]["model"] = QWEN72B

    result = run_research_decision_convergence_smoke(
        l1_l13["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "convergence_report"
    assert "unique divergence models < 4" in result["run"]["stages"][-1]["error"]


def test_convergence_report_rejects_l3_artifact_reuse(tmp_path: Path):
    class ReusingExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            self.last_executor_models[stage.stage_name] = (
                R1_ACTUAL_MODEL_DEFAULT if stage.stage_name in {"L3_r1_synthesis", "convergence_report"}
                else {
                    "structure_mapper": QWEN72B_ACTUAL_MODEL_DEFAULT,
                    "evidence_judge": NEMOTRON120B_ACTUAL_MODEL_DEFAULT,
                    "premise_auditor": LLAMA70B_ACTUAL_MODEL_DEFAULT,
                    "alternative_generator": GEMMA431B_ACTUAL_MODEL_DEFAULT,
                    "insight_harvester": GEMMA431B_ACTUAL_MODEL_DEFAULT,
                }[stage.stage_name]
            )
            return "ok"

        def write_artifact(self, stage, content, *, base_dir):
            if stage.stage_name == "convergence_report":
                outputs = {"convergence_report.md": str(Path(base_dir) / "convergence_report" / "convergence_report.md")}
                return Path(base_dir) / "L3_r1_synthesis" / "r1_synthesis.md", outputs
            return super().write_artifact(stage, content, base_dir=base_dir)

    l1_l13 = run_research_decision_l1_l13_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=ReusingExecutor())
    result = run_research_decision_convergence_smoke(
        l1_l13["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=ReusingExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "convergence_report"
    assert "artifact_path must be distinct from L3_r1_synthesis" in result["run"]["stages"][-1]["error"]


def test_convergence_report_output_forbidden_final_or_tool_chain_terms_blocked(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "L3_r1_synthesis":
                self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
                return "R1 synthesis body"
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "problem_axes"
            if stage.stage_name == "evidence_judge":
                self.last_executor_models[stage.stage_name] = NEMOTRON120B_ACTUAL_MODEL_DEFAULT
                return "evidence_quality_map"
            if stage.stage_name == "premise_auditor":
                self.last_executor_models[stage.stage_name] = LLAMA70B_ACTUAL_MODEL_DEFAULT
                return "implicit_premises"
            if stage.stage_name == "alternative_generator":
                self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
                return "mutually_exclusive_alternatives"
            if stage.stage_name == "insight_harvester":
                self.last_executor_models[stage.stage_name] = GEMMA431B_ACTUAL_MODEL_DEFAULT
                return "cross_model_insights"
            self.last_executor_models[stage.stage_name] = R1_ACTUAL_MODEL_DEFAULT
            return "# Final Controller Report\nweb_search\napi_call\ncodex_exec\nfinal_controller_report\npipeline_status=PIPELINE_COMPLETE"

    l1_l13 = run_research_decision_l1_l13_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_convergence_smoke(
        l1_l13["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "convergence_report"
    error = result["run"]["stages"][-1]["error"]
    assert "forbidden final/tool-chain tokens" in error
    assert "web_search" in error
    assert "api_call" in error
    assert "codex_exec" in error


def test_external_calibration_rejects_forbidden_executor_bindings():
    executor = LocalTaskEngineExecutor()
    for forbidden in (NEMOTRON120B, R1_32B, CONTROLLER_ACCEPTANCE, QWEN72B, LLAMA70B, GEMMA431B):
        stage = StageSpec("external_calibration", forbidden, forbidden, ("external_calibration.md",))
        try:
            executor.run_external_calibration(stage, {"prompt": "calibrate"})
        except RuntimeError as exc:
            assert "external calibration binding mismatch" in str(exc)
        else:
            raise AssertionError(f"external_calibration must reject forbidden executor binding: {forbidden}")


def test_external_calibration_discovers_chatgpt_app_bridge_wrapper_without_env(monkeypatch, tmp_path: Path):
    import tools.task_engine_executors as executors

    wrapper = tmp_path / "chatgpt_app_bridge_http_cli.py"
    wrapper.write_text("print('unused')\n", encoding="utf-8")
    monkeypatch.delenv("HERMES_GPT_BRIDGE_CMD", raising=False)
    monkeypatch.delenv("HERMES_GPT_BRIDGE_URL", raising=False)
    monkeypatch.setattr(executors, "_hermes_env_value", lambda key: "")
    monkeypatch.setattr(executors, "CHATGPT_APP_BRIDGE_WRAPPER", wrapper)

    assert executors._discover_chatgpt_app_bridge_wrapper() == wrapper


def test_external_calibration_wrapper_success_uses_gpt_bridge_without_gemini(monkeypatch, tmp_path: Path):
    import tools.task_engine_executors as executors

    secret = "super-secret-token"
    wrapper = tmp_path / "chatgpt_app_bridge_http_cli.py"
    wrapper.write_text(
        "import json\n"
        "print(json.dumps({'success': True, 'response': 'calibration_scope\\nclaim_strength_table\\ncalibration_verdict: supported'}))\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("HERMES_GPT_BRIDGE_CMD", raising=False)
    monkeypatch.delenv("HERMES_GPT_BRIDGE_URL", raising=False)
    monkeypatch.setenv("CHATGPT_BRIDGE_TOKEN", secret)
    monkeypatch.setattr(executors, "_hermes_env_value", lambda key: "")
    monkeypatch.setattr(executors, "CHATGPT_APP_BRIDGE_WRAPPER", wrapper)

    class NoGeminiExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model, timeout_s=None):
            raise AssertionError("Gemini fallback must not run when wrapper succeeds")

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][14]
    executor = NoGeminiExecutor()
    output = executor.run_external_calibration(stage, {"prompt": "calibrate this"})

    assert executor.last_executor_models["external_calibration"] == "ChatGPT App Bridge"
    assert "executor_model: ChatGPT App Bridge" in output
    assert "calibration_verdict" in output
    assert secret not in output


def test_external_calibration_wrapper_failure_falls_back_to_gemini(monkeypatch, tmp_path: Path):
    import tools.task_engine_executors as executors

    wrapper = tmp_path / "chatgpt_app_bridge_http_cli.py"
    wrapper.write_text(
        "import json, sys\n"
        "print(json.dumps({'success': False, 'error': 'worker busy'}))\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("HERMES_GPT_BRIDGE_CMD", raising=False)
    monkeypatch.delenv("HERMES_GPT_BRIDGE_URL", raising=False)
    monkeypatch.setattr(executors, "_hermes_env_value", lambda key: "")
    monkeypatch.setattr(executors, "CHATGPT_APP_BRIDGE_WRAPPER", wrapper)

    class FallbackExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model, timeout_s=None):
            assert stage.model == GEMINI_PRO_HIGH
            assert model == GEMINI_PRO_HIGH
            self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
            return "calibration_scope\nclaim_strength_table\ncalibration_verdict: plausible"

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][14]
    executor = FallbackExecutor()
    output = executor.run_external_calibration(stage, {"prompt": "calibrate this"})

    assert executor.last_executor_models["external_calibration"] == GEMINI_PRO_HIGH
    assert "GPT_BRIDGE_UNAVAILABLE:GPT_BRIDGE_WRAPPER_FAILED" in output
    assert "calibration_verdict" in output


def test_external_calibration_wrapper_absent_and_env_absent_not_configured(monkeypatch, tmp_path: Path):
    import tools.task_engine_executors as executors

    monkeypatch.delenv("HERMES_GPT_BRIDGE_CMD", raising=False)
    monkeypatch.delenv("HERMES_GPT_BRIDGE_URL", raising=False)
    monkeypatch.setattr(executors, "_hermes_env_value", lambda key: "")
    monkeypatch.setattr(executors, "CHATGPT_APP_BRIDGE_WRAPPER", tmp_path / "missing.py")
    monkeypatch.setattr(executors, "_decision_engine_bridge_script", lambda: None)

    class FailingExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model, timeout_s=None):
            raise RuntimeError("AGY_UNAVAILABLE")

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][14]
    try:
        FailingExecutor().run_external_calibration(stage, {"prompt": "calibrate this"})
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("external_calibration must block when GPT and Gemini are unavailable")

    assert "GPT_BRIDGE_UNAVAILABLE:GPT_BRIDGE_NOT_CONFIGURED" in message
    assert "AGY_UNAVAILABLE" in message


def test_external_calibration_gpt_unavailable_falls_back_to_gemini_pro(monkeypatch):
    import tools.task_engine_executors as executors

    monkeypatch.setattr(
        executors,
        "_run_gpt_bridge_calibration",
        lambda prompt: (_ for _ in ()).throw(RuntimeError("GPT_BRIDGE_AUTH_BLOCKED")),
    )

    class FallbackExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model, timeout_s=None):
            assert stage.stage_name == "external_calibration"
            assert stage.owner == GEMINI_PRO_HIGH
            assert stage.model == GEMINI_PRO_HIGH
            assert model == GEMINI_PRO_HIGH
            self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
            return "calibration_scope\nclaim_strength_table\ncalibration_verdict: plausible"

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][14]
    executor = FallbackExecutor()
    output = executor.run_external_calibration(stage, {"prompt": "calibrate this"})

    assert executor.last_executor_models["external_calibration"] == GEMINI_PRO_HIGH
    assert "executor_model: Gemini 3.1 Pro (High)" in output
    assert "GPT_BRIDGE_UNAVAILABLE:GPT_BRIDGE_AUTH_BLOCKED" in output
    assert "calibration_verdict" in output


def test_external_calibration_blocks_when_gpt_and_gemini_unavailable(monkeypatch):
    import tools.task_engine_executors as executors

    monkeypatch.setattr(
        executors,
        "_run_gpt_bridge_calibration",
        lambda prompt: (_ for _ in ()).throw(RuntimeError("GPT_BRIDGE_NOT_CONFIGURED")),
    )

    class FailingExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model, timeout_s=None):
            raise RuntimeError("AGY_AUTH_BLOCKED")

    stage = CANONICAL_STAGES[ENGINE_RESEARCH_DECISION][14]
    try:
        FailingExecutor().run_external_calibration(stage, {"prompt": "calibrate this"})
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("external_calibration must block when both GPT Bridge and Gemini are unavailable")

    assert "GPT Bridge and Gemini/agy unavailable" in message
    assert "GPT_BRIDGE_UNAVAILABLE:GPT_BRIDGE_NOT_CONFIGURED" in message
    assert "AGY_AUTH_BLOCKED" in message


def test_external_calibration_uses_bridge_or_gemini_and_stops_before_final_controller(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            actual = {
                "L3_r1_synthesis": R1_ACTUAL_MODEL_DEFAULT,
                "convergence_report": R1_ACTUAL_MODEL_DEFAULT,
                "structure_mapper": QWEN72B_ACTUAL_MODEL_DEFAULT,
                "evidence_judge": NEMOTRON120B_ACTUAL_MODEL_DEFAULT,
                "premise_auditor": LLAMA70B_ACTUAL_MODEL_DEFAULT,
                "alternative_generator": GEMMA431B_ACTUAL_MODEL_DEFAULT,
                "insight_harvester": GEMMA431B_ACTUAL_MODEL_DEFAULT,
            }[stage.stage_name]
            self.last_executor_models[stage.stage_name] = actual
            if stage.stage_name == "convergence_report":
                return "divergence_role_summary\nconvergence_decision_framework\nuncertainty_boundaries"
            return "stage body"

        def run_external_calibration(self, stage, packet):
            assert stage.stage_name == "external_calibration"
            assert stage.owner == "GPT Bridge or Gemini/agy"
            assert stage.model == "GPT Bridge or Gemini/agy"
            assert "convergence_report.md" in packet["prompt"]
            assert "research_evidence_packet.md" in packet["prompt"]
            self.last_executor_models[stage.stage_name] = "GPT Bridge"
            return "calibration_scope\nclaim_strength_table\nsupported / plausible / speculative / contradicted\ncalibration_verdict: plausible"

    result = run_research_decision_l1_l15_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    stages = result["run"]["stages"]
    assert [stage["stage_name"] for stage in stages][-2:] == ["convergence_report", "external_calibration"]
    calibration = stages[-1]
    assert calibration["owner"] == "GPT Bridge or Gemini/agy"
    assert calibration["model"] == "GPT Bridge or Gemini/agy"
    assert calibration["executor_model"] == "GPT Bridge"
    assert calibration["artifact_path"].endswith("external_calibration/external_calibration.md")
    report = Path(calibration["artifact_path"]).read_text(encoding="utf-8")
    assert "calibration_verdict" in report
    assert "final_controller_report" not in report
    assert "pipeline_status=PIPELINE_COMPLETE" not in report
    assert result["full_pipeline_validation"]["valid"] is False
    assert any("missing_stage:final_controller_report" in error for error in result["full_pipeline_validation"]["errors"])


def test_external_calibration_blocks_without_convergence_report(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_external_calibration(self, stage, packet):
            raise AssertionError("external_calibration must not run without convergence_report")

    result = run_research_decision_external_calibration_smoke(
        {"stages": []},
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "external_calibration"
    assert "requires fresh L1-L14 stages" in result["run"]["stages"][-1]["error"]


def test_external_calibration_output_forbidden_final_terms_blocked(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            actual = {
                "L3_r1_synthesis": R1_ACTUAL_MODEL_DEFAULT,
                "convergence_report": R1_ACTUAL_MODEL_DEFAULT,
                "structure_mapper": QWEN72B_ACTUAL_MODEL_DEFAULT,
                "evidence_judge": NEMOTRON120B_ACTUAL_MODEL_DEFAULT,
                "premise_auditor": LLAMA70B_ACTUAL_MODEL_DEFAULT,
                "alternative_generator": GEMMA431B_ACTUAL_MODEL_DEFAULT,
                "insight_harvester": GEMMA431B_ACTUAL_MODEL_DEFAULT,
            }[stage.stage_name]
            self.last_executor_models[stage.stage_name] = actual
            return "ok"

        def run_external_calibration(self, stage, packet):
            self.last_executor_models[stage.stage_name] = "GPT Bridge"
            return "# Final Controller Report\nfinal_controller_report\npipeline_status=PIPELINE_COMPLETE"

    l1_l14 = run_research_decision_l1_l14_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_external_calibration_smoke(
        l1_l14["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "external_calibration"
    error = result["run"]["stages"][-1]["error"]
    assert "forbidden final-output tokens" in error
    assert "final_controller_report" in error
    assert "PIPELINE_COMPLETE" in error


def test_final_controller_report_completes_16_stage_pipeline(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            actual = {
                "L3_r1_synthesis": R1_ACTUAL_MODEL_DEFAULT,
                "convergence_report": R1_ACTUAL_MODEL_DEFAULT,
                "structure_mapper": QWEN72B_ACTUAL_MODEL_DEFAULT,
                "evidence_judge": NEMOTRON120B_ACTUAL_MODEL_DEFAULT,
                "premise_auditor": LLAMA70B_ACTUAL_MODEL_DEFAULT,
                "alternative_generator": GEMMA431B_ACTUAL_MODEL_DEFAULT,
                "insight_harvester": GEMMA431B_ACTUAL_MODEL_DEFAULT,
            }[stage.stage_name]
            self.last_executor_models[stage.stage_name] = actual
            if stage.stage_name == "convergence_report":
                return "divergence_role_summary\nconflicts_to_resolve\nconvergence_decision_framework\nuncertainty_boundaries"
            return "stage body"

        def run_external_calibration(self, stage, packet):
            self.last_executor_models[stage.stage_name] = "GPT Bridge"
            return "calibration_scope\nclaim_strength_table\ncalibration_verdict: plausible"

        def run_final_controller_report(self, stage, packet):
            assert stage.stage_name == "final_controller_report"
            assert stage.owner == "Controller"
            assert stage.model == FINAL_CONTROLLER
            assert "external_calibration" in packet["excerpts"]
            assert "convergence_report" in packet["excerpts"]
            assert len(packet["stage_trace"]) == 15
            self.last_executor_models[stage.stage_name] = "Hermes Controller"
            return "# ADHD 儿童研究决策报告\n\n家长行为培训详细方案\n\n三年级准备路线"

    result = run_research_decision_l1_l16_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert result["full_pipeline_validation"]["valid"] is True
    assert result["full_pipeline_validation"]["stage_count"] == 16
    assert result["full_pipeline_validation"]["divergence_unique_model_count"] == 4
    stages = result["run"]["stages"]
    assert len([stage for stage in stages if stage["stage_name"] in {
        "structure_mapper",
        "evidence_judge",
        "premise_auditor",
        "alternative_generator",
        "insight_harvester",
    }]) == 5
    final = stages[-1]
    assert final["stage_name"] == "final_controller_report"
    assert final["owner"] == "Controller"
    assert final["model"] == FINAL_CONTROLLER
    assert final["executor_model"] == "Hermes Controller"
    assert final["artifact_path"].endswith("final_controller_report/final_decision_report.md")
    final_text = Path(final["artifact_path"]).read_text(encoding="utf-8")
    assert "家长行为培训详细方案" in final_text
    markdown = result["markdown"]
    assert "entered_engine_run_pipeline=true" in markdown
    assert "pipeline_status=PIPELINE_COMPLETE" in markdown
    assert "pipeline_validation.valid=true" in markdown
    assert "delegation_used=false" in markdown
    assert "家长行为培训详细方案" in markdown
    assert "Compact Pipeline Trace:" in markdown
    assert sum(1 for line in markdown.splitlines() if line.startswith("- ")) == 16
    assert "web_search" not in markdown
    assert "api_call" not in markdown
    assert "codex_exec" not in markdown
    assert "persona raw" not in markdown


def test_decision_final_smoke_completes_10_stage_pipeline_without_research(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            assert stage.stage_name == "intelligence_layer"
            assert "DECISION mode" in prompt
            assert "RESEARCH L1-L5" in prompt
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\ndecision_dimensions_for_later_stages"

        def run_ddgs(self, stage, queries):
            assert stage.stage_name == "supplementary_search"
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            assert "L1_gemini_search" not in prompt
            actual = {
                "convergence_report": R1_ACTUAL_MODEL_DEFAULT,
                "structure_mapper": QWEN72B_ACTUAL_MODEL_DEFAULT,
                "evidence_judge": NEMOTRON120B_ACTUAL_MODEL_DEFAULT,
                "premise_auditor": LLAMA70B_ACTUAL_MODEL_DEFAULT,
                "alternative_generator": GEMMA431B_ACTUAL_MODEL_DEFAULT,
                "insight_harvester": GEMMA431B_ACTUAL_MODEL_DEFAULT,
            }[stage.stage_name]
            self.last_executor_models[stage.stage_name] = actual
            if stage.stage_name == "convergence_report":
                return "divergence_role_summary\nconflicts_to_resolve\nconvergence_decision_framework\nuncertainty_boundaries"
            return f"{stage.stage_name} body"

        def run_external_calibration(self, stage, packet):
            assert "research_evidence_packet" not in packet["prompt"]
            self.last_executor_models[stage.stage_name] = "ChatGPT App Bridge"
            return "calibration_scope\nclaim_strength_table\ncalibration_verdict: plausible"

        def run_final_controller_report(self, stage, packet):
            assert stage.stage_name == "final_controller_report"
            assert len(packet["stage_trace"]) == 9
            assert "external_calibration" in packet["excerpts"]
            assert "L5_deepseek_acceptance" not in packet["excerpts"]
            self.last_executor_models[stage.stage_name] = "Hermes Controller"
            return "# ADHD 决策报告\n\n家长行为培训详细方案\n\n三年级准备路线"

    result = run_decision_final_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "ok"
    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert result["full_pipeline_validation"]["valid"] is True
    assert result["full_pipeline_validation"]["stage_count"] == 10
    assert result["full_pipeline_validation"]["divergence_unique_model_count"] == 4
    stages = result["run"]["stages"]
    names = [stage["stage_name"] for stage in stages]
    assert names == [stage.stage_name for stage in CANONICAL_STAGES[ENGINE_DECISION]]
    assert not any(name.startswith("L") for name in names)
    assert names.count("convergence_report") == 1
    assert [stage["model"] for stage in stages if stage["model"] == R1_32B] == [R1_32B]
    calibration = stages[8]
    assert calibration["stage_name"] == "external_calibration"
    assert calibration["executor_model"] == "ChatGPT App Bridge"
    final = stages[-1]
    assert final["artifact_path"].endswith("final_controller_report/final_decision_report.md")
    markdown = result["markdown"]
    assert "pipeline_status=PIPELINE_COMPLETE" in markdown
    assert "pipeline_validation.valid=true" in markdown
    assert sum(1 for line in markdown.splitlines() if line.startswith("- ")) == 10
    assert "L1_gemini_search" not in markdown
    assert "research_evidence_packet.md" not in markdown
    assert "web_search" not in markdown
    assert "api_call" not in markdown
    assert "codex_exec" not in markdown


def test_artifact_quality_blocks_agy_error_text_at_intelligence_layer(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            return "Error: timed out waiting for response"

        def run_ddgs(self, stage, queries):
            raise AssertionError("supplementary_search must not run after invalid intelligence artifact")

    result = run_decision_final_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "blocked"
    assert result["pipeline_status"] == PIPELINE_BLOCKED
    assert result["blocked_stage"] == "intelligence_layer"
    stage = result["run"]["stages"][-1]
    assert stage["stage_name"] == "intelligence_layer"
    assert stage["valid_for_pipeline"] is False
    assert "artifact_quality_error:error_timeout_response" in stage["error"]


def test_artifact_quality_blocks_omlx_error_text_at_structure_mapper(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nThis notes timeout risk as a planning risk, not an executor failure."

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            if stage.stage_name == "structure_mapper":
                self.last_executor_models[stage.stage_name] = QWEN72B_ACTUAL_MODEL_DEFAULT
                return "[ERROR: OMLX backend failed]"
            raise AssertionError("later OMLX stages must not run after invalid structure_mapper artifact")

    result = run_decision_final_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "structure_mapper"
    stage = result["run"]["stages"][-1]
    assert stage["stage_name"] == "structure_mapper"
    assert stage["valid_for_pipeline"] is False
    assert "artifact_quality_error:bracket_error" in stage["error"]


def test_artifact_quality_allows_normal_timeout_risk_discussion(tmp_path: Path):
    stage = CANONICAL_STAGES[ENGINE_DECISION][0]
    executor = LocalTaskEngineExecutor()
    content = "user_question_map\nThis discusses timeout risk as an operational risk, not an executor error."

    artifact_path, outputs = executor.write_artifact(stage, content, base_dir=tmp_path)
    record = executor.make_stage_record(
        stage,
        base_dir=tmp_path,
        artifact_path=artifact_path,
        outputs=outputs,
        created=True,
        valid=True,
        status="real",
        executor_model=GEMINI_HIGH,
    )

    assert record.valid_for_pipeline is True
    assert Path(artifact_path).read_text(encoding="utf-8") == content


def test_artifact_quality_token_detection_is_head_scoped():
    import tools.task_engine_executors as executors

    normal = "## Risk notes\nThe team should monitor timeout risk during external calls."
    bad = "Error: timed out waiting for response\n"
    quoted_late = "Good artifact body\n" + ("\n" * 45) + "Error: timed out waiting for response"

    assert executors._artifact_error_token(normal) == ""
    assert executors._artifact_error_token(bad) == "error_timeout_response"
    assert executors._artifact_error_token(quoted_late) == ""


def test_task_engine_runner_decision_final_action_does_not_use_research(tmp_path: Path, monkeypatch):
    import tools.task_engine_runner as runner

    calls = []

    def fake_decision_smoke(query, *, base_dir):
        calls.append((query, base_dir))
        return {
            "status": "ok",
            "pipeline_status": PIPELINE_COMPLETE,
            "full_pipeline_validation": {"valid": True, "stage_count": 10},
            "run": {
                "mode": ENGINE_DECISION,
                "execution_mode": "real-smoke-decision-final",
                "stages": [],
            },
        }

    monkeypatch.setattr(runner, "run_decision_final_smoke", fake_decision_smoke)

    result = json.loads(
        task_engine_runner(
            query="这是一个决策任务。请用 task_engine_runner full 执行决策管线。",
            mode=ENGINE_DECISION,
            action="smoke-decision-final",
            base_dir=str(tmp_path),
        )
    )

    assert result["status"] == "ok"
    assert result["pipeline_status"] == PIPELINE_COMPLETE
    assert result["artifact_dir"] == str(tmp_path)
    assert len(calls) == 1


def test_final_controller_blocks_without_external_calibration(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_final_controller_report(self, stage, packet):
            raise AssertionError("final_controller_report must not run without L1-L15")

    result = run_research_decision_final_controller_smoke(
        {"stages": []},
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "final_controller_report"
    assert "requires fresh L1-L15 stages" in result["run"]["stages"][-1]["error"]


def test_final_controller_legacy_artifact_cannot_complete(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            actual = {
                "L3_r1_synthesis": R1_ACTUAL_MODEL_DEFAULT,
                "convergence_report": R1_ACTUAL_MODEL_DEFAULT,
                "structure_mapper": QWEN72B_ACTUAL_MODEL_DEFAULT,
                "evidence_judge": NEMOTRON120B_ACTUAL_MODEL_DEFAULT,
                "premise_auditor": LLAMA70B_ACTUAL_MODEL_DEFAULT,
                "alternative_generator": GEMMA431B_ACTUAL_MODEL_DEFAULT,
                "insight_harvester": GEMMA431B_ACTUAL_MODEL_DEFAULT,
            }[stage.stage_name]
            self.last_executor_models[stage.stage_name] = actual
            return "ok"

        def run_external_calibration(self, stage, packet):
            self.last_executor_models[stage.stage_name] = "GPT Bridge"
            return "calibration_verdict: plausible"

        def run_final_controller_report(self, stage, packet):
            raise AssertionError("final_controller_report must not run with legacy external_calibration")

    l1_l15 = run_research_decision_l1_l15_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    l1_l15["run"]["stages"][-1]["legacy_contaminated"] = True

    result = run_research_decision_final_controller_smoke(
        l1_l15["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "final_controller_report"
    assert "external_calibration is legacy contaminated" in result["run"]["stages"][-1]["error"]


def test_final_controller_output_forbidden_tool_chain_blocked(tmp_path: Path):
    class FakeExecutor(LocalTaskEngineExecutor):
        def run_agy_gemini(self, stage, prompt, model):
            if stage.stage_name == "L1_gemini_search":
                return {"source_candidates": [{"title": "fake"}]}
            if stage.stage_name == "L4_gemini_audit":
                self.last_executor_models[stage.stage_name] = GEMINI_PRO_HIGH
                return "Gemini audit body"
            self.last_executor_models[stage.stage_name] = GEMINI_HIGH
            return "user_question_map\nresearch_packet_map"

        def run_ddgs(self, stage, queries):
            return [{"query": queries[0], "title": "fake ddgs", "url": "https://example.test/ddgs"}]

        def run_omlx_model(self, stage, model, prompt):
            actual = {
                "L3_r1_synthesis": R1_ACTUAL_MODEL_DEFAULT,
                "convergence_report": R1_ACTUAL_MODEL_DEFAULT,
                "structure_mapper": QWEN72B_ACTUAL_MODEL_DEFAULT,
                "evidence_judge": NEMOTRON120B_ACTUAL_MODEL_DEFAULT,
                "premise_auditor": LLAMA70B_ACTUAL_MODEL_DEFAULT,
                "alternative_generator": GEMMA431B_ACTUAL_MODEL_DEFAULT,
                "insight_harvester": GEMMA431B_ACTUAL_MODEL_DEFAULT,
            }[stage.stage_name]
            self.last_executor_models[stage.stage_name] = actual
            return "ok"

        def run_external_calibration(self, stage, packet):
            self.last_executor_models[stage.stage_name] = "GPT Bridge"
            return "calibration_verdict: plausible"

        def run_final_controller_report(self, stage, packet):
            self.last_executor_models[stage.stage_name] = "Hermes Controller"
            return "# ADHD 儿童研究决策报告\nweb_search\napi_call\ncodex_exec"

    l1_l15 = run_research_decision_l1_l15_smoke(ADHD_PROMPT, base_dir=tmp_path, executor=FakeExecutor())
    result = run_research_decision_final_controller_smoke(
        l1_l15["run"],
        query=ADHD_PROMPT,
        base_dir=tmp_path,
        executor=FakeExecutor(),
    )

    assert result["status"] == "blocked"
    assert result["blocked_stage"] == "final_controller_report"
    error = result["run"]["stages"][-1]["error"]
    assert "forbidden raw/tool-chain tokens" in error
    assert "web_search" in error
    assert "api_call" in error
    assert "codex_exec" in error


def test_nightly_runner_parses_completed_stress_stdout(monkeypatch):
    complete = _complete_stress_summary()

    def fake_run(command, *, timeout):
        if "work/stress_task_engine_adhd.py" in command:
            return _child_result(stdout=json.dumps(complete), returncode=0)
        return _child_result(returncode=0)

    monkeypatch.setattr(nightly_runner, "_run", fake_run)
    monkeypatch.setattr(nightly_runner, "_changed_files", lambda: [])
    monkeypatch.setattr(nightly_runner, "_legacy_parity_diff", lambda: {"ok": True, "diff": []})

    result = nightly_runner.run_round(1, 0)

    assert result["stress_status"] == "passed"
    assert result["stress_summary_source"] == "stdout"
    assert result["runner_timeout"] is False
    assert result["child_process_timeout"] is False
    assert result["pipeline_blocked"] is False
    assert result["blocked_stage"] == ""
    assert result["next_action"] == "final_controller_report_passed_pipeline_complete"


def test_nightly_runner_timeout_after_completed_stress_is_runner_timeout_not_pipeline_blocker(monkeypatch):
    complete = _complete_stress_summary()

    def fake_run(command, *, timeout):
        if "work/stress_task_engine_adhd.py" in command:
            return _child_result(
                returncode=124,
                stderr="timeout after 1800s",
                timed_out=True,
            )
        return _child_result(returncode=0)

    monkeypatch.setattr(nightly_runner, "_run", fake_run)
    monkeypatch.setattr(nightly_runner, "_changed_files", lambda: [])
    monkeypatch.setattr(nightly_runner, "_legacy_parity_diff", lambda: {"ok": True, "diff": []})
    monkeypatch.setattr(nightly_runner, "_latest_stress_summary_from_file", lambda: complete)

    result = nightly_runner.run_round(2, 0)

    assert result["stress_status"] == "passed"
    assert result["stress_summary_source"] == "summary_file"
    assert result["runner_timeout"] is True
    assert result["child_process_timeout"] is True
    assert result["child_stderr_tail"].endswith("timeout after 1800s")
    assert result["pipeline_blocked"] is False
    assert result["external_blocker"] is False
    assert result["blocked_stage"] == ""
    assert result["blocked_reason"] == ""
    assert result["next_action"] == "inspect_runner_timeout_after_completed_stress"


def test_nightly_runner_records_real_pipeline_block_from_stress(monkeypatch):
    blocked = _complete_stress_summary()
    blocked["blocked_stage"] = "L2_ddgs_supplement"
    blocked["blocked_reason"] = "DDGS returned no fresh hits"
    blocked["next_action"] = "fix_ddgs_real_search_adapter_then_rerun"

    def fake_run(command, *, timeout):
        if "work/stress_task_engine_adhd.py" in command:
            return _child_result(stdout=json.dumps(blocked), returncode=0)
        return _child_result(returncode=0)

    monkeypatch.setattr(nightly_runner, "_run", fake_run)
    monkeypatch.setattr(nightly_runner, "_changed_files", lambda: [])
    monkeypatch.setattr(nightly_runner, "_legacy_parity_diff", lambda: {"ok": True, "diff": []})

    result = nightly_runner.run_round(1, 0)

    assert result["stress_status"] == "passed"
    assert result["runner_timeout"] is False
    assert result["pipeline_blocked"] is True
    assert result["external_blocker"] is True
    assert result["blocked_stage"] == "L2_ddgs_supplement"
    assert result["blocked_reason"] == "DDGS returned no fresh hits"
    assert result["next_action"] == "stop_external_blocker"


def _complete_stress_summary() -> dict:
    return {
        "round_id": "round_01",
        "pytest": {"passed": True, "returncode": 0},
        "l5_deepseek_acceptance_smoke": {
            "status": "ok",
            "pipeline_status": PIPELINE_COMPLETE,
        },
        "evidence_judge_smoke": {
            "status": "ok",
            "pipeline_status": "PIPELINE_INCOMPLETE",
        },
        "premise_auditor_smoke": {
            "status": "ok",
            "pipeline_status": "PIPELINE_INCOMPLETE",
        },
        "alternative_generator_smoke": {
            "status": "ok",
            "pipeline_status": "PIPELINE_INCOMPLETE",
        },
        "insight_harvester_smoke": {
            "status": "ok",
            "pipeline_status": "PIPELINE_INCOMPLETE",
        },
        "convergence_report_smoke": {
            "status": "ok",
            "pipeline_status": "PIPELINE_INCOMPLETE",
        },
        "external_calibration_smoke": {
            "status": "ok",
            "pipeline_status": "PIPELINE_INCOMPLETE",
        },
        "final_controller_report_smoke": {
            "status": "ok",
            "pipeline_status": PIPELINE_COMPLETE,
        },
        "blocked_stage": "",
        "blocked_reason": "",
        "any_contract_violation": False,
        "next_action": "final_controller_report_passed_pipeline_complete",
    }


def _child_result(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    timed_out: bool = False,
) -> dict:
    return {
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_seconds": 0.1,
        "timed_out": timed_out,
    }


def _make_run(tmp_path: Path, mode: str) -> dict:
    stages = []
    for spec in CANONICAL_STAGES[mode]:
        stage_dir = tmp_path / spec.stage_name
        stage_dir.mkdir()

        if spec.stage_name == "L2_5_codex_evidence_organizer":
            for name in (
                "source_candidates.json",
                "ddgs_gap_sources.json",
                "evidence_runner_001.request.md",
                "evidence_runner_001.request.json",
                "sources.csv",
                "evidence.csv",
                "claims.md",
                "gaps.md",
            ):
                (stage_dir / name).write_text("ok", encoding="utf-8")
            artifact = stage_dir
        elif spec.required_outputs != ("artifact_path",):
            artifact = stage_dir / spec.required_outputs[0]
            body = "ok"
            if spec.stage_name == "L5_deepseek_acceptance":
                body = "\n".join(
                    [
                        "research_evidence_packet",
                        "verdict: ACCEPTED",
                        "accepted: true",
                        "checked_stages: [L1_gemini_search, L2_ddgs_supplement, L2_5_codex_evidence_organizer, L3_r1_synthesis, L4_gemini_audit]",
                        "missing_or_invalid_artifacts: []",
                        "audit_summary: ok",
                        "evidence_packet_ready_for_decision: true",
                    ]
                )
            if spec.stage_name == "final_controller_report":
                body = "FINAL CONTROLLER BODY"
            artifact.write_text(body, encoding="utf-8")
        else:
            artifact = stage_dir / "report.md"
            body = "ok"
            if spec.stage_name == "convergence_report":
                body = "R1 CONVERGENCE BODY"
            if spec.stage_name == "final_controller_report":
                body = "FINAL CONTROLLER BODY"
            artifact.write_text(body, encoding="utf-8")

        stages.append(
            {
                "stage_name": spec.stage_name,
                "owner": spec.owner,
                "model": spec.model,
                "artifact_path": str(artifact),
                "created_in_current_run": True,
                "legacy_contaminated": False,
                "valid_for_pipeline": True,
            }
        )
    return {"stages": stages}
