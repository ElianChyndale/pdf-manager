from __future__ import annotations

import json
import math
import re
import unicodedata
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
_LEADER_FIELDS = {"allowed", "required", "color", "width_points", "route", "arrow"}
_FINDING_FIELDS = {"code", "region_id", "reason"}
_LITERAL_PATTERN = re.compile(
    r"""
    (?<![A-Za-z0-9])
    (?:
        (?:[Øø⌀]\s*)?[+-]?\d+(?:[.,]\d+)?\s*(?:[x×/]\s*(?:[Øø⌀]\s*)?[+-]?\d+(?:[.,]\d+)?\s*)+
        (?:%|[A-Za-zµμ°][A-Za-z0-9²³µμ°%./-]{0,11}(?:\s+[A-Z][A-Z0-9²³µμ°%./-]{0,11})*)?
        |
        (?:[Øø⌀]\s*)?[+-]?\d+(?:[.,]\d+)?\s*(?:%|[A-Za-zµμ°][A-Za-z0-9²³µμ°%./-]{0,11}(?:\s+[A-Z][A-Z0-9²³µμ°%./-]{0,11})*)?
        |
        [A-Za-z][A-Za-z0-9._/+:\-]*\d[A-Za-z0-9._/+:\-]*
        |
        (?:ID|NO|REF|TYPE|MODEL)\s*[-:\#]?\s*[A-Z0-9][A-Z0-9._/+:\-]*
    )
    (?![A-Za-z0-9])
    """,
    re.VERBOSE,
)
_DASH_TRANSLATION = str.maketrans({char: "-" for char in "‐‑‒–—―−"})
_PUNCTUATION_RE = re.compile(r"[,:;()\[\]{}'\"`]+")

_RECT_JSON_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 4,
    "maxItems": 4,
}
_LEADER_JSON_SCHEMA = {
    "type": "object",
    "required": ["allowed", "required", "color", "width_points", "route", "arrow"],
    "additionalProperties": False,
    "properties": {
        "allowed": {"type": "boolean"},
        "required": {"type": "boolean"},
        "color": {"type": "string", "enum": ["dark_blue"]},
        "width_points": {"type": "number", "const": 0.32},
        "route": {"type": "string", "enum": ["orthogonal"]},
        "arrow": {"type": "boolean", "const": False},
    },
}
_PRELABEL_BLOCK_JSON_SCHEMA = {
    "type": "object",
    "required": sorted(_REQUIRED_BLOCK_FIELDS),
    "additionalProperties": False,
    "properties": {
        "block_id": {"type": "string", "pattern": r"^.+-b\d{3}$"},
        "member_ids": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        "source_text": {"type": "string", "minLength": 1},
        "source_language": {"type": "string", "minLength": 1},
        "source_bbox": _RECT_JSON_SCHEMA,
        "rotation": {"type": "integer", "enum": [0, 90, 180, 270]},
        "reading_order": {"type": "integer", "minimum": 1},
        "merge_decision": {"type": "string", "enum": sorted(_MERGE_DECISIONS)},
        "gold_translation": {"type": "string", "minLength": 1, "pattern": r"[\u3400-\u9fff]"},
        "literal_tokens": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "allowed_regions": {"type": "array", "items": _RECT_JSON_SCHEMA},
        "forbidden_zones": {"type": "array", "items": _RECT_JSON_SCHEMA},
        "font_size_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
        "leader": _LEADER_JSON_SCHEMA,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "risk_flags": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}
PRELABEL_RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "required": ["blocks"],
    "additionalProperties": False,
    "properties": {
        "blocks": {"type": "array", "minItems": 1, "items": _PRELABEL_BLOCK_JSON_SCHEMA}
    },
}
_VISUAL_FINDING_JSON_SCHEMA = {
    "type": "object",
    "required": ["code", "region_id", "reason"],
    "additionalProperties": False,
    "properties": {
        "code": {"type": "string", "minLength": 1},
        "region_id": {"type": "string", "minLength": 1},
        "reason": {"type": "string", "minLength": 1},
    },
}
VISUAL_REVIEW_RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "required": ["layout_association", "page_readability", "findings"],
    "additionalProperties": False,
    "properties": {
        "layout_association": {"type": "number", "minimum": 0, "maximum": 20},
        "page_readability": {"type": "number", "minimum": 0, "maximum": 15},
        "findings": {"type": "array", "items": _VISUAL_FINDING_JSON_SCHEMA},
    },
}


def build_prelabel_request(
    *,
    sample_id: str,
    image_data_url: str,
    regions: list[dict],
) -> list[dict]:
    schema_text = json.dumps(PRELABEL_RESPONSE_JSON_SCHEMA, ensure_ascii=False, sort_keys=True)
    rules = (
        "Return JSON only: no markdown, prose, or code fence. "
        "Conform exactly to this JSON Schema (including additionalProperties=false): "
        + schema_text
        + " "
        f"Use block_id '{sample_id}-bNNN'; member_ids are supplied region IDs; rotation is one of "
        "0, 90, 180, 270; merge_decision is one of single, merge_paragraph, separate_identifier, "
        "table_cell, legend_entry, dimension, title_row. gold_translation must contain Chinese. "
        "Each rect is [x0,y0,x1,y1], font_size_range is [min,max] with min at least 3.2, and "
        "leader is {allowed:boolean,required:boolean,color:'dark_blue',width_points:0.32,"
        "route:'orthogonal',arrow:false}. Group complete notes/specifications by meaning, but keep "
        "equipment IDs, table cells, legend entries, dimensions, and title rows separate. Preserve "
        "all numbers, units, models, IDs, and source rotation. Propose whitespace allowed_regions "
        "and source/dimension/line forbidden_zones. Prefer right, then below, then above; use an "
        "orthogonal leader only for dense CAD labels."
    )
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
    _require_only_keys(payload, {"blocks"}, "prelabel response")
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
    _require_only_keys(
        payload,
        {"layout_association", "page_readability", "findings"},
        "visual review response",
    )
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
        _require_only_keys(raw, _FINDING_FIELDS, "visual finding")
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
    schema_text = json.dumps(
        VISUAL_REVIEW_RESPONSE_JSON_SCHEMA, ensure_ascii=False, sort_keys=True
    )
    messages = [
        {
            "role": "system",
            "content": (
                "Return JSON only: no markdown, prose, or code fence. Conform exactly to this JSON "
                "Schema (including additionalProperties=false): "
                + schema_text
                + " "
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


def _require_only_keys(value: dict, allowed: set[str], label: str) -> None:
    undeclared = set(value).difference(allowed)
    if undeclared:
        raise ValueError(f"{label} contains undeclared keys: {', '.join(sorted(undeclared))}")


def _validate_block_shape(raw: object, sample_id: str, seen_block_ids: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("every prelabel block must be an object")
    _require_only_keys(raw, _REQUIRED_BLOCK_FIELDS, "prelabel block")
    missing = _REQUIRED_BLOCK_FIELDS.difference(raw)
    if missing:
        raise ValueError(f"prelabel block is missing required fields: {', '.join(sorted(missing))}")
    item = dict(raw)
    block_id = item["block_id"]
    if (
        not isinstance(block_id, str)
        or not re.fullmatch(re.escape(sample_id) + r"-b\d{3}", block_id)
        or block_id in seen_block_ids
    ):
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
    ordered_members = _members_in_reading_order(member_regions)
    _validate_claimed_source_text(item["source_text"], ordered_members)
    member_boxes = [_rect(member.get("bbox"), "referenced member bbox") for member in ordered_members]
    for source_box in [source_bbox, *member_boxes]:
        if source_box not in item["forbidden_zones"]:
            item["forbidden_zones"].append(source_box)
    source_obstacles = [
        _rect(region.get("bbox"), "source region bbox")
        for region in region_index.values()
    ]
    for source_obstacle in source_obstacles:
        _require_inside_page(source_obstacle, page_rect, "source region bbox")
    for rect in [*item["allowed_regions"], *item["forbidden_zones"]]:
        _require_inside_page(rect, page_rect, "block geometry")
    if any(
        _intersects(allowed, source_bbox)
        for allowed in item["allowed_regions"]
        for source_bbox in source_obstacles
    ):
        raise ValueError("allowed_regions cannot overlap any source region bbox")
    if any(
        _intersects(allowed, forbidden)
        for allowed in item["allowed_regions"]
        for forbidden in item["forbidden_zones"]
    ):
        raise ValueError("allowed_regions cannot overlap forbidden_zones")
    derived_literals = _derived_literals(ordered_members)
    tokens = set(item["literal_tokens"])
    translation = item["gold_translation"]
    for literal in derived_literals:
        if literal not in tokens or literal not in translation:
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
    _require_only_keys(value, _LEADER_FIELDS, "leader rule")
    if not _LEADER_FIELDS.issubset(value):
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
        literals.update(derive_engineering_literals(text))
    return literals


def _members_in_reading_order(member_regions: list[dict]) -> list[dict]:
    ordered = []
    for index, region in enumerate(member_regions):
        reading_order = region.get("reading_order", index + 1)
        if not _is_integer(reading_order) or reading_order <= 0:
            raise ValueError("referenced member reading_order must be a positive integer")
        ordered.append((reading_order, index, region))
    return [region for _, _, region in sorted(ordered)]


def _validate_claimed_source_text(claimed_source_text: str, member_regions: list[dict]) -> None:
    claimed = _canonical_source_text(claimed_source_text)
    cursor = 0
    for region in member_regions:
        source_text = region.get("source_text", region.get("text", ""))
        if not isinstance(source_text, str) or not source_text.strip():
            raise ValueError("referenced member source text must be a non-empty string")
        member = _canonical_source_text(source_text)
        position = claimed.find(member, cursor)
        if position < 0:
            raise ValueError("source_text must include member texts in reading order")
        cursor = position + len(member)


def _canonical_source_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).translate(_DASH_TRANSLATION).casefold()
    text = _PUNCTUATION_RE.sub(" ", text)
    text = re.sub(r"\s*[-/]\s*", lambda match: match.group(0).strip(), text)
    return re.sub(r"\s+", " ", text).strip()


def derive_engineering_literals(source_text: str) -> list[str]:
    """Return unique source-ordered engineering runs that must survive translation exactly."""
    seen = set()
    result = []
    for match in _LITERAL_PATTERN.finditer(source_text or ""):
        literal = match.group(0).strip()
        if literal and literal not in seen:
            seen.add(literal)
            result.append(literal)
    return result


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
