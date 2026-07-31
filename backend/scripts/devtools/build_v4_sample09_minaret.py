# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import fitz, json, hashlib

ROOT = Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
SRC = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\A3 DETAIL DRAWING\13_REV. JULAI 2025 MENARA.pdf")
WORK = ROOT / r"agent-artifacts/v4.0-readable-zone-complete/09-specialized"
OUT = ROOT / r"translated/v4.0-readable-zone-complete-candidates/09_minaret-specialized-candidate.pdf"
BLUE = (.05, .16, .45)
BLACK = (0, 0, 0)

VIEW_LABELS = {
    "ground_floor_plan": "底层平面图 / GROUND FLOOR PLAN",
    "detail_a": "详图A / DETAIL A",
    "roof_plan_1": "屋顶平面图1 / ROOF PLAN 1",
    "tower_plan_1": "塔楼平面图1 / TOWER PLAN 1",
    "tower_plan_2": "塔楼平面图2 / TOWER PLAN 2",
    "section_xx": "X-X剖面 / SECTION X-X",
}

TITLE_ANCHORS = [
    (180, 320, "底层平面图"), (180, 600, "屋顶平面图1"),
    (180, 870, "塔楼平面图1"), (203, 1140, "塔楼平面图2"),
    (543, 1150, "X-X剖面"), (554, 325, "详图A"),
]

STATE_ANCHORS = [
    (45, 850, "绘制：APIZ"), (68, 850, "修订：00"),
    (45, 920, "日期：2025年7月"), (68, 920, "比例：1:100"),
    (148, 980, "施工图"),
]


def add_index_group(page, font, rect, view, entries):
    page.draw_rect(rect, color=(.45, .45, .45), width=.6)
    head = fitz.Rect(rect.x0 + 7, rect.y0 + 6, rect.x1 - 7, rect.y0 + 27)
    page.insert_textbox(head, VIEW_LABELS[view], fontname="china-s", fontsize=9.0,
                        color=BLACK, align=0, overlay=True)
    body = fitz.Rect(rect.x0 + 7, rect.y0 + 30, rect.x1 - 7, rect.y1 - 7)
    lines = []
    for number, block in entries:
        lines.append(f"[{number}] {block['source_text']}\n中文：{block['translated_text']}")
    result = page.insert_textbox(body, "\n".join(lines), fontname="china-s", fontsize=6.8,
                                 lineheight=1.08, color=BLACK, overlay=True)
    if result < 0:
        raise RuntimeError(f"index group overflow: {view}, deficit={result}")


def main():
    ledger = json.loads((WORK / "new-semantic-ledger.json").read_text(encoding="utf8"))
    doc = fitz.open(SRC)
    source_page = doc[0]
    font = fitz.Font("china-s")
    source_page.insert_font(fontname="china-s", fontbuffer=font.buffer)
    blocks, groups, counters = [], {}, {}

    # Page 1: immutable source drawing plus compact, one-to-one blue anchors.
    for block in ledger["blocks"]:
        view = block["view"]
        counters[view] = counters.get(view, 0) + 1
        number = counters[view]
        x0, y0, _, _ = block["bbox"]
        source_page.insert_text((x0, max(7, y0 - 2)), f"[{number}]", fontname="china-s",
                                fontsize=5.8, color=BLUE, overlay=True)
        item = dict(block)
        item.update({"page_index": 0, "anchor_number": number,
                     "render_mode": "preserve_source_blue_chinese"})
        blocks.append(item)
        groups.setdefault(view, []).append((number, item))

    # Only short drawing titles stay on page 1; the long notes are moved to page 2.
    for i, (x, y, text) in enumerate(TITLE_ANCHORS, 1):
        source_page.insert_text((x, y), text, fontname="china-s", fontsize=6.8,
                                color=BLUE, overlay=True)
        blocks.append({"block_id": f"title-{i}", "source_ids": [f"title-{i}-src"],
                       "source_text": text, "translated_text": text,
                       "bbox": [x, y, x + 85, y + 10], "page_index": 0,
                       "view": "title", "rotation": 0, "zone": "drawing_body",
                       "render_mode": "preserve_source_blue_chinese", "status": "translated"})

    for i, (x, y, text) in enumerate(STATE_ANCHORS, 1):
        source_page.insert_text((x, y), text, fontname="china-s", fontsize=5.8,
                                color=BLUE, rotate=90, overlay=True)
        blocks.append({"block_id": f"state-{i}", "source_ids": [f"state-{i}-src"],
                       "source_text": text, "translated_text": text,
                       "bbox": [x, y, x + 10, y + 72], "page_index": 0,
                       "view": "left_panel", "rotation": 90,
                       "zone": "state_bearing_metadata",
                       "render_mode": "preserve_source_blue_chinese", "status": "translated"})

    # Page 2: clean, full bilingual index. Each region has independent geometry.
    index_page = doc.new_page(width=source_page.rect.width, height=source_page.rect.height)
    index_page.insert_font(fontname="china-s", fontbuffer=font.buffer)
    index_page.insert_text((42, 46), "塔楼图纸双语编号说明索引 / BILINGUAL NUMBERED NOTE INDEX",
                           fontname="china-s", fontsize=15, color=BLACK)
    index_page.insert_text((42, 68), "页1蓝色编号与本页分区编号一一对应；原图内容保持不变。",
                           fontname="china-s", fontsize=8.5, color=BLACK)

    project = ("PROJECT TITLE / 项目名称\n"
               "CADANGAN MEROBOH DAN MEMBINA SEMULA MASJID AL-EHSAN KAMPUNG TOK MUDA, KAPAR, "
               "DAERAH KLANG, SELANGOR DARUL EHSAN\n"
               "拟拆除并重建雪兰莪州巴生县加埔甘榜托穆达阿依善清真寺")
    company = ("AC ARCHITECTS SDN BHD / AC建筑师事务所\n"
               "SUITE 8-A0, 5TH LEVEL, TOWER A, PANDAN KAPITAL, PERSIARAN MPAJ, PANDAN INDAH, "
               "55100 SELANGOR DARUL EHSAN\n"
               "地址：雪兰莪州班丹英达MPAJ大道班丹资本大厦A座5层8-A0室，邮编55100；"
               "电话：03-4294 4122；邮箱：acarch.sfb@gmail.com")
    meta_rect = fitz.Rect(42, 82, 800, 194)
    index_page.draw_rect(meta_rect, color=(.45, .45, .45), width=.6)
    meta_result = index_page.insert_textbox(fitz.Rect(50, 90, 792, 187), project + "\n\n" + company,
                                            fontname="china-s", fontsize=7.4,
                                            lineheight=1.12, color=BLACK)
    if meta_result < 0:
        raise RuntimeError(f"metadata overflow: {meta_result}")

    order = ["ground_floor_plan", "detail_a", "roof_plan_1",
             "tower_plan_1", "tower_plan_2", "section_xx"]
    rects = [
        fitz.Rect(42, 208, 412, 495), fitz.Rect(430, 208, 800, 495),
        fitz.Rect(42, 510, 412, 797), fitz.Rect(430, 510, 800, 797),
        fitz.Rect(42, 812, 412, 1144), fitz.Rect(430, 812, 800, 1144),
    ]
    for view, rect in zip(order, rects):
        add_index_group(index_page, font, rect, view, groups[view])

    # The metadata has source on page 1 and complete bilingual reflow on page 2.
    for i, (zone, text) in enumerate([("prose_or_index_metadata", project),
                                      ("company_contact_panel", company)], 1):
        blocks.append({"block_id": f"left-index-{i}", "source_ids": [f"left-index-{i}-src"],
                       "source_text": text.split("\n", 1)[-1], "translated_text": text,
                       "bbox": list(meta_rect), "page_index": 1, "view": "index_metadata",
                       "rotation": 0, "zone": zone,
                       "render_mode": "opaque_bilingual_reflow", "status": "translated",
                       "old_glyph_visibility": "not_applicable_new_index_page", "partial": False})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT, garbage=4, deflate=True)
    metadata = {"schema": "v4-sample09-two-page-specialized-candidate",
                "source_sha256": hashlib.sha256(SRC.read_bytes()).hexdigest(),
                "blocks": blocks, "block_count": len(blocks), "page_count": 2,
                "index_mapping_count": len(ledger["blocks"]),
                "status": "candidate_requires_visual_review"}
    (WORK / "candidate-ledger.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"output": str(OUT), "blocks": len(blocks), "pages": 2}, ensure_ascii=False))


if __name__ == "__main__":
    main()
