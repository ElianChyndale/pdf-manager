from pathlib import Path

import fitz
import pytest

from services.engineering_drawing.codex_review import apply_codex_review_plan
from services.engineering_drawing.codex_review import build_codex_review_package
from services.engineering_drawing.codex_review import validate_codex_review_plan
from services.engineering_drawing.cli import _parser
from services.engineering_drawing.workflow_policy import WORKFLOW_VERSION


def _base_regions() -> list[dict]:
    return [
        {
            "region_id": "keep",
            "page_index": 0,
            "source_text": "DRAWING TITLE",
            "translated_text": "图纸标题",
            "bbox": [20, 20, 120, 35],
            "action": "translate",
            "qa_flags": [],
        },
        {
            "region_id": "duplicate",
            "page_index": 0,
            "source_text": "DRAWING TITLE",
            "translated_text": "图纸标题",
            "bbox": [20, 20, 120, 35],
            "action": "translate",
            "qa_flags": [],
        },
    ]


def _plan() -> dict:
    return {
        "schema": "engineering-drawing-codex-review-v1",
        "model": "gpt-5.6-sol",
        "reasoning_profile": "light",
        "supervisor_adapter": "codex-sol-light",
        "workflow_version": WORKFLOW_VERSION,
        "status": "approved",
        "source_line_ids": ["line-keep", "line-addition"],
        "page_sizes": [[300, 200]],
        "remove_region_ids": ["duplicate"],
        "moves": [
            {
                "region_id": "keep",
                "target_bbox": [150, 20, 230, 35],
                "rotation": 0,
                "font_size": 7,
                "region_type": "drawing_body",
                "translated_text": "图纸名称",
                "reason": "Use the blank area to the right of the English label.",
            }
        ],
        "additions": [
            {
                "region_id": "sol-missing-001",
                "page_index": 0,
                "source_text": "RAW WATER TANK",
                "translated_text": "原水箱",
                "source_bbox": [20, 80, 120, 95],
                "target_bbox": [150, 80, 230, 95],
                "rotation": 0,
                "font_size": 7,
                "region_type": "drawing_body",
                "confidence": 0.99,
                "reason": "Visible source text was missing from the OCR translation set.",
            }
        ],
        "coverage": [
            {"line_id": "line-keep", "page_index": 0, "source_text": "DRAWING TITLE", "status": "translated", "reason": "Bound to move keep."},
            {"line_id": "line-addition", "page_index": 0, "source_text": "RAW WATER TANK", "status": "translated", "reason": "Bound to addition sol-missing-001."},
        ],
    }


def test_sol_review_plan_can_remove_move_and_add_regions() -> None:
    plan = validate_codex_review_plan(_plan(), page_sizes=[(300, 200)])

    reviewed = apply_codex_review_plan(_base_regions(), plan)

    assert [region["region_id"] for region in reviewed] == [
        "keep",
        "sol-missing-001",
    ]
    moved = reviewed[0]
    assert moved["review_target_bbox"] == [150.0, 20.0, 230.0, 35.0]
    assert moved["review_font_size"] == 7.0
    assert moved["translated_text"] == "图纸名称"
    assert moved["placement_decision_source"] == "codex_sol"
    addition = reviewed[1]
    assert addition["bbox"] == [20.0, 80.0, 120.0, 95.0]
    assert addition["review_target_bbox"] == [150.0, 80.0, 230.0, 95.0]
    assert addition["addition_approval"] == "ai_verified_source"
    assert addition["provenance"] == "codex_sol_review"


def test_sol_review_plan_rejects_non_sol_model_and_out_of_page_target() -> None:
    not_sol = _plan()
    not_sol["model"] = "generic-ocr-model"
    with pytest.raises(ValueError, match="Sol model"):
        validate_codex_review_plan(not_sol, page_sizes=[(300, 200)])

    outside = _plan()
    outside["moves"][0]["target_bbox"] = [250, 20, 340, 35]
    with pytest.raises(ValueError, match="outside page"):
        validate_codex_review_plan(outside, page_sizes=[(300, 200)])


def test_sol_review_plan_requires_chinese_and_reason_for_additions() -> None:
    no_chinese = _plan()
    no_chinese["additions"][0]["translated_text"] = "RAW WATER TANK"
    with pytest.raises(ValueError, match="Chinese"):
        validate_codex_review_plan(no_chinese, page_sizes=[(300, 200)])

    no_reason = _plan()
    no_reason["additions"][0]["reason"] = ""
    with pytest.raises(ValueError, match="reason"):
        validate_codex_review_plan(no_reason, page_sizes=[(300, 200)])


def test_sol_review_plan_page_sizes_can_be_read_from_pdf(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page(width=300, height=200)
    document.save(source_path)
    document.close()

    plan = validate_codex_review_plan(_plan(), source_pdf_path=source_path)

    assert plan["page_sizes"] == [[300.0, 200.0]]


def test_v4_rejects_non_sol_production_plan() -> None:
    plan = _plan()
    plan["model"] = "gpt-5.6-terra"
    plan["workflow_version"] = WORKFLOW_VERSION
    plan["moves"][0].update(
        {
            "layout_role": "title_block",
            "placement_mode": "leader",
        }
    )

    with pytest.raises(ValueError, match="Sol model"):
        validate_codex_review_plan(plan, page_sizes=[(300, 200)])


def test_cli_exposes_sol_review_package_and_plan_application() -> None:
    package = _parser().parse_args(
        [
            "sol-review-package",
            "--source",
            "source.pdf",
            "--draft",
            "draft.pdf",
            "--manifest",
            "manifest.json",
            "--placement-audit",
            "placement.json",
            "--output-dir",
            "review",
        ]
    )
    transfer = _parser().parse_args(
        [
            "legacy-transfer",
            "--source",
            "source.pdf",
            "--legacy",
            "legacy.pdf",
            "--output",
            "output.pdf",
            "--sol-review-plan",
            "sol-plan.json",
        ]
    )

    assert package.command == "sol-review-package"
    assert package.output_dir == Path("review")
    assert transfer.sol_review_plan == Path("sol-plan.json")


def test_review_package_exports_rotated_text_in_display_coordinates(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.pdf"
    draft_path = tmp_path / "draft.pdf"
    review_dir = tmp_path / "review"
    document = fitz.open()
    page = document.new_page(width=200, height=300)
    page.insert_text((20, 40), "TITLE", fontsize=10)
    page.set_rotation(270)
    document.save(source_path)
    document.save(draft_path)
    document.close()

    review_input = build_codex_review_package(
        source_pdf_path=source_path,
        draft_pdf_path=draft_path,
        regions=[],
        placement_audit=[],
        output_dir=review_dir,
        dpi=72,
    )
    payload = __import__("json").loads(review_input.read_text(encoding="utf-8"))
    bbox = fitz.Rect(payload["pages"][0]["source_text_lines"][0]["bbox"])

    assert payload["pages"][0]["size"] == [300.0, 200.0]
    assert fitz.Rect(0, 0, 300, 200).contains(bbox)


def test_review_package_freezes_dynamic_group_layout_duplicate_suppression_and_single_page_policy(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.pdf"
    draft_path = tmp_path / "draft.pdf"
    review_dir = tmp_path / "review"
    document = fitz.open()
    document.new_page(width=300, height=200)
    document.save(source_path)
    document.save(draft_path)
    document.close()

    review_input = build_codex_review_package(
        source_pdf_path=source_path,
        draft_pdf_path=draft_path,
        regions=[],
        placement_audit=[],
        output_dir=review_dir,
        dpi=72,
    )
    payload = __import__("json").loads(review_input.read_text(encoding="utf-8"))

    policy = payload["layout_policy"]
    assert policy["preferred_side"] == "dynamic_multimodal_candidate_score"
    assert policy["fallback_order"] == [
        "local_whitespace_candidates",
        "bounded_reflow",
        "short_leader",
    ]
    assert policy["automatic_left_fallback"] == "leader_required"
    # V4 keeps translations close while making readability a hard gate.
    # create a long visual detour across the drawing.
    assert policy["max_local_distance_points"] == 48
    assert policy["safe_target_max_visual_ink_ratio"] == 0.03
    assert policy["font_size_policy"] == {
        "preferred_minimum_points": 6.4,
        "emergency_minimum_points": 5.8,
        "absolute_minimum_points": 5.8,
    }
    assert "merge related fragments" in policy["semantic_group_policy"]
    assert "orthogonal" in policy["leader_policy"]
    assert "whole-group" in policy["title_block_policy"]
    instructions = " ".join(payload["instructions"])
    assert "No fixed direction" in instructions
    assert "wording evidence only" in instructions
    assert "one PDF page at a time" in instructions
