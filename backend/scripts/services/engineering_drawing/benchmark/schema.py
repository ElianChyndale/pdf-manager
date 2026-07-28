from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


Rect = tuple[float, float, float, float]


def _rect(value: object, field_name: str) -> Rect:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{field_name} must contain four coordinates")
    result = tuple(float(item) for item in value)
    if result[2] <= result[0] or result[3] <= result[1]:
        raise ValueError(f"{field_name} must be non-empty")
    return result


def _intersects(left: Rect, right: Rect) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])


def _inside(page: Rect, rect: Rect) -> bool:
    return (
        page[0] <= rect[0]
        and page[1] <= rect[1]
        and page[2] >= rect[2]
        and page[3] >= rect[3]
    )


@dataclass(frozen=True)
class CoreSample:
    sample_id: str
    category: str
    relative_pdf: str
    page_number: int
    goals: tuple[str, ...]


@dataclass(frozen=True)
class CoreManifest:
    schema: str
    benchmark_version: str
    samples: tuple[CoreSample, ...]
    set_name: str = "core"


@dataclass
class GoldBlock:
    block_id: str
    source_text: str
    source_language: str
    source_bbox: Rect
    rotation: int
    reading_order: int
    group_member_ids: list[str]
    merge_decision: str
    gold_translation: str
    literal_tokens: list[str]
    allowed_regions: list[Rect]
    forbidden_zones: list[Rect]
    font_size_range: tuple[float, float]
    leader: dict[str, bool]
    manual_review_required: bool = False


@dataclass
class GoldSample:
    schema: str
    sample_id: str
    gold_version: int
    status: str
    page: dict[str, float | int]
    blocks: list[GoldBlock]
    audit: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GoldSample":
        blocks = []
        for raw in value.get("blocks", []):
            item = dict(raw)
            item["source_bbox"] = _rect(item["source_bbox"], "source_bbox")
            item["allowed_regions"] = [
                _rect(rect, "allowed_regions") for rect in item["allowed_regions"]
            ]
            item["forbidden_zones"] = [
                _rect(rect, "forbidden_zones") for rect in item["forbidden_zones"]
            ]
            item["font_size_range"] = tuple(
                float(number) for number in item["font_size_range"]
            )
            blocks.append(GoldBlock(**item))
        return cls(
            schema=str(value["schema"]),
            sample_id=str(value["sample_id"]),
            gold_version=int(value["gold_version"]),
            status=str(value["status"]),
            page=dict(value["page"]),
            blocks=blocks,
            audit=list(value.get("audit", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_core_manifest(path: Path) -> CoreManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    samples = tuple(
        CoreSample(
            sample_id=str(item["sample_id"]),
            category=str(item["category"]),
            relative_pdf=str(item["relative_pdf"]),
            page_number=int(item["page_number"]),
            goals=tuple(str(goal) for goal in item["goals"]),
        )
        for item in payload["samples"]
    )
    manifest = CoreManifest(
        schema=str(payload["schema"]),
        benchmark_version=str(payload["benchmark_version"]),
        samples=samples,
        set_name="core",
    )
    if manifest.schema != "engineering-drawing-core-set-v1":
        raise ValueError("unsupported core manifest schema")
    if len(samples) != 12 or len({item.sample_id for item in samples}) != 12:
        raise ValueError("core manifest must contain 12 unique samples")
    if any(item.page_number != 1 for item in samples):
        raise ValueError("approved core samples must use page 1")
    return manifest


def load_challenge_manifest(path: Path) -> CoreManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != "engineering-drawing-challenge-set-v1":
        raise ValueError("unsupported challenge manifest schema")
    samples = tuple(
        CoreSample(
            sample_id=str(item["sample_id"]),
            category=str(item["category"]),
            relative_pdf=str(item["relative_pdf"]),
            page_number=int(item["page_number"]),
            goals=tuple(str(goal) for goal in item["goals"]),
        )
        for item in payload.get("samples", [])
    )
    if len({item.sample_id for item in samples}) != len(samples):
        raise ValueError("challenge sample IDs must be unique")
    return CoreManifest(
        schema=str(payload["schema"]),
        benchmark_version=str(payload["benchmark_version"]),
        samples=samples,
        set_name="challenge",
    )


def validate_gold_sample(sample: GoldSample) -> None:
    if sample.schema != "engineering-drawing-gold-v1":
        raise ValueError("unsupported gold schema")
    if sample.status not in {"candidate", "prelabeled", "adjudicated", "locked"}:
        raise ValueError("invalid gold status")
    if sample.gold_version < 1:
        raise ValueError("gold_version must be positive")
    block_ids = [block.block_id for block in sample.blocks]
    if len(block_ids) != len(set(block_ids)):
        raise ValueError("block_id values must be unique")
    page_rect = (
        0.0,
        0.0,
        float(sample.page["width"]),
        float(sample.page["height"]),
    )
    for block in sample.blocks:
        if block.rotation not in {0, 90, 180, 270}:
            raise ValueError("rotation must be orthogonal")
        if not block.source_text or not block.gold_translation:
            raise ValueError("source and gold translation are required")
        if block.font_size_range[0] < 3.2:
            raise ValueError("font size is below the workflow minimum")
        if not _inside(page_rect, block.source_bbox) or any(
            not _inside(page_rect, rect)
            for rect in [*block.allowed_regions, *block.forbidden_zones]
        ):
            raise ValueError("block geometry is outside the source page")
        if any(
            _intersects(allowed, forbidden)
            for allowed in block.allowed_regions
            for forbidden in block.forbidden_zones
        ):
            raise ValueError("allowed region overlaps forbidden zone")
