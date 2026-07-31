from __future__ import annotations

import fitz

from services.engineering_drawing.overlay_pair import render_opaque_translation_companion
from services.engineering_drawing.post_ocr_supervision import build_post_ocr_supervision_package
from services.engineering_drawing.semantic_knowledge import load_engineering_semantic_knowledge


def test_local_semantic_knowledge_contains_engineering_coverage_rules() -> None:
    knowledge = load_engineering_semantic_knowledge()
    assert knowledge["terminology"]["R.C. FLAT ROOF"] == "钢筋混凝土平屋面"
    assert knowledge["drawing_families"]["drawing_index"]["delivery_mode"] == "opaque_bilingual_reflow"
    assert any("Vertical" in rule for rule in knowledge["instance_rules"])
    ct = knowledge["electrical_parameter_templates"]["current_transformer"]
    assert "secondary_winding_resistance" in ct["required_fields"]
    assert ct["field_labels_zh"]["rated_burden"] == "额定负荷"
    assert "CL.PX" in knowledge["electrical_code_policy"]["parameter_code_rule"]
    assert knowledge["repetition_strategy"]["name"] == "full-plus-compact"
    assert knowledge["reverse_reading_test"]["failure_rule"]


def test_post_ocr_package_returns_coordinates_to_multimodal_supervisor(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    image = tmp_path / "page.png"
    source.write_bytes(b"%PDF-placeholder")
    image.write_bytes(b"png-placeholder")
    package = build_post_ocr_supervision_package(
        source_pdf=source,
        page_image=image,
        ocr_payload={
            "regions": [
                {
                    "region_id": "r1",
                    "source_text": "R.C. FLAT ROOF",
                    "bbox": [10, 20, 80, 30],
                    "rotation": 0,
                }
            ]
        },
        initial_supervisor_plan={
            "page_type": "architectural_roof_plan",
            "delivery_mode": "inline_bilingual",
            "source_text_lines": [
                {"text": "R.C. FLAT ROOF", "bbox": [10, 20, 80, 30], "rotation": 0},
                {"text": "VERTICAL LABEL", "bbox": [90, 10, 100, 70], "rotation": 90},
            ],
        },
    )
    assert package["ocr_region_count"] == 1
    assert package["ocr_regions"][0]["bbox"] == [10, 20, 80, 30]
    assert "engineering_semantic_knowledge" in package
    assert "unexplained_region_ids" in package["required_output"]["fields"]
    assert package["candidate_union_count"] == 2
    assert package["candidate_union"][1]["rotation"] == 90
    assert package["supervisor_budget"]["maximum_model_passes_per_page"] == 3


def test_overlay_pair_keeps_source_separate_and_covers_translated_cell(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "translated.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=100)
    page.insert_text((10, 30), "DRAWING LIST", fontsize=10)
    document.save(source)
    document.close()

    result = render_opaque_translation_companion(
        source_pdf_path=source,
        output_pdf_path=output,
        semantic_blocks=[
                {
                    "page_index": 0,
                    "source_text": "DRAWING LIST",
                    "source_bbox": [8, 15, 100, 35],
                "translated_text": "图纸目录",
                "placement": {"font_size": 8},
            }
        ],
        ocr_regions=[
            {
                "region_id": "drawing-list",
                "source_text": "DRAWING LIST",
                "bbox": [8, 15, 100, 35],
            }
        ],
    )

    assert source.exists()
    assert output.exists()
    assert result["rendered_blocks"] == 1
    assert result["delivery_mode"] == "opaque_bilingual_reflow"
