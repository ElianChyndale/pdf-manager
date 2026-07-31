"""Shared fixtures for V4 orchestration enforcement tests."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import fitz
import pytest

from services.engineering_drawing.supervisor_bundle import create_supervisor_run_bundle


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def make_source_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((10, 20), "ROOF", fontsize=8)
    document.save(path)
    document.close()
    return path


def make_valid_plan(source_pdf: Path, response_sha256: str) -> dict:
    source_sha = _sha(source_pdf)
    return {
        "schema": "engineering-drawing-multimodal-plan-v3",
        "status": "approved",
        "planning_authority": "real_multimodal_supervisor",
        "model_name": "gpt-5.6-sol",
        "reasoning_profile": "light",
        "coordinate_space": "display_page_rect",
        "page_type": "engineering_drawing",
        "delivery_mode": "inline_bilingual",
        "supervisor_invocation": {
            "verified": True,
            "mode": "codex_agent_multimodal",
            "model": "gpt-5.6-sol",
            "reasoning_profile": "light",
            "agent_id": "/root/sol-supervisor",
            "started_at": "2026-07-30T00:00:00+00:00",
            "completed_at": "2026-07-30T00:00:01+00:00",
            "response_sha256": response_sha256,
            "source_sha256": source_sha,
        },
        "render_provenance": {
            "base": "original_source_pdf",
            "source_sha256": source_sha,
            "copied_reference_page_or_region": False,
        },
        "page_image_evidence": [
            {"page_index": 0, "visual_inspection": True, "image_sha256": "0" * 64},
        ],
        "page_region_map": [
            {
                "region_id": "r1",
                "region_type": "drawing_body",
                "visual_reason": "test drawing body",
                "decision_source": "multimodal_visual_plan",
                "bbox": [0, 0, 200, 120],
            },
        ],
        "coverage_inventory": [
            {
                "candidate_id": "c1",
                "status": "translated",
                "source_text": "ROOF",
                "source_bbox": [10, 10, 40, 25],
                "rotation": 0,
            },
        ],
        "coverage_evidence": [
            {
                "source": "native_pdf_text",
                "candidate_ids": ["c1"],
                "page_index": 0,
                "uncovered_candidate_ids": [],
            },
        ],
        "unexplained_region_ids": [],
        "semantic_blocks": [
            {
                "block_id": "b1",
                "page_region_id": "r1",
                "region_type": "drawing_body",
                "coverage_status": "translated",
                "source_text": "ROOF",
                "translated_text": "屋顶",
                "member_ids": ["c1"],
                "placement": {
                    "render_mode": "preserve_source_blue_chinese",
                    "mode": "inline",
                    "target_bbox": [50, 10, 90, 30],
                    "rotation": 0,
                    "color": "blue",
                    "font_size": 6.0,
                },
            },
        ],
    }


def make_bundle(bundle_dir: Path, source_pdf: Path, plan: dict) -> Path:
    image = bundle_dir / "page.png"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    with fitz.open(source_pdf) as document:
        document[0].get_pixmap(alpha=False).save(image)
    return create_supervisor_run_bundle(
        bundle_dir=bundle_dir / "run",
        source_pdf_path=source_pdf,
        page_images=[image],
        request={"task": "inspect and plan"},
        raw_response={"output": plan},
        normalized_plan=plan,
        invocation_id="v4-test-run-1",
        agent_id="/root/sol-supervisor",
        started_at="2026-07-30T00:00:00+00:00",
        completed_at="2026-07-30T00:00:02+00:00",
    )


@pytest.fixture
def v4_source(tmp_path: Path) -> Path:
    return make_source_pdf(tmp_path / "source.pdf")


@pytest.fixture
def v4_plan(v4_source: Path) -> dict:
    return make_valid_plan(v4_source, response_sha256="a" * 64)


@pytest.fixture
def v4_bundle(tmp_path: Path, v4_source: Path, v4_plan: dict) -> Path:
    return make_bundle(tmp_path / "bundle-root", v4_source, v4_plan)
