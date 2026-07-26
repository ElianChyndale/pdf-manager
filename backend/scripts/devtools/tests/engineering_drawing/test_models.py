import pytest

from services.engineering_drawing.models import (
    Action,
    BBox,
    LegacyStatus,
    Placement,
    Provenance,
    RegionRecord,
    SourceLanguage,
)


def test_region_record_round_trip_has_required_contract_fields():
    region = RegionRecord(
        source_text="Distribution Water Pump (3)",
        translated_text="配水泵（3 台）",
        source_language=SourceLanguage.ENGLISH,
        bbox=BBox(1, 2, 30, 40),
        rotation=90,
        provenance=Provenance.ROTATED_OCR,
        action=Action.TRANSLATE,
        legacy_status=LegacyStatus.MISSING,
        placement=Placement.SIDEBAR,
        qa_flags=["missing_chinese_companion", "missing_chinese_companion"],
    )

    payload = region.to_dict()

    assert set(
        (
            "source_text",
            "translated_text",
            "source_language",
            "bbox",
            "rotation",
            "provenance",
            "action",
            "legacy_status",
            "placement",
            "qa_flags",
        )
    ).issubset(payload)
    assert payload["qa_flags"] == ["missing_chinese_companion"]
    assert RegionRecord.from_dict(payload).to_dict() == payload


def test_region_record_rejects_invalid_rotation():
    with pytest.raises(ValueError, match="rotation"):
        RegionRecord(
            source_text="Pump",
            translated_text="泵",
            source_language=SourceLanguage.ENGLISH,
            bbox=BBox(0, 0, 10, 10),
            rotation=45,
            provenance=Provenance.NATIVE_TEXT,
            action=Action.TRANSLATE,
            legacy_status=LegacyStatus.ACCEPTED,
        )
