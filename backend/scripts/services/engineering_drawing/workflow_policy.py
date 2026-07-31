"""Versioned policy shared by engineering-drawing translation stages.

This module is deliberately data-only.  The OCR, translation, placement and
visual-QA stages all consume the same policy snapshot so a later stage cannot
silently fall back to word-by-word captions or a different placement order.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Mapping, Sequence


WORKFLOW_VERSION = "v4.0-readable-zone-complete"
# The active engineering-drawing supervisor is a Codex agent using Sol Light.
DEFAULT_MULTIMODAL_MODEL = "gpt-5.6-sol"
DEFAULT_SUPERVISOR_ADAPTER = {
    "alias": "codex-sol-light",
    "provider": "openai-codex",
    "model_name": "gpt-5.6-sol",
    "reasoning_profile": "light",
    "capabilities": [
        "multimodal_page_planning",
        "ocr_task_supervision",
        "semantic_translation_planning",
        "translation_placement_planning",
        "visual_release_review",
    ],
}
SUPPORTED_SUPERVISOR_ADAPTERS = {
    "codex-sol-light": deepcopy(DEFAULT_SUPERVISOR_ADAPTER),
}
# Backward-compatible name consumed by the disabled legacy batch manifest writer.
SOL_MODEL = "codex-sol-light"


def validate_directory_mask_audit(audit: Mapping[str, object]) -> dict[str, object]:
    """Hard-gate directory masks against protected columns and grid rules."""
    masks = audit.get("masks") or []
    protected = audit.get("protected_rects") or []
    rules = audit.get("table_rule_rects") or []
    clearance = float(audit.get("minimum_clearance_pt", 0.0) or 0.0)
    if clearance < 1.5:
        raise ValueError("directory mask audit requires at least 1.5pt structure clearance")
    def rect(raw: Sequence[object]) -> tuple[float, float, float, float]:
        if len(raw) != 4: raise ValueError("mask audit rectangles require four coordinates")
        x0,y0,x1,y1=map(float,raw);return x0,y0,x1,y1
    def area(a: tuple[float,float,float,float], b: tuple[float,float,float,float]) -> float:
        return max(0.0,min(a[2],b[2])-max(a[0],b[0]))*max(0.0,min(a[3],b[3])-max(a[1],b[1]))
    intersections=[]
    for mi,m in enumerate(masks):
        mr=rect(m)
        for kind,items in (("protected_column",protected),("table_rule",rules)):
            for ri,r in enumerate(items):
                overlap=area(mr,rect(r))
                if overlap>0: intersections.append({"mask_index":mi,"kind":kind,"protected_index":ri,"area":overlap})
    if intersections: raise ValueError(f"directory masks intersect protected structure: {intersections}")
    if audit.get("pagewise_row_numbers_match_source") is not True:
        raise ValueError("pagewise source row-number comparison is required")
    return {"passed":True,"intersection_count":0,"intersection_area":0.0,"minimum_clearance_pt":clearance}


PRODUCTION_TYPOGRAPHY = {
    "readability_is_release_gate": True,
    "inspection_scale": "100_percent_and_2x_targeted_crops",
    "global_rules": {
        "use_largest_fitting_size": True,
        "match_source_visual_hierarchy": True,
        "prefer_reflow_or_second_whitespace_area_before_shrinking": True,
        "translation_must_not_look_microscopic_relative_to_source": True,
    },
    "directory_index": {
        "batch_scale": 1.20,
        "batch_scale_basis": "source_hierarchy_baseline_before_largest_fit_clamp",
        "size_formula": "min(largest_fitting_size, max(hard_minimum_pt, source_hierarchy_baseline * batch_scale))",
        "preferred_minimum_pt": 7.2,
        "hard_minimum_pt": 6.8,
        "use_largest_fitting_size": True,
        "cell_edge_padding_pt": [1.5, 3.0],
        "target_cell_height_utilization": [0.72, 0.90],
        "content": "black_source_plus_chinese_in_each_corresponding_cell",
        "mask_scope": "verified_natural_language_glyph_union_only",
        "mask_protected_fields": ["row_number_column", "drawing_number_column", "size_column", "table_rules"],
        "maximum_mask_protected_intersection_area": 0.0,
        "minimum_mask_clearance_from_protected_pt": 1.5,
        "row_number_visibility_and_source_match_required": True,
        "mask_policy": {
            "scope": "verified_natural_language_glyph_union_only",
            "protected_columns": ["row_number", "drawing_number", "size"],
            "protect_table_rules": True,
            "minimum_structure_clearance_pt": 1.5,
            "required_audit": "mask-vs-protected-columns",
            "maximum_intersection_count": 0,
            "maximum_intersection_area": 0.0,
            "require_pagewise_row_number_source_comparison": True,
        },
    },
    "company_contact_panel": {
        "batch_scale": 1.18,
        "batch_scale_basis": "source_hierarchy_baseline_before_largest_fit_clamp",
        "size_formula": "min(largest_fitting_size, max(hard_minimum_pt, source_hierarchy_baseline * batch_scale))",
        "preferred_minimum_pt": 6.8,
        "hard_minimum_pt": 6.4,
        "use_each_cells_actual_whitespace": True,
        "use_largest_fitting_size": True,
        "protect": ["logo", "border", "separator", "stamp", "signature"],
    },
    "drawing_body": {
        "preferred_minimum_pt": 6.4,
        "hard_minimum_pt": 5.8,
        "source_size_ratio_minimum": 0.85,
        "content": "complete_blue_chinese_semantic_block_near_preserved_source",
    },
}


LAYOUT_POLICY = {
    "preferred_side": "dynamic_multimodal_candidate_score",
    "fallback_order": ["local_whitespace_candidates", "bounded_reflow", "short_leader"],
    "automatic_left_fallback": "leader_required",
    "default_local_distance_points": 24,
    "minimum_dynamic_radius_points": 12,
    "max_local_distance_points": 48,
    "near_translation_max_distance_points": 48,
    "allowed_source_overlap_ratio": 0.18,
    "allowed_visual_ink_ratio": 0.04,
    "safe_target_max_visual_ink_ratio": 0.03,
    "target_authority": "multimodal_visual_plan",
    "ocr_geometry_role": "source_anchor_only_not_target_obstacle",
    "inline_excluded_page_types": [
        "dense_drawing_index",
        "sheet_index",
        "catalog_table",
    ],
    "target_collision_inputs": [
        "visible_raster_or_vector_ink",
        "accepted_chinese_caption_boxes",
        "page_bounds",
    ],
    "minimum_text_gap_points": "soft_guidance_only",
    "font_size_policy": {
        "preferred_minimum_points": 6.4,
        "emergency_minimum_points": 5.8,
        "absolute_minimum_points": 5.8,
    },
    "duplicate_policy": "suppress_equivalent_existing_companion",
    "repeat_instance_policy": "translate_each_distinct_equipment_or_id_separately",
    "rotation_policy": "preserve_local_readable_orientation_never_mirror_or_upside_down",
    "translation_style": {
        "proper_names_and_addresses": "chinese_translation_with_original_in_parentheses",
        "source_literal_preservation": "numbers_units_ids_and_codes_unchanged",
        "layout_fidelity": (
            "layout_isomorphic_reflow: preserve the source panel hierarchy, "
            "alignment, whitespace rhythm, borders, separators, logos and all "
            "text embedded in logos; clear only confirmed non-logo text glyph "
            "bounds, never an undifferentiated whole panel"
        ),
        "typography_inheritance": (
            "inherit semantic emphasis from the source: headings, company names, "
            "category rows and emphasized table entries remain bold and use the "
            "same relative size hierarchy; the Chinese counterpart receives the "
            "same emphasis level"
        ),
        "semantic_fidelity": (
            "retain every qualifier, relationship, enumeration, scope, negation, "
            "unit, identifier and drawing/model reference; compression may shorten "
            "wording but may not remove meaning"
        ),
    },
    "leader_policy": (
        "explicit multimodal plan may use a short direct orthogonal or diagonal route for dense CAD, "
        "tables, title blocks, consultant/address panels, and paragraphs when the "
        "same semantic cell has no safe room; no arrow; choose the nearest readable "
        "target and the shortest direct route; do not add a long detour merely to "
        "avoid incidental background linework. Leader/background crossing is an "
        "advisory finding, and a leader crossing a Chinese caption is also only "
        "advisory when the characters remain visually identifiable. A small "
        "source-ink/table-line overlap is allowed "
        "when it keeps the complete Chinese block nearby and readable; "
        "target-target overlap remains a failure. Ordinary raster/CAD linework is not a hard "
        "routing obstacle; only Chinese caption boxes, protected borders, logos and critical "
        "engineering geometry are hard obstacles"
    ),
    "leader_style": {
        "color": "dark_blue",
        "width_points": 0.32,
        "arrow": False,
        "route": "shortest_direct_orthogonal_or_diagonal",
    },
    "space_priority": [
        "score_all_local_candidates_for_whole_semantic_group",
        "semantic_boundary_wrap_or_group_scale",
        "short_leader_with_audited_reason",
        "manual_review_candidate_not_release",
    ],
    "title_block_policy": (
        "classify as state_bearing_metadata or prose_or_index_metadata first; score "
        "whole-group local candidates without fixed direction order; preserve all "
        "state symbols, borders and semantic grouping"
    ),
    "legacy_position_policy": "legacy_positions_are_evidence_only_and_must_pass_all_v4_rules_before_reuse",
    "unit_of_work": "one_pdf_page",
    "repeat_title_policy": "translate_on_every_page_where_visible",
    "table_reflow_policy": (
        "translate_each_distinct_row_or_cell for ordinary tables; allow in-cell "
        "wrap without border change. A new visible item number is a hard semantic "
        "and placement boundary. One numbered item may span several physical "
        "subrows. When the same item number repeats with a different drawing/model "
        "number, each (item number, drawing/model number, ruled row range) tuple "
        "is a separate semantic and placement block. Source and Chinese text may "
        "never cross between those tuples. Dense drawing-index/sheet-index/catalog "
        "tables are excluded from ordinary inline-caption delivery and use "
        "single-page opaque bilingual reflow: preserve the grid, row number, "
        "drawing/model number and size columns, clear only the title-cell "
        "interior, then typeset source text plus Chinese in black. Preserve the "
        "source typography class per cell: section/category headings such as "
        "PERINCIAN STEPS remain bold and larger, and their Chinese translations "
        "use the same emphasis. Grid lines and row separators are release-critical"
    ),
    "non_drawing_panel_reflow_policy": (
        "For company, consultant, address and contact panels, use "
        "layout-isomorphic bilingual reflow. Treat each logo and any lettering "
        "inside it as one protected graphic object. Preserve every original divider "
        "and border. Replace only verified text glyph areas, and reconstruct source "
        "plus Chinese with the original alignment, emphasis and relative font-size "
        "hierarchy. A panel fails release if a logo, logo lettering, divider, "
        "identifier, contact value or semantic qualifier is lost or obscured."
    ),
    "source_replacement_policy": (
        "When a non-drawing text panel is re-typeset, the previous source text "
        "operators should be physically removed with text redaction before source "
        "plus Chinese are inserted. If the lettering is outlined/vector ink and "
        "cannot be text-redacted, a supervisor-approved opaque mask may cover only "
        "the exact complete glyph union; whole-panel white overlays are forbidden. "
        "The redaction envelope must cover the complete visual glyph union, "
        "including outlined or fragmented OCR spans; protected logos and vector "
        "rules are excluded and release-critical rules are restored explicitly."
    ),
    "microtext_detection_policy": {
        "authority": "multimodal_supervisor_not_ocr",
        "coverage_target": "every_visible_non_chinese_natural_language_instance",
        "scan_pyramid": [
            "full_page_semantic_scan",
            "drawing_zone_tiles_with_overlap",
            "high_zoom_microtext_crops",
            "rotated_vertical_and_diagonal_text_pass",
            "post_render_missing_text_rescan",
        ],
        "zoom_rule": (
            "inspect each suspected unreadable glyph from the original source PDF "
            "at up to 6x magnification before any exception; use 6x when lower "
            "magnification is insufficient. Tiny labels such as FLOW, FALL, PITCH "
            "and ROOF remain mandatory even when OCR returns no region"
        ),
        "manual_review_exception": {
            "allowed_scope": "one genuinely illegible glyph or objectively ambiguous technical symbol",
            "forbidden_scope": ["whole_page", "whole_zone", "ocr_batch", "readable_word_or_phrase"],
            "required_source": "original_source_pdf",
            "required_zoom_multiplier": 6,
            "required_evidence": ["source_pdf_sha256", "crop_reference", "single_glyph_bbox", "observed_context", "reason"],
        },
        "ocr_role": (
            "OCR proposes text and coordinates, but absence from OCR never proves "
            "that a visible label is non-language or exempt"
        ),
        "repeat_instance_rule": (
            "inventory every spatially distinct occurrence of repeated labels, "
            "including FALL, FLOW, PITCH, ROOF, VOID and equipment notes"
        ),
        "release_gate": (
            "zero unexplained visible foreign-language glyph groups at the highest "
            "inspection zoom"
        ),
    },
    "symbol_semantics_policy": {
        "directional_symbols_are_semantic": True,
        "examples": ["FLOW arrow", "FALL arrow", "slope arrow", "from/to leader"],
        "translation_rule": (
            "the Chinese companion must retain or reproduce the associated arrow, "
            "direction, degree value, polarity or relationship; translating only "
            "the word while dropping the symbol meaning is incomplete"
        ),
        "placement_rule": (
            "place the Chinese within the local visual group of the source word and "
            "its symbol; never fully cover the source, and use only a short leader "
            "when immediate adjacency is impossible"
        ),
    },
    "literal_exemption_policy": (
        "Only tokens that are purely identifiers or values are exempt: drawing/model "
        "codes, equipment IDs, grid/section letters, dimensions, levels, scale values, "
        "standards, phone numbers, email addresses and URLs. If a token group contains "
        "any natural-language descriptor, translate the descriptor and preserve the "
        "literal identifier/value."
    ),
    "planning_policy": {
        "order": [
            "multimodal_supervisor_page_scan",
            "supervisor_ocr_task_plan",
            "ocr_execution",
            "post_ocr_multimodal_reconciliation_with_page_image_coordinates_and_knowledge",
            "supervisor_translation_task_plan",
            "translation_execution",
            "semantic_block_grouping",
            "translation_and_layout_plan",
            "deterministic_render",
            "multimodal_visual_review",
            "deterministic_repair",
        ],
        "model_must_scan_image_beyond_ocr": True,
        "supervisor_role": "multimodal_page_manager",
        "supervisor_before_ocr_translation": True,
        "supervisor_after_ocr_before_translation": True,
        "post_ocr_release_gate": (
            "every OCR region must be translated, literal_only, false_positive, "
            "or manual_review; visual additions must be inventoried and "
            "unexplained_region_ids must be empty"
        ),
        "supervisor_handoff_contract": "supervisor_plan_declares_ocr_translation_and_placement_tasks",
        "execution_authority": "scripts_execute_only_declared_or_explicitly_escalated_tasks",
        "coverage_statuses": [
            "translated",
            "no_translation_needed",
            "missing",
            "low_confidence",
        ],
        "unexplained_candidate_is_release_blocking": True,
        "model_selected_target_is_authoritative": True,
        "ocr_target_conflict_rule": (
            "The multimodal visual target overrides OCR/native text occupancy; "
            "OCR geometry remains a source anchor and cannot reject a visually "
            "blank planned target"
        ),
        "coverage_release_rule": (
            "every visible natural-language block must receive a translated, "
            "literal-only, or explicitly manual-review entry; renderer repair "
            "may shrink, wrap, overlap a small amount of source ink, or use a "
            "short leader, but must never silently omit the block. A dense "
            "drawing-index page is not released inline or as a legacy pair; its "
            "supervisor plan must select opaque_bilingual_reflow"
        ),
    },
    "unreadable_text_policy": "preserve_source_and_request_multimodal_model_review",
    "language_scope": "all_visible_natural_languages_including_english_malay_arabic_jawi_and_other_scripts",
}


SUPERVISOR_POLICY = {
    "role": "multimodal_page_manager",
    "supervisor_count": 1,
    "parallel_multimodal_agents_forbidden": True,
    "stage": "before_ocr_and_translation",
    "image_authority": "full_page_render_first",
    "default_adapter": deepcopy(DEFAULT_SUPERVISOR_ADAPTER),
    "supported_adapters": deepcopy(SUPPORTED_SUPERVISOR_ADAPTERS),
    "adapter_selection_rule": (
        "production accepts only codex-sol-light with gpt-5.6-sol and light reasoning"
    ),
    "required_outputs": [
        "page_type",
        "page_region_map",
        "delivery_mode",
        "existing_translation_inventory",
        "coverage_inventory",
        "ocr_tasks",
        "translation_tasks",
        "placement_policy",
        "escalations",
    ],
    "ocr_task_contract": [
        "task_id",
        "page_index",
        "region_or_crop",
        "engine_or_mode",
        "rotation",
        "language_scope",
        "priority",
        "expected_output",
    ],
    "ocr_execution_contract": {
        "authority": "multimodal_supervisor",
        "mode_when_tasks_present": "supervisor_declared_task_crops",
        "allow_generic_full_page_fallback": False,
        "allow_crop_expansion_or_relocation": False,
        "multi_page_requires_page_index": True,
        "invalid_task_action": "fail_before_ocr",
    },
    "translation_task_contract": [
        "task_id",
        "source_candidate_ids",
        "semantic_unit",
        "translation_style",
        "preserved_tokens",
        "do_not_merge",
        "completeness_requirement",
    ],
    "placement_task_contract": [
        "target_regions",
        "font_size_range",
        "rotation",
        "leader_policy",
        "source_overlap_policy",
    ],
    "escalation_rule": (
        "if OCR and visual inspection disagree, the supervisor resolves the conflict "
        "or marks the block manual_review; OCR never silently chooses the target"
    ),
    "regional_rendering_contract": {
        "drawing_body": "preserve_source_and_add_nearby_blue_chinese",
        "drawing_table": "preserve_source_and_add_nearby_blue_chinese",
        "sidebar_footer": "must_semantically_subdivide_before_rendering",
        "sidebar_footer_table": "must_semantically_subdivide_before_rendering",
        "company_contact_panel": "exact_text_ink_cover_then_black_source_plus_chinese_reflow",
        "non_company_metadata_panel": "must_subclassify_as_state_bearing_or_prose_index",
        "directory_index": "exact_text_ink_cover_then_black_source_plus_chinese",
    },
    "mutually_exclusive_translation_render_modes": {
        "allowed": ["preserve_source_blue_chinese", "opaque_bilingual_reflow"],
        "exactly_one_per_translated_block": True,
        "preserve_source_blue_chinese": {
            "source_visible": True,
            "chinese_color": "blue",
            "mask_or_redaction_forbidden": True,
        },
        "opaque_bilingual_reflow": {
            "old_natural_language_glyphs_visible": False,
            "render": "black_source_plus_chinese",
            "partial_mask_or_mixed_old_new_text_forbidden": True,
        },
        "zone_defaults": {
            "company_contact_panel": "opaque_bilingual_reflow",
            "drawing_body": "preserve_source_blue_chinese",
            "drawing_table": "preserve_source_blue_chinese",
            "state_bearing_metadata": "preserve_source_blue_chinese",
        },
        "logo_policy": "soft_protection_prefer_avoid_but_logo_overlap_alone_does_not_block_release",
    },
    "sidebar_footer_subregion_gate": {
        "company_contact_preserve": ["logo", "border", "separator", "stamp"],
        "non_company_metadata_examples": [
            "project_description", "copyright_disclaimer", "drawing_status",
            "drawing_title_index", "scale", "drafter_checker_date_drawing_number",
        ],
        "state_bearing_metadata_forbidden": ["white_mask", "source_text_deletion", "region_clearing"],
        "state_bearing_metadata_preserve": [
            "source_text", "checkbox", "status_mark", "signature_line",
            "revision_symbol", "table_tick", "number_frame", "business_state_symbol",
        ],
        "prose_or_index_metadata": {
            "replacement_allowed": True,
            "strategy": "black_bilingual_hierarchy_reflow",
            "must_preserve": ["border", "section_hierarchy", "indentation", "emphasis", "whitespace_rhythm"],
            "dense_unstructured_block": "release_blocking",
        },
        "dynamic_blue_placement": {
            "candidate_directions": ["above", "below", "left", "right", "local_whitespace"],
            "bounded_weight_adjustment": True,
            "default_high_penalty": "source_text_overlap",
            "maximum_search_radius": "local_conservative",
            "audit": ["candidates", "scores", "chosen", "relaxation_reason"],
            "weight_bounds": {
                "source_text_overlap": "always_above_local_distance_gain",
                "semantic_association": "always_above_ordinary_engineering_line_avoidance",
                "group_internal_dispersion": "infinite_release_blocking",
                "translation_translation_overlap": "infinite_release_blocking",
            },
        },
        "excess_blank_space_with_tiny_type": "release_blocking",
    },
    "existing_translation_rule": (
        "read local reference PDFs and existing Chinese layers as wording evidence; every old "
        "translation must be revalidated for V4 completeness, zone, typography, position and "
        "visible ink before reuse; legacy status never grants automatic preservation"
    ),
    "repair_budget": 1,
    "second_failure_action": "human_handling",
    "render_base_contract": {
        "base": "original_source_pdf",
        "freeze_before_reference_read": ["absolute_path", "sha256", "page_count", "page_sizes"],
        "reference_usage": "translation_evidence_only",
        "copied_reference_page_or_region": False,
        "reference_coordinates_are_targets": False,
    },
    "no_reference_path": (
        "single multimodal supervisor inventories and classifies the original render first; "
        "OCR then transcribes only declared regions; the same supervisor reconciles evidence, "
        "translates and designs final layout on the original PDF"
    ),
}


PAGE_DELIVERY_POLICY = {
    "default_page_type": "engineering_drawing",
    "release_directory_policy": {
        "translated_root": "01_Bilingual_Inline/translated",
        "current_release_subdirectory": "v4.0-readable-zone-complete",
        "historical_subdirectories_are_evidence_only": ["01_报审图纸", "02_清真寺施工图纸"],
    },
    "delivery_modes": ["inline_bilingual", "opaque_bilingual_reflow", "source_only"],
    "dense_drawing_index": {
        "inline_allowed": False,
        "delivery_mode": "opaque_bilingual_reflow",
        "source_pdf_required": True,
        "translation_pdf_required": False,
        "reason": (
            "dense index/catalog tables become unreadable with external captions; "
            "preserve the table grid and administrative columns, clear each title "
            "cell interior, and re-typeset source plus Chinese in one final PDF"
        ),
    },
    "non_drawing_information_panel": {
        "requires_subclassification": True,
        "delivery_mode": "determined_by_subtype",
        "eligible_content": [
            "company_and_consultant_information",
            "address",
            "telephone_fax_email_website",
            "prose_or_index_metadata_after_semantic_subclassification",
            "drawing_index_title_cells",
        ],
        "preserve": [
            "panel_and_table_borders",
            "logos",
            "row_numbers",
            "drawing_model_numbers",
            "revision_scale_date_and_size_values",
        ],
        "typesetting": "determined_after_semantic_subclassification",
        "typesetting_by_subtype": {
            "company_contact_panel": "black_source_text_plus_black_chinese_translation",
            "state_bearing_metadata": "preserve_source_plus_blue_nearby_chinese",
            "prose_or_index_metadata": "black_hierarchy_preserving_source_plus_chinese",
        },
    },
}


SEMANTIC_GROUP_POLICY = {
    "unit": "semantic_block",
    "translate_before_place": True,
    "layout_atomicity": {
        "one_translation_string": True,
        "one_group_anchor": True,
        "one_target_bbox": True,
        "one_placement_decision": True,
        "independent_member_or_character_placement_forbidden": True,
    },
    "internal_consistency": {
        "uniform_font_size": True,
        "uniform_rotation": True,
        "uniform_color": True,
        "consistent_baseline_family": True,
        "consistent_character_spacing": True,
        "consistent_line_spacing": True,
        "maximum_member_dispersion_points": 0.0,
    },
    "line_break_policy": {
        "allowed": ["complete_phrase", "semantic_clause", "enumeration_item", "explicit_field_boundary"],
        "forbidden": [
            "inside_chinese_word", "between_number_and_unit", "inside_identifier_or_model_code",
            "between_modifier_and_head", "inside_parameter_expression",
        ],
        "continuous_multiline_source": "one_multiline_translation_textbox",
    },
    "paragraph_block": {
        "enabled": True,
        "join_adjacent_lines": True,
        "preserve_reading_order": True,
        "translation_join": "newline_within_block",
        "require_same_page_rotation_and_local_frame": True,
        "distinct_instances_are_always_separate": True,
        "do_not_merge": [
            "drawing/model/equipment identifiers",
            "dimensions, elevations, quantities, units and standards",
            "telephone, email and URL tokens",
            "independent room/equipment labels",
            "title-block field rows such as DRAWN, CHECKED, SCALE and REV",
            "separate table cells, legend entries or callouts",
        ],
    },
    "source_preservation": {
        "source_text_remains_visible": True,
        "legacy_translation_requires_full_v4_revalidation": True,
        "unknown_text_becomes_manual_review": True,
        "unreadable_text_keeps_original_visible": True,
    },
}


VISUAL_QA_POLICY = {
    "production_quality_target": {
        "minimum_score": 90,
        "objective": "good_and_close_to_excellent_at_reasonable_cost",
        "maximum_automatic_repairs": 1,
        "publish_when_target_met": True,
        "do_not_block_on_soft_cosmetic_findings": True,
    },
    "gate_partition": {
        "strict": [
            "important_natural_language_complete",
            "engineering_meaning_and_parameters_correct",
            "semantic_group_understandable",
            "source_object_association_clear",
            "no_blue_paint_stacking",
            "table_row_model_relationships_correct",
            "major_geometry_logo_dimension_device_wiring_protected",
            "normal_review_readability",
            "directory_and_company_typography_minimums",
        ],
        "soft": [
            "leader_crosses_ordinary_engineering_line",
            "minor_table_or_fill_line_overlap",
            "non_shortest_distance",
            "font_size_difference",
            "local_visual_density",
        ],
        "ignored": [
            "perfect_leader_ink_avoidance",
            "uniform_font_size",
            "one_ocr_box_per_translation",
            "zero_collision_score",
            "fixed_region_count",
            "four_x_pixel_difference",
            "fixed_direction_priority",
        ],
        "normal_zoom_readability_as_standalone_gate": True,
    },
    "source_translation_overlap": "bounded_advisory",
    "source_overlap_advisory_ratio": 0.18,
    "visual_ink_advisory_ratio": 0.04,
    "visual_ink_relaxed_ratio": 0.30,
    "dense_cad_visual_ink_relaxed_ratio": 0.70,
    "translation_translation_overlap": "zero",
    "leader_collision": "advisory_when_chinese_remains_readable",
    "leader_collision_release_rule": (
        "does_not_block_when_translation_boxes remain visually identifiable; "
        "leader crossings are advisory unless they materially hide or corrupt the Chinese"
    ),
    "leader_route_length_rule": (
        "prefer_nearest_clear_target_and_shortest_direct_orthogonal_or_diagonal_route; do not detour "
        "solely to avoid incidental background linework; the executor protects "
        "translation boxes, not source ink"
    ),
    "clipped_or_empty_translation": "zero",
    "untranslated_natural_language": "zero_for_release",
    "manual_review_allowed": True,
    "manual_review_release_rule": "candidate_only_unless_user_explicitly_accepts_each_exception",
    "manual_review_scope": "only an isolated glyph/symbol that remains illegible after original-PDF 6x inspection",
    "dense_index_inline": "release_blocking",
    "dense_index_required_delivery": "opaque_bilingual_reflow",
}


def policy_snapshot() -> dict:
    """Return a JSON-serialisable copy for manifests and review packages."""

    return {
        "workflow_version": WORKFLOW_VERSION,
        "model": DEFAULT_MULTIMODAL_MODEL,
        "default_supervisor_adapter": deepcopy(DEFAULT_SUPERVISOR_ADAPTER),
        "supported_supervisor_adapters": deepcopy(SUPPORTED_SUPERVISOR_ADAPTERS),
        "layout": deepcopy(LAYOUT_POLICY),
        "page_delivery": deepcopy(PAGE_DELIVERY_POLICY),
        "supervisor": deepcopy(SUPERVISOR_POLICY),
        "semantic_grouping": deepcopy(SEMANTIC_GROUP_POLICY),
        "visual_qa": deepcopy(VISUAL_QA_POLICY),
        "production_typography": deepcopy(PRODUCTION_TYPOGRAPHY),
    }


__all__ = [
    "LAYOUT_POLICY",
    "PAGE_DELIVERY_POLICY",
    "PRODUCTION_TYPOGRAPHY",
    "SUPERVISOR_POLICY",
    "SEMANTIC_GROUP_POLICY",
    "SOL_MODEL",
    "DEFAULT_SUPERVISOR_ADAPTER",
    "SUPPORTED_SUPERVISOR_ADAPTERS",
    "DEFAULT_MULTIMODAL_MODEL",
    "VISUAL_QA_POLICY",
    "WORKFLOW_VERSION",
    "policy_snapshot",
]
