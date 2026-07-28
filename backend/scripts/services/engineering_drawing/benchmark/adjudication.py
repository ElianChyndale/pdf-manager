from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
import math
import re
from typing import Any

from .prelabel import (
    PRELABEL_PROMPT_VERSION,
    PRELABEL_RESPONSE_JSON_SCHEMA,
    PRELABEL_SCHEMA,
)
from .schema import GoldSample, validate_gold_sample


EDITABLE_FIELDS = {
    "gold_translation",
    "merge_decision",
    "allowed_regions",
    "forbidden_zones",
    "font_size_range",
    "leader",
    "manual_review_required",
}
_MERGE_DECISIONS = frozenset(
    PRELABEL_RESPONSE_JSON_SCHEMA["properties"]["blocks"]["items"]["properties"]
    ["merge_decision"]["enum"]
)
_PRELABEL_FIELDS = {
    "schema",
    "prompt_version",
    "sample_id",
    "status",
    "model",
    "page",
    "blocks",
}
_PAGE_FIELDS = {"width", "height", "rotation"}
_PRELABEL_BLOCK_FIELDS = {
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
_DECISION_FIELDS = {"block_id", "field", "value", "reason"}


def _is_string(value: object) -> bool:
    return type(value) is str


def _is_nonempty_string(value: object) -> bool:
    return _is_string(value) and bool(value.strip())


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _require_exact_keys(value: object, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    value_keys = set(value)
    if value_keys != keys:
        raise ValueError(f"{label} must contain exactly the required fields")
    return value


def _rect(value: object, label: str) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4 or not all(
        _is_number(coordinate) for coordinate in value
    ):
        raise ValueError(f"{label} must contain four finite numeric coordinates")
    rect = tuple(float(coordinate) for coordinate in value)
    if rect[2] <= rect[0] or rect[3] <= rect[1]:
        raise ValueError(f"{label} must be non-empty")
    return rect


def _rects(value: object, label: str, *, require_items: bool) -> list[list[float]]:
    if not isinstance(value, (list, tuple)) or (require_items and not value):
        raise ValueError(f"{label} must be a non-empty list or tuple of rectangles")
    return [list(_rect(rect, label)) for rect in value]


def _inside(page: tuple[float, float, float, float], rect: tuple[float, float, float, float]) -> bool:
    return page[0] <= rect[0] and page[1] <= rect[1] and page[2] >= rect[2] and page[3] >= rect[3]


def _intersects(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(left[3], right[3]) > max(left[1], right[1])


def _validate_leader(value: object, label: str) -> dict[str, Any]:
    leader = _require_exact_keys(value, _LEADER_FIELDS, f"{label} leader")
    if type(leader["allowed"]) is not bool or type(leader["required"]) is not bool:
        raise ValueError(f"{label} leader allowed and required must be booleans")
    if leader["required"] and not leader["allowed"]:
        raise ValueError(f"{label} required leader must be allowed")
    if leader["color"] != "dark_blue":
        raise ValueError(f"{label} leader color must be dark_blue")
    if not _is_number(leader["width_points"]) or float(leader["width_points"]) != 0.32:
        raise ValueError(f"{label} leader width must be 0.32 points")
    if leader["route"] != "orthogonal":
        raise ValueError(f"{label} leader route must be orthogonal")
    if leader["arrow"] is not False:
        raise ValueError(f"{label} leader arrow must be false")
    return {
        "allowed": leader["allowed"],
        "required": leader["required"],
        "color": "dark_blue",
        "width_points": 0.32,
        "route": "orthogonal",
        "arrow": False,
    }


def _validate_font_range(value: object, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(
        _is_number(bound) for bound in value
    ):
        raise ValueError(f"{label} font_size_range must contain two finite numeric bounds")
    lower, upper = (float(bound) for bound in value)
    if lower < 3.2 or lower > upper:
        raise ValueError(f"{label} font_size_range must be ordered with a minimum of at least 3.2")
    return [lower, upper]


def _validate_translation(
    value: object,
    literal_tokens: object,
    label: str,
    *,
    exact_literals: bool,
) -> str:
    if not _is_nonempty_string(value) or not re.search(r"[\u3400-\u9fff]", value):
        raise ValueError(f"{label} gold_translation must be a non-empty Chinese string")
    if not isinstance(literal_tokens, (list, tuple)) or not all(
        _is_nonempty_string(token) for token in literal_tokens
    ):
        raise ValueError(f"{label} literal_tokens must be non-empty strings")
    literal_target = value if exact_literals else re.sub(r"\s+", "", value)
    if any((token if exact_literals else re.sub(r"\s+", "", token)) not in literal_target for token in literal_tokens):
        raise ValueError(f"{label} gold_translation must preserve every literal token")
    return value.strip()


def _validate_block_geometry(block: Mapping[str, Any], page: tuple[float, float, float, float], label: str) -> None:
    source = _rect(block["source_bbox"], f"{label} source_bbox")
    allowed = [_rect(rect, f"{label} allowed_regions") for rect in block["allowed_regions"]]
    forbidden = [_rect(rect, f"{label} forbidden_zones") for rect in block["forbidden_zones"]]
    if not _inside(page, source) or any(not _inside(page, rect) for rect in [*allowed, *forbidden]):
        raise ValueError(f"{label} geometry is outside the source page")
    if any(_intersects(left, right) for left in allowed for right in forbidden):
        raise ValueError(f"{label} allowed_regions overlap forbidden_zones")
    if block["manual_review_required"] and block["leader"]["required"]:
        raise ValueError(f"{label} manual review cannot require a leader")


def _validate_prelabel_contract(prelabel: object) -> dict[str, Any]:
    raw = _require_exact_keys(prelabel, _PRELABEL_FIELDS, "adjudication prelabel")
    if raw["schema"] != PRELABEL_SCHEMA or raw["prompt_version"] != PRELABEL_PROMPT_VERSION:
        raise ValueError("adjudication prelabel has an unsupported schema or prompt version")
    if raw["status"] != "prelabeled":
        raise ValueError("adjudication prelabel must have prelabeled status")
    if not _is_nonempty_string(raw["sample_id"]):
        raise ValueError("adjudication prelabel sample_id must be a non-empty string")
    if raw["model"] is not None and not _is_nonempty_string(raw["model"]):
        raise ValueError("adjudication prelabel model must be null or a non-empty string")
    page = _require_exact_keys(raw["page"], _PAGE_FIELDS, "adjudication prelabel page")
    if not _is_number(page["width"]) or not _is_number(page["height"]) or page["width"] <= 0 or page["height"] <= 0:
        raise ValueError("adjudication prelabel page width and height must be positive finite numbers")
    if type(page["rotation"]) is not int or page["rotation"] not in {0, 90, 180, 270}:
        raise ValueError("adjudication prelabel page rotation must be orthogonal")
    if not isinstance(raw["blocks"], list) or not raw["blocks"]:
        raise ValueError("adjudication prelabel blocks must be a non-empty list")

    page_rect = (0.0, 0.0, float(page["width"]), float(page["height"]))
    blocks = []
    seen_ids = set()
    for index, item in enumerate(raw["blocks"]):
        block = _validate_prelabel_block(item, raw["sample_id"], page_rect, index)
        if block["block_id"] in seen_ids:
            raise ValueError("adjudication prelabel block_id values must be unique")
        seen_ids.add(block["block_id"])
        blocks.append(block)
    return {
        "schema": raw["schema"],
        "prompt_version": raw["prompt_version"],
        "sample_id": raw["sample_id"].strip(),
        "status": raw["status"],
        "model": raw["model"],
        "page": {"width": float(page["width"]), "height": float(page["height"]), "rotation": page["rotation"]},
        "blocks": blocks,
    }


def _validate_prelabel_block(
    value: object,
    sample_id: str,
    page: tuple[float, float, float, float],
    index: int,
) -> dict[str, Any]:
    label = f"adjudication prelabel block {index + 1}"
    raw = _require_exact_keys(value, _PRELABEL_BLOCK_FIELDS, label)
    block_id = raw["block_id"]
    if not _is_string(block_id) or not re.fullmatch(re.escape(sample_id) + r"-b[0-9]{3}", block_id):
        raise ValueError(f"{label} block_id is invalid")
    if not isinstance(raw["member_ids"], list) or not raw["member_ids"] or not all(
        _is_nonempty_string(member) for member in raw["member_ids"]
    ) or len(raw["member_ids"]) != len(set(raw["member_ids"])):
        raise ValueError(f"{label} member_ids must be unique non-empty strings")
    if not _is_nonempty_string(raw["source_text"]) or not _is_nonempty_string(raw["source_language"]):
        raise ValueError(f"{label} source text and language must be non-empty strings")
    source_bbox = list(_rect(raw["source_bbox"], f"{label} source_bbox"))
    if type(raw["rotation"]) is not int or raw["rotation"] not in {0, 90, 180, 270}:
        raise ValueError(f"{label} rotation must be orthogonal")
    if type(raw["reading_order"]) is not int or raw["reading_order"] <= 0:
        raise ValueError(f"{label} reading_order must be a positive integer")
    if not _is_string(raw["merge_decision"]) or raw["merge_decision"] not in _MERGE_DECISIONS:
        raise ValueError(f"{label} merge_decision is unsupported")
    literal_tokens = raw["literal_tokens"]
    translation = _validate_translation(
        raw["gold_translation"], literal_tokens, label, exact_literals=False
    )
    allowed = _rects(raw["allowed_regions"], f"{label} allowed_regions", require_items=False)
    forbidden = _rects(raw["forbidden_zones"], f"{label} forbidden_zones", require_items=False)
    font_range = _validate_font_range(raw["font_size_range"], label)
    leader = _validate_leader(raw["leader"], label)
    if not _is_number(raw["confidence"]) or not 0 <= raw["confidence"] <= 1:
        raise ValueError(f"{label} confidence must be a finite number between zero and one")
    if not isinstance(raw["risk_flags"], list) or not all(_is_nonempty_string(flag) for flag in raw["risk_flags"]):
        raise ValueError(f"{label} risk_flags must be a list of non-empty strings")
    block = {
        "block_id": block_id,
        "member_ids": list(raw["member_ids"]),
        "source_text": raw["source_text"].strip(),
        "source_language": raw["source_language"].strip(),
        "source_bbox": source_bbox,
        "rotation": raw["rotation"],
        "reading_order": raw["reading_order"],
        "merge_decision": raw["merge_decision"],
        "gold_translation": translation,
        "literal_tokens": list(literal_tokens),
        "allowed_regions": allowed,
        "forbidden_zones": forbidden,
        "font_size_range": font_range,
        "leader": leader,
        "confidence": float(raw["confidence"]),
        "risk_flags": list(raw["risk_flags"]),
        "manual_review_required": False,
    }
    _validate_block_geometry(block, page, label)
    return block


def _gold_payload(prelabel: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "engineering-drawing-gold-v1",
        "sample_id": prelabel["sample_id"],
        "gold_version": 1,
        "status": "adjudicated",
        "page": deepcopy(prelabel["page"]),
        "blocks": [
            {
                "block_id": raw["block_id"],
                "source_text": raw["source_text"],
                "source_language": raw["source_language"],
                "source_bbox": deepcopy(raw["source_bbox"]),
                "rotation": raw["rotation"],
                "reading_order": raw["reading_order"],
                "group_member_ids": list(raw["member_ids"]),
                "merge_decision": raw["merge_decision"],
                "gold_translation": raw["gold_translation"],
                "literal_tokens": list(raw["literal_tokens"]),
                "allowed_regions": deepcopy(raw["allowed_regions"]),
                "forbidden_zones": deepcopy(raw["forbidden_zones"]),
                "font_size_range": list(raw["font_size_range"]),
                "leader": dict(raw["leader"]),
                "manual_review_required": False,
                "legacy_fallback": False,
            }
            for raw in prelabel["blocks"]
        ],
        "audit": [],
    }


def _validate_decision_value(field: str, value: object, block: Mapping[str, Any]) -> Any:
    label = "decision value"
    if field == "gold_translation":
        return _validate_translation(value, block["literal_tokens"], label, exact_literals=True)
    if field == "merge_decision":
        if not _is_string(value) or value not in _MERGE_DECISIONS:
            raise ValueError("decision value merge_decision is unsupported")
        return value
    if field in {"allowed_regions", "forbidden_zones"}:
        return _rects(value, f"decision value {field}", require_items=True)
    if field == "font_size_range":
        return _validate_font_range(value, label)
    if field == "leader":
        return _validate_leader(value, label)
    if field == "manual_review_required":
        if type(value) is not bool:
            raise ValueError("decision value manual_review_required must be a boolean")
        return value
    raise ValueError("decision targets an unknown block or field")


def _normalise(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(sorted((key, _normalise(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_normalise(item) for item in value)
    return value


def _validate_decisions(decisions: object, blocks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(decisions, (list, tuple)) or not decisions:
        raise ValueError("decisions must be a non-empty list or tuple")
    prepared = []
    targets = set()
    for raw in decisions:
        decision = _require_exact_keys(raw, _DECISION_FIELDS, "adjudication decision")
        block_id, field, reason = decision["block_id"], decision["field"], decision["reason"]
        if not _is_nonempty_string(block_id) or not _is_nonempty_string(field):
            raise ValueError("decision block_id and field must be non-empty strings")
        if not _is_nonempty_string(reason):
            raise ValueError("every decision requires a reason that is a non-empty string")
        block_id, field, reason = block_id.strip(), field.strip(), reason.strip()
        if block_id not in blocks or field not in EDITABLE_FIELDS:
            raise ValueError("decision targets an unknown block or field")
        target = (block_id, field)
        if target in targets:
            raise ValueError("decision cannot edit the same block field twice")
        targets.add(target)
        new_value = _validate_decision_value(field, decision["value"], blocks[block_id])
        if _normalise(blocks[block_id][field]) == _normalise(new_value):
            raise ValueError("decision is a semantic no-op")
        prepared.append(
            {
                "block_id": block_id,
                "field": field,
                "value": new_value,
                "reason": reason,
            }
        )
    return prepared


def _audit_identity(actor: object, decided_at: object, *, label: str = "audit") -> tuple[str, datetime, str]:
    if not _is_nonempty_string(actor):
        raise ValueError(f"{label} actor must be a non-empty string")
    if not _is_nonempty_string(decided_at) or "T" not in decided_at.strip():
        raise ValueError(f"{label} decided_at must be a timezone-aware ISO-8601 timestamp")
    text = decided_at.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{label} decided_at must be a timezone-aware ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} decided_at must be a timezone-aware ISO-8601 timestamp")
    return actor.strip(), parsed, parsed.isoformat()


def _latest_audit_time(audit: object) -> datetime | None:
    if not isinstance(audit, (list, tuple)):
        raise ValueError("existing audit history must be a list or tuple")
    latest = None
    for entry in audit:
        if not isinstance(entry, Mapping):
            raise ValueError("existing audit entry must be an object")
        _, parsed, _ = _audit_identity(entry.get("actor"), entry.get("decided_at"), label="existing audit")
        if latest is None or parsed > latest:
            latest = parsed
    return latest


def apply_adjudication(
    prelabel: dict[str, Any],
    decisions: list[dict[str, Any]],
    actor: str,
    decided_at: str,
) -> GoldSample:
    """Create immutable version-one gold with validated append-only adjudication events."""
    strict_prelabel = _validate_prelabel_contract(prelabel)
    actor, _, audit_time = _audit_identity(actor, decided_at)
    payload = _gold_payload(deepcopy(strict_prelabel))
    blocks = {block["block_id"]: block for block in payload["blocks"]}
    prepared = _validate_decisions(decisions, blocks)
    page = (0.0, 0.0, payload["page"]["width"], payload["page"]["height"])
    for decision in prepared:
        block = blocks[decision["block_id"]]
        old_value = deepcopy(block[decision["field"]])
        block[decision["field"]] = deepcopy(decision["value"])
        _validate_block_geometry(block, page, "decision value")
        payload["audit"].append(
            {
                "action": "adjudicate",
                "block_id": decision["block_id"],
                "field": decision["field"],
                "old_value": old_value,
                "new_value": deepcopy(decision["value"]),
                "reason": decision["reason"],
                "actor": actor,
                "decided_at": audit_time,
            }
        )
    sample = GoldSample.from_dict(payload)
    validate_gold_sample(sample)
    return sample


def lock_gold(sample: GoldSample, actor: str, decided_at: str) -> GoldSample:
    """Lock an adjudicated sample by appending one chronological lock audit event."""
    if not isinstance(sample, GoldSample):
        raise ValueError("lock requires a GoldSample")
    if sample.status != "adjudicated":
        raise ValueError("only an adjudicated sample can be locked")
    actor, lock_time, audit_time = _audit_identity(actor, decided_at)
    latest_audit = _latest_audit_time(sample.audit)
    if latest_audit is not None and lock_time < latest_audit:
        raise ValueError("lock timestamp cannot be before existing audit history")
    payload = sample.to_dict()
    payload["gold_version"] = sample.gold_version + 1
    payload["status"] = "locked"
    payload["audit"].append(
        {
            "action": "lock",
            "actor": actor,
            "decided_at": audit_time,
            "from_version": sample.gold_version,
            "to_version": sample.gold_version + 1,
        }
    )
    locked = GoldSample.from_dict(payload)
    validate_gold_sample(locked)
    return locked
