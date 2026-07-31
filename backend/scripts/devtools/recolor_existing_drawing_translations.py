from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import fitz

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
BLUE = (0.04, 0.22, 0.66)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recolor registered existing Chinese in drawing regions while preserving black sidebar/footer reflow."
    )
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--sidebar-left", type=float, default=2080.0)
    args = parser.parse_args()

    document = fitz.open(args.reference)
    audit_items: list[dict] = []
    for page_index, page in enumerate(document):
        replacements: list[dict] = []
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES)
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = str(span.get("text") or "")
                    bbox = fitz.Rect(span.get("bbox") or ())
                    origin = span.get("origin") or (bbox.x0, bbox.y1)
                    if not text.strip() or not _CJK_RE.search(text) or bbox.x0 >= args.sidebar_left:
                        continue
                    replacements.append(
                        {
                            "text": text,
                            "bbox": bbox,
                            "origin": (float(origin[0]), float(origin[1])),
                            "font_size": float(span.get("size") or 5),
                        }
                    )
                    page.add_redact_annot(bbox, fill=None, cross_out=False)
        if replacements:
            page.apply_redactions(images=0, graphics=0, text=0)
            font = fitz.Font("china-s")
            page.insert_font(fontname="china-s", fontbuffer=font.buffer)
            for item in replacements:
                page.insert_text(
                    item["origin"],
                    item["text"],
                    fontname="china-s",
                    fontsize=item["font_size"],
                    color=BLUE,
                    overlay=True,
                )
                audit_items.append(
                    {
                        "page_index": page_index,
                        "bbox": [round(value, 3) for value in item["bbox"]],
                        "text": item["text"],
                        "font_size": round(item["font_size"], 3),
                        "region_type": "drawing_body_or_drawing_table",
                        "action": "reuse_existing_translation_recolor_blue",
                    }
                )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    document.save(args.output, garbage=4, deflate=True)
    document.close()
    audit = {
        "schema": "engineering-drawing-human-gate-reuse-v1",
        "single_multimodal_supervisor": True,
        "reference_pdf": str(args.reference.resolve()),
        "output_pdf": str(args.output.resolve()),
        "sidebar_left": args.sidebar_left,
        "drawing_translation_color": list(BLUE),
        "sidebar_strategy": "preserve_existing_black_bilingual_reflow",
        "reused_translation_count": len(audit_items),
        "items": audit_items,
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"reused_translation_count": len(audit_items), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
