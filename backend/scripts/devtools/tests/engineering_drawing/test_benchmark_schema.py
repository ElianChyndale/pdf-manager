from pathlib import Path
import json

import pytest

from services.engineering_drawing.benchmark.schema import (
    GoldSample,
    load_challenge_manifest,
    load_core_manifest,
    validate_gold_sample,
)


def _valid_gold_payload() -> dict:
    return {
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
                "forbidden_zones": [],
                "font_size_range": [3.2, 6.5],
                "leader": {
                    "allowed": True,
                    "required": False,
                    "color": "dark_blue",
                    "width_points": 0.32,
                    "route": "orthogonal",
                    "arrow": False,
                },
                "manual_review_required": False,
                "legacy_fallback": False,
            }
        ],
        "audit": [{"event": "locked"}],
    }


def _write_payload(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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
    payload = _valid_gold_payload()
    payload["blocks"][0]["forbidden_zones"] = [[90, 10, 170, 30]]
    sample = GoldSample.from_dict(payload)
    with pytest.raises(ValueError, match="allowed region overlaps forbidden zone"):
        validate_gold_sample(sample)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("color", "black", "leader color must be dark_blue"),
        ("width_points", 0.5, "leader width must be 0.32 points"),
        ("route", "diagonal", "leader route must be orthogonal"),
        ("arrow", True, "leader arrow must be false"),
    ],
)
def test_gold_sample_rejects_nonstandard_leader_style(field, value, message):
    payload = _valid_gold_payload()
    payload["blocks"][0]["leader"][field] = value
    with pytest.raises(ValueError, match=message):
        validate_gold_sample(GoldSample.from_dict(payload))


def test_gold_sample_requires_allowed_leader_when_leader_is_required():
    payload = _valid_gold_payload()
    payload["blocks"][0]["leader"].update({"allowed": False, "required": True})
    with pytest.raises(ValueError, match="required leader must be allowed"):
        validate_gold_sample(GoldSample.from_dict(payload))


def test_gold_sample_requires_manual_review_for_legacy_fallback():
    payload = _valid_gold_payload()
    payload["blocks"][0]["legacy_fallback"] = True
    with pytest.raises(ValueError, match="legacy fallback requires manual review"):
        validate_gold_sample(GoldSample.from_dict(payload))


def test_gold_sample_is_deeply_immutable_and_serializable():
    sample = GoldSample.from_dict(_valid_gold_payload())
    with pytest.raises((AttributeError, TypeError)):
        sample.blocks[0].leader["color"] = "black"
    with pytest.raises((AttributeError, TypeError)):
        sample.audit[0]["event"] = "changed"
    assert sample.to_dict() == _valid_gold_payload()


@pytest.mark.parametrize(
    "font_size_range",
    ([3.2], [6.5, 3.2], [3.1, 6.5]),
)
def test_gold_sample_rejects_malformed_font_size_ranges(font_size_range):
    payload = _valid_gold_payload()
    payload["blocks"][0]["font_size_range"] = font_size_range
    with pytest.raises(ValueError, match="font_size_range"):
        validate_gold_sample(GoldSample.from_dict(payload))


@pytest.mark.parametrize(
    ("page", "block_rotation", "message"),
    [
        ({"width": 300, "height": 200, "rotation": 45}, 0, "page rotation"),
        ({"width": 0, "height": 200, "rotation": 0}, 0, "page geometry"),
        ({"width": 300, "height": 200, "rotation": 0}, 45, "rotation must be orthogonal"),
    ],
)
def test_gold_sample_rejects_invalid_source_page_rotation_or_geometry(
    page, block_rotation, message
):
    payload = _valid_gold_payload()
    payload["page"] = page
    payload["blocks"][0]["rotation"] = block_rotation
    with pytest.raises(ValueError, match=message):
        validate_gold_sample(GoldSample.from_dict(payload))


def test_gold_sample_rejects_source_geometry_outside_page():
    payload = _valid_gold_payload()
    payload["blocks"][0]["source_bbox"] = [10, 10, 400, 25]
    with pytest.raises(ValueError, match="block geometry is outside the source page"):
        validate_gold_sample(GoldSample.from_dict(payload))


@pytest.mark.parametrize(
    ("loader", "file_name", "version", "message"),
    [
        (load_core_manifest, "core-set.v1.json", "core-v2", "unsupported core manifest version"),
        (
            load_challenge_manifest,
            "challenge-set.v1.json",
            "challenge-v2",
            "unsupported challenge manifest version",
        ),
    ],
)
def test_manifest_rejects_unsupported_benchmark_version(
    tmp_path, loader, file_name, version, message
):
    source = Path(__file__).resolve().parents[3] / "services/engineering_drawing/benchmark" / file_name
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["benchmark_version"] = version
    with pytest.raises(ValueError, match=message):
        loader(_write_payload(tmp_path, file_name, payload))


def test_core_manifest_requires_approved_ids_in_order(tmp_path):
    source = Path(__file__).resolve().parents[3] / "services/engineering_drawing/benchmark/core-set.v1.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["samples"][0]["sample_id"] = "core-13"
    with pytest.raises(ValueError, match="approved core sample IDs"):
        load_core_manifest(_write_payload(tmp_path, "core.json", payload))


def test_core_manifest_rejects_case_insensitive_duplicate_pdf_path(tmp_path):
    source = Path(__file__).resolve().parents[3] / "services/engineering_drawing/benchmark/core-set.v1.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["samples"][1]["relative_pdf"] = payload["samples"][0]["relative_pdf"].upper()
    with pytest.raises(ValueError, match="PDF paths must be unique"):
        load_core_manifest(_write_payload(tmp_path, "core.json", payload))
