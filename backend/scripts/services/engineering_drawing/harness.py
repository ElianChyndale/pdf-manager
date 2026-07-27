from __future__ import annotations

"""Release harness for full-coverage bilingual engineering drawings.

This is deliberately a gate, not a best-effort renderer.  A readable non-Chinese
region may not disappear merely because the inline layout is crowded.  It must
be translated, placed safely, or block release with an explicit remediation
record.  Geographic entities get a small, cached external verification pass so
OCR mistakes in roads / addresses cannot silently become translation mistakes.
"""

import csv
import json
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import fitz


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06ff]")
_NUMERIC_ONLY_RE = re.compile(r"^[\s\d.,:+\-×x/()°%#]+$")
_GEO_ENTITY_RE = re.compile(
    r"\b(?:jalan|lorong|persiaran|taman|kampung|bandar|johor|selangor|kuala\s+lumpur)\b",
    re.IGNORECASE,
)
_UNSAFE_STATUSES = {"rejected_invalid", "rejected_unverified_ocr", "rejected_no_near_space", "rejected_text_did_not_fit"}
_NON_SOURCE_OBSERVATION_STATUSES = {"ai_confirmed_non_language", "ai_confirmed_duplicate_observation"}


@dataclass(frozen=True)
class GeographicMatch:
    name: str
    display_name: str
    category: str
    source: str = "nominatim"


@dataclass(frozen=True)
class HarnessResult:
    regions: list[dict]
    blocking: list[dict]
    report: dict[str, object]


def _normalized(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _is_required_source_text(value: object) -> bool:
    """All non-Chinese language is mandatory; bare Arabic numerals are not."""
    text = str(value or "").strip()
    if not text or _NUMERIC_ONLY_RE.fullmatch(text):
        return False
    return bool(_LATIN_RE.search(text) or _ARABIC_SCRIPT_RE.search(text))


def _has_chinese(value: object) -> bool:
    return bool(_CJK_RE.search(str(value or "")))


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalized(left), _normalized(right)).ratio()


class GeographicResolver:
    """Nominatim-backed, cache-first verifier for Malaysian geographic labels.

    It is intentionally limited to geographic-shaped strings and only corrects
    OCR where external evidence is strong.  No broad web search is used, and a
    miss never invents a replacement.  Production callers should share one
    cache across the batch to keep requests small and auditable.
    """

    def __init__(
        self,
        *,
        cache_path: Path | None = None,
        lookup: Callable[[str], list[GeographicMatch]] | None = None,
        allow_online: bool = False,
        min_interval_seconds: float = 1.0,
    ) -> None:
        self.cache_path = Path(cache_path) if cache_path else None
        self.allow_online = allow_online
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self._last_request = 0.0
        self._lookup = lookup or self._nominatim_lookup
        self._cache = self._load_cache()

    def _load_cache(self) -> dict[str, list[dict]]:
        if self.cache_path is None or not self.cache_path.exists():
            return {}
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return payload.get("entries", {}) if isinstance(payload.get("entries", {}), dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({"entries": self._cache}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _nominatim_lookup(self, query: str) -> list[GeographicMatch]:
        if not self.allow_online:
            return []
        delay = self.min_interval_seconds - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        url = "https://nominatim.openstreetmap.org/search?" + urlencode(
            {"q": query, "format": "jsonv2", "limit": 3, "countrycodes": "my"}
        )
        request = Request(url, headers={"User-Agent": "pdf-manager-engineering-translation/1.0"})
        try:
            with urlopen(request, timeout=12) as response:  # nosec B310: fixed public endpoint
                rows = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []
        self._last_request = time.monotonic()
        return [
            GeographicMatch(
                name=str(row.get("name") or "").strip(),
                display_name=str(row.get("display_name") or "").strip(),
                category=str(row.get("class") or row.get("type") or "").strip(),
            )
            for row in rows
            if str(row.get("name") or "").strip()
        ]

    def resolve(self, text: str, *, context_hints: Iterable[str] = ()) -> GeographicMatch | None:
        source = str(text or "").strip()
        if not _GEO_ENTITY_RE.search(source):
            return None
        hints = ", ".join(str(value).strip() for value in context_hints if str(value).strip())
        query = f"{source}, {hints}" if hints else source
        key = _normalized(query)
        cached = self._cache.get(key)
        if cached is None:
            matches = self._lookup(query)
            cached = [match.__dict__ for match in matches]
            self._cache[key] = cached
            self._save_cache()
        matches = [GeographicMatch(**row) for row in cached if isinstance(row, dict)]
        if not matches:
            return None
        ranked = sorted(matches, key=lambda item: _similarity(source, item.name), reverse=True)
        best = ranked[0]
        score = _similarity(source, best.name)
        runner_up = _similarity(source, ranked[1].name) if len(ranked) > 1 else 0.0
        # A one-character OCR error in a road label normally passes. Ambiguous
        # geocoding does not: it remains a review item rather than a mutation.
        return best if score >= 0.84 and score - runner_up >= 0.04 else None


def _geo_correct(region: dict, *, resolver: GeographicResolver | None, context_hints: Iterable[str]) -> dict:
    updated = dict(region)
    source = str(updated.get("source_text") or "").strip()
    flags = {str(flag) for flag in (updated.get("qa_flags") or [])}
    needs_geo_review = bool(_GEO_ENTITY_RE.search(source)) and (
        not flags or bool(flags.intersection({"ocr_suspect", "deepseek_ocr_conflict", "manual_review_required", "low_paddle_confidence"}))
    )
    if resolver is None or not needs_geo_review:
        return updated
    match = resolver.resolve(source, context_hints=context_hints)
    if match is None or _normalized(match.name) == _normalized(source):
        updated["geo_status"] = "verified" if match else "not_verified"
        return updated
    updated["raw_source_text"] = source
    updated["source_text"] = match.name
    updated["geo_status"] = "corrected"
    updated["geo_evidence"] = {"source": match.source, "category": match.category, "display_name": match.display_name}
    updated["qa_flags"] = sorted(flags | {"geo_ocr_corrected"})
    return updated


def correct_geographic_regions(
    regions: Iterable[dict],
    *,
    resolver: GeographicResolver | None,
    context_hints: Iterable[str] = (),
) -> list[dict]:
    """Apply evidence-backed OCR corrections before translation is requested."""
    return [_geo_correct(region, resolver=resolver, context_hints=context_hints) for region in regions]


def _region_page_index(region: dict) -> int:
    raw = region.get("page_index", region.get("page_number", 1))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if "page_index" in region else max(0, value - 1)


def _display_bbox(region: dict, page: fitz.Page) -> fitz.Rect | None:
    raw = region.get("bbox") or region.get("source_bbox")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        rect = fitz.Rect(raw)
    except (TypeError, ValueError):
        return None
    if not rect.is_valid or rect.is_empty:
        return None
    # Native PDF extraction is in unrotated media-box coordinates. Visual OCR
    # uses the already displayed raster coordinate system.
    if str(region.get("provenance") or "") == "native_text":
        rect = rect * page.rotation_matrix
    return rect


def _rect_distance(first: fitz.Rect, second: fitz.Rect) -> float:
    dx = max(first.x0 - second.x1, second.x0 - first.x1, 0.0)
    dy = max(first.y0 - second.y1, second.y0 - first.y1, 0.0)
    return (dx * dx + dy * dy) ** 0.5


def audit_existing_legacy_companions(
    *,
    legacy_pdf_path: Path,
    regions: Iterable[dict],
    max_distance: float = 28.0,
) -> list[dict]:
    """Verify Chinese already visible in a legacy base before adding another label.

    The audit is intentionally geometric and textual: a generic Chinese word in
    another part of the page cannot satisfy a source region.  This preserves a
    correct legacy companion and avoids turning a title block into blue noise.
    """
    by_page: dict[int, list[dict]] = {}
    for region in regions:
        by_page.setdefault(_region_page_index(region), []).append(dict(region))
    placements: list[dict] = []
    document = fitz.open(Path(legacy_pdf_path))
    try:
        for page_index, page_regions in by_page.items():
            if not 0 <= page_index < document.page_count:
                continue
            page = document[page_index]
            chinese_words = [
                (fitz.Rect(word[:4]) * page.rotation_matrix, str(word[4]))
                for word in page.get_text("words")
                if len(word) >= 5 and _has_chinese(word[4])
            ]
            for region in page_regions:
                target = str(region.get("translated_text") or "")
                source_rect = _display_bbox(region, page)
                # Preserve a numeric Chinese unit such as ``2层`` / ``3根`` as
                # one meaningful token. Engineering drawings commonly split a
                # bilingual row into separate words, so requiring two adjacent
                # CJK characters would miss a correct existing companion.
                chunks = [
                    chunk.replace(" ", "")
                    for chunk in re.findall(r"(?:\d+(?:[.,]\d+)?\s*)?[\u3400-\u9fff]+", target)
                    if len(chunk.replace(" ", "")) >= 2
                ]
                if source_rect is None or not chunks:
                    continue
                best: tuple[float, fitz.Rect, str] | None = None
                for word_rect, word in chinese_words:
                    # A meaningful two-character Chinese fragment must match;
                    # single characters are too ambiguous on dense drawings.
                    if not any(chunk in word or word in chunk for chunk in chunks):
                        continue
                    distance = _rect_distance(source_rect, word_rect)
                    if distance <= max_distance and (best is None or distance < best[0]):
                        best = (distance, word_rect, word)
                if best is None:
                    continue
                distance, word_rect, word = best
                placements.append(
                    {
                        "region_id": str(region.get("region_id") or ""),
                        "page_index": page_index,
                        "source_text": str(region.get("source_text") or ""),
                        "source_bbox": list(source_rect),
                        "status": "inline_near",
                        "target_bbox": list(word_rect),
                        "distance": round(distance, 3),
                        "placement_origin": "legacy_verified",
                        "legacy_companion_text": word,
                    }
                )
    finally:
        document.close()
    return placements


def run_full_coverage_harness(
    regions: Iterable[dict],
    *,
    placement_audit: Iterable[dict] = (),
    geographic_resolver: GeographicResolver | None = None,
    context_hints: Iterable[str] = (),
) -> HarnessResult:
    """Apply geographic correction and block any incomplete bilingual release."""
    corrected = [_geo_correct(item, resolver=geographic_resolver, context_hints=context_hints) for item in regions]
    placements = {str(item.get("region_id") or ""): dict(item) for item in placement_audit}
    blocking: list[dict] = []
    required = translated = geo_corrected = placed = 0
    for region in corrected:
        source = str(region.get("source_text") or "").strip()
        if str(region.get("observation_status") or "") in _NON_SOURCE_OBSERVATION_STATUSES:
            continue
        if not _is_required_source_text(source):
            continue
        required += 1
        region_id = str(region.get("region_id") or "")
        target = str(region.get("translated_text") or "").strip()
        if str(region.get("geo_status") or "") == "corrected":
            geo_corrected += 1
        if not _has_chinese(target) or str(region.get("action") or "") == "review":
            blocking.append({"region_id": region_id, "source_text": source, "reason": "missing_verified_chinese_translation"})
            continue
        translated += 1
        placement = placements.get(region_id)
        status = str(placement.get("status") or "") if placement else "not_rendered"
        if status in _UNSAFE_STATUSES or status != "inline_near":
            blocking.append(
                {
                    "region_id": region_id,
                    "source_text": source,
                    "reason": "no_safe_bilingual_placement",
                    "placement_status": status,
                }
            )
            continue
        placed += 1
    report = {
        "required_regions": required,
        "translated_regions": translated,
        "safely_placed_regions": placed,
        "geo_corrected_regions": geo_corrected,
        "blocking_regions": len(blocking),
        "passed": not blocking and required == translated == placed,
    }
    return HarnessResult(regions=corrected, blocking=blocking, report=report)


def write_harness_reports(result: HarnessResult, *, output_json: Path) -> tuple[Path, Path]:
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps({"report": result.report, "blocking": result.blocking, "regions": result.regions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_csv = output_json.with_suffix(".csv")
    fields = ["region_id", "source_text", "reason", "placement_status"]
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in result.blocking)
    return output_json, output_csv


def quality_exceeds_legacy_baseline(candidate: HarnessResult, legacy_status_counts: dict[str, int]) -> dict[str, object]:
    """Return a strict comparative gate for a pre-existing translated draft.

    "Better" is not an aesthetic assertion: the candidate must have zero
    coverage / placement blockers, while every recorded missing, partial,
    mistranslated or layout-defective legacy region is explicitly counted.
    """
    defect_keys = ("missing", "partial", "bad_translation", "layout_defect")
    legacy_defects = sum(int(legacy_status_counts.get(key, 0) or 0) for key in defect_keys)
    candidate_passed = bool(candidate.report.get("passed"))
    return {
        "legacy_defects": legacy_defects,
        "candidate_blocking_regions": int(candidate.report.get("blocking_regions", 0) or 0),
        "passed": candidate_passed and int(candidate.report.get("blocking_regions", 0) or 0) == 0,
        "reason": "candidate_has_full_coverage_and_safe_placement" if candidate_passed else "candidate_does_not_yet_meet_full_coverage_gate",
    }
