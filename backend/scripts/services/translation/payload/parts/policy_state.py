from __future__ import annotations

from .common import clear_translation_fields


def mark_item_skipped(item: dict, label: str) -> None:
    item["classification_label"] = label
    item["should_translate"] = False
    item["skip_reason"] = label
    clear_translation_fields(item)
    item["final_status"] = "kept_origin"


def preserve_source_as_translation(item: dict) -> None:
    source_text = str(item.get("source_text", "") or "").strip()
    protected_source_text = str(item.get("protected_source_text", "") or source_text).strip()
    item["translation_unit_protected_translated_text"] = protected_source_text
    item["translation_unit_translated_text"] = source_text
    item["protected_translated_text"] = protected_source_text
    item["translated_text"] = source_text


__all__ = ["mark_item_skipped", "preserve_source_as_translation"]
