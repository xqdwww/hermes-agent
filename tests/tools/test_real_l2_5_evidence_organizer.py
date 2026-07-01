from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import tools.task_engine_executors as executors
from tools.task_engine_contracts import CANONICAL_STAGES, ENGINE_RESEARCH, make_stage_record, planned_outputs


QUERY = "ADHD children parent training intervention evidence and long term treatment outcome monitoring"


def _l1_items() -> list[dict[str, str]]:
    return [
        {
            "candidate": "https://guideline.example.test/adhd-parent-training",
            "evidence_type": "clinical guideline",
            "coverage_axis": "intervention evidence",
            "why_relevant": "ADHD children parent training intervention evidence covers treatment intensity and monitoring outcomes.",
        },
        {
            "candidate": "https://review.example.test/adhd-treatment-review",
            "evidence_type": "systematic review",
            "coverage_axis": "comparison evidence",
            "why_relevant": "ADHD treatment review evidence compares parent training, medication boundaries, and uncertainty.",
        },
        {
            "candidate": "Query: ADHD children long term treatment outcome monitoring evidence gaps",
            "evidence_type": "search query",
            "coverage_axis": "outcome evidence",
            "why_relevant": "Targets ADHD long term treatment outcome monitoring and evidence gaps.",
        },
        {
            "candidate": "https://school.example.test/adhd-school-coordination",
            "evidence_type": "practice guideline",
            "coverage_axis": "contextual implementation",
            "why_relevant": "ADHD intervention evidence includes school coordination and family follow-up boundaries.",
        },
    ]


def _l2_items(query: str = QUERY) -> list[dict[str, str]]:
    return [
        {
            "query": query,
            "title": "ADHD parent training evidence review",
            "url": "https://fresh.example.test/adhd-parent-training",
            "snippet": "ADHD children parent training intervention evidence reports behavior outcomes, treatment intensity, and follow-up limits.",
        },
        {
            "query": query,
            "title": "ADHD treatment outcome monitoring",
            "url": "https://fresh.example.test/adhd-monitoring",
            "snippet": "ADHD treatment monitoring evidence discusses medication boundaries, family support, and uncertainty in long-term outcomes.",
        },
        {
            "query": query,
            "title": "ADHD school intervention coordination",
            "url": "https://fresh.example.test/adhd-school",
            "snippet": "ADHD school coordination evidence covers implementation boundaries and practical evidence gaps for families.",
        },
        {
            "query": query,
            "title": "ADHD evidence gap summary",
            "url": "https://fresh.example.test/adhd-gaps",
            "snippet": "ADHD evidence gaps remain for individual transfer, long horizon trajectories, and exact treatment dose decisions.",
        },
    ]


def _write_l1_l2_run(
    root: Path,
    *,
    query: str = QUERY,
    l1_items: list[dict[str, str]] | None = None,
    l2_items: list[dict[str, str]] | None = None,
    l1_created: bool = True,
    l2_created: bool = True,
    l1_outside: bool = False,
) -> dict:
    l1_spec, l2_spec = CANONICAL_STAGES[ENGINE_RESEARCH][:2]
    l1_outputs = planned_outputs(l1_spec, root)
    l2_outputs = planned_outputs(l2_spec, root)
    l1_path = Path(l1_outputs["source_candidates.json"])
    l2_path = Path(l2_outputs["ddgs_gap_sources.json"])
    if l1_outside:
        l1_path = root.parent / f"{root.name}_outside_source_candidates.json"
        l1_outputs = {"source_candidates.json": str(l1_path)}
    l1_path.parent.mkdir(parents=True, exist_ok=True)
    l2_path.parent.mkdir(parents=True, exist_ok=True)
    l1_payload = _l1_items() if l1_items is None else l1_items
    l2_payload = _l2_items(query) if l2_items is None else l2_items
    l1_path.write_text(json.dumps({"source_candidates": l1_payload}, ensure_ascii=False), encoding="utf-8")
    l2_path.write_text(json.dumps(l2_payload, ensure_ascii=False), encoding="utf-8")
    return {
        "mode": ENGINE_RESEARCH,
        "execution_mode": "production-research-l1-l2",
        "stages": [
            make_stage_record(
                l1_spec,
                base_dir=root,
                artifact_path=l1_path,
                outputs=l1_outputs,
                created=l1_created,
                valid=True,
                status="real",
            ).__dict__,
            make_stage_record(
                l2_spec,
                base_dir=root,
                artifact_path=l2_path,
                outputs=l2_outputs,
                created=l2_created,
                valid=True,
                status="real",
            ).__dict__,
        ],
    }


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_real_l2_5_outputs_have_real_status_and_current_run_provenance(tmp_path: Path) -> None:
    run = _write_l1_l2_run(tmp_path)

    result = executors.run_research_l2_5_evidence_organizer_real(run, base_dir=tmp_path, query=QUERY)

    assert result["status"] == "ok"
    assert result["pipeline_status"] == "PIPELINE_INCOMPLETE"
    assert result["run"]["execution_mode"] == "production-research-l1-l2-plus-l2_5"
    l2_5 = result["run"]["stages"][-1]
    assert l2_5["stage_name"] == "L2_5_codex_evidence_organizer"
    assert l2_5["status"] == "real"
    stage_dir = tmp_path / "L2_5_codex_evidence_organizer"
    for name in ("sources.csv", "evidence.csv", "claims.md", "gaps.md"):
        text = (stage_dir / name).read_text(encoding="utf-8")
        assert "handoff-smoke" not in text
        assert "fixture" not in text.lower()
        assert "cached" not in text.lower()
    analysis = executors.analyze_l2_5_evidence_organizer(tmp_path)
    assert analysis["l2_5_valid"] is True
    assert analysis["l2_5_stub_detected"] is False
    for row in _csv_rows(stage_dir / "sources.csv") + _csv_rows(stage_dir / "evidence.csv"):
        assert row["current_run_id"] == tmp_path.name
        assert row["query_hash"].startswith("sha256:")
        assert row["source_artifact_path"]
        assert row["generator"] == "real_l2_5_evidence_organizer"
        assert row["status"] == "real"
    assert f"current_run_id: {tmp_path.name}" in (stage_dir / "claims.md").read_text(encoding="utf-8")
    assert "generator: real_l2_5_evidence_organizer" in (stage_dir / "gaps.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda run, root: run["stages"].pop(0), "requires fresh L1/L2"),
        (lambda run, root: run["stages"].pop(1), "requires fresh L1/L2"),
        (lambda run, root: run["stages"][0].update({"created_in_current_run": False}), "not created_in_current_run"),
        (lambda run, root: run["stages"][0].update({"legacy_contaminated": True}), "legacy contaminated"),
        (lambda run, root: run["stages"][0].update({"valid_for_pipeline": False}), "not valid_for_pipeline"),
    ],
)
def test_real_l2_5_blocks_invalid_current_run_inputs(tmp_path: Path, mutator, expected: str) -> None:
    run = _write_l1_l2_run(tmp_path)
    mutator(run, tmp_path)

    result = executors.run_research_l2_5_evidence_organizer_real(run, base_dir=tmp_path, query=QUERY)

    assert result["status"] == "blocked"
    assert result["pipeline_status"] == "PIPELINE_BLOCKED"
    assert result["blocked_stage"] == "L2_5_codex_evidence_organizer"
    assert expected in result["blocked_reason"]


def test_real_l2_5_blocks_non_current_run_artifact_path(tmp_path: Path) -> None:
    run = _write_l1_l2_run(tmp_path, l1_outside=True)

    result = executors.run_research_l2_5_evidence_organizer_real(run, base_dir=tmp_path, query=QUERY)

    assert result["status"] == "blocked"
    assert "outside current run" in result["blocked_reason"]


def test_real_l2_5_blocks_empty_sources(tmp_path: Path) -> None:
    run = _write_l1_l2_run(tmp_path, l1_items=[], l2_items=[])

    result = executors.run_research_l2_5_evidence_organizer_real(run, base_dir=tmp_path, query=QUERY)

    assert result["status"] == "blocked"
    assert "empty L1 source_candidates" in result["blocked_reason"]


def test_real_l2_5_blocks_query_mismatch(tmp_path: Path) -> None:
    run = _write_l1_l2_run(
        tmp_path,
        l1_items=[
            {
                "candidate": "https://battery.example.test/recycling",
                "why_relevant": "Battery recycling policy and cobalt supply chain market constraints.",
            }
        ],
        l2_items=[
            {
                "query": "battery recycling cobalt policy",
                "title": "Battery recycling policy",
                "url": "https://battery.example.test/policy",
                "snippet": "Cobalt battery recycling supply chain policy and mineral market evidence.",
            }
        ],
    )

    result = executors.run_research_l2_5_evidence_organizer_real(run, base_dir=tmp_path, query=QUERY)

    assert result["status"] == "blocked"
    assert "query_mismatch" in result["blocked_reason"]


def test_real_l2_5_blocks_untraceable_l2_metadata(tmp_path: Path) -> None:
    run = _write_l1_l2_run(
        tmp_path,
        l2_items=[
            {
                "query": QUERY,
                "title": "ADHD metadata without URL",
                "url": "",
                "snippet": "ADHD children parent training evidence but no stable source URL.",
            }
        ],
    )

    result = executors.run_research_l2_5_evidence_organizer_real(run, base_dir=tmp_path, query=QUERY)

    assert result["status"] == "blocked"
    assert "L2 source metadata is untraceable" in result["blocked_reason"]
