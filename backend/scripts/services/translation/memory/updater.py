from __future__ import annotations

from typing import Any
from typing import Protocol


class TranslationMemoryUpdater(Protocol):
    def update_from_batch(self, batch: list[dict], translated: dict[str, dict[str, Any]]) -> int: ...


class NullTranslationMemoryUpdater:
    def update_from_batch(self, batch: list[dict], translated: dict[str, dict[str, Any]]) -> int:
        return 0


def update_translation_memory(
    updater: TranslationMemoryUpdater | None,
    *,
    batch: list[dict],
    translated: dict[str, dict[str, Any]],
) -> int:
    if updater is None:
        return 0
    return updater.update_from_batch(batch, translated)


__all__ = ["NullTranslationMemoryUpdater", "TranslationMemoryUpdater", "update_translation_memory"]
