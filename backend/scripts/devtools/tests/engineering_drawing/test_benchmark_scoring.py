from copy import deepcopy
import math

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
    result = _score(candidate_blocks=[])

    assert result["passed"] is False
    assert "missing_translation:b1" in result["hard_failure_ids"]


def test_promotion_requires_gain_or_equal_score_with_less_manual_review():
    current = {
        "core_score": 86.0,
        "hard_failure_count": 0,
        "manual_review_rate": 0.12,
        "category_scores": {"table": 85.0, "detail": 87.0},
        "challenge_pass_rate": 0.8,
        "hard_failure_ids": [],
    }
    candidate = {
        "core_score": 86.0,
        "hard_failure_count": 0,
        "manual_review_rate": 0.08,
        "category_scores": {"table": 84.0, "detail": 88.0},
        "challenge_pass_rate": 0.81,
        "hard_failure_ids": [],
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
        "block_id": "b1",
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


@pytest.mark.parametrize("value", [True, "15", math.nan, math.inf, -math.inf])
def test_subjective_scores_reject_nonfinite_or_non_numeric_values(value):
    result = _score(
        subjective={"layout_association": value, "page_readability": 15}
    )

    assert "invalid_subjective" in {
        item["code"] for item in result["hard_failures"]
    }
    assert result["dimensions"]["layout_association"] == 0.0


def test_human_ruled_inexact_nonempty_translation_receives_15_points():
    result = _score(
        candidate_blocks=[
            _candidate_block(translated_text="建筑屋面系统 0.48MM BMT")
        ]
    )

    assert result["dimensions"]["semantic_terminology"] == 15.0
    assert result["score"] == 85.0


def test_manual_review_block_still_fails_when_fallback_evidence_is_missing():
    result = _score(
        gold_blocks=[_gold_block(manual_review_required=True)],
        candidate_blocks=[],
    )

    assert result["passed"] is False
    assert "missing_translation:b1" in result["hard_failure_ids"]


@pytest.mark.parametrize(
    ("candidate_changes", "expected_reason"),
    [
        (
            {
                "hard_failure_count": 1,
                "hard_failure_ids": ["garbled_text"],
                "core_score": 100.0,
            },
            "new_hard_failures",
        ),
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
        "hard_failure_ids": [],
    }
    candidate = {
        "core_score": 87.0,
        "hard_failure_count": 0,
        "manual_review_rate": 0.12,
        "category_scores": {"table": 85.0, "detail": 87.0},
        "challenge_pass_rate": 0.8,
        "hard_failure_ids": [],
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
        "hard_failure_ids": [],
    }
    candidate = deepcopy(current)
    candidate["core_score"] = 87.0
    candidate["category_scores"]["table"] = 82.0

    decision = promotion_decision(current, candidate)

    assert decision == {
        "promote": True,
        "reasons": [],
        "core_score_gain": 1.0,
        "new_hard_failure_ids": [],
    }


@pytest.mark.parametrize("gain", [0.1, 0.9])
def test_subpoint_gain_does_not_promote_even_with_lower_manual_review(gain):
    current = _promotion_snapshot()
    candidate = deepcopy(current)
    candidate["core_score"] += gain
    candidate["manual_review_rate"] = 0.01

    decision = promotion_decision(current, candidate)

    assert decision["promote"] is False
    assert "insufficient_core_gain" in decision["reasons"]


def test_equal_score_uses_tight_zero_tolerance_with_lower_manual_review():
    current = _promotion_snapshot()
    candidate = deepcopy(current)
    candidate["core_score"] += 5e-10
    candidate["manual_review_rate"] = 0.01

    assert promotion_decision(current, candidate)["promote"] is True


def test_swapped_hard_failure_at_the_same_count_blocks_promotion():
    current = _promotion_snapshot(
        hard_failure_count=1,
        hard_failure_ids=["leader_collision"],
    )
    candidate = _promotion_snapshot(
        core_score=87.0,
        hard_failure_count=1,
        hard_failure_ids=["garbled_text"],
    )

    decision = promotion_decision(current, candidate)

    assert decision["promote"] is False
    assert decision["new_hard_failure_ids"] == ["garbled_text"]
    assert "new_hard_failures" in decision["reasons"]


def test_promotion_normalizes_structured_hard_failure_identity():
    current = _promotion_snapshot(
        hard_failure_count=1,
        hard_failures=[{"code": "wrong_rotation", "block_id": "b1"}],
    )
    current.pop("hard_failure_ids")
    candidate = deepcopy(current)
    candidate["core_score"] = 87.0

    decision = promotion_decision(current, candidate)

    assert decision["promote"] is True
    assert decision["new_hard_failure_ids"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rotation", True),
        ("rotation", "0"),
        ("rotation", math.nan),
        ("rotation", math.inf),
        ("font_size", False),
        ("font_size", "5"),
        ("font_size", math.nan),
        ("font_size", -math.inf),
        ("target_bbox", [10, 10, math.inf, 30]),
        ("target_bbox", [10, 10, "30", 30]),
        ("target_bbox", [10, 10, True, 30]),
    ],
)
def test_malformed_candidate_numeric_fields_become_hard_failures(field, value):
    result = _score(candidate_blocks=[_candidate_block(**{field: value})])

    assert result["passed"] is False
    assert "invalid_candidate:b1" in result["hard_failure_ids"]


@pytest.mark.parametrize("width", [True, "0.32", math.nan, math.inf])
def test_malformed_candidate_leader_width_becomes_a_hard_failure(width):
    result = _score(
        gold_blocks=[_gold_block(leader=_leader_rule(allowed=True))],
        candidate_blocks=[
            _candidate_block(
                leader={
                    "status": "drawn",
                    "color": "dark_blue",
                    "width_points": width,
                    "route": "orthogonal",
                    "arrow": False,
                }
            )
        ],
    )

    assert "invalid_candidate:b1" in result["hard_failure_ids"]


@pytest.mark.parametrize(
    "candidate_leader",
    [
        {
            "status": "drawn",
            "color": "dark_blue",
            "width_points": 0.3205,
            "route": "orthogonal",
            "arrow": False,
        },
        {
            "status": "drawn",
            "color": "dark_blue",
            "width_points": 0.32,
            "route": "orthogonal",
        },
    ],
)
def test_drawn_leader_requires_the_exact_complete_gold_style(candidate_leader):
    result = _score(
        gold_blocks=[_gold_block(leader=_leader_rule(allowed=True))],
        candidate_blocks=[_candidate_block(leader=candidate_leader)],
    )

    assert "leader_style:b1" in result["hard_failure_ids"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rotation", True),
        ("rotation", "0"),
        ("rotation", math.nan),
        ("allowed_regions", [[0, 0, math.nan, 100]]),
        ("allowed_regions", [[0, 0, "100", 100]]),
        ("forbidden_zones", [[110, 0, math.inf, 20]]),
        ("font_size_range", [3.2, math.inf]),
        ("font_size_range", [True, 6.5]),
    ],
)
def test_malformed_locked_gold_numeric_fields_are_invalid_gold(field, value):
    result = _score(gold_blocks=[_gold_block(**{field: value})])

    assert result["passed"] is False
    assert "invalid_gold:b1" in result["hard_failure_ids"]


def test_invalid_gold_leader_cannot_weaken_candidate_style_gate():
    gold = _gold_block()
    gold["leader"] = {**_leader_rule(), "width_points": 0.5}

    result = _score(gold_blocks=[gold])

    assert "invalid_gold:b1" in result["hard_failure_ids"]


def test_duplicate_candidates_are_order_independent_and_not_scored():
    first = _candidate_block(translated_text="屋面系统 0.48MM BMT")
    second = _candidate_block(
        translated_text="错误译文 0.48MM BMT",
        target_bbox=[40, 10, 60, 30],
    )

    forward = _score(candidate_blocks=[first, second])
    reverse = _score(candidate_blocks=[second, first])

    assert forward == reverse
    assert forward["dimensions"]["semantic_terminology"] == 0.0
    assert forward["dimensions"]["coverage_deduplication"] == 0.0
    assert forward["hard_failure_ids"].count("duplicate_translation:b1") == 1


def test_duplicate_gold_ids_are_rejected_and_not_scored():
    result = _score(
        gold_blocks=[
            _gold_block(),
            _gold_block(gold_translation="另一译文 0.48MM BMT"),
        ]
    )

    assert result["dimensions"]["semantic_terminology"] == 0.0
    assert "duplicate_gold_block_id:b1" in result["hard_failure_ids"]


@pytest.mark.parametrize("candidate_literal", ["50", "5.0", "5/10"])
def test_digit_literal_does_not_match_inside_a_larger_engineering_token(
    candidate_literal,
):
    result = _score(
        gold_blocks=[_gold_block(gold_translation="屋面系统 5", literal_tokens=["5"])],
        candidate_blocks=[
            _candidate_block(translated_text=f"屋面系统 {candidate_literal}")
        ],
    )

    assert "literal_changed:b1" in result["hard_failure_ids"]


def test_literal_matching_preserves_established_formatting_normalization():
    result = _score(
        candidate_blocks=[
            _candidate_block(translated_text="建筑屋面系统 0.48 mm bmt")
        ]
    )

    assert "literal_changed:b1" not in result["hard_failure_ids"]


@pytest.mark.parametrize("literal_tokens", [[""], [7], "5"])
def test_empty_nonstring_or_nonlist_gold_literals_are_invalid(literal_tokens):
    result = _score(gold_blocks=[_gold_block(literal_tokens=literal_tokens)])

    assert "invalid_gold:b1" in result["hard_failure_ids"]


def test_empty_gold_sample_is_a_hard_failure():
    result = _score(gold_blocks=[], candidate_blocks=[])

    assert result["passed"] is False
    assert result["hard_failure_ids"] == ["empty_gold_sample"]


def test_manual_review_missing_translation_requires_authorized_fallback_evidence():
    gold = [_gold_block(manual_review_required=True)]
    authorized = {
        "block_id": "b1",
        "translated_text": "",
        "manual_review_required": True,
        "status": "inline_legacy_fallback",
        "manual_review_reason": "authoritative legacy caption retained",
    }

    result = _score(gold_blocks=gold, candidate_blocks=[authorized])

    assert result["passed"] is True
    assert result["score"] == 35.0


@pytest.mark.parametrize(
    "candidate_changes",
    [
        {"manual_review_required": False},
        {"status": "inline_near"},
        {"manual_review_reason": ""},
        {"block_id": "other"},
    ],
)
def test_incomplete_or_mismatched_manual_fallback_evidence_fails(candidate_changes):
    candidate = {
        "block_id": "b1",
        "translated_text": "",
        "manual_review_required": True,
        "status": "inline_legacy_fallback",
        "manual_review_reason": "authorized legacy fallback",
    }
    candidate.update(candidate_changes)

    result = _score(
        gold_blocks=[_gold_block(manual_review_required=True)],
        candidate_blocks=[candidate],
    )

    assert result["passed"] is False
    assert "missing_translation:b1" in result["hard_failure_ids"]


def test_all_manual_sample_cannot_pass_without_fallback_evidence():
    result = _score(
        gold_blocks=[
            _gold_block(block_id="b1", manual_review_required=True),
            _gold_block(block_id="b2", manual_review_required=True),
        ],
        candidate_blocks=[],
    )

    assert result["passed"] is False
    assert result["hard_failure_ids"] == [
        "missing_translation:b1",
        "missing_translation:b2",
    ]


@pytest.mark.parametrize(
    ("mutate", "expected_reason"),
    [
        (lambda value: value.pop("core_score"), "invalid_candidate:missing_key:core_score"),
        (lambda value: value.update(core_score=True), "invalid_candidate:core_score"),
        (lambda value: value.update(core_score="87"), "invalid_candidate:core_score"),
        (lambda value: value.update(core_score=math.nan), "invalid_candidate:core_score"),
        (lambda value: value.update(core_score=math.inf), "invalid_candidate:core_score"),
        (
            lambda value: value.update(manual_review_rate=-0.1),
            "invalid_candidate:manual_review_rate",
        ),
        (
            lambda value: value.update(challenge_pass_rate=1.1),
            "invalid_candidate:challenge_pass_rate",
        ),
        (
            lambda value: value.update(hard_failure_count=True),
            "invalid_candidate:hard_failure_count",
        ),
        (
            lambda value: value.update(
                hard_failure_count=1, hard_failure_ids=[]
            ),
            "invalid_candidate:hard_failure_count_mismatch",
        ),
        (
            lambda value: value.pop("hard_failure_ids"),
            "invalid_candidate:missing_hard_failure_identity",
        ),
        (
            lambda value: value["category_scores"].pop("detail"),
            "category_universe_mismatch",
        ),
        (
            lambda value: value["category_scores"].update(extra=90.0),
            "category_universe_mismatch",
        ),
        (
            lambda value: value["category_scores"].update(table=math.inf),
            "invalid_candidate:category_score:table",
        ),
        (
            lambda value: value.update(
                category_scores={" table ": 85.0, "detail": 87.0}
            ),
            "invalid_candidate:category_scores",
        ),
    ],
)
def test_malformed_promotion_candidate_returns_structured_reasons(
    mutate, expected_reason
):
    current = _promotion_snapshot()
    candidate = _promotion_snapshot(core_score=87.0)
    mutate(candidate)

    decision = promotion_decision(current, candidate)

    assert decision["promote"] is False
    assert expected_reason in decision["reasons"]
    assert len(decision["reasons"]) == len(set(decision["reasons"]))


def test_missing_current_promotion_key_returns_reason_instead_of_raising():
    current = _promotion_snapshot()
    current.pop("category_scores")

    decision = promotion_decision(current, _promotion_snapshot(core_score=87.0))

    assert decision["promote"] is False
    assert "invalid_current:missing_key:category_scores" in decision["reasons"]


def _promotion_snapshot(**changes) -> dict:
    value = {
        "core_score": 86.0,
        "hard_failure_count": 0,
        "hard_failure_ids": [],
        "manual_review_rate": 0.12,
        "category_scores": {"table": 85.0, "detail": 87.0},
        "challenge_pass_rate": 0.8,
    }
    value.update(changes)
    return value
