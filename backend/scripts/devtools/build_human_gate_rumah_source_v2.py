# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import fitz

BLUE = (0.04, 0.22, 0.66)
BLACK = (0, 0, 0)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")

PANEL_Y = [
    55.3, 148.1, 248.2, 348.4, 484.7, 550.7, 659.3, 778.4,
    872.9, 970.2, 1070.3, 1170.4, 1266.2, 1362.2, 1398.6,
    1451.6, 1542.6, 1628.5,
]
LOGO_PANELS = {1, 2, 5, 6, 7, 8, 9, 10, 11, 12}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _spans(page: fitz.Page, clip: fitz.Rect | None = None) -> list[dict]:
    output: list[dict] = []
    data = page.get_text("dict", clip=clip, flags=fitz.TEXT_PRESERVE_LIGATURES)
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text") or "")
                bbox = span.get("bbox") or []
                origin = span.get("origin") or []
                if text.strip() and len(bbox) == 4 and len(origin) == 2:
                    output.append(
                        {
                            "text": text,
                            "bbox": fitz.Rect(*bbox),
                            "origin": (float(origin[0]), float(origin[1])),
                            "font_size": float(span.get("size") or 5),
                        }
                    )
    return output


def _clean_lines(text: str, *, chinese_only: bool = False) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line or (chinese_only and not _CJK_RE.search(line)) or line in seen:
            continue
        lines.append(line)
        seen.add(line)
    return lines


def _fit_textbox(page: fitz.Page, rect: fitz.Rect, text: str, *, start: float, minimum: float) -> float:
    size = start
    while size >= minimum:
        result = page.insert_textbox(
            rect,
            text,
            fontname="china-s",
            fontsize=size,
            lineheight=1.12,
            color=BLACK,
            align=fitz.TEXT_ALIGN_LEFT,
            overlay=True,
        )
        if result >= 0:
            return size
        size -= 0.25
    page.insert_textbox(
        rect, text, fontname="china-s", fontsize=minimum, lineheight=1.05,
        color=BLACK, align=fitz.TEXT_ALIGN_LEFT, overlay=True,
    )
    return minimum


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()

    source_sha = _sha256(args.source)
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    if ledger.get("source_sha256") != source_sha:
        raise SystemExit("ledger does not belong to the original source PDF")

    source = fitz.open(args.source)
    reference = fitz.open(args.reference)
    if source.page_count != 1 or reference.page_count != 1:
        raise SystemExit("this reviewed sample builder expects one-page PDFs")
    page = source[0]
    reference_page = reference[0]
    source.insert_page if False else None

    font = fitz.Font("china-s")
    page.insert_font(fontname="china-s", fontbuffer=font.buffer)
    audit: list[dict] = []

    # Drawing body and drawing-table placements were visually approved against
    # the original full-page render.  We transfer text only, never reference
    # page content, and keep the source drawing untouched.
    for item in _spans(reference_page):
        if item["bbox"].x0 >= 2080 or not _CJK_RE.search(item["text"]):
            continue
        page.insert_text(
            item["origin"], item["text"], fontname="china-s",
            fontsize=item["font_size"], color=BLUE, overlay=True,
        )
        audit.append(
            {
                "region_type": "drawing_body_or_drawing_table",
                "text": item["text"],
                "target_bbox": [round(v, 3) for v in item["bbox"]],
                "font_size": round(item["font_size"], 3),
                "color": list(BLUE),
                "preserve_source": True,
            }
        )

    # Remove only original sidebar text objects. Logos and vector borders are
    # untouched because redaction ignores graphics and images.
    sidebar = fitz.Rect(2083, 55, 2327, 1629)
    source_sidebar_spans = _spans(page, sidebar)
    for item in source_sidebar_spans:
        page.add_redact_annot(item["bbox"], fill=None, cross_out=False)
    page.apply_redactions(images=0, graphics=0, text=0)
    page.insert_font(fontname="china-s", fontbuffer=font.buffer)

    for panel_index, (y0, y1) in enumerate(zip(PANEL_Y, PANEL_Y[1:])):
        clip = fitz.Rect(2083, y0, 2327, y1)
        source_lines = _clean_lines(source[0].get_text("text", clip=clip, sort=True))
        # Source text was captured before redaction in the ledger extraction,
        # but page.get_text is now empty. Recover it from the saved spans.
        if not source_lines:
            source_lines = _clean_lines(
                "\n".join(
                    item["text"] for item in source_sidebar_spans
                    if item["bbox"].intersects(clip)
                )
            )
        chinese_lines = _clean_lines(
            reference_page.get_text("text", clip=clip, sort=True), chinese_only=True
        )
        if not source_lines and not chinese_lines:
            continue
        body = "原文：" + " / ".join(source_lines)
        if chinese_lines:
            body += "\n中文：" + " / ".join(chinese_lines)
        if panel_index in LOGO_PANELS:
            target = fitz.Rect(2190, y0 + 5, 2322, y1 - 5)
        else:
            target = fitz.Rect(2088, y0 + 5, 2322, y1 - 5)
        font_size = _fit_textbox(page, target, body, start=5.5, minimum=2.6)
        audit.append(
            {
                "region_type": "sidebar_footer",
                "panel_index": panel_index,
                "target_bbox": [round(v, 3) for v in target],
                "font_size": font_size,
                "color": list(BLACK),
                "strategy": "exact_source_text_removal_then_black_source_plus_chinese_reflow",
                "logo_and_borders_preserved": True,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    source.save(args.output, garbage=4, deflate=True)
    source.close()
    reference.close()
    plan = {
        "schema": "engineering-drawing-single-supervisor-human-gate-v1",
        "source_pdf": str(args.source.resolve()),
        "source_sha256": source_sha,
        "render_provenance": {
            "base": "original_source_pdf",
            "source_sha256": source_sha,
            "reference_usage": "translation_evidence_only",
            "copied_reference_page_or_region": False,
        },
        "reference_ledger": str(args.ledger.resolve()),
        "single_multimodal_supervisor": True,
        "page_regions": [
            {"region_type": "drawing_body", "bbox": [0, 0, 2080, 1683.78], "strategy": "blue_preserve_source"},
            {"region_type": "drawing_table", "bbox": [800, 70, 1160, 460], "strategy": "blue_preserve_source"},
            {"region_type": "sidebar_footer", "bbox": [2083, 55, 2327, 1629], "strategy": "black_bilingual_text_reflow"},
        ],
        "placements": audit,
    }
    args.plan.parent.mkdir(parents=True, exist_ok=True)
    args.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"placements": len(audit), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
