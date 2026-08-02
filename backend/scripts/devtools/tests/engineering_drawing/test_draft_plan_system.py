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
from services.engineering_drawing.run_v4 import _expand_min_bbox, render_inline_plus_opaque


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
    # The supervisor contract only allows translated/literal_only/not_needed/
    # manual_review; Chinese-origin maps to not_needed ("no translation needed").
    assert chinese["status"] == "not_needed"
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


# ---------------------------------------------------------------------------
# Regression tests: the canary-render fixes (locked so they never regress)
# ---------------------------------------------------------------------------

def test_opaque_blocks_count_as_rendered() -> None:
    """render_inline_plus_opaque must count opaque title_block/table_cell blocks
    as rendered even though the inline placement audit only covers inline
    blocks.  Regression for the canary render bug where all 55 opaque blocks
    were wrongly reported as failed."""
    from services.engineering_drawing.overlay_pair import render_planned_opaque_blocks

    # Build a plan with 2 opaque (company) + 2 inline (drawing) blocks.
    plan = {
        "semantic_blocks": [
            {
                "block_id": "op-1", "region_type": "company_contact_panel",
                "coverage_status": "translated", "source_text": "RACKS CENTRAL SDN. BHD.",
                "translated_text": "RACKS CENTRAL 有限公司", "source_bbox": [2080, 400, 2320, 415],
                "page_index": 0,
                "placement": {"mode": "table_cell", "render_mode": "opaque_bilingual_reflow",
                              "selected_region": [2080, 400, 2320, 420], "font_size": 6.8,
                              "render_runs": [
                                  {"text": "RACKS CENTRAL SDN. BHD.", "font_name": "simhei", "bbox": [2080, 400, 2320, 420], "font_size": 6.8, "color": [0, 0, 0]},
                                  {"text": "RACKS CENTRAL 有限公司", "font_name": "simhei", "bbox": [2080, 400, 2320, 420], "font_size": 6.8, "color": [0, 0, 0]},
                              ],
                              "exact_ink_masks": [[2080, 400, 2320, 415]],
                              "old_source_glyphs_visible": False, "partial_mask_overlap": False},
            },
            {
                "block_id": "in-1", "region_type": "drawing_body",
                "coverage_status": "translated", "source_text": "Flow Test Valve",
                "translated_text": "流量试验阀", "source_bbox": [500, 200, 700, 215],
                "page_index": 0,
                "placement": {"mode": "inline", "render_mode": "preserve_source_blue_chinese",
                              "target_bbox": [500, 200, 700, 215], "rotation": 0, "font_size": 6.4},
            },
        ]
    }
    # Use a real one-page source so the renderer can open it.
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "src.pdf"
    doc = fitz.open()
    page = doc.new_page(width=2384, height=1684)
    doc.save(src)
    doc.close()
    outcome = render_inline_plus_opaque(
        source_pdf=src,
        output_pdf=tmp / "out.pdf",
        plan=plan,
        ocr_payload=None,
        work_dir=tmp,
        renderer_options=None,
    )
    # The opaque block must be in rendered_ids (the regression).
    assert "op-1" in outcome.rendered_ids, f"opaque block not counted rendered: {outcome.rendered_ids}"
    assert "op-1" not in outcome.failed_block_ids
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


def test_narrow_bbox_is_expanded_to_readable() -> None:
    """A too-narrow source bbox (e.g. VENT TO 44x10) must be auto-expanded to a
    readable area so the bilingual text fits without human geometry editing."""
    expanded = _expand_min_bbox([1024.0, 1182.0, 1068.0, 1192.0])  # 44x10
    assert expanded[2] - expanded[0] >= 180.0, f"width not expanded: {expanded}"
    assert expanded[3] - expanded[1] >= 24.0, f"height not expanded: {expanded}"
    # A wide-enough box must be unchanged.
    assert _expand_min_bbox([0.0, 0.0, 500.0, 100.0]) == [0.0, 0.0, 500.0, 100.0]


def test_allow_partial_produces_reviewable_candidate() -> None:
    """With allow_partial, a render with failed blocks must produce the PDF and
    record failures as review items (not raise, not silently release)."""
    from services.engineering_drawing.run_v4 import run_v4_flow

    # A plan whose only block will fail (empty text -> renderer rejects).
    import tempfile, shutil, hashlib
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "src.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=120)
    page.insert_text((10, 20), "ROOF", fontsize=8)
    doc.save(src)
    doc.close()
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    # Real page-image evidence (the contract requires visual_inspection + image_sha256).
    image = tmp / "page.png"
    with fitz.open(src) as d:
        d[0].get_pixmap(alpha=False).save(image)
    image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
    plan = {
        "schema": "engineering-drawing-supervisor-plan-v1",
        "planning_authority": "real_multimodal_supervisor",
        "coordinate_space": "display_page_rect",
        "packet_id": "t-p0001", "source_sha256": sha, "page_index": 0,
        "page_rotation": 0, "unexplained_region_ids": [],
        "supervisor_invocation": {"verified": True, "mode": "codex_agent_multimodal",
                                  "model": "gpt-5.6-sol", "reasoning_profile": "light",
                                  "agent_id": "t", "started_at": "2026-08-02T00:00:00Z",
                                  "completed_at": "2026-08-02T00:00:01Z", "response_sha256": "b" * 64,
                                  "source_sha256": sha},
        "page_image_evidence": [{"visual_inspection": True, "image_sha256": image_sha, "image_path": str(image.resolve())}],
        "render_provenance": {"base": "original_source_pdf",
                                                          "source_pdf": str(src.resolve()),
                                                          "source_sha256": sha,
                                                          "copied_reference_page_or_region": False},
        "page_region_map": [{"region_id": "drawing_body", "region_type": "drawing_body",
                             "bbox": [0, 0, 200, 120], "decision_source": "real_multimodal_supervisor",
                             "visual_reason": "test region"}],
        "coverage_inventory": [{"candidate_id": "p0000", "source_text": "ROOF", "rotation": 0,
                                "source_bbox": [10000, 10000, 10050, 10020], "status": "translated",
                                "zone": "drawing_body"}],
        "coverage_evidence": [{"candidate_ids": ["p0000"], "source": "native_pdf_text",
                               "block_id": "b-fail", "page_index": 0}],
        "literal_only_ids": [],
        "semantic_blocks": [{
            "block_id": "b-fail", "page_region_id": "drawing_body", "region_type": "drawing_body", "coverage_status": "translated",
            "source_text": "ROOF", "translated_text": "屋面",
            "member_ids": ["p0000"], "source_ids": ["p0000"],
            # Contract-valid translation but an OUT-OF-PAGE bbox -> renderer cannot place it -> fails.
            "source_bbox": [10000, 10000, 10050, 10020], "page_index": 0,
            "placement": {"mode": "inline", "render_mode": "preserve_source_blue_chinese",
                          "target_bbox": [10000, 10000, 10050, 10020], "rotation": 0, "font_size": 6.4},
        }],
    }
    result = run_v4_flow(
        source_pdf=src, run_id="partial-test",
        supervisor_bundle_dir=tmp, normalized_plan=plan,
        work_dir=tmp / "work", candidate_dir=tmp / "cand", formal_dir=tmp / "formal",
        renderer="inline_plus_opaque", human_acceptance={"accepted_by": "t", "accepted_at": "2026-08-02T00:00:00Z"},
        allow_publish=True, bundle_verified=True,
        renderer_options={"allow_partial": True},
    )
    # Must produce a reviewable candidate, not raise, not publish.
    assert result["published"] is False
    assert result["reason"] == "partial_candidate_for_review"
    assert "b-fail" in result["failed_block_ids"]
    assert (tmp / "work" / "partial-candidate-review.json").is_file()
    shutil.rmtree(tmp, ignore_errors=True)
