from __future__ import annotations

import json
from pathlib import Path

import fitz

from services.engineering_drawing.visual_qa import _segments_intersect, analyze_visual_qa


def _output_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((20, 40), "SOURCE LABEL", fontsize=10)
    document.save(path)
    document.close()


def _output_pdf_with_background_text(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((20, 40), "SOURCE LABEL", fontsize=10)
    page.insert_text((120, 40), "BACKGROUND", fontsize=10)
    document.save(path)
    document.close()


def _write_audit(path: Path, placements: list[dict]) -> None:
    path.write_text(json.dumps({"placements": placements}), encoding="utf-8")


def test_visual_qa_counts_non_manual_text_overlap(tmp_path: Path) -> None:
    output = tmp_path / "output.pdf"
    audit = tmp_path / "output.inline-placement.json"
    _output_pdf(output)
    _write_audit(
        audit,
        [
            {
                "region_id": "overlap",
                "page_index": 0,
                "source_bbox": [20, 28, 100, 44],
                "target_bbox": [20, 28, 100, 44],
                "status": "inline_near",
                "coverage_status": "translated",
                "leader": {"status": "not_needed", "path": []},
            }
        ],
    )

    result = analyze_visual_qa(output_pdf_path=output, placement_audit_path=audit)

    assert result["visual_overlap_count"] == 1
    assert not result["passed"]


def test_visual_qa_allows_explicit_manual_fallback_but_reports_it(tmp_path: Path) -> None:
    output = tmp_path / "output.pdf"
    audit = tmp_path / "output.inline-placement.json"
    _output_pdf(output)
    _write_audit(
        audit,
        [
            {
                "region_id": "manual",
                "page_index": 0,
                "source_bbox": [20, 28, 100, 44],
                "target_bbox": [20, 28, 100, 44],
                "status": "inline_legacy_fallback",
                "coverage_status": "translated",
                "manual_review_required": True,
                "manual_review_reason": "trusted_legacy_conflict",
                "leader": {"status": "not_needed", "path": []},
            }
        ],
    )

    result = analyze_visual_qa(output_pdf_path=output, placement_audit_path=audit)

    assert result["visual_overlap_count"] == 0
    assert result["manual_review_count"] == 1
    assert result["passed"]


def test_visual_qa_detects_leader_crossing_another_caption(tmp_path: Path) -> None:
    output = tmp_path / "output.pdf"
    audit = tmp_path / "output.inline-placement.json"
    _output_pdf(output)
    _write_audit(
        audit,
        [
            {
                "region_id": "leader",
                "page_index": 0,
                "source_bbox": [20, 28, 80, 44],
                "target_bbox": [220, 100, 280, 118],
                "status": "inline_reviewed",
                "coverage_status": "translated",
                "leader": {"status": "drawn", "path": [[82, 36], [250, 36], [250, 100]]},
            },
            {
                "region_id": "caption",
                "page_index": 0,
                "source_bbox": [120, 20, 160, 34],
                "target_bbox": [230, 30, 270, 48],
                "status": "inline_near",
                "coverage_status": "translated",
                "leader": {"status": "not_needed", "path": []},
            },
        ],
    )

    result = analyze_visual_qa(output_pdf_path=output, placement_audit_path=audit)

    assert result["leader_collision_count"] >= 1
    assert not result["passed"]


def test_visual_qa_treats_v3_background_leader_crossing_as_advisory(tmp_path: Path) -> None:
    output = tmp_path / "output.pdf"
    audit = tmp_path / "output.inline-placement.json"
    _output_pdf_with_background_text(output)
    _write_audit(
        audit,
        [
            {
                "region_id": "v3-leader",
                "page_index": 0,
                "source_bbox": [20, 28, 80, 44],
                "target_bbox": [220, 100, 280, 118],
                "status": "inline_reviewed",
                "coverage_status": "translated",
                "multimodal_v3": True,
                "translated_text": "中文标签",
                "leader": {"status": "drawn", "path": [[82, 36], [180, 36], [180, 100]]},
            }
        ],
    )

    result = analyze_visual_qa(output_pdf_path=output, placement_audit_path=audit)

    assert result["leader_collision_count"] == 0
    assert result["leader_advisory_count"] >= 1
    assert result["passed"]


def test_visual_qa_does_not_count_separated_parallel_leaders_as_crossing() -> None:
    assert not _segments_intersect(
        ((700.0, 713.0), (700.0, 817.0)),
        ((700.0, 649.0), (820.0, 649.0)),
    )


def test_segments_intersect_vertical_crosses_horizontal_midspan() -> None:
    # The old bug: the vertical x=10 crossed the MIDDLE of a horizontal
    # 0..20, but only the horizontal start x was compared against the
    # vertical's x-span, so this genuine crossing was missed.
    assert _segments_intersect(((10.0, 0.0), (10.0, 10.0)), ((0.0, 5.0), (20.0, 5.0)))
    assert _segments_intersect(((0.0, 5.0), (20.0, 5.0)), ((10.0, 0.0), (10.0, 10.0)))


def test_segments_intersect_horizontal_crosses_vertical_midspan() -> None:
    assert _segments_intersect(((5.0, 0.0), (5.0, 10.0)), ((0.0, 7.0), (10.0, 7.0)))
    assert _segments_intersect(((0.0, 7.0), (10.0, 7.0)), ((5.0, 0.0), (5.0, 10.0)))


def test_segments_intersect_no_overlap_false() -> None:
    # Vertical x=10 but horizontal spans only 0..5 -> no x-overlap.
    assert not _segments_intersect(((10.0, 0.0), (10.0, 10.0)), ((0.0, 5.0), (5.0, 5.0)))
    # Horizontal y=5 but vertical spans only 0..3 -> no y-overlap.
    assert not _segments_intersect(((10.0, 0.0), (10.0, 3.0)), ((0.0, 5.0), (20.0, 5.0)))
