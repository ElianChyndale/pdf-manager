from __future__ import annotations

from pathlib import Path

import fitz

from services.engineering_drawing.run_v4 import _as_blocks, render_inline_plus_opaque


def test_as_blocks_keeps_literal_only_members_out_of_render_blocks() -> None:
    """Literal-only inventory entries close coverage but are never render blocks."""
    plan = {
        "coverage_inventory": [
            {"candidate_id": "translated-1", "status": "translated"},
            {"candidate_id": "literal-1", "status": "literal_only"},
        ],
        "semantic_blocks": [
            {
                "block_id": "translated-block",
                "coverage_status": "translated",
                "member_ids": ["translated-1"],
                "region_type": "drawing_body",
                "placement": {"render_mode": "preserve_source_blue_chinese"},
            },
            {
                "block_id": "literal-block",
                "coverage_status": "literal_only",
                "member_ids": ["literal-1"],
                "region_type": "drawing_body",
                "placement": {},
            },
        ],
    }

    blocks, literal_ids, expected_ids = _as_blocks(plan)

    assert [block["block_id"] for block in blocks] == ["translated-block"]
    assert literal_ids == ["literal-1"]
    assert set(expected_ids) == {"translated-1", "literal-1"}


def test_opaque_failure_still_writes_partial_candidate(tmp_path: Path) -> None:
    """An opaque failure must leave a renderable partial PDF for review."""
    source = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page(width=200, height=120)
    document.save(source)
    document.close()
    output = tmp_path / "candidate.pdf"
    plan = {
        "semantic_blocks": [
            {
                "block_id": "opaque-failure",
                "region_type": "company_contact_panel",
                "coverage_status": "translated",
                "source_text": "Company",
                "translated_text": "公司",
                "source_bbox": [10, 10, 80, 22],
                "page_index": 0,
                "placement": {
                    "mode": "table_cell",
                    "render_mode": "opaque_bilingual_reflow",
                    "selected_region": [10, 10, 14, 14],
                    "font_size": 6.8,
                    "exact_ink_masks": [[10, 10, 80, 22]],
                },
            }
        ]
    }

    outcome = render_inline_plus_opaque(
        source_pdf=source,
        output_pdf=output,
        plan=plan,
        ocr_payload=None,
        work_dir=tmp_path,
    )

    assert output.is_file()
    assert "opaque-failure" in outcome.failed_block_ids


def test_literal_only_block_is_not_sent_to_opaque_renderer(tmp_path: Path) -> None:
    """Literal-only source content remains on the page and never becomes a failure."""
    source = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page(width=200, height=120)
    document.save(source)
    document.close()
    output = tmp_path / "candidate.pdf"
    plan = {
        "semantic_blocks": [
            {
                "block_id": "literal-code",
                "region_type": "state_bearing_metadata",
                "coverage_status": "literal_only",
                "source_text": "A-101",
                "translated_text": "",
                "source_bbox": [10, 10, 60, 22],
                "page_index": 0,
                "placement": {"mode": "title_block"},
            }
        ]
    }

    outcome = render_inline_plus_opaque(
        source_pdf=source,
        output_pdf=output,
        plan=plan,
        ocr_payload=None,
        work_dir=tmp_path,
    )

    assert output.is_file()
    assert outcome.failed_block_ids == []
