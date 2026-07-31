from __future__ import annotations

import json
from pathlib import Path
import math
from typing import Any

import fitz

SIMHEI = Path(r"C:\Windows\Fonts\simhei.ttf")


def company_panel_font_bounds(
    selected_region: list[float],
    *,
    text: str,
    batch_scale: float = 1.18,
) -> dict[str, float]:
    """Choose readable company-panel type from the actual usable whitespace."""

    rect = _rect(selected_region)
    usable_area = max(rect.width * rect.height, 1.0)
    glyph_count = max(len(str(text).strip()), 1)
    area_size = math.sqrt(usable_area / glyph_count) * 0.55 * batch_scale
    max_size = round(min(12.0, max(6.8, area_size)), 2)
    min_size = round(min(max_size, max(6.4, max_size * 0.78)), 2)
    return {
        "max_size": max_size,
        "min_size": min_size,
        "batch_scale": batch_scale,
        "usable_area": usable_area,
    }


def _rect(values: list[float]) -> fitz.Rect:
    if len(values) != 4:
        raise ValueError(f"Expected four rectangle coordinates, got {values!r}")
    return fitz.Rect(*map(float, values))


def _fit_textbox(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    fontname: str,
    max_size: float,
    min_size: float,
    lineheight: float,
    align: int = fitz.TEXT_ALIGN_LEFT,
) -> float:
    if fontname == "simhei":
        if not SIMHEI.exists():
            raise FileNotFoundError(f"Required CJK font not found: {SIMHEI}")
        page.insert_font(fontname="simhei", fontfile=str(SIMHEI))
    size = max_size
    while size >= min_size:
        shape = page.new_shape()
        spare = shape.insert_textbox(
            rect,
            text,
            fontname=fontname,
            fontsize=size,
            lineheight=lineheight,
            color=(0, 0, 0),
            align=align,
        )
        if spare >= 0:
            shape.commit(overlay=True)
            return size
        size = round(size - 0.2, 2)
    raise RuntimeError(
        f"Text did not fit in {tuple(round(v, 2) for v in rect)} at {min_size} pt: "
        f"{text[:100]!r}"
    )


def render_panel_reflow(
    source_pdf: str | Path,
    output_pdf: str | Path,
    specification: str | Path | dict[str, Any],
) -> dict[str, Any]:
    """Clear only approved text interiors and re-typeset black source + Chinese.

    The caller supplies exact clear rectangles. Borders, logos, identifiers and
    engineering graphics are therefore protected by construction rather than by
    OCR confidence.
    """

    if isinstance(specification, (str, Path)):
        spec = json.loads(Path(specification).read_text(encoding="utf-8"))
    else:
        spec = specification

    source_path = Path(source_pdf)
    output_path = Path(output_pdf)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(source_path)
    original_drawings: dict[int, list[dict[str, Any]]] = {}
    cleared_by_page: dict[int, list[fitz.Rect]] = {}
    audit: dict[str, Any] = {
        "source_pdf": str(source_path),
        "output_pdf": str(output_path),
        "mode": "non_drawing_information_panel_bilingual_reflow",
        "panels": [],
        "failed": [],
    }

    for panel in spec.get("panels", []):
        page_index = int(panel.get("page_index", 0))
        page = doc[page_index]
        restore_vector_rules = bool(spec.get("restore_vector_rules"))
        if restore_vector_rules and page_index not in original_drawings:
            original_drawings[page_index] = page.get_cdrawings()
            cleared_by_page[page_index] = []
        panel_audit = {
            "panel_id": panel["panel_id"],
            "page_index": page_index,
            "cleared_regions": 0,
            "fields": [],
        }

        clear_mode = str(panel.get("clear_mode") or "white_overlay")
        for values in panel.get("clear_regions", []):
            clear_rect = _rect(values)
            if clear_mode == "redact_text":
                page.add_redact_annot(clear_rect, fill=(1, 1, 1))
            else:
                page.draw_rect(
                    clear_rect,
                    color=None,
                    fill=(1, 1, 1),
                    overlay=True,
                )
            if restore_vector_rules:
                cleared_by_page[page_index].append(clear_rect)
            panel_audit["cleared_regions"] += 1

        if clear_mode == "redact_text" and panel.get("clear_regions"):
            # Physically remove the old text operators. Images and vector graphics
            # are retained; release-critical panel rules are explicitly restored
            # after typesetting. This remains stable in PDF viewers whose content
            # stream ordering differs from MuPDF's white-overlay rendering.
            page.apply_redactions(images=0, graphics=0, text=0)

        for field in panel.get("fields", []):
            try:
                # R6 explicitly separates the tiny source-ink mask from the
                # approved cell used to lay out the bilingual field.  A field
                # must never treat its expanded layout cell as a redaction
                # rectangle: that would erase rules, logos, or neighbouring
                # non-text artwork in a title panel.
                selected_region = field.get("selected_region", field.get("rect"))
                used_size = _fit_textbox(
                    page,
                    _rect(selected_region),
                    field["text"],
                    fontname=field.get("font", "helv"),
                    max_size=float(field.get("max_size", 12.0)),
                    min_size=float(field.get("min_size", 6.4)),
                    lineheight=float(field.get("lineheight", 1.08)),
                    align=int(field.get("align", fitz.TEXT_ALIGN_LEFT)),
                )
                panel_audit["fields"].append(
                    {
                        "field_id": field["field_id"],
                        "status": "rendered",
                        "font_size": used_size,
                        "selected_region": list(selected_region),
                    }
                )
            except Exception as exc:
                failure = {
                    "panel_id": panel["panel_id"],
                    "field_id": field["field_id"],
                    "error": str(exc),
                }
                panel_audit["fields"].append({**failure, "status": "failed"})
                audit["failed"].append(failure)

        audit["panels"].append(panel_audit)

    # White glyph masks can cross a table rule by a fraction of a point. Restore
    # every original vector line/rectangle touched by a clear region after all
    # bilingual text has been placed. This preserves the source grid exactly and
    # also prevents later fields from erasing a divider restored too early.
    for page_index, drawings in original_drawings.items():
        page = doc[page_index]
        clear_regions = cleared_by_page[page_index]
        restored = 0
        for drawing in drawings:
            color = drawing.get("color")
            if color is None:
                color = (0, 0, 0)
            width = max(0.2, float(drawing.get("width") or 0.5))
            for item in drawing.get("items", []):
                kind = item[0]
                if kind == "l":
                    start, end = fitz.Point(*item[1]), fitz.Point(*item[2])
                    length = ((end.x - start.x) ** 2 + (end.y - start.y) ** 2) ** 0.5
                    axis_aligned = abs(end.x - start.x) <= 0.25 or abs(end.y - start.y) <= 0.25
                    if length < 35 or not axis_aligned:
                        continue
                    bounds = fitz.Rect(
                        min(start.x, end.x) - width,
                        min(start.y, end.y) - width,
                        max(start.x, end.x) + width,
                        max(start.y, end.y) + width,
                    )
                    if any((bounds & region).get_area() > 0 for region in clear_regions):
                        page.draw_line(start, end, color=color, width=width, overlay=True)
                        restored += 1
                elif kind == "re":
                    bounds = fitz.Rect(item[1])
                    if max(bounds.width, bounds.height) < 35:
                        continue
                    if any((bounds & region).get_area() > 0 for region in clear_regions):
                        page.draw_rect(bounds, color=color, width=width, overlay=True)
                        restored += 1
        audit.setdefault("restored_vector_rules", {})[str(page_index)] = restored

    for rule in spec.get("restore_lines", []):
        page_index = int(rule.get("page_index", 0))
        page = doc[page_index]
        start = fitz.Point(*map(float, rule["start"]))
        end = fitz.Point(*map(float, rule["end"]))
        page.draw_line(
            start,
            end,
            color=tuple(rule.get("color", [0, 0, 0])),
            width=float(rule.get("width", 0.45)),
            overlay=True,
        )
        audit.setdefault("explicit_restored_lines", 0)
        audit["explicit_restored_lines"] += 1

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()

    audit_path = output_path.with_suffix(".audit.json")
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return audit
