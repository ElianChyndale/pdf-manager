# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

from pathlib import Path

import fitz


ROOT = Path(r"D:\AmyProjects\business\pdf-manager")
SOURCE = (
    ROOT
    / "tmp"
    / "pdfs"
    / "engineering-drawing-v3-sol-light"
    / "full-page-layout-fidelity"
    / "core-03"
    / "ROOF_DETAIL_FULL_PAGE_V16_MICROTEXT_REVIEWED.pdf"
)
OUTPUT = (
    ROOT
    / "tmp"
    / "pdfs"
    / "engineering-drawing-v3-3-cross-domain-review"
    / "03_屋面平面与微文字_V3.3.pdf"
)
FONT = r"C:\Windows\Fonts\simhei.ttf"
BLUE = (0.05, 0.22, 0.68)
RED = (1, 0, 0)


def insert_fit(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    size: float,
    color=BLUE,
    bold: bool = False,
    align: int = 0,
) -> None:
    fontname = "simhei-v33-bold" if bold else "simhei-v33"
    page.insert_font(fontname=fontname, fontfile=FONT)
    trial = size
    while trial >= 2.4:
        shape = page.new_shape()
        spare = shape.insert_textbox(
            rect,
            text,
            fontname=fontname,
            fontsize=trial,
            color=color,
            lineheight=1.08,
            align=align,
        )
        if spare >= 0:
            shape.commit(overlay=True)
            return
        trial -= 0.2
    raise RuntimeError(f"cannot fit text in {tuple(rect)}")


def build() -> Path:
    doc = fitz.open(SOURCE)
    page = doc[0]

    # The lower half of the original GENERAL NOTES frame is intentionally
    # blank. Use it for readable Chinese companions while retaining the source
    # English text and every frame line.
    notes = [
        (
            fitz.Rect(41, 618, 258, 697),
            "屋面系统（ROOF SYSTEM）\n"
            "采用按长度定制的 KLIPLOK OPTIMA 0.48 mm BMT（0.54 mm TCT）"
            "AZ200 G550 COLORBOND ULTRA 钢板，具 THERMATECH 与 CLEAN "
            "TECHNOLOGY 涂层；暗扣固定于 KL98 夹具，肋高43 mm、有效覆盖宽"
            "980 mm。适用于2°及25°坡度，须符合厂家技术要求并经建筑师批准；"
            "抗风揭性能须由 NATA 认可实验室检测。",
        ),
        (
            fitz.Rect(261, 618, 468, 697),
            "屋面结构（ROOF STRUCTURE）\n"
            "轻型屋架按2°及25°坡度设置，构造依工程师详图；铺设1层50 mm厚"
            "ROCKWOOL Cool and Comfort RL920 岩棉，密度40 kg/m³；另设1层"
            "BLM V-FOIL ENVIRO-TUFF 阻燃编织反射箔，双面镀铝膜与高密度"
            "聚乙烯编织基材复合，防火等级Class 0。",
        ),
        (
            fitz.Rect(472, 618, 814, 697),
            "钢筋混凝土平屋面防水系统（WATERPROOFING SYSTEM）\n"
            "采用 PURTOP 1000 纯聚脲弹性防水系统：基层先涂底漆并进行撒布"
            "石英砂3%的刮涂处理，再施工最小厚度2.0 mm的PURTOP 1000喷涂"
            "聚脲。使用带流量及温度控制、自清洁功能的专用双组分喷枪施工。"
            "系统应适用于长期浸水环境，具耐化学性、抗裂桥接、耐水解及抗热冲击性能。",
        ),
    ]
    for rect, text in notes:
        insert_fit(page, rect, text, size=5.8, color=BLUE, bold=False)

    # Construction-status stamp is a non-drawing information field.
    page.draw_rect(
        fitz.Rect(916, 673, 1145, 697),
        color=None,
        fill=(1, 1, 1),
        overlay=True,
    )
    insert_fit(
        page,
        fitz.Rect(920, 675, 1142, 695),
        "CONSTRUCTION DRAWING / 施工图",
        size=11.0,
        color=RED,
        bold=True,
        align=1,
    )

    if OUTPUT.exists():
        OUTPUT.unlink()
    doc.save(OUTPUT, garbage=4, deflate=True)
    doc.close()
    return OUTPUT


if __name__ == "__main__":
    print(build())
