from services.engineering_drawing.harness import GeographicMatch
from services.engineering_drawing.harness import GeographicResolver
from services.engineering_drawing.harness import quality_exceeds_legacy_baseline
from services.engineering_drawing.harness import run_full_coverage_harness


def test_harness_requires_every_non_chinese_non_numeric_region_to_have_chinese_and_placement() -> None:
    result = run_full_coverage_harness(
        [
            {
                "region_id": "pump",
                "source_text": "Distribution Water Pump",
                "translated_text": "配水泵",
                "action": "translate",
            },
            {
                "region_id": "number",
                "source_text": "275",
                "translated_text": "",
                "action": "keep_literal",
            },
        ],
        placement_audit=[
            {"region_id": "pump", "status": "inline_near", "distance": 3.2},
        ],
    )

    assert result.report["required_regions"] == 1
    assert result.report["passed"] is True


def test_harness_blocks_release_when_a_readable_region_was_filtered_or_has_no_safe_placement() -> None:
    result = run_full_coverage_harness(
        [
            {
                "region_id": "consultant-address",
                "source_text": "88-01, Jalan Setia Tropika 1/7, Johor Bahru",
                "translated_text": "88-01，实达热带路 1/7，新山",
                "action": "translate",
            }
        ],
        placement_audit=[
            {"region_id": "consultant-address", "status": "rejected_no_near_space"},
        ],
    )

    assert result.report["passed"] is False
    assert result.blocking[0]["reason"] == "no_safe_bilingual_placement"


def test_geographic_resolver_corrects_ocr_road_name_only_with_strong_external_evidence() -> None:
    resolver = GeographicResolver(
        lookup=lambda query: [
            GeographicMatch(
                name="Jalan Felda Cahaya Baru",
                display_name="Jalan Felda Cahaya Baru, Johor Bahru, Johor, Malaysia",
                category="highway",
                source="nominatim",
            )
        ]
    )
    result = run_full_coverage_harness(
        [
            {
                "region_id": "road",
                "source_text": "Jalan Felda Cahaya Banu",
                "translated_text": "费尔达新光路（Jalan Felda Cahaya Baru）",
                "action": "translate",
                "qa_flags": ["ocr_suspect"],
            }
        ],
        placement_audit=[{"region_id": "road", "status": "inline_near", "distance": 3.2}],
        geographic_resolver=resolver,
        context_hints=["Johor Bahru", "Malaysia"],
    )

    region = result.regions[0]
    assert region["source_text"] == "Jalan Felda Cahaya Baru"
    assert region["raw_source_text"] == "Jalan Felda Cahaya Banu"
    assert region["geo_status"] == "corrected"
    assert result.report["geo_corrected_regions"] == 1


def test_legacy_baseline_gate_requires_a_complete_candidate_and_zero_new_defects() -> None:
    candidate = run_full_coverage_harness(
        [{"region_id": "a", "source_text": "SITE PLAN", "translated_text": "总平面图", "action": "translate"}],
        placement_audit=[{"region_id": "a", "status": "inline_near"}],
    )

    gate = quality_exceeds_legacy_baseline(candidate, {"missing": 4, "partial": 2, "bad_translation": 1, "layout_defect": 3})

    assert gate["passed"] is True
    assert gate["legacy_defects"] == 10
