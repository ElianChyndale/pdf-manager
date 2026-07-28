from pathlib import Path

import pytest

from services.engineering_drawing.benchmark.schema import (
    GoldSample,
    load_challenge_manifest,
    load_core_manifest,
    validate_gold_sample,
)


def test_core_manifest_has_the_approved_twelve_page_one_samples():
    path = (
        Path(__file__).resolve().parents[3]
        / "services/engineering_drawing/benchmark/core-set.v1.json"
    )
    manifest = load_core_manifest(path)
    assert manifest.schema == "engineering-drawing-core-set-v1"
    assert len(manifest.samples) == 12
    assert [item.sample_id for item in manifest.samples] == [
        f"core-{index:02d}" for index in range(1, 13)
    ]
    assert {item.page_number for item in manifest.samples} == {1}
    assert len({item.relative_pdf.casefold() for item in manifest.samples}) == 12


def test_challenge_manifest_starts_empty_and_versioned():
    path = (
        Path(__file__).resolve().parents[3]
        / "services/engineering_drawing/benchmark/challenge-set.v1.json"
    )
    manifest = load_challenge_manifest(path)
    assert manifest.set_name == "challenge"
    assert manifest.benchmark_version == "challenge-v1"
    assert manifest.samples == ()


def test_gold_sample_rejects_target_inside_forbidden_zone():
    sample = GoldSample.from_dict(
        {
            "schema": "engineering-drawing-gold-v1",
            "sample_id": "core-03",
            "gold_version": 1,
            "status": "locked",
            "page": {"width": 300, "height": 200, "rotation": 0},
            "blocks": [
                {
                    "block_id": "core-03-b001",
                    "source_text": "ROOF SYSTEM",
                    "source_language": "en",
                    "source_bbox": [10, 10, 80, 25],
                    "rotation": 0,
                    "reading_order": 1,
                    "group_member_ids": ["ocr-1"],
                    "merge_decision": "single",
                    "gold_translation": "屋面系统",
                    "literal_tokens": [],
                    "allowed_regions": [[90, 10, 170, 30]],
                    "forbidden_zones": [[90, 10, 170, 30]],
                    "font_size_range": [3.2, 6.5],
                    "leader": {"allowed": True, "required": False},
                    "manual_review_required": False,
                }
            ],
            "audit": [],
        }
    )
    with pytest.raises(ValueError, match="allowed region overlaps forbidden zone"):
        validate_gold_sample(sample)
