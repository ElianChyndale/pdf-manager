from pathlib import Path

import fitz

from services.engineering_drawing.overlay_pair import render_planned_opaque_blocks


def test_planned_opaque_block_masks_text_not_the_layout_cell(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "output.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.draw_line((10, 50), (190, 50), color=(0, 0, 0), width=1)
    page.insert_text((20, 68), "PROJECT TITLE", fontsize=8)
    document.save(source_path)
    document.close()

    result = render_planned_opaque_blocks(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        semantic_blocks=[
            {
                "block_id": "title",
                "page_index": 0,
                "source_bbox": [18, 58, 90, 72],
                "source_text": "PROJECT TITLE",
                "translated_text": "项目名称",
                "placement": {
                    "mode": "title_block",
                    "selected_region": [10, 40, 190, 105],
                    "font_size": 7,
                },
            }
        ],
        ocr_regions=[
            {
                "page_index": 0,
                "bbox": [18, 58, 90, 72],
                "source_text": "PROJECT TITLE",
            }
        ],
    )

    assert result["rendered_blocks"] == 1
    with fitz.open(output_path) as output:
        pixmap = output[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        # The horizontal cell divider lies inside selected_region but outside
        # source_bbox. It must remain black after bilingual field reflow.
        sample = pixmap.pixel(20, 100)
        assert max(sample) < 80

