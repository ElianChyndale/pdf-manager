from __future__ import annotations

from collections import Counter
import math
import re
import unicodedata
from typing import Any


_CJK = re.compile(r"[\u3400-\u9fff]")
_DASH_TRANSLATION = str.maketrans({char: "-" for char in "‐‑‒–—―−"})
_ROTATIONS = {0, 90, 180, 270}
_LEADER_RULE_FIELDS = {
    "allowed",
    "required",
    "color",
    "width_points",
    "route",
    "arrow",
}
_DRAWN_LEADER_STYLE_FIELDS = {"color", "width_points", "route", "arrow"}
_MANUAL_FALLBACK_STATUSES = {
    "inline_legacy_fallback",
    "legacy_fallback",
    "manual_review_fallback",
}
_VISUAL_QA_COUNTERS = (
    "visual_overlap_count",
    "leader_collision_count",
    "untranslated_candidate_count",
)
_PDF_DIAGNOSTIC_COUNTERS = (
    "replacement_characters",
    "private_use_characters",
    "clipped_or_outside_count",
)
_MAX_COUNTER = (1 << 63) - 1
_PROMOTION_REQUIRED_FIELDS = {
    "core_score",
    "hard_failure_count",
    "manual_review_rate",
    "category_scores",
    "challenge_pass_rate",
}
def _fold(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _bounded_number(value: object, minimum: float, maximum: float) -> bool:
    return _number(value) and minimum <= value <= maximum


def _counter(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= _MAX_COUNTER
    )


def _rotation(value: object) -> bool:
    return _number(value) and value in _ROTATIONS


def _rect(value: object) -> tuple[float, float, float, float] | None:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or not all(_number(item) for item in value)
    ):
        return None
    result = tuple(float(item) for item in value)
    return result if result[2] > result[0] and result[3] > result[1] else None


def _contains(
    outer: tuple[float, ...], inner: tuple[float, ...]
) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def _intersects(
    left: tuple[float, ...], right: tuple[float, ...]
) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])


def _failure_identity(code: str, scope: str | None = None) -> str:
    return code if scope is None else f"{code}:{scope}"


def _add_failure(
    failures: dict[str, dict[str, Any]],
    code: str,
    *,
    block_id: str | None = None,
    region_id: str | None = None,
    fields: list[str] | None = None,
    **details: Any,
) -> None:
    scope = block_id if block_id is not None else region_id
    identity = _failure_identity(code, scope)
    item: dict[str, Any] = {"code": code}
    if block_id is not None:
        item["block_id"] = block_id
    elif region_id is not None:
        item["region_id"] = region_id
    if fields:
        item["fields"] = sorted(set(fields))
    item.update(details)
    existing = failures.get(identity)
    if existing is None:
        failures[identity] = item
        return
    if fields:
        existing["fields"] = sorted(
            set(existing.get("fields", [])) | set(fields)
        )


def _gold_invalid_fields(gold: object) -> list[str]:
    if not isinstance(gold, dict):
        return ["block"]
    invalid = []
    if not _nonempty_string(gold.get("block_id")):
        invalid.append("block_id")
    if not _nonempty_string(gold.get("gold_translation")):
        invalid.append("gold_translation")
    if not _nonempty_string(gold.get("merge_decision")):
        invalid.append("merge_decision")
    if not _rotation(gold.get("rotation")):
        invalid.append("rotation")
    if not isinstance(gold.get("manual_review_required"), bool):
        invalid.append("manual_review_required")

    literals = gold.get("literal_tokens")
    if not isinstance(literals, (list, tuple)) or not all(
        _nonempty_string(token) for token in literals
    ):
        invalid.append("literal_tokens")

    for field in ("allowed_regions", "forbidden_zones"):
        values = gold.get(field)
        if not isinstance(values, (list, tuple)):
            invalid.append(field)
            continue
        rects = [_rect(value) for value in values]
        if any(rect is None for rect in rects):
            invalid.append(field)

    font_range = gold.get("font_size_range")
    if (
        not isinstance(font_range, (list, tuple))
        or len(font_range) != 2
        or not all(_number(value) for value in font_range)
        or font_range[0] < 3.2
        or font_range[0] > font_range[1]
    ):
        invalid.append("font_size_range")

    leader = gold.get("leader")
    if not isinstance(leader, dict) or set(leader) != _LEADER_RULE_FIELDS:
        invalid.append("leader")
    elif (
        not isinstance(leader["allowed"], bool)
        or not isinstance(leader["required"], bool)
        or (leader["required"] and not leader["allowed"])
        or leader["color"] != "dark_blue"
        or not _number(leader["width_points"])
        or leader["width_points"] != 0.32
        or leader["route"] != "orthogonal"
        or leader["arrow"] is not False
    ):
        invalid.append("leader")
    return sorted(set(invalid))


def _candidate_invalid_fields(candidate: dict) -> list[str]:
    invalid = []
    if not _nonempty_string(candidate.get("merge_decision")):
        invalid.append("merge_decision")
    if not _rotation(candidate.get("rotation")):
        invalid.append("rotation")
    target_value = candidate.get("target_bbox")
    if target_value is not None and _rect(target_value) is None:
        invalid.append("target_bbox")
    if not _number(candidate.get("font_size")):
        invalid.append("font_size")
    leader = candidate.get("leader")
    if not isinstance(leader, dict) or not _nonempty_string(
        leader.get("status") if isinstance(leader, dict) else None
    ):
        invalid.append("leader")
    elif leader.get("status") == "drawn":
        width = leader.get("width_points")
        if "width_points" in leader and not _number(width):
            invalid.append("leader.width_points")
    return sorted(set(invalid))


def _fallback_numeric_invalid_fields(candidate: dict) -> list[str]:
    invalid = []
    if "rotation" in candidate and not _rotation(candidate["rotation"]):
        invalid.append("rotation")
    if "target_bbox" in candidate and _rect(candidate["target_bbox"]) is None:
        invalid.append("target_bbox")
    if "font_size" in candidate and not _number(candidate["font_size"]):
        invalid.append("font_size")
    leader = candidate.get("leader")
    if isinstance(leader, dict) and "width_points" in leader and not _number(
        leader["width_points"]
    ):
        invalid.append("leader.width_points")
    return sorted(set(invalid))


def _leader_style_matches(rule: dict, candidate: dict) -> bool:
    leader = candidate.get("leader")
    if not isinstance(leader, dict):
        return False
    if not _DRAWN_LEADER_STYLE_FIELDS.issubset(leader):
        return False
    width = leader.get("width_points")
    if not _number(width):
        return False
    return (
        leader["color"] == rule["color"]
        and width == rule["width_points"]
        and leader["route"] == rule["route"]
        and leader["arrow"] is rule["arrow"]
    )


def _literal_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(
        _DASH_TRANSLATION
    )
    return re.sub(r"\s+", "", normalized).casefold()


def _literal_present(token: str, target: str) -> bool:
    normalized_token = _literal_key(token)
    normalized_target = _literal_key(target)
    token_chars = r"a-z0-9._/+:%°µμ-"
    prefix = (
        rf"(?<![{token_chars}])"
        if normalized_token[0].isascii() and normalized_token[0].isalnum()
        else ""
    )
    suffix = (
        rf"(?![{token_chars}])"
        if normalized_token[-1].isascii() and normalized_token[-1].isalnum()
        else ""
    )
    return re.search(
        prefix + re.escape(normalized_token) + suffix,
        normalized_target,
    ) is not None


def _authorized_manual_fallback(gold: dict, candidate: dict | None) -> bool:
    if not gold.get("manual_review_required") or not isinstance(candidate, dict):
        return False
    reason = candidate.get("manual_review_reason", candidate.get("reason"))
    return (
        candidate.get("manual_review_required") is True
        and candidate.get("status") in _MANUAL_FALLBACK_STATUSES
        and _nonempty_string(reason)
    )


def _subjective_dimension(
    subjective: object,
    field: str,
    maximum: float,
    failures: dict[str, dict[str, Any]],
) -> float:
    value = subjective.get(field) if isinstance(subjective, dict) else None
    if not _bounded_number(value, 0.0, maximum):
        _add_failure(
            failures,
            "invalid_subjective",
            fields=[field],
        )
        return 0.0
    return float(value)


def _validated_counter_evidence(
    value: object,
    *,
    required_counters: tuple[str, ...],
    failure_code: str,
    failures: dict[str, dict[str, Any]],
) -> dict[str, int]:
    if not isinstance(value, dict):
        _add_failure(
            failures,
            failure_code,
            fields=["container"],
        )
        return {}
    valid: dict[str, int] = {}
    invalid_fields = []
    for field in required_counters:
        if field not in value or not _counter(value[field]):
            invalid_fields.append(field)
            continue
        valid[field] = value[field]
    if invalid_fields:
        _add_failure(
            failures,
            failure_code,
            fields=invalid_fields,
        )
    return valid


def score_sample(
    *,
    gold_blocks: list[dict],
    candidate_blocks: list[dict],
    visual_qa: dict,
    pdf_diagnostics: dict,
    subjective: dict,
) -> dict:
    failures: dict[str, dict[str, Any]] = {}
    semantic_points = coverage_points = grouping_points = 0.0

    if not isinstance(gold_blocks, list) or not gold_blocks:
        _add_failure(failures, "empty_gold_sample")
        gold_items: list[object] = []
    else:
        gold_items = list(gold_blocks)
    candidate_items = (
        list(candidate_blocks) if isinstance(candidate_blocks, list) else []
    )
    if not isinstance(candidate_blocks, list):
        _add_failure(
            failures,
            "invalid_candidate",
            fields=["candidate_blocks"],
        )

    gold_ids = [
        item["block_id"].strip()
        for item in gold_items
        if isinstance(item, dict) and _nonempty_string(item.get("block_id"))
    ]
    candidate_ids = [
        str(item.get("block_id") or item.get("region_id")).strip()
        for item in candidate_items
        if isinstance(item, dict)
        and _nonempty_string(item.get("block_id") or item.get("region_id"))
    ]
    duplicate_gold_ids = sorted(
        block_id
        for block_id, count in Counter(gold_ids).items()
        if count > 1
    )
    duplicate_candidate_ids = sorted(
        block_id
        for block_id, count in Counter(candidate_ids).items()
        if count > 1
    )
    for block_id in duplicate_gold_ids:
        _add_failure(
            failures,
            "duplicate_gold_block_id",
            block_id=block_id,
        )
    for block_id in duplicate_candidate_ids:
        _add_failure(
            failures,
            "duplicate_translation",
            block_id=block_id,
        )

    candidate_by_id: dict[str, dict] = {}
    for index, candidate in enumerate(candidate_items):
        if not isinstance(candidate, dict):
            _add_failure(
                failures,
                "invalid_candidate",
                fields=[f"candidate_blocks[{index}]"],
            )
            continue
        raw_id = candidate.get("block_id") or candidate.get("region_id")
        if not _nonempty_string(raw_id):
            _add_failure(
                failures,
                "invalid_candidate",
                fields=[f"candidate_blocks[{index}].block_id"],
            )
            continue
        candidate_id = raw_id.strip()
        if candidate_id not in duplicate_candidate_ids:
            candidate_by_id[candidate_id] = candidate

    duplicate_gold_set = set(duplicate_gold_ids)
    denominator = max(1, len(gold_items))
    for index, raw_gold in enumerate(gold_items):
        if not isinstance(raw_gold, dict):
            _add_failure(
                failures,
                "invalid_gold",
                fields=[f"gold_blocks[{index}]"],
            )
            continue
        raw_block_id = raw_gold.get("block_id")
        block_id = raw_block_id.strip() if _nonempty_string(raw_block_id) else None
        invalid_gold = _gold_invalid_fields(raw_gold)
        if invalid_gold:
            _add_failure(
                failures,
                "invalid_gold",
                block_id=block_id,
                fields=invalid_gold,
            )
            continue
        assert block_id is not None
        if block_id in duplicate_gold_set:
            continue

        candidate = candidate_by_id.get(block_id)
        translated = candidate.get("translated_text") if candidate else None
        if translated is None or (
            isinstance(translated, str) and not translated.strip()
        ):
            if candidate is not None:
                invalid_fallback = _fallback_numeric_invalid_fields(candidate)
                if invalid_fallback:
                    _add_failure(
                        failures,
                        "invalid_candidate",
                        block_id=block_id,
                        fields=invalid_fallback,
                    )
            if not _authorized_manual_fallback(raw_gold, candidate):
                _add_failure(
                    failures,
                    "missing_translation",
                    block_id=block_id,
                )
            continue
        if not isinstance(translated, str):
            _add_failure(
                failures,
                "invalid_candidate",
                block_id=block_id,
                fields=["translated_text"],
            )
            continue

        invalid_candidate = _candidate_invalid_fields(candidate)
        if invalid_candidate:
            _add_failure(
                failures,
                "invalid_candidate",
                block_id=block_id,
                fields=invalid_candidate,
            )
            continue

        target = translated
        if not _CJK.search(target):
            _add_failure(
                failures,
                "missing_chinese",
                block_id=block_id,
            )
        missing_literals = [
            token
            for token in raw_gold["literal_tokens"]
            if not _literal_present(token, target)
        ]
        if missing_literals:
            _add_failure(
                failures,
                "literal_changed",
                block_id=block_id,
                tokens=missing_literals,
            )

        block_weight = 1 / denominator
        # Human ruling for Fix Round 1: every nonempty, valid candidate receives
        # 15/30 semantic points when it is not an exact normalized gold match.
        semantic_points += (
            30 * block_weight
            if _fold(raw_gold["gold_translation"]) == _fold(target)
            else 15 * block_weight
        )
        coverage_points += 20 * block_weight
        if candidate["merge_decision"] == raw_gold["merge_decision"]:
            grouping_points += 15 * block_weight
        else:
            _add_failure(
                failures,
                "wrong_grouping",
                block_id=block_id,
            )

        if candidate["rotation"] != raw_gold["rotation"]:
            _add_failure(
                failures,
                "wrong_rotation",
                block_id=block_id,
            )

        target_bbox = _rect(candidate.get("target_bbox"))
        allowed = [_rect(value) for value in raw_gold["allowed_regions"]]
        forbidden = [_rect(value) for value in raw_gold["forbidden_zones"]]
        assert all(rect is not None for rect in [*allowed, *forbidden])
        if candidate.get("target_bbox") is None:
            _add_failure(
                failures,
                "missing_target_bbox",
                block_id=block_id,
            )
        elif target_bbox is not None and allowed and not any(
            _contains(rect, target_bbox)
            for rect in allowed
            if rect is not None
        ):
            _add_failure(
                failures,
                "outside_allowed_region",
                block_id=block_id,
            )
        elif target_bbox is not None and any(
            _intersects(rect, target_bbox)
            for rect in forbidden
            if rect is not None
        ):
            _add_failure(
                failures,
                "forbidden_zone_overlap",
                block_id=block_id,
            )

        font_range = raw_gold["font_size_range"]
        if not font_range[0] <= candidate["font_size"] <= font_range[1]:
            _add_failure(
                failures,
                "unsafe_font_size",
                block_id=block_id,
            )

        leader_rule = raw_gold["leader"]
        leader = candidate["leader"]
        leader_drawn = leader.get("status") == "drawn"
        if leader_rule["required"] and not leader_drawn:
            _add_failure(
                failures,
                "required_leader_missing",
                block_id=block_id,
            )
        if leader_drawn and not leader_rule["allowed"]:
            _add_failure(
                failures,
                "leader_forbidden",
                block_id=block_id,
            )
        if leader_drawn and not _leader_style_matches(leader_rule, candidate):
            _add_failure(
                failures,
                "leader_style",
                block_id=block_id,
            )

    pdf_counts = _validated_counter_evidence(
        pdf_diagnostics,
        required_counters=_PDF_DIAGNOSTIC_COUNTERS,
        failure_code="invalid_pdf_diagnostics",
        failures=failures,
    )
    if pdf_counts.get("replacement_characters", 0) > 0 or pdf_counts.get(
        "private_use_characters", 0
    ) > 0:
        _add_failure(failures, "garbled_text")
    if pdf_counts.get("clipped_or_outside_count", 0) > 0:
        _add_failure(failures, "clipped_or_outside")

    visual_counts = _validated_counter_evidence(
        visual_qa,
        required_counters=_VISUAL_QA_COUNTERS,
        failure_code="invalid_visual_qa",
        failures=failures,
    )
    if visual_counts.get("visual_overlap_count", 0) > 0:
        _add_failure(failures, "source_or_translation_overlap")
    if visual_counts.get("leader_collision_count", 0) > 0:
        _add_failure(failures, "leader_collision")
    if visual_counts.get("untranslated_candidate_count", 0) > 0:
        _add_failure(failures, "untranslated_candidate")

    layout_points = _subjective_dimension(
        subjective,
        "layout_association",
        20.0,
        failures,
    )
    readability_points = _subjective_dimension(
        subjective,
        "page_readability",
        15.0,
        failures,
    )
    dimensions = {
        "semantic_terminology": round(semantic_points, 3),
        "coverage_deduplication": round(coverage_points, 3),
        "semantic_grouping": round(grouping_points, 3),
        "layout_association": layout_points,
        "page_readability": readability_points,
    }
    hard_failure_ids = sorted(failures)
    hard_failures = [failures[identity] for identity in hard_failure_ids]
    return {
        "schema": "engineering-drawing-score-v1",
        "hard_failures": hard_failures,
        "hard_failure_ids": hard_failure_ids,
        "hard_failure_count": len(hard_failure_ids),
        "dimensions": dimensions,
        "score": round(sum(dimensions.values()), 3),
        "passed": not hard_failure_ids,
    }


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _canonical_failure_id(value: object) -> str | None:
    if not _nonempty_string(value):
        return None
    identity = value.strip()
    if ":" not in identity:
        return identity if _nonempty_string(identity) else None
    code, scope = identity.split(":", 1)
    if not _nonempty_string(code) or not _nonempty_string(scope):
        return None
    return f"{code.strip()}:{scope.strip()}"


def _identities_from_failures(
    value: object,
    *,
    label: str,
    reasons: list[str],
) -> set[str] | None:
    if not isinstance(value, list):
        _append_reason(reasons, f"invalid_{label}:hard_failures")
        return None
    identities: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or not _nonempty_string(item.get("code")):
            _append_reason(reasons, f"invalid_{label}:hard_failures")
            return None
        code = item["code"].strip()
        block_id = item.get("block_id")
        region_id = item.get("region_id")
        if block_id is not None and region_id is not None:
            _append_reason(reasons, f"invalid_{label}:hard_failures")
            return None
        scope = block_id if block_id is not None else region_id
        if scope is not None and not _nonempty_string(scope):
            _append_reason(reasons, f"invalid_{label}:hard_failures")
            return None
        identities.add(
            _failure_identity(
                code,
                scope.strip() if isinstance(scope, str) else None,
            )
        )
    return identities


def _normalize_snapshot_identities(
    snapshot: dict,
    *,
    label: str,
    reasons: list[str],
) -> set[str] | None:
    has_ids = "hard_failure_ids" in snapshot
    has_items = "hard_failures" in snapshot
    if not has_ids and not has_items:
        _append_reason(
            reasons,
            f"invalid_{label}:missing_hard_failure_identity",
        )
        return None

    ids: set[str] | None = None
    if has_ids:
        raw_ids = snapshot["hard_failure_ids"]
        if not isinstance(raw_ids, list):
            _append_reason(reasons, f"invalid_{label}:hard_failure_ids")
        else:
            normalized = [_canonical_failure_id(item) for item in raw_ids]
            if any(item is None for item in normalized):
                _append_reason(reasons, f"invalid_{label}:hard_failure_ids")
            else:
                ids = {item for item in normalized if item is not None}

    item_ids = (
        _identities_from_failures(
            snapshot["hard_failures"],
            label=label,
            reasons=reasons,
        )
        if has_items
        else None
    )
    if ids is not None and item_ids is not None and ids != item_ids:
        _append_reason(reasons, f"invalid_{label}:hard_failure_identity_mismatch")
        return None
    return ids if ids is not None else item_ids


def _validate_promotion_snapshot(
    value: object,
    *,
    label: str,
    reasons: list[str],
) -> tuple[dict | None, set[str] | None, set[str] | None]:
    if not isinstance(value, dict):
        _append_reason(reasons, f"invalid_{label}:object")
        return None, None, None
    for key in sorted(_PROMOTION_REQUIRED_FIELDS - set(value)):
        _append_reason(reasons, f"invalid_{label}:missing_key:{key}")

    for key in ("core_score", "manual_review_rate", "challenge_pass_rate"):
        if key not in value:
            continue
        maximum = 100.0 if key == "core_score" else 1.0
        if not _bounded_number(value[key], 0.0, maximum):
            _append_reason(reasons, f"invalid_{label}:{key}")

    count = value.get("hard_failure_count")
    if "hard_failure_count" in value and (
        not isinstance(count, int) or isinstance(count, bool) or count < 0
    ):
        _append_reason(reasons, f"invalid_{label}:hard_failure_count")

    categories: set[str] | None = None
    category_scores = value.get("category_scores")
    if "category_scores" in value:
        if not isinstance(category_scores, dict) or not category_scores:
            _append_reason(reasons, f"invalid_{label}:category_scores")
        else:
            categories = set()
            for category, score in sorted(
                category_scores.items(),
                key=lambda item: str(item[0]),
            ):
                if not _nonempty_string(category):
                    _append_reason(reasons, f"invalid_{label}:category_scores")
                    continue
                if category != category.strip():
                    _append_reason(reasons, f"invalid_{label}:category_scores")
                    continue
                categories.add(category)
                if not _bounded_number(score, 0.0, 100.0):
                    _append_reason(
                        reasons,
                        f"invalid_{label}:category_score:{category}",
                    )

    identities = _normalize_snapshot_identities(
        value,
        label=label,
        reasons=reasons,
    )
    if (
        identities is not None
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
        and count != len(identities)
    ):
        _append_reason(
            reasons,
            f"invalid_{label}:hard_failure_count_mismatch",
        )
    return value, identities, categories


def promotion_decision(current: dict, candidate: dict) -> dict:
    reasons: list[str] = []
    current_value, current_ids, current_categories = _validate_promotion_snapshot(
        current,
        label="current",
        reasons=reasons,
    )
    candidate_value, candidate_ids, candidate_categories = (
        _validate_promotion_snapshot(
            candidate,
            label="candidate",
            reasons=reasons,
        )
    )
    if (
        current_categories is not None
        and candidate_categories is not None
        and current_categories != candidate_categories
    ):
        _append_reason(reasons, "category_universe_mismatch")

    valid_core_scores = (
        current_value is not None
        and candidate_value is not None
        and _bounded_number(current_value.get("core_score"), 0.0, 100.0)
        and _bounded_number(candidate_value.get("core_score"), 0.0, 100.0)
    )
    score_gain = (
        float(candidate_value["core_score"]) - float(current_value["core_score"])
        if valid_core_scores
        else None
    )
    if reasons:
        return {
            "promote": False,
            "reasons": reasons,
            "core_score_gain": score_gain,
            "new_hard_failure_ids": [],
        }

    assert current_value is not None and candidate_value is not None
    assert current_ids is not None and candidate_ids is not None
    new_hard_failure_ids = sorted(candidate_ids - current_ids)
    if new_hard_failure_ids:
        _append_reason(reasons, "new_hard_failures")

    assert score_gain is not None
    has_required_gain = score_gain >= 1.0
    equal_with_lower_review = score_gain == 0.0 and (
        candidate_value["manual_review_rate"]
        < current_value["manual_review_rate"]
    )
    if not has_required_gain and not equal_with_lower_review:
        _append_reason(reasons, "insufficient_core_gain")

    for category in sorted(current_value["category_scores"]):
        old_score = current_value["category_scores"][category]
        new_score = candidate_value["category_scores"][category]
        if new_score < old_score - 3:
            _append_reason(reasons, f"category_regression:{category}")
    if (
        candidate_value["challenge_pass_rate"]
        < current_value["challenge_pass_rate"]
    ):
        _append_reason(reasons, "challenge_regression")
    return {
        "promote": not reasons,
        "reasons": reasons,
        "core_score_gain": score_gain,
        "new_hard_failure_ids": new_hard_failure_ids,
    }
