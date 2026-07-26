from pathlib import Path

import fitz

from services.engineering_drawing.inventory import build_inventory


def _pdf(path: Path, text: str, pages: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for page_number in range(pages):
        page = document.new_page(width=300, height=200)
        page.insert_text((20, 30), f"{text} {page_number + 1}")
    document.save(path)
    document.close()


def test_inventory_deduplicates_source_and_pairs_legacy_by_normalized_name(tmp_path):
    source = tmp_path / "报审图纸" / "A-001 Site Plan.pdf"
    duplicate = tmp_path / "A3 DETAIL DRAWING" / "A-001 Site Plan.pdf"
    legacy = tmp_path / "Translated Drawing 图纸翻译" / "A-001 Site Plan_Translated.pdf"
    _pdf(source, "SITE PLAN", pages=2)
    duplicate.parent.mkdir()
    duplicate.write_bytes(source.read_bytes())
    _pdf(legacy, "SITE PLAN 总平面图", pages=2)

    inventory = build_inventory(tmp_path)

    assert inventory.source_pdf_count == 2
    assert inventory.unique_source_count == 1
    assert inventory.duplicate_source_count == 1
    assert inventory.legacy_pdf_count == 1
    assert inventory.paired_count == 1
    assert inventory.total_unique_source_pages == 2
    assert inventory.total_legacy_pages == 2
    item = inventory.items[0]
    assert item.source_path == str(source.resolve())
    assert item.legacy_translation_path == str(legacy.resolve())
    assert item.duplicate_paths == ["A3 DETAIL DRAWING/A-001 Site Plan.pdf"]
    assert item.pairing_status == "paired"


def test_inventory_reports_unpaired_files(tmp_path):
    _pdf(tmp_path / "source" / "A.pdf", "A")
    _pdf(tmp_path / "翻译" / "B_翻译.pdf", "B 中文")

    inventory = build_inventory(tmp_path)

    assert inventory.unpaired_source_count == 1
    assert inventory.unpaired_legacy_paths == ["翻译/B_翻译.pdf"]
