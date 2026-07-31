from __future__ import annotations

import json
from pathlib import Path

import pytest

from devtools.build_v33_production_queue import _is_current_release
from devtools.release_v33_candidate import _load_visual_pass, _require_secure_release_path


def _review() -> dict:
    return {
        "verdict": "PASS",
        "inspection": {"source_and_candidate_full_page": True, "four_x_crops": 2},
        "hard_checks": {
            "all_natural_language_translated": True,
            "translated_text_readable": True,
            "translated_text_local": True,
            "no_text_overlap_or_crowding": True,
            "no_white_body_blocks": True,
            "logos_grids_numbers_preserved": True,
            "original_page_geometry_preserved": True,
        },
    }


def test_release_requires_structured_complete_visual_pass(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    path.write_text(json.dumps(_review()), encoding="utf-8")
    assert _load_visual_pass(path)["verdict"] == "PASS"

    failed = _review()
    failed["hard_checks"]["all_natural_language_translated"] = False
    path.write_text(json.dumps(failed), encoding="utf-8")
    with pytest.raises(SystemExit, match="all_natural_language_translated"):
        _load_visual_pass(path)


def test_queue_rejects_marker_without_multimodal_authority(tmp_path: Path) -> None:
    output = tmp_path / "published.pdf"
    output.write_bytes(b"%PDF-test")
    marker = {
        "schema": "engineering-drawing-v3.4-release-v1",
        "status": "passed_and_published",
        "independent_review_verdict": "PASS",
        "candidate_sha256": "candidate",
        "plan_sha256": "plan",
        "published_outputs": [str(output)],
    }
    assert not _is_current_release(marker)
    marker["visual_planning_authority"] = {
        "authority": "multimodal_model",
        "sequence": "visual_design_before_ocr_execution",
        "ocr_role": "extraction_and_mask_execution_only",
        "placement_basis": "rendered_page_visual",
    }
    assert _is_current_release(marker)


def test_legacy_v34_release_entrypoint_is_disabled() -> None:
    with pytest.raises(SystemExit, match="secure supervisor bundle"):
        _require_secure_release_path()
