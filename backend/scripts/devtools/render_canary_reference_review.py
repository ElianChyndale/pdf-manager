"""Render a readable, non-release review PDF from a signed V4 plan.

This tool is deliberately a review fallback, not a release renderer.  It
preserves the source sheet and writes every translated semantic block into an
immediately-following, numbered Chinese reference page.  It exists for dense
drawings where forcing captions into source geometry can erase source ink or
silently reject a placement.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from services.rendering.output.engineering import render_bilingual_overlay


def _review_regions(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for raw in plan.get("semantic_blocks") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("coverage_status") or "").casefold() != "translated":
            continue
        placement = raw.get("placement") if isinstance(raw.get("placement"), Mapping) else {}
        # Early canary plans recorded the approved source geometry only as the
        # initial placement target.  This is sufficient for a reference anchor
        # (which never paints in that box), but is *not* sufficient for an
        # inline/opaque release.  Keep this compatibility recovery confined to
        # the review-only tool.
        source_bbox = raw.get("source_bbox") or placement.get("target_bbox")
        translated = str(raw.get("translated_text") or "").strip()
        if not isinstance(source_bbox, (list, tuple)) or len(source_bbox) != 4 or not translated:
            continue
        regions.append(
            {
                "region_id": str(raw.get("block_id") or ""),
                "page_index": int(raw.get("page_index") or 0),
                "source_text": str(raw.get("source_text") or ""),
                "translated_text": translated,
                "bbox": [float(value) for value in source_bbox],
                # Force the legible, link-verified reference route.  Inline
                # candidates are intentionally disabled for a review artifact.
                "placement": "reference",
                "action": "translate",
                "coverage_status": "translated",
            }
        )
    return regions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    regions = _review_regions(plan)
    if not regions:
        raise SystemExit("signed plan has no translated semantic blocks")
    result = render_bilingual_overlay(
        source_pdf_path=args.source,
        output_pdf_path=args.output,
        regions=regions,
    )
    print(
        json.dumps(
            {
                "kind": "canary_reference_review",
                "output": str(result.output_pdf_path),
                "translated_blocks": len(regions),
                "reference_items": result.reference_items,
                "reference_pages": result.reference_pages,
                "inline_placements": result.inline_placements,
                "review_items": result.review_items,
                "reference_map": str(result.reference_map_path or ""),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
