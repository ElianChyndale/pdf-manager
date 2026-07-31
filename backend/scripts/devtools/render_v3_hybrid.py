# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.engineering_drawing.multimodal_plan import (
    apply_multimodal_plan,
    prepare_multimodal_plan_payload,
    validate_multimodal_plan,
)
from services.engineering_drawing.overlay_pair import render_planned_opaque_blocks
from services.rendering.output.engineering import render_bilingual_inline_only


OPAQUE_MODES = {"title_block", "table_cell"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render mixed engineering sheets: opaque panels, then inline drawing captions."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument(
        "--ocr-json",
        type=Path,
        help="Supervised OCR JSON used to mask source text ink precisely.",
    )
    args = parser.parse_args()

    raw = json.loads(args.plan.read_text(encoding="utf-8"))
    plan = validate_multimodal_plan(
        prepare_multimodal_plan_payload(raw, source_pdf_path=args.source),
        source_pdf_path=args.source,
    )
    blocks = [dict(item) for item in plan["semantic_blocks"]]
    opaque = [
        item
        for item in blocks
        if str((item.get("placement") or {}).get("mode") or "") in OPAQUE_MODES
    ]
    inline = [item for item in blocks if item not in opaque]
    args.work_dir.mkdir(parents=True, exist_ok=True)
    ocr_regions = []
    if args.ocr_json:
        ocr_payload = json.loads(args.ocr_json.read_text(encoding="utf-8"))
        if isinstance(ocr_payload, list):
            ocr_regions = ocr_payload
        elif isinstance(ocr_payload, dict):
            for key in ("regions", "ocr_regions", "items"):
                value = ocr_payload.get(key)
                if isinstance(value, list):
                    ocr_regions = value
                    break
    panel_pdf = args.work_dir / f"{args.output.stem}.opaque-panels.pdf"
    panel_result = render_planned_opaque_blocks(
        source_pdf_path=args.source,
        output_pdf_path=panel_pdf,
        semantic_blocks=opaque,
        ocr_regions=ocr_regions,
        strict_execution=plan.get("execution_policy") == "strict_multimodal_execution",
    )
    inline_plan = dict(plan)
    inline_plan["semantic_blocks"] = inline
    regions = apply_multimodal_plan([], inline_plan)
    inline_result = render_bilingual_inline_only(
        source_pdf_path=panel_pdf,
        output_pdf_path=args.output,
        regions=regions,
        max_local_distance=96.0,
        draw_leaders=True,
        preserve_legacy_position=False,
    )
    result = {
        "source_pdf": str(args.source.resolve()),
        "output_pdf": str(args.output.resolve()),
        "opaque_blocks": len(opaque),
        "inline_blocks": len(inline),
        "opaque_rendered": panel_result["rendered_blocks"],
        "opaque_failed_block_ids": panel_result["failed_block_ids"],
        "inline_placements": inline_result.inline_placements,
        "inline_review_items": inline_result.review_items,
        "placement_audit": str(args.output.with_suffix(".inline-placement.json")),
    }
    args.output.with_suffix(".hybrid-render.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["opaque_failed_block_ids"] and not result["inline_review_items"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
