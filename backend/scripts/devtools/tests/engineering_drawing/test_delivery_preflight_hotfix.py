"""Hotfix tests: glossary-dir resolution, production-runtime, delivery report,
duplicate map, validate-production dry-run, dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from services.engineering_drawing.delivery_dashboard import build_dashboard, build_dashboard_html
from services.engineering_drawing.delivery_run import (
    build_delivery_report,
    build_duplicate_map,
)
from services.engineering_drawing.preflight import run_preflight
from services.engineering_drawing.validate_production import validate_production


def _pdf(path: Path, *, text: str = "ROOF TANK") -> Path:
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((10, 20), text, fontsize=8)
    document.save(path)
    document.close()
    return path


class _Args:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_preflight_uses_manifest_declared_glossary_dir(tmp_path: Path) -> None:
    """P1-1: the manifest's glossary_tm_dir is honored, not ../05_Glossary_TM."""
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source = _pdf(source_root / "d1.pdf")
    glossary_dir = tmp_path / "glossary_tm"
    glossary_dir.mkdir()
    (glossary_dir / "engineering-glossary-v1.csv").write_text("source,target\n", encoding="utf-8")
    (glossary_dir / "translation-memory-v1.json").write_text('{"entries": []}', encoding="utf-8")
    manifest = {
        "items": [{"item_id": "d1", "source_pdf": "d1.pdf", "content_hash": ""}],
        "glossary_tm_dir": "glossary_tm",
    }
    report = run_preflight(manifest=manifest, source_root=source_root, output_root=tmp_path / "out")
    glossary_check = next(c for c in report["checks"] if c["check"] == "glossary_readable")
    tm_check = next(c for c in report["checks"] if c["check"] == "tm_readable")
    assert glossary_check["passed"] is True
    assert tm_check["passed"] is True
    assert str(glossary_dir) in glossary_check["detail"]


def test_production_runtime_checks_reported(tmp_path: Path) -> None:
    """P1-2: --production-runtime adds runtime_* checks to the report."""
    source_root = tmp_path / "sources"
    source_root.mkdir()
    _pdf(source_root / "d1.pdf")
    manifest = {"items": [{"item_id": "d1", "source_pdf": "d1.pdf", "content_hash": ""}], "glossary_tm_dir": ""}
    report = run_preflight(manifest=manifest, source_root=source_root, output_root=tmp_path / "out", production_runtime=True)
    runtime_checks = [c for c in report["checks"] if c["check"].startswith("runtime_")]
    assert runtime_checks
    names = {c["check"] for c in runtime_checks}
    assert {"runtime_paddleocr", "runtime_deepseek_ocr", "runtime_translation_provider", "runtime_pymupdf", "runtime_dependencies", "runtime_cjk_font"} <= names


def test_delivery_report_counts(tmp_path: Path) -> None:
    """P1-3: source_count = unique + duplicates reused; delivered = processed + reused."""
    manifest = {
        "items": [
            {"item_id": "eng-a", "content_hash": "h1"},
            {"item_id": "eng-b", "content_hash": "h2"},
        ]
    }
    report = build_delivery_report(manifest=manifest, source_root=tmp_path, duplicate_map={"dup1.pdf": "eng-a", "dup2.pdf": "eng-b"})
    assert report["unique_processed"] == 2
    assert report["duplicates_reused"] == 2
    assert report["delivered_files"] == 4


def test_build_duplicate_map_finds_only_duplicates(tmp_path: Path) -> None:
    """P2-4: only content-identical extra copies are mapped."""
    from hashlib import sha256

    source_root = tmp_path / "sources"
    source_root.mkdir()
    raw = tmp_path / "raw"
    raw.mkdir()
    original = _pdf(raw / "orig.pdf")
    duplicate = _pdf(raw / "duplicate.pdf")
    # force identical content
    duplicate.write_bytes(original.read_bytes())
    content_hash = sha256(original.read_bytes()).hexdigest()
    manifest = {
        "items": [
            {"item_id": "eng-x", "source_pdf": "eng-x.pdf", "content_hash": content_hash},
        ]
    }
    # stage the canonical copy
    (source_root / "eng-x.pdf").write_bytes(original.read_bytes())
    duplicate_map = build_duplicate_map(manifest=manifest, source_root=source_root, all_sources=[original, duplicate])
    assert len(duplicate_map) == 1
    assert str(duplicate) in duplicate_map
    assert str(original) not in duplicate_map  # the canonical raw path is not a duplicate


def test_validate_production_dry_run(tmp_path: Path) -> None:
    """P2-5: validate-production checks manifest/PDFs/context/glossary/naming/freeze."""
    source_root = tmp_path / "sources"
    source_root.mkdir()
    _pdf(source_root / "d1.pdf")
    glossary_dir = tmp_path / "glossary_tm"
    glossary_dir.mkdir()
    (glossary_dir / "engineering-glossary-v1.csv").write_text("a,b\n", encoding="utf-8")
    (glossary_dir / "translation-memory-v1.json").write_text('{"entries": []}', encoding="utf-8")
    lock = {
        "engineering-glossary-v1.csv": {"sha256": None},
        "translation-memory-v1.json": {"sha256": None},
    }
    (glossary_dir / "glossary-tm-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    manifest = {
        "items": [{"item_id": "d1", "source_pdf": "d1.pdf", "relative_output": "d1.pdf", "content_hash": "x"}],
        "document_context_template": {},
        "document_context_template_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # sha256 of {}
        "glossary_tm_dir": "glossary_tm",
        "policy_fingerprint": "x",
    }
    args = _Args(
        manifest=tmp_path / "m.json",
        source_root=source_root,
        output_root=tmp_path,
        freeze_config=tmp_path / "none.json",
    )
    (args.manifest).write_text(json.dumps(manifest), encoding="utf-8")
    # freeze_config missing -> the only failure is freeze_config_present.
    result = validate_production(args=args)
    assert result["passed"] is False
    assert "freeze_config_present" in result["failures"]
    # Most dry-run checks pass (no OCR/LLM/render touched).
    passed = {c["check"] for c in result["checks"] if c["passed"]}
    assert "manifest_parses" in passed
    assert "open_d1" in passed


def test_dashboard_counts_and_projection() -> None:
    batch = {
        "batch_id": "delivery-160",
        "phase": "canary",
        "items": [
            {"state": "released"},
            {"state": "ocr"},
            {"state": "failed"},
            {"state": "review_required"},
            {"state": "awaiting_supervisor_plan"},
        ],
    }
    dashboard = build_dashboard(batch=batch, capacity={"total_pages": 273, "completed_pages": 5, "average_minutes_per_page": 0.2})
    assert dashboard["total"] == 5
    assert dashboard["completed"] == 1
    assert dashboard["failed"] == 1
    assert dashboard["estimated_completion_hours"] is not None
    assert "<table>" in build_dashboard_html(dashboard)
