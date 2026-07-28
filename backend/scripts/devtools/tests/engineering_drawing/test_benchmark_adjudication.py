import pytest

from services.engineering_drawing.benchmark.adjudication import (
    apply_adjudication,
    lock_gold,
)


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
        "sample_id": "core-03",
        "status": "prelabeled",
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
    with pytest.raises(ValueError, match="leader color"):
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
