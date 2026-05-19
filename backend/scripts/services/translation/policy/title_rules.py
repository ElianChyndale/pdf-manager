from __future__ import annotations

from services.translation.item_reader import item_is_title_like


TITLE_STYLE_HINT = (
    "Title rule: translate titles as concise formal headings. Preserve numbering, "
    "formula placeholders, symbols, and proper nouns; do not expand into body prose."
)


def is_title_translation_candidate(item: dict | None) -> bool:
    return item_is_title_like(item)


def apply_title_translation_rule(payload: list[dict]) -> int:
    applied = 0
    for item in payload:
        if not is_title_translation_candidate(item):
            continue
        existing = str(item.get("translation_style_hint", "") or "").strip()
        item["translation_style_hint"] = f"{existing}\n{TITLE_STYLE_HINT}".strip() if existing else TITLE_STYLE_HINT
        metadata = item.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["translation_style_hint"] = item["translation_style_hint"]
        applied += 1
    return applied


__all__ = [
    "TITLE_STYLE_HINT",
    "apply_title_translation_rule",
    "is_title_translation_candidate",
]
