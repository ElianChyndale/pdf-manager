from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from services.engineering_drawing.supervisor_contract import (
    file_sha256,
    validate_real_supervisor_plan,
)


def _source(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((10, 20), "ROOF", fontsize=8)
    document.save(path)
    document.close()
    return path


def _plan(source: Path) -> dict:
    digest = file_sha256(source)
    return {
        "schema": "engineering-drawing-multimodal-plan-v3",
        "planning_authority": "real_multimodal_supervisor",
        "model_name": "gpt-5.6-sol",
        "execution_policy": "strict_multimodal_execution",
        "coordinate_space": "display_page_rect",
        "render_provenance": {
            "base": "original_source_pdf",
            "source_sha256": digest,
            "reference_usage": "translation_evidence_only",
            "copied_reference_page_or_region": False,
        },
        "supervisor_invocation": {
            "verified": True,
            "mode": "codex_agent_multimodal",
            "model": "gpt-5.6-sol",
            "reasoning_profile": "light",
            "agent_id": "test-supervisor",
            "source_sha256": digest,
            "started_at": "2026-07-30T00:00:00Z",
            "completed_at": "2026-07-30T00:00:01Z",
            "response_sha256": "a" * 64,
        },
        "page_image_evidence": [
            {"page_index": 0, "visual_inspection": True, "image_sha256": "b" * 64}
        ],
        "page_type": "engineering_drawing",
        "delivery_mode": "inline_bilingual",
        "page_region_map": [
            {
                "region_id": "p1-drawing",
                "region_type": "drawing_body",
                "page_index": 0,
                "bbox": [0, 0, 200, 120],
                "visual_reason": "The page is a simple drawing body with no panel.",
                "strategy": "blue_preserve_source",
                "decision_source": "multimodal_visual_plan",
            }
        ],
        "coverage_inventory": [
            {
                "candidate_id": "roof-1",
                "page_index": 0,
                "source_text": "ROOF",
                "source_bbox": [10, 10, 35, 22],
                "status": "translated",
                "rotation": 0,
            }
        ],
        "coverage_evidence": [
            {
                "page_index": 0,
                "source": "native_pdf_text",
                "candidate_ids": ["roof-1"],
                "uncovered_candidate_ids": [],
            }
        ],
        "semantic_blocks": [
            {
                "block_id": "roof-1",
                "member_ids": ["roof-1"],
                "page_index": 0,
                "page_region_id": "p1-drawing",
                "region_type": "drawing_body",
                "source_text": "ROOF",
                "source_bbox": [10, 10, 35, 22],
                "translated_text": "屋面",
                "coverage_status": "translated",
                "placement": {
                    "render_mode": "preserve_source_blue_chinese",
                    "side": "right",
                    "mode": "inline",
                    "target_bbox": [38, 10, 60, 22],
                    "render_text": "屋面",
                    "font_size": 6,
                    "color": [0.05, 0.16, 0.45],
                    "rotation": 0,
                },
            }
        ],
        "unexplained_region_ids": [],
    }


def test_native_pdf_text_must_be_closed_by_coverage_inventory(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["coverage_inventory"][0]["source_text"] = "RIDGE"
    plan["semantic_blocks"][0]["source_text"] = "RIDGE"
    with pytest.raises(ValueError, match="native source text is not covered"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_translated_semantic_block_requires_its_own_source_geometry(tmp_path: Path) -> None:
    """A signed coverage ledger is not enough to make a block executable."""
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["semantic_blocks"][0].pop("source_bbox")
    with pytest.raises(ValueError, match="requires source_bbox"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_coverage_evidence_cannot_be_empty_or_self_inconsistent(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["coverage_evidence"] = []
    with pytest.raises(ValueError, match="coverage_evidence"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)

    plan = _plan(source)
    plan["coverage_evidence"][0]["candidate_ids"] = []
    with pytest.raises(ValueError, match="coverage_evidence"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_translation_rotation_must_match_source_rotation(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["coverage_inventory"][0]["rotation"] = 90
    with pytest.raises(ValueError, match="rotation"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_directory_cells_require_source_and_chinese_render_runs(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["page_type"] = "dense_drawing_index"
    plan["delivery_mode"] = "opaque_bilingual_reflow"
    plan["page_region_map"][0]["region_type"] = "directory_index"
    block = plan["semantic_blocks"][0]
    block.update({"region_type": "directory_index", "cell_id": "cell-1"})
    block["placement"].update(
        {
            "mode": "table_cell",
            "preserve_source": False,
            "exact_ink_masks": [[10, 10, 35, 22]],
                "render_runs": [
                {
                    "text": "屋面",
                    "bbox": [10, 10, 35, 22],
                    "font_size": 6,
                    "color": [0, 0, 0],
                    "rotation": 0,
                }
                ],
                "render_mode": "opaque_bilingual_reflow",
                "old_source_glyphs_visible": False,
                "partial_mask_overlap": False,
                "mask_protection_audit": {"protected_intersection_area": 0.0, "row_numbers_source_match": True, "minimum_clearance_pt": 1.5},
        }
    )
    with pytest.raises(ValueError, match="source plus Chinese"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_directory_and_company_tiny_type_is_release_blocking(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["page_type"] = "dense_drawing_index"
    plan["delivery_mode"] = "opaque_bilingual_reflow"
    plan["page_region_map"][0]["region_type"] = "directory_index"
    block = plan["semantic_blocks"][0]
    block.update({"region_type": "directory_index", "cell_id": "cell-1"})
    block["placement"].update(
        {
            "mode": "table_cell",
            "preserve_source": False,
            "exact_ink_masks": [[10, 10, 35, 22]],
                "render_runs": [
                {"text": "ROOF", "bbox": [10, 10, 35, 16], "font_size": 5, "color": [0, 0, 0], "rotation": 0},
                {"text": "屋面", "bbox": [10, 16, 35, 22], "font_size": 5, "color": [0, 0, 0], "rotation": 0},
                ],
                "render_mode": "opaque_bilingual_reflow",
                "old_source_glyphs_visible": False,
                "partial_mask_overlap": False,
                "mask_protection_audit": {"protected_intersection_area": 0.0, "row_numbers_source_match": True, "minimum_clearance_pt": 1.5},
        }
    )
    with pytest.raises(ValueError, match="directory.*6.8"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_drawing_group_cannot_merge_labels_across_a_large_page_area(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["coverage_inventory"].append(
        {
            "candidate_id": "ridge-1",
            "page_index": 0,
            "source_text": "RIDGE",
            "source_bbox": [160, 90, 195, 102],
            "status": "translated",
            "rotation": 0,
        }
    )
    plan["coverage_evidence"][0]["candidate_ids"].append("ridge-1")
    block = plan["semantic_blocks"][0]
    block["member_ids"].append("ridge-1")
    block["source_bbox"] = [10, 10, 195, 102]
    block["placement"]["group_layout"] = {
        "independent_fragment_placement": False,
    }
    with pytest.raises(ValueError, match="spatially incoherent"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_declared_model_name_without_invocation_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan.pop("supervisor_invocation")
    with pytest.raises(ValueError, match="supervisor_invocation"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_production_supervisor_contract_rejects_non_sol_light_model(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["supervisor_invocation"]["model"] = "gpt-5.6-terra"
    plan["supervisor_invocation"]["reasoning_profile"] = "high"
    with pytest.raises(ValueError, match="gpt-5.6-sol"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_real_supervisor_plan_requires_final_review_for_release(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    assert validate_real_supervisor_plan(plan, source_pdf_path=source)["planning_authority"] == "real_multimodal_supervisor"
    with pytest.raises(ValueError, match="final_visual_review"):
        validate_real_supervisor_plan(plan, source_pdf_path=source, require_final_review=True)
    plan["final_visual_review"] = {
        "same_supervisor": True,
        "status": "accepted",
        "questions": {
            "chinese_understandable": True,
            "association_clear": True,
            "no_omission_or_damage": True,
        },
        "findings": [],
    }
    validate_real_supervisor_plan(plan, source_pdf_path=source, require_final_review=True)


def test_unexplained_visual_region_blocks_execution(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["unexplained_region_ids"] = ["p1-unknown"]
    with pytest.raises(ValueError, match="unexplained"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_placeholder_source_text_blocks_execution(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["coverage_inventory"][0]["source_text"] = "VISIBLE RULED TITLE CELL ROW 1"
    plan["semantic_blocks"][0]["source_text"] = "VISIBLE RULED TITLE CELL ROW 1"
    with pytest.raises(ValueError, match="placeholder"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)


def test_manual_review_needs_original_pdf_six_x_individual_glyph_evidence(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    plan = _plan(source)
    plan["coverage_inventory"][0].update(
        {"source_text": "R?OF", "status": "manual_review", "reason": "One glyph remains unclear."}
    )
    plan["semantic_blocks"][0].update({"source_text": "R?OF", "coverage_status": "manual_review"})
    with pytest.raises(ValueError, match="six_x_inspection"):
        validate_real_supervisor_plan(plan, source_pdf_path=source)
    plan["coverage_inventory"][0]["six_x_inspection"] = {
        "source": "original_source_pdf",
        "source_pdf_sha256": file_sha256(source),
        "zoom_multiplier": 6,
        "result": "individual_glyph_illegible",
        "crop_reference": "page-0001/roof-glyph-6x.png",
        "glyph_bbox": [20, 10, 25, 22],
        "observed_context": "R?OF beside roof outline",
    }
    validate_real_supervisor_plan(plan, source_pdf_path=source)
