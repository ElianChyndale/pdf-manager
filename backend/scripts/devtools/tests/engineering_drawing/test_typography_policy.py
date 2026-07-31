"""V4 typography policy gate tests (pre + post render, fail-closed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.engineering_drawing.typography_policy import (
    FONT_BELOW_V4_FLOOR,
    render_path_contract,
    validate_placement_audit_fonts,
    validate_plan_fonts,
    zone_font_floor,
)


def _plan_block(*, block_id: str, zone: str, font_size: float | None, status: str = "translated") -> dict:
    return {
        "block_id": block_id,
        "region_type": zone,
        "coverage_status": status,
        "placement": {"font_size": font_size, "target_bbox": [10, 10, 40, 25]},
    }


def test_zone_font_floors_match_spec() -> None:
    assert zone_font_floor("drawing_body") == 5.8
    assert zone_font_floor("drawing_table") == 5.8
    assert zone_font_floor("state_bearing_metadata") == 5.8
    assert zone_font_floor("directory_index") == 6.8
    assert zone_font_floor("company_contact_panel") == 6.4
    assert zone_font_floor("unknown_zone") == 5.8  # default body floor


def test_validate_plan_fonts_blocks_below_floor() -> None:
    plan = {"semantic_blocks": [_plan_block(block_id="b1", zone="drawing_body", font_size=4.0)]}
    violations = validate_plan_fonts(plan=plan, renderer="inline_plus_opaque")
    assert len(violations) == 1
    v = violations[0]
    assert v["region_id"] == "b1"
    assert v["zone"] == "drawing_body"
    assert v["actual_font_size"] == 4.0
    assert v["required_floor"] == 5.8
    assert v["renderer"] == "inline_plus_opaque"
    assert v["reason"] == "plan_below_v4_floor"


def test_validate_plan_fonts_passes_at_or_above_floor() -> None:
    plan = {
        "semantic_blocks": [
            _plan_block(block_id="b1", zone="drawing_body", font_size=6.0),
            _plan_block(block_id="b2", zone="directory_index", font_size=7.2),
            _plan_block(block_id="b3", zone="company_contact_panel", font_size=6.4),
        ]
    }
    assert validate_plan_fonts(plan=plan, renderer="inline_plus_opaque") == []


def test_validate_plan_fonts_ignores_non_translated() -> None:
    plan = {"semantic_blocks": [_plan_block(block_id="b1", zone="drawing_body", font_size=3.0, status="manual_review")]}
    assert validate_plan_fonts(plan=plan, renderer="inline_plus_opaque") == []


def test_validate_placement_audit_fonts_fails_below_floor_with_detail() -> None:
    audit = [
        {"region_id": "r1", "zone": "drawing_body", "status": "inline_near", "font_size": 4.0, "target_bbox": [0, 0, 10, 10]},
    ]
    violations = validate_placement_audit_fonts(placement_audit=audit, renderer="dense_index")
    assert len(violations) == 1
    v = violations[0]
    assert v["region_id"] == "r1"
    assert v["actual_font_size"] == 4.0
    assert v["required_floor"] == 5.8
    assert v["renderer"] == "dense_index"
    assert v["reason"] == "below_v4_floor"


def test_validate_placement_audit_fonts_fails_closed_on_missing_size() -> None:
    audit = [
        {"region_id": "r1", "zone": "drawing_body", "status": "inline_near", "target_bbox": [0, 0, 10, 10]},
    ]
    violations = validate_placement_audit_fonts(placement_audit=audit, renderer="inline_plus_opaque")
    assert len(violations) == 1
    assert violations[0]["reason"] == "missing_font_size_fail_closed"


def test_validate_placement_audit_fonts_skips_rejected_records() -> None:
    audit = [
        {"region_id": "r1", "zone": "drawing_body", "status": "rejected_invalid", "font_size": 3.0},
    ]
    assert validate_placement_audit_fonts(placement_audit=audit, renderer="inline_plus_opaque") == []


def test_render_path_contract_lists_floors_and_renderers() -> None:
    contract = render_path_contract()
    assert contract["schema"] == "engineering-drawing-render-path-contract-v1"
    assert contract["font_source"] == "workflow_policy.PRODUCTION_TYPOGRAPHY"
    assert set(contract["renderers"]) == {"inline_plus_opaque", "dense_index", "human_gate_rumah"}
    assert contract["floors"]["directory_index"] == 6.8
    assert "font_size" in contract["required_audit_fields"]
