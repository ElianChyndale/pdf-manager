from services.engineering_drawing.harness import GeographicMatch
from services.engineering_drawing.harness import GeographicResolver
from services.engineering_drawing.harness import audit_existing_legacy_companions
from services.engineering_drawing.harness import quality_exceeds_legacy_baseline
from services.engineering_drawing.harness import run_full_coverage_harness
from services.engineering_drawing.harness import select_legacy_additions


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


def test_harness_ignores_only_ai_confirmed_duplicate_ocr_observations() -> None:
    result = run_full_coverage_harness(
        [
            {
                "region_id": "real-label",
                "source_text": "6M SETBACK LINE",
                "translated_text": "6米退界线",
                "action": "translate",
            },
            {
                "region_id": "bad-tile-read",
                "source_text": "Q4 EBITDA",
                "translated_text": "第四季度息税折旧摊销前利润",
                "action": "translate",
                "observation_status": "ai_confirmed_duplicate_observation",
            },
        ],
        placement_audit=[{"region_id": "real-label", "status": "inline_near"}],
    )

    assert result.report["required_regions"] == 1
    assert result.report["passed"] is True


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


def test_legacy_companion_audit_requires_matching_chinese_near_the_source(tmp_path) -> None:
    import fitz

    legacy = tmp_path / "legacy.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=160)
    page.insert_text((20, 40), "BALLAST STONE", fontsize=10)
    page.insert_text((20, 54), "道砟石", fontsize=10, fontname="china-s")
    page.insert_text((220, 140), "道砟石", fontsize=10, fontname="china-s")
    document.save(legacy)
    document.close()

    placements = audit_existing_legacy_companions(
        legacy_pdf_path=legacy,
        regions=[
            {
                "region_id": "ballast",
                "page_number": 1,
                "source_text": "BALLAST STONE",
                "translated_text": "道砟石",
                "bbox": [20, 28, 100, 42],
                "provenance": "paddle_ocr",
            }
        ],
    )

    assert len(placements) == 1
    assert placements[0]["placement_origin"] == "legacy_verified"
    assert placements[0]["distance"] < 20


def test_legacy_additive_selection_freezes_existing_and_requires_source_approval(tmp_path) -> None:
    import fitz

    legacy = tmp_path / "legacy.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=160)
    page.insert_text((20, 40), "EXISTING LABEL", fontsize=10)
    page.insert_text((20, 54), "既有译文", fontsize=10, fontname="china-s")
    document.save(legacy)
    document.close()
    additions, existing = select_legacy_additions(
        legacy_pdf_path=legacy,
        source_regions=[
            {
                "region_id": "existing",
                "page_number": 1,
                "source_text": "EXISTING LABEL",
                "translated_text": "既有译文",
                "bbox": [20, 28, 100, 42],
                "provenance": "paddle_ocr",
                "action": "translate",
                "addition_approval": "ai_verified_source",
            },
            {
                "region_id": "new",
                "page_number": 1,
                "source_text": "Distribution Storage Tank",
                "translated_text": "配水储水罐",
                "bbox": [140, 28, 250, 42],
                "provenance": "deepseek_ocr",
                "action": "translate",
                "addition_approval": "ai_verified_source",
            },
            {
                "region_id": "unapproved",
                "page_number": 1,
                "source_text": "SOME SYMBOL",
                "translated_text": "某符号",
                "bbox": [140, 80, 220, 92],
                "provenance": "paddle_ocr",
                "action": "translate",
            },
        ],
    )

    assert [item["region_id"] for item in additions] == ["new"]
    assert [item["region_id"] for item in existing] == ["existing"]
