from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

import fitz


_BACKEND_DIR = Path(__file__).resolve().parents[5]
_DEFAULT_FONT_PATH = _BACKEND_DIR / "fonts" / "SourceHanSerifSC-Regular.otf"
_FONT_NAME = "engineering_zh"
_SIDEBAR_COLUMN_WIDTH = 190.0
_SIDEBAR_GUTTER = 12.0
_MIN_FONT_SIZE = 5.5
_REFERENCE_MARGIN = 18.0
_REFERENCE_GUTTER = 12.0
_REFERENCE_HEADER_HEIGHT = 34.0
_REFERENCE_FOOTER_HEIGHT = 16.0
_REFERENCE_INDEX_THRESHOLD = 36


@dataclass(frozen=True)
class EngineeringRenderResult:
    output_pdf_path: Path
    pages_rendered: int
    inline_placements: int
    sidebar_placements: int
    review_items: int
    reference_pages: int = 0
    reference_items: int = 0
    reference_map_path: Path | None = None


def _page_index(region: dict) -> int:
    return max(0, int(region.get("page_index", region.get("page", 0)) or 0))


def _translated_text(region: dict) -> str:
    return str(
        region.get("translated_text")
        or region.get("protected_translated_text")
        or region.get("translation")
        or ""
    ).strip()


def _source_text(region: dict) -> str:
    return str(region.get("source_text") or region.get("text") or "").strip()


def _valid_bbox(region: dict) -> fitz.Rect | None:
    bbox = region.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        rect = fitz.Rect(*(float(value) for value in bbox))
    except (TypeError, ValueError):
        return None
    return rect if not rect.is_empty and not rect.is_infinite else None


def _regions_by_page(regions: Iterable[dict]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {}
    for region in regions:
        translated = _translated_text(region)
        if not translated:
            continue
        result.setdefault(_page_index(region), []).append(region)
    for page_regions in result.values():
        page_regions.sort(key=lambda item: (_valid_bbox(item).y0 if _valid_bbox(item) else 0, _valid_bbox(item).x0 if _valid_bbox(item) else 0))
    return result


def _font_path(font_path: Path | None) -> Path:
    selected = Path(font_path) if font_path else _DEFAULT_FONT_PATH
    if not selected.exists():
        raise FileNotFoundError(f"Chinese render font not found: {selected}")
    return selected


def _normalize_source_page_rotations(source: fitz.Document) -> None:
    # show_pdf_page() composes the unrotated page content stream and can therefore
    # rotate or clip CAD sheets whose landscape appearance is stored in /Rotate.
    # Baking the rotation preserves the displayed geometry and its coordinates.
    for page in source:
        if page.rotation:
            page.remove_rotation()


def _regions_for_normalized_source(regions: Iterable[dict], source: fitz.Document) -> list[dict]:
    """Transform OCR coordinates before baking a PDF page rotation.

    OCR and native text extraction use the source page's unrotated coordinate
    system.  ``remove_rotation()`` changes the visible geometry.  Leaving the
    old bbox behind was the direct cause of captions appearing in unrelated
    blank margins on 90° / 270° engineering sheets.
    """
    matrices = [page.rotation_matrix for page in source]
    rotations = [int(page.rotation or 0) % 360 for page in source]
    transformed: list[dict] = []
    for raw in regions:
        region = dict(raw)
        page_index = _page_index(region)
        source_rect = _valid_bbox(region)
        # Native PDF text is emitted in the unrotated page coordinate system.
        # Paddle / DeepSeek work on a rendered page image, so their bboxes are
        # already in display coordinates and must *not* be transformed again.
        needs_page_transform = str(region.get("provenance") or "") == "native_text"
        if source_rect is not None and needs_page_transform and 0 <= page_index < len(matrices):
            displayed_rect = source_rect * matrices[page_index]
            region["bbox"] = [displayed_rect.x0, displayed_rect.y0, displayed_rect.x1, displayed_rect.y1]
            rotation = _rotation(region)
            if rotation:
                region["rotation"] = (rotation - rotations[page_index]) % 360
        transformed.append(region)
    return transformed


def _text_height(text: str, width: float, font: fitz.Font, font_size: float, *, line_gap: float = 1.22) -> float:
    effective_width = max(20.0, width)
    logical_lines = 0
    for paragraph in (text or " ").splitlines() or [" "]:
        paragraph_width = max(font.text_length(paragraph or " ", fontsize=font_size), font_size)
        logical_lines += max(1, int(paragraph_width / effective_width) + 1)
    return max(font_size * line_gap, logical_lines * font_size * line_gap)


def _occupied_rects(page: fitz.Page) -> list[fitz.Rect]:
    occupied: list[fitz.Rect] = []
    for block in page.get_text("blocks"):
        if len(block) >= 4:
            occupied.append(fitz.Rect(block[:4]))
    try:
        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect:
                occupied.append(fitz.Rect(rect))
    except Exception:
        pass
    return occupied


def _source_text_rects(page: fitz.Page) -> list[fitz.Rect]:
    """Return source *word* bounds, not broad PDF text blocks.

    CAD title blocks frequently expose an entire table cell (or a rotated
    column) as one PDF text block.  Treating that envelope as ink makes the
    legitimate empty area beside a tank, road label or address unavailable to
    the bilingual layout.  Word-level bounds remain a hard no-overlap boundary
    while allowing a nearby Chinese companion in the same cell.
    """
    return [fitz.Rect(word[:4]) for word in page.get_text("words") if len(word) >= 4]


def _is_clear(rect: fitz.Rect, occupied: list[fitz.Rect], page_rect: fitz.Rect) -> bool:
    if not page_rect.contains(rect):
        return False
    padded = fitz.Rect(rect.x0 - 1.5, rect.y0 - 1.5, rect.x1 + 1.5, rect.y1 + 1.5)
    return not any(padded.intersects(other) and not (padded & other).is_empty for other in occupied)


def _inline_candidate(
    *,
    source_rect: fitz.Rect,
    translated: str,
    page_rect: fitz.Rect,
    occupied: list[fitz.Rect],
    font: fitz.Font,
) -> tuple[fitz.Rect, float] | None:
    font_size = max(_MIN_FONT_SIZE, min(8.0, max(6.0, source_rect.height * 0.72)))
    desired_width = min(max(58.0, font.text_length(translated, fontsize=font_size) + 8.0), max(70.0, page_rect.width * 0.28))
    desired_height = _text_height(translated, desired_width - 6.0, font, font_size) + 5.0
    gap = 3.0
    candidates = (
        fitz.Rect(source_rect.x0, source_rect.y1 + gap, source_rect.x0 + desired_width, source_rect.y1 + gap + desired_height),
        fitz.Rect(source_rect.x0, source_rect.y0 - gap - desired_height, source_rect.x0 + desired_width, source_rect.y0 - gap),
        fitz.Rect(source_rect.x1 + gap, source_rect.y0, source_rect.x1 + gap + desired_width, source_rect.y0 + desired_height),
        fitz.Rect(source_rect.x0 - gap - desired_width, source_rect.y0, source_rect.x0 - gap, source_rect.y0 + desired_height),
    )
    for candidate in candidates:
        if _is_clear(candidate, occupied, page_rect):
            return candidate, font_size
    return None


def _insert_textbox_fitted(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    font_path: Path,
    font_size: float,
    min_font_size: float = _MIN_FONT_SIZE,
    color: tuple[float, float, float] = (0.05, 0.16, 0.45),
    fill: tuple[float, float, float] | None = None,
    rotate: int = 0,
) -> float:
    current = font_size
    while current >= min_font_size:
        remaining = page.insert_textbox(
            rect,
            text,
            fontname=_FONT_NAME,
            fontfile=str(font_path),
            fontsize=current,
            color=color,
            fill=fill,
            border_width=0,
            rotate=rotate if rotate in {0, 90, 180, 270} else 0,
            overlay=True,
        )
        if remaining >= -0.01:
            return current
        current -= 0.5
    return -1.0


def _sidebar_layout(
    regions: list[dict],
    *,
    page_height: float,
    font: fitz.Font,
) -> tuple[int, list[float]]:
    heights: list[float] = []
    usable_height = max(80.0, page_height - 40.0)
    for region in regions:
        source = _source_text(region)
        translated = _translated_text(region)
        source_height = _text_height(source, _SIDEBAR_COLUMN_WIDTH - 24.0, font, 5.5)
        translated_height = _text_height(translated, _SIDEBAR_COLUMN_WIDTH - 24.0, font, 7.0)
        heights.append(max(28.0, source_height + translated_height + 12.0))
    columns = 1
    while columns < 8 and sum(heights) > usable_height * columns:
        columns += 1
    return columns, heights


def _draw_sidebar(
    page: fitz.Page,
    *,
    source_width: float,
    regions: list[dict],
    font_path: Path,
    font: fitz.Font,
    heading: str,
) -> None:
    page.draw_rect(
        fitz.Rect(source_width, 0, page.rect.width, page.rect.height),
        color=(0.72, 0.76, 0.84),
        fill=(0.97, 0.98, 1.0),
        width=0.6,
        overlay=True,
    )
    _insert_textbox_fitted(
        page,
        fitz.Rect(source_width + 10, 8, page.rect.width - 8, 27),
        heading,
        font_path=font_path,
        font_size=9.0,
        min_font_size=7.0,
        color=(0.05, 0.12, 0.3),
    )
    _columns, heights = _sidebar_layout(regions, page_height=page.rect.height, font=font)
    x = source_width + _SIDEBAR_GUTTER
    y = 32.0
    for index, (region, height) in enumerate(zip(regions, heights), start=1):
        if y + height > page.rect.height - 8:
            x += _SIDEBAR_COLUMN_WIDTH
            y = 32.0
        source = _source_text(region)
        translated = _translated_text(region)
        bbox = _valid_bbox(region)
        coord = f"({bbox.x0:.0f},{bbox.y0:.0f})" if bbox else "(无坐标)"
        page.draw_rect(
            fitz.Rect(x - 3, y - 2, x + _SIDEBAR_COLUMN_WIDTH - 9, y + height - 3),
            color=(0.84, 0.86, 0.91),
            fill=(1, 1, 1),
            width=0.35,
            overlay=True,
        )
        _insert_textbox_fitted(
            page,
            fitz.Rect(x, y, x + 19, y + 13),
            str(index),
            font_path=font_path,
            font_size=7.0,
            min_font_size=6.0,
            color=(0.75, 0.12, 0.08),
        )
        _insert_textbox_fitted(
            page,
            fitz.Rect(x + 20, y, x + _SIDEBAR_COLUMN_WIDTH - 12, y + height - 3),
            f"{coord} {source}\n{translated}",
            font_path=font_path,
            font_size=7.0,
            min_font_size=5.5,
            color=(0.05, 0.12, 0.3),
        )
        y += height + 4.0


def _reference_requested(region: dict) -> bool:
    return str(region.get("placement", "") or "").strip().casefold() in {
        "reference",
        "sidebar",
        "side_bar",
    }


def _reference_label(number: int) -> str:
    return f"[{number}]"


def _anchor_rect(
    source_rect: fitz.Rect,
    *,
    page_rect: fitz.Rect,
    occupied: list[fitz.Rect],
) -> fitz.Rect:
    width, height, gap = 17.0, 9.0, 2.0
    candidates = (
        fitz.Rect(source_rect.x1 + gap, source_rect.y0 - height, source_rect.x1 + gap + width, source_rect.y0),
        fitz.Rect(source_rect.x0 - width - gap, source_rect.y0 - height, source_rect.x0 - gap, source_rect.y0),
        fitz.Rect(source_rect.x1 + gap, source_rect.y1, source_rect.x1 + gap + width, source_rect.y1 + height),
        fitz.Rect(source_rect.x0 - width - gap, source_rect.y1, source_rect.x0 - gap, source_rect.y1 + height),
    )
    for candidate in candidates:
        if _is_clear(candidate, occupied, page_rect):
            return candidate
    # A source label can be dense on every side. Use a very small, visible
    # fallback over its corner rather than losing the source-to-reference link.
    return fitz.Rect(
        source_rect.x0,
        source_rect.y0,
        min(source_rect.x1, source_rect.x0 + width),
        min(source_rect.y1, source_rect.y0 + height),
    )


def _draw_reference_anchor(
    page: fitz.Page,
    *,
    rect: fitz.Rect,
    label: str,
    font_path: Path,
) -> None:
    page.draw_rect(
        rect,
        color=(0.72, 0.12, 0.08),
        fill=(1.0, 1.0, 0.90),
        width=0.45,
        overlay=True,
    )
    _insert_textbox_fitted(
        page,
        rect,
        label,
        font_path=font_path,
        font_size=5.8,
        min_font_size=4.5,
        color=(0.65, 0.08, 0.05),
    )


def _reference_card_measure(entry: dict, *, font: fitz.Font, width: float) -> tuple[float, float, float]:
    # Measure the actual strings inserted below, including their Chinese labels.
    # CAD sheets often produce narrow reference columns, where omitting these
    # prefixes was enough to cut the source line after the card had been drawn.
    # The extra leading is intentional: a reference page may be longer, but it
    # must never silently clip a source or Chinese companion string.
    source_height = _text_height(
        f"原文：{_source_text(entry['region'])}",
        width,
        font,
        5.8,
        line_gap=1.42,
    ) + 5.8
    target_height = _text_height(
        f"中文：{_translated_text(entry['region'])}",
        width,
        font,
        7.5,
        line_gap=1.42,
    ) + 7.5
    return max(44.0, source_height + target_height + 28.0), source_height, target_height


def _draw_reference_card(
    page: fitz.Page,
    *,
    card_rect: fitz.Rect,
    entry: dict,
    source_height: float,
    target_height: float,
    font_path: Path,
) -> bool:
    label = str(entry["label"])
    region = entry["region"]
    page.draw_rect(
        card_rect,
        color=(0.76, 0.80, 0.88),
        fill=(0.985, 0.99, 1.0),
        width=0.4,
        overlay=True,
    )
    label_rect = fitz.Rect(card_rect.x0 + 4, card_rect.y0 + 3, card_rect.x0 + 24, card_rect.y0 + 14)
    source_rect = fitz.Rect(card_rect.x0 + 25, card_rect.y0 + 3, card_rect.x1 - 4, card_rect.y0 + 5 + source_height)
    target_rect = fitz.Rect(
        card_rect.x0 + 4,
        source_rect.y1 + 3,
        card_rect.x1 - 4,
        min(card_rect.y1 - 3, source_rect.y1 + 5 + target_height),
    )
    _insert_textbox_fitted(
        page,
        label_rect,
        label,
        font_path=font_path,
        font_size=6.5,
        min_font_size=5.0,
        color=(0.72, 0.12, 0.08),
    )
    source_ok = _insert_textbox_fitted(
        page,
        source_rect,
        f"原文：{_source_text(region)}",
        font_path=font_path,
        font_size=5.8,
        min_font_size=4.8,
        color=(0.20, 0.24, 0.32),
    )
    target_ok = _insert_textbox_fitted(
        page,
        target_rect,
        f"中文：{_translated_text(region)}",
        font_path=font_path,
        font_size=7.5,
        min_font_size=5.5,
        color=(0.02, 0.10, 0.28),
    )
    return source_ok >= 0 and target_ok >= 0


def _render_reference_pages(
    output: fitz.Document,
    *,
    source_output_page_index: int,
    source_page_number: int,
    source_rect: fitz.Rect,
    entries: list[dict],
    font: fitz.Font,
    font_path: Path,
) -> tuple[int, list[dict]]:
    if not entries:
        return 0, []
    width, height = source_rect.width, source_rect.height
    columns = 3 if width >= height else 2
    column_width = (width - 2 * _REFERENCE_MARGIN - (columns - 1) * _REFERENCE_GUTTER) / columns
    top = _REFERENCE_MARGIN + _REFERENCE_HEADER_HEIGHT
    bottom = height - _REFERENCE_MARGIN - _REFERENCE_FOOTER_HEIGHT
    page_count = 0
    reference_map: list[dict] = []
    entry_index = 0
    while entry_index < len(entries):
        reference_page = output.new_page(width=width, height=height)
        page_count += 1
        reference_page.draw_rect(
            reference_page.rect,
            color=(0.76, 0.80, 0.88),
            fill=(0.985, 0.99, 1.0),
            width=0.3,
            overlay=True,
        )
        _insert_textbox_fitted(
            reference_page,
            fitz.Rect(_REFERENCE_MARGIN, _REFERENCE_MARGIN, width - _REFERENCE_MARGIN, top - 4),
            f"源图第 {source_page_number} 页 · 中文引用翻译索引（编号对应原图）",
            font_path=font_path,
            font_size=10.0,
            min_font_size=8.0,
            color=(0.04, 0.12, 0.30),
        )
        x = _REFERENCE_MARGIN
        y = top
        column = 0
        while entry_index < len(entries):
            entry = entries[entry_index]
            card_height, source_height, target_height = _reference_card_measure(
                entry,
                font=font,
                width=column_width - 10,
            )
            if y + card_height > bottom and y > top:
                column += 1
                x += column_width + _REFERENCE_GUTTER
                y = top
            if column >= columns:
                break
            card_rect = fitz.Rect(x, y, x + column_width, min(bottom, y + card_height))
            complete = _draw_reference_card(
                reference_page,
                card_rect=card_rect,
                entry=entry,
                source_height=source_height,
                target_height=target_height,
                font_path=font_path,
            )
            source_output_page = output[source_output_page_index]
            source_output_page.insert_link(
                {
                    "kind": fitz.LINK_GOTO,
                    "from": entry["anchor_rect"],
                    "page": reference_page.number,
                    "to": fitz.Point(card_rect.x0, card_rect.y0),
                }
            )
            reference_page.insert_link(
                {
                    "kind": fitz.LINK_GOTO,
                    "from": card_rect,
                    "page": source_output_page_index,
                    "to": fitz.Point(entry["anchor_rect"].x0, entry["anchor_rect"].y0),
                }
            )
            reference_map.append(
                {
                    "reference_id": entry["reference_id"],
                    "display_label": entry["label"],
                    "region_id": entry["region"].get("region_id", ""),
                    "source_page_number": source_page_number,
                    "source_output_page": source_output_page_index + 1,
                    "anchor_bbox": list(entry["anchor_rect"]),
                    "reference_output_page": reference_page.number + 1,
                    "reference_card_bbox": list(card_rect),
                    "complete_text_fit": complete,
                    "link_verified": False,
                }
            )
            entry_index += 1
            y = card_rect.y1 + 5.0
        _insert_textbox_fitted(
            reference_page,
            fitz.Rect(_REFERENCE_MARGIN, bottom + 2, width - _REFERENCE_MARGIN, height - _REFERENCE_MARGIN),
            f"引用索引页 {page_count}",
            font_path=font_path,
            font_size=6.0,
            min_font_size=5.0,
            color=(0.32, 0.38, 0.48),
        )
    return page_count, reference_map


def _rects_intersect(left: fitz.Rect, right: fitz.Rect) -> bool:
    return not (left & right).is_empty


def _verify_reference_links(pdf_path: Path, reference_map: list[dict]) -> None:
    """Mark a reference as verified only after the saved PDF exposes both links."""
    if not reference_map:
        return
    try:
        document = fitz.open(pdf_path)
    except Exception:
        for entry in reference_map:
            entry["link_verified"] = False
        return
    try:
        for entry in reference_map:
            try:
                source_index = int(entry["source_output_page"]) - 1
                reference_index = int(entry["reference_output_page"]) - 1
                anchor = fitz.Rect(*entry["anchor_bbox"])
                card = fitz.Rect(*entry["reference_card_bbox"])
                source_links = document[source_index].get_links()
                reference_links = document[reference_index].get_links()
                forward = any(
                    link.get("kind") == fitz.LINK_GOTO
                    and int(link.get("page", -1)) == reference_index
                    and _rects_intersect(fitz.Rect(link["from"]), anchor)
                    for link in source_links
                    if link.get("from")
                )
                backward = any(
                    link.get("kind") == fitz.LINK_GOTO
                    and int(link.get("page", -1)) == source_index
                    and _rects_intersect(fitz.Rect(link["from"]), card)
                    for link in reference_links
                    if link.get("from")
                )
                entry["link_verified"] = forward and backward
            except Exception:
                entry["link_verified"] = False
    finally:
        document.close()


def _compact_inline_text(value: str) -> str:
    """The source drawing already preserves literals, so avoid repeating them."""
    text = str(value or "").strip()
    text = text.replace("（原文：", "（").replace("（原文数值/标识：", "（")
    return text


def _inline_only_rect(
    source_rect: fitz.Rect,
    *,
    translated: str,
    page_rect: fitz.Rect,
    occupied: list[fitz.Rect],
    font: fitz.Font,
    rotation: int,
) -> tuple[fitz.Rect, float, float] | None:
    """Find a *near* caption position without covering source information.

    A CAD sheet has attractive but semantically unrelated white areas.  Those
    areas are not valid fallbacks: the user must be able to compare Chinese with
    its source at a glance.  This helper therefore considers only adjoining
    rectangles and returns ``None`` when the source neighbourhood is occupied.
    """
    # Dense CAD annotations are often materially smaller than conventional
    # document text.  A missing companion is worse than a 2.4pt caption when
    # viewed at the drawing's native zoom, so start from the source size and
    # permit a controlled micro-caption fallback.  The caller still rejects a
    # rectangle that touches source text.
    font_size = max(2.4, min(6.8, max(3.2, source_rect.height * 0.58)))
    # _is_clear applies 1.5pt padding around both rectangles; leave enough room
    # for a caption immediately beside a source label to remain selectable.
    gap = max(3.2, font_size * 0.45)
    if rotation in {90, 270}:
        # PyMuPDF rotates text inside the supplied rectangle.  A vertical
        # caption therefore needs a narrow rectangle whose long axis contains
        # the unrotated Chinese line.
        thickness = max(font_size * 1.55, 7.0)
        span = min(
            max(30.0, font.text_length(translated, fontsize=font_size) + 5.0),
            page_rect.height * 0.16,
        )
        candidates = (
            fitz.Rect(source_rect.x1 + gap, source_rect.y0, source_rect.x1 + gap + thickness, source_rect.y0 + span),
            fitz.Rect(source_rect.x0 - gap - thickness, source_rect.y0, source_rect.x0 - gap, source_rect.y0 + span),
            fitz.Rect(source_rect.x1 + gap, source_rect.y1 - span, source_rect.x1 + gap + thickness, source_rect.y1),
            fitz.Rect(source_rect.x0 - gap - thickness, source_rect.y1 - span, source_rect.x0 - gap, source_rect.y1),
        )
    else:
        width = min(max(34.0, font.text_length(translated, fontsize=font_size) + 5.0), page_rect.width * 0.16)
        height = max(font_size * 1.45, _text_height(translated, width - 3.0, font, font_size, line_gap=1.12) + 1.5)
        # Two extra side candidates make title-block rows and labels embedded
        # in linework placeable without falling back to a distant blank margin.
        candidates = (
            fitz.Rect(source_rect.x0, source_rect.y1 + gap, source_rect.x0 + width, source_rect.y1 + gap + height),
            fitz.Rect(source_rect.x0, source_rect.y0 - gap - height, source_rect.x0 + width, source_rect.y0 - gap),
            fitz.Rect(source_rect.x1 - width, source_rect.y1 + gap, source_rect.x1, source_rect.y1 + gap + height),
            fitz.Rect(source_rect.x1 - width, source_rect.y0 - gap - height, source_rect.x1, source_rect.y0 - gap),
            fitz.Rect(source_rect.x1 + gap, source_rect.y0, source_rect.x1 + gap + width, source_rect.y0 + height),
            fitz.Rect(source_rect.x0 - gap - width, source_rect.y0, source_rect.x0 - gap, source_rect.y0 + height),
            fitz.Rect(source_rect.x1 + gap, source_rect.y1 - height, source_rect.x1 + gap + width, source_rect.y1),
            fitz.Rect(source_rect.x0 - gap - width, source_rect.y1 - height, source_rect.x0 - gap, source_rect.y1),
        )
    for candidate in candidates:
        if _is_clear(candidate, occupied, page_rect):
            return candidate, font_size, gap
    return None


def _safe_inline_region(region: dict) -> bool:
    """Suppress speculative OCR rather than placing an incorrect caption."""
    flags = {str(flag) for flag in (region.get("qa_flags") or [])}
    blocked = {
        "manual_review_required",
        "deepseek_ocr_conflict",
        "low_paddle_confidence",
        "ai_qa_missing",
        "ai_translation_missing",
        "missing_chinese_companion",
    }
    return str(region.get("action") or "") != "review" and not flags.intersection(blocked)


def render_bilingual_inline_only(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    regions: Iterable[dict],
    font_path: Path | None = None,
) -> EngineeringRenderResult:
    """Render a single-page, unnumbered original-plus-Chinese drawing.

    This mode intentionally never adds a reference page or numbered anchor. It
    is suitable for a visually calm client-facing sample; untranslated literal
    codes remain on the source drawing and are retained in the audit JSON.
    """
    source_pdf_path = Path(source_pdf_path)
    output_pdf_path = Path(output_pdf_path)
    selected_font_path = _font_path(font_path)
    font = fitz.Font(fontfile=str(selected_font_path))
    source = fitz.open(source_pdf_path)
    by_page = _regions_by_page(_regions_for_normalized_source(regions, source))
    _normalize_source_page_rotations(source)
    output = fitz.open()
    placed = unplaced = 0
    placement_audit: list[dict] = []
    try:
        for page_index, source_page in enumerate(source):
            page = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
            page.show_pdf_page(page.rect, source, page_index)
            page_regions = by_page.get(page_index, [])
            # Use the native source text geometry as a hard collision boundary.
            # We intentionally do not inspect every CAD vector path: it is both
            # expensive and too conservative on dense drawings.  Visual-OCR
            # bboxes fill the gap for outlines / raster labels.
            # Do not turn every OCR observation into an obstacle.  The same
            # source label is often observed by native extraction, full-page
            # OCR and overlapping tiles; treating all those bboxes as occupied
            # was the reason a prior release silently lost dense labels.  The
            # page's actual selectable text plus accepted Chinese captions are
            # the collision boundary; vector-only labels are protected by their
            # own source rectangle below.
            occupied = [rect for rect in _source_text_rects(source_page) if rect.is_valid]
            for region in page_regions:
                source_rect = _valid_bbox(region)
                translated = _compact_inline_text(_translated_text(region))
                rotation = _rotation(region)
                audit_entry = {
                    "region_id": str(region.get("region_id") or ""),
                    "page_index": page_index,
                    "source_text": _source_text(region),
                    "source_bbox": list(source_rect) if source_rect is not None else [],
                    "rotation": rotation,
                    "status": "rejected_invalid",
                    "target_bbox": [],
                    "distance": None,
                }
                if not _safe_inline_region(region):
                    audit_entry["status"] = "rejected_unverified_ocr"
                    placement_audit.append(audit_entry)
                    unplaced += 1
                    continue
                if source_rect is None or not translated:
                    placement_audit.append(audit_entry)
                    unplaced += 1
                    continue
                candidate = _inline_only_rect(
                    source_rect,
                    translated=translated,
                    page_rect=page.rect,
                    occupied=occupied,
                    font=font,
                    rotation=rotation,
                )
                if candidate is None:
                    audit_entry["status"] = "rejected_no_near_space"
                    placement_audit.append(audit_entry)
                    unplaced += 1
                    continue
                rect, font_size, distance = candidate
                inserted = _insert_textbox_fitted(
                    page,
                    rect,
                    translated,
                    font_path=selected_font_path,
                    font_size=font_size,
                    min_font_size=2.2,
                    color=(0.08, 0.20, 0.58),
                    rotate=rotation,
                )
                if inserted < 0:
                    audit_entry["status"] = "rejected_text_did_not_fit"
                    placement_audit.append(audit_entry)
                    unplaced += 1
                    continue
                occupied.append(rect)
                audit_entry.update(
                    {
                        "status": "inline_near",
                        "target_bbox": list(rect),
                        "distance": round(distance, 3),
                    }
                )
                placement_audit.append(audit_entry)
                placed += 1
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_pdf_path, garbage=4, deflate=True)
        output_pdf_path.with_suffix(".inline-placement.json").write_text(
            json.dumps({"placements": placement_audit}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    finally:
        output.close()
        source.close()
    return EngineeringRenderResult(
        output_pdf_path=output_pdf_path,
        pages_rendered=len(by_page),
        inline_placements=placed,
        sidebar_placements=0,
        review_items=unplaced,
    )


def render_bilingual_overlay(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    regions: Iterable[dict],
    font_path: Path | None = None,
) -> EngineeringRenderResult:
    source_pdf_path = Path(source_pdf_path)
    output_pdf_path = Path(output_pdf_path)
    selected_font_path = _font_path(font_path)
    font = fitz.Font(fontfile=str(selected_font_path))
    source = fitz.open(source_pdf_path)
    by_page = _regions_by_page(_regions_for_normalized_source(regions, source))
    _normalize_source_page_rotations(source)
    page_count = source.page_count
    output = fitz.open()
    inline_count = 0
    reference_count = 0
    reference_pages = 0
    review_count = 0
    reference_map: list[dict] = []
    try:
        for page_index, source_page in enumerate(source):
            page_regions = by_page.get(page_index, [])
            # Approval CAD samples deliberately use numbered reference cards.
            # Scanning every vector primitive merely to search inline space is
            # prohibitively expensive on dense sheets (hundreds of thousands of
            # paths) and serves no purpose when no inline placement is allowed.
            has_inline_candidate = any(not _reference_requested(region) for region in page_regions)
            occupied = _occupied_rects(source_page) if has_inline_candidate else []
            inline: list[tuple[dict, fitz.Rect, float]] = []
            reference_regions: list[dict] = []
            for region in page_regions:
                source_rect = _valid_bbox(region)
                candidate = (
                    _inline_candidate(
                        source_rect=source_rect,
                        translated=_translated_text(region),
                        page_rect=source_page.rect,
                        occupied=occupied,
                        font=font,
                    )
                    if source_rect is not None and not _reference_requested(region)
                    else None
                )
                if candidate is None:
                    reference_regions.append(region)
                else:
                    rect, size = candidate
                    inline.append((region, rect, size))
                    occupied.append(rect)
                if str(region.get("action", "")) == "review" or region.get("qa_flags"):
                    review_count += 1

            page = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
            page.show_pdf_page(page.rect, source, page_index)
            for region, rect, size in inline:
                inserted = _insert_textbox_fitted(
                    page,
                    rect,
                    _translated_text(region),
                    font_path=selected_font_path,
                    font_size=size,
                    fill=(0.96, 0.98, 1.0),
                )
                if inserted < 0:
                    reference_regions.append(region)
                else:
                    inline_count += 1

            # Hundreds of reference labels on a CAD sheet destroy its legibility.
            # Dense pages therefore receive an immediately following indexed copy
            # of the source page: the original stays truly 1:1 and clean, while
            # every reference still has a visible, clickable source number.
            anchor_page = page
            anchor_page_index = page.number
            if len(reference_regions) > _REFERENCE_INDEX_THRESHOLD:
                anchor_page = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
                anchor_page.show_pdf_page(anchor_page.rect, source, page_index)
                anchor_page_index = anchor_page.number
                _insert_textbox_fitted(
                    anchor_page,
                    fitz.Rect(8, 8, min(anchor_page.rect.width - 8, 180), 22),
                    "中文引用定位索引页",
                    font_path=selected_font_path,
                    font_size=6.0,
                    min_font_size=5.0,
                    color=(0.65, 0.08, 0.05),
                    fill=(1.0, 1.0, 0.90),
                )
                reference_pages += 1
            anchor_occupied = occupied + [rect for _region, rect, _size in inline]
            if len(reference_regions) > _REFERENCE_INDEX_THRESHOLD:
                # The original source page is already preserved cleanly. The
                # indexed copy may use compact anchor fallbacks without walking
                # every CAD vector collision box again.
                anchor_occupied = []
            entries: list[dict] = []
            for number, region in enumerate(reference_regions, start=1):
                source_rect = _valid_bbox(region)
                if source_rect is None:
                    continue
                anchor = _anchor_rect(source_rect, page_rect=source_page.rect, occupied=anchor_occupied)
                anchor_occupied.append(anchor)
                label = _reference_label(number)
                _draw_reference_anchor(anchor_page, rect=anchor, label=label, font_path=selected_font_path)
                entries.append(
                    {
                        "reference_id": f"P{page_index + 1:03d}-R{number:03d}",
                        "label": label,
                        "region": region,
                        "anchor_rect": anchor,
                    }
                )
            page_reference_pages, page_reference_map = _render_reference_pages(
                output,
                source_output_page_index=anchor_page_index,
                source_page_number=page_index + 1,
                source_rect=source_page.rect,
                entries=entries,
                font=font,
                font_path=selected_font_path,
            )
            reference_count += len(entries)
            reference_pages += page_reference_pages
            reference_map.extend(page_reference_map)
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_pdf_path, garbage=4, deflate=True, clean=True)
    finally:
        output.close()
        source.close()
    reference_map_path = output_pdf_path.with_suffix(".reference-map.json")
    _verify_reference_links(output_pdf_path, reference_map)
    reference_map_path.write_text(
        json.dumps({"references": reference_map}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return EngineeringRenderResult(
        output_pdf_path,
        page_count,
        inline_count,
        reference_count,
        review_count,
        reference_pages=reference_pages,
        reference_items=reference_count,
        reference_map_path=reference_map_path,
    )


def _rotation(region: dict) -> int:
    try:
        value = int(round(float(region.get("rotation", 0) or 0))) % 360
    except (TypeError, ValueError):
        return 0
    return value if value in {0, 90, 180, 270} else 0


def render_source_chinese_dual(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    regions: Iterable[dict],
    font_path: Path | None = None,
) -> EngineeringRenderResult:
    """Render a source/Chinese comparison without redacting a tight CAD textbox.

    The old implementation copied the drawing to the right, erased a source box
    and attempted to squeeze Chinese into its original geometry.  A failed fit
    left a blank patch.  The right side is now a clean numbered Chinese reference
    panel: it is more legible, never changes the left source drawing, and can
    continue onto additional dual pages when the panel fills.
    """
    source_pdf_path = Path(source_pdf_path)
    output_pdf_path = Path(output_pdf_path)
    selected_font_path = _font_path(font_path)
    font = fitz.Font(fontfile=str(selected_font_path))
    source = fitz.open(source_pdf_path)
    by_page = _regions_by_page(_regions_for_normalized_source(regions, source))
    _normalize_source_page_rotations(source)
    page_count = source.page_count
    output = fitz.open()
    placed = 0
    reference_pages = 0
    review_count = 0
    reference_map: list[dict] = []
    try:
        for page_index, source_page in enumerate(source):
            width, height = source_page.rect.width, source_page.rect.height
            page_regions = by_page.get(page_index, [])
            # The dual format always uses a separate reference panel, so it
            # never needs an expensive CAD-vector occupancy scan for inline text.
            source_occupied: list[fitz.Rect] = []
            entries: list[dict] = []
            for number, region in enumerate(page_regions, start=1):
                source_rect = _valid_bbox(region)
                if source_rect is None:
                    review_count += 1
                    continue
                entries.append(
                    {
                        "reference_id": f"P{page_index + 1:03d}-R{number:03d}",
                        "label": _reference_label(number),
                        "region": region,
                        "source_rect": source_rect,
                    }
                )
                if str(region.get("action", "")) == "review" or region.get("qa_flags"):
                    review_count += 1

            def new_dual_page(*, continuation: int) -> fitz.Page:
                page = output.new_page(width=width * 2 + 8.0, height=height)
                page.show_pdf_page(fitz.Rect(0, 0, width, height), source, page_index)
                page.draw_line((width + 4.0, 0), (width + 4.0, height), color=(0.5, 0.5, 0.5), width=0.5)
                right_rect = fitz.Rect(width + 8.0, 0, width * 2 + 8.0, height)
                page.draw_rect(
                    right_rect,
                    color=(0.76, 0.80, 0.88),
                    fill=(0.985, 0.99, 1.0),
                    width=0.35,
                    overlay=True,
                )
                _insert_textbox_fitted(
                    page,
                    fitz.Rect(width + 8.0 + _REFERENCE_MARGIN, _REFERENCE_MARGIN, width * 2 + 8.0 - _REFERENCE_MARGIN, _REFERENCE_MARGIN + _REFERENCE_HEADER_HEIGHT - 4),
                    f"源图第 {page_index + 1} 页 · 中文对照索引（编号对应左侧原图）" + (f" · 续 {continuation}" if continuation else ""),
                    font_path=selected_font_path,
                    font_size=10.0,
                    min_font_size=8.0,
                    color=(0.04, 0.12, 0.30),
                )
                return page

            first_page = new_dual_page(continuation=0)
            first_page_index = first_page.number
            anchor_occupied = list(source_occupied)
            for entry in entries:
                anchor = _anchor_rect(
                    entry["source_rect"],
                    page_rect=fitz.Rect(0, 0, width, height),
                    occupied=anchor_occupied,
                )
                anchor_occupied.append(anchor)
                entry["anchor_rect"] = anchor
                _draw_reference_anchor(first_page, rect=anchor, label=entry["label"], font_path=selected_font_path)

            columns = 3 if width >= height else 2
            column_width = (width - 2 * _REFERENCE_MARGIN - (columns - 1) * _REFERENCE_GUTTER) / columns
            right_origin = width + 8.0
            top = _REFERENCE_MARGIN + _REFERENCE_HEADER_HEIGHT
            bottom = height - _REFERENCE_MARGIN - _REFERENCE_FOOTER_HEIGHT
            page = first_page
            current_x = right_origin + _REFERENCE_MARGIN
            current_y = top
            column = 0
            continuation = 0
            for entry in entries:
                card_height, source_height, target_height = _reference_card_measure(
                    entry,
                    font=font,
                    width=column_width - 10,
                )
                if current_y + card_height > bottom and current_y > top:
                    column += 1
                    current_x += column_width + _REFERENCE_GUTTER
                    current_y = top
                if column >= columns:
                    continuation += 1
                    page = new_dual_page(continuation=continuation)
                    reference_pages += 1
                    current_x = right_origin + _REFERENCE_MARGIN
                    current_y = top
                    column = 0
                card_rect = fitz.Rect(current_x, current_y, current_x + column_width, min(bottom, current_y + card_height))
                complete = _draw_reference_card(
                    page,
                    card_rect=card_rect,
                    entry=entry,
                    source_height=source_height,
                    target_height=target_height,
                    font_path=selected_font_path,
                )
                if not complete:
                    review_count += 1
                source_page_for_link = output[first_page_index]
                source_page_for_link.insert_link(
                    {
                        "kind": fitz.LINK_GOTO,
                        "from": entry["anchor_rect"],
                        "page": page.number,
                        "to": fitz.Point(card_rect.x0, card_rect.y0),
                    }
                )
                page.insert_link(
                    {
                        "kind": fitz.LINK_GOTO,
                        "from": card_rect,
                        "page": first_page_index,
                        "to": fitz.Point(entry["anchor_rect"].x0, entry["anchor_rect"].y0),
                    }
                )
                reference_map.append(
                    {
                        "reference_id": entry["reference_id"],
                        "display_label": entry["label"],
                        "region_id": entry["region"].get("region_id", ""),
                        "source_page_number": page_index + 1,
                        "source_output_page": first_page_index + 1,
                        "anchor_bbox": list(entry["anchor_rect"]),
                        "reference_output_page": page.number + 1,
                        "reference_card_bbox": list(card_rect),
                        "complete_text_fit": complete,
                        "link_verified": False,
                    }
                )
                placed += 1
                current_y = card_rect.y1 + 5.0

        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_pdf_path, garbage=4, deflate=True, clean=True)
    finally:
        output.close()
        source.close()
    reference_map_path = output_pdf_path.with_suffix(".reference-map.json")
    _verify_reference_links(output_pdf_path, reference_map)
    reference_map_path.write_text(
        json.dumps({"references": reference_map}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return EngineeringRenderResult(
        output_pdf_path,
        page_count,
        0,
        placed,
        review_count,
        reference_pages=reference_pages,
        reference_items=placed,
        reference_map_path=reference_map_path,
    )
