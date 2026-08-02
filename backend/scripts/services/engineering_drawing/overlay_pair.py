from __future__ import annotations

from pathlib import Path
import re
from difflib import SequenceMatcher
from typing import Iterable, Mapping

import fitz

from .fonts.resolve import resolve_cjk_font

# Deprecated alias kept for import compatibility; the V4 render path resolves
# the bundled project font via fonts.resolve (never the hardcoded Windows path).
SIMHEI = Path(r"C:\Windows\Fonts\simhei.ttf")


def _normalized_tokens(value: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Z0-9]+", str(value or "").upper())
        if len(token) > 1
    }


def _matched_ocr_rects(
    *,
    source_text: str,
    fallback: fitz.Rect,
    ocr_regions: Iterable[Mapping[str, object]],
) -> list[fitz.Rect]:
    source_tokens = _normalized_tokens(source_text)
    normalized_source = " ".join(sorted(source_tokens))
    matches: list[tuple[float, fitz.Rect]] = []
    for region in ocr_regions:
        bbox = region.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        rect = fitz.Rect([float(value) for value in bbox])
        if rect.is_empty or not (rect & fallback).get_area():
            continue
        candidate_text = str(region.get("source_text") or "").strip()
        candidate_tokens = _normalized_tokens(candidate_text)
        if not candidate_tokens:
            continue
        if re.search(
            r"^\s*(?:\d+[\.\)]?|A[0-4]|ACASB/[A-Z0-9/\-]+)\s*$",
            candidate_text,
            re.I,
        ):
            continue
        if (
            len(source_text) > 120
            and re.search(r"[A-Za-z]", candidate_text)
        ):
            matches.append((0.46, rect))
            continue
        overlap = len(source_tokens & candidate_tokens) / max(1, len(candidate_tokens))
        similarity = SequenceMatcher(
            None,
            normalized_source,
            " ".join(sorted(candidate_tokens)),
        ).ratio()
        score = max(overlap, similarity)
        if score >= 0.45:
            matches.append((score, rect))
    if not matches:
        return []
    return [rect for score, rect in matches if score >= 0.45]


def _table_grid(page: fitz.Page) -> tuple[list[float], tuple[float, float], tuple[float, float]]:
    horizontal: list[float] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue
            start, end = item[1], item[2]
            if (
                abs(start.y - end.y) <= 0.2
                and abs(start.x - end.x) >= 450
                and 220 <= start.y <= 810
            ):
                horizontal.append(round(float(start.y), 2))
    return (
        sorted(set(horizontal)),
        (109.18, 419.10),
        (660.34, 970.25),
    )


def _grid_cell_rect(
    *,
    ink_union: fitz.Rect,
    semantic_scope: fitz.Rect,
    horizontal: list[float],
    left_title_column: tuple[float, float],
    right_title_column: tuple[float, float],
) -> fitz.Rect | None:
    center_x = (ink_union.x0 + ink_union.x1) / 2
    center_y = (ink_union.y0 + ink_union.y1) / 2
    if center_y < 249.8 or center_y > 802:
        return None
    column = left_title_column if center_x < 600 else right_title_column
    boundary_basis = semantic_scope if semantic_scope.height > 18 else ink_union
    above = [value for value in horizontal if value <= boundary_basis.y0 + 1.5]
    below = [value for value in horizontal if value >= boundary_basis.y1 - 1.5]
    if not above or not below:
        return None
    top = max(above)
    bottom = min(below)
    if bottom <= top:
        below = [value for value in horizontal if value > top + 0.5]
        if not below:
            return None
        bottom = min(below)
    return fitz.Rect(column[0], top, column[1], bottom)


def _insert_fit(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    fontname: str,
    start_size: float,
    minimum_size: float,
    align: int = 0,
    rotate: int = 0,
) -> bool:
    if fontname == "simhei":
        page.insert_font(fontname="simhei", fontfile=str(resolve_cjk_font()))
    size = start_size
    while size >= minimum_size:
        result = page.insert_textbox(
            rect,
            text,
            fontname=fontname,
            fontsize=size,
            color=(0.0, 0.0, 0.0),
            lineheight=1.0,
            align=align,
            rotate=rotate,
            overlay=True,
        )
        if result >= 0:
            return True
        size -= 0.2
    return False


def render_opaque_translation_companion(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    semantic_blocks: Iterable[Mapping[str, object]],
    ocr_regions: Iterable[Mapping[str, object]] = (),
    include_source_text: bool = True,
) -> dict:
    """Cover indexed source text and write Chinese in the same table cells.

    This renderer is intentionally limited to pages whose supervisor selected
    ``overlay_pair``. The untouched source PDF remains the authoritative
    comparison copy.
    """
    document = fitz.open(Path(source_pdf_path))
    rendered = 0
    unmatched: list[str] = []
    failed_layout: list[str] = []
    ocr_regions = [dict(item) for item in ocr_regions]
    for block in semantic_blocks:
        page_index = int(block.get("page_index", 0) or 0)
        if page_index < 0 or page_index >= document.page_count:
            continue
        bbox = block.get("source_bbox")
        translated = str(block.get("translated_text") or "").strip()
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not translated:
            continue
        page = document[page_index]
        horizontal, left_title_column, right_title_column = _table_grid(page)
        rect = fitz.Rect([float(value) for value in bbox])
        rect &= page.rect
        if rect.is_empty:
            continue
        ink_rects = _matched_ocr_rects(
            source_text=str(block.get("source_text") or ""),
            fallback=rect,
            ocr_regions=ocr_regions,
        )
        placement = block.get("placement")
        preserve_source = bool(
            isinstance(placement, Mapping) and placement.get("preserve_source")
        )
        if not ink_rects and not preserve_source:
            unmatched.append(str(block.get("block_id") or ""))
            continue
        if preserve_source:
            ink_union = fitz.Rect(rect)
        else:
            for ink_rect in ink_rects:
                mask = fitz.Rect(
                    max(page.rect.x0, ink_rect.x0 - 0.8),
                    max(page.rect.y0, ink_rect.y0 - 0.45),
                    min(page.rect.x1, ink_rect.x1 + 0.8),
                    min(page.rect.y1, ink_rect.y1 + 0.45),
                )
                page.draw_rect(mask, color=None, fill=(1, 1, 1), overlay=True)
            ink_union = fitz.Rect(ink_rects[0])
            for ink_rect in ink_rects[1:]:
                ink_union |= ink_rect
        requested = (
            float(placement.get("font_size", 4.0))
            if isinstance(placement, Mapping)
            else 4.0
        )
        # Plan font sizes are authored against an A3 reference sheet. Scale
        # them for A2/A1 sheets so a correct cell-level reflow does not become
        # unreadable merely because the physical page is larger.
        page_scale = max(
            1.0,
            min(2.5, max(page.rect.width / 841.89, page.rect.height / 1190.55)),
        )
        # Index rows are read as a comparison document, so use normal black
        # drafting text and fill more of the row height than inline captions.
        # Keep a small inset so table borders remain intact.
        cell_rect = _grid_cell_rect(
            ink_union=ink_union,
            semantic_scope=rect,
            horizontal=horizontal,
            left_title_column=left_title_column,
            right_title_column=right_title_column,
        )
        selected_region = (
            placement.get("selected_region")
            if isinstance(placement, Mapping)
            else None
        )
        if preserve_source and isinstance(selected_region, (list, tuple)) and len(selected_region) == 4:
            target = fitz.Rect([float(value) for value in selected_region]) & page.rect
        else:
            target = cell_rect or fitz.Rect(
                rect.x0,
                max(rect.y0, ink_union.y0 - 0.8),
                rect.x1,
                min(rect.y1, max(ink_union.y1 + 1.2, ink_union.y0 + 18.0)),
            )
        if include_source_text and not preserve_source:
            clear_rect = fitz.Rect(
                target.x0 + 0.55,
                target.y0 + 0.55,
                target.x1 - 0.55,
                target.y1 - 0.55,
            )
            page.draw_rect(clear_rect, color=None, fill=(1, 1, 1), overlay=True)
        text_rect = fitz.Rect(
            target.x0 + 2.2,
            target.y0 + 0.7,
            target.x1 - 2.2,
            target.y1 - 0.6,
        )
        # The source detector may return a box spanning more than one visual
        # row. Do not derive an unbounded font size from that height.
        font_size = max(
            4.6 * page_scale,
            min(
                6.0 * page_scale,
                (requested + 2.15) * page_scale,
                max(4.6 * page_scale, text_rect.height * 0.58),
            ),
        )
        source_text = str(block.get("source_text") or "").strip()
        typography = block.get("typography")
        if not isinstance(typography, Mapping):
            typography = {}
        is_emphasized = bool(
            typography.get("bold")
            or typography.get("font_weight") == "bold"
            or typography.get("semantic_role") in {"section_heading", "category_heading"}
            or (
                len(source_text) <= 48
                and source_text == source_text.upper()
                and any(character.isalpha() for character in source_text)
                and not re.match(r"^(?:ACASB|A[0-4])", source_text)
            )
        )
        if is_emphasized:
            font_size = min(7.2 * page_scale, font_size + 0.9 * page_scale)
        alignment = str(typography.get("alignment") or "left").casefold()
        fitz_align = 1 if alignment == "center" else 2 if alignment == "right" else 0
        rotation = (
            int(placement.get("rotation", 0) or 0) % 360
            if isinstance(placement, Mapping)
            else 0
        )
        if include_source_text and not preserve_source:
            if text_rect.height >= 18:
                split_y = text_rect.y0 + text_rect.height * 0.56
                source_rect = fitz.Rect(text_rect.x0, text_rect.y0, text_rect.x1, split_y)
                chinese_rect = fitz.Rect(text_rect.x0, split_y, text_rect.x1, text_rect.y1)
            else:
                source_weight = max(0.56, min(0.78, len(source_text) / max(1, len(source_text) + len(translated) * 1.7)))
                split_x = text_rect.x0 + text_rect.width * source_weight
                source_rect = fitz.Rect(text_rect.x0, text_rect.y0, split_x - 1.0, text_rect.y1)
                chinese_rect = fitz.Rect(split_x + 1.0, text_rect.y0, text_rect.x1, text_rect.y1)
            source_ok = _insert_fit(
                page,
                source_rect,
                source_text,
                fontname="hebo" if is_emphasized else "helv",
                start_size=min(
                    font_size,
                    (5.8 if is_emphasized else 4.8) * page_scale,
                ),
                minimum_size=2.7 * page_scale,
                align=fitz_align,
                rotate=rotation,
            )
            chinese_ok = _insert_fit(
                page,
                chinese_rect,
                translated,
                fontname="simhei",
                start_size=font_size,
                minimum_size=3.0 * page_scale,
                align=fitz_align,
                rotate=rotation,
            )
            placed = source_ok and chinese_ok
        elif preserve_source:
            placed = _insert_fit(
                page,
                text_rect,
                translated,
                fontname="simhei",
                start_size=font_size,
                minimum_size=3.0 * page_scale,
                align=fitz_align,
                rotate=rotation,
            )
            if not placed:
                page.draw_rect(clear_rect, color=None, fill=(1, 1, 1), overlay=True)
                placed = _insert_fit(
                    page,
                    text_rect,
                    f"{source_text} / {translated}",
                    fontname="simhei",
                    start_size=min(3.4, font_size),
                    minimum_size=2.6,
                )
        else:
            placed = _insert_fit(
                page,
                text_rect,
                translated,
                fontname="simhei",
                start_size=font_size,
                minimum_size=3.0,
            )
        if placed:
            rendered += 1
        else:
            failed_layout.append(str(block.get("block_id") or ""))
    output_pdf_path = Path(output_pdf_path)
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_pdf_path, garbage=3, deflate=True)
    document.close()
    return {
        "source_pdf": str(Path(source_pdf_path).resolve()),
        "translated_companion_pdf": str(output_pdf_path.resolve()),
        "rendered_blocks": rendered,
        "unmatched_block_ids": [item for item in unmatched if item],
        "failed_layout_block_ids": [item for item in failed_layout if item],
        "delivery_mode": (
            "opaque_bilingual_reflow" if include_source_text else "overlay_pair"
        ),
    }


def render_planned_opaque_blocks(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    semantic_blocks: Iterable[Mapping[str, object]],
    ocr_regions: Iterable[Mapping[str, object]] = (),
    strict_execution: bool = False,
) -> dict:
    """Reflow supervisor-declared title/table panels without touching drawings.

    Unlike the drawing-index renderer above, this function trusts the
    multimodal supervisor's exact selected layout rectangles.  Only OCR text
    ink inside ``source_bbox`` is erased; ``selected_region`` is never used as
    a white mask.  This distinction preserves logos, borders, dividers and
    drawing geometry while still allowing the supervisor to reflow the
    bilingual text into a larger part of the same field.
    """
    document = fitz.open(Path(source_pdf_path))
    rendered = 0
    failed: list[str] = []
    semantic_blocks = [dict(item) for item in semantic_blocks]
    ocr_regions = [dict(item) for item in ocr_regions]
    try:
        # Erase every declared source glyph before inserting any replacement
        # text.  Rendering one field at a time allows a later exact glyph mask
        # to cut through an earlier field's reflow where title-panel lanes are
        # vertically adjacent.  This two-pass order keeps the mask scope just
        # as narrow while eliminating those white strike marks.
        for raw in semantic_blocks:
            block = dict(raw)
            placement = block.get("placement") or {}
            if strict_execution and bool(placement.get("preserve_source")):
                continue
            page_index = int(block.get("page_index", 0) or 0)
            source_bbox_value = block.get("source_bbox")
            if (
                page_index < 0
                or page_index >= document.page_count
                or not isinstance(source_bbox_value, (list, tuple))
                or len(source_bbox_value) != 4
            ):
                continue
            page = document[page_index]
            source_bbox = fitz.Rect(
                [float(value) for value in source_bbox_value]
            ) & page.rect
            if source_bbox.is_empty:
                continue
            page_ocr = [
                region
                for region in ocr_regions
                if int(region.get("page_index", 0) or 0) == page_index
            ]
            ink_rects = _matched_ocr_rects(
                source_text=str(block.get("source_text") or ""),
                fallback=source_bbox,
                ocr_regions=page_ocr,
            )
            exact_masks = (block.get("placement") or {}).get("exact_ink_masks") or []
            if exact_masks:
                inspected = [
                    fitz.Rect([float(value) for value in mask]) & page.rect
                    for mask in exact_masks
                    if isinstance(mask, (list, tuple)) and len(mask) == 4
                ]
                ink_rects = [rect for rect in inspected if not rect.is_empty]
            for ink_rect in ink_rects or [source_bbox]:
                # Supervisor rectangles are always display-page coordinates.
                # PyMuPDF drawing/text APIs operate in the unrotated page
                # coordinate system, so rotated sheets require the same
                # display -> derotation chain used by the inline renderer.
                native_ink_rect = ink_rect * page.derotation_matrix
                page.draw_rect(
                    fitz.Rect(
                        native_ink_rect.x0 - 0.20,
                        native_ink_rect.y0 - 0.45,
                        native_ink_rect.x1 + 0.20,
                        native_ink_rect.y1 + 0.45,
                    ),
                    color=None,
                    fill=(1, 1, 1),
                    overlay=True,
                )
        for raw in semantic_blocks:
            block = dict(raw)
            page_index = int(block.get("page_index", 0) or 0)
            if page_index < 0 or page_index >= document.page_count:
                failed.append(str(block.get("block_id") or ""))
                continue
            placement = block.get("placement")
            if not isinstance(placement, Mapping):
                failed.append(str(block.get("block_id") or ""))
                continue
            target_value = placement.get("selected_region")
            if not isinstance(target_value, (list, tuple)) or len(target_value) != 4:
                failed.append(str(block.get("block_id") or ""))
                continue
            page = document[page_index]
            target = fitz.Rect([float(value) for value in target_value]) & page.rect
            if target.is_empty or target.width < 8 or target.height < 6:
                failed.append(str(block.get("block_id") or ""))
                continue
            source_bbox_value = block.get("source_bbox")
            if (
                not isinstance(source_bbox_value, (list, tuple))
                or len(source_bbox_value) != 4
            ):
                failed.append(str(block.get("block_id") or ""))
                continue
            source_bbox = (
                fitz.Rect([float(value) for value in source_bbox_value]) & page.rect
            )
            if source_bbox.is_empty:
                failed.append(str(block.get("block_id") or ""))
                continue
            page_ocr = [
                region
                for region in ocr_regions
                if int(region.get("page_index", 0) or 0) == page_index
            ]
            text_rect = fitz.Rect(
                target.x0 + 1.4,
                target.y0 + 1.0,
                target.x1 - 1.4,
                target.y1 - 1.0,
            )
            source_text = str(
                placement.get("render_source_text")
                or block.get("source_text")
                or ""
            ).strip()
            translated = str(block.get("translated_text") or "").strip()
            if not source_text or not translated:
                failed.append(str(block.get("block_id") or ""))
                continue
            typography = block.get("typography")
            if not isinstance(typography, Mapping):
                typography = {}
            bold = bool(
                typography.get("bold")
                or typography.get("font_weight") == "bold"
                or typography.get("semantic_role")
                in {"section_heading", "category_heading", "table_header"}
            )
            alignment = str(typography.get("alignment") or "left").casefold()
            fitz_align = 1 if alignment == "center" else 2 if alignment == "right" else 0
            # Mixed-sheet supervisor plans use native PDF points, so do not
            # rescale them by sheet size here.  A1/A0 title panels are often
            # physically narrow even though the page canvas is large.
            page_scale = 1.0
            requested = float(placement.get("font_size") or 4.0)
            if strict_execution:
                render_runs = placement.get("render_runs") or []
                if render_runs:
                    runs_ok = True
                    for run in render_runs:
                        run_font = str(run.get("font_name") or "simhei")
                        if run_font not in {"simhei", "helv", "hebo"}:
                            runs_ok = False
                            break
                        if run_font == "simhei":
                            page.insert_font(fontname="simhei", fontfile=str(resolve_cjk_font()))
                        run_result = page.insert_textbox(
                            fitz.Rect(run["bbox"]) * page.derotation_matrix,
                            str(run["text"]),
                            fontname=run_font,
                            fontsize=float(run["font_size"]),
                            color=tuple(float(channel) for channel in run["color"]),
                            lineheight=float(run.get("lineheight") or 1.0),
                            align=int(run.get("align") or 0),
                            rotate=(int(run.get("rotation") or 0) + page.rotation) % 360,
                            overlay=True,
                        )
                        if run_result < 0:
                            runs_ok = False
                            break
                    if runs_ok:
                        rendered += 1
                    else:
                        failed.append(str(block.get("block_id") or ""))
                    continue
                preserve_source = bool(placement.get("preserve_source"))
                render_text = str(
                    placement.get("render_text")
                    or block.get("render_text")
                    or (translated if preserve_source else f"{source_text}\n{translated}")
                ).strip()
                fontname = str(placement.get("font_name") or "simhei")
                if fontname not in {"simhei", "helv", "hebo"}:
                    failed.append(str(block.get("block_id") or ""))
                    continue
                if fontname == "simhei":
                    page.insert_font(fontname="simhei", fontfile=str(resolve_cjk_font()))
                exact_color = placement.get("color") or placement.get("colour")
                if not isinstance(exact_color, (list, tuple)) or len(exact_color) != 3:
                    failed.append(str(block.get("block_id") or ""))
                    continue
                exact_result = page.insert_textbox(
                    target,
                    render_text,
                    fontname=fontname,
                    fontsize=requested,
                    color=tuple(float(channel) for channel in exact_color),
                    lineheight=float(placement.get("lineheight") or 1.0),
                    align=fitz_align,
                    rotate=int(placement.get("rotation") or 0),
                    overlay=True,
                )
                if exact_result >= 0:
                    rendered += 1
                else:
                    failed.append(str(block.get("block_id") or ""))
                continue
            layout_variant = str(placement.get("layout_variant") or "")
            if layout_variant == "sidebar_two_zone":
                # Company ledgers retain their original hierarchy in an upper
                # right source strip and place the concise complete Chinese
                # ledger in a distinct lower blank strip.  Do not silently
                # shrink this editorial content below the readable 3 pt gate.
                split_y = text_rect.y0 + text_rect.height * 0.46
                source_rect = fitz.Rect(text_rect.x0, text_rect.y0, text_rect.x1, split_y)
                chinese_rect = fitz.Rect(text_rect.x0, split_y + 0.8, text_rect.x1, text_rect.y1)
                source_ok = _insert_fit(
                    page, source_rect, source_text,
                    fontname="hebo" if bold else "helv",
                    start_size=max(3.0, requested * 0.95), minimum_size=3.0,
                    align=fitz_align,
                )
                chinese_ok = _insert_fit(
                    page, chinese_rect, translated, fontname="simhei",
                    start_size=max(3.0, requested), minimum_size=3.0,
                    align=fitz_align,
                )
            elif layout_variant == "cell_horizontal":
                split_x = text_rect.x0 + text_rect.width * 0.58
                source_rect = fitz.Rect(text_rect.x0, text_rect.y0, split_x - 0.6, text_rect.y1)
                chinese_rect = fitz.Rect(split_x + 0.6, text_rect.y0, text_rect.x1, text_rect.y1)
                source_ok = _insert_fit(
                    page, source_rect, source_text,
                    fontname="hebo" if bold else "helv",
                    start_size=max(3.0, requested * 0.92), minimum_size=2.8,
                    align=fitz_align,
                )
                chinese_ok = _insert_fit(
                    page, chinese_rect, translated, fontname="simhei",
                    start_size=max(3.0, requested), minimum_size=2.8,
                    align=fitz_align,
                )
            else:
                split_y = text_rect.y0 + text_rect.height * 0.52
                source_rect = fitz.Rect(text_rect.x0, text_rect.y0, text_rect.x1, split_y)
                chinese_rect = fitz.Rect(text_rect.x0, split_y, text_rect.x1, text_rect.y1)
                source_ok = _insert_fit(
                    page,
                    source_rect,
                    source_text,
                    fontname="hebo" if bold else "helv",
                    start_size=max(3.0 * page_scale, requested * 0.88),
                    minimum_size=1.8,
                    align=fitz_align,
                )
                chinese_ok = _insert_fit(
                    page,
                    chinese_rect,
                    translated,
                    fontname="simhei",
                    start_size=max(3.2 * page_scale, requested),
                    minimum_size=1.9,
                    align=fitz_align,
                )
            if not (source_ok and chinese_ok) and layout_variant not in {"sidebar_two_zone", "cell_horizontal"}:
                # Shallow rows and narrow side panels often read better as two
                # columns than two half-height lines.
                split_x = text_rect.x0 + text_rect.width * 0.55
                source_rect = fitz.Rect(
                    text_rect.x0, text_rect.y0, split_x - 0.8, text_rect.y1
                )
                chinese_rect = fitz.Rect(
                    split_x + 0.8, text_rect.y0, text_rect.x1, text_rect.y1
                )
                source_ok = _insert_fit(
                    page,
                    source_rect,
                    source_text,
                    fontname="hebo" if bold else "helv",
                    start_size=max(2.2, requested * 0.88),
                    minimum_size=1.8,
                    align=fitz_align,
                )
                chinese_ok = _insert_fit(
                    page,
                    chinese_rect,
                    translated,
                    fontname="simhei",
                    start_size=max(2.3, requested),
                    minimum_size=1.9,
                    align=fitz_align,
                )
            if source_ok and chinese_ok:
                rendered += 1
            else:
                failed.append(str(block.get("block_id") or ""))
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(output_pdf_path, garbage=4, deflate=True)
    finally:
        document.close()
    return {
        "source_pdf": str(Path(source_pdf_path).resolve()),
        "output_pdf": str(Path(output_pdf_path).resolve()),
        "rendered_blocks": rendered,
        "failed_block_ids": failed,
        "mode": "planned_opaque_panels",
        "strict_execution": strict_execution,
    }


__all__ = [
    "render_opaque_translation_companion",
    "render_planned_opaque_blocks",
]
