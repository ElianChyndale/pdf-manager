from __future__ import annotations

from services.translation.memory import TranslationMemoryUpdater
from services.translation.memory import update_translation_memory
from services.translation.payload import apply_translated_text_map
from services.translation.payload.parts.common import GROUP_ITEM_PREFIX

from services.translation.results.flush import TranslationFlushState


def _clone_result_for_item(payload: dict[str, str], *, item: dict) -> dict[str, str]:
    cloned = dict(payload)
    diagnostics = dict(cloned.get("translation_diagnostics") or {})
    if diagnostics:
        diagnostics["item_id"] = item.get("item_id", "")
        diagnostics["page_idx"] = item.get("page_idx")
        cloned["translation_diagnostics"] = diagnostics
    return cloned


def expand_duplicate_results(
    translated: dict[str, dict[str, str]],
    *,
    duplicate_items_by_rep_id: dict[str, list[dict]],
) -> dict[str, dict[str, str]]:
    if not duplicate_items_by_rep_id:
        return translated
    expanded = dict(translated)
    for rep_id, duplicate_items in duplicate_items_by_rep_id.items():
        rep_payload = translated.get(rep_id)
        if not rep_payload:
            continue
        for duplicate_item in duplicate_items:
            expanded[str(duplicate_item.get("item_id", "") or "")] = _clone_result_for_item(
                rep_payload,
                item=duplicate_item,
            )
    return expanded


def current_payload_page_indexes(flat_payload: list[dict], fallback_item_to_page: dict[str, int]) -> tuple[dict[str, int], dict[str, set[int]]]:
    item_to_page: dict[str, int] = dict(fallback_item_to_page)
    unit_to_pages: dict[str, set[int]] = {}
    for item in flat_payload:
        item_id = str(item.get("item_id", "") or "")
        page_idx = item.get("page_idx")
        if page_idx is None:
            page_idx = fallback_item_to_page.get(item_id)
        if page_idx is None:
            continue
        item_to_page[item_id] = int(page_idx)
        unit_id = str(item.get("translation_unit_id") or item_id or "")
        if unit_id:
            unit_to_pages.setdefault(unit_id, set()).add(int(page_idx))
    return item_to_page, unit_to_pages


def touched_pages_for_batch(
    translated: dict[str, str],
    flat_payload: list[dict],
    fallback_item_to_page: dict[str, int],
) -> set[int]:
    item_to_page, unit_to_pages = current_payload_page_indexes(flat_payload, fallback_item_to_page)
    touched_pages: set[int] = set()
    for item_id in translated:
        if item_id.startswith(GROUP_ITEM_PREFIX):
            touched_pages.update(unit_to_pages.get(item_id, set()))
        elif item_id in item_to_page:
            touched_pages.add(item_to_page[item_id])
    return touched_pages


class TranslationResultApplier:
    def __init__(
        self,
        *,
        flat_payload: list[dict],
        item_to_page: dict[str, int],
        duplicate_items_by_rep_id: dict[str, list[dict]],
        flush_state: TranslationFlushState,
        memory_store: TranslationMemoryUpdater | None,
    ) -> None:
        self.flat_payload = flat_payload
        self.item_to_page = item_to_page
        self.duplicate_items_by_rep_id = duplicate_items_by_rep_id
        self.flush_state = flush_state
        self.memory_store = memory_store

    def apply_immediate(self, translated: dict[str, dict[str, str]]) -> set[int]:
        return self.apply_batch([], translated, update_memory=False)

    def apply_batch(
        self,
        batch: list[dict],
        translated: dict[str, dict[str, str]],
        *,
        update_memory: bool = True,
    ) -> set[int]:
        expanded = expand_duplicate_results(
            translated,
            duplicate_items_by_rep_id=self.duplicate_items_by_rep_id,
        )
        apply_translated_text_map(self.flat_payload, expanded)
        if update_memory:
            update_translation_memory(self.memory_store, batch=batch, translated=expanded)
        touched_pages = touched_pages_for_batch(expanded, self.flat_payload, self.item_to_page)
        self.flush_state.mark_dirty(touched_pages)
        return touched_pages


__all__ = [
    "TranslationResultApplier",
    "current_payload_page_indexes",
    "expand_duplicate_results",
    "touched_pages_for_batch",
]
