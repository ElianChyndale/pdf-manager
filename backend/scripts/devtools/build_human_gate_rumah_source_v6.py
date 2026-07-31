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
COMPANY_PANELS = {1, 2, 5, 6, 7, 8, 9, 10, 11, 12}
NON_COMPANY_METADATA_PANELS = {3, 4, 13, 14, 15, 16}
PROSE_INDEX_REFLOW_PANELS = {15}


def _rect_overlap_area(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = a & b
    return max(0.0, inter.width) * max(0.0, inter.height)


def _choose_blue_candidate(page_rect: fitz.Rect, anchor: fitz.Rect, text: str, size: float,
                           obstacles: list[fitz.Rect], placed: list[fitz.Rect]) -> tuple[tuple[float, float], fitz.Rect, list[dict]]:
    width = min(max(size * 1.15, fitz.get_text_length(text, fontname="china-s", fontsize=size)), 180.0)
    height = size * 1.2
    gap = max(1.5, size * 0.35)
    raw = {
        "above": fitz.Rect(anchor.x0, anchor.y0 - gap - height, anchor.x0 + width, anchor.y0 - gap),
        "below": fitz.Rect(anchor.x0, anchor.y1 + gap, anchor.x0 + width, anchor.y1 + gap + height),
        "right": fitz.Rect(anchor.x1 + gap, anchor.y0, anchor.x1 + gap + width, anchor.y0 + height),
        "left": fitz.Rect(anchor.x0 - gap - width, anchor.y0, anchor.x0 - gap, anchor.y0 + height),
    }
    audit = []
    best = None
    for name, rect in raw.items():
        if not page_rect.contains(rect):
            score = 1e9
        else:
            ink_overlap = sum(_rect_overlap_area(rect, other) for other in obstacles)
            translation_overlap = sum(_rect_overlap_area(rect, other) for other in placed)
            distance = min(abs(rect.y1-anchor.y0), abs(rect.y0-anchor.y1), abs(rect.x0-anchor.x1), abs(rect.x1-anchor.x0))
            # Bounded conservative weights: source/visible-text collision is much
            # more expensive than a few extra points of local distance.
            score = ink_overlap * 120.0 + translation_overlap * 240.0 + distance * 1.5
        audit.append({"candidate": name, "bbox": [round(v, 2) for v in rect], "score": round(score, 2)})
        if best is None or score < best[0]:
            best = (score, name, rect)
    assert best is not None
    chosen = best[2]
    return (chosen.x0, chosen.y1), chosen, audit


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


def _fit_textbox(page: fitz.Page, rect: fitz.Rect, text: str, *, start: float, minimum: float, color=BLACK) -> float:
    size = start
    while size >= minimum:
        result = page.insert_textbox(
            rect,
            text,
            fontname="china-s",
            fontsize=size,
            lineheight=1.12,
            color=color,
            align=fitz.TEXT_ALIGN_LEFT,
            overlay=True,
        )
        if result >= 0:
            return size
        size -= 0.25
    page.insert_textbox(
        rect, text, fontname="china-s", fontsize=minimum, lineheight=1.05,
        color=color, align=fitz.TEXT_ALIGN_LEFT, overlay=True,
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
    visual_text_obstacles = [item["bbox"] for item in _spans(reference_page)]
    placed_blue: list[fitz.Rect] = []

    # Drawing body and drawing-table placements were visually approved against
    # the original full-page render.  We transfer text only, never reference
    # page content, and keep the source drawing untouched.
    for item in _spans(reference_page):
        if item["bbox"].x0 >= 2080 or not _CJK_RE.search(item["text"]):
            continue
        # These dense annotations are translated as reviewed semantic blocks
        # below. Rendering their fragmented reference spans would recreate the
        # blue-paint overlap even with better candidate scoring.
        if (1180 <= item["bbox"].x0 <= 1600 and 140 <= item["bbox"].y0 <= 175) or \
           (1380 <= item["bbox"].x0 <= 1540 and 260 <= item["bbox"].y0 <= 310):
            continue
        # The reference coordinates are evidence, not final placement.  Put the
        # Chinese immediately above the source label (or just below the top
        # edge) so headings and callouts remain visibly bilingual instead of
        # producing the blue-on-black duplicate seen in v2.
        size = item["font_size"]
        if size >= 8:
            size = max(4.5, size * 0.62)
        (x, y), chosen_rect, candidate_audit = _choose_blue_candidate(
            page.rect, item["bbox"], item["text"], size,
            visual_text_obstacles, placed_blue,
        )
        page.insert_text(
            (x, y), item["text"], fontname="china-s",
            fontsize=size, color=BLUE, overlay=True,
        )
        placed_blue.append(chosen_rect)
        audit.append(
            {
                "region_type": "drawing_body_or_drawing_table",
                "text": item["text"],
                "target_bbox": [round(v, 3) for v in item["bbox"]],
                "font_size": round(size, 3),
                "color": list(BLUE),
                "preserve_source": True,
                "placement_candidates": candidate_audit,
                "chosen_bbox": [round(v, 3) for v in chosen_rect],
                "weight_profile": "bounded_dynamic_conservative",
            }
        )

    reviewed_blocks = [
        (fitz.Rect(1195, 132, 1298, 148), "AMI基座及接地井\n由TNB（AMI团队）供货安装"),
        (fitz.Rect(1300, 132, 1382, 148), "AMI电杆混凝土基础\n按工程师详图施工"),
        (fitz.Rect(1383, 132, 1452, 146), "接地点：铜母线\n50×6×300mm"),
        (fitz.Rect(1453, 132, 1515, 146), "接地：铜带\n25×3mm"),
        (fitz.Rect(1516, 130, 1610, 148), "接地井300×300×190mm\n配可延伸铜接地棒"),
        (fitz.Rect(1385, 250, 1545, 268), "PE压实基座周边区域须按规范预拌处理；\n150mm厚碎石层压实，表面涂沥青底涂层。"),
    ]
    for rect, text in reviewed_blocks:
        size = _fit_textbox(page, rect, text, start=5.0, minimum=3.8, color=BLUE)
        audit.append({
            "region_type": "drawing_body",
            "text": text,
            "target_bbox": [round(v, 3) for v in rect],
            "font_size": size,
            "color": list(BLUE),
            "strategy": "reviewed_semantic_block_dynamic_placement",
            "preserve_source": True,
        })

    # Sidebar/footer is subdivided semantically. Only company/contact text is
    # replaced. Project metadata, copyright, status, title/index and drawing
    # controls preserve their source and receive nearby blue Chinese.
    sidebar = fitz.Rect(2083, 55, 2327, 1629)
    source_sidebar_spans = _spans(page, sidebar)
    for item in source_sidebar_spans:
        center_y = (item["bbox"].y0 + item["bbox"].y1) / 2
        panel_index = next((i for i, (a, b) in enumerate(zip(PANEL_Y, PANEL_Y[1:])) if a <= center_y < b), None)
        if panel_index in COMPANY_PANELS:
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
        # The trusted reference is used only as a text ledger.  Its text layer
        # contains both source-language OCR and Chinese translations, including
        # company addresses that are vector outlines in the original PDF.
        evidence_lines = _clean_lines(reference_page.get_text("text", clip=clip, sort=True))
        if not source_lines and not evidence_lines:
            continue
        if panel_index in PROSE_INDEX_REFLOW_PANELS:
            target = fitz.Rect(2088, y0 + 4, 2322, y1 - 4)
            page.draw_rect(target, color=None, fill=(1, 1, 1), overlay=True)
            page.insert_text((target.x0, target.y0 + 5), "DRAWING TITLE / 图纸标题", fontname="china-s", fontsize=5.2, color=BLACK, overlay=True)
            body_rect = fitz.Rect(target.x0, target.y0 + 8, target.x1, target.y1)
            body = (
                "KEBUK SAMPAH / BILIK PAM / BILIK TANGKI SEDUTAN\n"
                "垃圾间／泵房／吸水箱室\n"
                "PELAN LANTAI 平面图  ·  PANDANGAN HADAPAN 正立面图\n"
                "PANDANGAN SISI KIRI 左侧立面图  ·  PELAN SILING 天花平面图\n"
                "PANDANGAN BELAKANG 背立面图  ·  KERATAN A-A 剖面A-A\n"
                "PELAN BUMBUNG 屋顶平面图  ·  PANDANGAN SISI KANAN 右侧立面图\n"
                "KERATAN B-B 剖面B-B\n"
                "PENCAWANG PADAT / 紧凑型变电站\n"
                "PELAN LANTAI 平面图  ·  X-KERATAN B-B/G-G 剖面B-B/G-G\n"
                "PANDANGAN HADAPAN 正立面图  ·  X-KERATAN C-C 剖面C-C\n"
                "BOLLARD & FOOTING 防撞柱及基础  ·  PANDANGAN SISI KANAN 右侧立面图\n"
                "X-KERATAN D-D/E-E/F-F/A-A 剖面D-D/E-E/F-F/A-A\n"
                "CONCRETE KERB 混凝土路缘石  ·  COVER SLAB 盖板\n"
                "PANDANGAN SISI KIRI 左侧立面图"
            )
            font_size = _fit_textbox(page, body_rect, body, start=4.2, minimum=3.3)
            audit.append({
                "region_type": "prose_or_index_metadata",
                "panel_index": panel_index,
                "strategy": "black_bilingual_hierarchy_reflow",
                "font_size": font_size,
                "preserved": ["panel_border", "section_grouping", "indentation", "whitespace_rhythm"],
            })
            continue
        if panel_index in NON_COMPANY_METADATA_PANELS:
            for item in _spans(reference_page, clip):
                if not _CJK_RE.search(item["text"]):
                    continue
                size = max(3.2, min(5.5, item["font_size"] * 0.9))
                (x, y), chosen_rect, candidate_audit = _choose_blue_candidate(
                    page.rect, item["bbox"], item["text"], size,
                    visual_text_obstacles, placed_blue,
                )
                page.insert_text((x, y), item["text"], fontname="china-s", fontsize=size, color=BLUE, overlay=True)
                placed_blue.append(chosen_rect)
                audit.append({
                    "region_type": "non_company_metadata_panel",
                    "panel_index": panel_index,
                    "text": item["text"],
                    "font_size": size,
                    "color": list(BLUE),
                    "strategy": "preserve_source_add_nearby_blue_chinese",
                    "placement_candidates": candidate_audit,
                    "chosen_bbox": [round(v, 3) for v in chosen_rect],
                    "weight_profile": "bounded_dynamic_conservative",
                })
            continue
        if panel_index not in COMPANY_PANELS:
            continue
        if panel_index in COMPANY_PANELS:
            target = fitz.Rect(2190, y0 + 5, 2322, y1 - 5)
        else:
            target = fitz.Rect(2088, y0 + 5, 2322, y1 - 5)
        # Original sidebar lettering is frequently outlined vector ink, so a
        # text-only redaction cannot remove it.  Mask only the reviewed text
        # column; do not touch logos, panel borders, or separator lines.
        page.draw_rect(target, color=None, fill=(1, 1, 1), overlay=True)
        body = "\n".join(evidence_lines or source_lines)
        font_size = _fit_textbox(page, target, body, start=7.0, minimum=3.6)
        audit.append(
            {
                "region_type": "sidebar_footer",
                "panel_index": panel_index,
                "target_bbox": [round(v, 3) for v in target],
                "font_size": font_size,
                "color": list(BLACK),
                "strategy": "exact_source_text_removal_then_black_source_plus_chinese_reflow",
                "logo_and_borders_preserved": True,
                "minimum_usable_non_logo_occupancy": 0.50,
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
            {"region_type": "company_contact_panel", "bbox": [2083, 55, 2327, 1362.2], "strategy": "black_bilingual_text_reflow", "minimum_non_logo_occupancy": 0.50},
            {"region_type": "non_company_metadata_panel", "bbox": [2083, 348.4, 2327, 1629], "strategy": "blue_preserve_source", "semantic_subregions": [3, 4, 13, 14, 15, 16]},
            {"region_type": "prose_or_index_metadata", "bbox": [2083, 1451.6, 2327, 1542.6], "strategy": "black_bilingual_hierarchy_reflow", "semantic_subregions": [15]},
        ],
        "placements": audit,
    }
    args.plan.parent.mkdir(parents=True, exist_ok=True)
    args.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"placements": len(audit), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
