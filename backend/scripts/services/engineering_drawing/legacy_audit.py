from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import fitz

from .inventory import Inventory, InventoryItem
from .models import (
    Action,
    BBox,
    LegacyStatus,
    Placement,
    Provenance,
    RegionRecord,
    SourceLanguage,
)


CJK_RE = re.compile(r"[\u3400-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)*(?![A-Za-z])")
LITERAL_RE = re.compile(
    r"^(?:[A-Z]{1,3}|[A-Z]?\d[\w./×xØø+\-]*|[A-Z]{1,8}\d[\w./×xØø+\-]*|"
    r"[A-Z]{1,5}[-_/]\d[\w./\-]*|"
    r"\d+(?:\.\d+)?\s*(?:mm|cm|m|m2|m3|kV|V|A|Hz|kW|kVA|bar|°C))$",
    re.IGNORECASE,
)
MALAY_HINTS = {
    "dan",
    "untuk",
    "jalan",
    "tingkat",
    "bangunan",
    "pintu",
    "bilik",
    "tandas",
    "masjid",
    "julai",
    "depoh",
    "lori",
}


@dataclass(frozen=True)
class RegressionSpec:
    check_id: str
    filename_pattern: str
    source_patterns: tuple[str, ...]
    description: str
    vector_outline: bool = False


REGRESSION_SPECS = (
    RegressionSpec(
        "site-plan-water-system",
        "1310-CN-ELEC-A001",
        (
            "distribution water pump",
            "distribution storage tank",
            "treated water tank",
            "setbackline",
        ),
        "Water pumps, storage tanks, treated-water tank and setback annotations",
    ),
    RegressionSpec(
        "site-plan-title-block",
        "1310-CN-ELEC-A001",
        ("landowner", "developer", "architect", "associate", "jalan", "johor"),
        "Title-block field names, company names, addresses and body text",
    ),
    RegressionSpec(
        "site-plan-depoh-lori",
        "1310-CN-ELEC-A001",
        ("depoh lori",),
        "Vector-outline DEPOT/DEPOH LORI lettering",
        vector_outline=True,
    ),
)


@dataclass
class PageAudit:
    page_number: int
    source_width: float
    source_height: float
    legacy_width: float = 0.0
    legacy_height: float = 0.0
    geometry_matches: bool = False
    regions: list[RegionRecord] = field(default_factory=list)
    qa_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["regions"] = [region.to_dict() for region in self.regions]
        return result


@dataclass
class FileAudit:
    source_path: str
    legacy_translation_path: str
    relative_path: str
    content_hash: str
    pairing_status: str
    page_count_matches: bool
    version_matches: bool
    pages: list[PageAudit]
    regression_checks: list[dict[str, object]]
    qa_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "legacy_translation_path": self.legacy_translation_path,
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "pairing_status": self.pairing_status,
            "page_count_matches": self.page_count_matches,
            "version_matches": self.version_matches,
            "pages": [page.to_dict() for page in self.pages],
            "regression_checks": self.regression_checks,
            "qa_flags": self.qa_flags,
            "status_counts": self.status_counts(),
        }

    def status_counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in LegacyStatus}
        for page in self.pages:
            for region in page.regions:
                counts[region.legacy_status.value] += 1
        return counts


@dataclass
class AuditResult:
    inventory_summary: dict[str, int]
    files: list[FileAudit]

    def to_dict(self) -> dict[str, object]:
        totals = {status.value: 0 for status in LegacyStatus}
        for file_audit in self.files:
            for status, count in file_audit.status_counts().items():
                totals[status] += count
        return {
            "inventory_summary": self.inventory_summary,
            "status_counts": totals,
            "files": [file.to_dict() for file in self.files],
        }


@dataclass(frozen=True)
class _Line:
    text: str
    bbox: fitz.Rect
    rotation: int


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _detect_rotation(direction: object) -> int:
    if not isinstance(direction, (list, tuple)) or len(direction) != 2:
        return 0
    x, y = float(direction[0]), float(direction[1])
    angle = int(round(math.degrees(math.atan2(-y, x)))) % 360
    return min((0, 90, 180, 270), key=lambda candidate: abs(candidate - angle))


def _page_lines(page: fitz.Page) -> list[_Line]:
    lines: list[_Line] = []
    raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES)
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = _normalize_text(
                "".join(str(span.get("text", "")) for span in line.get("spans", []))
            )
            if not text:
                continue
            lines.append(
                _Line(
                    text=text,
                    bbox=fitz.Rect(line.get("bbox", (0, 0, 0, 0))),
                    rotation=_detect_rotation(line.get("dir")),
                )
            )
    return lines


def _language(text: str) -> SourceLanguage:
    has_cjk = bool(CJK_RE.search(text))
    has_latin = bool(LATIN_RE.search(text))
    if has_cjk and has_latin:
        return SourceLanguage.MIXED
    if has_cjk:
        return SourceLanguage.CHINESE
    if not has_latin:
        return SourceLanguage.UNKNOWN
    words = {word.casefold() for word in re.findall(r"[A-Za-z]+", text)}
    if words & MALAY_HINTS:
        return SourceLanguage.MALAY
    return SourceLanguage.ENGLISH


def _action(text: str) -> Action:
    compact = _normalize_text(text)
    if LITERAL_RE.fullmatch(compact):
        return Action.KEEP_LITERAL
    if LATIN_RE.search(compact):
        return Action.TRANSLATE
    return Action.REVIEW


def _center_distance(left: fitz.Rect, right: fitz.Rect) -> float:
    lx, ly = (left.x0 + left.x1) / 2, (left.y0 + left.y1) / 2
    rx, ry = (right.x0 + right.x1) / 2, (right.y0 + right.y1) / 2
    return math.hypot(lx - rx, ly - ry)


def _nearby_chinese(
    source_line: _Line,
    legacy_lines: Iterable[_Line],
    page_diagonal: float,
) -> _Line | None:
    normalized_source = _normalize_text(source_line.text).casefold()
    same_line = [
        line
        for line in legacy_lines
        if CJK_RE.search(line.text)
        and normalized_source in _normalize_text(line.text).casefold()
    ]
    if same_line:
        return min(
            same_line,
            key=lambda line: _center_distance(source_line.bbox, line.bbox),
        )
    distance_limit = min(
        72.0,
        max(24.0, page_diagonal * 0.025, source_line.bbox.height * 5 + 8),
    )
    candidates = [
        line
        for line in legacy_lines
        if CJK_RE.search(line.text)
        and _center_distance(source_line.bbox, line.bbox) <= distance_limit
    ]
    return min(candidates, key=lambda line: _center_distance(source_line.bbox, line.bbox)) if candidates else None


def _source_still_present(source_text: str, legacy_lines: Iterable[_Line]) -> bool:
    normalized = _normalize_text(source_text).casefold()
    if len(normalized) < 3:
        return False
    return any(normalized in _normalize_text(line.text).casefold() for line in legacy_lines)


def _numbers(text: str) -> list[str]:
    return [value.replace(",", "") for value in NUMBER_RE.findall(text)]


def _audit_region(
    source_line: _Line,
    legacy_lines: list[_Line],
    page_diagonal: float,
    region_id: str,
    page_number: int,
) -> RegionRecord:
    action = _action(source_line.text)
    flags: list[str] = []
    translated = ""
    if action is Action.KEEP_LITERAL:
        status = LegacyStatus.ACCEPTED
        placement = Placement.UNCHANGED
    else:
        chinese = _nearby_chinese(source_line, legacy_lines, page_diagonal)
        source_present = _source_still_present(source_line.text, legacy_lines)
        if chinese is None:
            status = LegacyStatus.MISSING
            placement = Placement.UNPLACED
            flags.append("missing_chinese_companion")
        else:
            translated = chinese.text
            placement = Placement.INLINE
            status = LegacyStatus.ACCEPTED
            normalized_source = _normalize_text(source_line.text).casefold()
            same_line = normalized_source in _normalize_text(
                chinese.text
            ).casefold()
            if not source_present:
                flags.append("source_text_not_retained")
            if len(CJK_RE.findall(translated)) < max(1, len(source_line.text) // 35):
                status = LegacyStatus.PARTIAL
                flags.append("translation_appears_partial")
            source_numbers = _numbers(source_line.text)
            translated_numbers = _numbers(translated)
            if translated_numbers and source_numbers != translated_numbers:
                status = LegacyStatus.BAD_TRANSLATION
                flags.append("number_mismatch")
            if not same_line and chinese.bbox.intersects(source_line.bbox):
                overlap = chinese.bbox & source_line.bbox
                if overlap.get_area() > min(
                    chinese.bbox.get_area(), source_line.bbox.get_area()
                ) * 0.35:
                    status = LegacyStatus.LAYOUT_DEFECT
                    flags.append("translation_overlaps_source")

    if source_line.rotation:
        flags.append("rotated_source_text")
    return RegionRecord(
        source_text=source_line.text,
        translated_text=translated,
        source_language=_language(source_line.text),
        bbox=BBox(*tuple(source_line.bbox)),
        rotation=source_line.rotation,
        provenance=Provenance.NATIVE_TEXT,
        action=action,
        legacy_status=status,
        placement=placement,
        qa_flags=flags,
        page_number=page_number,
        region_id=region_id,
    )


def _regression_checks(
    item: InventoryItem,
    source_text: str,
    legacy_text: str,
    pages: list[PageAudit],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    filename = Path(item.source_path).name.casefold()
    source_normalized = _normalize_text(source_text).casefold()
    legacy_normalized = _normalize_text(legacy_text).casefold()
    for spec in REGRESSION_SPECS:
        if spec.filename_pattern.casefold() not in filename:
            continue
        found = [
            pattern
            for pattern in spec.source_patterns
            if pattern.casefold() in source_normalized
        ]
        residual = [
            pattern
            for pattern in spec.source_patterns
            if pattern.casefold() in legacy_normalized
        ]
        failed_region_patterns: list[str] = []
        for pattern in spec.source_patterns:
            matching_regions = [
                region
                for page in pages
                for region in page.regions
                if pattern.casefold() in region.source_text.casefold()
            ]
            if matching_regions and all(
                region.legacy_status
                in (
                    LegacyStatus.MISSING,
                    LegacyStatus.PARTIAL,
                    LegacyStatus.BAD_TRANSLATION,
                    LegacyStatus.LAYOUT_DEFECT,
                )
                for region in matching_regions
            ):
                failed_region_patterns.append(pattern)
        flags: list[str] = []
        if spec.vector_outline and not found:
            flags.append("vector_outline_ocr_required")
        if failed_region_patterns:
            flags.append("legacy_translation_missing_or_defective")
        if len(found) < len(spec.source_patterns):
            flags.append("high_resolution_or_rotated_ocr_required")
        results.append(
            {
                "check_id": spec.check_id,
                "description": spec.description,
                "source_patterns_found": found,
                "legacy_source_residuals": residual,
                "failed_region_patterns": failed_region_patterns,
                "passed": not flags,
                "qa_flags": flags,
            }
        )
    return results


def audit_file(item: InventoryItem, geometry_tolerance: float = 0.5) -> FileAudit:
    qa_flags: list[str] = []
    pages: list[PageAudit] = []
    if not item.legacy_translation_path:
        qa_flags.append("legacy_translation_missing")
        return FileAudit(
            source_path=item.source_path,
            legacy_translation_path="",
            relative_path=item.relative_path,
            content_hash=item.content_hash,
            pairing_status=item.pairing_status,
            page_count_matches=False,
            version_matches=item.version_matches,
            pages=[],
            regression_checks=[],
            qa_flags=qa_flags,
        )

    with fitz.open(item.source_path) as source_doc, fitz.open(
        item.legacy_translation_path
    ) as legacy_doc:
        page_count_matches = source_doc.page_count == legacy_doc.page_count
        if not page_count_matches:
            qa_flags.append("page_count_mismatch")
        if not item.version_matches:
            qa_flags.append("drawing_version_mismatch")
        all_source_text: list[str] = []
        all_legacy_text: list[str] = []
        for page_index in range(source_doc.page_count):
            source_page = source_doc[page_index]
            source_lines = _page_lines(source_page)
            all_source_text.extend(line.text for line in source_lines)
            if page_index >= legacy_doc.page_count:
                pages.append(
                    PageAudit(
                        page_number=page_index + 1,
                        source_width=source_page.rect.width,
                        source_height=source_page.rect.height,
                        qa_flags=["legacy_page_missing"],
                    )
                )
                continue
            legacy_page = legacy_doc[page_index]
            legacy_lines = _page_lines(legacy_page)
            all_legacy_text.extend(line.text for line in legacy_lines)
            geometry_matches = (
                abs(source_page.rect.width - legacy_page.rect.width)
                <= geometry_tolerance
                and abs(source_page.rect.height - legacy_page.rect.height)
                <= geometry_tolerance
                and source_page.rotation == legacy_page.rotation
            )
            page_flags: list[str] = []
            if not geometry_matches:
                page_flags.append("page_geometry_mismatch")
            diagonal = math.hypot(source_page.rect.width, source_page.rect.height)
            regions = [
                _audit_region(
                    source_line,
                    legacy_lines,
                    diagonal,
                    f"p{page_index + 1}-r{line_index + 1}",
                    page_index + 1,
                )
                for line_index, source_line in enumerate(source_lines)
            ]
            pages.append(
                PageAudit(
                    page_number=page_index + 1,
                    source_width=source_page.rect.width,
                    source_height=source_page.rect.height,
                    legacy_width=legacy_page.rect.width,
                    legacy_height=legacy_page.rect.height,
                    geometry_matches=geometry_matches,
                    regions=regions,
                    qa_flags=page_flags,
                )
            )
        regression = _regression_checks(
            item,
            "\n".join(all_source_text),
            "\n".join(all_legacy_text),
            pages,
        )
        if any(not check["passed"] for check in regression):
            qa_flags.append("regression_check_failed")
    return FileAudit(
        source_path=item.source_path,
        legacy_translation_path=item.legacy_translation_path,
        relative_path=item.relative_path,
        content_hash=item.content_hash,
        pairing_status=item.pairing_status,
        page_count_matches=page_count_matches,
        version_matches=item.version_matches,
        pages=pages,
        regression_checks=regression,
        qa_flags=qa_flags,
    )


def audit_inventory(
    inventory: Inventory,
    *,
    only_paired: bool = False,
    geometry_tolerance: float = 0.5,
) -> AuditResult:
    items = inventory.items
    if only_paired:
        items = [item for item in items if item.legacy_translation_path]
    summary = {
        "unique_source_count": inventory.unique_source_count,
        "paired_count": inventory.paired_count,
        "unpaired_source_count": inventory.unpaired_source_count,
        "duplicate_source_count": inventory.duplicate_source_count,
    }
    return AuditResult(
        inventory_summary=summary,
        files=[
            audit_file(item, geometry_tolerance=geometry_tolerance)
            for item in items
        ],
    )
