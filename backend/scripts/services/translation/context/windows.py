from __future__ import annotations

from dataclasses import dataclass

from services.translation.context.models import sanitize_prompt_context_text
from services.translation.item_reader import item_is_textual


DEFAULT_CONTEXT_WINDOW_NEIGHBORS = 2
DEFAULT_CONTEXT_TEXT_LIMIT = 360


@dataclass(frozen=True)
class TranslationContextWindow:
    item_id: str
    before: str = ""
    after: str = ""


def _item_order(item: dict) -> tuple[int, int]:
    page_idx = item.get("page_idx", 0)
    block_idx = item.get("block_idx", item.get("reading_order", 0))
    try:
        page_idx = int(page_idx)
    except Exception:
        page_idx = 0
    try:
        block_idx = int(block_idx)
    except Exception:
        block_idx = 0
    return page_idx, block_idx


def _context_source(item: dict) -> str:
    return sanitize_prompt_context_text(
        str(
            item.get("source_text")
            or item.get("protected_source_text")
            or item.get("translation_unit_protected_source_text")
            or ""
        )
    )


def _trim_context(text: str, *, limit: int) -> str:
    compact = sanitize_prompt_context_text(text)
    if len(compact) <= limit:
        return compact
    return f"{compact[: max(0, limit - 1)].rstrip()}..."


def _join_context_items(items: list[dict], *, limit: int) -> str:
    parts = [_context_source(item) for item in items if _context_source(item)]
    return _trim_context(" / ".join(parts), limit=limit)


def _is_context_candidate(item: dict) -> bool:
    if not item_is_textual(item):
        return False
    if not _context_source(item):
        return False
    return True


def build_translation_context_windows(
    page_payloads: dict[int, list[dict]],
    *,
    neighbors: int = DEFAULT_CONTEXT_WINDOW_NEIGHBORS,
    text_limit: int = DEFAULT_CONTEXT_TEXT_LIMIT,
) -> dict[str, TranslationContextWindow]:
    flat_items = [
        item
        for page_idx in sorted(page_payloads)
        for item in sorted(page_payloads[page_idx], key=_item_order)
    ]
    context_items = [item for item in flat_items if _is_context_candidate(item)]
    index_by_identity = {id(item): index for index, item in enumerate(context_items)}
    windows: dict[str, TranslationContextWindow] = {}
    window_size = max(0, int(neighbors))
    for item in flat_items:
        item_id = str(item.get("item_id", "") or "")
        if not item_id or not _is_context_candidate(item):
            continue
        index = index_by_identity.get(id(item))
        if index is None:
            continue
        before_items = context_items[max(0, index - window_size) : index]
        after_items = context_items[index + 1 : index + 1 + window_size]
        windows[item_id] = TranslationContextWindow(
            item_id=item_id,
            before=_join_context_items(before_items, limit=text_limit),
            after=_join_context_items(after_items, limit=text_limit),
        )
    return windows


def annotate_translation_context_windows(
    page_payloads: dict[int, list[dict]],
    *,
    neighbors: int = DEFAULT_CONTEXT_WINDOW_NEIGHBORS,
    text_limit: int = DEFAULT_CONTEXT_TEXT_LIMIT,
) -> int:
    """Attach lightweight reading-order context for the translator.

    This does not decide whether an item should be translated. It only gives the
    model nearby text so short fragments, captions, and structured technical
    rows can be interpreted without adding fragile no-translation rules.
    """

    windows = build_translation_context_windows(page_payloads, neighbors=neighbors, text_limit=text_limit)
    annotated = 0
    flat_items = [
        item
        for page_idx in sorted(page_payloads)
        for item in sorted(page_payloads[page_idx], key=_item_order)
    ]
    for item in flat_items:
        item_id = str(item.get("item_id", "") or "")
        window = windows.get(item_id)
        if window is None:
            item["translation_context_before"] = ""
            item["translation_context_after"] = ""
            continue
        if item.get("translation_context_before") != window.before:
            item["translation_context_before"] = window.before
            annotated += 1
        if item.get("translation_context_after") != window.after:
            item["translation_context_after"] = window.after
            annotated += 1
    return annotated


__all__ = [
    "DEFAULT_CONTEXT_TEXT_LIMIT",
    "DEFAULT_CONTEXT_WINDOW_NEIGHBORS",
    "TranslationContextWindow",
    "annotate_translation_context_windows",
    "build_translation_context_windows",
]
