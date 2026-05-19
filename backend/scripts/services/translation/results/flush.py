from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from services.translation.workflow.pages import save_pages


class TranslationFlushState:
    def __init__(
        self,
        *,
        page_payloads: dict[int, list[dict]],
        translation_paths: dict[int, Path],
        flush_interval: int,
        total_batches: int,
        progress_callback: Callable[[int, int, set[int]], None] | None = None,
    ) -> None:
        self.page_payloads = page_payloads
        self.translation_paths = translation_paths
        self.flush_interval = max(1, flush_interval)
        self.total_batches = total_batches
        self.progress_callback = progress_callback
        self.dirty_pages: set[int] = set()

    def mark_dirty(self, pages: set[int]) -> None:
        self.dirty_pages.update(pages)

    def record_progress(self, completed: int, touched_pages: set[int]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(completed, self.total_batches, touched_pages)

    def flush_if_due(self, completed: int, *, label: str) -> None:
        if completed % self.flush_interval != 0:
            return
        self.flush(label=label)

    def flush(self, *, label: str) -> None:
        if not self.dirty_pages:
            return
        save_started = time.perf_counter()
        page_count = len(self.dirty_pages)
        save_pages(self.page_payloads, self.translation_paths, self.dirty_pages)
        print(
            f"book: {label} pages={page_count} in {time.perf_counter() - save_started:.2f}s",
            flush=True,
        )
        self.dirty_pages.clear()

    def final_flush(self) -> None:
        self.flush(label="final flush")


__all__ = ["TranslationFlushState"]
