from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Callable

from services.translation.llm.shared.response_parsing import extract_json_text


PRELABEL_SCHEMA = "engineering-drawing-prelabel-v1"
PRELABEL_PROMPT_VERSION = "2026-07-benchmark-block-v1"
VISUAL_REVIEW_SCHEMA = "engineering-drawing-visual-review-v1"
VISUAL_REVIEW_PROMPT_VERSION = "2026-07-benchmark-visual-v1"
_GEOMETRY_TOLERANCE = 1.0
_MERGE_DECISIONS = {
    "single",
    "merge_paragraph",
    "separate_identifier",
    "table_cell",
    "legend_entry",
    "dimension",
    "title_row",
}
_HIGH_VALUE_FLAGS = {
    "identifier_boundary",
    "number_or_unit",
    "unreadable",
    "layout_collision",
    "leader_route",
    "table_boundary",
}
_REQUIRED_BLOCK_FIELDS = {
    "block_id",
    "member_ids",
    "source_text",
    "source_language",
    "source_bbox",
    "rotation",
    "reading_order",
    "merge_decision",
    "gold_translation",
    "literal_tokens",
    "allowed_regions",
    "forbidden_zones",
    "font_size_range",
    "leader",
    "confidence",
    "risk_flags",
}
_LITERAL_PATTERN = re.compile(
    r"""
    (?<![A-Za-z0-9])
    (?:
        [A-Za-z]{1,12}[-_./]?\d+[A-Za-z0-9._/-]*
        |
        \d+(?:\.\d+)?\s*(?:MM|CM|M|KG|G|MPA|KPA|PA|KV|V|KW|W|HZ|MA|A|BMT|MIL|IN|FT|°C|%)
        (?:\s+[A-Z]{2,8})?
        |
        (?:ID|NO|REF|TYPE|MODEL)\s*[-:\#]?\s*[A-Z0-9][A-Z0-9._/-]*
        |
        \d+(?:\.\d+)?
    )
    (?![A-Za-z0-9])
    """,
    re.VERBOSE,
)


def build_prelabel_request(
    *,
    sample_id: str,
    image_data_url: str,
    regions: list[dict],
) -> list[dict]:
    rules = (
        "Return JSON only: no markdown, prose, or code fence. "
        "The exact top-level schema is {{\"blocks\":[BLOCK,...]}} and blocks must be nonempty. "
        "Every BLOCK must contain block_id, member_ids, source_text, source_language, "
        "source_bbox, rotation, reading_order, merge_decision, gold_translation, literal_tokens, "
        "allowed_regions, forbidden_zones, font_size_range, leader, confidence, and risk_flags. "
        "Use block_id '{sample_id}-bNNN'; member_ids are supplied region IDs; rotation is one of "
        "0, 90, 180, 270; merge_decision is one of single, merge_paragraph, separate_identifier, "
        "table_cell, legend_entry, dimension, title_row. gold_translation must contain Chinese. "
        "Each rect is [x0,y0,x1,y1], font_size_range is [min,max] with min at least 3.2, and "
        "leader is {{allowed:boolean,required:boolean,color:'dark_blue',width_points:0.32,"
        "route:'orthogonal',arrow:false}}. Group complete notes/specifications by meaning, but keep "
        "equipment IDs, table cells, legend entries, dimensions, and title rows separate. Preserve "
        "all numbers, units, models, IDs, and source rotation. Propose whitespace allowed_regions "
        "and source/dimension/line forbidden_zones. Prefer right, then below, then above; use an "
        "orthogonal leader only for dense CAD labels."
    ).format(sample_id=sample_id)
    return [
        {"role": "system", "content": rules},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"sample_id": sample_id, "regions": regions}, ensure_ascii=False
                    ),
                },
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def parse_prelabel_response(
    content: str,
    sample_id: str,
    *,
    regions: list[dict] | None = None,
    page: Mapping[str, float | int] | None = None,
    model: str | None = None,
) -> dict:
    payload = _json_object(content, "prelabel response")
    raw_blocks = payload.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError("prelabel response requires a non-empty blocks list")
    if (regions is None) != (page is None):
        raise ValueError("regions and page must be supplied together")

    region_index: dict[str, dict] | None = None
    page_rect: tuple[float, float, float, float] | None = None
    if regions is not None and page is not None:
        region_index = _region_index(regions)
        page_rect = _page_rect(page)

    blocks = []
    seen_block_ids = set()
    claimed_member_ids = set()
    for raw in raw_blocks:
        item = _validate_block_shape(raw, sample_id, seen_block_ids)
        if region_index is not None and page_rect is not None:
            _validate_block_against_source(
                item,
                region_index=region_index,
                page_rect=page_rect,
                claimed_member_ids=claimed_member_ids,
            )
        blocks.append(item)

    result = {
        "schema": PRELABEL_SCHEMA,
        "prompt_version": PRELABEL_PROMPT_VERSION,
        "sample_id": sample_id,
        "status": "prelabeled",
        "model": model,
        "blocks": blocks,
    }
    if page is not None:
        result["page"] = dict(page)
    return result


def select_adjudication_queue(prelabel: dict) -> list[dict]:
    return [
        block
        for block in prelabel.get("blocks", [])
        if _is_number(block.get("confidence"))
        and (
            block["confidence"] < 0.8
            or bool(_HIGH_VALUE_FLAGS.intersection(block.get("risk_flags", [])))
        )
    ]


def request_prelabels(
    *,
    sample_id: str,
    image_data_url: str,
    regions: list[dict],
    page: dict[str, float | int],
    api_key: str,
    model: str,
    base_url: str,
    request_fn: Callable[..., str],
) -> dict:
    content = request_fn(
        api_key=api_key,
        model=model,
        base_url=base_url,
        messages=build_prelabel_request(
            sample_id=sample_id,
            image_data_url=image_data_url,
            regions=regions,
        ),
        request_label="engineering-benchmark-prelabel",
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return parse_prelabel_response(
        content,
        sample_id,
        regions=regions,
        page=page,
        model=model,
    )


def parse_visual_review_response(
    content: str,
    sample_id: str,
    model: str,
    *,
    candidate_region_ids: Sequence[str] | None = None,
) -> dict:
    payload = _json_object(content, "visual review response")
    layout = _bounded_score(payload.get("layout_association"), 20, "layout_association")
    readability = _bounded_score(payload.get("page_readability"), 15, "page_readability")
    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise ValueError("visual review findings must be a list")
    known_region_ids = _candidate_region_ids(candidate_region_ids)
    findings = []
    for raw in raw_findings:
        if not isinstance(raw, dict):
            raise ValueError("every visual finding must be an object")
        code = raw.get("code")
        region_id = raw.get("region_id")
        reason = raw.get("reason")
        if not all(isinstance(value, str) and value.strip() for value in (code, region_id, reason)):
            raise ValueError("every visual finding requires code, region_id, and reason")
        if region_id not in known_region_ids:
            raise ValueError("visual finding region_id is not a candidate region")
        findings.append(dict(raw))
    return {
        "schema": VISUAL_REVIEW_SCHEMA,
        "prompt_version": VISUAL_REVIEW_PROMPT_VERSION,
        "sample_id": sample_id,
        "model": model,
        "layout_association": layout,
        "page_readability": readability,
        "findings": findings,
    }


def request_visual_review(
    *,
    sample_id: str,
    source_image_data_url: str,
    candidate_image_data_url: str,
    candidate_region_ids: Sequence[str],
    api_key: str,
    model: str,
    base_url: str,
    request_fn: Callable[..., str],
) -> dict:
    known_region_ids = _candidate_region_ids(candidate_region_ids)
    messages = [
        {
            "role": "system",
            "content": (
                "Return JSON only: no markdown, prose, or code fence. The exact top-level schema is "
                "{\"layout_association\":number,\"page_readability\":number,\"findings\":[FINDING,...]}. "
                "layout_association is 0 through 20 and page_readability is 0 through 15. Every FINDING "
                "is {\"code\":string,\"region_id\":string,\"reason\":string}; region_id must be one "
                "of the supplied candidate IDs. Compare source and bilingual candidate as an engineering "
                "drawing. Check missing translations, semantic fragmentation, source overlap, unsafe font "
                "size, unclear source-target association, and leader obstruction. Empty findings is allowed."
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "sample_id": sample_id,
                            "candidate_region_ids": sorted(known_region_ids),
                        }
                    ),
                },
                {"type": "image_url", "image_url": {"url": source_image_data_url}},
                {
                    "type": "image_url",
                    "image_url": {"url": candidate_image_data_url},
                },
            ],
        },
    ]
    content = request_fn(
        api_key=api_key,
        model=model,
        base_url=base_url,
        messages=messages,
        request_label="engineering-benchmark-visual-review",
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return parse_visual_review_response(
        content,
        sample_id,
        model,
        candidate_region_ids=known_region_ids,
    )


def _json_object(content: str, label: str) -> dict:
    payload = json.loads(extract_json_text(content))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _validate_block_shape(raw: object, sample_id: str, seen_block_ids: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("every prelabel block must be an object")
    missing = _REQUIRED_BLOCK_FIELDS.difference(raw)
    if missing:
        raise ValueError(f"prelabel block is missing required fields: {', '.join(sorted(missing))}")
    item = dict(raw)
    block_id = item["block_id"]
    if not isinstance(block_id, str) or not block_id.startswith(f"{sample_id}-b") or block_id in seen_block_ids:
        raise ValueError("block_id must be stable and unique")
    seen_block_ids.add(block_id)
    if not _nonempty_string(item["source_text"]) or not _nonempty_string(item["source_language"]):
        raise ValueError("source_text and source_language must be non-empty strings")
    if not _nonempty_string(item["gold_translation"]) or not re.search(r"[\u3400-\u9fff]", item["gold_translation"]):
        raise ValueError("gold_translation must be a non-empty Chinese translation")
    _validate_member_ids(item["member_ids"])
    item["source_bbox"] = _rect(item["source_bbox"], "source_bbox")
    if not _is_integer(item["rotation"]) or item["rotation"] not in {0, 90, 180, 270}:
        raise ValueError("rotation must be one of 0, 90, 180, 270")
    if not _is_integer(item["reading_order"]) or item["reading_order"] <= 0:
        raise ValueError("reading_order must be a positive integer")
    if (
        not isinstance(item["merge_decision"], str)
        or item["merge_decision"] not in _MERGE_DECISIONS
    ):
        raise ValueError("merge_decision is unsupported")
    _validate_literal_tokens(item["literal_tokens"], item["gold_translation"])
    item["allowed_regions"] = _rect_list(item["allowed_regions"], "allowed_regions")
    item["forbidden_zones"] = _rect_list(item["forbidden_zones"], "forbidden_zones")
    _validate_font_range(item["font_size_range"])
    _validate_leader(item["leader"])
    if not _is_number(item["confidence"]) or not 0 <= item["confidence"] <= 1:
        raise ValueError("confidence must be a non-boolean number between 0 and 1")
    if not isinstance(item["risk_flags"], list) or not all(
        _nonempty_string(flag) for flag in item["risk_flags"]
    ):
        raise ValueError("risk_flags must be a list of non-empty strings")
    return item


def _validate_block_against_source(
    item: dict,
    *,
    region_index: dict[str, dict],
    page_rect: tuple[float, float, float, float],
    claimed_member_ids: set[str],
) -> None:
    source_bbox = item["source_bbox"]
    _require_inside_page(source_bbox, page_rect, "source_bbox")
    member_regions = []
    for member_id in item["member_ids"]:
        if member_id not in region_index:
            raise ValueError(f"member_id is not a known source region: {member_id}")
        if member_id in claimed_member_ids:
            raise ValueError(f"member_id is reused across blocks: {member_id}")
        member = region_index[member_id]
        member_bbox = _rect(member.get("bbox"), f"region {member_id} bbox")
        _require_inside_page(member_bbox, page_rect, f"region {member_id} bbox")
        rotation = member.get("rotation", 0)
        if not _is_integer(rotation) or rotation not in {0, 90, 180, 270}:
            raise ValueError(f"region {member_id} rotation must be orthogonal")
        if rotation != item["rotation"]:
            raise ValueError("block rotation must agree with each member rotation")
        if not _contains(source_bbox, member_bbox, _GEOMETRY_TOLERANCE):
            raise ValueError("source_bbox must contain every member bbox")
        member_regions.append(member)
        claimed_member_ids.add(member_id)
    for rect in [*item["allowed_regions"], *item["forbidden_zones"]]:
        _require_inside_page(rect, page_rect, "block geometry")
    if any(
        _intersects(allowed, forbidden)
        for allowed in item["allowed_regions"]
        for forbidden in item["forbidden_zones"]
    ):
        raise ValueError("allowed_regions cannot overlap forbidden_zones")
    derived_literals = _derived_literals(member_regions)
    tokens = {_literal_key(token) for token in item["literal_tokens"]}
    translation = _literal_key(item["gold_translation"])
    for literal in derived_literals:
        key = _literal_key(literal)
        if key not in tokens or key not in translation:
            raise ValueError(f"derived literal is missing from tokens or translation: {literal}")


def _region_index(regions: list[dict]) -> dict[str, dict]:
    if not isinstance(regions, list):
        raise ValueError("regions must be a list")
    index = {}
    for raw in regions:
        if not isinstance(raw, dict) or not _nonempty_string(raw.get("id")):
            raise ValueError("each region must contain a non-empty id")
        region_id = raw["id"]
        if region_id in index:
            raise ValueError("region IDs must be unique")
        index[region_id] = raw
    return index


def _page_rect(page: Mapping[str, float | int]) -> tuple[float, float, float, float]:
    if not isinstance(page, Mapping):
        raise ValueError("page must be an object with width and height")
    width = page.get("width")
    height = page.get("height")
    if not _is_number(width) or not _is_number(height) or width <= 0 or height <= 0:
        raise ValueError("page width and height must be finite positive numbers")
    return (0.0, 0.0, float(width), float(height))


def _validate_member_ids(value: object) -> None:
    if not isinstance(value, list) or not value or not all(_nonempty_string(item) for item in value):
        raise ValueError("member_ids must be a non-empty list of strings")
    if len(value) != len(set(value)):
        raise ValueError("member_ids must be unique within a block")


def _validate_literal_tokens(value: object, translation: str) -> None:
    if not isinstance(value, list) or not all(_nonempty_string(token) for token in value):
        raise ValueError("literal_tokens must be a list of non-empty strings")
    target = _literal_key(translation)
    for token in value:
        if _literal_key(token) not in target:
            raise ValueError(f"literal token missing from translation: {token}")


def _validate_font_range(value: object) -> None:
    if not isinstance(value, list) or len(value) != 2 or not all(_is_number(bound) for bound in value):
        raise ValueError("font_size_range must contain two finite numeric bounds")
    if value[0] < 3.2 or value[0] > value[1]:
        raise ValueError("font_size_range must be ordered with a minimum of at least 3.2")


def _validate_leader(value: object) -> None:
    if not isinstance(value, dict):
        raise ValueError("leader must be an object")
    required = {"allowed", "required", "color", "width_points", "route", "arrow"}
    if not required.issubset(value):
        raise ValueError("leader rule is incomplete")
    if not isinstance(value["allowed"], bool) or not isinstance(value["required"], bool):
        raise ValueError("leader allowed and required must be booleans")
    if value["required"] and not value["allowed"]:
        raise ValueError("required leader must be allowed")
    if value["color"] != "dark_blue" or value["route"] != "orthogonal" or value["arrow"] is not False:
        raise ValueError("leader rule must use the fixed engineering style")
    if not _is_number(value["width_points"]) or value["width_points"] != 0.32:
        raise ValueError("leader width must be 0.32 points")


def _rect_list(value: object, field_name: str) -> list[tuple[float, float, float, float]]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [_rect(rect, field_name) for rect in value]


def _rect(value: object, field_name: str) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4 or not all(_is_number(item) for item in value):
        raise ValueError(f"{field_name} must contain four finite numeric coordinates")
    rect = tuple(float(item) for item in value)
    if rect[2] <= rect[0] or rect[3] <= rect[1]:
        raise ValueError(f"{field_name} must be non-empty")
    return rect


def _derived_literals(member_regions: list[dict]) -> set[str]:
    literals = set()
    for region in member_regions:
        text = region.get("source_text", region.get("text", ""))
        if not isinstance(text, str):
            raise ValueError("referenced member source text must be a string")
        literals.update(match.group(0).strip() for match in _LITERAL_PATTERN.finditer(text))
    return literals


def _candidate_region_ids(candidate_region_ids: Sequence[str] | None) -> set[str]:
    if candidate_region_ids is None:
        return set()
    if isinstance(candidate_region_ids, (str, bytes)) or not all(
        _nonempty_string(region_id) for region_id in candidate_region_ids
    ):
        raise ValueError("candidate_region_ids must contain non-empty strings")
    return set(candidate_region_ids)


def _bounded_score(value: object, maximum: float, field_name: str) -> float | int:
    if not _is_number(value) or not 0 <= value <= maximum:
        raise ValueError(f"{field_name} is outside its allowed range")
    return value


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _literal_key(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _require_inside_page(
    rect: tuple[float, float, float, float],
    page_rect: tuple[float, float, float, float],
    field_name: str,
) -> None:
    if not _contains(page_rect, rect, 0.0):
        raise ValueError(f"{field_name} is outside the source page")


def _contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    tolerance: float,
) -> bool:
    return (
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[2] + tolerance >= inner[2]
        and outer[3] + tolerance >= inner[3]
    )


def _intersects(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])
