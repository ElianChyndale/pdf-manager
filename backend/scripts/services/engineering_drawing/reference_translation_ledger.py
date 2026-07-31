from __future__ import annotations

"""Build evidence-only source/Chinese candidates from an original and reference PDF.

Spatial candidates reduce transcription work but never select a translation or a
target position.  The single multimodal supervisor must visually adjudicate them.
"""

import hashlib
from pathlib import Path
import re

import fitz

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _spans(page: fitz.Page) -> list[dict]:
    output: list[dict] = []
    for block in page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = " ".join(str(span.get("text") or "").split())
                bbox = span.get("bbox") or []
                if text and len(bbox) == 4:
                    output.append({"text": text, "bbox": [float(value) for value in bbox]})
    return output


def _distance(a: fitz.Rect, b: fitz.Rect) -> float:
    if a.intersects(b):
        return 0.0
    dx = max(a.x0 - b.x1, b.x0 - a.x1, 0)
    dy = max(a.y0 - b.y1, b.y0 - a.y1, 0)
    return (dx * dx + dy * dy) ** 0.5


def build_reference_translation_ledger(source_pdf: Path, reference_pdf: Path) -> dict:
    source_path = Path(source_pdf).resolve()
    reference_path = Path(reference_pdf).resolve()
    entries: list[dict] = []
    with fitz.open(source_path) as source, fitz.open(reference_path) as reference:
        if source.page_count != reference.page_count:
            raise ValueError("source/reference page count mismatch")
        for page_index in range(source.page_count):
            source_rect = source[page_index].rect
            reference_rect = reference[page_index].rect
            if (
                abs(source_rect.width - reference_rect.width) > 0.5
                or abs(source_rect.height - reference_rect.height) > 0.5
            ):
                raise ValueError(f"source/reference page geometry mismatch on page {page_index + 1}")
            source_spans = [item for item in _spans(source[page_index]) if _LATIN_RE.search(item["text"])]
            chinese_spans = [item for item in _spans(reference[page_index]) if _CJK_RE.search(item["text"])]
            for index, chinese in enumerate(chinese_spans):
                chinese_rect = fitz.Rect(chinese["bbox"])
                ranked = sorted(
                    (
                        (_distance(chinese_rect, fitz.Rect(candidate["bbox"])), candidate)
                        for candidate in source_spans
                    ),
                    key=lambda pair: pair[0],
                )[:5]
                entries.append(
                    {
                        "ledger_id": f"p{page_index + 1:03d}-zh{index + 1:04d}",
                        "page_index": page_index,
                        "reference_chinese": chinese["text"],
                        "reference_bbox": [round(value, 3) for value in chinese["bbox"]],
                        "source_candidates": [
                            {
                                "source_text": candidate["text"],
                                "source_bbox": [round(value, 3) for value in candidate["bbox"]],
                                "distance": round(distance, 3),
                            }
                            for distance, candidate in ranked
                        ],
                        "supervisor_source_association": None,
                        "supervisor_translation_decision": "pending_visual_review",
                        "reference_coordinates_are_target": False,
                    }
                )
        page_count = source.page_count
    return {
        "schema": "engineering-drawing-reference-translation-ledger-v1",
        "source_pdf": str(source_path),
        "source_sha256": _sha256(source_path),
        "reference_pdf": str(reference_path),
        "reference_sha256": _sha256(reference_path),
        "page_count": page_count,
        "reference_usage": "translation_evidence_only",
        "render_base": "original_source_pdf",
        "entries": entries,
    }


__all__ = ["build_reference_translation_ledger"]
