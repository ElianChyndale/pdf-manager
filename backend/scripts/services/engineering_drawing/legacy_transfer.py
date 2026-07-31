from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Iterable

import fitz


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_BLOCKING_ADDITION_FLAGS = {
    "manual_review_required",
    "deepseek_ocr_conflict",
    "low_paddle_confidence",
    "ai_qa_missing",
    "ai_translation_missing",
    "missing_chinese_companion",
}


@dataclass(frozen=True)
class _DisplayLine:
    text: str
    bbox: fitz.Rect
    rotation: int


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _line_rotation(direction: object) -> int:
    if not isinstance(direction, (list, tuple)) or len(direction) != 2:
        return 0
    x, y = float(direction[0]), float(direction[1])
    angle = int(round(math.degrees(math.atan2(-y, x)))) % 360
    return min((0, 90, 180, 270), key=lambda candidate: abs(candidate - angle))


def _display_lines(page: fitz.Page) -> list[_DisplayLine]:
    lines: list[_DisplayLine] = []
    raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES)
    page_rotation = int(page.rotation or 0) % 360
    matrix = page.rotation_matrix
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = _normalize_text(
                "".join(str(span.get("text") or "") for span in line.get("spans", []))
            )
            if not text:
                continue
            bbox = fitz.Rect(line.get("bbox", (0, 0, 0, 0)))
            if bbox.is_empty or bbox.is_infinite:
                continue
            if page_rotation:
                bbox = bbox * matrix
            rotation = (_line_rotation(line.get("dir")) - page_rotation) % 360
            lines.append(_DisplayLine(text=text, bbox=bbox, rotation=rotation))
    return lines


def _center_distance(left: fitz.Rect, right: fitz.Rect) -> float:
    return math.hypot(
        (left.x0 + left.x1 - right.x0 - right.x1) / 2,
        (left.y0 + left.y1 - right.y0 - right.y1) / 2,
    )


def _same_existing_chinese(candidate: _DisplayLine, source_lines: list[_DisplayLine]) -> bool:
    normalized = _normalize_text(candidate.text).casefold()
    for source in source_lines:
        if not _CJK_RE.search(source.text):
            continue
        if _normalize_text(source.text).casefold() != normalized:
            continue
        tolerance = max(4.0, candidate.bbox.height, source.bbox.height)
        if _center_distance(candidate.bbox, source.bbox) <= tolerance:
            return True
    return False


def _nearest_source_line(
    translation: _DisplayLine,
    source_lines: list[_DisplayLine],
    page_rect: fitz.Rect,
) -> _DisplayLine | None:
    candidates = [line for line in source_lines if _LATIN_RE.search(line.text)]
    if not candidates:
        return None

    def score(line: _DisplayLine) -> tuple[int, int, float]:
        intersects = line.bbox.intersects(translation.bbox)
        rotation_delta = min(
            (line.rotation - translation.rotation) % 360,
            (translation.rotation - line.rotation) % 360,
        )
        return (
            0 if intersects else 1,
            rotation_delta,
            _center_distance(line.bbox, translation.bbox),
        )

    nearest = min(candidates, key=score)
    if nearest.bbox.intersects(translation.bbox):
        return nearest
    distance = _center_distance(nearest.bbox, translation.bbox)
    rotation_delta = min(
        (nearest.rotation - translation.rotation) % 360,
        (translation.rotation - nearest.rotation) % 360,
    )
    if rotation_delta:
        return None
    x_overlap = max(
        0.0,
        min(nearest.bbox.x1, translation.bbox.x1)
        - max(nearest.bbox.x0, translation.bbox.x0),
    )
    y_overlap = max(
        0.0,
        min(nearest.bbox.y1, translation.bbox.y1)
        - max(nearest.bbox.y0, translation.bbox.y0),
    )
    if translation.rotation in {90, 270}:
        aligned = y_overlap >= min(nearest.bbox.height, translation.bbox.height) * 0.35
        axis_gap = max(
            nearest.bbox.x0 - translation.bbox.x1,
            translation.bbox.x0 - nearest.bbox.x1,
            0.0,
        )
    else:
        aligned = x_overlap >= min(nearest.bbox.width, translation.bbox.width) * 0.35
        axis_gap = max(
            nearest.bbox.y0 - translation.bbox.y1,
            translation.bbox.y0 - nearest.bbox.y1,
            0.0,
        )
    distance_limit = min(
        48.0,
        max(12.0, math.hypot(page_rect.width, page_rect.height) * 0.01),
    )
    return nearest if aligned and axis_gap <= distance_limit and distance <= distance_limit * 3 else None


def _token_key(value: str) -> set[str]:
    """Return comparable technical/name tokens without punctuation noise."""
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(_normalize_text(value))
        if len(token) >= 2
    }


def _match_source_line(
    translation: _DisplayLine,
    source_lines: list[_DisplayLine],
    page_rect: fitz.Rect,
) -> _DisplayLine | None:
    """Match a translated line by shared identifiers before using proximity.

    Title blocks contain many short neighbouring lines. Pure nearest-neighbour
    matching routinely attaches a company/address translation to the heading
    above it. Shared company names, registration numbers, drawing codes, and
    phone fragments are stronger evidence and keep the original English anchor
    intact for V2 placement.
    """
    translation_tokens = _token_key(translation.text)
    candidates = [line for line in source_lines if _LATIN_RE.search(line.text)]
    if translation_tokens and candidates:
        scored: list[tuple[int, int, int, float, _DisplayLine]] = []
        for line in candidates:
            source_tokens = _token_key(line.text)
            shared = translation_tokens & source_tokens
            if not shared:
                continue
            # Prefer more shared tokens, then longer identifiers, then a
            # nearby line. Intersections remain a useful final tie-breaker.
            shared_chars = sum(len(token) for token in shared)
            intersects = line.bbox.intersects(translation.bbox)
            scored.append(
                (
                    len(shared),
                    shared_chars,
                    1 if intersects else 0,
                    -_center_distance(line.bbox, translation.bbox),
                    line,
                )
            )
        if scored:
            scored.sort(key=lambda item: item[:4], reverse=True)
            best = scored[0]
            # A single generic token (for example "TEL") should not override
            # the geometry matcher. Require a meaningful identifier or a
            # genuine overlap with the source line.
            if best[0] >= 2 or best[2] or best[1] >= 5:
                return best[4]
    return _nearest_source_line(translation, source_lines, page_rect)


def extract_legacy_translation_regions(
    *,
    source_pdf_path: Path,
    legacy_pdf_path: Path,
) -> list[dict]:
    """Build trusted bilingual regions from Chinese text in a translated PDF.

    The original drawing remains the rendering base. Only real Unicode CJK text
    found in the human-provided translated PDF is admitted here; Latin OCR
    fragments and text already present in the source drawing are excluded.
    Coordinates are returned in displayed page space so rotated CAD sheets can
    be rendered without applying the page transform a second time.
    """
    source_pdf_path = Path(source_pdf_path)
    legacy_pdf_path = Path(legacy_pdf_path)
    regions: list[dict] = []
    with fitz.open(source_pdf_path) as source, fitz.open(legacy_pdf_path) as legacy:
        if source.page_count != legacy.page_count:
            raise ValueError(
                "Source and translated PDFs must have the same page count "
                f"({source.page_count} != {legacy.page_count})"
            )

        for page_index in range(source.page_count):
            source_page = source[page_index]
            legacy_page = legacy[page_index]
            if (
                abs(source_page.rect.width - legacy_page.rect.width) > 0.5
                or abs(source_page.rect.height - legacy_page.rect.height) > 0.5
            ):
                raise ValueError(
                    f"Page {page_index + 1} display geometry differs between "
                    "the source and translated PDFs"
                )

            source_lines = _display_lines(source_page)
            legacy_lines = _display_lines(legacy_page)
            seen: set[tuple[str, int, int]] = set()
            translated_index = 0
            for legacy_line in legacy_lines:
                translated = _normalize_text(legacy_line.text)
                if not _CJK_RE.search(translated) or "\ufffd" in translated:
                    continue
                if _same_existing_chinese(legacy_line, source_lines):
                    continue
                key = (
                    translated.casefold(),
                    round((legacy_line.bbox.x0 + legacy_line.bbox.x1) / 2),
                    round((legacy_line.bbox.y0 + legacy_line.bbox.y1) / 2),
                )
                if key in seen:
                    continue
                seen.add(key)

                source_line = _match_source_line(
                    legacy_line,
                    source_lines,
                    source_page.rect,
                )
                # The translated drawing is the authority for where its Chinese
                # belongs. Source matching is metadata only: using a merely
                # nearby English line as the placement anchor can associate map
                # names with a compass label or a title-cell neighbour.
                anchor = legacy_line.bbox
                translated_index += 1
                regions.append(
                    {
                        "region_id": (
                            f"p{page_index + 1:03d}-legacy-{translated_index:04d}"
                        ),
                        "page_index": page_index,
                        "page_number": page_index + 1,
                        "source_text": source_line.text if source_line is not None else "",
                        "translated_text": translated,
                        "bbox": list(anchor),
                        "display_bbox": list(anchor),
                        "legacy_bbox": list(legacy_line.bbox),
                        # V2 places from the actual English source when it can
                        # be matched. The former Chinese coordinate remains a
                        # separate fallback, never the default source anchor.
                        "source_anchor_bbox": list(source_line.bbox)
                        if source_line is not None
                        else list(anchor),
                        "placement_anchor_bbox": list(source_line.bbox)
                        if source_line is not None
                        else list(anchor),
                        "rotation": (
                            source_line.rotation
                            if source_line is not None
                            else legacy_line.rotation
                        ),
                        "provenance": "legacy_translation",
                        "action": "translate",
                        "placement": "inline_only",
                        "qa_flags": (
                            ["authoritative_legacy_translation"]
                            if source_line is not None
                            else [
                                "authoritative_legacy_translation",
                                "legacy_position_only",
                            ]
                        ),
                        "ocr_confidence": 1.0,
                        "ai_judgement": "accepted",
                        "coverage_status": "translated",
                    }
                )
    return regions


def select_strict_additions(additions: Iterable[dict]) -> list[dict]:
    """Admit only reviewed Unicode-Chinese additions after the legacy transfer."""
    accepted: list[dict] = []
    for raw in additions:
        region = dict(raw)
        translated = _normalize_text(
            region.get("translated_text")
            or region.get("protected_translated_text")
            or region.get("translation")
            or ""
        )
        if not _CJK_RE.search(translated) or "\ufffd" in translated:
            continue
        if str(region.get("action") or "") == "review":
            continue
        pipeline_verified = (
            str(region.get("coverage_status") or "")
            in {"translated", "literal_labeled"}
            and str(region.get("ai_judgement") or "") in {"accepted", "corrected"}
        )
        explicit_approval = (
            str(region.get("addition_approval") or "")
            in {"manual_verified_source", "ai_verified_source"}
            and bool(_normalize_text(region.get("approval_evidence") or ""))
        )
        if not pipeline_verified and not explicit_approval:
            continue
        flags = {str(flag) for flag in (region.get("qa_flags") or [])}
        if flags.intersection(_BLOCKING_ADDITION_FLAGS):
            continue
        region["translated_text"] = translated
        region["placement"] = "inline_only"
        region.setdefault("qa_flags", []).append("strict_post_legacy_addition")
        accepted.append(region)
    return accepted
