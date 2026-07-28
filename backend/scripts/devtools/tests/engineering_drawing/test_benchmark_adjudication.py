import pytest

from services.engineering_drawing.benchmark.adjudication import (
    apply_adjudication,
    lock_gold,
)
from services.engineering_drawing.benchmark.schema import GoldSample


def _leader():
    return {
        "allowed": False,
        "required": False,
        "color": "dark_blue",
        "width_points": 0.32,
        "route": "orthogonal",
        "arrow": False,
    }


def _prelabel():
    return {
        "schema": "engineering-drawing-prelabel-v1",
        "prompt_version": "2026-07-benchmark-block-v1",
        "sample_id": "core-03",
        "status": "prelabeled",
        "model": "test-model",
        "page": {"width": 300, "height": 200, "rotation": 0},
        "blocks": [
            {
                "block_id": "core-03-b001",
                "member_ids": ["ocr-1", "ocr-2"],
                "source_text": "ROOF SYSTEM 0.48MM BMT",
                "source_language": "en",
                "source_bbox": [10, 10, 150, 30],
                "rotation": 0,
                "reading_order": 1,
                "merge_decision": "merge_paragraph",
                "gold_translation": "屋面系统，0.48MM BMT",
                "literal_tokens": ["0.48MM BMT"],
                "allowed_regions": [[10, 40, 170, 65]],
                "forbidden_zones": [[10, 10, 150, 30]],
                "font_size_range": [3.2, 6.5],
                "leader": _leader(),
                "confidence": 0.7,
                "risk_flags": ["layout_collision"],
            }
        ],
    }


def _decision(**overrides):
    result = {
        "block_id": "core-03-b001",
        "field": "gold_translation",
        "value": "屋面系统：基板厚度 0.48MM BMT",
        "reason": "按完整技术说明翻译",
    }
    result.update(overrides)
    return result


def _adjudicated():
    return apply_adjudication(
        _prelabel(),
        [_decision()],
        actor="reviewer",
        decided_at="2026-07-28T10:00:00+08:00",
    )


def test_adjudication_changes_value_appends_audit_and_lock_preserves_history():
    sample = apply_adjudication(
        _prelabel(),
        [
            {
                "block_id": "core-03-b001",
                "field": "gold_translation",
                "value": "屋面系统：基板厚度 0.48MM BMT",
                "reason": "按完整技术说明翻译",
            }
        ],
        actor="user",
        decided_at="2026-07-28T10:00:00+08:00",
    )

    assert sample.gold_version == 1
    assert sample.blocks[0].gold_translation == "屋面系统：基板厚度 0.48MM BMT"
    assert sample.audit[0]["action"] == "adjudicate"
    assert sample.audit[0]["old_value"] == "屋面系统，0.48MM BMT"
    assert sample.audit[0]["new_value"] == "屋面系统：基板厚度 0.48MM BMT"
    assert sample.audit[0]["reason"] == "按完整技术说明翻译"
    assert sample.audit[0]["actor"] == "user"
    assert sample.audit[0]["decided_at"] == "2026-07-28T10:00:00+08:00"

    locked = lock_gold(sample, actor="user", decided_at="2026-07-28T10:05:00+08:00")

    assert locked.status == "locked"
    assert locked.gold_version == 2
    assert locked.audit[:-1] == sample.audit
    assert locked.audit[-1]["action"] == "lock"
    assert locked.audit[-1]["actor"] == "user"
    assert locked.audit[-1]["decided_at"] == "2026-07-28T10:05:00+08:00"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda prelabel: prelabel.update(schema="other-prelabel-v1"),
        lambda prelabel: prelabel.update(status="candidate"),
        lambda prelabel: prelabel.pop("page"),
    ],
)
def test_adjudication_requires_a_strict_prelabel_record(mutate):
    prelabel = _prelabel()
    mutate(prelabel)

    with pytest.raises(ValueError, match="prelabel"):
        apply_adjudication(
            prelabel,
            [],
            actor="user",
            decided_at="2026-07-28T10:00:00+08:00",
        )


@pytest.mark.parametrize("field", ["source_text", "legacy_fallback"])
def test_adjudication_rejects_fields_outside_the_editable_allowlist(field):
    with pytest.raises(ValueError, match="unknown block or field"):
        apply_adjudication(
            _prelabel(),
            [
                {
                    "block_id": "core-03-b001",
                    "field": field,
                    "value": "replacement",
                    "reason": "protect source-derived data",
                }
            ],
            actor="user",
            decided_at="2026-07-28T10:00:00+08:00",
        )


def test_adjudication_requires_a_reason_for_every_decision():
    with pytest.raises(ValueError, match="requires a reason"):
        apply_adjudication(
            _prelabel(),
            [
                {
                    "block_id": "core-03-b001",
                    "field": "gold_translation",
                    "value": "屋面系统：基板厚度 0.48MM BMT",
                    "reason": " ",
                }
            ],
            actor="user",
            decided_at="2026-07-28T10:00:00+08:00",
        )


def test_adjudication_preserves_prelabel_and_makes_manual_review_an_audited_edit():
    prelabel = _prelabel()
    sample = apply_adjudication(
        prelabel,
        [
            {
                "block_id": "core-03-b001",
                "field": "manual_review_required",
                "value": True,
                "reason": "retain reviewer sign-off for collision risk",
            }
        ],
        actor="reviewer",
        decided_at="2026-07-28T10:00:00+08:00",
    )

    assert prelabel["blocks"][0]["gold_translation"] == "屋面系统，0.48MM BMT"
    assert sample.blocks[0].manual_review_required is True
    assert sample.blocks[0].legacy_fallback is False
    assert sample.audit[0]["old_value"] is False
    assert sample.audit[0]["new_value"] is True
    with pytest.raises(TypeError):
        sample.audit[0]["reason"] = "changed"


def test_adjudication_revalidates_full_leader_contract_after_an_edit():
    with pytest.raises(ValueError, match="decision value leader"):
        apply_adjudication(
            _prelabel(),
            [
                {
                    "block_id": "core-03-b001",
                    "field": "leader",
                    "value": {"allowed": True, "required": False},
                    "reason": "add a leader",
                }
            ],
            actor="user",
            decided_at="2026-07-28T10:00:00+08:00",
        )


@pytest.mark.parametrize(
    "decision",
    [
        _decision(value=[]),
        _decision(value="Roof system 0.48MM BMT"),
        _decision(value="屋面系统"),
        _decision(field="merge_decision", value=["single"]),
        _decision(field="merge_decision", value="unsupported"),
        _decision(field="allowed_regions", value=[]),
        _decision(field="allowed_regions", value=[[10, 40, 10, 65]]),
        _decision(field="forbidden_zones", value=[[10, 10, float("inf"), 30]]),
        _decision(field="font_size_range", value=[3.2, True]),
        _decision(field="font_size_range", value=[6.5, 3.2]),
        _decision(field="leader", value={**_leader(), "extra": True}),
        _decision(field="leader", value={**_leader(), "arrow": True}),
        _decision(field="manual_review_required", value=1),
        _decision(field="manual_review_required", value=[True]),
    ],
)
def test_adjudication_rejects_invalid_edit_values_before_gold_conversion(decision):
    with pytest.raises(ValueError, match="decision value"):
        apply_adjudication(
            _prelabel(),
            [decision],
            actor="reviewer",
            decided_at="2026-07-28T10:00:00+08:00",
        )


@pytest.mark.parametrize("actor", [" ", 7, []])
def test_adjudication_rejects_blank_or_nonstring_actor(actor):
    with pytest.raises(ValueError, match="actor"):
        apply_adjudication(
            _prelabel(), [_decision()], actor=actor, decided_at="2026-07-28T10:00:00+08:00"
        )


@pytest.mark.parametrize("decided_at", ["2026-07-28T10:00:00", "not-a-time", 7])
def test_adjudication_requires_a_timezone_aware_iso_timestamp(decided_at):
    with pytest.raises(ValueError, match="decided_at"):
        apply_adjudication(_prelabel(), [_decision()], actor="reviewer", decided_at=decided_at)


def test_adjudication_normalizes_a_valid_timestamp_for_audit_stability():
    sample = apply_adjudication(
        _prelabel(), [_decision()], actor=" reviewer ", decided_at="2026-07-28T02:00:00Z"
    )

    assert sample.audit[0]["actor"] == "reviewer"
    assert sample.audit[0]["decided_at"] == "2026-07-28T02:00:00+00:00"


@pytest.mark.parametrize(
    "decisions",
    [
        [],
        (),
        "not-a-list",
        [_decision(), _decision()],
        [object()],
        [{"block_id": "core-03-b001", "field": "gold_translation", "value": "屋面 0.48MM BMT"}],
        [{**_decision(), "unexpected": True}],
        [_decision(block_id=" ")],
        [_decision(block_id=7)],
        [_decision(field=7)],
        [_decision(reason=[])],
        [_decision(reason=7)],
        [
            _decision(
                field="allowed_regions",
                value=((10, 40, 170, 65),),
                reason="same placement",
            )
        ],
    ],
)
def test_adjudication_rejects_malformed_duplicate_or_semantic_noop_decisions(decisions):
    with pytest.raises(ValueError, match="decision"):
        apply_adjudication(
            _prelabel(), decisions, actor="reviewer", decided_at="2026-07-28T10:00:00+08:00"
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda prelabel: prelabel.pop("sample_id"),
        lambda prelabel: prelabel.update(unexpected=True),
        lambda prelabel: prelabel["page"].pop("rotation"),
        lambda prelabel: prelabel["page"].update(width=True),
        lambda prelabel: prelabel.update(blocks=[]),
        lambda prelabel: prelabel["blocks"][0].pop("source_text"),
        lambda prelabel: prelabel["blocks"][0].update(unexpected=True),
        lambda prelabel: prelabel["blocks"][0].update(member_ids="ocr-1"),
    ],
)
def test_adjudication_rejects_malformed_prelabel_boundary_inputs(mutate):
    prelabel = _prelabel()
    mutate(prelabel)

    with pytest.raises(ValueError, match="prelabel"):
        apply_adjudication(
            prelabel, [_decision()], actor="reviewer", decided_at="2026-07-28T10:00:00+08:00"
        )


def test_adjudication_does_not_retain_mutable_caller_values():
    prelabel = _prelabel()
    leader = _leader()
    leader["allowed"] = True
    decision = _decision(field="leader", value=leader, reason="preserve approved style")

    sample = apply_adjudication(
        prelabel, [decision], actor="reviewer", decided_at="2026-07-28T10:00:00+08:00"
    )
    prelabel["blocks"][0]["gold_translation"] = "changed outside"
    leader["color"] = "changed outside"
    decision["reason"] = "changed outside"

    assert sample.blocks[0].gold_translation == "屋面系统，0.48MM BMT"
    assert sample.blocks[0].leader["color"] == "dark_blue"
    assert sample.audit[0]["reason"] == "preserve approved style"


def test_adjudication_accepts_prelabel_literals_normalized_by_the_task3_contract():
    prelabel = _prelabel()
    prelabel["blocks"][0]["gold_translation"] = "屋面系统，0.48 MM BMT"

    sample = apply_adjudication(
        prelabel,
        [_decision(field="manual_review_required", value=True, reason="review collision risk")],
        actor="reviewer",
        decided_at="2026-07-28T10:00:00+08:00",
    )

    assert sample.blocks[0].gold_translation == "屋面系统，0.48 MM BMT"


@pytest.mark.parametrize("status", ["candidate", "prelabeled"])
def test_lock_rejects_samples_that_have_not_been_adjudicated(status):
    payload = _adjudicated().to_dict()
    payload["status"] = status

    with pytest.raises(ValueError, match="adjudicated"):
        lock_gold(
            GoldSample.from_dict(payload), actor="reviewer", decided_at="2026-07-28T10:05:00+08:00"
        )


def test_lock_rejects_relocking_and_earlier_or_malformed_audit_timestamps():
    sample = _adjudicated()
    locked = lock_gold(sample, actor="reviewer", decided_at="2026-07-28T10:05:00+08:00")
    with pytest.raises(ValueError, match="adjudicated"):
        lock_gold(locked, actor="reviewer", decided_at="2026-07-28T10:06:00+08:00")
    with pytest.raises(ValueError, match="before"):
        lock_gold(sample, actor="reviewer", decided_at="2026-07-28T09:59:00+08:00")

    payload = sample.to_dict()
    payload["audit"][0]["decided_at"] = "bad-time"
    with pytest.raises(ValueError, match="existing audit"):
        lock_gold(
            GoldSample.from_dict(payload), actor="reviewer", decided_at="2026-07-28T10:05:00+08:00"
        )


@pytest.mark.parametrize("actor", [" ", 4])
def test_lock_uses_the_same_identity_validation(actor):
    with pytest.raises(ValueError, match="actor"):
        lock_gold(_adjudicated(), actor=actor, decided_at="2026-07-28T10:05:00+08:00")


@pytest.mark.parametrize("decided_at", ["2026-07-28T10:05:00", "bad-time"])
def test_lock_uses_the_same_timezone_aware_timestamp_validation(decided_at):
    with pytest.raises(ValueError, match="decided_at"):
        lock_gold(_adjudicated(), actor="reviewer", decided_at=decided_at)
