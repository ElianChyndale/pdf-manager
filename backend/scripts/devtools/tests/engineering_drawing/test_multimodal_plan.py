from __future__ import annotations

import pytest

from services.engineering_drawing.multimodal_plan import (
    _literal_only_is_semantically_safe,
    apply_multimodal_plan,
    build_supervisor_handoff,
)


def test_literal_only_is_narrow_and_rejects_language_bearing_fields() -> None:
    assert _literal_only_is_semantically_safe("ACASB/2401/MTM/WD-01")
    assert _literal_only_is_semantically_safe("4000A")
    assert _literal_only_is_semantically_safe("N.T.S")
    assert _literal_only_is_semantically_safe("A")
    assert _literal_only_is_semantically_safe("500MM(H)RCC25MMTHK")
    assert not _literal_only_is_semantically_safe("JABATAN KERJA RAYA SELANGOR")
    assert not _literal_only_is_semantically_safe("CABLE LAID IN TRENCHES")
    assert not _literal_only_is_semantically_safe("FALL")


def test_plan_merge_uses_translated_text_when_supervisor_omits_render_override() -> None:
    """A supervisor-approved block must never lose its text in executor handoff."""
    regions = apply_multimodal_plan(
        [],
        {
            "execution_policy": "strict_multimodal_execution",
            "semantic_blocks": [
                {
                    "block_id": "equipment-label",
                    "page_index": 0,
                    "source_text": "WATER TANK",
                    "source_bbox": [10, 10, 70, 20],
                    "translated_text": "水箱",
                    "coverage_status": "translated",
                    "placement": {
                        "selected_region": [80, 10, 120, 24],
                        "font_size": 6,
                        "rotation": 0,
                        "mode": "inline",
                        "side": "right",
                    },
                }
            ],
        },
    )

    assert regions[0]["render_text"] == "水箱"
from services.engineering_drawing.multimodal_plan import validate_multimodal_plan
from services.engineering_drawing.workflow_policy import WORKFLOW_VERSION


def _score_candidate(bbox: list[float]) -> dict:
    return {
        "candidate_id": "selected",
        "bbox": bbox,
        "features": {
            "source_overlap_ratio": 0.0,
            "distance_pt": 12.0,
            "protected_object_overlap_ratio": 0.0,
            "translation_overlap_ratio": 0.0,
            "engineering_ink_ratio": 0.01,
            "semantic_association": 1.0,
            "whitespace_utilization": 0.9,
            "font_fit": 0.9,
        },
    }


def _plan(*, delivery_mode: str) -> dict:
    return {
        "schema": "engineering-drawing-multimodal-plan-v3",
        "status": "prepared",
        "model_name": "gpt-5.6-sol",
        "model_provider": "openai-codex",
        "reasoning_profile": "light",
        "multimodal_page_planning": True,
        "page_type": "dense_drawing_index",
        "delivery_mode": delivery_mode,
        "coordinate_space": "display_page_rect",
        "coverage_inventory": [
            {
                "candidate_id": "row-1",
                "page_index": 0,
                "source_text": "DRAWING LIST",
                "source_bbox": [10, 10, 50, 20],
                "status": "translated",
            }
        ],
        "semantic_blocks": [
            {
                "block_id": "row-1",
                "member_ids": ["row-1"],
                "page_index": 0,
                "source_text": "DRAWING LIST",
                "source_bbox": [10, 10, 50, 20],
                "translated_text": "图纸目录",
                "coverage_status": "translated",
                "placement": {
                    "side": "right",
                    "mode": "inline",
                    "target_bbox": [55, 10, 95, 20],
                    "font_size": 3.0,
                },
            }
        ],
    }


def test_dense_drawing_index_cannot_use_inline_delivery() -> None:
    with pytest.raises(ValueError, match="require opaque_bilingual_reflow"):
        validate_multimodal_plan(_plan(delivery_mode="inline_bilingual"), page_sizes=[[100, 100]])


def test_dense_drawing_index_rejects_legacy_overlay_pair() -> None:
    with pytest.raises(ValueError, match="require opaque_bilingual_reflow"):
        validate_multimodal_plan(_plan(delivery_mode="overlay_pair"), page_sizes=[[100, 100]])


def test_natural_language_not_needed_requires_verified_low_confidence_artifact_evidence() -> None:
    payload = _plan(delivery_mode="opaque_bilingual_reflow")
    payload["coverage_inventory"][0].update({"source_text": "GARBLED OCR WORDS", "status": "not_needed", "reason": "OCR artifact"})
    payload["semantic_blocks"] = [
        {**payload["semantic_blocks"][0], "coverage_status": "literal_only", "translated_text": ""}
    ]
    with pytest.raises(ValueError, match="language-bearing"):
        validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    payload["coverage_inventory"][0]["ocr_artifact_evidence"] = {
        "provenance": "paddle_ocr", "ocr_confidence": 0.42, "visual_reviewed": True,
        "decision": "garbled_fragment", "crop_reference": "p001-crop-001.png",
    }
    normalized = validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    assert normalized["coverage_inventory"][0]["status"] == "not_needed"


def test_manual_review_requires_an_isolated_glyph_with_original_pdf_six_x_evidence() -> None:
    payload = _plan(delivery_mode="opaque_bilingual_reflow")
    payload["coverage_inventory"][0].update(
        {"source_text": "R?OF", "status": "manual_review", "reason": "One glyph is unclear."}
    )
    payload["semantic_blocks"][0].update({"source_text": "R?OF", "coverage_status": "manual_review"})
    with pytest.raises(ValueError, match="six_x_inspection"):
        validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    payload["coverage_inventory"][0]["six_x_inspection"] = {
        "source": "original_source_pdf",
        "source_pdf_sha256": "a" * 64,
        "zoom_multiplier": 6,
        "result": "individual_glyph_illegible",
        "crop_reference": "p001-r001-6x.png",
        "glyph_bbox": [20, 10, 25, 20],
        "observed_context": "R?OF label beside roof outline",
    }
    normalized = validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    assert normalized["coverage_inventory"][0]["six_x_inspection"]["zoom_multiplier"] == 6


def test_dense_drawing_index_accepts_single_page_opaque_bilingual_reflow() -> None:
    normalized = validate_multimodal_plan(_plan(delivery_mode="opaque_bilingual_reflow"), page_sizes=[[100, 100]])
    assert normalized["page_type"] == "dense_drawing_index"
    assert normalized["delivery_mode"] == "opaque_bilingual_reflow"


def test_stale_supervisor_workflow_version_must_be_replanned() -> None:
    payload = _plan(delivery_mode="opaque_bilingual_reflow")
    payload["workflow_version"] = "v3.5-group-coherent-dynamic-layout"
    with pytest.raises(ValueError, match="re-plan stale supervisor output"):
        validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    payload["workflow_version"] = WORKFLOW_VERSION
    assert validate_multimodal_plan(payload, page_sizes=[[100, 100]])["workflow_version"] == WORKFLOW_VERSION


def test_supervisor_plan_becomes_explicit_tool_handoff() -> None:
    payload = _plan(delivery_mode="inline_bilingual")
    payload["page_type"] = "architectural_roof_plan"
    payload["supervisor_plan"] = {
        "contract_version": "v3-supervisor-plan-1",
        "role": "multimodal_page_manager",
        "page_type": "architectural_roof_plan",
        "delivery_mode": "inline_bilingual",
        "ocr_tasks": [{"id": "roof-crop", "region_norm": [0, 0, 1, 1], "engine": "technical_cad_ocr"}],
        "translation_tasks": [{"id": "roof-notes", "semantic_block": "paragraph"}],
        "placement_policy": {"target": "nearby_clear_band"},
        "escalations": [],
    }
    normalized = validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    handoff = build_supervisor_handoff(normalized)
    assert handoff["schema"] == "engineering-drawing-supervisor-handoff-v1"
    assert handoff["ocr_tasks"][0]["id"] == "roof-crop"
    assert handoff["translation_tasks"][0]["id"] == "roof-notes"


def test_sol_light_remains_adapter_compatible() -> None:
    payload = _plan(delivery_mode="opaque_bilingual_reflow")
    payload.update(
        {
            "model_name": "gpt-5.6-sol",
            "reasoning_profile": "light",
            "model_capabilities": ["multimodal_page_planning"],
        }
    )
    normalized = validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    assert normalized["supervisor_adapter"] == "codex-sol-light"


def test_sol_light_is_the_active_default_adapter() -> None:
    normalized = validate_multimodal_plan(
        _plan(delivery_mode="opaque_bilingual_reflow"),
        page_sizes=[[100, 100]],
    )
    assert normalized["model_name"] == "gpt-5.6-sol"
    assert normalized["supervisor_adapter"] == "codex-sol-light"
    assert "multimodal_page_planning" in normalized["model_capabilities"]


def test_strict_execution_requires_one_final_region_without_fallbacks() -> None:
    payload = _plan(delivery_mode="opaque_bilingual_reflow")
    payload["execution_policy"] = "strict_multimodal_execution"
    payload["visual_planning_authority"] = {
        "authority": "multimodal_model",
        "sequence": "visual_design_before_ocr_execution",
        "ocr_role": "extraction_and_mask_execution_only",
        "placement_basis": "rendered_page_visual",
    }
    payload["render_provenance"] = {
        "base": "original_source_pdf",
        "source_sha256": "a" * 64,
        "reference_usage": "translation_evidence_only",
        "copied_reference_page_or_region": False,
    }
    payload["page_region_map"] = [
        {
            "region_id": "page-1-drawing",
            "region_type": "drawing_body",
            "page_index": 0,
            "bbox": [0, 0, 100, 100],
            "strategy": "blue_preserve_source",
            "decision_source": "multimodal_visual_plan",
        }
    ]
    payload["existing_translation_inventory"] = []
    payload["semantic_blocks"][0]["page_region_id"] = "page-1-drawing"
    payload["semantic_blocks"][0]["decision_source"] = "multimodal_visual_plan"
    payload["semantic_blocks"][0]["placement"].update(
        {"render_text": "图纸目录", "color": [0.05, 0.16, 0.45], "preserve_source": True}
    )
    payload["mandatory_zone_audit"] = [
        {
            "zone_id": "page-1-index",
            "zone_type": "drawing_index",
            "page_index": 0,
            "member_ids": ["row-1"],
            "block_ids": ["row-1"],
            "status": "complete",
            "decision_source": "multimodal_visual_plan",
        }
    ]
    payload["semantic_blocks"][0]["placement"]["candidate_regions"] = [
        [5, 30, 45, 40]
    ]
    with pytest.raises(ValueError, match="forbids candidate fallbacks"):
        validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    payload["semantic_blocks"][0]["placement"]["candidate_regions"] = []
    payload["semantic_blocks"][0]["placement"]["candidate_score_audit"] = [
        _score_candidate([55, 10, 95, 20])
    ]
    normalized = validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    assert normalized["execution_policy"] == "strict_multimodal_execution"

    payload["coverage_inventory"].append({
        "candidate_id": "row-2", "page_index": 0, "source_text": "CONTINUED TITLE",
        "source_bbox": [10, 21, 50, 29], "status": "translated",
    })
    payload["semantic_blocks"][0]["member_ids"].append("row-2")
    payload["mandatory_zone_audit"][0]["member_ids"].append("row-2")
    with pytest.raises(ValueError, match="requires group_layout"):
        validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    payload["semantic_blocks"][0]["placement"]["group_layout"] = {
        "placement_scope": "semantic_block",
        "group_anchor": [50, 15],
        "independent_fragment_placement": False,
        "line_break_policy": "semantic_boundaries_only",
        "group_internal_dispersion_points": 0,
        "candidate_score_audit": [{"candidate": "right", "score": 1.0}],
    }
    normalized = validate_multimodal_plan(payload, page_sizes=[[100, 100]])
    assert normalized["semantic_blocks"][0]["placement"]["group_layout"]["placement_scope"] == "semantic_block"


def test_strict_execution_rejects_ocr_as_visual_planning_authority() -> None:
    payload = _plan(delivery_mode="opaque_bilingual_reflow")
    payload["execution_policy"] = "strict_multimodal_execution"
    payload["visual_planning_authority"] = {
        "authority": "ocr",
        "sequence": "ocr_before_visual_design",
        "ocr_role": "region_planning",
        "placement_basis": "ocr_ink_boxes",
    }
    with pytest.raises(ValueError, match="visual_planning_authority.authority"):
        validate_multimodal_plan(payload, page_sizes=[[100, 100]])


def test_strict_drawing_region_rejects_black_or_source_cover() -> None:
    payload = _plan(delivery_mode="opaque_bilingual_reflow")
    payload["execution_policy"] = "strict_multimodal_execution"
    payload["visual_planning_authority"] = {
        "authority": "multimodal_model",
        "sequence": "visual_design_before_ocr_execution",
        "ocr_role": "extraction_and_mask_execution_only",
        "placement_basis": "rendered_page_visual",
    }
    payload["render_provenance"] = {
        "base": "original_source_pdf",
        "source_sha256": "b" * 64,
        "reference_usage": "translation_evidence_only",
        "copied_reference_page_or_region": False,
    }
    payload["page_region_map"] = [{
        "region_id": "body", "region_type": "drawing_body", "page_index": 0,
        "bbox": [0, 0, 100, 100], "strategy": "blue_preserve_source",
        "decision_source": "multimodal_visual_plan",
    }]
    payload["existing_translation_inventory"] = []
    block = payload["semantic_blocks"][0]
    block.update({"page_region_id": "body", "decision_source": "multimodal_visual_plan"})
    block["placement"].update({
        "render_text": "图纸目录", "color": [0, 0, 0], "preserve_source": True,
        "candidate_score_audit": [_score_candidate([55, 10, 95, 20])],
    })
    payload["mandatory_zone_audit"] = [{
        "zone_id": "body", "zone_type": "drawing_body", "page_index": 0,
        "member_ids": ["row-1"], "block_ids": ["row-1"], "status": "complete",
        "decision_source": "multimodal_visual_plan",
    }]
    with pytest.raises(ValueError, match="must be blue"):
        validate_multimodal_plan(payload, page_sizes=[[100, 100]])


def test_strict_blue_placement_requires_audited_dynamic_candidate_decision() -> None:
    payload = _plan(delivery_mode="inline_bilingual")
    payload.update(
        {
            "page_type": "architectural_roof_plan",
            "execution_policy": "strict_multimodal_execution",
            "visual_planning_authority": {
                "authority": "multimodal_model",
                "sequence": "visual_design_before_ocr_execution",
                "ocr_role": "extraction_and_mask_execution_only",
                "placement_basis": "rendered_page_visual",
            },
            "render_provenance": {
                "base": "original_source_pdf",
                "source_sha256": "c" * 64,
                "reference_usage": "translation_evidence_only",
                "copied_reference_page_or_region": False,
            },
            "page_region_map": [{
                "region_id": "roof-body",
                "region_type": "drawing_body",
                "page_index": 0,
                "bbox": [0, 0, 100, 100],
                "strategy": "blue_preserve_source",
                "decision_source": "multimodal_visual_plan",
            }],
            "existing_translation_inventory": [],
            "mandatory_zone_audit": [{
                "zone_id": "roof-body",
                "zone_type": "drawing_body",
                "page_index": 0,
                "member_ids": ["row-1"],
                "block_ids": ["row-1"],
                "status": "complete",
                "decision_source": "multimodal_visual_plan",
            }],
        }
    )
    block = payload["semantic_blocks"][0]
    block.update(
        {
            "page_region_id": "roof-body",
            "region_type": "drawing_body",
            "decision_source": "multimodal_visual_plan",
        }
    )
    block["placement"].update(
        {"render_text": "图纸目录", "color": [0.05, 0.16, 0.45], "preserve_source": True}
    )

    with pytest.raises(ValueError, match="candidate_score_audit"):
        validate_multimodal_plan(payload, page_sizes=[[100, 100]])

    block["placement"]["candidate_score_audit"] = [
        _score_candidate([55, 10, 95, 20])
    ]
    assert validate_multimodal_plan(payload, page_sizes=[[100, 100]])["semantic_blocks"][0]["block_id"] == "row-1"
