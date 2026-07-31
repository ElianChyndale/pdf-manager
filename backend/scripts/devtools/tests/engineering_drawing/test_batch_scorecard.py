"""Batch scorecard aggregation and degradation."""

from __future__ import annotations

import json
from pathlib import Path

from services.engineering_drawing.batch_scorecard import (
    build_scorecard_html,
    compute_run_metrics,
    scorecard_from_formal_dir,
    scorecard_from_work_dirs,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _synthetic_work_dir(tmp_path: Path, *, name: str = "run-1", hard_findings=None) -> Path:
    work = tmp_path / name
    _write_json(
        work / "stage4-rendered-candidate.json",
        {
            "run_id": name,
            "workflow_version": "v4.0-readable-zone-complete",
            "policy_fingerprint": "p" * 64,
            "hard_findings": hard_findings or [],
            "whole_page_closure": 1.0,
            "candidate_pdf": str(work / "candidate.pdf"),
            "blocks": [
                {"block_id": "b1", "zone": "drawing_body", "status": "translated"},
                {"block_id": "b2", "zone": "drawing_body", "status": "translated"},
                {"block_id": "b3", "zone": "directory_index", "status": "manual_review"},
            ],
        },
    )
    _write_json(
        work / "visual-qa.json",
        {
            "visual_overlap_count": 1,
            "leader_collision_count": 0,
            "untranslated_candidate_count": 1,
            "passed": False,
            "untranslated_candidate_items": [{"region_id": "b1"}],
            "visual_overlap_items": [{"region_id": "b1"}],
        },
    )
    _write_json(
        work / "timing.json",
        {
            "schema": "engineering-drawing-run-timing-v1",
            "stage1_ms": 10.0,
            "stage2_ms": 20.0,
            "stage3_ms": 30.0,
            "stage4_ms": 40.0,
            "stage5_ms": 50.0,
            "started_at": "2026-07-31T00:00:00Z",
            "completed_at": "2026-07-31T00:00:01Z",
        },
    )
    _write_json(
        work / "delivery-manifest.json",
        {
            "delivery_id": f"dlv-{name}",
            "run_id": name,
            "renderer": {"name": "inline_plus_opaque"},
            "operator": {"name": "op", "qa_status": "reviewed"},
        },
    )
    _write_json(
        work / "translation-qa-report.json",
        {
            "source_regions": 10,
            "translated_regions": 8,
            "literal_labeled_regions": 1,
            "manual_review_regions": 1,
            "unresolved_regions": 1,
        },
    )
    (work / "page-0001.png").write_bytes(b"png")
    return work


def test_compute_run_metrics_formulas(tmp_path: Path) -> None:
    work = _synthetic_work_dir(tmp_path, hard_findings=["ink_coverage_gap"])
    metrics = compute_run_metrics(work_dir=work)
    assert metrics["run_id"] == "run-1"
    assert metrics["pages"] == 1
    assert metrics["total_regions"] == 10
    assert metrics["translated_regions"] == 8
    assert metrics["literal_labeled_regions"] == 1
    assert metrics["manual_review_regions"] == 1
    # Unique critical region ids: b1 appears in BOTH untranslated and visual
    # overlap items -> deduplicated to ONE; b3 (manual_review block) is a
    # second distinct region. hard_findings carry no region id so they never
    # inflate the count. Deduplicated / 10.
    assert metrics["critical_error_rate"] == 0.2
    assert metrics["unique_critical_region_ids"] == ["b1", "b3"]
    assert metrics["unprocessed_english_rate"] == 0.1
    assert metrics["numeric_identifier_preservation"] == 0.1
    assert metrics["manual_review_rate"] == 0.1
    assert metrics["closure_pass_rate"] == 1.0
    assert metrics["visual_collision_count"] == 1
    assert metrics["total_elapsed_ms"] == 150.0
    assert metrics["missing_artifacts"] == []


def test_scorecard_degrades_gracefully_on_missing_artifacts(tmp_path: Path) -> None:
    work = tmp_path / "bare"
    work.mkdir()
    metrics = compute_run_metrics(work_dir=work)
    assert metrics["run_id"] == ""
    assert metrics["critical_error_rate"] is None
    assert "stage4-rendered-candidate.json" in metrics["missing_artifacts"]


def test_scorecard_from_work_dirs_aggregates(tmp_path: Path) -> None:
    _synthetic_work_dir(tmp_path, name="run-a")
    _synthetic_work_dir(tmp_path, name="run-b", hard_findings=["omission"])
    report = scorecard_from_work_dirs(work_roots=[tmp_path / "run-a", tmp_path / "run-b"])
    assert report["run_count"] == 2
    assert report["critical_error_rate_avg"] is not None


def test_scorecard_html_escapes_and_lists_rows(tmp_path: Path) -> None:
    work = _synthetic_work_dir(tmp_path)
    report = scorecard_from_work_dirs(work_roots=[work])
    html_text = build_scorecard_html(report)
    assert "<table>" in html_text
    assert "run-1" in html_text
    assert "&lt;" not in html_text  # nothing unescaped to escape


def test_scorecard_from_formal_dir_lists_pdfs(tmp_path: Path) -> None:
    formal = tmp_path / "formal"
    formal.mkdir()
    pdf = formal / "01_drawing.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    report = scorecard_from_formal_dir(formal_dir=formal)
    assert report["run_count"] == 1
    assert "delivery-manifest.json" in report["runs"][0]["missing_artifacts"]
    assert "release-authorization.json" in report["runs"][0]["missing_artifacts"]
