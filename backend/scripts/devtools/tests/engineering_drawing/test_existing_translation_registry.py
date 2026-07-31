from __future__ import annotations

from pathlib import Path

import fitz

from services.engineering_drawing.existing_translation_registry import (
    extract_native_existing_translations,
)


def test_registry_records_native_chinese_coordinates_without_planning(tmp_path: Path) -> None:
    pdf = tmp_path / "existing.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=100)
    font = fitz.Font("china-s")
    page.insert_font(fontname="china-s", fontbuffer=font.buffer)
    page.insert_text((20, 30), "项目名称", fontname="china-s", fontsize=10)
    page.insert_text((20, 55), "PROJECT TITLE", fontsize=10)
    document.save(pdf)
    document.close()

    registry = extract_native_existing_translations(pdf)
    assert registry["planning_authority"] == "none_evidence_only"
    assert registry["page_count"] == 1
    assert len(registry["items"]) == 1
    assert registry["items"][0]["text"] == "项目名称"
    assert len(registry["items"][0]["bbox"]) == 4
    assert registry["items"][0]["supervisor_action"] == "pending_visual_decision"
