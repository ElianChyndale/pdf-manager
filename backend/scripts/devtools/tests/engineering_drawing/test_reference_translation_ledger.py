from __future__ import annotations

from pathlib import Path

import fitz

from services.engineering_drawing.reference_translation_ledger import (
    build_reference_translation_ledger,
)


def _pdf(path: Path, text: str) -> None:
    document = fitz.open()
    page = document.new_page(width=200, height=100)
    if any("\u3400" <= char <= "\u9fff" for char in text):
        font = fitz.Font("china-s")
        page.insert_font(fontname="china-s", fontbuffer=font.buffer)
        page.insert_text((20, 30), text, fontname="china-s", fontsize=10)
    else:
        page.insert_text((20, 30), text, fontsize=10)
    document.save(path)
    document.close()


def test_ledger_keeps_reference_coordinates_as_evidence_only(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    _pdf(source, "PROJECT TITLE")
    _pdf(reference, "项目名称")
    ledger = build_reference_translation_ledger(source, reference)
    assert ledger["render_base"] == "original_source_pdf"
    assert ledger["reference_usage"] == "translation_evidence_only"
    assert ledger["entries"][0]["reference_chinese"] == "项目名称"
    assert ledger["entries"][0]["source_candidates"][0]["source_text"] == "PROJECT TITLE"
    assert ledger["entries"][0]["reference_coordinates_are_target"] is False
    assert ledger["entries"][0]["supervisor_translation_decision"] == "pending_visual_review"
