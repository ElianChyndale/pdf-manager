import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.diagnostics.io import aggregate_payload_diagnostics
from runtime.pipeline.book_pipeline import _blocking_untranslated_items


def test_aggregate_payload_diagnostics_keeps_items_with_final_status_only() -> None:
    translated_pages_map = {
        4: [
            {
                "item_id": "p004-b030",
                "final_status": "translated",
                "translated_text": "译文",
            }
        ]
    }

    item_diagnostics, summary = aggregate_payload_diagnostics(translated_pages_map)

    assert len(item_diagnostics) == 1
    assert item_diagnostics[0]["item_id"] == "p004-b030"
    assert item_diagnostics[0]["page_idx"] == 4
    assert item_diagnostics[0]["final_status"] == "translated"
    assert summary["status_summary"]["translated"] == 1


def test_aggregate_payload_diagnostics_whitelists_intentional_keep_origin_items() -> None:
    translated_pages_map = {
        5: [
            {
                "item_id": "p006-b015",
                "final_status": "kept_origin",
                "skip_reason": "skip_display_formula",
            },
            {
                "item_id": "p006-b016",
                "final_status": "kept_origin",
                "skip_reason": "skip_model_keep_origin",
            },
        ]
    }

    _item_diagnostics, summary = aggregate_payload_diagnostics(translated_pages_map)

    assert summary["status_summary"]["kept_origin"] == 2
    assert summary["unresolved_translation_count"] == 0
    assert _blocking_untranslated_items(translated_pages_map) == []


def test_blocking_untranslated_items_keeps_non_whitelisted_failures_blocking() -> None:
    translated_pages_map = {
        1: [
            {
                "item_id": "p002-b001",
                "final_status": "kept_origin",
                "translation_diagnostics": {
                    "route_path": ["block_level", "direct_typst"],
                    "degradation_reason": "validation",
                },
            }
        ]
    }

    blocked = _blocking_untranslated_items(translated_pages_map)

    assert len(blocked) == 1
    assert blocked[0]["item_id"] == "p002-b001"


def test_aggregate_payload_diagnostics_adds_debug_location_fields() -> None:
    translated_pages_map = {
        2: [
            {
                "item_id": "p003-b004",
                "math_mode": "direct_typst",
                "final_status": "failed",
                "translation_diagnostics": {
                    "route_path": ["block_level", "direct_typst"],
                    "request_label": "book: batch 1/2 item 1/3",
                    "provider_family": "deepseek_official",
                    "error_trace": [{"type": "validation", "message": "empty translation output"}],
                },
            }
        ]
    }

    item_diagnostics, _summary = aggregate_payload_diagnostics(translated_pages_map)

    assert item_diagnostics[0]["provider"] == "deepseek_official"
    assert item_diagnostics[0]["prompt_mode"] == "direct_typst"
    assert item_diagnostics[0]["request_label"] == "book: batch 1/2 item 1/3"
    assert item_diagnostics[0]["raw_excerpt"] == "empty translation output"
