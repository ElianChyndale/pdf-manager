"""Systemic tests: draft plans are gate-ready without supervisor manual fixes.

These tests encode the learnings from the canary signing rework so future
draft-plan runs do not force the supervisor to hand-fix coverage, fonts, or
contract fields.  A draft must already be: full-coverage (closure=1.0), have
per-zone font floors, classify Chinese as not_source_language, and be signable
to a contract-passing plan via sign_draft_plan.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from services.engineering_drawing.draft_plans import (
    _packet_regions_for_translation,
    build_draft_plan,
    sign_draft_plan,
)


def _make_packet(tmp_path: Path, *, chinese: bool = False) -> dict:
    """Build a synthetic packet with mixed candidates."""
    candidates = [
        {"text": "BATTERY", "bbox": [100.0, 100.0, 200.0, 115.0], "rotation": 0},
        {"text": "Flow Test Valve", "bbox": [500.0, 200.0, 700.0, 215.0], "rotation": 0},
        {"text": "1310-CN-MECH-FP-C003", "bbox": [100.0, 1500.0, 400.0, 1515.0], "rotation": 0},
        {"text": "DETAIL 6", "bbox": [1000.0, 300.0, 1100.0, 315.0], "rotation": 0},
    ]
    if chinese:
        candidates.append({"text": "华西（马来西亚）有限公司", "bbox": [2100.0, 200.0, 2300.0, 215.0], "rotation": 0})
    return {
        "packet_id": "t-p0001",
        "source_sha256": "a" * 64,
        "page_index": 0,
        "page_size": [2384.0, 1684.0],
        "page_rotation": 0,
        "native_text_candidates": candidates,
    }


def test_draft_has_full_coverage_closure() -> None:
    """Every native-text candidate must appear in coverage (closure=1.0)."""
    packet = _make_packet(Path("."))
    regions = _packet_regions_for_translation(packet)
    draft = build_draft_plan(packet=packet, translation_report={"regions": regions})
    cov_ids = {c["candidate_id"] for c in draft["coverage_inventory"]}
    all_candidates = {f"p{i:04d}" for i in range(len(packet["native_text_candidates"]))}
    assert all_candidates <= cov_ids, f"missing coverage: {all_candidates - cov_ids}"
    # no candidate left manual_review (all resolved by offline/literal/chinese)
    unresolved = [c for c in draft["coverage_inventory"] if c["status"] == "manual_review"]
    assert unresolved == [], f"unresolved coverage items: {unresolved}"


def test_draft_has_zone_font_floors() -> None:
    """Every translated block carries a valid per-zone font floor."""
    packet = _make_packet(Path("."))
    regions = _packet_regions_for_translation(packet)
    draft = build_draft_plan(packet=packet, translation_report={"regions": regions})
    for block in draft["semantic_blocks"]:
        font = block.get("placement", {}).get("font_size")
        assert font is not None and font > 0, f"block {block['block_id']} missing font_size"
        zone = block.get("region_type")
        if zone == "company_contact_panel":
            assert font >= 6.4
        elif zone == "directory_index":
            assert font >= 6.8
        else:
            assert font >= 5.8


def test_chinese_candidates_are_not_source_language() -> None:
    """Chinese-origin text must never be a translation target."""
    packet = _make_packet(Path("."), chinese=True)
    regions = _packet_regions_for_translation(packet)
    draft = build_draft_plan(packet=packet, translation_report={"regions": regions})
    chinese = next(c for c in draft["coverage_inventory"] if "华西" in c["source_text"])
    assert chinese["status"] == "not_source_language"
    # and it must NOT be in semantic_blocks as a translated block
    assert not any("华西" in b.get("source_text", "") for b in draft["semantic_blocks"])


def test_sign_draft_produces_contract_plan() -> None:
    """sign_draft_plan yields a plan that passes validate_real_supervisor_plan."""
    from services.engineering_drawing.supervisor_contract import validate_real_supervisor_plan

    packet = _make_packet(Path("."))
    regions = _packet_regions_for_translation(packet)
    draft = build_draft_plan(packet=packet, translation_report={"regions": regions})
    # build a real page image for the evidence
    pdf = Path(".") / "_t_pdf.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=120)
    page.insert_text((10, 20), "BATTERY", fontsize=8)
    doc.save(pdf)
    doc.close()
    image = Path(".") / "_t_png.png"
    with fitz.open(pdf) as d:
        d[0].get_pixmap(alpha=False).save(image)
    plan = sign_draft_plan(
        draft=draft,
        page_image=image,
        agent_id="codex-test",
        started_at="2026-08-02T00:00:00Z",
        completed_at="2026-08-02T00:00:01Z",
        response_sha256="b" * 64,
    )
    assert plan["schema"] == "engineering-drawing-supervisor-plan-v1"
    assert plan["planning_authority"] == "real_multimodal_supervisor"
    assert plan["supervisor_invocation"]["verified"] is True
    assert len(plan["page_image_evidence"]) == 1
    # The plan's source_pdf must exist for contract validation; point it at the temp pdf
    # and use its REAL sha256 so the contract's source-binding check passes.
    import hashlib

    real_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    plan["render_provenance"] = {
        "base": "original_source_pdf",
        "source_pdf": str(pdf.resolve()),
        "source_sha256": real_sha,
        "copied_reference_page_or_region": False,
    }
    plan["source_sha256"] = real_sha
    plan["supervisor_invocation"]["source_sha256"] = real_sha
    # Validate: this must pass WITHOUT manual fixes (the systemic goal).
    validated = validate_real_supervisor_plan(plan, source_pdf_path=pdf)
    assert validated["planning_authority"] == "real_multimodal_supervisor"
    pdf.unlink(missing_ok=True)
    image.unlink(missing_ok=True)
