from __future__ import annotations

from services.translation.results.applier import TranslationResultApplier


class _MemoryUpdater:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict], dict]] = []

    def update_from_batch(self, batch: list[dict], translated: dict) -> int:
        self.calls.append((batch, translated))
        return 1


class _FlushState:
    def __init__(self) -> None:
        self.dirty_pages: set[int] = set()

    def mark_dirty(self, pages: set[int]) -> None:
        self.dirty_pages.update(pages)


def test_result_applier_uses_memory_updater_protocol(tmp_path) -> None:
    payload = [{"item_id": "a", "page_idx": 0, "source_text": "SCF", "translated_text": ""}]
    memory = _MemoryUpdater()
    applier = TranslationResultApplier(
        flat_payload=payload,
        item_to_page={"a": 0},
        duplicate_items_by_rep_id={},
        flush_state=_FlushState(),
        memory_store=memory,
    )
    batch = [{"item_id": "a", "source_text": "SCF"}]
    translated = {"a": {"decision": "translate", "translated_text": "自洽场"}}

    touched = applier.apply_batch(batch, translated)

    assert touched == {0}
    assert len(memory.calls) == 1
    assert memory.calls[0][0] is batch
    assert memory.calls[0][1]["a"]["translated_text"] == "自洽场"


def test_result_applier_skips_memory_for_immediate_results(tmp_path) -> None:
    payload = [{"item_id": "a", "page_idx": 0, "source_text": "SCF", "translated_text": ""}]
    memory = _MemoryUpdater()
    applier = TranslationResultApplier(
        flat_payload=payload,
        item_to_page={"a": 0},
        duplicate_items_by_rep_id={},
        flush_state=_FlushState(),
        memory_store=memory,
    )

    applier.apply_immediate({"a": {"decision": "keep_origin", "translated_text": ""}})

    assert memory.calls == []
