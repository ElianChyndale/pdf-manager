from __future__ import annotations

import fitz

from services.rendering.source.preparation.bbox_text_strip_accumulator import BBoxTextStripCandidateAccumulator
from services.rendering.source.preparation.bbox_text_strip_geometry import formula_guard_rects
from services.rendering.source.preparation.bbox_text_strip_items import build_source_item_rects
from services.rendering.source.preparation.bbox_text_strip_items import iter_formula_item_rects_for_page
from services.rendering.source.preparation.bbox_text_strip_items import iter_strip_item_rects_for_page
from services.rendering.source.preparation.bbox_text_strip_page_gate import bbox_text_strip_items_skip_reason
from services.rendering.source.preparation.bbox_text_strip_page_gate import bbox_text_strip_page_skip_reason
from services.rendering.source.preparation.bbox_text_strip_rects import merge_rects
from services.rendering.source.preparation.bbox_text_strip_segments import strip_segments_for_text_rect
from services.rendering.source.preparation.bbox_text_strip_types import BBOX_TEXT_STRIP_PAGE_SKIP_NONE
from services.rendering.source.preparation.bbox_text_strip_types import BBoxTextStripCandidates
from services.rendering.source.preparation.bbox_text_strip_types import BBoxTextStripPagePlan


def build_bbox_text_strip_candidates(
    *,
    source_pdf_path,
    translated_pages: dict[int, list[dict]],
    skip_formula_pages: bool = True,
    strict_replace: bool = False,
) -> BBoxTextStripCandidates:
    accumulator = BBoxTextStripCandidateAccumulator()
    doc = fitz.open(source_pdf_path)
    try:
        for page_idx, items in translated_pages.items():
            if page_idx < 0 or page_idx >= len(doc):
                continue
            page = doc[page_idx]
            page_plan = plan_bbox_text_strip_page(
                doc,
                page,
                translated_items=items,
                skip_formula_pages=skip_formula_pages,
                strict_replace=strict_replace,
            )
            accumulator.add_page_plan(page_idx, page_plan)
    finally:
        doc.close()
    return accumulator.build()


def plan_bbox_text_strip_page(
    doc: fitz.Document,
    page: fitz.Page,
    *,
    translated_items: list[dict],
    skip_formula_pages: bool = False,
    strict_replace: bool = False,
) -> BBoxTextStripPagePlan:
    items_skip_reason = bbox_text_strip_items_skip_reason(
        translated_items,
        skip_formula_pages=skip_formula_pages,
    )
    if items_skip_reason != BBOX_TEXT_STRIP_PAGE_SKIP_NONE:
        target_rects = build_page_strip_source_rects_for_page(
            page,
            translated_items=translated_items,
            strict_replace=strict_replace,
        )
        formula_rects = build_page_formula_rects_for_page(page, translated_items=translated_items)
        protected_rects = build_formula_guard_rects(formula_rects, strip_rects=target_rects)
        return BBoxTextStripPagePlan(
            target_rects=tuple(target_rects),
            protected_rects=tuple(protected_rects),
            skip_reason=items_skip_reason,
        )

    target_rects = build_page_strip_source_rects_for_page(
        page,
        translated_items=translated_items,
        strict_replace=strict_replace,
    )
    if not target_rects:
        return BBoxTextStripPagePlan()
    formula_rects = build_page_formula_rects_for_page(page, translated_items=translated_items)
    protected_rects = build_formula_guard_rects(formula_rects, strip_rects=target_rects)

    item_rects = build_source_item_rects(translated_items, strict_replace=strict_replace)
    if not item_rects:
        return BBoxTextStripPagePlan()
    skip_reason = bbox_text_strip_page_skip_reason(doc, page, source_item_rects=item_rects)
    if skip_reason != BBOX_TEXT_STRIP_PAGE_SKIP_NONE:
        return BBoxTextStripPagePlan(
            target_rects=tuple(target_rects),
            protected_rects=tuple(protected_rects),
            skip_reason=skip_reason,
        )

    strip_rects = build_page_strip_rects_for_page(
        page,
        translated_items=translated_items,
        strict_replace=strict_replace,
    )
    return BBoxTextStripPagePlan(
        target_rects=tuple(target_rects),
        strip_rects=tuple(strip_rects),
        protected_rects=tuple(protected_rects),
    )


def build_page_strip_rects_for_page(
    page: fitz.Page,
    *,
    translated_items: list[dict],
    strict_replace: bool = False,
) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    protected_formula_rects = build_page_formula_rects_for_page(page, translated_items=translated_items)
    for _item, rect in iter_strip_item_rects_for_page(
        page,
        translated_items,
        strict_replace=strict_replace,
    ):
        rects.extend(strip_segments_for_text_rect(rect, protected_formula_rects))
    return merge_rects(rects)


def build_page_formula_rects_for_page(
    page: fitz.Page,
    *,
    translated_items: list[dict],
) -> list[fitz.Rect]:
    return [rect for _item, rect in iter_formula_item_rects_for_page(page, translated_items)]


def build_formula_guard_rects(
    formula_rects: list[fitz.Rect],
    *,
    strip_rects: list[fitz.Rect] | None = None,
) -> list[fitz.Rect]:
    return formula_guard_rects(formula_rects, strip_rects=strip_rects)


def build_page_strip_source_rects_for_page(
    page: fitz.Page,
    *,
    translated_items: list[dict],
    strict_replace: bool = False,
) -> list[fitz.Rect]:
    return merge_rects(
        [
            rect
            for _item, rect in iter_strip_item_rects_for_page(
                page,
                translated_items,
                strict_replace=strict_replace,
            )
        ]
    )
