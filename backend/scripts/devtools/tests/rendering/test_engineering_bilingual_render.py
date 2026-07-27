from pathlib import Path
import json

import fitz
import pytest

from services.rendering.output.engineering import render_bilingual_overlay
from services.rendering.output.engineering import render_bilingual_inline_only
from services.rendering.output.engineering import render_source_chinese_dual


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
