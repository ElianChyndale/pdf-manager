"""Risk-ranked review queue generation and HTML output."""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from services.engineering_drawing.review_queue import (
    RISK_WEIGHTS,
    build_review_queue,
    build_review_queue_html,
)


def _make_candidate_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "candidate.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((10, 20), "ROOF", fontsize=8)
    document.save(pdf)
    document.close()
    return pdf


def _synthetic_work_dir(tmp_path: Path, candidate_pdf: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "stage4-rendered-candidate.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "source_sha256": "a" * 64,
                "workflow_version": "v4.0-readable-zone-complete",
                "hard_findings": [],
                "candidate_pdf": str(candidate_pdf),
                "blocks": [
                    {
                        "block_id": "b1",
                        "zone": "drawing_body",
                        "source_text": "ROOF",
                        "translated_text": "屋顶",
                    },
                    {
                        "block_id": "b2",
                        "zone": "company_contact_panel",
                        "source_text": "ACME ENGINEERING PTE LTD 123 LONG ADDRESS ROAD JOHOR BAHRU MALAYSIA",
                        "translated_text": "ACME 工程私人有限公司 长地址路 123 号 柔佛巴鲁 马来西亚",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (work / "inline-placement.json").write_text(
        json.dumps(
            {
                "placements": [
                    {
                        "region_id": "b1",
                        "page_index": 0,
                        "status": "inline_near",
                        "confidence": 0.42,
                        "rotation": 90,
                        "font_size": 4.0,
                        "target_bbox": [50, 10, 90, 30],
                        "qa_flags": ["manual_review_required"],
                    },
                    {
                        "region_id": "b2",
                        "page_index": 0,
                        "status": "inline_near",
                        "confidence": 0.90,
                        "rotation": 0,
                        "font_size": 8.0,
                        "target_bbox": [110, 10, 150, 40],
                        "qa_flags": [],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (work / "visual-qa.json").write_text(
        json.dumps({"untranslated_candidate_items": [{"region_id": "b1"}]}),
        encoding="utf-8",
    )
    return work


def test_review_queue_ranks_high_risk_first(tmp_path: Path) -> None:
    candidate = _make_candidate_pdf(tmp_path)
    work = _synthetic_work_dir(tmp_path, candidate)
    queue = build_review_queue(work_dir=work)
    assert queue["schema"] == "engineering-drawing-review-queue-v1"
    assert queue["run_id"] == "run-1"
    items = queue["items"]
    assert len(items) == 2
    # b1 is low-confidence + rotated + microtext + residual-English -> risk > b2.
    assert items[0]["region_id"] == "b1"
    assert items[0]["risk_score"] > items[1]["risk_score"]
    assert items[0]["rank"] == 1 and items[1]["rank"] == 2
    assert "residual_english" in items[0]["risk_factors"]
    assert items[0]["risk_score"] == sum(
        RISK_WEIGHTS[f] for f in items[0]["risk_factors"]
    )


def test_review_queue_generates_crop(tmp_path: Path) -> None:
    candidate = _make_candidate_pdf(tmp_path)
    work = _synthetic_work_dir(tmp_path, candidate)
    queue = build_review_queue(work_dir=work)
    crop_path = next(item["crop_path"] for item in queue["items"] if item["crop_path"])
    assert Path(crop_path).is_file()
    assert crop_path.endswith(".png")


def test_review_queue_html_is_static_export(tmp_path: Path) -> None:
    candidate = _make_candidate_pdf(tmp_path)
    work = _synthetic_work_dir(tmp_path, candidate)
    queue = build_review_queue(work_dir=work)
    html_text = build_review_queue_html(queue)
    assert 'action="#"' in html_text
    assert "Static export" in html_text
    assert "crops/" in html_text
    assert "<select" in html_text
    assert "keep_literal" in html_text


def test_review_queue_raises_without_stage4(tmp_path: Path) -> None:
    import pytest

    from services.engineering_drawing.review_queue import build_review_queue

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="stage4"):
        build_review_queue(work_dir=empty)
