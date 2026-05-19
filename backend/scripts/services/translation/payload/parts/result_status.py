from __future__ import annotations

from .common import clear_translation_fields
from .result_entries import result_diagnostics_for_item

KEEP_ORIGIN_LABEL = "skip_model_keep_origin"


def mark_keep_origin(item: dict) -> None:
    item["classification_label"] = KEEP_ORIGIN_LABEL
    item["should_translate"] = False
    item["skip_reason"] = KEEP_ORIGIN_LABEL
    item["final_status"] = "kept_origin"
    clear_translation_fields(item)


def mark_translation_failed(item: dict, metadata: dict) -> None:
    item["should_translate"] = True
    item["classification_label"] = ""
    item["skip_reason"] = ""
    item["final_status"] = "failed"
    clear_translation_fields(item)
    diagnostics = result_diagnostics_for_item(metadata, item)
    if diagnostics:
        diagnostics["final_status"] = "failed"
        item["translation_diagnostics"] = diagnostics


__all__ = ["KEEP_ORIGIN_LABEL", "mark_keep_origin", "mark_translation_failed"]
