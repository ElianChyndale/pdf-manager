from pathlib import Path

from services.engineering_drawing.workflow_policy import (
    SUPPORTED_SUPERVISOR_ADAPTERS,
    WORKFLOW_VERSION,
    policy_snapshot,
)


ROOT = Path(__file__).resolve().parents[5]


def test_v4_is_the_only_active_normative_language() -> None:
    assert WORKFLOW_VERSION == "v4.0-readable-zone-complete"
    files = [
        ROOT / "backend/scripts/services/engineering_drawing/WORKFLOW_SPEC_V4.md",
        ROOT / "backend/scripts/foundation/prompts/rule_profile_engineering_drawing.txt",
        ROOT / "backend/scripts/foundation/prompts/engineering_drawing_supervisor_v37.txt",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for stale in (
        "normal-zoom readability is deliberately not a standalone release gate",
        "normal_zoom_readability_as_standalone_gate\": false",
        "black_chinese_only",
        "black_chinese_replacement",
        "不设“正常查看比例必须可读”的统一硬门槛",
        "不以正常查看倍率的字号作为单独失败条件",
        "后写且更具体",
    ):
        assert stale.casefold() not in combined.casefold()


def test_directory_and_company_typography_are_explicit_hard_rules() -> None:
    policy = policy_snapshot()
    typography = policy["production_typography"]
    assert typography["readability_is_release_gate"] is True
    assert typography["directory_index"]["batch_scale"] == 1.20
    assert typography["directory_index"]["hard_minimum_pt"] >= 6.8
    assert typography["directory_index"]["use_largest_fitting_size"] is True
    assert typography["directory_index"]["maximum_mask_protected_intersection_area"] == 0.0
    assert typography["directory_index"]["minimum_mask_clearance_from_protected_pt"] >= 1.5
    assert typography["directory_index"]["row_number_visibility_and_source_match_required"] is True
    assert typography["company_contact_panel"]["batch_scale"] == 1.18
    assert typography["company_contact_panel"]["hard_minimum_pt"] >= 6.4
    assert typography["company_contact_panel"]["use_each_cells_actual_whitespace"] is True


def test_production_policy_has_no_legacy_bypass_semantics() -> None:
    policy = policy_snapshot()
    assert set(SUPPORTED_SUPERVISOR_ADAPTERS) == {"codex-sol-light"}
    assert policy["page_delivery"]["dense_drawing_index"]["delivery_mode"] == "opaque_bilingual_reflow"
    assert policy["page_delivery"]["non_drawing_information_panel"]["delivery_mode"] == "determined_by_subtype"
    assert policy["visual_qa"]["gate_partition"]["normal_zoom_readability_as_standalone_gate"] is True
    serialized = repr(policy).casefold()
    assert "v3_" not in serialized
    assert "black_chinese_only" not in serialized
    assert "never_drop_legacy_translation" not in serialized


def test_translated_blocks_use_one_exclusive_render_mode_and_logo_is_soft() -> None:
    modes = policy_snapshot()["supervisor"]["mutually_exclusive_translation_render_modes"]
    assert modes["exactly_one_per_translated_block"] is True
    assert set(modes["allowed"]) == {"preserve_source_blue_chinese", "opaque_bilingual_reflow"}
    assert modes["zone_defaults"]["company_contact_panel"] == "opaque_bilingual_reflow"
    assert modes["preserve_source_blue_chinese"]["mask_or_redaction_forbidden"] is True
    assert modes["opaque_bilingual_reflow"]["old_natural_language_glyphs_visible"] is False
    assert "soft" in modes["logo_policy"]
