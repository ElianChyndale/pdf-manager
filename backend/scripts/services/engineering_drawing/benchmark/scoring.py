from __future__ import annotations

import re
from typing import Any


_CJK = re.compile(r"[\u3400-\u9fff]")


def _fold(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _rect(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
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


def score_sample(
    *,
    gold_blocks: list[dict],
    candidate_blocks: list[dict],
    visual_qa: dict,
    pdf_diagnostics: dict,
    subjective: dict,
) -> dict:
    candidate_by_id = {
        str(item.get("block_id") or item.get("region_id")): item
        for item in candidate_blocks
    }
    hard_failures: list[dict[str, Any]] = []
    semantic_points = coverage_points = grouping_points = 0.0
    for gold in gold_blocks:
        block_id = str(gold["block_id"])
        candidate = candidate_by_id.get(block_id)
        if candidate is None or not str(
            candidate.get("translated_text") or ""
        ).strip():
            if not gold.get("manual_review_required"):
                hard_failures.append(
                    {"code": "missing_translation", "block_id": block_id}
                )
            continue

        target = str(candidate["translated_text"])
        if not _CJK.search(target):
            hard_failures.append({"code": "missing_chinese", "block_id": block_id})
        missing_literals = [
            token
            for token in gold.get("literal_tokens", [])
            if _fold(token) not in _fold(target)
        ]
        if missing_literals:
            hard_failures.append(
                {
                    "code": "literal_changed",
                    "block_id": block_id,
                    "tokens": missing_literals,
                }
            )

        block_weight = 1 / max(1, len(gold_blocks))
        semantic_points += (
            30 * block_weight
            if _fold(gold["gold_translation"]) == _fold(target)
            else 15 * block_weight
        )
        coverage_points += 20 * block_weight
        if str(candidate.get("merge_decision")) == str(
            gold.get("merge_decision")
        ):
            grouping_points += 15 * block_weight
        else:
            hard_failures.append(
                {"code": "wrong_grouping", "block_id": block_id}
            )

        if int(candidate.get("rotation", 0)) != int(gold.get("rotation", 0)):
            hard_failures.append(
                {"code": "wrong_rotation", "block_id": block_id}
            )

        target_bbox = _rect(candidate.get("target_bbox"))
        allowed = [
            rect
            for value in gold.get("allowed_regions", [])
            if (rect := _rect(value))
        ]
        forbidden = [
            rect
            for value in gold.get("forbidden_zones", [])
            if (rect := _rect(value))
        ]
        if target_bbox is None:
            hard_failures.append(
                {"code": "missing_target_bbox", "block_id": block_id}
            )
        elif allowed and not any(
            _contains(rect, target_bbox) for rect in allowed
        ):
            hard_failures.append(
                {"code": "outside_allowed_region", "block_id": block_id}
            )
        elif any(_intersects(rect, target_bbox) for rect in forbidden):
            hard_failures.append(
                {"code": "forbidden_zone_overlap", "block_id": block_id}
            )

        font_range = [
            float(value)
            for value in gold.get("font_size_range", [3.2, 18])
        ]
        font_size = float(candidate.get("font_size", 0))
        if not font_range[0] <= font_size <= font_range[1]:
            hard_failures.append(
                {"code": "unsafe_font_size", "block_id": block_id}
            )

        leader_rule = dict(gold.get("leader") or {})
        leader = dict(candidate.get("leader") or {})
        leader_drawn = leader.get("status") == "drawn"
        if leader_rule.get("required") and not leader_drawn:
            hard_failures.append(
                {"code": "required_leader_missing", "block_id": block_id}
            )
        if leader_drawn and not leader_rule.get("allowed", False):
            hard_failures.append(
                {"code": "leader_forbidden", "block_id": block_id}
            )
        if leader_drawn and (
            leader.get("color") != "dark_blue"
            or abs(float(leader.get("width_points", 0)) - 0.32) > 0.001
            or bool(leader.get("arrow"))
            or leader.get("route") != "orthogonal"
        ):
            hard_failures.append(
                {"code": "leader_style", "block_id": block_id}
            )

    duplicate_ids = [
        block_id
        for block_id in candidate_by_id
        if sum(
            1
            for item in candidate_blocks
            if str(item.get("block_id") or item.get("region_id")) == block_id
        )
        > 1
    ]
    if duplicate_ids:
        hard_failures.append(
            {"code": "duplicate_translation", "block_ids": duplicate_ids}
        )

    if pdf_diagnostics.get("replacement_characters") or pdf_diagnostics.get(
        "private_use_characters"
    ):
        hard_failures.append({"code": "garbled_text"})
    if pdf_diagnostics.get("clipped_or_outside_count"):
        hard_failures.append({"code": "clipped_or_outside"})
    if visual_qa.get("visual_overlap_count"):
        hard_failures.append({"code": "source_or_translation_overlap"})
    if visual_qa.get("leader_collision_count"):
        hard_failures.append({"code": "leader_collision"})
    if visual_qa.get("untranslated_candidate_count"):
        hard_failures.append({"code": "untranslated_candidate"})

    layout_points = max(
        0.0, min(20.0, float(subjective.get("layout_association", 0)))
    )
    readability_points = max(
        0.0, min(15.0, float(subjective.get("page_readability", 0)))
    )
    dimensions = {
        "semantic_terminology": round(semantic_points, 3),
        "coverage_deduplication": round(coverage_points, 3),
        "semantic_grouping": round(grouping_points, 3),
        "layout_association": layout_points,
        "page_readability": readability_points,
    }

    return {
        "schema": "engineering-drawing-score-v1",
        "hard_failures": hard_failures,
        "hard_failure_count": len(hard_failures),
        "dimensions": dimensions,
        "score": round(sum(dimensions.values()), 3),
        "passed": not hard_failures,
    }


def promotion_decision(current: dict, candidate: dict) -> dict:
    reasons = []
    if int(candidate["hard_failure_count"]) > int(current["hard_failure_count"]):
        reasons.append("new_hard_failures")
    score_gain = float(candidate["core_score"]) - float(current["core_score"])
    if score_gain < 1 and not (
        score_gain >= 0
        and float(candidate["manual_review_rate"])
        < float(current["manual_review_rate"])
    ):
        reasons.append("insufficient_core_gain")
    for category, old_score in current["category_scores"].items():
        if float(candidate["category_scores"].get(category, 0)) < float(old_score) - 3:
            reasons.append(f"category_regression:{category}")
    if float(candidate["challenge_pass_rate"]) < float(
        current["challenge_pass_rate"]
    ):
        reasons.append("challenge_regression")
    return {
        "promote": not reasons,
        "reasons": reasons,
        "core_score_gain": score_gain,
    }
