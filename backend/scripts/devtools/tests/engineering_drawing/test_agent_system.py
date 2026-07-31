from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from services.engineering_drawing.agent_system import (
    AGENT_NAME,
    EngineeringDrawingAgent,
    STRICT_GATES,
    validate_decision_ledger_coverage,
)
from services.engineering_drawing.batch import run_batch


def _pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=100, height=100)
    page.insert_text((10, 20), "DRAWING TITLE", fontsize=8)
    document.save(path)
    document.close()
    return path


def test_manifest_freezes_original_and_evidence_only_reference(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "source.pdf")
    reference = _pdf(tmp_path / "reference.pdf")
    agent = EngineeringDrawingAgent()
    manifest = agent.build_manifest(source, reference_pdf=reference)
    assert manifest["agent_name"] == AGENT_NAME
    assert manifest["supervisor_count"] == 1
    assert manifest["render_provenance"]["base"] == "original_source_pdf"
    assert manifest["render_provenance"]["copied_reference_page_or_region"] is False
    assert manifest["reference"]["usage"] == "translation_evidence_only"
    assert STRICT_GATES["normal_zoom_readability"] is True


def test_agent_rejects_parallel_or_reference_base() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        EngineeringDrawingAgent.validate_single_supervisor_plan({"supervisor_count": 2})
    with pytest.raises(ValueError, match="original source"):
        EngineeringDrawingAgent.validate_single_supervisor_plan(
            {
                "supervisor_count": 1,
                "render_provenance": {
                    "base": "reference_pdf",
                    "copied_reference_page_or_region": False,
                },
            }
        )


def test_release_decision_uses_hard_findings_only() -> None:
    result = EngineeringDrawingAgent.release_decision(
        {
            "status": "accepted",
            "findings": [
                {"code": "leader_crosses_ordinary_line", "reason": "soft"},
                {"code": "omission", "reason": "missing paragraph"},
            ],
        }
    )
    assert result["passed"] is False
    assert len(result["blocking_findings"]) == 1
    assert result["normal_zoom_readability_is_release_gate"] is True


def test_legacy_batch_cannot_bypass_supervisor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENGINEERING_DRAWING_ALLOW_LEGACY_BATCH", raising=False)
    with pytest.raises(RuntimeError, match="legacy engineering-drawing batch is disabled"):
        run_batch(root=tmp_path, output_root=tmp_path / "output")


def test_page_packet_preserves_each_text_lines_local_rotation(tmp_path: Path) -> None:
    source = tmp_path / "rotated-label.pdf"
    document = fitz.open()
    page = document.new_page(width=160, height=120)
    page.insert_text((20, 100), "VERTICAL LABEL", fontsize=8, rotate=90)
    document.save(source)
    document.close()
    agent = EngineeringDrawingAgent()
    manifest = agent.build_manifest(source)
    packet = agent.build_page_packet(source, 0, manifest=manifest, output_dir=tmp_path / "packet")
    assert packet["source_text_lines"][0]["rotation"] == 90
    assert packet["source_text_lines"][0]["line_id"] == "p001-line-00001"


def test_page_packet_gives_supervisor_one_bounded_three_pass_workflow(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "source.pdf")
    agent = EngineeringDrawingAgent()
    manifest = agent.build_manifest(source)
    packet = agent.build_page_packet(source, 0, manifest=manifest, output_dir=tmp_path / "packet")
    workflow = packet["supervisor_instructions"]["bounded_workflow"]
    assert [step["name"] for step in workflow] == [
        "plan_once",
        "targeted_difference_scan_once",
        "rendered_candidate_review_once",
    ]
    assert packet["supervisor_instructions"]["repair_policy"]["maximum_local_repairs"] == 1
    assert packet["supervisor_instructions"]["repair_policy"]["full_page_replan_for_soft_findings"] is False


def test_decision_ledger_rejects_any_unbound_source_line() -> None:
    source_lines = [
        {"line_id": "p001-line-00001", "text": "COPPER TAPE", "zone_hint": "drawing_body"},
        {"line_id": "p001-line-00002", "text": "MAIN CONTRACTOR", "zone_hint": "sidebar_footer"},
    ]
    ledger = {
        "blocks": [
            {
                "block_id": "body-1",
                "source_ids": ["p001-line-00001"],
                "source_text": "COPPER TAPE",
                "translation": "铜带",
                "zone": "drawing_body",
            }
        ],
        "literal_only_ids": [],
    }
    with pytest.raises(ValueError, match="unbound source lines.*p001-line-00002"):
        validate_decision_ledger_coverage(source_lines=source_lines, ledger=ledger)


def test_decision_ledger_requires_complete_member_text_and_zone_closure() -> None:
    source_lines = [
        {"line_id": "p001-line-00001", "text": "PLATE TYPE TEST CLAMP", "zone_hint": "drawing_body"},
        {"line_id": "p001-line-00002", "text": "COVERED IN METAL BOX", "zone_hint": "drawing_body"},
    ]
    ledger = {
        "blocks": [
            {
                "block_id": "callout-1",
                "source_ids": ["p001-line-00001", "p001-line-00002"],
                "source_text": "PLATE TYPE TEST CLAMP",
                "translation": "板式测试夹",
                "zone": "drawing_body",
            }
        ],
        "literal_only_ids": [],
    }
    with pytest.raises(ValueError, match="does not preserve all member text"):
        validate_decision_ledger_coverage(source_lines=source_lines, ledger=ledger)
    ledger["blocks"][0]["source_text"] = "PLATE TYPE TEST CLAMP / COVERED IN METAL BOX"
    audit = validate_decision_ledger_coverage(source_lines=source_lines, ledger=ledger)
    assert audit["overall_closure_ratio"] == 1.0
    assert audit["zone_closure"]["drawing_body"] == 1.0


def test_long_project_description_rejects_token_chinese_translation() -> None:
    source_lines = [
        {
            "line_id": "p001-line-00001",
            "text": "PROPOSED DEVELOPMENT OF PROJECT DATA CENTER WHICH CONSISTS OF A WATER TREATMENT PLANT AND A GUARDHOUSE",
            "zone_hint": "sidebar",
        }
    ]
    ledger = {
        "blocks": [
            {
                "block_id": "project-description",
                "source_ids": ["p001-line-00001"],
                "source_text": source_lines[0]["text"],
                "translation": "项目说明",
                "zone": "sidebar",
            }
        ],
        "literal_only_ids": [],
    }
    with pytest.raises(ValueError, match="implausibly short"):
        validate_decision_ledger_coverage(source_lines=source_lines, ledger=ledger)
