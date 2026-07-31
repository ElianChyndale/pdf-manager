"""V4 harness reconciliation: the old full-coverage gate is evidence, not release.

``harness.run_full_coverage_harness`` reports coverage/placement evidence for
historical V3.x audits.  Its passing result must never be treated as a release
authorization under V4: the release authority is the orchestration harness
closure gate plus the authorization surface.
"""

from __future__ import annotations

import warnings

import pytest

from services.engineering_drawing.harness import (
    GeographicResolver,
    correct_geographic_regions,
    run_full_coverage_harness,
    select_legacy_additions,
)
from services.engineering_drawing.orchestration_harness import new_run_identity, validate_handoff


def test_passing_legacy_harness_is_not_a_release_authorization() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = run_full_coverage_harness(
            [
                {
                    "region_id": "r1",
                    "source_text": "ROOF",
                    "translated_text": "屋顶",
                    "action": "translate",
                    "observation_status": "source",
                }
            ],
            placement_audit=[{"region_id": "r1", "status": "inline_near"}],
        )
    assert result.report["passed"] is True
    # A legacy HarnessResult has no release surface at all.
    assert not hasattr(result, "release")
    assert not hasattr(result.report, "authorization")


def test_legacy_harness_cannot_satisfy_v4_closure_gate() -> None:
    # Even when the legacy harness passes, the V4 gate independently requires
    # whole-page and rendered-ink closure of 1.0 for rendered candidates.
    base = new_run_identity(run_id="r1", source_sha256="a" * 64)
    blocks = [{"block_id": "b1", "source_ids": ["s1"], "zone": "drawing_body", "status": "translated", "render_mode": "preserve_source_blue_chinese"}]
    stage4 = {
        **base,
        "stage": "rendered_candidate",
        "blocks": blocks,
        "literal_only_ids": [],
        "expected_source_ids": ["s1"],
        "whole_page_closure": 1.0,
        "ink_closure": 0.5,
        "zone_closure": {"drawing_body": 1.0},
        "hard_findings": [],
    }
    with pytest.raises(ValueError, match="ink closure"):
        validate_handoff(stage4)


def test_geo_evidence_helper_still_returns_regions() -> None:
    regions = [{"region_id": "r1", "source_text": "Jalan Masjid 5"}]
    corrected = correct_geographic_regions(regions, resolver=GeographicResolver(allow_online=False))
    assert corrected[0]["region_id"] == "r1"
    assert corrected[0]["source_text"] == "Jalan Masjid 5"
    assert corrected[0]["geo_status"] in {"verified", "not_verified"}


def test_legacy_companion_helper_still_selects_additions(tmp_path: Path) -> None:
    import fitz

    source_pdf = tmp_path / "source.pdf"
    legacy_pdf = tmp_path / "legacy.pdf"
    for path in (source_pdf, legacy_pdf):
        document = fitz.open()
        page = document.new_page(width=200, height=120)
        page.insert_text((10, 20), "ROOF", fontsize=8)
        document.save(path)
        document.close()
    regions = [
        {
            "region_id": "r1",
            "source_text": "ROOF",
            "translated_text": "屋顶",
            "bbox": [10, 10, 40, 25],
            "action": "translate",
            "addition_approval": "ai_verified_source",
            "coverage_status": "translated",
        }
    ]
    additions, existing = select_legacy_additions(legacy_pdf_path=legacy_pdf, source_regions=regions)
    assert isinstance(additions, list)
    assert isinstance(existing, list)
