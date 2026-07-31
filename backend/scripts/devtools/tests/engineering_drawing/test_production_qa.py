"""Task 3A: raster residual QA, token preservation, review decisions/revisions."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from services.engineering_drawing import run_v4
from services.engineering_drawing.raster_residual_qa import run_raster_residual_qa
from services.engineering_drawing.review_decisions import (
    add_decision,
    build_revision_run,
    load_decisions,
    revision_run_id,
)
from services.engineering_drawing.token_preservation import (
    check_token_preservation,
    scan_regions,
)


def _pdf(path: Path, *, text: str = "ROOF WATER TANK") -> Path:
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((10, 20), text, fontsize=8)
    document.save(path)
    document.close()
    return path


def _append_page(path: Path) -> None:
    document = fitz.open(path)
    document.new_page(width=200, height=120)
    temporary = path.with_suffix(".tmp2.pdf")
    document.save(temporary)
    document.close()
    temporary.replace(path)


def test_raster_residual_qa_detects_english_in_remove_zone(tmp_path: Path) -> None:
    candidate = _pdf(tmp_path / "candidate.pdf")
    source = _pdf(tmp_path / "source.pdf")
    run_v4.set_raster_ocr_engine("fake")
    report = run_raster_residual_qa(
        candidate_pdf=candidate,
        source_pdf=source,
        work_dir=tmp_path,
        placement_audit=[{"region_id": "b1", "target_bbox": [10, 10, 40, 25], "expected_source_visibility": "remove"}],
        blocks=[{"block_id": "b1", "render_mode": "opaque_bilingual_reflow"}],
        ocr_engine="fake",
    )
    # The fake OCR reports ROOF at [10,10,40,25] which is INSIDE the authorized
    # zone for b1 -> not a finding. Add an unauthorized token by offsetting.
    assert report["schema"] == "engineering-drawing-raster-residual-qa-v1"
    assert report["findings"] == []  # inside authorized zone
    run_v4.set_raster_ocr_engine("paddle")


def test_raster_residual_qa_flags_outside_authorized_zone(tmp_path: Path) -> None:
    candidate = _pdf(tmp_path / "candidate.pdf")
    source = _pdf(tmp_path / "source.pdf")
    # No authorized zone -> the fake ROOF token is outside -> finding.
    report = run_raster_residual_qa(
        candidate_pdf=candidate,
        source_pdf=source,
        work_dir=tmp_path,
        placement_audit=[],
        blocks=[{"block_id": "b1", "render_mode": "opaque_bilingual_reflow"}],
        ocr_engine="fake",
    )
    assert report["hard_failure"] == "raster_residual_english"
    assert report["findings"][0]["mode"] == "remove"
    assert (tmp_path / "raster-residual-english.json").is_file()


def test_raster_residual_qa_page_count_mismatch(tmp_path: Path) -> None:
    candidate = _pdf(tmp_path / "candidate.pdf")
    source = _pdf(tmp_path / "source2.pdf")
    _append_page(source)
    report = run_raster_residual_qa(
        candidate_pdf=candidate,
        source_pdf=source,
        work_dir=tmp_path,
        placement_audit=[],
        blocks=[],
        ocr_engine="fake",
    )
    assert report["page_count_mismatch"] is True
    assert report["hard_failure"] == "page_count_changed"


def test_token_preservation_real_loss_and_canonical() -> None:
    lost = check_token_preservation(source_text="DN200 pipe", target_text="DN20 管道")
    assert lost["lost_tokens"] and lost["lost_tokens"][0]["token"] == "DN200"
    assert lost["preserved"] is False
    # Canonical variations are NOT loss.
    assert check_token_preservation(source_text="25 mm", target_text="25mm")["preserved"] is True
    assert check_token_preservation(source_text="Ø200", target_text="ø200")["preserved"] is True
    assert check_token_preservation(source_text="1:100", target_text="1：100")["preserved"] is True
    assert check_token_preservation(source_text="220 kV", target_text="220 kV")["preserved"] is True
    assert check_token_preservation(source_text="10×20", target_text="10x20")["preserved"] is True


def test_scan_regions_aggregates_and_dedups_region_ids() -> None:
    report = scan_regions(
        regions=[
            {"region_id": "r1", "source_text": "DN200", "translated_text": "DN20"},
            {"region_id": "r2", "source_text": "220 kV", "translated_text": "220 kV"},
        ]
    )
    assert report["source_token_count"] == 2
    assert report["unique_lost_region_ids"] == ["r1"]
    assert report["identifier_preservation_accuracy"] == 0.5


def test_review_decision_roundtrip(tmp_path: Path) -> None:
    decisions_path = tmp_path / "review-decisions.json"
    decision = {
        "run_id": "run-001",
        "source_sha256": "a" * 64,
        "candidate_sha256": "b" * 64,
        "policy_fingerprint": "c" * 64,
        "supervisor_plan_sha256": "d" * 64,
        "region_id": "r1",
        "region_revision": 1,
        "decision": "edit",
        "approved_translation": "门卫室",
        "decision_reason": "wrong term",
        "tm_promotion_scope": "project",
    }
    saved = add_decision(decisions_path, decision)
    assert saved["reviewer_id"] == ""  # default
    assert load_decisions(decisions_path)[0]["decision"] == "edit"
    assert revision_run_id("run-001", "r1", 1) == "run-001-r1"


def test_revision_run_is_immutable_and_never_literal_only(tmp_path: Path) -> None:
    original = {"run_id": "run-001", "source_sha256": "a" * 64}
    revision = build_revision_run(
        original_run=original,
        decision={
            "run_id": "run-001",
            "source_sha256": "a" * 64,
            "candidate_sha256": "b" * 64,
            "policy_fingerprint": "c" * 64,
            "supervisor_plan_sha256": "d" * 64,
            "region_id": "r1",
            "region_revision": 1,
            "decision": "keep_literal",
            "decision_reason": "temporarily keep source",
            "tm_promotion_scope": "none",
        },
        work_dir=tmp_path,
    )
    record = json.loads(revision.read_text(encoding="utf-8"))
    # keep_literal must NOT become literal_only; it's a human exception.
    assert record["status"] == "human_exception_keep_source"
    assert record["bindings"]["source_sha256"] == "a" * 64
    assert record["revision_id"] == "run-001-r1"
