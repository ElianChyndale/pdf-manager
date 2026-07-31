from __future__ import annotations

"""Semantic grouping for fragmented engineering-drawing text observations.

OCR and vector extraction commonly split one drawing label into several records.
Rendering each record independently produces scattered Chinese characters, most
visibly on vertically orientated equipment names.  This module is intentionally
pure: it accepts region dictionaries and returns serialisable group dictionaries
without changing the original records or deciding their final placement.
"""

from dataclasses import dataclass
from hashlib import sha1
import math
import re
from typing import Iterable


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_OR_DIGIT_RE = re.compile(r"[A-Za-z0-9]")
_TECHNICAL_RE = re.compile(
    r"(?:\b(?:hv|lv|mv|kv|v|a|hz|mm|m2|m3|mva|kva|gis|msb|db|fcu|ahu|"
    r"transformer|tank|pump|pipe|cable|panel|switch|room|floor|level|line|"
    r"station|building|chamber|manhole|drain|valve|duct|tray|generator)\b|"
    r"\d\s*(?:/|x|×|-)|[/#])",
    re.IGNORECASE,
)
_HARD_ROW_BREAK_RE = re.compile(r"[:;]\s*$")
_FIELD_ROW_RE = re.compile(
    r"^\s*(?:DRAWN|CHECKED|DESIGNED|APPROVED|SCALE|DATE|REV(?:ISION)?|"
    r"DRAWING(?:\s+NO(?:\.?|\b)|\s+TITLE)?|PROJECT\s+TITLE|"
    r"SERVICES\s+TITLE|SHEET|PAGE|NO\.?)\s*:?[ \t]*$",
    re.IGNORECASE,
)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*]|(?:[ivxlcdm]+|\d+|[a-z])[\).:])\s+", re.IGNORECASE)
_LITERAL_ONLY_RE = re.compile(
    r"^\s*(?:[A-Z]{1,5}[-_/]?\d+[A-Z0-9._/-]*|\d+(?:[./x×-]\d+)*\s*(?:mm|cm|m|kv|v|a|hz|m2|m3|%)?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticGroupingConfig:
    """Conservative geometry thresholds for adjacent label fragments."""

    max_primary_gap: float = 36.0
    min_primary_gap: float = 8.0
    min_cross_axis_overlap: float = 0.35
    max_stacked_gap: float = 24.0
    max_candidate_neighbors: int = 12
    paragraph_blocks: bool = True
    max_paragraph_gap_factor: float = 2.15
    max_paragraph_gap_points: float = 42.0
    min_paragraph_x_overlap: float = 0.28


@dataclass(frozen=True)
class _Fragment:
    index: int
    raw: dict
    region_id: str
    page_index: int
    source_text: str
    translated_text: str
    bbox: tuple[float, float, float, float] | None
    rotation: int

    @property
    def valid_geometry(self) -> bool:
        return self.bbox is not None


class _DisjointSet:
    def __init__(self, count: int) -> None:
        self._parent = list(range(count))

    def find(self, value: int) -> int:
        while self._parent[value] != value:
            self._parent[value] = self._parent[self._parent[value]]
            value = self._parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self._parent[right_root] = left_root


def _normalized(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _page_index(raw: dict) -> int:
    try:
        if "page_index" in raw:
            return max(0, int(raw.get("page_index", 0)))
        return max(0, int(raw.get("page_number", 1)) - 1)
    except (TypeError, ValueError):
        return 0


def _rotation(value: object) -> int:
    try:
        rotation = int(float(value or 0)) % 360
    except (TypeError, ValueError):
        return 0
    return rotation if rotation in {0, 90, 180, 270} else 0


def _bbox(raw: dict) -> tuple[float, float, float, float] | None:
    value = raw.get("source_group_bbox") or raw.get("bbox") or raw.get("source_bbox")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (x0, y0, x1, y1)) or x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _fragments(regions: Iterable[dict]) -> list[_Fragment]:
    result: list[_Fragment] = []
    for index, value in enumerate(regions):
        raw = dict(value)
        result.append(
            _Fragment(
                index=index,
                raw=raw,
                region_id=_normalized(raw.get("region_id")) or f"observation-{index + 1:05d}",
                page_index=_page_index(raw),
                source_text=_normalized(raw.get("source_text") or raw.get("source_group_text")),
                translated_text=_normalized(raw.get("translated_text")),
                bbox=_bbox(raw),
                rotation=_rotation(raw.get("rotation")),
            )
        )
    return result


def _primary_bounds(fragment: _Fragment) -> tuple[float, float]:
    assert fragment.bbox is not None
    x0, y0, x1, y1 = fragment.bbox
    if fragment.rotation == 0:
        return x0, x1
    if fragment.rotation == 180:
        return -x1, -x0
    if fragment.rotation == 90:
        return -y1, -y0
    return y0, y1


def _cross_bounds(fragment: _Fragment) -> tuple[float, float]:
    assert fragment.bbox is not None
    x0, y0, x1, y1 = fragment.bbox
    return (y0, y1) if fragment.rotation in {0, 180} else (x0, x1)


def _cross_extent(fragment: _Fragment) -> float:
    start, end = _cross_bounds(fragment)
    return end - start


def _cross_overlap(left: _Fragment, right: _Fragment) -> float:
    left_start, left_end = _cross_bounds(left)
    right_start, right_end = _cross_bounds(right)
    return max(0.0, min(left_end, right_end) - max(left_start, right_start))


def _cross_aligned(left: _Fragment, right: _Fragment, config: SemanticGroupingConfig) -> bool:
    overlap = _cross_overlap(left, right)
    smallest = min(_cross_extent(left), _cross_extent(right))
    if smallest and overlap / smallest >= config.min_cross_axis_overlap:
        return True
    left_start, left_end = _cross_bounds(left)
    right_start, right_end = _cross_bounds(right)
    center_distance = abs((left_start + left_end - right_start - right_end) / 2)
    return center_distance <= max(2.5, min(_cross_extent(left), _cross_extent(right)) * 0.65)


def _intersection_ratio(left: _Fragment, right: _Fragment) -> float:
    assert left.bbox is not None and right.bbox is not None
    x0 = max(left.bbox[0], right.bbox[0])
    y0 = max(left.bbox[1], right.bbox[1])
    x1 = min(left.bbox[2], right.bbox[2])
    y1 = min(left.bbox[3], right.bbox[3])
    overlap = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    left_area = (left.bbox[2] - left.bbox[0]) * (left.bbox[3] - left.bbox[1])
    right_area = (right.bbox[2] - right.bbox[0]) * (right.bbox[3] - right.bbox[1])
    return overlap / min(left_area, right_area) if left_area and right_area else 0.0


def _technical_signal(text: str) -> bool:
    normalized = _normalized(text)
    if not normalized:
        return False
    return bool(_TECHNICAL_RE.search(normalized)) or (
        len(normalized) <= 5 and normalized.isupper() and _LATIN_OR_DIGIT_RE.search(normalized)
    )


def _metadata_frame(fragment: _Fragment) -> str:
    """Return an explicit OCR/table frame id when the upstream stage supplied one."""
    for key in (
        "semantic_frame_id",
        "text_block_id",
        "layout_group_id",
        "table_cell_id",
        "cell_id",
        "block_id",
    ):
        value = _normalized(fragment.raw.get(key))
        if value:
            return value
    return ""


def _field_row(text: str) -> bool:
    return bool(_FIELD_ROW_RE.match(_normalized(text)))


def _paragraph_signal(text: str) -> bool:
    """Identify sentence-like text without treating every technical label as prose."""
    normalized = _normalized(text)
    if not normalized or _field_row(normalized) or _LITERAL_ONLY_RE.match(normalized):
        return False
    if _LIST_ITEM_RE.match(normalized):
        # A bullet can introduce a paragraph, but numbered/roman list entries
        # are usually independent title-block or schedule rows.
        return normalized.startswith(("-", "*"))
    words = re.findall(r"[A-Za-z]{2,}", normalized)
    punctuation = bool(re.search(r"[,.;:()]", normalized))
    return len(normalized) >= 20 or len(words) >= 4 or (punctuation and len(words) >= 2)


def _paragraph_heading(text: str) -> bool:
    """Allow a short heading to attach to its following sentence block."""
    normalized = _normalized(text)
    return bool(normalized and normalized.endswith(":") and len(normalized) >= 6)


def _short_label(text: str) -> bool:
    normalized = _normalized(text)
    words = re.findall(r"[A-Za-z]{2,}", normalized)
    return bool(normalized and len(normalized) <= 18 and len(words) <= 3 and not re.search(r"[,.;:()]", normalized))


def _paragraph_related(
    upper: _Fragment,
    lower: _Fragment,
    config: SemanticGroupingConfig,
) -> bool:
    """Join adjacent lines that form one readable note/title block.

    This deliberately requires stronger evidence than the technical-label
    joiner.  It protects title-block field rows, identifiers and neighbouring
    schedule entries from being translated as one paragraph.
    """
    if not config.paragraph_blocks or upper.rotation not in {0, 180} or lower.rotation != upper.rotation:
        return False
    if not upper.source_text or not lower.source_text:
        return False
    if _field_row(upper.source_text) or _field_row(lower.source_text):
        return False
    if not (
        (_paragraph_signal(upper.source_text) or _paragraph_heading(upper.source_text))
        and (_paragraph_signal(lower.source_text) or _paragraph_heading(lower.source_text))
    ):
        return False
    upper_frame = _metadata_frame(upper)
    lower_frame = _metadata_frame(lower)
    if upper_frame and lower_frame and upper_frame != lower_frame:
        return False
    assert upper.bbox is not None and lower.bbox is not None
    vertical_gap = lower.bbox[1] - upper.bbox[3]
    height = max(upper.bbox[3] - upper.bbox[1], lower.bbox[3] - lower.bbox[1])
    gap_limit = min(config.max_paragraph_gap_points, max(8.0, height * config.max_paragraph_gap_factor + 2.0))
    if vertical_gap < -min(2.0, height * 0.2) or vertical_gap > gap_limit:
        return False
    overlap = max(0.0, min(upper.bbox[2], lower.bbox[2]) - max(upper.bbox[0], lower.bbox[0]))
    smallest_width = min(upper.bbox[2] - upper.bbox[0], lower.bbox[2] - lower.bbox[0])
    left_aligned = abs(upper.bbox[0] - lower.bbox[0]) <= max(8.0, height * 1.4)
    if not smallest_width or not (overlap / smallest_width >= config.min_paragraph_x_overlap or left_aligned):
        return False
    # A real paragraph normally keeps a regular line rhythm.  A larger gap
    # after terminal punctuation is treated as a new block even if the boxes
    # happen to share the same left edge.
    if re.search(r"[.!?]\s*$", upper.source_text) and vertical_gap > height * 1.25:
        return False
    return True


def _short_cjk_fragment(fragment: _Fragment) -> bool:
    """Return whether a legacy record is a split vertical Chinese glyph run.

    Older translated sheets frequently encode a vertical label as independent
    1-2 character horizontal records.  It has no extractable source anchor, so
    source-text based grouping alone cannot repair it.  Complete Chinese labels
    are deliberately excluded to avoid joining neighbouring legend entries.
    """
    if fragment.source_text or not fragment.translated_text:
        return False
    compact = re.sub(r"\s+", "", fragment.translated_text)
    cjk_count = len(_CJK_RE.findall(compact))
    non_cjk = _CJK_RE.sub("", compact)
    return 1 <= cjk_count <= 2 and len(non_cjk) <= 1


def _same_cjk_column(upper: _Fragment, lower: _Fragment) -> bool:
    """Require nearly identical columns for source-less vertical CJK runs."""
    assert upper.bbox is not None and lower.bbox is not None
    upper_width = upper.bbox[2] - upper.bbox[0]
    lower_width = lower.bbox[2] - lower.bbox[0]
    overlap = max(0.0, min(upper.bbox[2], lower.bbox[2]) - max(upper.bbox[0], lower.bbox[0]))
    smallest = min(upper_width, lower_width)
    centers = abs((upper.bbox[0] + upper.bbox[2] - lower.bbox[0] - lower.bbox[2]) / 2)
    return bool(smallest) and (
        overlap / smallest >= 0.78 or centers <= max(1.5, smallest * 0.22)
    )


def _can_join_text(left: _Fragment, right: _Fragment, *, gap: float, tight_gap: float) -> bool:
    if _short_cjk_fragment(left) and _short_cjk_fragment(right):
        return gap <= min(8.5, max(2.5, tight_gap))
    if not left.source_text or not right.source_text:
        return False
    if _HARD_ROW_BREAK_RE.search(left.source_text) and gap > tight_gap:
        return False
    if gap <= tight_gap:
        return True
    return _technical_signal(left.source_text) or _technical_signal(right.source_text)


def _inline_related(
    left: _Fragment,
    right: _Fragment,
    config: SemanticGroupingConfig,
) -> bool:
    if _intersection_ratio(left, right) >= 0.65 or not _cross_aligned(left, right, config):
        return False
    left_start, left_end = _primary_bounds(left)
    right_start, _right_end = _primary_bounds(right)
    gap = right_start - left_end
    thickness = max(_cross_extent(left), _cross_extent(right))
    gap_limit = min(config.max_primary_gap, max(config.min_primary_gap, thickness * 2.5 + 2.0))
    if gap < -min(2.0, thickness * 0.2) or gap > gap_limit:
        return False
    if _short_cjk_fragment(left) and _short_cjk_fragment(right):
        # For a horizontal source-less CJK run, the regular cross axis is the
        # correct narrow lane. This prevents fragments from nearby labels from
        # connecting merely because their bounding boxes touch.
        cross_overlap = _cross_overlap(left, right)
        smallest_cross = min(_cross_extent(left), _cross_extent(right))
        if not smallest_cross or cross_overlap / smallest_cross < 0.78:
            return False
    return _can_join_text(left, right, gap=gap, tight_gap=max(4.0, thickness * 0.85))


def _stacked_related(
    upper: _Fragment,
    lower: _Fragment,
    config: SemanticGroupingConfig,
) -> bool:
    """Identify wrapped horizontal technical labels without joining table rows."""
    if upper.rotation not in {0, 180} or lower.rotation != upper.rotation:
        return False
    # A dimension or identifier is a literal, not a wrapped prose line.  A
    # short room/equipment label must also stay independent when it sits next
    # to a longer note; this is a common title-block and legend pattern.
    if _LITERAL_ONLY_RE.match(upper.source_text) or _LITERAL_ONLY_RE.match(lower.source_text):
        return False
    if (
        _short_label(upper.source_text) != _short_label(lower.source_text)
        and (_paragraph_signal(upper.source_text) or _paragraph_signal(lower.source_text))
    ):
        return False
    assert upper.bbox is not None and lower.bbox is not None
    vertical_gap = lower.bbox[1] - upper.bbox[3]
    height = max(upper.bbox[3] - upper.bbox[1], lower.bbox[3] - lower.bbox[1])
    if vertical_gap < -min(2.0, height * 0.2) or vertical_gap > min(config.max_stacked_gap, height * 1.7 + 3.0):
        return False
    x_overlap = max(0.0, min(upper.bbox[2], lower.bbox[2]) - max(upper.bbox[0], lower.bbox[0]))
    smallest_width = min(upper.bbox[2] - upper.bbox[0], lower.bbox[2] - lower.bbox[0])
    left_aligned = abs(upper.bbox[0] - lower.bbox[0]) <= max(4.0, height * 0.8)
    if not (smallest_width and (x_overlap / smallest_width >= 0.4 or left_aligned)):
        return False
    if _HARD_ROW_BREAK_RE.search(upper.source_text):
        return False
    if _short_cjk_fragment(upper) and _short_cjk_fragment(lower):
        # A split glyph run is much tighter than adjacent legend rows. The
        # narrow gap requirement is what keeps ``保温 / 冷凝 / 水管`` together
        # without merging the next complete Chinese legend label.
        return _same_cjk_column(upper, lower) and vertical_gap <= min(
            6.5,
            max(1.75, height * 0.75 + 1.0),
        )
    # A stacked merge is intentionally stricter than an inline merge. This
    # prevents title-block fields such as DRAWN / CHECKED from becoming one row.
    return _technical_signal(upper.source_text) or _technical_signal(lower.source_text)


def _reading_key(fragment: _Fragment) -> tuple[float, float, int]:
    assert fragment.bbox is not None
    x0, y0, x1, y1 = fragment.bbox
    if fragment.rotation == 0:
        return ((y0 + y1) / 2, x0, fragment.index)
    if fragment.rotation == 180:
        return ((y0 + y1) / 2, -x1, fragment.index)
    if fragment.rotation == 90:
        return ((x0 + x1) / 2, -y1, fragment.index)
    return ((x0 + x1) / 2, y0, fragment.index)


def _bbox_union(fragments: list[_Fragment]) -> list[float]:
    boxes = [fragment.bbox for fragment in fragments if fragment.bbox is not None]
    if not boxes:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _source_anchor_union(fragments: list[_Fragment]) -> list[float] | None:
    """Return the union of actual source-line anchors when available."""
    boxes: list[tuple[float, float, float, float]] = []
    for fragment in fragments:
        if not fragment.source_text:
            continue
        value = fragment.raw.get("source_anchor_bbox") or fragment.raw.get("source_bbox")
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            continue
        try:
            box = tuple(float(item) for item in value)
        except (TypeError, ValueError):
            continue
        if len(box) == 4 and all(math.isfinite(item) for item in box) and box[2] > box[0] and box[3] > box[1]:
            boxes.append(box)
    if not boxes:
        return None
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _join_source(fragments: list[_Fragment]) -> str:
    parts: list[str] = []
    for fragment in fragments:
        source = fragment.source_text
        if source and (not parts or source.casefold() != parts[-1].casefold()):
            parts.append(source)
    return " ".join(parts).strip()


def _join_translation(fragments: list[_Fragment], *, paragraph_block: bool = False) -> str:
    parts = [fragment.translated_text for fragment in fragments if fragment.translated_text]
    if not parts:
        return ""
    result = parts[0]
    for part in parts[1:]:
        if result == part:
            continue
        if paragraph_block:
            # Preserve the visual reading order of a wrapped note.  The
            # renderer measures split lines and can reflow them as one block;
            # a space-only join would recreate the scattered-word problem.
            result = f"{result.rstrip()}\n{part.lstrip()}"
            continue
        previous = result[-1:]
        following = part[:1]
        if previous in "([{/" or following in ")]},.;:!?/":
            separator = ""
        elif _CJK_RE.search(previous) and _CJK_RE.search(following):
            separator = ""
        else:
            separator = " "
        result = f"{result}{separator}{part}"
    return result


def _group_id(page_index: int, rotation: int, fragments: list[_Fragment]) -> str:
    identity = "|".join(
        f"{fragment.region_id}:{fragment.source_text}:{fragment.bbox}"
        for fragment in fragments
    )
    digest = sha1(f"{page_index}:{rotation}:{identity}".encode("utf-8")).hexdigest()[:12]
    return f"p{page_index + 1:03d}-semantic-{digest}"


def _uniform_value(fragments: list[_Fragment], key: str, default: object = "") -> object:
    values = [fragment.raw.get(key) for fragment in fragments if fragment.raw.get(key) not in (None, "")]
    if not values:
        return default
    first = values[0]
    return first if all(value == first for value in values[1:]) else default


def _merged_flags(fragments: list[_Fragment]) -> list[str]:
    flags: set[str] = set()
    for fragment in fragments:
        flags.update(
            str(flag).strip()
            for flag in fragment.raw.get("qa_flags", [])
            if str(flag).strip()
        )
    return sorted(flags)


def _minimum_confidence(fragments: list[_Fragment]) -> float:
    values: list[float] = []
    for fragment in fragments:
        try:
            value = float(fragment.raw.get("ocr_confidence"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    return min(values, default=0.0)


def _group_dict(
    fragments: list[_Fragment],
    *,
    relationship_kinds: set[str],
) -> dict:
    ordered = sorted(fragments, key=_reading_key) if all(fragment.bbox is not None for fragment in fragments) else list(fragments)
    page_index = ordered[0].page_index
    rotation = ordered[0].rotation
    member_ids = [fragment.region_id for fragment in ordered]
    source_bbox = _bbox_union(ordered)
    source_anchor_bbox = _source_anchor_union(ordered) or source_bbox
    if len(ordered) == 1:
        group_kind = "atomic"
    elif "paragraph" in relationship_kinds:
        group_kind = "paragraph_block"
    elif "cjk_fragment" in relationship_kinds:
        group_kind = "split_cjk_label"
    elif "stacked" in relationship_kinds:
        group_kind = "stacked_technical_label"
    else:
        group_kind = "inline_technical_label"
    translated = _join_translation(ordered, paragraph_block=group_kind == "paragraph_block")
    translation_status = (
        "missing"
        if not translated
        else "complete" if all(fragment.translated_text for fragment in ordered) else "partial"
    )
    group_id = _group_id(page_index, rotation, ordered)
    provenance = _uniform_value(ordered, "provenance", "semantic_group")
    result = {
        "group_id": group_id,
        "semantic_group_id": group_id,
        "region_id": group_id,
        "page_index": page_index,
        "page_number": page_index + 1,
        "source_group_text": _join_source(ordered),
        "source_group_bbox": source_bbox,
        # These aliases make the result easy to feed into existing review and
        # rendering adapters while they are migrated to group-aware input.
        "source_text": _join_source(ordered),
        "bbox": source_bbox,
        "source_anchor_bbox": source_anchor_bbox,
        "placement_anchor_bbox": source_anchor_bbox,
        "legacy_bbox": source_bbox,
        "translated_text": translated,
        "translation_status": translation_status,
        "rotation": rotation,
        "source_language": _uniform_value(ordered, "source_language", "mixed"),
        "provenance": provenance,
        "action": _uniform_value(ordered, "action", "translate"),
        "placement": _uniform_value(ordered, "placement", "inline_only"),
        "ai_judgement": _uniform_value(ordered, "ai_judgement", "review"),
        "coverage_status": "translated" if translation_status == "complete" else translation_status,
        "qa_flags": _merged_flags(ordered),
        "ocr_confidence": _minimum_confidence(ordered),
        "member_region_ids": member_ids,
        "covered_region_ids": member_ids,
        "member_count": len(ordered),
        "semantic_group_kind": group_kind,
        "translation_unit": "one_block" if group_kind == "paragraph_block" else "one_label",
        "source_lines": [fragment.source_text for fragment in ordered if fragment.source_text],
        "translation_lines": [fragment.translated_text for fragment in ordered if fragment.translated_text],
        "block_translation_required": group_kind == "paragraph_block",
        "members": [
            {
                "region_id": fragment.region_id,
                "source_text": fragment.source_text,
                "translated_text": fragment.translated_text,
                "bbox": list(fragment.bbox) if fragment.bbox is not None else None,
                "rotation": fragment.rotation,
            }
            for fragment in ordered
        ],
    }
    if provenance == "legacy_translation":
        result["legacy_bbox"] = list(source_bbox)
        result["placement_anchor_bbox"] = list(source_bbox)
    return result


def build_semantic_groups(
    regions: Iterable[dict],
    *,
    config: SemanticGroupingConfig | None = None,
) -> list[dict]:
    """Return conservative, atomic semantic groups for drawing text records.

    The grouping never crosses a page or rotation, never joins overlapping OCR
    duplicates, and leaves every input record represented by exactly one group.
    Adjacent pieces such as ``275/11/11kV`` / ``HV`` / ``TRANSFORMER B-2`` are
    joined in their visual reading direction, including 90- and 270-degree CAD
    labels.  Sentence-like wrapped lines are joined into a newline-preserving
    paragraph block, while identifiers, dimensions, independent labels and
    title-block field rows remain separate.  No translation is invented; existing
    translated fragments are only joined into one readable target string.
    """
    resolved_config = config or SemanticGroupingConfig()
    fragments = _fragments(regions)
    if not fragments:
        return []
    disjoint_set = _DisjointSet(len(fragments))
    relationship_by_pair: dict[tuple[int, int], str] = {}
    buckets: dict[tuple[int, int], list[_Fragment]] = {}
    for fragment in fragments:
        if fragment.valid_geometry:
            buckets.setdefault((fragment.page_index, fragment.rotation), []).append(fragment)

    for bucket in buckets.values():
        by_primary = sorted(bucket, key=lambda fragment: (*_primary_bounds(fragment), fragment.index))
        for position, left in enumerate(by_primary):
            _left_start, left_end = _primary_bounds(left)
            for right in by_primary[position + 1 : position + 1 + resolved_config.max_candidate_neighbors]:
                right_start, _right_end = _primary_bounds(right)
                if right_start - left_end > resolved_config.max_primary_gap:
                    break
                if not _inline_related(left, right, resolved_config):
                    continue
                disjoint_set.union(left.index, right.index)
                relationship_by_pair[tuple(sorted((left.index, right.index)))] = (
                    "cjk_fragment"
                    if _short_cjk_fragment(left) and _short_cjk_fragment(right)
                    else "inline"
                )

        if bucket[0].rotation in {0, 180}:
            by_vertical = sorted(bucket, key=lambda fragment: (fragment.bbox[1], fragment.bbox[0], fragment.index))
            for position, upper in enumerate(by_vertical):
                assert upper.bbox is not None
                for lower in by_vertical[position + 1 : position + 1 + resolved_config.max_candidate_neighbors]:
                    assert lower.bbox is not None
                    if lower.bbox[1] - upper.bbox[3] > resolved_config.max_stacked_gap:
                        break
                    if not _stacked_related(upper, lower, resolved_config):
                        continue
                    disjoint_set.union(upper.index, lower.index)
                    relationship_by_pair[tuple(sorted((upper.index, lower.index)))] = (
                        "cjk_fragment"
                        if _short_cjk_fragment(upper) and _short_cjk_fragment(lower)
                        else "stacked"
                    )

            # Paragraph blocks are evaluated after the stricter technical-row
            # pass.  Their evidence is intentionally conservative so a dense
            # table or equipment legend cannot become one large translation.
            for position, upper in enumerate(by_vertical):
                assert upper.bbox is not None
                for lower in by_vertical[position + 1 : position + 1 + resolved_config.max_candidate_neighbors]:
                    assert lower.bbox is not None
                    if lower.bbox[1] - upper.bbox[3] > resolved_config.max_paragraph_gap_points:
                        break
                    if not _paragraph_related(upper, lower, resolved_config):
                        continue
                    disjoint_set.union(upper.index, lower.index)
                    relationship_by_pair[tuple(sorted((upper.index, lower.index)))] = "paragraph"

    grouped: dict[int, list[_Fragment]] = {}
    for fragment in fragments:
        grouped.setdefault(disjoint_set.find(fragment.index), []).append(fragment)

    output: list[dict] = []
    for members in grouped.values():
        member_indexes = {fragment.index for fragment in members}
        relationship_kinds = {
            relationship
            for pair, relationship in relationship_by_pair.items()
            if pair[0] in member_indexes and pair[1] in member_indexes
        }
        output.append(_group_dict(members, relationship_kinds=relationship_kinds))
    return sorted(
        output,
        key=lambda group: (
            int(group["page_index"]),
            float(group["source_group_bbox"][1]),
            float(group["source_group_bbox"][0]),
            str(group["group_id"]),
        ),
    )
