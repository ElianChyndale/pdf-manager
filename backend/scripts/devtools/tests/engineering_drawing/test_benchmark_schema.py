from pathlib import Path
import json
import math

import pytest

from services.engineering_drawing.benchmark.schema import (
    CoreManifest,
    CoreSample,
    GoldBlock,
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


@pytest.mark.parametrize(
    ("relative_pdf", "goals"),
    [
        ("../escape.pdf", ("semantic_block",)),
        ("C:/escape.pdf", ("semantic_block",)),
        (r"C:\escape.pdf", ("semantic_block",)),
        (r"\\server\share\escape.pdf", ("semantic_block",)),
        (r"\\?\C:\escape.pdf", ("semantic_block",)),
        (r"\\.\NUL.pdf", ("semantic_block",)),
        ("safe//escape.pdf", ("semantic_block",)),
        ("one.pdf", ("semantic_block", "semantic_block")),
        ("one.pdf", ("unknown_goal",)),
    ],
)
def test_direct_core_sample_rejects_unsafe_path_or_goals(
    relative_pdf: str, goals: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError):
        CoreSample("core-01", "detail", relative_pdf, 1, goals)


def test_direct_core_manifest_rejects_non_page_one_core_sample() -> None:
    sample = CoreSample(
        "core-01", "detail", "one.pdf", 2, ("semantic_block",)
    )

    with pytest.raises(ValueError, match="page 1"):
        CoreManifest(
            schema="engineering-drawing-core-set-v1",
            benchmark_version="core-v1",
            samples=(sample,),
        )


def test_direct_manifest_constructors_reject_coercive_inputs_and_arbitrary_identity() -> None:
    with pytest.raises(ValueError, match="immutable tuple"):
        CoreSample("core-01", "detail", "one.pdf", 1, ["semantic_block"])

    sample = CoreSample(
        "core-01", "detail", "one.pdf", 1, ("semantic_block",)
    )
    with pytest.raises(ValueError, match="immutable tuple"):
        CoreManifest(
            schema="engineering-drawing-core-set-v1",
            benchmark_version="core-v1",
            samples=[sample],
        )
    with pytest.raises(ValueError, match="approved"):
        CoreManifest(
            schema="engineering-drawing-core-set-v1",
            benchmark_version="arbitrary-version",
            samples=(sample,),
        )
    with pytest.raises(ValueError, match="approved"):
        CoreManifest(
            schema="engineering-drawing-core-set-v1",
            benchmark_version="core-v999",
            samples=(sample,),
        )


def test_challenge_manifest_loader_rejects_unsafe_sample_before_return(
    tmp_path: Path,
) -> None:
    payload = {
        "schema": "engineering-drawing-challenge-set-v1",
        "benchmark_version": "challenge-v1",
        "samples": [
            {
                "sample_id": "challenge-01",
                "category": "detail",
                "relative_pdf": r"\\?\C:\escape.pdf",
                "page_number": 1,
                "goals": ["semantic_block"],
            }
        ],
    }
    path = _write_payload(tmp_path, "challenge.json", payload)

    with pytest.raises(ValueError, match="relative_pdf"):
        load_challenge_manifest(path)


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


def test_direct_gold_construction_deeply_freezes_nested_values():
    payload = _valid_gold_payload()
    raw_block = payload["blocks"][0]
    block = GoldBlock(**raw_block)
    sample = GoldSample(
        schema=payload["schema"],
        sample_id=payload["sample_id"],
        gold_version=payload["gold_version"],
        status=payload["status"],
        page=payload["page"],
        blocks=[block],
        audit=payload["audit"],
    )
    raw_block["leader"]["color"] = "black"
    payload["audit"][0]["event"] = "changed"
    with pytest.raises((AttributeError, TypeError)):
        sample.blocks[0].leader["color"] = "black"
    with pytest.raises((AttributeError, TypeError)):
        sample.audit[0]["event"] = "changed"
    with pytest.raises(AttributeError):
        sample.gold_version = 2
    assert sample.blocks[0].leader["color"] == "dark_blue"
    assert sample.audit[0]["event"] == "locked"


@pytest.mark.parametrize("bound", (math.nan, math.inf, -math.inf))
def test_gold_sample_rejects_non_finite_font_size_bounds(bound):
    payload = _valid_gold_payload()
    payload["blocks"][0]["font_size_range"] = [bound, 6.5]
    with pytest.raises(ValueError, match="font_size_range must be finite"):
        validate_gold_sample(GoldSample.from_dict(payload))


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


@pytest.mark.parametrize("unknown_field", ("extra", "set_name"))
def test_core_manifest_loader_rejects_unknown_top_level_fields(
    tmp_path: Path, unknown_field: str
) -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "services/engineering_drawing/benchmark/core-set.v1.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload[unknown_field] = "unexpected"

    with pytest.raises(ValueError, match="manifest fields"):
        load_core_manifest(_write_payload(tmp_path, "core.json", payload))


def test_manifest_loader_rejects_unknown_sample_field(tmp_path: Path) -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "services/engineering_drawing/benchmark/core-set.v1.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["samples"][0]["extra"] = True

    with pytest.raises(ValueError, match="sample fields"):
        load_core_manifest(_write_payload(tmp_path, "core.json", payload))


@pytest.mark.parametrize("page_number", (True, 1.0, 1.5, "1"))
def test_manifest_loader_rejects_non_integer_page_number(
    tmp_path: Path, page_number: object
) -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "services/engineering_drawing/benchmark/core-set.v1.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["samples"][0]["page_number"] = page_number

    with pytest.raises(ValueError, match="page_number"):
        load_core_manifest(_write_payload(tmp_path, "core.json", payload))


@pytest.mark.parametrize(
    ("field", "value"),
    (("sample_id", 3), ("category", 3), ("relative_pdf", 3), ("goals", [3])),
)
def test_manifest_loader_rejects_non_string_sample_values(
    tmp_path: Path, field: str, value: object
) -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "services/engineering_drawing/benchmark/core-set.v1.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["samples"][0][field] = value

    with pytest.raises(ValueError):
        load_core_manifest(_write_payload(tmp_path, "core.json", payload))


def test_challenge_manifest_rejects_core_sample_identity(tmp_path: Path) -> None:
    payload = {
        "schema": "engineering-drawing-challenge-set-v1",
        "benchmark_version": "challenge-v1",
        "samples": [
            {
                "sample_id": "core-99",
                "category": "detail",
                "relative_pdf": "one.pdf",
                "page_number": 1,
                "goals": ["semantic_block"],
            }
        ],
    }

    with pytest.raises(ValueError, match="challenge sample_id"):
        load_challenge_manifest(_write_payload(tmp_path, "challenge.json", payload))


def test_direct_manifest_rejects_sample_identity_from_wrong_set() -> None:
    sample = CoreSample(
        "core-99", "detail", "one.pdf", 1, ("semantic_block",)
    )

    with pytest.raises(ValueError, match="challenge sample_id"):
        CoreManifest(
            schema="engineering-drawing-challenge-set-v1",
            benchmark_version="challenge-v1",
            samples=(sample,),
            set_name="challenge",
        )
