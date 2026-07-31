# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import fitz, json, hashlib

ROOT = Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
SOURCE = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\A3 DETAIL DRAWING\28_REV. JULAI 2025 GAZEBO.pdf")
WORK = ROOT / r"agent-artifacts/v4.0-readable-zone-complete/10-specialized"
OUT = ROOT / r"translated/v4.0-readable-zone-complete-candidates/10_gazebo-specialized-candidate.pdf"
BLUE = (.05, .16, .45)
BLACK = (0, 0, 0)

VIEW = {
    "plan": ("P", "底层平面图 / PLAN"),
    "roof_plan": ("R", "屋面平面图 / ROOF PLAN"),
    "front_elevation": ("F", "正立面 / FRONT ELEVATION"),
    "section_detail": ("S", "X-X剖面及详图1 / SECTION X-X & DETAIL 1"),
    "title_sidebar_footer": ("T", "标题栏、公司及状态信息 / TITLE, COMPANY & STATE"),
}


def add_group(page, rect, view, entries):
    prefix, title = VIEW[view]
    page.draw_rect(rect, color=(.45, .45, .45), width=.6)
    page.insert_textbox(fitz.Rect(rect.x0 + 8, rect.y0 + 6, rect.x1 - 8, rect.y0 + 28),
                        title, fontname="china-s", fontsize=9.2, color=BLACK)
    lines = []
    for number, block in entries:
        lines.append(f"[{prefix}{number}] {block['source_text']}\n中文：{block['translated_text']}")
    body = fitz.Rect(rect.x0 + 8, rect.y0 + 31, rect.x1 - 8, rect.y1 - 8)
    result = page.insert_textbox(body, "\n".join(lines), fontname="china-s", fontsize=6.8,
                                 lineheight=1.06, color=BLACK)
    if result < 0:
        raise RuntimeError(f"index overflow {view}: {result}")


def main():
    ledger = json.loads((WORK / "new-semantic-ledger.json").read_text(encoding="utf8"))
    doc = fitz.open(SOURCE)
    source_page = doc[0]
    font = fitz.Font("china-s")
    source_page.insert_font(fontname="china-s", fontbuffer=font.buffer)
    counters, groups, blocks = {}, {}, []

    # Page 1 preserves the source drawing; compact blue anchors identify the exact region.
    for block in ledger["blocks"]:
        view = block["view"]
        counters[view] = counters.get(view, 0) + 1
        number = counters[view]
        prefix = VIEW[view][0]
        x0, y0, _, _ = block["bbox"]
        anchor_x = max(7, x0 - 23)
        source_page.insert_text((anchor_x, max(8, y0)), f"[{prefix}{number}]",
                                fontname="china-s", fontsize=5.8, color=BLUE, overlay=True)
        item = dict(block)
        item.update({"anchor_number": number, "anchor_code": f"{prefix}{number}",
                     "page_index": 0})
        blocks.append(item)
        groups.setdefault(view, []).append((number, item))

    index_page = doc.new_page(width=source_page.rect.width, height=source_page.rect.height)
    index_page.insert_font(fontname="china-s", fontbuffer=font.buffer)
    index_page.insert_text((42, 43), "凉亭图纸双语编号说明索引 / GAZEBO BILINGUAL NUMBERED INDEX",
                           fontname="china-s", fontsize=15, color=BLACK)
    index_page.insert_text((42, 65),
                           "页1蓝色分区编号与本页编号一一对应；P=平面，R=屋面，F=正立面，S=剖面/详图，T=标题栏。",
                           fontname="china-s", fontsize=8.2, color=BLACK)

    rects = {
        "plan": fitz.Rect(42, 82, 582, 342),
        "roof_plan": fitz.Rect(608, 82, 1148, 342),
        "front_elevation": fitz.Rect(42, 358, 582, 614),
        "section_detail": fitz.Rect(608, 358, 1148, 614),
        "title_sidebar_footer": fitz.Rect(42, 630, 1148, 816),
    }
    for view in VIEW:
        add_group(index_page, rects[view], view, groups[view])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT, garbage=4, deflate=True)
    metadata = {"schema": "v4-sample10-two-page-specialized-candidate",
                "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                "blocks": blocks, "block_count": len(blocks), "page_count": 2,
                "index_mapping_count": len(blocks), "status": "candidate_requires_visual_review"}
    (WORK / "candidate-ledger.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"output": str(OUT), "blocks": len(blocks), "pages": 2}, ensure_ascii=False))


if __name__ == "__main__":
    main()
