from pathlib import Path
import json

import fitz
import pytest

from services.rendering.output.engineering import render_bilingual_overlay
from services.rendering.output.engineering import render_bilingual_inline_only
from services.rendering.output.engineering import render_source_chinese_dual
from services.rendering.output.engineering import bilingual as bilingual_renderer
from services.rendering.output.engineering.bilingual import _source_text_rects


def test_v34_exact_region_never_moves_or_shrinks_supervisor_layout() -> None:
    declared = fitz.Rect(10, 10, 90, 30)
    result = bilingual_renderer._fit_v34_exact_region(
        declared,
        translated="设备间",
        requested_font_size=6.0,
        rotation=0,
        font=fitz.Font("china-s"),
        placement_bounds=fitz.Rect(0, 0, 100, 100),
        occupied=[],
    )
    assert result == (declared, 6.0)
    assert bilingual_renderer._fit_v34_exact_region(
        declared,
        translated="这是一段远远无法放入主管指定矩形的超长中文译文" * 20,
        requested_font_size=6.0,
        rotation=0,
        font=fitz.Font("china-s"),
        placement_bounds=fitz.Rect(0, 0, 100, 100),
        occupied=[],
    ) is None


def _source_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 40), "Distribution Water Pump", fontsize=10)
    doc.save(path)
    doc.close()


def _regions() -> list[dict]:
    return [
        {
            "page_index": 0,
            "source_text": "Distribution Water Pump",
            "translated_text": "配水泵",
            "bbox": [20, 28, 150, 44],
            "rotation": 0,
            "action": "translate",
            "qa_flags": [],
        }
    ]


def test_bilingual_overlay_preserves_source_scale_and_adds_chinese(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "bilingual.pdf"
    _source_pdf(source_path)

    result = render_bilingual_overlay(source_pdf_path=source_path, output_pdf_path=output_path, regions=_regions())

    with fitz.open(source_path) as source, fitz.open(output_path) as output:
        assert output[0].rect.height == source[0].rect.height
        assert output[0].rect.width >= source[0].rect.width
        text = output[0].get_text()
        assert "Distribution Water Pump" in text
        assert "配水泵" in text
    assert result.inline_placements + result.sidebar_placements == 1


def test_bilingual_overlay_fast_save_keeps_reference_content(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "fast-reference.pdf"
    _source_pdf(source_path)

    render_bilingual_overlay(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=_regions(),
        optimize=False,
    )

    with fitz.open(output_path) as output:
        assert "Distribution Water Pump" in output[0].get_text()
        assert "配水泵" in output[0].get_text()


def test_dual_output_keeps_left_page_at_one_to_one_scale(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "dual.pdf"
    _source_pdf(source_path)

    render_source_chinese_dual(source_pdf_path=source_path, output_pdf_path=output_path, regions=_regions())

    with fitz.open(source_path) as source, fitz.open(output_path) as output:
        assert output[0].rect.height == source[0].rect.height
        assert output[0].rect.width == source[0].rect.width * 2 + 8
        assert "配水泵" in output[0].get_text()


def test_bilingual_overlay_bakes_page_rotation_without_clipping(tmp_path: Path) -> None:
    source_path = tmp_path / "rotated-source.pdf"
    output_path = tmp_path / "rotated-bilingual.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    page.insert_text((20, 40), "ROTATION MARKER", fontsize=10)
    page.set_rotation(270)
    doc.save(source_path)
    doc.close()

    render_bilingual_overlay(source_pdf_path=source_path, output_pdf_path=output_path, regions=[])

    with fitz.open(source_path) as source, fitz.open(output_path) as output:
        assert output[0].rect == source[0].rect
        assert "ROTATION MARKER" in output[0].get_text()


def test_bilingual_overlay_uses_numbered_reference_pages_instead_of_widening_source_page(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "bilingual.pdf"
    _source_pdf(source_path)
    regions = [
        {
            "page_index": 0,
            "source_text": f"Engineering note {index}",
            "translated_text": f"工程说明 {index}，必须完整保留原句含义。",
            "bbox": [20, 28 + index * 12, 270, 39 + index * 12],
            "rotation": 0,
            "action": "translate",
            "placement": "reference",
            "qa_flags": [],
        }
        for index in range(1, 10)
    ]

    result = render_bilingual_overlay(source_pdf_path=source_path, output_pdf_path=output_path, regions=regions)

    with fitz.open(source_path) as source, fitz.open(output_path) as output:
        assert output[0].rect == source[0].rect
        assert output.page_count >= 2
        assert "[1]" in output[0].get_text()
        assert "[1]" in output[1].get_text()
        # PDF text extraction can add a line break between the phrase and the
        # number, so assert the semantic content instead of a layout artifact.
        assert "工程说明" in output[1].get_text()
        assert "必须完整" in output[1].get_text()
    assert result.reference_pages >= 1
    assert result.reference_map_path is not None
    reference_map = json.loads(result.reference_map_path.read_text(encoding="utf-8"))
    assert len(reference_map["references"]) == len(regions)
    assert all(item["link_verified"] for item in reference_map["references"])
    assert all(item["complete_text_fit"] for item in reference_map["references"])


def test_bilingual_overlay_keeps_literal_regions_when_they_have_a_chinese_companion(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "bilingual.pdf"
    _source_pdf(source_path)
    regions = [
        {
            "page_index": 0,
            "source_text": "AHU-01",
            "translated_text": "空调处理机编号：AHU-01",
            "bbox": [20, 70, 75, 80],
            "rotation": 0,
            "action": "keep_literal",
            "placement": "reference",
            "qa_flags": [],
        }
    ]

    render_bilingual_overlay(source_pdf_path=source_path, output_pdf_path=output_path, regions=regions)

    with fitz.open(output_path) as output:
        # Source Han's embedded ToUnicode map exposes one compatibility glyph
        # differently in PyMuPDF extraction, so check stable semantic tokens.
        assert "空调" in output[1].get_text()
        assert "编号" in output[1].get_text()


def test_dual_output_moves_overflow_to_numbered_chinese_reference_cards(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "dual.pdf"
    _source_pdf(source_path)
    regions = [
        {
            "page_index": 0,
            "source_text": f"Engineering note {index}",
            "translated_text": f"工程说明 {index}，必须完整保留原句含义，不能在右侧译页被截断。",
            "bbox": [20, 28 + index * 12, 270, 39 + index * 12],
            "rotation": 0,
            "action": "translate",
            "placement": "reference",
            "qa_flags": [],
        }
        for index in range(1, 10)
    ]

    result = render_source_chinese_dual(source_pdf_path=source_path, output_pdf_path=output_path, regions=regions)

    with fitz.open(source_path) as source, fitz.open(output_path) as output:
        assert output[0].rect.width == source[0].rect.width * 2 + 8
        assert "Distribution Water Pump" in output[0].get_text()
        assert "[1]" in output[0].get_text()
        assert "工程说明" in output[0].get_text()
    assert result.reference_items == len(regions)
    assert result.reference_map_path is not None
    reference_map = json.loads(result.reference_map_path.read_text(encoding="utf-8"))
    assert all(item["complete_text_fit"] for item in reference_map["references"])


def test_dense_bilingual_overlay_keeps_original_page_clean_and_adds_indexed_source_copy(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "bilingual.pdf"
    _source_pdf(source_path)
    regions = [
        {
            "page_index": 0,
            "source_text": f"Label {index}",
            "translated_text": f"中文标签 {index}",
            "bbox": [20, 28 + (index % 12) * 12, 120, 38 + (index % 12) * 12],
            "rotation": 0,
            "action": "translate",
            "placement": "reference",
            "qa_flags": [],
        }
        for index in range(40)
    ]

    render_bilingual_overlay(source_pdf_path=source_path, output_pdf_path=output_path, regions=regions)

    with fitz.open(source_path) as source, fitz.open(output_path) as output:
        assert output[0].rect == source[0].rect
        assert "[1]" not in output[0].get_text()
        assert output[1].rect == source[0].rect
        assert "[1]" in output[1].get_text()


def test_inline_only_output_stays_single_page_without_reference_numbers(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "inline-only.pdf"
    _source_pdf(source_path)

    result = render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "page_index": 0,
                "source_text": "Distribution Water Pump",
                "translated_text": "配水泵",
                "bbox": [20, 28, 150, 44],
                "action": "translate",
            }
        ],
    )

    with fitz.open(output_path) as output:
        assert output.page_count == 1
        assert "Distribution Water Pump" in output[0].get_text()
        assert "配水泵" in output[0].get_text()
        assert "[1]" not in output[0].get_text()
    assert result.inline_placements == 1
    assert result.reference_items == 0


def test_inline_only_honors_clear_codex_review_target(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "reviewed-inline.pdf"
    _source_pdf(source_path)

    result = render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "sol-reviewed",
                "page_index": 0,
                "source_text": "Distribution Water Pump",
                "translated_text": "配水泵",
                "bbox": [20, 28, 150, 44],
                "review_target_bbox": [180, 28, 240, 44],
                "review_font_size": 7,
                "placement_decision_source": "codex_sol",
                "action": "translate",
                "qa_flags": [],
            }
        ],
    )

    placement = json.loads(
        output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8")
    )["placements"][0]
    assert placement["status"] == "inline_reviewed"
    assert placement["target_bbox"] == [180.0, 28.0, 240.0, 44.0]
    assert placement["decision_source"] == "codex_sol"
    assert result.inline_placements == 1


def test_inline_only_prefers_clear_right_side_for_horizontal_caption(tmp_path: Path) -> None:
    source_path = tmp_path / "right-preferred-source.pdf"
    output_path = tmp_path / "right-preferred-inline.pdf"
    _source_pdf(source_path)

    result = render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "right-preferred",
                "page_index": 0,
                "source_text": "Distribution Water Pump",
                "translated_text": "配水泵",
                "bbox": [20, 28, 150, 44],
                "action": "translate",
            }
        ],
    )

    placement = json.loads(
        output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8")
    )["placements"][0]
    assert placement["status"] == "inline_near"
    assert placement["target_bbox"][0] > placement["source_bbox"][2]
    assert result.inline_placements == 1


def test_inline_only_rejects_codex_review_target_over_source_text(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "reviewed-inline.pdf"
    _source_pdf(source_path)

    result = render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "sol-reviewed",
                "page_index": 0,
                "source_text": "Distribution Water Pump",
                "translated_text": "配水泵",
                "bbox": [20, 28, 150, 44],
                "review_target_bbox": [20, 28, 150, 44],
                "review_font_size": 7,
                "placement_decision_source": "codex_sol",
                "action": "translate",
                "qa_flags": [],
            }
        ],
    )

    placement = json.loads(
        output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8")
    )["placements"][0]
    assert placement["status"] == "inline_reflowed_after_review_collision"
    assert placement["target_bbox"][0] > placement["source_bbox"][2]
    assert result.inline_placements == 1


def test_inline_only_rejects_codex_target_over_vector_only_source_ink(tmp_path: Path) -> None:
    source_path = tmp_path / "vector-source.pdf"
    output_path = tmp_path / "vector-inline.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.draw_rect(fitz.Rect(100, 55, 200, 80), color=(0, 0, 0), fill=(0, 0, 0), width=0.5)
    doc.save(source_path)
    doc.close()

    result = render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "vector-only-source",
                "page_index": 0,
                "source_text": "VECTOR LABEL",
                "translated_text": "矢量标签",
                "bbox": [20, 28, 80, 44],
                "review_target_bbox": [110, 60, 160, 74],
                "review_font_size": 6,
                "placement_decision_source": "codex_sol",
                "action": "translate",
            }
        ],
    )

    placement = json.loads(
        output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8")
    )["placements"][0]
    assert placement["status"] == "inline_reflowed_after_review_collision"
    assert result.inline_placements == 1
    assert result.review_items == 0


def test_inline_only_preserves_authoritative_legacy_position_after_collision(tmp_path: Path) -> None:
    source_path = tmp_path / "legacy-fallback-source.pdf"
    output_path = tmp_path / "legacy-fallback-inline.pdf"
    _source_pdf(source_path)

    result = render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "legacy-fallback",
                "page_index": 0,
                "source_text": "Distribution Water Pump",
                "translated_text": "配水泵",
                "bbox": [20, 28, 150, 44],
                "legacy_bbox": [20, 28, 70, 44],
                "review_target_bbox": [20, 28, 150, 44],
                "review_font_size": 5,
                "provenance": "legacy_translation",
                "placement_decision_source": "codex_sol",
                "action": "translate",
                "qa_flags": ["authoritative_legacy_translation"],
            }
        ],
    )

    placement = json.loads(
        output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8")
    )["placements"][0]
    with fitz.open(output_path) as output:
        assert "配水泵" in output[0].get_text()
    assert placement["status"] == "inline_reflowed_after_review_collision"
    assert placement["target_bbox"] != [20.0, 28.0, 70.0, 44.0]
    assert result.inline_placements == 1
    assert result.review_items == 0


def test_inline_only_rejects_a_caption_when_nearby_source_text_would_be_covered(tmp_path: Path) -> None:
    source_path = tmp_path / "blocked-source.pdf"
    output_path = tmp_path / "blocked-inline.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 40), "SOURCE LABEL", fontsize=10)
    # This block occupies both close horizontal caption candidates.  The
    # renderer must reject rather than move a Chinese caption to a distant
    # blank part of the sheet.
    page.insert_text((20, 56), "ORIGINAL TITLE-BLOCK CONTENT", fontsize=10)
    page.insert_text((20, 20), "ORIGINAL HEADER", fontsize=10)
    page.insert_text((104, 40), "ORIGINAL SIDE CONTENT", fontsize=10)
    doc.save(source_path)
    doc.close()

    result = render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "page_index": 0,
                "source_text": "SOURCE LABEL",
                "translated_text": "源标签",
                "bbox": [20, 28, 100, 44],
                "action": "translate",
            }
        ],
        max_local_distance=8,
    )

    with fitz.open(output_path) as output:
        assert "源标签" not in output[0].get_text()
    assert result.inline_placements == 0
    assert result.review_items == 1


def test_inline_only_keeps_vertical_caption_rotation_and_writes_placement_audit(tmp_path: Path) -> None:
    source_path = tmp_path / "vertical-source.pdf"
    output_path = tmp_path / "vertical-inline.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((100, 180), "BOUNDARY LINE", fontsize=10, rotate=90)
    doc.save(source_path)
    doc.close()

    result = render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "vertical-boundary",
                "page_index": 0,
                "source_text": "BOUNDARY LINE",
                "translated_text": "边界线",
                "bbox": [90, 70, 105, 180],
                "rotation": 90,
                "action": "translate",
            }
        ],
    )

    audit = json.loads(output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8"))
    assert audit["placements"][0]["status"] == "inline_near"
    assert audit["placements"][0]["rotation"] == 90
    assert audit["placements"][0]["distance"] <= 12
    with fitz.open(output_path) as output:
        assert "边界线" in output[0].get_text()
    assert result.inline_placements == 1


def test_source_collision_rects_protect_complete_rotated_text_spans() -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text(
        (100, 180),
        "ROTATED SOURCE WORDS",
        fontsize=10,
        rotate=90,
    )
    raw = page.get_text("dict")
    span_bbox = next(
        fitz.Rect(span["bbox"])
        for block in raw["blocks"]
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if "ROTATED SOURCE WORDS" in span["text"]
    )

    collision_rects = _source_text_rects(page)

    assert any(rect == span_bbox for rect in collision_rects)
    doc.close()


def test_inline_only_transforms_ocr_bbox_when_source_page_has_rotation(tmp_path: Path) -> None:
    source_path = tmp_path / "rotated-geometry-source.pdf"
    output_path = tmp_path / "rotated-geometry-inline.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    page.insert_text((20, 40), "ROTATED LABEL", fontsize=10)
    source_bbox = [block[:4] for block in page.get_text("blocks") if "ROTATED LABEL" in block[4]][0]
    page.set_rotation(270)
    doc.save(source_path)
    doc.close()

    result = render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "rotated-label",
                "page_index": 0,
                "source_text": "ROTATED LABEL",
                "translated_text": "旋转标签",
                "bbox": source_bbox,
                "rotation": 0,
                "provenance": "native_text",
                "action": "translate",
            }
        ],
    )

    audit = json.loads(output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8"))["placements"][0]
    with fitz.open(output_path) as output:
        displayed_bbox = [block[:4] for block in output[0].get_text("blocks") if "ROTATED LABEL" in block[4]][0]
    assert audit["source_bbox"] == pytest.approx(displayed_bbox)
    assert result.inline_placements == 1


def test_inline_only_routes_a_short_orthogonal_leader_for_a_distant_dense_label(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "leader-source.pdf"
    output_path = tmp_path / "leader-output.pdf"
    _source_pdf(source_path)

    render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "leader-label",
                "page_index": 0,
                "source_text": "Distribution Water Pump",
                "translated_text": "配水泵",
                "bbox": [20, 28, 150, 44],
                "review_target_bbox": [220, 100, 280, 118],
                "review_font_size": 6,
                "leader_required": True,
                "action": "translate",
            }
        ],
    )

    audit = json.loads(output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8"))["placements"][0]
    assert audit["leader"]["status"] == "drawn"
    assert 3 <= len(audit["leader"]["path"]) <= 4
    for start, end in zip(audit["leader"]["path"], audit["leader"]["path"][1:]):
        assert start[0] == pytest.approx(end[0]) or start[1] == pytest.approx(end[1])


def test_v3_leader_prefers_short_route_even_when_background_linework_crosses_it(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "v3-background-source.pdf"
    output_path = tmp_path / "v3-background-output.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 40), "Distribution Water Pump", fontsize=10)
    # This line deliberately crosses the shortest local leader route.  V3
    # should keep the short connection instead of making a long detour.
    page.draw_line(fitz.Point(150, 36), fitz.Point(220, 36), color=(0, 0, 0), width=3)
    doc.save(source_path)
    doc.close()

    render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "v3-background-leader",
                "page_index": 0,
                "source_text": "Distribution Water Pump",
                "translated_text": "配水泵",
                "bbox": [20, 28, 150, 44],
                "review_target_bbox": [220, 100, 280, 118],
                "review_font_size": 6,
                "leader_required": True,
                "placement_decision_source": "multimodal_v3",
                "qa_flags": ["multimodal_v3_plan"],
                "placement_side": "external_gutter",
                "placement_mode": "leader",
                "action": "translate",
            }
        ],
    )

    audit = json.loads(output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8"))["placements"][0]
    assert audit["leader"]["status"] == "drawn"
    path = audit["leader"]["path"]
    path_length = sum(
        abs(end[0] - start[0]) + abs(end[1] - start[1])
        for start, end in zip(path, path[1:])
    )
    direct_distance = abs(path[0][0] - path[-1][0]) + abs(path[0][1] - path[-1][1])
    assert path_length <= direct_distance + 1.0


def test_v3_visual_plan_can_use_blank_target_marked_by_false_ocr_text_box(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "v3-false-ocr-source.pdf"
    output_path = tmp_path / "v3-false-ocr-output.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    doc.save(source_path)
    doc.close()

    # Simulate an OCR/native text span that claims the planned blank band is
    # occupied even though the rendered page contains no ink there.
    monkeypatch.setattr(
        bilingual_renderer,
        "_source_text_rects",
        lambda _page: [fitz.Rect(180, 80, 250, 100)],
    )

    render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "v3-false-ocr-target",
                "page_index": 0,
                "source_text": "MISDETECTED SOURCE",
                "translated_text": "可用空白译文",
                "bbox": [20, 28, 150, 44],
                "review_target_bbox": [180, 80, 250, 100],
                "review_font_size": 6,
                "placement_decision_source": "multimodal_v3",
                "qa_flags": ["multimodal_v3_plan"],
                "placement_side": "right",
                "placement_mode": "inline",
                "action": "translate",
            }
        ],
    )

    audit = json.loads(output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8"))["placements"][0]
    assert audit["status"] == "inline_reflowed_after_review_collision"
    assert audit["target_bbox"][0] > 180.0
    assert audit["target_bbox"][2] < 250.0
    assert audit["visual_ink_ratio"] == 0.0


def test_explicit_leader_route_does_not_confuse_separated_parallel_lines() -> None:
    from services.rendering.output.engineering.bilingual import _segments_intersect

    assert not _segments_intersect(
        ((700.0, 713.0), (700.0, 817.0)),
        ((700.0, 649.0), (820.0, 649.0)),
    )


def test_inline_only_forbids_leaders_in_title_block_rows(tmp_path: Path) -> None:
    source_path = tmp_path / "title-block-source.pdf"
    output_path = tmp_path / "title-block-output.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 40), "PROJECT TITLE", fontsize=10)
    doc.save(source_path)
    doc.close()

    render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=[
            {
                "region_id": "title-block-row",
                "page_index": 0,
                "source_text": "PROJECT TITLE",
                "translated_text": "项目名称",
                "bbox": [20, 28, 110, 44],
                "review_target_bbox": [210, 100, 280, 118],
                "review_font_size": 6,
                "layout_role": "title_block",
                "leader_required": True,
                "action": "translate",
            }
        ],
    )

    audit = json.loads(output_path.with_suffix(".inline-placement.json").read_text(encoding="utf-8"))["placements"][0]
    assert audit["leader"]["status"] == "not_needed"
