from __future__ import annotations

"""Extract auditable existing-Chinese evidence from local reference PDFs.

This module is deliberately not a planner.  It records native PDF Chinese text,
page coordinates and source provenance so the single multimodal supervisor can
visually decide whether to reuse or replace each item before creating layout.
"""

import hashlib
from pathlib import Path
import re

import fitz

_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_native_existing_translations(pdf_path: Path) -> dict:
    """Return native CJK spans without deciding translation or layout policy."""

    path = Path(pdf_path).resolve()
    items: list[dict] = []
    with fitz.open(path) as document:
        for page_index, page in enumerate(document):
            text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES)
            for block_index, block in enumerate(text_dict.get("blocks", [])):
                if block.get("type") != 0:
                    continue
                for line_index, line in enumerate(block.get("lines", [])):
                    for span_index, span in enumerate(line.get("spans", [])):
                        text = " ".join(str(span.get("text") or "").split())
                        if not text or not _CJK_RE.search(text):
                            continue
                        bbox = [round(float(value), 3) for value in span.get("bbox", [])]
                        if len(bbox) != 4:
                            continue
                        items.append(
                            {
                                "translation_id": (
                                    f"p{page_index + 1:03d}-b{block_index:04d}-"
                                    f"l{line_index:03d}-s{span_index:03d}"
                                ),
                                "page_index": page_index,
                                "bbox": bbox,
                                "text": text,
                                "source_file": str(path),
                                "provenance": "native_pdf_text",
                                "font_name": str(span.get("font") or ""),
                                "font_size": round(float(span.get("size") or 0), 3),
                                "color": int(span.get("color") or 0),
                                "source_association": None,
                                "supervisor_action": "pending_visual_decision",
                            }
                        )
        page_count = document.page_count
    return {
        "schema": "engineering-drawing-existing-translation-registry-v1",
        "source_file": str(path),
        "source_sha256": _sha256(path),
        "page_count": page_count,
        "items": items,
        "planning_authority": "none_evidence_only",
        "required_next_step": "single_multimodal_supervisor_assigns_source_association_and_reuse_or_replace",
    }


__all__ = ["extract_native_existing_translations"]
