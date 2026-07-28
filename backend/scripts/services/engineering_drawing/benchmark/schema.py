from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


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


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


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


@dataclass(frozen=True)
class GoldBlock:
    block_id: str
    source_text: str
    source_language: str
    source_bbox: Rect
    rotation: int
    reading_order: int
    group_member_ids: tuple[str, ...]
    merge_decision: str
    gold_translation: str
    literal_tokens: tuple[str, ...]
    allowed_regions: tuple[Rect, ...]
    forbidden_zones: tuple[Rect, ...]
    font_size_range: tuple[float, float]
    leader: Mapping[str, Any]
    manual_review_required: bool = False
    legacy_fallback: bool = False


@dataclass(frozen=True)
class GoldSample:
    schema: str
    sample_id: str
    gold_version: int
    status: str
    page: Mapping[str, float | int]
    blocks: tuple[GoldBlock, ...]
    audit: tuple[Mapping[str, Any], ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GoldSample":
        blocks = []
        for raw in value.get("blocks", []):
            item = dict(raw)
            item["source_bbox"] = _rect(item["source_bbox"], "source_bbox")
            item["allowed_regions"] = tuple(
                _rect(rect, "allowed_regions") for rect in item["allowed_regions"]
            )
            item["forbidden_zones"] = tuple(
                _rect(rect, "forbidden_zones") for rect in item["forbidden_zones"]
            )
            item["font_size_range"] = tuple(
                float(number) for number in item["font_size_range"]
            )
            item["group_member_ids"] = tuple(str(item) for item in item["group_member_ids"])
            item["literal_tokens"] = tuple(str(item) for item in item["literal_tokens"])
            item["leader"] = _freeze(dict(item["leader"]))
            blocks.append(GoldBlock(**item))
        return cls(
            schema=str(value["schema"]),
            sample_id=str(value["sample_id"]),
            gold_version=int(value["gold_version"]),
            status=str(value["status"]),
            page=_freeze(dict(value["page"])),
            blocks=tuple(blocks),
            audit=tuple(_freeze(dict(item)) for item in value.get("audit", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "sample_id": self.sample_id,
            "gold_version": self.gold_version,
            "status": self.status,
            "page": _thaw(self.page),
            "blocks": [
                {
                    "block_id": block.block_id,
                    "source_text": block.source_text,
                    "source_language": block.source_language,
                    "source_bbox": list(block.source_bbox),
                    "rotation": block.rotation,
                    "reading_order": block.reading_order,
                    "group_member_ids": list(block.group_member_ids),
                    "merge_decision": block.merge_decision,
                    "gold_translation": block.gold_translation,
                    "literal_tokens": list(block.literal_tokens),
                    "allowed_regions": [list(rect) for rect in block.allowed_regions],
                    "forbidden_zones": [list(rect) for rect in block.forbidden_zones],
                    "font_size_range": list(block.font_size_range),
                    "leader": _thaw(block.leader),
                    "manual_review_required": block.manual_review_required,
                    "legacy_fallback": block.legacy_fallback,
                }
                for block in self.blocks
            ],
            "audit": [_thaw(item) for item in self.audit],
        }


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
    if manifest.benchmark_version != "core-v1":
        raise ValueError("unsupported core manifest version")
    if len(samples) != 12 or len({item.sample_id for item in samples}) != 12:
        raise ValueError("core manifest must contain 12 unique samples")
    if [item.sample_id for item in samples] != [
        f"core-{index:02d}" for index in range(1, 13)
    ]:
        raise ValueError("core manifest must use approved core sample IDs in order")
    if any(item.page_number != 1 for item in samples):
        raise ValueError("approved core samples must use page 1")
    if len({item.relative_pdf.casefold() for item in samples}) != len(samples):
        raise ValueError("core manifest PDF paths must be unique case-insensitively")
    return manifest


def load_challenge_manifest(path: Path) -> CoreManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != "engineering-drawing-challenge-set-v1":
        raise ValueError("unsupported challenge manifest schema")
    if payload.get("benchmark_version") != "challenge-v1":
        raise ValueError("unsupported challenge manifest version")
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
    try:
        page_width = float(sample.page["width"])
        page_height = float(sample.page["height"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("page geometry must include width and height") from error
    if page_width <= 0 or page_height <= 0:
        raise ValueError("page geometry must be non-empty")
    if sample.page.get("rotation") not in {0, 90, 180, 270}:
        raise ValueError("page rotation must be orthogonal")
    page_rect = (0.0, 0.0, page_width, page_height)
    for block in sample.blocks:
        if block.rotation not in {0, 90, 180, 270}:
            raise ValueError("rotation must be orthogonal")
        if not block.source_text or not block.gold_translation:
            raise ValueError("source and gold translation are required")
        if (
            len(block.font_size_range) != 2
            or block.font_size_range[0] > block.font_size_range[1]
        ):
            raise ValueError("font_size_range must contain an ordered minimum and maximum")
        if block.font_size_range[0] < 3.2:
            raise ValueError("font_size_range is below the workflow minimum")
        if not isinstance(block.leader.get("allowed"), bool) or not isinstance(
            block.leader.get("required"), bool
        ):
            raise ValueError("leader allowed and required must be boolean")
        if block.leader["required"] and not block.leader["allowed"]:
            raise ValueError("required leader must be allowed")
        if block.leader.get("color") != "dark_blue":
            raise ValueError("leader color must be dark_blue")
        if block.leader.get("width_points") != 0.32:
            raise ValueError("leader width must be 0.32 points")
        if block.leader.get("route") != "orthogonal":
            raise ValueError("leader route must be orthogonal")
        if block.leader.get("arrow") is not False:
            raise ValueError("leader arrow must be false")
        if block.legacy_fallback and not block.manual_review_required:
            raise ValueError("legacy fallback requires manual review")
        if block.manual_review_required and block.leader["required"]:
            raise ValueError("manual review cannot require a leader")
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
