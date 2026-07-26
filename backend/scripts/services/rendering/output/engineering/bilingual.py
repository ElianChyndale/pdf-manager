from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import fitz


_BACKEND_DIR = Path(__file__).resolve().parents[5]
_DEFAULT_FONT_PATH = _BACKEND_DIR / "fonts" / "SourceHanSerifSC-Regular.otf"
_FONT_NAME = "engineering_zh"
_SIDEBAR_COLUMN_WIDTH = 190.0
_SIDEBAR_GUTTER = 12.0
_MIN_FONT_SIZE = 5.5


@dataclass(frozen=True)
class EngineeringRenderResult:
    output_pdf_path: Path
    pages_rendered: int
    inline_placements: int
    sidebar_placements: int
    review_items: int


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
        if str(region.get("action", "translate") or "translate") == "keep_literal":
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
    by_page = _regions_by_page(regions)
    source = fitz.open(source_pdf_path)
    _normalize_source_page_rotations(source)
    page_count = source.page_count
    output = fitz.open()
    inline_count = 0
    sidebar_count = 0
    review_count = 0
    try:
        for page_index, source_page in enumerate(source):
            page_regions = by_page.get(page_index, [])
            occupied = _occupied_rects(source_page)
            inline: list[tuple[dict, fitz.Rect, float]] = []
            sidebar: list[dict] = []
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
                    if source_rect is not None
                    else None
                )
                if candidate is None:
                    sidebar.append(region)
                else:
                    rect, size = candidate
                    inline.append((region, rect, size))
                    occupied.append(rect)
                if str(region.get("action", "")) == "review" or region.get("qa_flags"):
                    review_count += 1

            columns, _heights = _sidebar_layout(sidebar, page_height=source_page.rect.height, font=font) if sidebar else (0, [])
            sidebar_width = columns * _SIDEBAR_COLUMN_WIDTH if sidebar else 0.0
            page = output.new_page(width=source_page.rect.width + sidebar_width, height=source_page.rect.height)
            page.show_pdf_page(fitz.Rect(0, 0, source_page.rect.width, source_page.rect.height), source, page_index)
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
                    sidebar.append(region)
                else:
                    inline_count += 1
            if sidebar:
                _draw_sidebar(
                    page,
                    source_width=source_page.rect.width,
                    regions=sidebar,
                    font_path=selected_font_path,
                    font=font,
                    heading=f"第 {page_index + 1} 页中文伴随项（坐标对应原图）",
                )
                sidebar_count += len(sidebar)
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_pdf_path, garbage=4, deflate=True, clean=True)
    finally:
        output.close()
        source.close()
    return EngineeringRenderResult(output_pdf_path, page_count, inline_count, sidebar_count, review_count)


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
    source_pdf_path = Path(source_pdf_path)
    output_pdf_path = Path(output_pdf_path)
    selected_font_path = _font_path(font_path)
    by_page = _regions_by_page(regions)
    source = fitz.open(source_pdf_path)
    _normalize_source_page_rotations(source)
    page_count = source.page_count
    output = fitz.open()
    placed = 0
    review_count = 0
    try:
        for page_index, source_page in enumerate(source):
            width, height = source_page.rect.width, source_page.rect.height
            page = output.new_page(width=width * 2 + 8.0, height=height)
            page.show_pdf_page(fitz.Rect(0, 0, width, height), source, page_index)
            page.show_pdf_page(fitz.Rect(width + 8.0, 0, width * 2 + 8.0, height), source, page_index)
            page.draw_line((width + 4.0, 0), (width + 4.0, height), color=(0.5, 0.5, 0.5), width=0.5)

            page_regions = by_page.get(page_index, [])
            for region in page_regions:
                rect = _valid_bbox(region)
                if rect is None:
                    review_count += 1
                    continue
                target = fitz.Rect(rect.x0 + width + 8.0, rect.y0, rect.x1 + width + 8.0, rect.y1)
                page.add_redact_annot(target, fill=None, cross_out=False)
            if page_regions:
                page.apply_redactions(images=0, graphics=0, text=0)
            for region in page_regions:
                rect = _valid_bbox(region)
                if rect is None:
                    continue
                target = fitz.Rect(rect.x0 + width + 8.0, rect.y0, rect.x1 + width + 8.0, rect.y1)
                source_size = max(_MIN_FONT_SIZE, min(10.0, max(6.0, rect.height * 0.72)))
                inserted = _insert_textbox_fitted(
                    page,
                    target,
                    _translated_text(region),
                    font_path=selected_font_path,
                    font_size=source_size,
                    rotate=_rotation(region),
                    color=(0.02, 0.08, 0.22),
                )
                if inserted < 0:
                    review_count += 1
                else:
                    placed += 1
                if str(region.get("action", "")) == "review" or region.get("qa_flags"):
                    review_count += 1

        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_pdf_path, garbage=4, deflate=True, clean=True)
    finally:
        output.close()
        source.close()
    return EngineeringRenderResult(output_pdf_path, page_count, placed, 0, review_count)
