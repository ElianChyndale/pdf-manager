from copy import deepcopy

import pytest

from services.engineering_drawing.benchmark.scoring import (
    promotion_decision,
    score_sample,
)


def _leader_rule(*, allowed: bool = False, required: bool = False) -> dict:
    return {
        "allowed": allowed,
        "required": required,
        "color": "dark_blue",
        "width_points": 0.32,
        "route": "orthogonal",
        "arrow": False,
    }


def _gold_block(**changes) -> dict:
    block = {
        "block_id": "b1",
        "gold_translation": "屋面系统 0.48MM BMT",
        "literal_tokens": ["0.48MM BMT"],
        "merge_decision": "single",
        "rotation": 0,
        "allowed_regions": [[0, 0, 100, 100]],
        "forbidden_zones": [[110, 0, 120, 20]],
        "font_size_range": [3.2, 6.5],
        "leader": _leader_rule(),
        "manual_review_required": False,
    }
    block.update(changes)
    return block


def _candidate_block(**changes) -> dict:
    block = {
        "block_id": "b1",
        "translated_text": "屋面系统 0.48MM BMT",
        "merge_decision": "single",
        "rotation": 0,
        "target_bbox": [10, 10, 30, 30],
        "font_size": 5,
        "leader": {"status": "not_needed"},
    }
    block.update(changes)
    return block


def _score(
    *,
    gold_blocks: list[dict] | None = None,
    candidate_blocks: list[dict] | None = None,
    visual_qa: dict | None = None,
    pdf_diagnostics: dict | None = None,
    subjective: dict | None = None,
) -> dict:
    return score_sample(
        gold_blocks=[_gold_block()] if gold_blocks is None else gold_blocks,
        candidate_blocks=[_candidate_block()]
        if candidate_blocks is None
        else candidate_blocks,
        visual_qa={
            "visual_overlap_count": 0,
            "leader_collision_count": 0,
            "untranslated_candidate_count": 0,
        }
        if visual_qa is None
        else visual_qa,
        pdf_diagnostics={
            "replacement_characters": 0,
            "private_use_characters": 0,
            "clipped_or_outside_count": 0,
        }
        if pdf_diagnostics is None
        else pdf_diagnostics,
        subjective={"page_readability": 15, "layout_association": 20}
        if subjective is None
        else subjective,
    )


def test_missing_block_is_a_hard_failure_despite_other_scores():
    result = score_sample(
        gold_blocks=[
            {
                "block_id": "b1",
                "gold_translation": "屋面系统",
                "literal_tokens": [],
                "merge_decision": "single",
                "rotation": 0,
                "manual_review_required": False,
            }
        ],
        candidate_blocks=[],
        visual_qa={
            "visual_overlap_count": 0,
            "leader_collision_count": 0,
            "untranslated_candidate_count": 0,
        },
        pdf_diagnostics={
            "replacement_characters": 0,
            "private_use_characters": 0,
            "clipped_or_outside_count": 0,
        },
        subjective={"page_readability": 15, "layout_association": 20},
    )

    assert result["passed"] is False
    assert result["hard_failures"][0]["code"] == "missing_translation"


def test_promotion_requires_gain_or_equal_score_with_less_manual_review():
    current = {
        "core_score": 86.0,
        "hard_failure_count": 0,
        "manual_review_rate": 0.12,
        "category_scores": {"table": 85.0, "detail": 87.0},
        "challenge_pass_rate": 0.8,
    }
    candidate = {
        "core_score": 86.0,
        "hard_failure_count": 0,
        "manual_review_rate": 0.08,
        "category_scores": {"table": 84.0, "detail": 88.0},
        "challenge_pass_rate": 0.81,
    }

    assert promotion_decision(current, candidate)["promote"] is True
    candidate["category_scores"]["table"] = 81.9
    assert promotion_decision(current, candidate)["promote"] is False


def test_exact_candidate_receives_the_weighted_100_point_score():
    result = _score()

    assert result["passed"] is True
    assert result["hard_failure_count"] == 0
    assert result["dimensions"] == {
        "semantic_terminology": 30.0,
        "coverage_deduplication": 20.0,
        "semantic_grouping": 15.0,
        "layout_association": 20.0,
        "page_readability": 15.0,
    }
    assert result["score"] == 100.0


def test_candidate_can_use_placement_audit_region_id():
    candidate = _candidate_block()
    candidate["region_id"] = candidate.pop("block_id")

    assert _score(candidate_blocks=[candidate])["passed"] is True


@pytest.mark.parametrize(
    ("candidate_changes", "expected"),
    [
        ({"translated_text": "ROOF SYSTEM 0.48MM BMT"}, "missing_chinese"),
        ({"translated_text": "屋面系统 0.50MM BMT"}, "literal_changed"),
        ({"merge_decision": "merge_paragraph"}, "wrong_grouping"),
        ({"rotation": 90}, "wrong_rotation"),
        ({"target_bbox": None}, "missing_target_bbox"),
        ({"target_bbox": [90, 90, 105, 105]}, "outside_allowed_region"),
        ({"target_bbox": [112, 2, 118, 10]}, "outside_allowed_region"),
        ({"font_size": 3.1}, "unsafe_font_size"),
    ],
)
def test_candidate_block_hard_gates(candidate_changes, expected):
    result = _score(candidate_blocks=[_candidate_block(**candidate_changes)])

    assert expected in {item["code"] for item in result["hard_failures"]}
    assert result["passed"] is False


def test_forbidden_zone_overlap_is_checked_after_allowed_region_membership():
    gold = _gold_block(
        allowed_regions=[[0, 0, 100, 100]],
        forbidden_zones=[[20, 20, 40, 40]],
    )

    result = _score(
        gold_blocks=[gold],
        candidate_blocks=[_candidate_block(target_bbox=[25, 25, 35, 35])],
    )

    assert "forbidden_zone_overlap" in {
        item["code"] for item in result["hard_failures"]
    }


def test_duplicate_candidate_translation_is_a_hard_failure():
    first = _candidate_block()
    second = _candidate_block(target_bbox=[40, 10, 60, 30])

    result = _score(candidate_blocks=[first, second])

    assert {
        "code": "duplicate_translation",
        "block_ids": ["b1"],
    } in result["hard_failures"]


@pytest.mark.parametrize(
    ("gold_leader", "candidate_leader", "expected"),
    [
        (_leader_rule(allowed=True, required=True), {"status": "not_needed"}, "required_leader_missing"),
        (_leader_rule(), {"status": "drawn"}, "leader_forbidden"),
        (
            _leader_rule(allowed=True),
            {
                "status": "drawn",
                "color": "blue",
                "width_points": 0.5,
                "arrow": True,
                "route": "diagonal",
            },
            "leader_style",
        ),
    ],
)
def test_leader_hard_gates(gold_leader, candidate_leader, expected):
    result = _score(
        gold_blocks=[_gold_block(leader=gold_leader)],
        candidate_blocks=[_candidate_block(leader=candidate_leader)],
    )

    assert expected in {item["code"] for item in result["hard_failures"]}


@pytest.mark.parametrize(
    ("visual", "diagnostics", "expected"),
    [
        (
            {
                "visual_overlap_count": 1,
                "leader_collision_count": 0,
                "untranslated_candidate_count": 0,
            },
            {},
            "source_or_translation_overlap",
        ),
        (
            {
                "visual_overlap_count": 0,
                "leader_collision_count": 1,
                "untranslated_candidate_count": 0,
            },
            {},
            "leader_collision",
        ),
        (
            {
                "visual_overlap_count": 0,
                "leader_collision_count": 0,
                "untranslated_candidate_count": 1,
            },
            {},
            "untranslated_candidate",
        ),
        (
            {
                "visual_overlap_count": 0,
                "leader_collision_count": 0,
                "untranslated_candidate_count": 0,
            },
            {"replacement_characters": 1},
            "garbled_text",
        ),
        (
            {
                "visual_overlap_count": 0,
                "leader_collision_count": 0,
                "untranslated_candidate_count": 0,
            },
            {"private_use_characters": 1},
            "garbled_text",
        ),
        (
            {
                "visual_overlap_count": 0,
                "leader_collision_count": 0,
                "untranslated_candidate_count": 0,
            },
            {"clipped_or_outside_count": 1},
            "clipped_or_outside",
        ),
    ],
)
def test_visual_and_pdf_hard_gates(visual, diagnostics, expected):
    result = _score(
        gold_blocks=[],
        candidate_blocks=[],
        visual_qa=visual,
        pdf_diagnostics=diagnostics,
    )

    assert expected in {item["code"] for item in result["hard_failures"]}


def test_subjective_scores_are_clamped_to_their_dimension_weights():
    result = _score(
        subjective={"layout_association": 25, "page_readability": -2}
    )

    assert result["dimensions"]["layout_association"] == 20.0
    assert result["dimensions"]["page_readability"] == 0.0
    assert result["score"] == 85.0


def test_inexact_chinese_translation_receives_partial_semantic_credit():
    result = _score(
        candidate_blocks=[
            _candidate_block(translated_text="建筑屋面系统 0.48MM BMT")
        ]
    )

    assert result["dimensions"]["semantic_terminology"] == 15.0
    assert result["score"] == 85.0


def test_manual_review_block_can_be_missing_without_a_hard_failure():
    result = _score(
        gold_blocks=[_gold_block(manual_review_required=True)],
        candidate_blocks=[],
    )

    assert result["passed"] is True
    assert result["score"] == 35.0


@pytest.mark.parametrize(
    ("candidate_changes", "expected_reason"),
    [
        ({"hard_failure_count": 1, "core_score": 100.0}, "new_hard_failures"),
        ({"core_score": 86.9}, "insufficient_core_gain"),
        ({"challenge_pass_rate": 0.79}, "challenge_regression"),
    ],
)
def test_each_promotion_guard_rejects_independently(
    candidate_changes, expected_reason
):
    current = {
        "core_score": 86.0,
        "hard_failure_count": 0,
        "manual_review_rate": 0.12,
        "category_scores": {"table": 85.0, "detail": 87.0},
        "challenge_pass_rate": 0.8,
    }
    candidate = {
        "core_score": 87.0,
        "hard_failure_count": 0,
        "manual_review_rate": 0.12,
        "category_scores": {"table": 85.0, "detail": 87.0},
        "challenge_pass_rate": 0.8,
    }
    candidate.update(candidate_changes)

    decision = promotion_decision(current, candidate)

    assert decision["promote"] is False
    assert expected_reason in decision["reasons"]


def test_promotion_accepts_exactly_one_point_gain_and_three_point_category_drop():
    current = {
        "core_score": 86.0,
        "hard_failure_count": 0,
        "manual_review_rate": 0.12,
        "category_scores": {"table": 85.0, "detail": 87.0},
        "challenge_pass_rate": 0.8,
    }
    candidate = deepcopy(current)
    candidate["core_score"] = 87.0
    candidate["category_scores"]["table"] = 82.0

    decision = promotion_decision(current, candidate)

    assert decision == {"promote": True, "reasons": [], "core_score_gain": 1.0}
