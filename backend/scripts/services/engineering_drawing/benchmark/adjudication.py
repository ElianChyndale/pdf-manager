from __future__ import annotations

from copy import deepcopy
from typing import Any

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


def _validate_prelabel_contract(prelabel: object) -> dict[str, Any]:
    if not isinstance(prelabel, dict):
        raise ValueError("adjudication requires a prelabel object")
    if prelabel.get("schema") != "engineering-drawing-prelabel-v1":
        raise ValueError("adjudication requires an engineering-drawing prelabel")
    if prelabel.get("status") != "prelabeled":
        raise ValueError("adjudication requires a prelabeled record")
    if not isinstance(prelabel.get("page"), dict):
        raise ValueError("adjudication prelabel requires page metadata")
    if not isinstance(prelabel.get("blocks"), list):
        raise ValueError("adjudication prelabel requires blocks")
    return prelabel


def _gold_payload(prelabel: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    for raw in prelabel["blocks"]:
        blocks.append(
            {
                "block_id": raw["block_id"],
                "source_text": raw["source_text"],
                "source_language": raw["source_language"],
                "source_bbox": raw["source_bbox"],
                "rotation": raw["rotation"],
                "reading_order": raw["reading_order"],
                "group_member_ids": list(raw["member_ids"]),
                "merge_decision": raw["merge_decision"],
                "gold_translation": raw["gold_translation"],
                "literal_tokens": list(raw["literal_tokens"]),
                "allowed_regions": list(raw["allowed_regions"]),
                "forbidden_zones": list(raw["forbidden_zones"]),
                "font_size_range": list(raw["font_size_range"]),
                "leader": dict(raw["leader"]),
                "manual_review_required": False,
                "legacy_fallback": False,
            }
        )
    return {
        "schema": "engineering-drawing-gold-v1",
        "sample_id": prelabel["sample_id"],
        "gold_version": 1,
        "status": "adjudicated",
        "page": dict(prelabel["page"]),
        "blocks": blocks,
        "audit": [],
    }


def apply_adjudication(
    prelabel: dict[str, Any],
    decisions: list[dict[str, Any]],
    actor: str,
    decided_at: str,
) -> GoldSample:
    """Create a version-one gold sample while retaining every adjudicated change."""
    payload = _gold_payload(deepcopy(_validate_prelabel_contract(prelabel)))
    by_id = {block["block_id"]: block for block in payload["blocks"]}
    for decision in decisions:
        block_id = str(decision["block_id"])
        field = str(decision["field"])
        if block_id not in by_id or field not in EDITABLE_FIELDS:
            raise ValueError("decision targets an unknown block or field")
        reason = str(decision.get("reason") or "").strip()
        if not reason:
            raise ValueError("every adjudication requires a reason")
        old_value = deepcopy(by_id[block_id][field])
        new_value = deepcopy(decision["value"])
        by_id[block_id][field] = new_value
        payload["audit"].append(
            {
                "action": "adjudicate",
                "block_id": block_id,
                "field": field,
                "old_value": old_value,
                "new_value": deepcopy(new_value),
                "reason": reason,
                "actor": actor,
                "decided_at": decided_at,
            }
        )
    sample = GoldSample.from_dict(payload)
    validate_gold_sample(sample)
    return sample


def lock_gold(sample: GoldSample, actor: str, decided_at: str) -> GoldSample:
    """Append a lock event and create the next immutable gold version."""
    payload = sample.to_dict()
    payload["gold_version"] = sample.gold_version + 1
    payload["status"] = "locked"
    payload["audit"].append(
        {
            "action": "lock",
            "actor": actor,
            "decided_at": decided_at,
            "from_version": sample.gold_version,
            "to_version": sample.gold_version + 1,
        }
    )
    locked = GoldSample.from_dict(payload)
    validate_gold_sample(locked)
    return locked
