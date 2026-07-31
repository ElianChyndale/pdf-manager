from pathlib import Path

import fitz

from services.engineering_drawing.cli import _parser
from services.engineering_drawing.legacy_transfer import extract_legacy_translation_regions
from services.engineering_drawing.legacy_transfer import select_strict_additions
from services.rendering.output.engineering import render_bilingual_inline_only


def _write_rotated_pair(source_path: Path, legacy_path: Path) -> None:
    source = fitz.open()
    source_page = source.new_page(width=240, height=360)
    source_page.insert_text((40, 300), "PUMP", fontsize=11, rotate=270)
    source_page.insert_text(
        (80, 300),
        "华西公司",
        fontsize=11,
        fontname="china-s",
        rotate=270,
    )
    source_page.set_rotation(270)
    source.save(source_path)
    source.close()

    legacy = fitz.open()
    legacy_page = legacy.new_page(width=240, height=360)
    legacy_page.insert_text(
        (40, 300),
        "泵房",
        fontsize=11,
        fontname="china-s",
        rotate=270,
    )
    legacy_page.insert_text(
        (80, 300),
        "华西公司",
        fontsize=11,
        fontname="china-s",
        rotate=270,
    )
    legacy_page.set_rotation(270)
    legacy.save(legacy_path)
    legacy.close()


def test_extracts_authoritative_unicode_chinese_and_keeps_source_on_rotated_page(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.pdf"
    legacy_path = tmp_path / "translated.pdf"
    output_path = tmp_path / "bilingual.pdf"
    _write_rotated_pair(source_path, legacy_path)

    regions = extract_legacy_translation_regions(
        source_pdf_path=source_path,
        legacy_pdf_path=legacy_path,
    )

    assert [region["translated_text"] for region in regions] == ["泵房"]
    assert regions[0]["source_text"] == "PUMP"
    assert regions[0]["provenance"] == "legacy_translation"
    assert fitz.Rect(regions[0]["bbox"]) == fitz.Rect(regions[0]["display_bbox"])

    result = render_bilingual_inline_only(
        source_pdf_path=source_path,
        output_pdf_path=output_path,
        regions=regions,
        max_local_distance=24,
        draw_leaders=False,
    )

    with fitz.open(output_path) as output:
        text = output[0].get_text()
        assert "PUMP" in text
        assert "泵房" in text
    assert result.inline_placements == 1


def test_ignores_non_chinese_garbled_legacy_text(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    legacy_path = tmp_path / "translated.pdf"

    source = fitz.open()
    page = source.new_page(width=300, height=200)
    page.insert_text((20, 40), "BASE BUILD MEP CONSULTANT", fontsize=10)
    source.save(source_path)
    source.close()

    legacy = fitz.open()
    page = legacy.new_page(width=300, height=200)
    page.insert_text((20, 40), "By7Q IR Sy0Q", fontsize=10)
    legacy.save(legacy_path)
    legacy.close()

    regions = extract_legacy_translation_regions(
        source_pdf_path=source_path,
        legacy_pdf_path=legacy_path,
    )

    assert regions == []


def test_strict_additions_admit_only_verified_unicode_chinese() -> None:
    base = {
        "page_index": 0,
        "source_text": "Distribution Storage Tank",
        "bbox": [20, 30, 140, 44],
        "action": "translate",
        "coverage_status": "translated",
        "ai_judgement": "accepted",
        "qa_flags": [],
    }

    additions = select_strict_additions(
        [
            {**base, "region_id": "accepted", "translated_text": "配水储水罐"},
            {
                "page_index": 0,
                "region_id": "explicitly-approved",
                "source_text": "Treated Water Tank",
                "translated_text": "净水箱",
                "bbox": [20, 60, 140, 74],
                "action": "translate",
                "addition_approval": "manual_verified_source",
                "approval_evidence": "High-resolution source-page review.",
                "qa_flags": [],
            },
            {**base, "region_id": "garbled", "translated_text": "By7Q IR Sy0Q"},
            {
                **base,
                "region_id": "blocked",
                "translated_text": "低置信度文本",
                "qa_flags": ["low_paddle_confidence"],
            },
            {
                **base,
                "region_id": "unreviewed",
                "translated_text": "未审核文本",
                "ai_judgement": "manual_review",
            },
        ]
    )

    assert [region["region_id"] for region in additions] == [
        "accepted",
        "explicitly-approved",
    ]


def test_cli_exposes_legacy_transfer_workflow() -> None:
    args = _parser().parse_args(
        [
            "legacy-transfer",
            "--source",
            "source.pdf",
            "--legacy",
            "translated.pdf",
            "--output",
            "bilingual.pdf",
            "--additions-json",
            "additions.json",
        ]
    )

    assert args.command == "legacy-transfer"
    assert args.source == Path("source.pdf")
    assert args.legacy == Path("translated.pdf")
    assert args.output == Path("bilingual.pdf")
    assert args.additions_json == Path("additions.json")
