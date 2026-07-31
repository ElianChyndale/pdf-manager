"""Raster residual-English QA for scanned engineering drawings.

``visual_qa.py`` detects only text-layer English (``page.get_text("words")``),
which misses pixel-baked English on scanned/rasterized drawings.  This module
re-rasterizes the candidate PDF, runs a lightweight OCR over the regions
OUTSIDE the authorized text-modification zones, and judges every detected
English token against each block's render-mode expectation:

- ``preserve_source_blue_chinese``  -> old English SHOULD be present + Chinese present
- ``opaque_bilingual_reflow``       -> old English glyphs must NOT remain (remove);
                                       regenerated bilingual text is allowed

This is a validation pass only — it never re-translates.  Residual English in a
``remove`` zone is exported to ``raster-residual-english.json`` and raised as a
hard finding.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import fitz

RASTER_RESIDUAL_SCHEMA = "engineering-drawing-raster-residual-qa-v1"
_LATIN_RE = re.compile(r"[A-Za-z]{2,}")
_MIN_CONFIDENCE = 0.4

# Block-level expectations recorded by the V4 renderer in the placement audit.
EXPECTED_VISIBILITY_KEY = "expected_source_visibility"  # preserve | remove | replace_bilingual
RESIDUAL_POLICY_KEY = "residual_policy"  # allowed | forbidden | generated_only


def run_raster_residual_qa(
    *,
    candidate_pdf: Path,
    source_pdf: Path,
    work_dir: Path,
    placement_audit: Iterable[Mapping[str, Any]],
    blocks: Iterable[Mapping[str, Any]],
    dpi: int = 150,
    ocr_engine: str = "paddle",
) -> dict[str, Any]:
    """Rasterize the candidate and check unmasked regions for residual English.

    The raster is OCR'd page by page; boxes are mapped back to PDF coordinates
    via the scale factor.  Each detected English token outside the authorized
    change zones is judged against the block's render mode.
    """
    candidate_pdf = Path(candidate_pdf)
    work_dir = Path(work_dir)
    findings: list[dict[str, Any]] = []
    pages_checked = 0

    audit_by_region = {
        str(item.get("region_id") or ""): dict(item) for item in placement_audit if isinstance(item, Mapping)
    }
    blocks_by_id = {str(block.get("block_id") or ""): dict(block) for block in blocks if isinstance(block, Mapping)}

    with fitz.open(candidate_pdf) as candidate, fitz.open(source_pdf) as source:
        if candidate.page_count != source.page_count:
            return {
                "schema": RASTER_RESIDUAL_SCHEMA,
                "page_count_mismatch": True,
                "candidate_pages": candidate.page_count,
                "source_pages": source.page_count,
                "findings": [],
                "hard_failure": "page_count_changed",
            }
        for page_index, candidate_page in enumerate(candidate):
            page = candidate_page
            scale = dpi / 72
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
            raster_path = work_dir / f"raster-page-{page_index + 1:04d}.png"
            raster_path.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(raster_path))

            detected = _ocr_page(raster_path, engine=ocr_engine, page_size=[float(page.rect.width), float(page.rect.height)])
            pages_checked += 1

            # Authorized zones = target boxes of placed blocks + their masks.
            authorized = [
                fitz.Rect(*(float(v) for v in item.get("target_bbox") or item.get("source_bbox") or []))
                for item in audit_by_region.values()
                if isinstance(item.get("target_bbox"), (list, tuple)) and len(item.get("target_bbox")) == 4
            ] + [
                fitz.Rect(*(float(v) for v in (block.get("source_bbox") or [])))
                for block in blocks_by_id.values()
                if isinstance(block.get("source_bbox"), (list, tuple)) and len(block.get("source_bbox")) == 4
            ]
            authorized = [rect for rect in authorized if rect.is_valid and not rect.is_empty]

            for token in detected:
                rect = fitz.Rect(*(float(v) for v in token["bbox"]))
                if _inside_any(rect, authorized):
                    continue  # inside an authorized text zone
                mode = _mode_for_region(token, audit_by_region, blocks_by_id)
                if mode == "preserve" or mode == "replace_bilingual":
                    continue  # English presence expected in this mode
                findings.append(
                    {
                        "region_id": token.get("region_id") or "",
                        "page_index": page_index,
                        "text": token["text"],
                        "bbox": list(token["bbox"]),
                        "confidence": token.get("confidence"),
                        "mode": mode,
                        "reason": "residual_english_outside_authorized_zone",
                    }
                )

    report = {
        "schema": RASTER_RESIDUAL_SCHEMA,
        "candidate_pdf": str(candidate_pdf),
        "pages_checked": pages_checked,
        "findings": findings,
        "hard_failure": "raster_residual_english" if findings else None,
    }
    (work_dir / "raster-residual-english.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _ocr_page(raster_path: Path, *, engine: str, page_size: list[float]) -> list[dict[str, Any]]:
    """OCR one rasterized page and return tokens in PDF coordinates.

    ``engine="paddle"`` shells out to the Paddle runner directly on the raster
    PNG (never a PDF round-trip); ``engine="fake"`` returns a canned token for
    tests.  The real Paddle runner's JSON output is normalized here.
    """
    if engine == "fake":
        return [
            {"text": "ROOF", "region_id": "fake-token", "bbox": [10.0, 10.0, 40.0, 25.0], "confidence": 0.95},
        ]
    import json
    import subprocess
    import sys

    runner = Path(__file__).resolve().parent / "ocr_runners" / "paddle_runner.py"
    try:
        result = subprocess.run(
            [sys.executable, str(runner), str(raster_path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
    except Exception as error:  # pragma: no cover - environment dependent
        raise RuntimeError(f"raster residual OCR unavailable ({engine}): {error}") from error

    tokens: list[dict[str, Any]] = []
    sx = float(page_size[0]) / float(payload.get("image_width", 1) or 1)
    sy = float(page_size[1]) / float(payload.get("image_height", 1) or 1)
    for item in payload.get("regions") or []:
        if not isinstance(item, dict) or not _LATIN_RE.search(str(item.get("text") or "")):
            continue
        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0
        if confidence < _MIN_CONFIDENCE:
            continue
        bbox = item.get("bbox") or item.get("polygon") or []
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            tokens.append(
                {
                    "text": str(item.get("text") or ""),
                    "bbox": [float(bbox[0]) * sx, float(bbox[1]) * sy, float(bbox[2]) * sx, float(bbox[3]) * sy],
                    "confidence": confidence,
                }
            )
    return tokens


def _inside_any(rect: fitz.Rect, rects: list[fitz.Rect]) -> bool:
    for other in rects:
        if not (rect & other).is_empty:
            return True
    return False


def _mode_for_region(token: Mapping[str, Any], audit: Mapping[str, Mapping[str, Any]], blocks: Mapping[str, Mapping[str, Any]]) -> str:
    region_id = str(token.get("region_id") or "")
    item = audit.get(region_id) or {}
    visibility = str(item.get(EXPECTED_VISIBILITY_KEY) or "")
    if not visibility:
        block = blocks.get(region_id) or {}
        render_mode = str(block.get("render_mode") or "")
        if render_mode == "opaque_bilingual_reflow":
            visibility = "remove"
        elif render_mode == "preserve_source_blue_chinese":
            visibility = "preserve"
        else:
            # Conservative default: an unresolved token in an unmasked zone is
            # treated as remove (residual detection should err on flagging).
            visibility = "remove"
    return visibility


__all__ = ["RASTER_RESIDUAL_SCHEMA", "run_raster_residual_qa"]
