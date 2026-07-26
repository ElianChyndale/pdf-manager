from pathlib import Path

import fitz

from services.rendering.output.engineering import render_bilingual_overlay
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
