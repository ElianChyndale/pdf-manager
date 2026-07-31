# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image


ROOT = Path(r"D:\AmyProjects\business")
OUT = ROOT / "pdf-manager" / "tmp" / "pdfs" / "engineering-drawing-semantic-v3"
FONT = r"C:\Windows\Fonts\simhei.ttf"
FONT_BOLD = r"C:\Windows\Fonts\simhei.ttf"
BLUE = (0.05, 0.22, 0.68)
BLACK = (0, 0, 0)


def insert_textbox(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    size: float,
    color=BLUE,
    bold: bool = False,
    align: int = 0,
    fill=None,
    rotate: int = 0,
) -> None:
    if fill is not None:
        page.draw_rect(rect, color=None, fill=fill, overlay=True)
    fontname = "simhei-bold" if bold else "simhei"
    page.insert_font(fontname=fontname, fontfile=FONT_BOLD if bold else FONT)
    trial = size
    while trial >= 1.8:
        shape = page.new_shape()
        spare = shape.insert_textbox(
            rect,
            text,
            fontname=fontname,
            fontsize=trial,
            color=color,
            align=align,
            lineheight=1.05,
            rotate=rotate,
        )
        if spare >= 0:
            shape.commit(overlay=True)
            return
        trial -= 0.25
    raise RuntimeError(f"text did not fit in {tuple(rect)}: {text[:80]!r}")


def display_rect(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    return rect * page.rotation_matrix if page.rotation else rect


def semantic_hits(page: fitz.Page, term: str, *, join_gap: float = 3.0) -> list[fitz.Rect]:
    """Return one displayed rectangle per visible text instance.

    Some CAD PDFs expose both per-character and full-word search hits. A raw
    search can therefore return 10–20 overlapping boxes for one visible label.
    Merge horizontally connected hits on the same baseline before placement.
    """
    rects = [display_rect(page, r) for r in page.search_for(term)]
    groups: list[fitz.Rect] = []
    for rect in sorted(rects, key=lambda r: (round(r.y0, 1), r.x0)):
        merged = False
        for i, group in enumerate(groups):
            vertical_overlap = min(group.y1, rect.y1) - max(group.y0, rect.y0)
            same_line = vertical_overlap >= 0.55 * min(group.height, rect.height)
            horizontal_gap = max(rect.x0 - group.x1, group.x0 - rect.x1, 0)
            if same_line and horizontal_gap <= join_gap:
                groups[i] = group | rect
                merged = True
                break
        if not merged:
            groups.append(fitz.Rect(rect))
    # Re-run until transitive character chains are fully merged.
    changed = True
    while changed:
        changed = False
        out: list[fitz.Rect] = []
        for rect in groups:
            for i, group in enumerate(out):
                vertical_overlap = min(group.y1, rect.y1) - max(group.y0, rect.y0)
                same_line = vertical_overlap >= 0.55 * min(group.height, rect.height)
                horizontal_gap = max(rect.x0 - group.x1, group.x0 - rect.x1, 0)
                if same_line and horizontal_gap <= join_gap:
                    out[i] = group | rect
                    changed = True
                    break
            else:
                out.append(rect)
        groups = out
    return groups


def flattened_page(source_pdf: Path) -> tuple[fitz.Document, fitz.Page, fitz.Document, fitz.Page]:
    source_doc = fitz.open(source_pdf)
    source_page = source_doc[0]
    pix = source_page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0), alpha=False)
    out_doc = fitz.open()
    out_page = out_doc.new_page(
        width=source_page.rect.width,
        height=source_page.rect.height,
    )
    out_page.insert_image(out_page.rect, stream=pix.tobytes("png"))
    return source_doc, source_page, out_doc, out_page


def leader(page: fitz.Page, anchor: tuple[float, float], target: tuple[float, float]) -> None:
    page.draw_line(anchor, target, color=BLUE, width=0.55, overlay=True)
    page.draw_circle(anchor, 1.3, color=BLUE, fill=(1, 1, 1), width=0.5, overlay=True)


def restore_a3_title_grid(page: fitz.Page) -> None:
    for x in (35, 340, 505, 704, 925, 1170):
        page.draw_line((x, 704), (x, 813), color=BLACK, width=0.7, overlay=True)
    page.draw_line((35, 704), (1170, 704), color=BLACK, width=0.7, overlay=True)
    page.draw_line((35, 813), (1170, 813), color=BLACK, width=0.7, overlay=True)


def bilingual_reflow(
    page: fitz.Page,
    rect: fitz.Rect,
    source: str,
    chinese: str,
    *,
    source_size: float,
    chinese_size: float,
    bold: bool = False,
) -> None:
    inner = fitz.Rect(rect.x0 + 1.2, rect.y0 + 0.8, rect.x1 - 1.2, rect.y1 - 0.8)
    page.draw_rect(inner, color=None, fill=(1, 1, 1), overlay=True)
    split = inner.y0 + max(source_size * 1.3, inner.height * 0.45)
    insert_textbox(
        page,
        fitz.Rect(inner.x0, inner.y0, inner.x1, split),
        source,
        size=source_size,
        color=BLACK,
        bold=bold,
    )
    insert_textbox(
        page,
        fitz.Rect(inner.x0, split, inner.x1, inner.y1),
        chinese,
        size=chinese_size,
        color=BLACK,
        bold=bold,
    )


def build_corner_bead() -> Path:
    src = ROOT / "WROK-CONTENT" / "malasia" / "A3 DETAIL DRAWING" / "17-CORNER BEAD DETAIL.pdf"
    source_doc, source_page, doc, page = flattened_page(src)

    notes = [
        ((135, 66), (137, 89), "抹灰用 uPVC 滴水线", True),
        ((137, 101), (139, 117), "U 形槽圆边滴水线", True),
        ((779, 67), (779, 90), "抹灰／饰面用 uPVC 护角条", True),
        ((795, 101), (796, 117), "锐角型", True),
        ((491, 389), (491, 410), "薄抹灰层用 uPVC 护角条", True),
        ((505, 429), (505, 446), "薄抹灰墙角条", True),
        ((145, 348), (145, 365), "适用于外部钢筋混凝土雨篷、阳台及平屋面檐口", False),
        ((145, 363), (145, 379), "防止雨水沿饰面底部回流并形成污痕", False),
        ((790, 338), (790, 378), "适用于抹灰和饰面施工", False),
        ((790, 355), (790, 390), "易形成 90° 平直外角", False),
        ((790, 367), (790, 402), "加强并保护墙角免受碰撞等损坏", False),
        ((735, 678), (760, 674), "适用于薄抹灰施工", False),
        ((735, 689), (760, 686), "易形成 90° 平直外角", False),
        ((735, 700), (760, 698), "加强并保护墙角免受碰撞等损坏", False),
    ]
    for anchor, target, text, bold in notes:
        width = 230 if len(text) > 16 else 175
        rect = fitz.Rect(target[0], target[1], target[0] + width, target[1] + (20 if bold else 16))
        insert_textbox(page, rect, text, size=8.4 if bold else 7.2, bold=bold)
        # Bullet translations placed directly below the source block do not
        # need a leader. Other labels retain a short local leader.
        if not (target[0] == 790 and not bold):
            leader(page, anchor, target)

    detail_notes = [
        ((310, 278), fitz.Rect(420, 274, 555, 320), "钢筋混凝土梁／板\n抹灰饰面：外、底面 20 mm；内、底面 10 mm\nAGL 3-6 滴水线"),
        ((970, 260), fitz.Rect(1035, 292, 1165, 328), "AW2-3 护角条\n24 mm 水泥抹灰\n102 mm 厚砖墙"),
        ((650, 625), fitz.Rect(760, 638, 900, 674), "SG2020 薄抹灰护角条\n2–3 mm 薄抹灰层\nAAC 砌块"),
    ]
    for anchor, rect, text in detail_notes:
        insert_textbox(page, rect, text, size=6.8)
        leader(page, anchor, (rect.x0, rect.y0 + 4))

    # Bottom/title panel is a non-drawing information zone: clear only text
    # interiors and re-typeset source + Chinese in black.
    title_cells = [
        fitz.Rect(36, 704, 338, 813),
        fitz.Rect(340, 704, 505, 813),
        fitz.Rect(704, 704, 925, 813),
    ]
    for rect in title_cells:
        page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions(images=0, graphics=0, text=0)
    insert_textbox(page, fitz.Rect(39, 707, 334, 812),
        "PROJECT TITLE / 项目名称\nCADANGAN MEROBOH DAN MEMBINA SEMULA MASJID AL-EHSAN,\nKAMPUNG TOK MUDA, KAPAR, DAERAH KLANG, SELANGOR DARUL EHSAN\n拟拆除并重建雪兰莪州巴生县 Tok Muda 村 Al-Ehsan 清真寺",
        size=7.2, color=BLACK, bold=True)
    insert_textbox(page, fitz.Rect(343, 707, 502, 812),
        "DRAWING TITLE / 图纸名称\nTYPICAL CORNER BEAD\n典型护角条详图\n• ROUND EDGE WITH U-GROOVE DRIP LINE / U形槽圆边滴水线\n• SHARP EDGE / 锐角型\n• SKIM COAT WALL ANGLE / 薄抹灰墙角条",
        size=6.1, color=BLACK, bold=True)
    insert_textbox(page, fitz.Rect(708, 707, 922, 812),
        "DRAWING NO. / 图纸编号\nACASB 2401/MTM/CB/DT-01\nREVISION / 修订：00\nSCALE / 比例：NTS\nDRAWN BY / 绘制：NAZMI\nDATE / 日期：JULAI 2025",
        size=6.4, color=BLACK, bold=True)
    restore_a3_title_grid(page)
    page.draw_rect(
        fitz.Rect(916, 673, 1145, 697),
        color=None,
        fill=(1, 1, 1),
        overlay=True,
    )
    insert_textbox(
        page,
        fitz.Rect(920, 675, 1142, 695),
        "CONSTRUCTION DRAWING / 施工图",
        size=11.0,
        color=(1, 0, 0),
        bold=True,
        align=1,
    )

    out = OUT / "01_ARCHITECTURAL_CORNER_BEAD_V3.pdf"
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    source_doc.close()
    return out


def find_one(page: fitz.Page, text: str) -> fitz.Rect | None:
    hits = page.search_for(text)
    return hits[0] if hits else None


def build_door_schedule() -> Path:
    src = ROOT / "WROK-CONTENT" / "malasia" / "A3 DETAIL DRAWING" / "02_REV. JULAI 2025 JADUAL PINTU & TINGKAP.pdf"
    source_doc, source_page, doc, page = flattened_page(src)

    left_labels = {
        "ELEVATION": "立面",
        "FLOOR LEVEL": "楼面标高",
        "MATERIAL": "材料",
        "FINISHES": "饰面",
        "HINGES": "合页",
        "LOCKSET": "锁具",
        "CLOSER": "闭门器",
        "STOPPER": "门挡",
        "CORE": "门芯",
        "ARCHITRAVE": "门套线",
        "REMARKS": "备注",
        "FRAMING": "门框",
        "ROOM & BLOCK": "房间及分区",
        "TOTAL NOS.": "总数量",
    }
    for source_text, zh in left_labels.items():
        rect = next(
            (
                display_rect(source_page, item)
                for item in source_page.search_for(source_text)
                if display_rect(source_page, item).x0 < 170
                and display_rect(source_page, item).y0 < 700
            ),
            None,
        )
        if not rect:
            continue
        target = fitz.Rect(rect.x1 + 2, rect.y0 - 1, rect.x1 + 42, rect.y1 + 4)
        insert_textbox(
            page,
            target,
            zh,
            size=5.4,
            color=BLUE,
        )

    manual_rows = [
        (323, "MATERIAL / 材料"),
        (339, "FINISHES / 饰面"),
        (355, "HINGES / 合页"),
        (371, "LOCKSET / 锁具"),
        (387, "CLOSER / 闭门器"),
        (403, "STOPPER / 门挡"),
        (419, "CORE / 门芯"),
        (435, "ARCHITRAVE / 门套线"),
        (451, "REMARKS / 备注"),
        (476, "FRAMING / 门框"),
        (503, "ROOM & BLOCK / 房间及分区"),
        (675, "TOTAL NOS. / 总数量"),
    ]
    for y, text in manual_rows:
        insert_textbox(page, fitz.Rect(74, y, 153, y + 12), text, size=5.2, color=BLUE)

    # Some schedule labels are vector outlines and therefore absent from PDF
    # search results. The multimodal coverage pass supplies their fixed visual
    # anchors explicitly.
    for rect, text in [
        (fitz.Rect(75, 169, 145, 181), "ELEVATION / 立面"),
        (fitz.Rect(75, 294, 150, 306), "FLOOR LEVEL / 楼面标高"),
        (fitz.Rect(115, 604, 180, 616), "ANCILLARY / 附属用房"),
    ]:
        insert_textbox(page, rect, text, size=5.4, color=BLUE, bold=True)

    descriptions = {
        "STEEL FRAME SINGLE LEAF DECORATIVE SOLID TIMBER DOOR TO MANUF'S DETAIL / ARCH'S SELECTION":
            "钢框单扇装饰实木门，按厂家详图／建筑师选型",
        "STEEL FRAME DOUBLE LEAF DECORATIVE SOLID TIMBER DOOR TO MANUF'S DETAIL / ARCH'S SELECTION":
            "钢框双扇装饰实木门，按厂家详图／建筑师选型",
        "STEEL FRAME SINGLE LEAF PLYWOOD FLUSH DOOR WITH WATERPROOF TREATMENT ON PANEL FOR BOTHSIDE TO MANUF'S DETAIL":
            "钢框单扇夹板平板门，两面板作防水处理，按厂家详图",
        "STEEL FRAME DOUBLE LEAF PLYWOOD FLUSH DOOR WITH WATERPROOF TREATMENT ON PANEL FOR BOTHSIDE TO MANUF'S DETAIL":
            "钢框双扇夹板平板门，两面板作防水处理，按厂家详图",
    }
    y_band = (284, 324)
    columns = [(155, 350), (350, 545), (545, 740), (740, 935), (935, 1130)]
    # Repeated door-elevation callouts are independent visible instances.
    for x0, x1 in columns:
        insert_textbox(
            page,
            fitz.Rect(x1 - 58, 171, x1 - 4, 190),
            "钢筋混凝土过梁\n详见工程师详图",
            size=4.2,
            color=BLUE,
        )
        insert_textbox(
            page,
            fitz.Rect(x1 - 48, 240, x1 - 4, 251),
            "HINGES / 合页",
            size=4.5,
            color=BLUE,
        )
    col_pairs = [
        (list(descriptions)[0], descriptions[list(descriptions)[0]]),
        (list(descriptions)[1], descriptions[list(descriptions)[1]]),
        (list(descriptions)[2], descriptions[list(descriptions)[2]]),
        (list(descriptions)[3], descriptions[list(descriptions)[3]]),
        (list(descriptions)[3], descriptions[list(descriptions)[3]]),
    ]
    for (x0, x1), (en, zh) in zip(columns, col_pairs):
        # Drawing/table body: transparent nearby translation only.
        insert_textbox(
            page,
            fitz.Rect(x0 + 4, 309, x1 - 4, 323),
            zh,
            size=5.2,
            color=BLUE,
        )

    value_terms = {
        "TIMBER": "木材",
        "PAINT": "油漆",
        "HIGH QUALITY LEVER MORTISE LOCKSET": "优质执手插芯锁",
        "MAGNETIC DOOR STOPPER": "磁性门挡",
        "RUBBER DOOR STOPPER": "橡胶门挡",
        "SOLID TIMBER CORE WITH STRUCTURAL FRAMING": "带结构框架的实木门芯",
        "HONEYCOMB CORE WITH STRUCTURAL FRAMING": "带结构框架的蜂窝门芯",
    }
    for en, zh in value_terms.items():
        for raw_rect in source_page.search_for(en):
            rect = display_rect(source_page, raw_rect)
            if rect.y0 < 320 or rect.y0 > 500:
                continue
            add = fitz.Rect(rect.x1 + 3, rect.y0 - 1, min(rect.x1 + 70, page.rect.x1 - 5), rect.y1 + 4)
            insert_textbox(page, add, zh, size=4.8, color=BLUE)

    cell_zh = [
        (339, ["木材"] * 5),
        (355, ["油漆"] * 5),
        (371, ["不锈钢合页（4只）", "不锈钢合页（8只）", "不锈钢合页（4只）", "不锈钢合页（8只）", "不锈钢合页（8只）"]),
        (387, ["优质执手插芯锁"] * 5),
        (403, ["无"] * 5),
        (419, ["磁性门挡", "磁性门挡", "橡胶门挡", "橡胶门挡", "橡胶门挡"]),
        (435, ["结构框架实木门芯", "结构框架实木门芯", "结构框架蜂窝门芯", "结构框架蜂窝门芯", "结构框架蜂窝门芯"]),
        (451, ["无"] * 5),
    ]
    for y, texts in cell_zh:
        for (x0, x1), text in zip(columns, texts):
            insert_textbox(page, fitz.Rect(x0 + 70, y, x1 - 3, y + 11), text, size=4.7, color=BLUE)

    room_notes = [
        (fitz.Rect(212, 505, 350, 535), "清真寺：伊玛目室、扩音室"),
        (fitz.Rect(350, 505, 545, 535), "清真寺：无"),
        (fitz.Rect(545, 505, 740, 545), "塔楼通道、办公室、男卫生间、男小净室"),
        (fitz.Rect(740, 505, 935, 545), "女卫生间、男卫生间、杂物间、女小净室"),
        (fitz.Rect(935, 505, 1128, 535), "遗体室"),
        (fitz.Rect(212, 568, 350, 600), "办公室、贵宾室、会议室、祈祷室 1／2"),
        (fitz.Rect(350, 568, 545, 590), "婚姻登记室"),
    ]
    for rect, text in room_notes:
        insert_textbox(page, rect, text, size=5.2, color=BLUE)

    for rect in source_page.search_for("HINGES"):
        if rect.y0 < 250:
            insert_textbox(page, fitz.Rect(rect.x0, rect.y1, rect.x0 + 35, rect.y1 + 10), "合页", size=5.0)
    insert_textbox(page, fitz.Rect(74, 690, 160, 705), "门表（D1–D5）", size=7.2, color=BLUE, bold=True)
    # Bottom panel only: opaque bilingual reflow.
    bottom_cell = fitz.Rect(340, 704, 505, 813)
    page.add_redact_annot(bottom_cell, fill=(1, 1, 1))
    page.apply_redactions(images=0, graphics=0, text=0)
    insert_textbox(page, fitz.Rect(343, 707, 502, 812),
        "DRAWING TITLE / 图纸名称\nMASJID, PEJABAT & ANCILLARY\n清真寺、办公室及附属用房\nJADUAL PINTU / 门表",
        size=7.0, color=BLACK, bold=True)
    # Other bottom cells are also information-only. Keep their borders and
    # logo cell untouched; reflow only the interior text.
    for rect in [fitz.Rect(36, 704, 338, 813), fitz.Rect(704, 704, 925, 813)]:
        page.draw_rect(
            fitz.Rect(rect.x0 + 1, rect.y0 + 1, rect.x1 - 1, rect.y1 - 1),
            color=None,
            fill=(1, 1, 1),
            overlay=True,
        )
    insert_textbox(page, fitz.Rect(39, 707, 334, 812),
        "PROJECT TITLE / 项目名称\nCADANGAN MEROBOH DAN MEMBINA SEMULA MASJID AL-EHSAN,\nKAMPUNG TOK MUDA, KAPAR, DAERAH KLANG, SELANGOR DARUL EHSAN\n拟拆除并重建雪兰莪州巴生县 Tok Muda 村 Al-Ehsan 清真寺",
        size=7.0, color=BLACK, bold=True)
    insert_textbox(page, fitz.Rect(708, 707, 922, 812),
        "DRAWING NO. / 图纸编号\nACASB 2401/MTM/DW/DT-01\nREVISION / 修订：00\nSCALE / 比例：1:50\nDRAWN BY / 绘制：APIZ\nDATE / 日期：JULAI 2025",
        size=6.3, color=BLACK, bold=True)
    restore_a3_title_grid(page)
    page.draw_rect(
        fitz.Rect(916, 673, 1145, 697),
        color=None,
        fill=(1, 1, 1),
        overlay=True,
    )
    insert_textbox(
        page,
        fitz.Rect(920, 675, 1142, 695),
        "CONSTRUCTION DRAWING / 施工图",
        size=11.0,
        color=(1, 0, 0),
        bold=True,
        align=1,
    )

    out = OUT / "02_DOOR_SCHEDULE_PAGE1_V3.pdf"
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    source_doc.close()
    return out


def build_sld() -> Path:
    src = ROOT / "WROK-CONTENT" / "malasia" / "报审图纸" / "275kV MEP Construction Drawing_260610" / "Construction Drawing" / "RCJM2 CN ELEC 20260610" / "Constrcution Drawing PDF" / "1310-CN-ELEC-SCH-C001_275kV SLD.pdf"
    source_doc, source_page, doc, page = flattened_page(src)

    pairs = {
        "TNB INCOMER 1": "TNB 进线 1",
        "TNB INCOMER 2": "TNB 进线 2",
        "INDUCTIVE VOLTAGE TRANSFORMER": "电磁式电压互感器",
        "BUS SECTION": "母线分段",
        "TO LVAC": "至低压交流系统",
        "TO BUSBAR": "至母线",
        "FUTURE PHASE": "远期阶段",
        "NEUTRAL EARTHING NO. 1": "中性点接地 1",
        "NEUTRAL EARTHING NO. 2": "中性点接地 2",
        "FAST ACTING EARTH SWITCH": "快速接地开关",
        "TNB MAIN METER": "TNB 主计量表",
        "TNB CHECK METER": "TNB 校核表",
        "TO 11KV SWITCHGEAR 2-A": "至11kV开关柜2-A",
        "TO 11KV SWITCHGEAR 2-B": "至11kV开关柜2-B",
        "TO 1KV SWITCHGEAR 1-A": "至11kV开关柜1-A",
        "TO 1KV SWITCHGEAR 1-B": "至11kV开关柜1-B",
        "TO 1KV SWITCHGEAR 2-A": "至11kV开关柜2-A",
        "TO 1KV SWITCHGEAR 2-B": "至11kV开关柜2-B",
        "NEUTRAL EARTHING NO. 2": "中性点接地装置2",
    }
    for en, zh in pairs.items():
        for rect in semantic_hits(source_page, en):
            if len(en) >= 6 and rect.width < max(12, len(en) * 1.8):
                continue
            width = max(72, min(165, len(zh) * 13))
            if en == "FUTURE PHASE":
                target = fitz.Rect(rect.x0, rect.y1 + 1.5, rect.x0 + width, rect.y1 + 16)
            elif rect.y0 > 1450:
                target = fitz.Rect(rect.x0, rect.y1 + 2, rect.x0 + width, rect.y1 + 17)
            else:
                target = fitz.Rect(rect.x1 + 4, rect.y0 - 1, rect.x1 + 4 + width, rect.y1 + 7)
            if target.x1 > page.rect.x1 - 20:
                target = fitz.Rect(max(20, rect.x0 - width - 4), rect.y0 - 1, rect.x0 - 4, rect.y1 + 7)
            insert_textbox(
                page,
                target,
                zh,
                size=max(5.0, min(7.5, rect.height * 0.72)),
            )

    # Protection / equipment codes carry operational meaning. Preserve the
    # source code and add a compact Chinese functional label once per visible
    # instance after CAD-character candidates have been merged.
    code_meanings = {
        "CSE": "电缆侧接地开关",
        "ZN": "中性点接地装置",
    }
    for code, zh in code_meanings.items():
        for rect in semantic_hits(source_page, code, join_gap=2.5):
            if rect.x0 > 2050:
                continue
            width = min(105, max(56, len(zh) * 7.0))
            candidates = [
                fitz.Rect(rect.x1 + 3, rect.y0 - 1, rect.x1 + 3 + width, rect.y1 + 9),
                fitz.Rect(rect.x0, rect.y1 + 1, rect.x0 + width, rect.y1 + 12),
                fitz.Rect(max(4, rect.x0 - width - 3), rect.y0 - 1, rect.x0 - 3, rect.y1 + 9),
            ]
            target = next(
                (candidate for candidate in candidates if candidate.x1 < 2050 and candidate.y1 < 1635),
                candidates[-1],
            )
            insert_textbox(page, target, zh, size=5.5, color=BLUE)

    insert_textbox(
        page,
        fitz.Rect(910, 126, 1045, 143),
        "保护代码图例",
        size=7.2,
        color=BLUE,
        bold=True,
    )

    # Object-level parameter notes planned from the electrical object graph.
    # These complement, rather than replace, the source numbers and codes.
    for rect, text, size in [
        (fitz.Rect(367, 1255, 430, 1272), "变压器2", 5.5),
        (fitz.Rect(1812, 1303, 1875, 1320), "变压器1", 5.5),
        (fitz.Rect(575, 1417, 735, 1434), "12千伏；1600安；31.5千安短时耐受3秒", 5.2),
        (fitz.Rect(1054, 1465, 1215, 1482), "12千伏；1600安；31.5千安短时耐受3秒", 5.2),
        (fitz.Rect(515, 1555, 790, 1584),
         "CT：1600/1安；PX级（Vk≥600伏，Vk/2时励磁≤10毫安）\n"
         "5P20级／30伏安；接地支路1600安／4欧，耐受10秒", 4.8),
        (fitz.Rect(1035, 1553, 1260, 1585),
         "CT：1600/1安；PX级（Vk≥600伏，Vk/2时励磁≤10毫安）\n"
         "5P20级／30伏安；接地支路1600安／4欧，耐受10秒", 4.8),
        (fitz.Rect(1433, 1528, 1503, 1558),
         "11/0.415千伏\nZNyn11接线组\n1000千伏安", 4.5),
        (fitz.Rect(321, 1577, 395, 1610),
         "11/0.415千伏\nZNyn11接线组\n1000千伏安", 4.5),
        (fitz.Rect(1548, 1553, 1738, 1586),
         "2组×4根单芯300平方毫米\nXLPE绝缘／铝线铠装／PVC护套（铜芯）\n电缆敷设于电缆沟", 4.5),
        (fitz.Rect(108, 1600, 310, 1633),
         "2组×4根单芯300平方毫米\nXLPE绝缘／铝线铠装／PVC护套（铜芯）\n电缆敷设于电缆沟", 4.5),
    ]:
        insert_textbox(page, rect, text, size=size, color=BLUE)

    # V3.3: dense repeated bays use two-level expression. The complete
    # parameter explanation is placed once in the large same-page legend area;
    # every local source line receives a short semantic role label in the
    # narrow whitespace before the next bay. This avoids covering the next
    # bay's protection-code boxes while still making each parameter readable.
    insert_textbox(
        page,
        fitz.Rect(1555, 126, 2025, 145),
        "CT／避雷器技术参数释义",
        size=8.0,
        color=BLUE,
        bold=True,
    )
    insert_textbox(
        page,
        fitz.Rect(1555, 148, 2025, 250),
        "CT 300/1A CL.PX：电流互感器变比300/1A，PX级\n"
        "Vk≥600V：拐点电压不低于600V\n"
        "Rct≤1.6Ω：二次绕组电阻不大于1.6Ω\n"
        "Im≤40mA at Vk/2：半拐点电压时励磁电流不大于40mA\n"
        "CL.0.2 30VA：0.2准确级，额定负荷30VA（计量绕组）\n"
        "CL.5P20 30VA：5P20保护级，额定负荷30VA（保护绕组）\n"
        "CT 4000/1A CL.PX：母差CT；Rct≤16Ω；Vk/2时Im≤10mA\n"
        "240kV 20kA CL.4：避雷器240kV、20kA、4级",
        size=6.2,
        color=BLUE,
    )

    upper_local = [
        (505, 548, 1005), (770, 823, 1008), (1044, 1073, 1008),
        (1295, 1347, 1008), (1570, 1637, 1008), (1860, 2015, 1014),
    ]
    lower_local = [
        (651, 686, 1177), (908, 1210, 1177),
        (1433, 1485, 1177), (1708, 1842, 1177),
    ]
    for x0, x1, y0 in [*upper_local, *lower_local]:
        for dy, label in (
            (0, "CT／PX参数"),
            (24, "计量级"),
            (41, "保护级"),
            (54, "母差CT"),
            (75, "母差CT"),
        ):
            insert_textbox(
                page,
                fitz.Rect(x0, y0 + dy, x1, y0 + dy + 11),
                label,
                size=4.2,
                color=BLUE,
            )

    # The surge arrester labels immediately below each CT group are also
    # semantic parameters, not literal-only values.
    for target in [
        fitz.Rect(495, 1104, 630, 1119),
        fitz.Rect(760, 1107, 905, 1122),
        fitz.Rect(1035, 1107, 1155, 1122),
        fitz.Rect(1285, 1107, 1429, 1122),
        fitz.Rect(1560, 1107, 1719, 1122),
        fitz.Rect(1850, 1110, 2015, 1125),
        fitz.Rect(641, 1275, 775, 1290),
        fitz.Rect(897, 1275, 1032, 1290),
        fitz.Rect(1423, 1275, 1568, 1290),
        fitz.Rect(1697, 1275, 1842, 1290),
    ]:
        insert_textbox(
            page,
            target,
            "避雷器：240kV，20kA，4级",
            size=4.8,
            color=BLUE,
        )

    legend_rows = [
        ("MAIN 1 INEGRATED LINE DIFFERENTIAL PROTECTION INCOMER", "主进线 1 集成线路差动保护"),
        ("MAIN 2 INEGRATED LINE DIFFERENTIAL PROTECTION INCOMER", "主进线 2 集成线路差动保护"),
        ("DIRECTIONAL OVERCURRENT PROTECTION", "方向过电流保护"),
        ("TRANSFORMER BIAS DIFFERENTIAL PROTECTION", "变压器比率差动保护"),
        ("RESTRICTED EARTH FAULT PROTECTION (HV SIDE)", "高压侧限制性接地故障保护"),
        ("RESTRICTED EARTH FAULT PROTECTION (LV SIDE)", "低压侧限制性接地故障保护"),
        ("STANDBY EARTH FAULT PROTECTION", "备用接地故障保护"),
        ("BAY CONTROLLER UNIT", "间隔控制单元"),
        ("POWER QUALITY METER", "电能质量表"),
        ("AUTOMATIC VOLTAGE REGULATOR", "自动电压调节器"),
        ("CIRCUIT BREAKER MANAGEMENT", "断路器管理"),
        ("DIGITAL POWER METER", "数字电力仪表"),
        ("BUS SEPARATION BACKUP DISTANCE PROTECTION", "母线分隔后备距离保护"),
        ("MAIN 1 BUSBAR LOW IMPEDANCE PROTECTION", "主母线 1 低阻抗保护"),
        ("MAIN 2 BUSBAR LOW IMPEDANCE PROTECTION", "主母线 2 低阻抗保护"),
        ("SYNCHECK RELAY", "同期检查继电器"),
    ]
    legend_codes = [
        "F11L1", "F11L2", "67", "87T", "64REF/HV", "64REF/LV", "64SBEF",
        "F34C", "PQM", "AVR", "50/51", "50N/51N", "21Z", "52CBM", "DPM",
        "21ZBS", "BBLO 1", "BBLO 2", "25SYN",
    ]
    legend_zh = [
        "主进线1集成线路差动保护", "主进线2集成线路差动保护", "方向过电流保护",
        "变压器比率差动保护", "高压侧限制性接地故障保护", "低压侧限制性接地故障保护",
        "备用接地故障保护", "间隔控制单元", "电能质量表", "自动电压调节器",
        "瞬时／延时过电流保护", "瞬时／延时接地故障保护", "后备距离保护",
        "断路器管理", "数字电力仪表", "母线分隔后备距离保护", "主母线1低阻抗保护",
        "主母线2低阻抗保护", "同期检查继电器",
    ]
    for code, zh in zip(legend_codes, legend_zh):
        hits = [
            display_rect(source_page, r)
            for r in source_page.search_for(code)
            if 700 < display_rect(source_page, r).x0 < 1250
            and 90 < display_rect(source_page, r).y0 < 650
        ]
        if not hits:
            continue
        rect = hits[0]
        target = fitz.Rect(1270, rect.y0 - 2, 1545, rect.y1 + 12)
        insert_textbox(
            page,
            target,
            zh,
            size=6.3,
            color=BLUE,
        )

    for en, zh in [
        ("ELECTRICAL SYSTEM", "电气系统"),
        ("CONSUMER LANDING STATION:", "用户接入站："),
        ("275KV MAIN SINGLE LINE DIAGRAM", "275 kV 主单线图"),
    ]:
        for raw_rect in source_page.search_for(en):
            rect = display_rect(source_page, raw_rect)
            display_target = fitz.Rect(
                rect.x0,
                rect.y1 + 1,
                min(rect.x0 + 220, page.rect.x1 - 4),
                rect.y1 + 18,
            )
            insert_textbox(
                page,
                display_target,
                zh,
                size=max(5.5, rect.height * 0.6),
                color=BLACK,
                bold=True,
            )

    # Preserve the original sidebar as the visual substrate. Clear only tightly
    # bounded ordinary-text regions; logo artwork and every rule line remain
    # untouched. Each replacement contains the complete source field plus
    # Chinese, rather than a shortened summary.
    panel_fields = [
        (fitz.Rect(2075, 325, 2378, 340), "LANDOWNER / DEVELOPER / 业主／开发商", 6.5, True),
        (fitz.Rect(2078, 399, 2377, 465),
         "RACKS CENTRAL SDN. BHD. / RACKS CENTRAL 有限公司\n"
         "Co. No.: 202401039267 (1585114-W) / 公司注册号\n"
         "Wisma SP Setia, Unit 05-22 Indah Walk 3 / SP Setia 大厦 Indah Walk 3 座 05-22 单元\n"
         "Jalan Indah 15, Taman Bukit Indah / 英达15路，武吉英达花园\n"
         "81200 Johor Bahru, Johor Darul Ta'zim / 81200 柔佛州新山\n"
         "TEL / 电话：07-230 5995  FAX / 传真：07-230 5959", 4.2, False),
        (fitz.Rect(2075, 470, 2157, 488), "ARCHITECT / 建筑师", 6.2, True),
        (fitz.Rect(2158, 470, 2377, 574),
         "RICHARD W.Z LEE ARCHITECT / 建筑事务所\n"
         "11-01, Medan Aliff Harmoni 1/2 / Aliff Harmoni 1/2 广场11-01室\n"
         "Taman Damansara Aliff / Damansara Aliff 花园\n"
         "81200 Johor Bahru, Johor Darul Takzim / 81200 柔佛州新山\n"
         "TEL / 电话：+603-4161 5698", 4.4, False),
        (fitz.Rect(2075, 579, 2377, 594), "BASE BUILD MEP CONSULTANT / 基础建设机电顾问", 5.8, True),
        (fitz.Rect(2161, 611, 2377, 639),
         "PSB ASSOCIATES SDN. BHD. / PSB 联合顾问有限公司\n"
         "Co. No.: 201201037893 (1022375-D) / 公司注册号：201201037893（1022375-D）",
         4.2, True),
        (fitz.Rect(2076, 640, 2377, 704),
         "88-01, Jalan Setia Tropika 1/7 / Setia Tropika 1/7路88-01号\n"
         "Setia Tropika, 81200 Johor Bahru / Setia Tropika 花园，81200 柔佛州新山\n"
         "Johor Darul Ta'zim / 柔佛州\n"
         "TEL / 电话：(+607) 230 9889\nFAX / 传真：(+607) 232 8799", 4.2, False),
        (fitz.Rect(2075, 710, 2377, 725), "C&S CONSULTANT / 土木与结构顾问", 6.0, True),
        (fitz.Rect(2076, 768, 2377, 831),
         "PERUNDING TLK SDN. BHD. (606257-W) / TLK 顾问有限公司\n"
         "34-01, Jalan Ros Merah 2/7 / Ros Merah 2/7路34-01号\n"
         "Taman Johor Jaya, 81100 Johor Bahru / Johor Jaya 花园，81100 柔佛州新山\n"
         "Johor Darul Ta'zim / 柔佛州\n"
         "TEL / 电话：(+607) 355 7675  FAX / 传真：(+607) 361 0076", 4.0, False),
        (fitz.Rect(2075, 835, 2377, 850), "DATA CENTRE MEP CONSULTANT / 数据中心机电顾问", 5.6, True),
        (fitz.Rect(2162, 879, 2377, 957),
         "ALPHA CONSULTING ENGINEERS PTE LTD / Alpha 咨询工程师有限公司\n"
         "2, BUKIT MERAH CENTRAL #16-01 / 红山中心2号16-01室\n"
         "SINGAPORE 159835 / 新加坡159835\n"
         "TEL / 电话：(65) 6276 2228\nE-MAIL / 电邮：ace@alpha.com.sg\n"
         "WEBSITE / 网站：www.alpha.com.sg", 3.9, False),
        (fitz.Rect(2075, 963, 2377, 978), "MAIN CONTRACTOR / 总承包商", 6.0, True),
        (fitz.Rect(2132, 980, 2377, 1019),
         "HUASHI (MALAYSIA) SDN. BHD. / 华西（马来西亚）有限公司", 4.2, True),
        (fitz.Rect(2098, 1019, 2377, 1068),
         "Wisma Zelan, Level 21 / Zelan 大厦21层\n"
         "Jalan Tasik Permaisuri 2, Bandar Tun Razak / Tasik Permaisuri 2路，敦拉萨镇\n"
         "56000 Kuala Lumpur, Wilayah Persekutuan, Malaysia / 56000 吉隆坡联邦直辖区\n"
         "TEL / 电话：+603-9174 5568", 4.0, False),
        (fitz.Rect(2075, 1075, 2377, 1090), "MAIN CONTRACTOR'S MEP CONSULTANT / 总包机电顾问", 5.5, True),
        (fitz.Rect(2124, 1091, 2377, 1136),
         "GREATIANS CONSULTING SDN. BHD. (1043345-H) / GREATIANS 咨询有限公司\n"
         "Consulting Engineers / 咨询工程师\nMechanical & Electrical / 机械与电气\n"
         , 3.7, False),
        (fitz.Rect(2076, 1135, 2377, 1209),
         "A-03A-5, Block A Setiawalk / Setiawalk A座A-03A-5\n"
         "Persiaran Wawasan, Pusat Bandar Puchong / Wawasan 大道，蒲种市中心\n"
         "47160 Selangor Darul Ehsan / 47160 雪兰莪州\n"
         "TEL / 电话：+603-5879 3257 / +607-562 0395\n"
         "FAX / 传真：+603-5886 2613 / +07-562 6386\n"
         "WEBSITE / 网站：www.greatian.com  E-MAIL / 电邮：gc@greatian.com", 3.7, False),
        (fitz.Rect(2076, 1215, 2378, 1387),
         "PROJECT TITLE / 项目名称\nPROJECT RACKS CENTRAL / RACKS CENTRAL 项目\n"
         "PROPOSED DEVELOPMENT OF PROJECT (DATA CENTRE) WHICH CONSISTS OF:\n"
         "拟建数据中心项目，包括：\n"
         "i) 2-STOREY 275kV / 11kV CONSUMER LANDING STATION BUILDING / 两层275kV／11kV用户接入站建筑\n"
         "ii) A WATER TREATMENT PLANT / 水处理厂\n"
         "iii) A GUARDHOUSE / 警卫室\n"
         "iv) A REFUSE CHAMBER WITH A RECYCLING AREA / 带回收区的垃圾房\n"
         "LOCATED ON PTD 238149, ISKANDAR HALAL PARK, INDUSTRIAL ESTATE,\n"
         "MUKIM PLENTONG, JOHOR BAHRU DISTRICT, JOHOR DARUL TA'ZIM /\n"
         "位于 PTD 238149，依斯干达清真产业园工业区，柔佛州新山县避兰东区\n"
         "FOR RACK CENTRAL SDN. BHD. / 业主：RACK CENTRAL 有限公司", 3.8, True),
        (fitz.Rect(2076, 1384, 2378, 1437),
         "SERVICES TITLE / 专业名称\nELECTRICAL SYSTEM / 电气系统", 6.0, True),
        (fitz.Rect(2076, 1436, 2378, 1580),
         "DRAWING TITLE / 图纸名称\nCONSUMER LANDING STATION / 用户接入站\n"
         "275kV MAIN SINGLE LINE DIAGRAM / 275kV 主单线图", 5.8, True),
    ]
    for rect, text, size, bold in panel_fields:
        # The source sidebar's true right rule is x=2356. The area from there
        # to the page edge is intentional margin, not a missing border.
        rect.x1 = min(rect.x1, 2354.5)
        clear = fitz.Rect(rect.x0 + 0.5, rect.y0 + 0.5, rect.x1 - 0.5, rect.y1 - 0.5)
        page.draw_rect(clear, color=None, fill=(1, 1, 1), overlay=True)
        insert_textbox(page, clear, text, size=size, color=BLACK, bold=bold)
    # These two source headings cross their horizontal cell rules. Their tight
    # masks therefore touch the rules; restore the original rules exactly.
    page.draw_rect(
        fitz.Rect(2076.5, 1384.5, 2354.5, 1435.5),
        color=None,
        fill=(1, 1, 1),
        overlay=True,
    )
    for y in (469, 578, 709, 834, 960, 1072, 1212, 1389, 1436):
        page.draw_line((2072, y), (2356, y), color=BLACK, width=0.65, overlay=True)
    page.draw_line((2072, 323), (2072, 1580), color=BLACK, width=0.65, overlay=True)
    page.draw_line((2356, 323), (2356, 1580), color=BLACK, width=0.65, overlay=True)
    page.draw_rect(
        fitz.Rect(2124, 1090, 2354.5, 1137),
        color=None,
        fill=(1, 1, 1),
        overlay=True,
    )
    page.draw_rect(
        fitz.Rect(2075.5, 1073, 2354.5, 1090.5),
        color=None,
        fill=(1, 1, 1),
        overlay=True,
    )
    page.draw_line((2072, 1072), (2356, 1072), color=BLACK, width=0.65, overlay=True)
    insert_textbox(
        page,
        fitz.Rect(2075.5, 1076, 2354.5, 1090),
        "MAIN CONTRACTOR'S MEP CONSULTANT / 总包机电顾问",
        size=5.5,
        color=BLACK,
        bold=True,
    )
    insert_textbox(
        page,
        fitz.Rect(2124.5, 1091.5, 2354, 1135.5),
        "GREATIANS CONSULTING SDN. BHD. (1043345-H) / GREATIANS 咨询有限公司\n"
        "Consulting Engineers / 咨询工程师\n"
        "Mechanical & Electrical / 机械与电气",
        size=3.7,
        color=BLACK,
    )
    insert_textbox(
        page,
        fitz.Rect(2076.5, 1392, 2354.5, 1435),
        "SERVICES TITLE / 专业名称\nELECTRICAL SYSTEM / 电气系统",
        size=6.0,
        color=BLACK,
        bold=True,
    )
    # Bottom metadata remains a text-only title block. Reflow the text inside
    # each cell while preserving every original grid line and identifier.
    metadata_fields = [
        (fitz.Rect(2075, 1562, 2212, 1584), "DRAWN / 绘制：AISYAH", 5.0),
        (fitz.Rect(2075, 1586, 2212, 1598), "DESIGNED / 设计：BRYAN", 4.8),
        (fitz.Rect(2075, 1600, 2212, 1612), "CHECKED / 校核：Y.P TAN", 4.8),
        (fitz.Rect(2216, 1562, 2283, 1612), "SCALE / 比例\nN.T.S.", 5.2),
        (fitz.Rect(2287, 1562, 2354, 1612), "DATE / 日期\nJun 2026 / 2026年6月", 4.8),
        (fitz.Rect(2075, 1615, 2283, 1654), "DRAWING NO. / 图纸编号\n1310-CN-ELEC-SCH-C001", 5.5),
        (fitz.Rect(2287, 1615, 2354, 1654), "REVISION / 修订\n00", 5.2),
    ]
    for rect, text, size in metadata_fields:
        page.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)
        insert_textbox(page, rect, text, size=size, color=BLACK, bold=True)
    for y in (1585, 1599, 1613, 1655):
        page.draw_line((2072, y), (2356, y), color=BLACK, width=0.65, overlay=True)
    for x, y0, y1 in (
        (2072, 1560, 1655), (2214, 1560, 1655), (2285, 1560, 1655),
        (2356, 1560, 1655),
    ):
        page.draw_line((x, y0), (x, y1), color=BLACK, width=0.65, overlay=True)

    out = OUT / "03_ELECTRICAL_275KV_SLD_V3_3_TEST.pdf"
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    source_doc.close()
    return out


def render(pdf: Path) -> Path:
    doc = fitz.open(pdf)
    page = doc[0]
    scale = min(1.55, 2200 / max(page.rect.width, page.rect.height))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    png = pdf.with_suffix(".png")
    pix.save(png)
    doc.close()
    return png


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    outputs = [build_corner_bead(), build_door_schedule(), build_sld()]
    for pdf in outputs:
        print(pdf)
        print(render(pdf))


if __name__ == "__main__":
    main()
