from __future__ import annotations

from statistics import median

import fitz

from services.rendering.layout.font_roles import is_body_text_candidate
from services.rendering.layout.font_roles import is_caption_like_block
from services.rendering.layout.font_roles import is_footnote_like_block
from services.rendering.layout.font_roles import is_title_like_block
from services.rendering.layout.typography.measurement import bbox_height
from services.rendering.layout.typography.measurement import bbox_width
from services.translation.item_reader import item_layout_role
from services.translation.item_reader import item_semantic_role


INDENT_RENDER_SCALE = 2.0
MIN_BLOCK_WIDTH_PT = 80.0
MIN_BLOCK_HEIGHT_PT = 20.0
MIN_DETECTED_LINES = 2
INK_THRESHOLD = 26
ROW_INK_RATIO = 0.012
COL_INK_RATIO = 0.035
MIN_LINE_HEIGHT_PX = 3
MAX_INDENT_EM = 2.2


def _is_body_paragraph(item: dict, *, page_text_width_med: float) -> bool:
    if is_caption_like_block(item) or is_footnote_like_block(item) or is_title_like_block(item):
        return False
    layout_role = item_layout_role(item)
    semantic_role = item_semantic_role(item)
    if layout_role not in {"paragraph", "list_item"} and not is_body_text_candidate(item, page_text_width_med):
        return False
    return semantic_role in {"", "body", "abstract", "unknown"}


def _border_background(samples: bytes, width: int, height: int) -> int:
    if width <= 0 or height <= 0:
        return 255
    values: list[int] = []
    for x in range(width):
        values.append(samples[x])
        values.append(samples[(height - 1) * width + x])
    for y in range(height):
        values.append(samples[y * width])
        values.append(samples[y * width + width - 1])
    if not values:
        return 255
    return int(median(values))


def _ink_rows(samples: bytes, width: int, height: int, background: int) -> list[bool]:
    min_ink = max(2, int(width * ROW_INK_RATIO))
    rows: list[bool] = []
    for y in range(height):
        start = y * width
        ink = 0
        for pixel in samples[start : start + width]:
            if abs(int(pixel) - background) >= INK_THRESHOLD and int(pixel) < background:
                ink += 1
        rows.append(ink >= min_ink)
    return rows


def _bands(flags: list[bool], *, min_size: int) -> list[tuple[int, int]]:
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            if index - start >= min_size:
                bands.append((start, index))
            start = None
    if start is not None and len(flags) - start >= min_size:
        bands.append((start, len(flags)))
    return bands


def _line_left_px(samples: bytes, width: int, background: int, y0: int, y1: int) -> int | None:
    band_height = max(1, y1 - y0)
    min_ink = max(1, int(band_height * COL_INK_RATIO))
    for x in range(width):
        ink = 0
        for y in range(y0, y1):
            pixel = int(samples[y * width + x])
            if abs(pixel - background) >= INK_THRESHOLD and pixel < background:
                ink += 1
        if ink >= min_ink:
            return x
    return None


def detect_first_line_indent_pt(
    source_doc: fitz.Document | None,
    item: dict,
    *,
    page_idx: int,
    font_size_pt: float,
    page_text_width_med: float,
) -> float:
    if source_doc is None or page_idx < 0 or page_idx >= len(source_doc):
        return 0.0
    if not _is_body_paragraph(item, page_text_width_med=page_text_width_med):
        return 0.0
    if bbox_width(item) < MIN_BLOCK_WIDTH_PT or bbox_height(item) < MIN_BLOCK_HEIGHT_PT:
        return 0.0
    bbox = item.get("bbox", [])
    if len(bbox) != 4:
        return 0.0

    page = source_doc[page_idx]
    clip = fitz.Rect(bbox) & page.rect
    if clip.is_empty or clip.width <= 0 or clip.height <= 0:
        return 0.0
    pix = page.get_pixmap(
        matrix=fitz.Matrix(INDENT_RENDER_SCALE, INDENT_RENDER_SCALE),
        colorspace=fitz.csGRAY,
        alpha=False,
        clip=clip,
    )
    if pix.width <= 0 or pix.height <= 0:
        return 0.0

    samples = pix.samples
    background = _border_background(samples, pix.width, pix.height)
    line_bands = _bands(_ink_rows(samples, pix.width, pix.height, background), min_size=MIN_LINE_HEIGHT_PX)
    if len(line_bands) < MIN_DETECTED_LINES:
        return 0.0
    lefts = [
        left
        for y0, y1 in line_bands
        if (left := _line_left_px(samples, pix.width, background, y0, y1)) is not None
    ]
    if len(lefts) < MIN_DETECTED_LINES:
        return 0.0

    first_left = lefts[0]
    rest_lefts = lefts[1:]
    rest_median = median(rest_lefts)
    indent_px = first_left - rest_median
    indent_pt = indent_px / INDENT_RENDER_SCALE
    threshold = max(4.0, min(8.0, font_size_pt * 0.75))
    if indent_pt < threshold:
        return 0.0
    max_indent = max(8.0, font_size_pt * MAX_INDENT_EM)
    return round(max(0.0, min(indent_pt, max_indent)), 2)


__all__ = [
    "detect_first_line_indent_pt",
]
