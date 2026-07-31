from __future__ import annotations

"""Geometry-backed visual QA for bilingual engineering drawings.

The renderer writes each Chinese target and leader route into its placement
audit.  This module compares those records against the saved PDF's selectable
Latin text and against the other generated targets.  It intentionally reports
explicit manual-review fallbacks separately. A legacy caption is evidence only;
it must be revalidated under V4 and can never silently pass the visual gate.
"""

import json
from pathlib import Path
import re

import fitz


_LATIN_RE = re.compile(r"[A-Za-z]")
_CLEARANCE = 1.25
_V3_SOURCE_OVERLAP_ADVISORY_RATIO = 0.18


def _rect(value: object) -> fitz.Rect | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        rect = fitz.Rect(*(float(item) for item in value))
    except (TypeError, ValueError):
        return None
    return rect if rect.is_valid and not rect.is_empty and not rect.is_infinite else None


def _expanded(rect: fitz.Rect, amount: float = _CLEARANCE) -> fitz.Rect:
    return fitz.Rect(rect.x0 - amount, rect.y0 - amount, rect.x1 + amount, rect.y1 + amount)


def _intersects(left: fitz.Rect, right: fitz.Rect) -> bool:
    return not (_expanded(left) & _expanded(right)).is_empty


def _latin_word_rects(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    return [
        (str(word[4]), fitz.Rect(word[:4]))
        for word in page.get_text("words")
        if len(word) >= 5 and _LATIN_RE.search(str(word[4]))
    ]


def _is_generated_translation_word(item: dict, target: fitz.Rect, text: str, rect: fitz.Rect) -> bool:
    def fold(value: object) -> str:
        return (
            str(value or "")
            .casefold()
            .replace("\u2010", "-")
            .replace("\u2011", "-")
            .replace("\u2012", "-")
            .replace("\u2013", "-")
            .replace("\u2014", "-")
        )

    translated = fold(item.get("translated_text"))
    folded_text = fold(text)
    if not translated:
        return False
    overlap = target & rect
    if overlap.is_empty:
        return False
    # PyMuPDF's textbox word bbox can extend a fraction past the requested
    # rectangle because of font ascent/descent. Treat a substantial
    # intersection as generated text instead of flagging the translation's
    # own Latin code (VRV, PVC, phone numbers, etc.) as source overlap.
    word_area = max(rect.width * rect.height, 1e-6)
    overlap_ratio = (overlap.width * overlap.height) / word_area
    if overlap_ratio < 0.45:
        return False
    if folded_text in translated:
        return True
    # CJK fonts can expose compatibility/private glyphs in extracted output,
    # so the complete mixed-script word is not always byte-identical to the
    # audit text. Matching one technical Latin/number token is sufficient for
    # the generated textbox, while still leaving unrelated source labels to
    # the visual gate.
    tokens = re.findall(r"[A-Za-z0-9]+", folded_text)
    translated_tokens = set(re.findall(r"[A-Za-z0-9]+", translated))
    return any(token in translated_tokens for token in tokens if len(token) >= 2)


def _segments(path: object) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    if not isinstance(path, list):
        return []
    points: list[tuple[float, float]] = []
    for raw in path:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            return []
        try:
            points.append((float(raw[0]), float(raw[1])))
        except (TypeError, ValueError):
            return []
    return list(zip(points, points[1:]))


def _segment_hits_rect(
    start: tuple[float, float],
    end: tuple[float, float],
    rect: fitz.Rect,
) -> bool:
    padded = _expanded(rect)
    if abs(start[0] - end[0]) <= 0.01:
        return padded.x0 <= start[0] <= padded.x1 and max(min(start[1], end[1]), padded.y0) <= min(max(start[1], end[1]), padded.y1)
    if abs(start[1] - end[1]) <= 0.01:
        return padded.y0 <= start[1] <= padded.y1 and max(min(start[0], end[0]), padded.x0) <= min(max(start[0], end[0]), padded.x1)
    return True


def _segments_intersect(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    (ax, ay), (bx, by) = first
    (cx, cy), (dx, dy) = second
    first_vertical = abs(ax - bx) <= 0.01
    second_vertical = abs(cx - dx) <= 0.01
    if first_vertical and second_vertical:
        return abs(ax - cx) <= _CLEARANCE and max(min(ay, by), min(cy, dy)) <= min(max(ay, by), max(cy, dy))
    if not first_vertical and not second_vertical:
        return abs(ay - cy) <= _CLEARANCE and max(min(ax, bx), min(cx, dx)) <= min(max(ax, bx), max(cx, dx))
    vertical = first if first_vertical else second
    horizontal = second if first_vertical else first
    (vx0, vy0), (vx1, vy1) = vertical
    (hx0, hy0), (hx1, hy1) = horizontal
    # The vertical line crosses the horizontal only when the vertical's x falls
    # within the horizontal segment's x-span (using a small clearance) AND the
    # horizontal's y falls within the vertical segment's y-span. The previous
    # check compared `hx0` (the horizontal's start x) against the vertical's
    # x-span, which missed every genuine mid-segment crossing where the
    # horizontal did not begin exactly on the vertical line.
    vx = (vx0 + vx1) / 2
    hy = (hy0 + hy1) / 2
    return (
        min(hx0, hx1) - _CLEARANCE <= vx <= max(hx0, hx1) + _CLEARANCE
        and min(vy0, vy1) - _CLEARANCE <= hy <= max(vy0, vy1) + _CLEARANCE
    )


def analyze_visual_qa(*, output_pdf_path: Path, placement_audit_path: Path) -> dict:
    """Return V2 layout metrics for a saved drawing PDF."""
    output_pdf_path = Path(output_pdf_path)
    placement_audit_path = Path(placement_audit_path)
    placements = json.loads(placement_audit_path.read_text(encoding="utf-8")).get("placements", [])
    by_page: dict[int, list[dict]] = {}
    for item in placements:
        if not isinstance(item, dict):
            continue
        by_page.setdefault(int(item.get("page_index", 0) or 0), []).append(item)

    visual_overlap_items: list[dict] = []
    visual_overlap_advisory_items: list[dict] = []
    manual_review_items: list[dict] = []
    leader_collision_items: list[dict] = []
    leader_advisory_items: list[dict] = []
    all_leader_segments: dict[int, list[tuple[str, tuple[tuple[float, float], tuple[float, float]]]]] = {}
    v3_pages: set[int] = set()
    untranslated_items: list[dict] = []

    with fitz.open(output_pdf_path) as document:
        for page_index, page_items in by_page.items():
            if any(bool(item.get("multimodal_v3")) for item in page_items):
                v3_pages.add(page_index)
            if not 0 <= page_index < document.page_count:
                for item in page_items:
                    untranslated_items.append({"region_id": item.get("region_id", ""), "reason": "audit_page_outside_output"})
                continue
            latin_rects = _latin_word_rects(document[page_index])
            target_records = [
                (item, _rect(item.get("target_bbox")))
                for item in page_items
                if _rect(item.get("target_bbox")) is not None
            ]
            for item, target in target_records:
                assert target is not None
                source = _rect(item.get("source_bbox"))
                manual = bool(item.get("manual_review_required"))
                overlaps_latin = [
                    rect
                    for text, rect in latin_rects
                    if _intersects(target, rect)
                    and not _is_generated_translation_word(item, target, text, rect)
                ]
                overlaps_target = [
                    other.get("region_id", "")
                    for other, other_target in target_records
                    if other is not item and other_target is not None and _intersects(target, other_target)
                ]
                if overlaps_latin or overlaps_target:
                    issue = {
                        "region_id": item.get("region_id", ""),
                        "page_index": page_index,
                        "latin_overlap_count": len(overlaps_latin),
                        "target_overlap_region_ids": sorted(set(overlaps_target)),
                    }
                    target_area = max(target.width * target.height, 1e-6)
                    source_overlap_area = sum(
                        (target & rect).get_area()
                        for rect in overlaps_latin
                        if not (target & rect).is_empty
                    )
                    source_overlap_ratio = min(1.0, source_overlap_area / target_area)
                    issue["source_overlap_ratio"] = round(source_overlap_ratio, 4)
                    small_v3_source_overlap = (
                        page_index in v3_pages
                        and bool(overlaps_latin)
                        and not overlaps_target
                        and source_overlap_ratio <= _V3_SOURCE_OVERLAP_ADVISORY_RATIO
                    )
                    if small_v3_source_overlap:
                        visual_overlap_advisory_items.append(
                            {**issue, "reason": "small_source_overlap_advisory"}
                        )
                    elif manual:
                        manual_review_items.append({**issue, "reason": item.get("manual_review_reason", "legacy_conflict")})
                    else:
                        visual_overlap_items.append(issue)

                leader = item.get("leader") or {}
                if isinstance(leader, dict) and leader.get("status") == "drawn":
                    for segment in _segments(leader.get("path")):
                        crosses_latin = any(
                            _segment_hits_rect(*segment, word_rect)
                            and (source is None or not _intersects(source, word_rect))
                            and not _is_generated_translation_word(
                                item,
                                target,
                                word_text,
                                word_rect,
                            )
                            for word_text, word_rect in latin_rects
                        )
                        crosses_target = any(
                            other is not item
                            and other_target is not None
                            and _segment_hits_rect(*segment, other_target)
                            for other, other_target in target_records
                        )
                        if crosses_target:
                            issue = {
                                "region_id": item.get("region_id", ""),
                                "page_index": page_index,
                                "reason": "leader_crosses_chinese_caption",
                            }
                            if page_index in v3_pages:
                                leader_advisory_items.append(issue)
                            elif manual:
                                manual_review_items.append(issue)
                            else:
                                leader_collision_items.append(issue)
                        elif crosses_latin:
                            issue = {
                                "region_id": item.get("region_id", ""),
                                "page_index": page_index,
                                "reason": "leader_crosses_background_text",
                            }
                            if page_index in v3_pages:
                                leader_advisory_items.append(issue)
                            elif manual:
                                manual_review_items.append(issue)
                            else:
                                leader_collision_items.append(issue)
                        all_leader_segments.setdefault(page_index, []).append((str(item.get("region_id") or ""), segment))

            for item in page_items:
                status = str(item.get("status") or "")
                coverage = str(item.get("coverage_status") or "translated")
                if status.startswith("rejected") or coverage in {"missing", "low_confidence"}:
                    issue = {
                        "region_id": item.get("region_id", ""),
                        "page_index": page_index,
                        "reason": status if status.startswith("rejected") else coverage,
                    }
                    if item.get("manual_review_required"):
                        manual_review_items.append(issue)
                    else:
                        untranslated_items.append(issue)

    for page_index, page_segments in all_leader_segments.items():
        for index, (region_id, segment) in enumerate(page_segments):
            for other_region_id, other_segment in page_segments[index + 1 :]:
                if region_id != other_region_id and _segments_intersect(segment, other_segment):
                    issue = {
                        "region_id": region_id,
                        "page_index": page_index,
                        "reason": "leader_crosses_leader",
                        "other_region_id": other_region_id,
                    }
                    if page_index in v3_pages:
                        leader_advisory_items.append(issue)
                    else:
                        leader_collision_items.append(issue)

    return {
        "visual_overlap_count": len(visual_overlap_items),
        "visual_overlap_advisory_count": len(visual_overlap_advisory_items),
        "leader_collision_count": len(leader_collision_items),
        "leader_advisory_count": len(leader_advisory_items),
        "untranslated_candidate_count": len(untranslated_items),
        "manual_review_count": len(manual_review_items),
        "visual_overlap_items": visual_overlap_items,
        "visual_overlap_advisory_items": visual_overlap_advisory_items,
        "leader_collision_items": leader_collision_items,
        "leader_advisory_items": leader_advisory_items,
        "untranslated_candidate_items": untranslated_items,
        "manual_review_items": manual_review_items,
        "passed": not visual_overlap_items and not leader_collision_items and not untranslated_items,
    }
