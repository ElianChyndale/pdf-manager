from __future__ import annotations

from dataclasses import dataclass
import json
import math
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
_VISUAL_INK_SCALE = 0.5
_VISUAL_INK_THRESHOLD = 235
_VISUAL_INK_RATIO_LIMIT = 0.006
_V3_SOURCE_OVERLAP_RATIO_LIMIT = 0.18
_V3_RELAXED_SOURCE_OVERLAP_RATIO_LIMIT = 0.60
_V3_VISUAL_INK_RATIO_LIMIT = 0.04
_V3_RELAXED_VISUAL_INK_RATIO_LIMIT = 0.30
_V3_DENSE_VISUAL_INK_RATIO_LIMIT = 0.70
_INLINE_FONT_MIN = 3.4
_INLINE_FONT_MAX = 7.2
_INLINE_FONT_SCALE = 0.66
_LEGACY_FALLBACK_FONT_MIN = 3.2
_LEGACY_FALLBACK_FONT_MAX = 6.4
_LEADER_COLOR = (0.08, 0.20, 0.58)
_LEADER_WIDTH = 0.32
_LEADER_CLEARANCE = 2.0


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


def _source_anchor_rect(region: dict, fallback: fitz.Rect | None) -> fitz.Rect | None:
    """Return an English-source anchor while retaining legacy bbox fallback."""
    bbox = region.get("source_anchor_bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return fallback
    try:
        rect = fitz.Rect(*(float(value) for value in bbox))
    except (TypeError, ValueError):
        return fallback
    return rect if not rect.is_empty and not rect.is_infinite else fallback


def _placement_anchor_rect(region: dict, fallback: fitz.Rect | None) -> fitz.Rect | None:
    """Use an approved visual anchor without changing the recorded source bbox."""
    bbox = region.get("placement_anchor_bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return fallback
    try:
        rect = fitz.Rect(*(float(value) for value in bbox))
    except (TypeError, ValueError):
        return fallback
    return rect if not rect.is_empty and not rect.is_infinite else fallback


def _review_target_rect(region: dict) -> fitz.Rect | None:
    bbox = region.get("review_target_bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        rect = fitz.Rect(*(float(value) for value in bbox))
    except (TypeError, ValueError):
        return None
    return rect if not rect.is_empty and not rect.is_infinite else None


def _is_v3_planned(region: dict) -> bool:
    """Return whether a multimodal V3 plan owns this placement decision."""
    flags = {str(flag) for flag in (region.get("qa_flags") or [])}
    return str(region.get("placement_decision_source") or "") == "multimodal_v3" or "multimodal_v3_plan" in flags


def _planned_candidate_rects(region: dict) -> list[fitz.Rect]:
    """Read only the candidate rectangles declared by the V3 planner."""
    result: list[fitz.Rect] = []
    raw_candidates = region.get("review_candidate_regions") or []
    if not isinstance(raw_candidates, (list, tuple)):
        return result
    for raw in raw_candidates:
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            continue
        try:
            rect = fitz.Rect(*(float(value) for value in raw))
        except (TypeError, ValueError):
            continue
        if not rect.is_empty and not rect.is_infinite:
            result.append(rect)
    return result


def _fit_v3_declared_region(
    declared: fitz.Rect,
    *,
    translated: str,
    requested_font_size: float,
    rotation: int,
    font: fitz.Font,
    page_rect: fitz.Rect,
    placement_bounds: fitz.Rect,
    occupied: list[fitz.Rect],
    pixmap: fitz.Pixmap | None,
    source_obstacles: list[fitz.Rect] | None = None,
    max_source_overlap_ratio: float = _V3_SOURCE_OVERLAP_RATIO_LIMIT,
    visual_ink_limit: float = _V3_VISUAL_INK_RATIO_LIMIT,
    min_font_size: float = 2.8,
) -> tuple[fitz.Rect, float] | None:
    """Find a clear text rectangle inside a model-declared region.

    The model supplies a visual band, not a license to paint over its border or
    a neighbouring CAD rule. The deterministic pass may tighten the band and
    reduce the font while keeping the planner's side/region decision intact.
    """
    if not placement_bounds.contains(declared):
        return None
    floor = max(2.2, min(2.8, min_font_size))
    upper = max(floor, min(18.0, requested_font_size or 6.0))
    sizes = [upper]
    while sizes[-1] > floor:
        next_size = max(floor, round(sizes[-1] - 0.35, 2))
        if math.isclose(next_size, sizes[-1], abs_tol=0.001):
            break
        sizes.append(next_size)
    for font_size in sizes:
        inner = fitz.Rect(
            declared.x0 + 1.5,
            declared.y0 + 1.5,
            declared.x1 - 1.5,
            declared.y1 - 1.5,
        )
        if inner.width <= 4 or inner.height <= 4:
            continue
        if rotation in {90, 270}:
            required_width = max(font_size * 1.5, _text_height(translated, inner.height, font, font_size))
            required_height = max(font_size * 1.35, font_size * 1.5)
        else:
            required_width = min(inner.width, max(18.0, inner.width))
            required_height = _text_height(translated, required_width, font, font_size, line_gap=1.12)
        if required_height > inner.height + 0.01:
            continue
        width = min(inner.width, max(required_width, 18.0))
        # PyMuPDF's textbox ascent/descent needs more than the logical line
        # height returned by `_text_height`; keeping only that tight box makes
        # otherwise valid 3-4pt Chinese captions fail insertion. Use the
        # declared clear band as the vertical budget and retain a generous
        # minimum line box for reliable embedding.
        height = min(inner.height, max(required_height * 1.6, font_size * 1.8))
        x_positions = [inner.x0, inner.x1 - width, inner.x0 + max(0.0, (inner.width - width) / 2.0)]
        y_positions = [inner.y0, inner.y1 - height, inner.y0 + max(0.0, (inner.height - height) / 2.0)]
        for x in x_positions:
            for y in y_positions:
                candidate = fitz.Rect(x, y, x + width, y + height)
                if not placement_bounds.contains(candidate):
                    continue
                if source_obstacles and _rect_overlap_ratio(candidate, source_obstacles) > max_source_overlap_ratio:
                    continue
                if _is_clear(candidate, occupied, page_rect) and _is_visual_clear(
                    candidate,
                    pixmap=pixmap,
                    page_rect=page_rect,
                    max_ink_ratio=visual_ink_limit,
                ):
                    return candidate, font_size


def _v3_source_overlap_limit(region: dict) -> float:
    """Use raster evidence for a supervisor-approved light-overlap target.

    Native PDF word boxes often occupy a much larger area than their visible
    glyphs.  They are useful as a guardrail, but must not veto a location that
    the multimodal planner selected from the rendered drawing and that still
    passes the stricter raster-ink and caption-collision checks below.
    """
    if region.get("allow_dense_source_overlap"):
        return _V3_RELAXED_SOURCE_OVERLAP_RATIO_LIMIT
    if region.get("allow_source_overlap"):
        return _V3_RELAXED_SOURCE_OVERLAP_RATIO_LIMIT
    return _V3_SOURCE_OVERLAP_RATIO_LIMIT
    return None


def _fit_v34_exact_region(
    declared: fitz.Rect,
    *,
    translated: str,
    requested_font_size: float,
    rotation: int,
    font: fitz.Font,
    placement_bounds: fitz.Rect,
    occupied: list[fitz.Rect],
) -> tuple[fitz.Rect, float] | None:
    """Validate, but never alter, a supervisor's final V3.4 placement."""
    if not placement_bounds.contains(declared) or requested_font_size <= 0:
        return None
    if not _is_clear(declared, occupied, placement_bounds):
        return None
    if rotation in {90, 270}:
        logical_width = declared.height
        logical_height = declared.width
    else:
        logical_width = declared.width
        logical_height = declared.height
    required_height = _text_height(
        translated,
        logical_width,
        font,
        requested_font_size,
        line_gap=1.12,
    )
    if required_height > logical_height + 0.01:
        return None
    return declared, requested_font_size


def _planned_leader_path(region: dict) -> list[tuple[float, float]]:
    """Normalize a model-supplied orthogonal route for later validation."""
    raw_path = region.get("leader_path") or []
    if not isinstance(raw_path, (list, tuple)):
        return []
    path: list[tuple[float, float]] = []
    for raw_point in raw_path:
        if not isinstance(raw_point, (list, tuple)) or len(raw_point) != 2:
            return []
        try:
            point = (float(raw_point[0]), float(raw_point[1]))
        except (TypeError, ValueError):
            return []
        if not all(math.isfinite(value) for value in point):
            return []
        path.append(point)
    return _simplify_leader_path(path) if len(path) >= 2 else []


def _planned_leader_is_clear(
    path: list[tuple[float, float]],
    *,
    page_rect: fitz.Rect,
    obstacles: list[fitz.Rect],
    existing_segments: list[tuple[tuple[float, float], tuple[float, float]]],
    pixmap: fitz.Pixmap | None,
    allow_diagonal: bool = False,
) -> bool:
    """Accept an explicit route when it is direct and collision-free.

    Legacy plans remain orthogonal. V3 multimodal plans may choose a diagonal
    segment when that is the genuinely shortest local connection.
    """
    if len(path) < 2:
        return False
    if any(not page_rect.contains(fitz.Point(*point)) for point in path):
        return False
    segments = _leader_segments(path)
    if len(segments) != len(path) - 1:
        return False
    if not allow_diagonal and any(
        not (
            math.isclose(start[0], end[0], abs_tol=0.01)
            or math.isclose(start[1], end[1], abs_tol=0.01)
        )
        for start, end in segments
    ):
        return False
    for segment in segments:
        if any(_segment_hits_rect(*segment, obstacle) for obstacle in obstacles):
            return False
        if not _leader_segment_visually_clear(*segment, pixmap=pixmap, page_rect=page_rect):
            return False
        if any(_segments_intersect(segment, existing) for existing in existing_segments):
            return False
    return True


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
            page_rect = source[page_index].rect
            if rotations[page_index]:
                displayed_rect = source_rect * matrices[page_index]
            elif not page_rect.contains(source_rect) and page_rect.width > page_rect.height:
                # The frozen legacy base can already have its page rotation
                # baked into landscape geometry.  Native source bboxes remain
                # in the original portrait system; keep using that 270° CAD
                # transform instead of sending captions into a blank margin.
                displayed_rect = source_rect * fitz.Matrix(0.0, -1.0, 1.0, 0.0, 0.0, page_rect.height)
            else:
                displayed_rect = source_rect
            region["bbox"] = [displayed_rect.x0, displayed_rect.y0, displayed_rect.x1, displayed_rect.y1]
            rotation = _rotation(region)
            if rotation and rotations[page_index]:
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
    rects = [fitz.Rect(word[:4]) for word in page.get_text("words") if len(word) >= 4]
    raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES)
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            direction = line.get("dir", (1.0, 0.0))
            if (
                not isinstance(direction, (list, tuple))
                or len(direction) != 2
                or (abs(float(direction[0]) - 1.0) < 0.01 and abs(float(direction[1])) < 0.01)
            ):
                continue
            for span in line.get("spans", []):
                bbox = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
                if bbox.is_valid and not bbox.is_empty:
                    rects.append(bbox)
    return rects


def _native_source_word_rects(page: fitz.Page) -> list[fitz.Rect]:
    """Return only selectable source-word bounds from the rendered PDF.

    This intentionally bypasses OCR/visual observations. A native word is
    evidence that the source PDF itself paints text in that band; external OCR
    boxes remain non-authoritative for V3 target placement.
    """
    try:
        return [
            fitz.Rect(word[:4])
            for word in page.get_text("words")
            if len(word) >= 4 and fitz.Rect(word[:4]).is_valid
        ]
    except Exception:
        return []


def _source_visual_pixmap(page: fitz.Page) -> fitz.Pixmap | None:
    """Render a light grayscale occupancy map for vector-only CAD text.

    Many engineering PDFs draw lettering as paths rather than selectable text.
    Word bboxes cannot protect those paths, so a small raster occupancy map is
    used as a second collision boundary.  It is deliberately low resolution:
    this is a layout guard, not the delivered artwork.
    """
    try:
        return page.get_pixmap(
            matrix=fitz.Matrix(_VISUAL_INK_SCALE, _VISUAL_INK_SCALE),
            colorspace=fitz.csGRAY,
            alpha=False,
        )
    except Exception:
        return None


def _visual_ink_ratio(
    rect: fitz.Rect,
    *,
    pixmap: fitz.Pixmap | None,
    page_rect: fitz.Rect,
) -> float:
    if pixmap is None or rect.is_empty or rect.is_infinite:
        return 0.0
    scale_x = pixmap.width / max(page_rect.width, 1.0)
    scale_y = pixmap.height / max(page_rect.height, 1.0)
    x0 = max(0, min(pixmap.width - 1, int(rect.x0 * scale_x)))
    x1 = max(x0 + 1, min(pixmap.width, int(rect.x1 * scale_x) + 1))
    y0 = max(0, min(pixmap.height - 1, int(rect.y0 * scale_y)))
    y1 = max(y0 + 1, min(pixmap.height, int(rect.y1 * scale_y) + 1))
    samples = pixmap.samples
    channels = max(1, int(pixmap.n))
    stride = int(pixmap.stride)
    ink = total = 0
    for y in range(y0, y1):
        row = y * stride
        for x in range(x0, x1):
            total += 1
            if samples[row + x * channels] < _VISUAL_INK_THRESHOLD:
                ink += 1
    return ink / total if total else 0.0


def _is_visual_clear(
    rect: fitz.Rect,
    *,
    pixmap: fitz.Pixmap | None,
    page_rect: fitz.Rect,
    max_ink_ratio: float = _VISUAL_INK_RATIO_LIMIT,
) -> bool:
    if pixmap is None:
        return True
    padded = fitz.Rect(rect.x0 - 1.5, rect.y0 - 1.5, rect.x1 + 1.5, rect.y1 + 1.5)
    return _visual_ink_ratio(padded, pixmap=pixmap, page_rect=page_rect) <= max_ink_ratio


def _is_clear(rect: fitz.Rect, occupied: list[fitz.Rect], page_rect: fitz.Rect) -> bool:
    if not page_rect.contains(rect):
        return False
    padded = fitz.Rect(rect.x0 - 1.5, rect.y0 - 1.5, rect.x1 + 1.5, rect.y1 + 1.5)
    for other in occupied:
        other_padded = fitz.Rect(other.x0 - 1.5, other.y0 - 1.5, other.x1 + 1.5, other.y1 + 1.5)
        if padded.intersects(other_padded) and not (padded & other_padded).is_empty:
            return False
    return True


def _rect_overlap_ratio(rect: fitz.Rect, obstacles: list[fitz.Rect]) -> float:
    """Return the largest single source-obstacle coverage of ``rect``.

    V3 deliberately permits a small amount of source/table-line overlap so a
    complete nearby block is not discarded.  Use the largest intersection
    rather than summing all word boxes: adjacent OCR words often overlap or
    duplicate the same native span and would otherwise inflate the ratio.
    """
    if rect.is_empty or rect.is_infinite:
        return 1.0
    area = max(rect.get_area(), 1e-6)
    largest = 0.0
    for obstacle in obstacles:
        if obstacle.is_empty or obstacle.is_infinite:
            continue
        intersection = rect & obstacle
        if not intersection.is_empty:
            largest = max(largest, intersection.get_area() / area)
    return largest


def _is_title_or_table_region(region: dict, *, page_rect: fitz.Rect) -> bool:
    """Keep callout leaders out of title blocks, tables, and long text rows."""
    role = str(
        region.get("layout_role")
        or region.get("semantic_group_kind")
        or region.get("placement_role")
        or ""
    ).casefold()
    if role in {"title_block", "table", "table_cell", "paragraph", "address"}:
        return True
    source = _source_text(region).casefold()
    table_markers = (
        "project",
        "drawing",
        "consultant",
        "contractor",
        "developer",
        "landowner",
        "owner",
        "designed",
        "drawn",
        "checked",
        "approved",
        "scale",
        "revision",
        "address",
        "tel",
        "fax",
        "website",
        "e-mail",
        "email",
    )
    if any(marker in source for marker in table_markers):
        return True
    bbox = _valid_bbox(region)
    if bbox is None:
        return False
    # Conventional drawing title blocks live in the outer lower/right bands.
    # This is deliberately a weak signal: text semantics above take priority.
    # Do not classify an arbitrary right-side plan/legend as a title block.
    # The former 76% threshold swallowed dense drawing content and disabled
    # leaders there. Actual title columns in these sheets start near the page
    # edge; semantic markers above still cover title rows that begin farther
    # left, while the tighter geometry keeps ordinary map labels in leader mode.
    return bbox.x0 >= page_rect.width * 0.84 or bbox.y0 >= page_rect.height * 0.90


def _rect_center(rect: fitz.Rect) -> tuple[float, float]:
    return ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)


def _edge_anchor(rect: fitz.Rect, other: fitz.Rect, *, clearance: float = 1.5) -> tuple[float, float]:
    """Return the external edge point closest to another rectangle."""
    center_x, center_y = _rect_center(rect)
    other_x, other_y = _rect_center(other)
    if abs(other_x - center_x) >= abs(other_y - center_y):
        if other_x >= center_x:
            return (rect.x1 + clearance, min(max(other_y, rect.y0 + clearance), rect.y1 - clearance))
        return (rect.x0 - clearance, min(max(other_y, rect.y0 + clearance), rect.y1 - clearance))
    if other_y >= center_y:
        return (min(max(other_x, rect.x0 + clearance), rect.x1 - clearance), rect.y1 + clearance)
    return (min(max(other_x, rect.x0 + clearance), rect.x1 - clearance), rect.y0 - clearance)


def _simplify_leader_path(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for point in points:
        if result and math.isclose(point[0], result[-1][0], abs_tol=0.01) and math.isclose(point[1], result[-1][1], abs_tol=0.01):
            continue
        result.append(point)
    compact: list[tuple[float, float]] = []
    for point in result:
        if len(compact) >= 2:
            before = compact[-2]
            previous = compact[-1]
            if (
                (math.isclose(before[0], previous[0], abs_tol=0.01) and math.isclose(previous[0], point[0], abs_tol=0.01))
                or (math.isclose(before[1], previous[1], abs_tol=0.01) and math.isclose(previous[1], point[1], abs_tol=0.01))
            ):
                compact[-1] = point
                continue
        compact.append(point)
    return compact


def _leader_path_length(path: list[tuple[float, float]]) -> float:
    """Return the Manhattan length of an orthogonal leader path."""
    return sum(
        abs(end[0] - start[0]) + abs(end[1] - start[1])
        for start, end in zip(path, path[1:])
    )


def _leader_segments(path: list[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return [
        (start, end)
        for start, end in zip(path, path[1:])
        if not (math.isclose(start[0], end[0], abs_tol=0.01) and math.isclose(start[1], end[1], abs_tol=0.01))
    ]


def _orthogonal_segments(path: list[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Backward-compatible alias used by the orthogonal auto-router."""
    return _leader_segments(path)


def _segment_hits_rect(
    start: tuple[float, float],
    end: tuple[float, float],
    rect: fitz.Rect,
    *,
    clearance: float = _LEADER_CLEARANCE,
) -> bool:
    padded = fitz.Rect(rect.x0 - clearance, rect.y0 - clearance, rect.x1 + clearance, rect.y1 + clearance)
    if math.isclose(start[0], end[0], abs_tol=0.01):
        x = start[0]
        return padded.x0 <= x <= padded.x1 and max(min(start[1], end[1]), padded.y0) <= min(max(start[1], end[1]), padded.y1)
    if math.isclose(start[1], end[1], abs_tol=0.01):
        y = start[1]
        return padded.y0 <= y <= padded.y1 and max(min(start[0], end[0]), padded.x0) <= min(max(start[0], end[0]), padded.x1)
    return True


def _segments_intersect(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    (ax, ay), (bx, by) = first
    (cx, cy), (dx, dy) = second

    def orient(px: float, py: float, qx: float, qy: float, rx: float, ry: float) -> float:
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)

    def on_segment(px: float, py: float, qx: float, qy: float, rx: float, ry: float) -> bool:
        return (
            min(px, rx) - _LEADER_CLEARANCE <= qx <= max(px, rx) + _LEADER_CLEARANCE
            and min(py, ry) - _LEADER_CLEARANCE <= qy <= max(py, ry) + _LEADER_CLEARANCE
        )

    o1 = orient(ax, ay, bx, by, cx, cy)
    o2 = orient(ax, ay, bx, by, dx, dy)
    o3 = orient(cx, cy, dx, dy, ax, ay)
    o4 = orient(cx, cy, dx, dy, bx, by)
    eps = 0.01
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)):
        return True
    if abs(o1) <= eps and on_segment(ax, ay, cx, cy, bx, by):
        return True
    if abs(o2) <= eps and on_segment(ax, ay, dx, dy, bx, by):
        return True
    if abs(o3) <= eps and on_segment(cx, cy, ax, ay, dx, dy):
        return True
    if abs(o4) <= eps and on_segment(cx, cy, bx, by, dx, dy):
        return True
    return False


def _leader_segment_visually_clear(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    pixmap: fitz.Pixmap | None,
    page_rect: fitz.Rect,
) -> bool:
    """Reject a leader that would visibly cross heavy drawing content."""
    if pixmap is None:
        return True
    distance = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
    samples = max(1, int(distance / 6.0))
    for index in range(1, samples):
        progress = index / samples
        x = start[0] + (end[0] - start[0]) * progress
        y = start[1] + (end[1] - start[1]) * progress
        probe = fitz.Rect(x - 1.25, y - 1.25, x + 1.25, y + 1.25)
        if _visual_ink_ratio(probe, pixmap=pixmap, page_rect=page_rect) > 0.48:
            return False
    return True


def _orthogonal_leader_path(
    source_rect: fitz.Rect,
    target_rect: fitz.Rect,
    *,
    page_rect: fitz.Rect,
    obstacles: list[fitz.Rect],
    existing_segments: list[tuple[tuple[float, float], tuple[float, float]]],
    pixmap: fitz.Pixmap | None,
) -> list[tuple[float, float]] | None:
    """Find a short one/two-bend local callout route through whitespace."""
    start = _edge_anchor(source_rect, target_rect)
    end = _edge_anchor(target_rect, source_rect)
    midpoint_x = (start[0] + end[0]) / 2
    midpoint_y = (start[1] + end[1]) / 2
    candidates = [
        [start, (end[0], start[1]), end],
        [start, (start[0], end[1]), end],
        [start, (midpoint_x, start[1]), (midpoint_x, end[1]), end],
        [start, (start[0], midpoint_y), (end[0], midpoint_y), end],
    ]
    # A background line is not a reason to route around the sheet.  Evaluate
    # local candidates by length first, then by bend count, so the first
    # accepted route is always the shortest readable connection available.
    candidates.sort(
        key=lambda raw_path: (
            _leader_path_length(_simplify_leader_path(raw_path)),
            len(_simplify_leader_path(raw_path)),
        )
    )
    for raw_path in candidates:
        path = _simplify_leader_path(raw_path)
        if len(path) < 2 or any(not page_rect.contains(fitz.Point(*point)) for point in path):
            continue
        segments = _orthogonal_segments(path)
        if not segments:
            continue
        clear = True
        for segment in segments:
            for obstacle in obstacles:
                if obstacle.intersects(source_rect) or obstacle.intersects(target_rect):
                    continue
                if _segment_hits_rect(*segment, obstacle):
                    clear = False
                    break
            if not clear or not _leader_segment_visually_clear(*segment, pixmap=pixmap, page_rect=page_rect):
                clear = False
                break
            if any(_segments_intersect(segment, existing) for existing in existing_segments):
                clear = False
                break
        if clear:
            return path
    return None


def _draw_orthogonal_leader(page: fitz.Page, path: list[tuple[float, float]]) -> None:
    for start, end in _leader_segments(path):
        page.draw_line(
            fitz.Point(*start),
            fitz.Point(*end),
            color=_LEADER_COLOR,
            width=_LEADER_WIDTH,
            overlay=True,
        )


def _page_grid_lines(page: fitz.Page) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Collect substantial horizontal/vertical rules for title-block cells."""
    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return horizontal, vertical
    for drawing in drawings:
        rect = fitz.Rect(drawing.get("rect", (0, 0, 0, 0)))
        if rect.width >= 48.0 and rect.height <= 1.8:
            horizontal.append((rect.y0, rect.x0, rect.x1))
        if rect.height >= 24.0 and rect.width <= 1.8:
            vertical.append((rect.x0, rect.y0, rect.y1))
        for item in drawing.get("items", []):
            if not item or item[0] != "l" or len(item) < 3:
                continue
            first, second = item[1], item[2]
            if abs(first.y - second.y) <= 0.5 and abs(first.x - second.x) >= 48.0:
                horizontal.append((first.y, min(first.x, second.x), max(first.x, second.x)))
            elif abs(first.x - second.x) <= 0.5 and abs(first.y - second.y) >= 24.0:
                vertical.append((first.x, min(first.y, second.y), max(first.y, second.y)))
    return horizontal, vertical


def _title_cell_rect(
    anchor: fitz.Rect,
    *,
    page_rect: fitz.Rect,
    grid_lines: tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]],
) -> fitz.Rect | None:
    """Find the title-block/table cell enclosing an existing caption anchor."""
    horizontal, vertical = grid_lines
    center_x, center_y = _rect_center(anchor)
    # The drawing often has a long horizontal rule ending exactly at the
    # title-block border, while the border itself is split into many short
    # vector segments. Recover the stable right-hand block bounds first, then
    # reject page-wide frame lines that would otherwise create a full-page
    # "cell".
    block_segments = [
        (x0, x1)
        for _y, x0, x1 in horizontal
        if x1 - x0 >= 160.0
        and x1 >= page_rect.width * 0.90
        and x0 >= page_rect.width * 0.62
    ]
    block_x0 = min((x0 for x0, _x1 in block_segments), default=None)
    block_x1 = max((x1 for _x0, x1 in block_segments), default=None)
    in_block = (
        block_x0 is not None
        and block_x1 is not None
        and block_x0 - 8.0 <= center_x <= block_x1 + 8.0
    )
    top_candidates = [
        y
        for y, x0, x1 in horizontal
        if x0 - 1.0 <= center_x <= x1 + 1.0 and y < center_y - 0.8
    ]
    bottom_candidates = [
        y
        for y, x0, x1 in horizontal
        if x0 - 1.0 <= center_x <= x1 + 1.0 and y > center_y + 0.8
    ]
    left_candidates = [
        x
        for x, y0, y1 in vertical
        if y0 - 1.0 <= center_y <= y1 + 1.0 and x < center_x - 0.8
    ]
    right_candidates = [
        x
        for x, y0, y1 in vertical
        if y0 - 1.0 <= center_y <= y1 + 1.0 and x > center_x + 0.8
    ]
    if in_block:
        left_candidates = [x for x in left_candidates if x >= block_x0 - 4.0]
        right_candidates = [x for x in right_candidates if x <= block_x1 + 4.0]
    y0 = max(top_candidates, default=max(page_rect.y0, center_y - 76.0))
    y1 = min(bottom_candidates, default=min(page_rect.y1, center_y + 76.0))
    x0 = max(
        left_candidates,
        default=(block_x0 if in_block else max(page_rect.x0, center_x - 160.0)),
    )
    x1 = min(
        right_candidates,
        default=(block_x1 if in_block else min(page_rect.x1, center_x + 160.0)),
    )
    cell = fitz.Rect(x0 + 0.8, y0 + 0.8, x1 - 0.8, y1 - 0.8) & page_rect
    if cell.is_empty or cell.width < 44.0 or cell.height < 6.0:
        return None
    return cell


def _title_block_candidate(
    source_rect: fitz.Rect,
    *,
    translated: str,
    cell_rect: fitz.Rect,
    page_rect: fitz.Rect,
    occupied: list[fitz.Rect],
    font: fitz.Font,
    visual_pixmap: fitz.Pixmap | None,
) -> tuple[fitz.Rect, float, float] | None:
    """Place a title-block translation within the same drawn cell, no leader."""
    font_size = max(4.8, min(6.5, max(4.2, source_rect.height * 0.58)))
    gap = max(3.0, font_size * 0.5)
    available_width = max(38.0, cell_rect.width - 6.0)
    desired_width = min(
        available_width,
        max(48.0, font.text_length(translated, fontsize=font_size) + 6.0),
    )
    desired_height = max(
        font_size * 1.48,
        _text_height(translated, max(24.0, desired_width - 4.0), font, font_size, line_gap=1.16) + 2.5,
    )
    below_y = max(cell_rect.y0, source_rect.y1 + gap)
    above_y = min(cell_rect.y1 - desired_height, source_rect.y0 - gap - desired_height)
    right_x = max(cell_rect.x0, source_rect.x1 + gap)
    candidates_list: list[fitz.Rect] = []
    # A source title can end just before a large blank part of the row. Try a
    # few rightward slots instead of accepting the first one, which may still
    # touch vector lettering that is not selectable in the source PDF.
    right_limit = cell_rect.x1 - desired_width
    right_y_positions = [
        max(cell_rect.y0, source_rect.y0),
        cell_rect.y0,
        max(cell_rect.y0, min(cell_rect.y1 - desired_height, source_rect.y0 - desired_height - gap)),
        min(cell_rect.y1 - desired_height, source_rect.y1 + gap),
    ]
    seen_y: set[float] = set()
    for raw_y in right_y_positions:
        right_y0 = max(cell_rect.y0, min(cell_rect.y1 - desired_height, raw_y))
        right_y1 = right_y0 + desired_height
        if right_y1 - right_y0 < font_size * 1.25:
            continue
        if right_y0 in seen_y:
            continue
        seen_y.add(right_y0)
        cursor = max(cell_rect.x0, right_x)
        if cursor > right_limit:
            cursor = cell_rect.x0
        while cursor <= right_limit + 0.1:
            candidates_list.append(fitz.Rect(cursor, right_y0, cursor + desired_width, right_y1))
            cursor += 8.0
    candidates_list.extend(
        [
            fitz.Rect(
                cell_rect.x0 + 3.0,
                below_y,
                cell_rect.x1 - 3.0,
                min(cell_rect.y1, below_y + desired_height),
            ),
            fitz.Rect(
                cell_rect.x0 + 3.0,
                max(cell_rect.y0, above_y),
                cell_rect.x1 - 3.0,
                max(cell_rect.y0, above_y) + desired_height,
            ),
        ]
    )
    candidates = tuple(candidates_list)
    for candidate in candidates:
        if candidate.width < 28.0 or candidate.height < font_size * 1.25:
            continue
        # The cell border itself is ink. A normal padded visual check rejects
        # candidates that sit neatly on the inner side of that border, so use a
        # small inset for title cells while keeping selectable source words as
        # hard collision boundaries.
        visual_probe = fitz.Rect(
            candidate.x0 + 0.8,
            candidate.y0 + 0.8,
            candidate.x1 - 0.8,
            candidate.y1 - 0.8,
        )
        visual_clear = (
            _visual_ink_ratio(
                visual_probe,
                pixmap=visual_pixmap,
                page_rect=page_rect,
            )
            <= 0.03
        )
        if _is_clear(candidate, occupied, cell_rect) and visual_clear:
            return candidate, font_size, gap
    return None


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


def _insert_textbox_exact(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    font_path: Path,
    font_size: float,
    color: tuple[float, float, float],
    rotate: int = 0,
) -> float:
    """Insert once at the supervisor's exact geometry; never shrink or move."""
    remaining = page.insert_textbox(
        rect,
        text,
        fontname=_FONT_NAME,
        fontfile=str(font_path),
        fontsize=font_size,
        color=color,
        border_width=0,
        rotate=rotate if rotate in {0, 90, 180, 270} else 0,
        overlay=True,
    )
    return font_size if remaining >= -0.01 else -1.0


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
    visual_pixmap: fitz.Pixmap | None = None,
    max_local_distance: float = 36.0,
    allow_left: bool = False,
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
    font_size = max(
        _INLINE_FONT_MIN,
        min(_INLINE_FONT_MAX, max(3.6, source_rect.height * _INLINE_FONT_SCALE)),
    )
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
        # V2 kept automatic captions on the right/below/above. V3 may use the
        # left side only when the multimodal planner has explicitly permitted it
        # (normally with a leader); this preserves the old conservative default
        # for non-planned OCR regions.
        candidates = [
            fitz.Rect(source_rect.x1 + gap, source_rect.y0, source_rect.x1 + gap + width, source_rect.y0 + height),
            fitz.Rect(source_rect.x1 + gap, source_rect.y1 - height, source_rect.x1 + gap + width, source_rect.y1),
            fitz.Rect(source_rect.x0, source_rect.y1 + gap, source_rect.x0 + width, source_rect.y1 + gap + height),
            fitz.Rect(source_rect.x1 - width, source_rect.y1 + gap, source_rect.x1, source_rect.y1 + gap + height),
            fitz.Rect(source_rect.x0, source_rect.y0 - gap - height, source_rect.x0 + width, source_rect.y0 - gap),
            fitz.Rect(source_rect.x1 - width, source_rect.y0 - gap - height, source_rect.x1, source_rect.y0 - gap),
        ]
        if allow_left:
            candidates[2:2] = [
                fitz.Rect(source_rect.x0 - gap - width, source_rect.y0, source_rect.x0 - gap, source_rect.y0 + height),
                fitz.Rect(source_rect.x0 - gap - width, source_rect.y1 - height, source_rect.x0 - gap, source_rect.y1),
            ]
    # Keep the companion local, but allow a small ring search when its immediate
    # edge is occupied by a dimension line or a neighbouring CAD label.  A
    # The last radii are a leader-caption fallback for dense equipment notes.
    # They remain in the same equipment bay / title-block cell rather than a
    # page margin; the audit records the actual distance so QA can reject a
    # placement that is no longer visually local.
    expanded: list[fitz.Rect] = list(candidates)
    for extra_gap in (8.0, 14.0, 20.0, 28.0, 36.0, 44.0, 60.0, 80.0, 104.0):
        if extra_gap > max_local_distance:
            continue
        delta = extra_gap - gap
        for candidate in candidates:
            if rotation in {90, 270}:
                # Vertical captions are narrow; shift only horizontally so the
                # text keeps the original label's reading axis.
                if candidate.x0 >= source_rect.x1:
                    expanded.append(fitz.Rect(candidate.x0 + delta, candidate.y0, candidate.x1 + delta, candidate.y1))
                elif candidate.x1 <= source_rect.x0:
                    expanded.append(fitz.Rect(candidate.x0 - delta, candidate.y0, candidate.x1 - delta, candidate.y1))
            elif candidate.y0 >= source_rect.y1:
                expanded.append(fitz.Rect(candidate.x0, candidate.y0 + delta, candidate.x1, candidate.y1 + delta))
            elif candidate.y1 <= source_rect.y0:
                expanded.append(fitz.Rect(candidate.x0, candidate.y0 - delta, candidate.x1, candidate.y1 - delta))
            elif candidate.x0 >= source_rect.x1:
                expanded.append(fitz.Rect(candidate.x0 + delta, candidate.y0, candidate.x1 + delta, candidate.y1))
            else:
                expanded.append(fitz.Rect(candidate.x0 - delta, candidate.y0, candidate.x1 - delta, candidate.y1))
    for candidate in expanded:
        if _is_clear(candidate, occupied, page_rect) and _is_visual_clear(
            candidate,
            pixmap=visual_pixmap,
            page_rect=page_rect,
        ):
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


def _legacy_fallback_rect(
    region: dict,
    page_rect: fitz.Rect,
    *,
    translated: str = "",
    font: fitz.Font | None = None,
) -> fitz.Rect | None:
    """Return the trusted legacy caption box when a new slot is unavailable.

    Legacy translated PDFs are still the user's visual source of truth.  A
    caption with a recorded legacy bbox must therefore remain visible even if
    the current page has no safe right/below/above slot.  Synthetic OCR or
    Sol additions do not get this fallback because they have no authoritative
    prior placement to preserve.
    """
    if str(region.get("provenance") or "") != "legacy_translation":
        return None
    raw = region.get("legacy_bbox") or region.get("bbox")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        rect = fitz.Rect(*(float(value) for value in raw))
    except (TypeError, ValueError):
        return None
    if rect.is_empty or rect.is_infinite:
        return None
    if not page_rect.contains(rect):
        return None
    # Very small CAD labels in the legacy PDF can have a 3pt-high text box.
    # Preserve their original anchor but give the renderer enough room to
    # reproduce the complete Chinese companion instead of dropping it.
    if rect.width < 36.0 or rect.height < 7.0:
        measure_font = font or fitz.Font("helv")
        desired_width = measure_font.text_length(
            translated or " ", fontsize=3.8
        ) + 8.0
        width = min(max(rect.width, 28.0, desired_width), 96.0)
        height = max(rect.height, 8.0)
        rect = fitz.Rect(
            rect.x0,
            rect.y0,
            min(page_rect.x1, rect.x0 + width),
            min(page_rect.y1, rect.y0 + height),
        )
    return rect


def _legacy_fallback_font_size(region: dict, rect: fitz.Rect) -> float:
    requested = float(region.get("legacy_font_size") or 0)
    if requested > 0:
        return max(_LEGACY_FALLBACK_FONT_MIN, min(_LEGACY_FALLBACK_FONT_MAX, requested))
    return max(
        _LEGACY_FALLBACK_FONT_MIN,
        min(_LEGACY_FALLBACK_FONT_MAX, max(3.8, rect.height * 0.66)),
    )


def render_bilingual_inline_only(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    regions: Iterable[dict],
    font_path: Path | None = None,
    max_local_distance: float = 36.0,
    draw_leaders: bool = True,
    preserve_legacy_position: bool = True,
) -> EngineeringRenderResult:
    """Render a single-page, unnumbered original-plus-Chinese drawing.

    This mode intentionally never adds a reference page or numbered anchor. It
    is suitable for a visually calm client-facing sample; untranslated literal
    codes remain on the source drawing and authoritative legacy captions are
    preserved at their old position when no safe nearby slot exists.
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
            visual_pixmap = _source_visual_pixmap(source_page)
            # V2 fallback placement uses native source geometry as a hard
            # collision boundary. V3 declared targets below deliberately do
            # not: their target authority comes from the multimodal page image
            # and the actual visual-ink probe.
            # We intentionally do not inspect every CAD vector path here: it is
            # both expensive and too conservative on dense drawings. Visual
            # raster checks still protect genuinely visible source ink.
            # Do not turn every OCR observation into an obstacle.  The same
            # source label is often observed by native extraction, full-page
            # OCR and overlapping tiles; treating all those bboxes as occupied
            # was the reason a prior release silently lost dense labels.  The
            # page's actual selectable text plus accepted Chinese captions are
            # the collision boundary; vector-only labels are protected by their
            # own source rectangle below.
            occupied = [rect for rect in _source_text_rects(source_page) if rect.is_valid]
            # Treat all authoritative legacy caption boxes as protected
            # obstacles up front. Otherwise an automatic caption processed
            # just before a later fallback can occupy the fallback's old
            # position, recreating the very overlap V2 is meant to prevent.
            legacy_obstacles = [
                fallback
                for item in page_regions
                if (
                    not _is_v3_planned(item)
                    and
                    (
                        fallback := _legacy_fallback_rect(
                            item,
                            page.rect,
                            translated=_translated_text(item),
                            font=font,
                        )
                    ) is not None
                )
            ]
            occupied.extend(legacy_obstacles)
            # A V3 target is chosen from the rendered page image, not from an
            # external OCR rectangle. Native selectable words remain source
            # anchors for the bounded-overlap audit, but are not hard target
            # obstacles: a visually blank band may be usable even when OCR
            # reported text there. Accepted Chinese captions remain hard
            # obstacles so translations never cover one another.
            native_source_word_obstacles = _native_source_word_rects(source_page)
            v3_caption_obstacles = list(legacy_obstacles)
            # V3 leaders only need to avoid Chinese captions.  Native source
            # text and CAD linework may be crossed when that keeps the route
            # short; visual QA records those crossings as advisory findings.
            leader_caption_obstacles = list(legacy_obstacles)
            leader_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
            title_grid = (
                _page_grid_lines(source_page)
                if any(_is_title_or_table_region(region, page_rect=page.rect) for region in page_regions)
                else ([], [])
            )
            for region in page_regions:
                legacy_rect = _valid_bbox(region)
                source_rect = _source_anchor_rect(region, legacy_rect)
                placement_anchor = _placement_anchor_rect(region, source_rect)
                translated = _compact_inline_text(_translated_text(region))
                rotation = _rotation(region)
                title_or_table = _is_title_or_table_region(region, page_rect=page.rect)
                v3_planned = _is_v3_planned(region)
                strict_v34 = bool(region.get("strict_multimodal_execution"))
                title_cell = (
                    _title_cell_rect(
                        legacy_rect or placement_anchor,
                        page_rect=page.rect,
                        grid_lines=title_grid,
                    )
                    if title_or_table and (legacy_rect is not None or placement_anchor is not None)
                    else None
                )
                # A V3 leader may intentionally leave a title/table cell and
                # land in a declared nearby gutter. Keep the page as the
                # placement bound for that explicit decision; ordinary V2
                # title rows remain constrained to their detected cell.
                placement_bounds = page.rect if v3_planned else (title_cell or page.rect)
                # A translated title-block paragraph can contain a company
                # name that also appears elsewhere on the sheet. If matching
                # picked that distant English occurrence, keep the authoritative
                # legacy title-cell coordinate for layout while retaining the
                # matched source bbox in the audit for traceability.
                layout_source_rect = source_rect
                if (
                    title_cell is not None
                    and source_rect is not None
                    and not title_cell.contains(source_rect)
                ):
                    layout_source_rect = legacy_rect or placement_anchor or source_rect
                audit_entry = {
                    "region_id": str(region.get("region_id") or ""),
                    "page_index": page_index,
                    "source_text": _source_text(region),
                    "translated_text": translated,
                    "source_bbox": list(source_rect) if source_rect is not None else [],
                    "rotation": rotation,
                    "status": "rejected_invalid",
                    "target_bbox": [],
                    "distance": None,
                    "visual_ink_ratio": None,
                    "decision_source": str(
                        region.get("placement_decision_source") or "automatic"
                    ),
                    "semantic_group_id": str(
                        region.get("semantic_group_id") or region.get("group_id") or ""
                    ),
                    "semantic_group_members": int(region.get("member_count") or 1),
                    "coverage_status": str(region.get("coverage_status") or "translated"),
                    "placement_side": str(region.get("placement_side") or ""),
                    "placement_mode": str(region.get("placement_mode") or ""),
                    "multimodal_v3": v3_planned,
                    "leader": {"status": "not_needed", "path": []},
                    "placement_bounds": list(placement_bounds),
                    "target_inside_page": None,
                    "candidate_rejections": [],
                }
                # Panel reflow has already written a black source+Chinese pair
                # inside a visually reviewed title/table cell.  It is a real
                # placement, not a waived translation: record it in the same
                # audit and do not add a duplicate inline caption.  The caller
                # is responsible for running panel_reflow successfully before
                # invoking this renderer with the managed-plan flag.
                if region.get("panel_reflow_managed"):
                    panel_target = region.get("panel_reflow_target_bbox") or region.get("review_target_bbox") or []
                    audit_entry.update(
                        {
                            "status": "panel_reflowed",
                            "target_bbox": list(panel_target),
                            "distance": 0.0,
                            "panel_reflow": {
                                "panel_id": str(region.get("panel_reflow_panel_id") or ""),
                                "field_id": str(region.get("panel_reflow_field_id") or ""),
                            },
                            "target_inside_page": (
                                page.rect.contains(fitz.Rect(*panel_target))
                                if isinstance(panel_target, (list, tuple)) and len(panel_target) == 4
                                else None
                            ),
                        }
                    )
                    placement_audit.append(audit_entry)
                    placed += 1
                    continue
                legacy_fallback = (
                    _legacy_fallback_rect(
                        region,
                        page.rect,
                        translated=translated,
                        font=font,
                    )
                    if preserve_legacy_position
                    else None
                )
                region_flags = {str(flag) for flag in (region.get("qa_flags") or [])}
                trusted_legacy = (
                    legacy_fallback is not None
                    and str(region.get("provenance") or "") == "legacy_translation"
                    and "authoritative_legacy_translation" in region_flags
                )
                if not _safe_inline_region(region) and not trusted_legacy:
                    audit_entry["status"] = "rejected_unverified_ocr"
                    placement_audit.append(audit_entry)
                    unplaced += 1
                    continue
                if source_rect is None or placement_anchor is None or not translated:
                    placement_audit.append(audit_entry)
                    unplaced += 1
                    continue
                review_target = _review_target_rect(region)
                if review_target is not None:
                    audit_entry["target_inside_page"] = page.rect.contains(review_target)
                fallback_used = False
                review_target_reflowed = False
                if review_target is not None:
                    review_visual_pad = fitz.Rect(
                        review_target.x0 - 1.5,
                        review_target.y0 - 1.5,
                        review_target.x1 + 1.5,
                        review_target.y1 + 1.5,
                    )
                    audit_entry["visual_ink_ratio"] = round(
                        _visual_ink_ratio(
                            review_visual_pad,
                            pixmap=visual_pixmap,
                            page_rect=page.rect,
                        ),
                        4,
                    )
                    if v3_planned:
                        candidate = None
                        declared_regions = (
                            [review_target]
                            if strict_v34
                            else [review_target, *_planned_candidate_rects(region)]
                        )
                        for declared in declared_regions:
                            fitted = (
                                _fit_v34_exact_region(
                                    declared,
                                    # V3.4's supervisor supplies the exact
                                    # executed string.  Validate the rendered
                                    # companion text itself, rather than a
                                    # longer audit translation that is not
                                    # painted into the declared rectangle.
                                    translated=str(region.get("render_text") or translated),
                                    requested_font_size=float(region.get("review_font_size") or 0),
                                    rotation=rotation,
                                    font=font,
                                    placement_bounds=placement_bounds,
                                    occupied=v3_caption_obstacles,
                                )
                                if strict_v34
                                else _fit_v3_declared_region(
                                    declared,
                                    translated=translated,
                                    requested_font_size=float(region.get("review_font_size") or 0),
                                    rotation=rotation,
                                    font=font,
                                    page_rect=page.rect,
                                    placement_bounds=placement_bounds,
                                    occupied=v3_caption_obstacles,
                                    pixmap=visual_pixmap,
                                    source_obstacles=native_source_word_obstacles,
                                    max_source_overlap_ratio=_v3_source_overlap_limit(region),
                                    visual_ink_limit=(
                                        1.0
                                        if region.get("multimodal_visual_whitespace_override")
                                        else _V3_DENSE_VISUAL_INK_RATIO_LIMIT
                                        if region.get("allow_dense_source_overlap")
                                        else _V3_RELAXED_VISUAL_INK_RATIO_LIMIT
                                        if region.get("allow_source_overlap")
                                        else _V3_VISUAL_INK_RATIO_LIMIT
                                    ),
                                    min_font_size=(2.4 if region.get("allow_source_overlap") else 2.8),
                                )
                            )
                            if fitted is None:
                                audit_entry["candidate_rejections"].append(
                                    {
                                        "bbox": list(declared),
                                        "reason": "declared_target_not_clear_or_text_did_not_fit",
                                    }
                                )
                                continue
                            fitted_rect, fitted_font = fitted
                            candidate = (fitted_rect, fitted_font, 0.0)
                            review_target_reflowed = fitted_rect != review_target
                            break
                        if candidate is None:
                            audit_entry["status"] = "rejected_v3_declared_target_collision"
                            audit_entry["target_bbox"] = list(review_target)
                            audit_entry["manual_review_required"] = True
                            audit_entry["manual_review_reason"] = "all_declared_v3_targets_are_occupied"
                            placement_audit.append(audit_entry)
                            unplaced += 1
                            continue
                    elif not placement_bounds.contains(review_target):
                        if legacy_fallback is None:
                            audit_entry["status"] = "rejected_review_target_outside_page"
                            placement_audit.append(audit_entry)
                            unplaced += 1
                            continue
                        candidate = (
                            legacy_fallback,
                            _legacy_fallback_font_size(region, legacy_fallback),
                            0.0,
                        )
                        fallback_used = True
                    elif not _is_clear(review_target, occupied, placement_bounds) or not _is_visual_clear(
                        review_target,
                        pixmap=visual_pixmap,
                        page_rect=page.rect,
                    ):
                        # A review raster can miss vector content. Search the
                        # same local semantic neighbourhood before preserving an
                        # old caption that may cover the source text.
                        candidate = (
                            _title_block_candidate(
                                layout_source_rect or source_rect,
                                translated=translated,
                                cell_rect=title_cell,
                                page_rect=page.rect,
                                occupied=occupied,
                                font=font,
                                visual_pixmap=visual_pixmap,
                            )
                            if title_cell is not None
                            else _inline_only_rect(
                                placement_anchor,
                                translated=translated,
                                page_rect=page.rect,
                                occupied=occupied,
                                font=font,
                                rotation=rotation,
                                visual_pixmap=visual_pixmap,
                                max_local_distance=max_local_distance,
                            )
                        )
                        if candidate is None:
                            if legacy_fallback is None:
                                audit_entry["status"] = "rejected_review_target_collision"
                                audit_entry["target_bbox"] = list(review_target)
                                placement_audit.append(audit_entry)
                                unplaced += 1
                                continue
                            candidate = (
                                legacy_fallback,
                                _legacy_fallback_font_size(region, legacy_fallback),
                                0.0,
                            )
                            fallback_used = True
                        else:
                            review_target_reflowed = True
                    else:
                        candidate = (
                            review_target,
                            float(region.get("review_font_size") or 0),
                            0.0,
                        )
                else:
                    if v3_planned:
                        candidate = None
                        for planned_rect in _planned_candidate_rects(region):
                            fitted = _fit_v3_declared_region(
                                planned_rect,
                                translated=translated,
                                requested_font_size=float(region.get("review_font_size") or 0),
                                rotation=rotation,
                                font=font,
                                page_rect=page.rect,
                                placement_bounds=placement_bounds,
                                occupied=v3_caption_obstacles,
                                pixmap=visual_pixmap,
                                source_obstacles=native_source_word_obstacles,
                                max_source_overlap_ratio=_v3_source_overlap_limit(region),
                                visual_ink_limit=(
                                    1.0
                                    if region.get("multimodal_visual_whitespace_override")
                                    else
                                    _V3_DENSE_VISUAL_INK_RATIO_LIMIT
                                    if region.get("allow_dense_source_overlap")
                                    else _V3_RELAXED_VISUAL_INK_RATIO_LIMIT
                                    if region.get("allow_source_overlap")
                                    else _V3_VISUAL_INK_RATIO_LIMIT
                                ),
                                min_font_size=(2.4 if region.get("allow_source_overlap") else 2.8),
                            )
                            if fitted is None:
                                audit_entry["candidate_rejections"].append(
                                    {
                                        "bbox": list(planned_rect),
                                        "reason": "declared_target_not_clear_or_text_did_not_fit",
                                    }
                                )
                                continue
                            fitted_rect, fitted_font = fitted
                            candidate = (fitted_rect, fitted_font, 0.0)
                            break
                        if candidate is None:
                            audit_entry["status"] = "rejected_v3_no_declared_target"
                            audit_entry["manual_review_required"] = True
                            audit_entry["manual_review_reason"] = "multimodal_plan_did_not_supply_a_clear_target"
                            placement_audit.append(audit_entry)
                            unplaced += 1
                            continue
                    else:
                        candidate = (
                            _title_block_candidate(
                                layout_source_rect or source_rect,
                                translated=translated,
                                cell_rect=title_cell,
                                page_rect=page.rect,
                                occupied=occupied,
                                font=font,
                                visual_pixmap=visual_pixmap,
                            )
                            if title_cell is not None
                            else _inline_only_rect(
                                placement_anchor,
                                translated=translated,
                                page_rect=page.rect,
                                occupied=occupied,
                                font=font,
                                rotation=rotation,
                                visual_pixmap=visual_pixmap,
                                max_local_distance=max_local_distance,
                            )
                        )
                        if candidate is None and legacy_fallback is not None:
                            candidate = (
                                legacy_fallback,
                                _legacy_fallback_font_size(region, legacy_fallback),
                                0.0,
                            )
                            fallback_used = True
                if candidate is None:
                    audit_entry["status"] = "rejected_no_near_space"
                    placement_audit.append(audit_entry)
                    unplaced += 1
                    continue
                rect, font_size, distance = candidate
                visual_pad = fitz.Rect(
                    rect.x0 - 1.5,
                    rect.y0 - 1.5,
                    rect.x1 + 1.5,
                    rect.y1 + 1.5,
                )
                audit_entry["visual_ink_ratio"] = round(
                    _visual_ink_ratio(
                        visual_pad,
                        pixmap=visual_pixmap,
                        page_rect=page.rect,
                    ),
                    4,
                )
                conflict_occupied = [
                    other
                    for other in occupied
                    if not (
                        fallback_used
                        and legacy_fallback is not None
                        and other == legacy_fallback
                    )
                ]
                fallback_visual_conflict = fallback_used and (
                    not _is_clear(rect, conflict_occupied, page.rect)
                    or not _is_visual_clear(
                        rect,
                        pixmap=visual_pixmap,
                        page_rect=page.rect,
                    )
                )
                layout_rect = layout_source_rect or source_rect
                actual_distance = max(
                    layout_rect.x0 - rect.x1,
                    rect.x0 - layout_rect.x1,
                    layout_rect.y0 - rect.y1,
                    rect.y0 - layout_rect.y1,
                    0.0,
                )
                leader_path: list[tuple[float, float]] | None = None
                leader_requested = bool(
                    region.get("leader_required")
                    or region.get("leader") == "required"
                    or str(region.get("placement_mode") or "") == "leader"
                )
                placement_side = str(region.get("placement_side") or "").casefold()
                # Left/right/above/below are valid nearby placement choices.
                # Only an explicit supervisor leader decision requires a
                # routed connector; do not turn a close inline caption into a
                # false strict-route failure merely because it is on the left.
                v3_leader_required = v3_planned and leader_requested
                if (
                    draw_leaders
                    and not fallback_used
                    and (not title_or_table or v3_planned)
                    and (
                        v3_leader_required
                        or (not v3_planned and (actual_distance > 20.0 or leader_requested))
                    )
                ):
                    explicit_path = _planned_leader_path(region) if v3_planned else []
                    if explicit_path and _planned_leader_is_clear(
                        explicit_path,
                        page_rect=page.rect,
                        # An explicit V3 path is the multimodal model's
                        # reviewed route. The deterministic pass still checks
                        # orthogonality, page bounds, and leader-to-leader
                        # collisions, but does not reinterpret the model's
                        # raster obstacle mask as a new route decision.
                        obstacles=[],
                        existing_segments=leader_segments,
                        pixmap=None,
                        allow_diagonal=v3_planned,
                    ):
                        leader_path = explicit_path
                    elif strict_v34:
                        audit_entry["leader"] = {
                            "status": "rejected_strict_planned_route",
                            "path": explicit_path,
                        }
                        audit_entry["manual_review_required"] = True
                        audit_entry["manual_review_reason"] = "strict_planned_leader_route_invalid"
                    else:
                        leader_path = _orthogonal_leader_path(
                            source_rect,
                            rect,
                            page_rect=page.rect,
                            obstacles=(
                                leader_caption_obstacles
                                if v3_planned
                                else occupied
                            ),
                            existing_segments=leader_segments,
                            pixmap=(None if v3_planned else visual_pixmap),
                        )
                    if leader_path is None:
                        audit_entry["leader"] = {"status": "unroutable", "path": []}
                        if v3_leader_required:
                            audit_entry["leader"]["advisory"] = "planned_short_route_unavailable"
                        elif leader_requested:
                            audit_entry["manual_review_required"] = True
                            audit_entry["manual_review_reason"] = "planned_leader_route_is_not_clear"
                planned_color = region.get("planned_color") or _LEADER_COLOR
                color = tuple(float(channel) for channel in planned_color)
                render_text = str(region.get("render_text") or translated)
                exact_rotation = (
                    0
                    if str(region.get("leader_caption_orientation") or "").casefold() == "horizontal"
                    or region.get("leader_caption_rotation") == 0
                    else rotation
                )
                inserted = (
                    _insert_textbox_exact(
                        page,
                        rect,
                        render_text,
                        font_path=selected_font_path,
                        font_size=font_size,
                        color=color,
                        rotate=exact_rotation,
                    )
                    if strict_v34
                    else _insert_textbox_fitted(
                        page,
                        rect,
                        translated,
                        font_path=selected_font_path,
                        font_size=font_size,
                        min_font_size=(
                            2.2
                            if fallback_used
                            else 2.4
                            if v3_planned and region.get("allow_source_overlap")
                            else 2.8
                        ),
                        color=color,
                        rotate=exact_rotation,
                    )
                )
                if inserted < 0 and not fallback_used and legacy_fallback is not None and not v3_planned:
                    # A wider automatic slot can still be too short for a
                    # compact equipment label.  Retry at the authoritative
                    # legacy box before declaring the translation missing.
                    rect = legacy_fallback
                    font_size = _legacy_fallback_font_size(region, rect)
                    distance = 0.0
                    fallback_used = True
                    leader_path = None
                    fallback_visual_conflict = (
                        not _is_clear(
                            rect,
                            [
                                other
                                for other in occupied
                                if not (
                                    legacy_fallback is not None
                                    and other == legacy_fallback
                                )
                            ],
                            page.rect,
                        )
                        or not _is_visual_clear(
                            rect,
                            pixmap=visual_pixmap,
                            page_rect=page.rect,
                        )
                    )
                    inserted = _insert_textbox_fitted(
                        page,
                        rect,
                        translated,
                        font_path=selected_font_path,
                        font_size=font_size,
                        min_font_size=2.2,
                        color=_LEADER_COLOR,
                        rotate=rotation,
                    )
                if inserted < 0:
                    audit_entry["status"] = "rejected_text_did_not_fit"
                    placement_audit.append(audit_entry)
                    unplaced += 1
                    continue
                actual_distance = max(
                    source_rect.x0 - rect.x1,
                    rect.x0 - source_rect.x1,
                    source_rect.y0 - rect.y1,
                    rect.y0 - source_rect.y1,
                    0.0,
                )
                if leader_path is not None:
                    _draw_orthogonal_leader(page, leader_path)
                    leader_segments.extend(_leader_segments(leader_path))
                    audit_entry["leader"] = {
                        "status": "drawn",
                        "path": [[round(x, 3), round(y, 3)] for x, y in leader_path],
                    }
                occupied.append(rect)
                v3_caption_obstacles.append(rect)
                leader_caption_obstacles.append(rect)
                audit_entry.update(
                    {
                        "status": (
                            "inline_legacy_fallback"
                            if fallback_used
                            else "inline_reflowed_after_review_collision"
                            if review_target_reflowed
                            else "inline_reviewed"
                            if review_target is not None
                            else "inline_near"
                        ),
                        "target_bbox": list(rect),
                        "distance": round(actual_distance, 3),
                        "placement_bounds": list(placement_bounds),
                        "target_inside_page": page.rect.contains(rect),
                    }
                )
                if fallback_used:
                    audit_entry["fallback_reason"] = (
                        "preserve_authoritative_legacy_position_after_no_safe_nearby_slot"
                    )
                    if fallback_visual_conflict:
                        audit_entry["manual_review_required"] = True
                        audit_entry["manual_review_reason"] = (
                            "authoritative_legacy_caption_preserved_but_visual_conflict_remains"
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
    optimize: bool = True,
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
        # The normal path keeps its compact, fully-cleaned output.  A private
        # reference-delivery batch already preserves the complete source page
        # unchanged and can safely skip expensive stream rewriting; this makes
        # bounded foreground rendering practical without changing any text or
        # placement semantics.
        output.save(
            output_pdf_path,
            garbage=4 if optimize else 1,
            deflate=optimize,
            clean=optimize,
        )
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
