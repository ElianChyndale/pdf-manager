from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class Action(StrEnum):
    TRANSLATE = "translate"
    KEEP_LITERAL = "keep_literal"
    REVIEW = "review"


class LegacyStatus(StrEnum):
    MISSING = "missing"
    PARTIAL = "partial"
    BAD_TRANSLATION = "bad_translation"
    LAYOUT_DEFECT = "layout_defect"
    ACCEPTED = "accepted"


class SourceLanguage(StrEnum):
    ENGLISH = "en"
    MALAY = "ms"
    CHINESE = "zh"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Provenance(StrEnum):
    NATIVE_TEXT = "native_text"
    PAGE_OCR = "page_ocr"
    ROTATED_OCR = "rotated_ocr"
    TILED_OCR = "tiled_ocr"
    VECTOR_OUTLINE = "vector_outline"
    PADDLE_OCR = "paddle_ocr"
    DEEPSEEK_OCR = "deepseek_ocr"
    MANUAL = "manual"


class Placement(StrEnum):
    UNPLACED = "unplaced"
    INLINE = "inline"
    SIDEBAR = "sidebar"
    DUAL_PAGE = "dual_page"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        values = (self.x0, self.y0, self.x1, self.y1)
        if not all(isinstance(value, (int, float)) for value in values):
            raise TypeError("bbox coordinates must be numbers")
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox must satisfy x1 >= x0 and y1 >= y0")

    @classmethod
    def from_sequence(cls, value: Any) -> "BBox":
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ValueError("bbox must contain four coordinates")
        return cls(*(float(item) for item in value))

    def to_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]


@dataclass
class RegionRecord:
    source_text: str
    translated_text: str
    source_language: SourceLanguage
    bbox: BBox
    rotation: int
    provenance: Provenance
    action: Action
    legacy_status: LegacyStatus
    placement: Placement = Placement.UNPLACED
    qa_flags: list[str] = field(default_factory=list)
    page_number: int = 1
    region_id: str = ""

    def __post_init__(self) -> None:
        self.source_text = str(self.source_text or "").strip()
        self.translated_text = str(self.translated_text or "").strip()
        if self.rotation not in (0, 90, 180, 270):
            raise ValueError("rotation must be one of 0, 90, 180, 270")
        if self.page_number < 1:
            raise ValueError("page_number must be 1-based")
        self.qa_flags = sorted({str(flag) for flag in self.qa_flags if str(flag)})

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["source_language"] = self.source_language.value
        result["bbox"] = self.bbox.to_list()
        result["provenance"] = self.provenance.value
        result["action"] = self.action.value
        result["legacy_status"] = self.legacy_status.value
        result["placement"] = self.placement.value
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RegionRecord":
        return cls(
            source_text=value.get("source_text", ""),
            translated_text=value.get("translated_text", ""),
            source_language=SourceLanguage(value.get("source_language", "unknown")),
            bbox=BBox.from_sequence(value.get("bbox", (0, 0, 0, 0))),
            rotation=int(value.get("rotation", 0)),
            provenance=Provenance(value.get("provenance", "native_text")),
            action=Action(value.get("action", "review")),
            legacy_status=LegacyStatus(value.get("legacy_status", "missing")),
            placement=Placement(value.get("placement", "unplaced")),
            qa_flags=list(value.get("qa_flags", [])),
            page_number=int(value.get("page_number", 1)),
            region_id=str(value.get("region_id", "")),
        )
