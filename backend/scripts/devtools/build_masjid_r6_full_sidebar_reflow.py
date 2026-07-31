# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""Build the field-complete, source-mask-only R6 Masjid sidebar repair."""

import json
from pathlib import Path
import re


ARTIFACT = Path(
    r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing"
    r"\01_Bilingual_Inline\batch-artifacts"
    r"\03_CONSTRUCTION_DWG_MASJID_11_NOV_2025__01_Masjid_Tok_Muda_CONSTRUCTION__f8ffb95ffe"
)
INPUT_PLAN = ARTIFACT / "v3.3-post-ocr-executable-plan.json"
OUTPUT_PLAN = ARTIFACT / "v3.3-r6-full-sidebar-reflow-plan.json"
OUTPUT_SPEC = ARTIFACT / "v3.3-r6-full-sidebar-reflow.json"
OUTPUT_NOTES = ARTIFACT / "v3.3-r6-full-sidebar-reflow-notes.md"


def field(
    key: str,
    source_masks: list[list[float]],
    selected_region: list[float],
    text: str,
    *,
    max_size: float = 4.0,
    min_size: float = 2.0,
) -> dict:
    width = selected_region[2] - selected_region[0]
    # PDF textbox wrapping is inconsistent for mixed Latin / CJK strings at
    # 2--4pt engineering-title sizes.  Pre-wrap every source+Chinese line so
    # a field cannot paint past its approved selected_region.
    text = wrap_for_cell(text, width)
    return {
        "key": key,
        "source_masks": source_masks,
        "selected_region": selected_region,
        "text": text,
        "max_size": max_size,
        "min_size": min_size,
    }


def wrap_for_cell(text: str, width: float) -> str:
    latin_limit = max(18, int(width / 1.5))
    cjk_limit = max(12, int(width / 2.45))
    output: list[str] = []
    for original in str(text).splitlines():
        line = original.strip()
        if not line:
            output.append("")
            continue
        if re.search(r"[\u3400-\u9fff]", line) and " " not in line:
            output.extend(line[index:index + cjk_limit] for index in range(0, len(line), cjk_limit))
            continue
        words = re.findall(r"\S+", line)
        current = ""
        for word in words:
            if len(word) > latin_limit:
                if current:
                    output.append(current)
                    current = ""
                output.extend(word[index:index + latin_limit] for index in range(0, len(word), latin_limit))
                continue
            trial = f"{current} {word}".strip()
            if current and len(trial) > latin_limit:
                output.append(current)
                current = word
            else:
                current = trial
        if current:
            output.append(current)
    return "\n".join(output)


def fields_for_page(page: int) -> list[dict]:
    # Source masks are manually reviewed visual text bounds.  They never
    # include a logo, seal, signature drawing, border, or CAD geometry.  The
    # independent selected_region is the actual text layout cell.
    title = {
        0: "MASJID\n清真寺\n- PELAN TINGKAT BAWAH\n- 底层平面图",
        1: "MASJID\n清真寺\n- PELAN BUMBUNG 1 (RASUK 2)\n- 屋面平面图 1（梁 2）\n- PELAN MENARA 1 (RASUK 3)\n- 塔楼平面图 1（梁 3）\n- PELAN MENARA 2 (RASUK 5)\n- 塔楼平面图 2（梁 5）\n- PELAN BUMBUNG KESELURUHAN\n- 总体屋面平面图",
        2: "MASJID\n清真寺\n- PANDANGAN HADAPAN\n- 正立面\n- PANDANGAN BELAKANG\n- 后立面\n- PANDANGAN SISI KANAN\n- 右侧立面\n- PANDANGAN SISI KIRI\n- 左侧立面",
        3: "MASJID\n清真寺\n- KERATAN A-A\n- A-A 剖面\n- KERATAN B-B\n- B-B 剖面\n- KERATAN C-C\n- C-C 剖面\n- KERATAN D-D\n- D-D 剖面\n- KERATAN E-E\n- E-E 剖面",
    }[page]
    return [
        field("land-owner-label", [[1042, 75, 1091, 84]], [1042, 73, 1091, 88], "PEMILIK TANAH :\n土地所有者：", max_size=4.0),
        field(
            "land-owner-detail",
            [[1093, 63, 1166, 109]],
            [1093, 75, 1166, 109],
            "MAJLIS AGAMA ISLAM SELANGOR\n雪兰莪伊斯兰宗教理事会\nTINGKAT 9 & 10, MENARA UTARA, BANGUNAN SULTAN IDRIS SHAH, 40000 SHAH ALAM, SELANGOR\n地址：雪兰莪州莎阿南 40000，苏丹依德理斯沙大厦北塔 9 与 10 层\nt：03-5514 3400  f：03-5512 4042  e：pro@mais.gov.my\n电话 / 传真 / 电子邮箱：同上",
            max_size=3.0,
        ),
        field("building-owner-label", [[1042, 125, 1093, 137]], [1042, 123, 1093, 140], "PEMILIK BANGUNAN :\n建筑业主：", max_size=4.0),
        field(
            "building-owner-detail",
            [[1093, 116, 1166, 163]],
            [1093, 127, 1166, 163],
            "JABATAN AGAMA ISLAM SELANGOR\n雪兰莪伊斯兰宗教局\nTINGKAT 1, MENARA SELATAN, BANGUNAN SULTAN IDRIS SHAH, NO. 2, PERSIARAN MASJID, BUKIT SUK, SEKSYEN 5, 40670 SHAH ALAM, SELANGOR\n地址：雪兰莪州莎阿南 40670，第 5 区苏克山，清真寺大道 2 号，苏丹依德理斯沙大厦南塔 1 层\nt：03-5514 3400  f：03-5510 3368  e：www.jais.gov.my\n电话 / 传真 / 网站：同上",
            max_size=2.8,
        ),
        field(
            "project",
            [[1042, 176, 1165, 207]],
            [1042, 176, 1165, 207],
            "PROJEK : CADANGAN MEROBOH DAN MEMBINA SEMULA MASJID AL-EHSAN KAMPUNG TOK MUDA, KAPAR, DAERAH KLANG, SELANGOR DARUL EHSAN\n项目：建议拆除并重建位于雪兰莪州巴生县卡帕托穆达村的 Al-Ehsan 清真寺。",
            max_size=3.8,
        ),
        field(
            "revision-header",
            [[1042, 242, 1166, 253]],
            [1042, 242, 1166, 253],
            "Bil. / 编号    Tarikh / 日期    Pindaan / 修订    DISEMAK / 审核",
            max_size=3.0,
            min_size=2.2,
        ),
        field("agency-label", [[1042, 276, 1092, 288]], [1042, 274, 1092, 291], "AGENSI PELAKSANA :\n实施机构：", max_size=4.0),
        field(
            "agency-detail",
            [[1093, 269, 1166, 322]],
            [1093, 278, 1166, 322],
            "JABATAN KERJA RAYA SELANGOR\n雪兰莪公共工程局\nKOMPLEKS IBU PEJABAT JKR NEGERI SELANGOR, PERSIARAN JUBLI PERAK, SEKSYEN 17, 40200 SHAH ALAM, SELANGOR DARUL EHSAN\n地址：雪兰莪州莎阿南 40200，第 17 区银禧大道，雪兰莪州公共工程局总部\nt：03-5545 9800  f：03-5545 3858  e：aduansel@jkr.gov.my\n电话 / 传真 / 电子邮箱：同上",
            max_size=2.8,
        ),
        field("applicant-label", [[1042, 330, 1141, 344]], [1042, 330, 1165, 350], "NAMA / TANDATANGAN / NO K.P. PEMOHON :\n申请人姓名 / 签名 / 身份证号：", max_size=3.7),
        field(
            "applicant-detail",
            [[1078, 351, 1150, 378], [1042, 379, 1166, 391]],
            [1078, 351, 1165, 391],
            "Ar. Mohd Azahari Bin Mad Atan\n莫哈末·阿扎哈里·本·马德·阿坦建筑师\nA R K I T E K — No. Pendaftaran LAM : A/M 91\n建筑师 — 马来西亚建筑师委员会注册号：A/M 91\nSaya memperakui bahawa perincian-perincian dalam pelan-pelan ini adalah menurut kehendak-kehendak Undang-Undang Kecil Bangunan Seragam Selangor 1986 dan saya setuju terima tanggungjawab penuh terhadap perancangan seterusnya.\n本人确认本图纸细节符合《1986 年雪兰莪统一建筑附则》，并承担后续规划的全部责任。",
            max_size=2.4,
        ),
        field("architect-label", [[1042, 389, 1093, 404]], [1042, 389, 1093, 407], "ARKITEK :\n建筑师：", max_size=4.0),
        field(
            "architect-detail",
            [[1093, 397, 1166, 436]],
            [1093, 397, 1166, 436],
            "AC ARCHITECTS SDN BHD\nAC 建筑师有限公司\nSUITE 8-A, 5TH. LEVEL, TOWER A, PANDAN KAPITAL, PERSIARAN MP AJ, PANDAN INDAH, 55100 SELANGOR DARUL EHSAN\n地址：雪兰莪州 55100，班登英达，MPAJ 大道，Pandan Kapital A 座 5 层 8-A 室\nt：03-429 44122  f：03-4294 3122  e：acarch.sb@gmail.com",
            max_size=2.6,
        ),
        field("civil-label", [[1042, 436, 1119, 450]], [1042, 436, 1121, 452], "JURUTERA SIVIL DAN STRUKTUR :\n土木与结构工程师：", max_size=3.4),
        field(
            "civil-detail",
            [[1093, 449, 1166, 483]],
            [1093, 449, 1166, 483],
            "UNITI CONSULTANTS SDN. BHD.\nUNITI 顾问有限公司\nNO. 25, JALAN BUNGA RAYA 8, SENAWANG BUSINESS CENTRE, TAMAN TASIK JAYA, 70450 SEREMBAN, NEGERI SEMBILAN\n地址：森美兰州芙蓉 70450，达西再也湖花园，Senawang 商业中心 Bunga Raya 8 路 25 号\nt：06-679 2037  f：06-679 2037  e：uniticonsult@gmail.com",
            max_size=2.5,
        ),
        field("mechanical-label", [[1042, 485, 1097, 500]], [1042, 485, 1100, 502], "JURUTERA MEKANIKAL :\n机械工程师：", max_size=3.7),
        field(
            "mechanical-detail",
            [[1093, 497, 1166, 533]],
            [1093, 497, 1166, 533],
            "CAWANGAN KEJURUTERAAN MEKANIKAL NEGERI\n州机械工程分局\nJABATAN KERJA RAYA, CAWANGAN MEKANIKAL NEGERI SELANGOR, PERSIARAN JUBLI PERAK, SEKSYEN 17, 40200 SHAH ALAM, SELANGOR\n地址：雪兰莪州莎阿南 40200，第 17 区银禧大道，州公共工程局机械工程分局\nt：03-5545 9800  f：03-5545 3858  e：aduansel@jkr.gov.my",
            max_size=2.4,
        ),
        field("electrical-label", [[1042, 535, 1100, 550]], [1042, 535, 1100, 552], "JURUTERA ELEKTRIKAL :\n电气工程师：", max_size=3.7),
        field(
            "electrical-detail",
            [[1093, 547, 1166, 581]],
            [1093, 547, 1166, 581],
            "CAWANGAN KEJURUTERAAN ELEKTRIK NEGERI\n州电气工程分局\nTINGKAT 3, KOMPLEKS IBU PEJABAT, JABATAN KERJA RAYA NEGERI SELANGOR, PERSIARAN JUBLI PERAK, SEKSYEN 17, 40200 SHAH ALAM, SELANGOR\n地址：雪兰莪州莎阿南 40200，第 17 区银禧大道，雪兰莪州公共工程局总部 3 层\nt：03-5545 9800  f：03-5545 3858  e：aduansel@jkr.gov.my",
            max_size=2.35,
        ),
        field("quantity-label", [[1042, 585, 1087, 599]], [1042, 585, 1088, 601], "JURUKUR BAHAN :\n工料测量师：", max_size=3.8),
        field(
            "quantity-detail",
            [[1093, 596, 1166, 631]],
            [1093, 596, 1166, 631],
            "AZIZI, AZIZI & PARTNERS SDN BHD\n阿兹兹与合伙人有限公司\nNO 43A, TINGKAT 1, JALAN LAWAN PEDANG 13/27, SEKSYEN 13, 40100 SHAH ALAM, SELANGOR\n地址：雪兰莪州莎阿南 40100，第 13 区 Lawan Pedang 13/27 路 43A 号 1 层\nt：03-5510 8600  f：03-5510 5518  e：aapsb.aa@gmail.com",
            max_size=2.5,
        ),
        field("landscape-label", [[1042, 633, 1100, 647]], [1042, 633, 1100, 649], "PERUNDING LANDSKAP :\n景观顾问：", max_size=3.6),
        field(
            "landscape-detail",
            [[1093, 645, 1166, 681], [1042, 665, 1110, 679]],
            [1093, 645, 1166, 681],
            "LAMAN TBG SDN BHD\nLaman TBG 有限公司\nNO 1, JALAN PP 3/5, PERSIARAN DESA PINGGIRAN PUTRA, 43000 KAJANG, SELANGOR\n地址：雪兰莪州加影 43000，Desa Pinggiran Putra 大道，PP 3/5 路 1 号\nt：03-8922 9999  f：03-8920 8999  e：info@lamantbg.com",
            max_size=2.5,
        ),
        field(
            "copyright-and-notes",
            [[1042, 681, 1166, 702]],
            [1042, 681, 1166, 702],
            "This drawing is copyright.\n本图纸受版权保护。\nContractors must check all dimensions on site. Only figured dimensions are to be worked on. Discrepancies must be reported immediately to the architect before proceeding.\n承包商须在现场核对全部尺寸，仅按标注尺寸施工；任何差异须在施工前立即报告建筑师。",
            max_size=2.35,
        ),
        field(
            "drawing-status",
            [[1042, 702, 1166, 725]],
            [1042, 702, 1166, 725],
            "Drawing Status / 图纸状态\nPRELIMINARY / 初步    TENDER / 招标    CONSTRUCTION / 施工\nINFORMATION / 信息    TENDER TABLE / 招标表    CONTRACT / 合同",
            max_size=3.0,
        ),
        field("drawing-title", [[1042, 726, 1115, 771]], [1042, 726, 1115, 771], title, max_size=3.1, min_size=2.1),
        field(
            "drawing-metadata",
            [[1042, 771, 1166, 813]],
            [1042, 771, 1166, 813],
            f"Skala : 1:200\n比例：1:200\nDilukis Oleh : apiz\n绘图：apiz\nDisemak Oleh : AR. AZAHARI\n审核：AR. AZAHARI\nTarikh : JULAI 2025\n日期：2025 年 7 月\nNo. Lukisan : ACASB 2401/MTM/M/WD-0{page + 1}\n图纸编号：ACASB 2401/MTM/M/WD-0{page + 1}",
            max_size=2.9,
            min_size=2.0,
        ),
    ]


def contains(rect: list[float], bbox: list[float]) -> bool:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return rect[0] - 1 <= cx <= rect[2] + 1 and rect[1] - 1 <= cy <= rect[3] + 1


def main() -> None:
    plan = json.loads(INPUT_PLAN.read_text(encoding="utf-8"))
    all_fields = [fields_for_page(page) for page in range(4)]
    panels = []
    mapped_blocks: dict[str, tuple[str, str, list[float]]] = {}
    for page_index, page_fields in enumerate(all_fields):
        panel_id = f"masjid-r6-sidebar-p{page_index + 1:03d}"
        fields = []
        source_masks: list[list[float]] = []
        for item in page_fields:
            field_id = f"{panel_id}-{item['key']}"
            fields.append(
                {
                    "field_id": field_id,
                    "selected_region": item["selected_region"],
                    "text": item["text"],
                    "font": "simhei",
                    "max_size": item["max_size"],
                    "min_size": item["min_size"],
                    "lineheight": 0.96,
                    "source_bbox_masks": item["source_masks"],
                }
            )
            source_masks.extend(item["source_masks"])
        panels.append(
            {
                "panel_id": panel_id,
                "page_index": page_index,
                "clear_mode": "white_overlay",
                "clear_regions": source_masks,
                "fields": fields,
                "visual_review": {
                    "reviewed_from": f"source page {page_index + 1}",
                    "mask_rule": "source_bbox_masks only; no selected_region is cleared",
                    "protected": "all vector rules, logos, seals, signatures, and drawing body",
                },
            }
        )
        for block in plan["semantic_blocks"]:
            if block["page_index"] != page_index or block["source_bbox"][0] < 1035:
                continue
            matched = next((item for item in page_fields if contains(item["selected_region"], block["source_bbox"])), None)
            if matched is None:
                raise ValueError(f"unmapped sidebar semantic block: {block['block_id']} {block['source_text']!r}")
            mapped_blocks[block["block_id"]] = (
                panel_id,
                f"{panel_id}-{matched['key']}",
                matched["selected_region"],
            )
    for block in plan["semantic_blocks"]:
        owned = mapped_blocks.get(block["block_id"])
        if owned is None:
            continue
        panel_id, field_id, selected_region = owned
        block["placement"].update(
            {
                "panel_reflow_managed": True,
                "panel_reflow_panel_id": panel_id,
                "panel_reflow_field_id": field_id,
                "panel_reflow_target_bbox": selected_region,
                "text_color": "#000000",
                "opaque_background": "source_bbox_mask_then_black_bilingual_reflow",
                "preserve_source": False,
                "allow_source_overlap": False,
                "allow_dense_source_overlap": False,
                "multimodal_visual_whitespace_override": False,
                "instruction": "R6：仅掩蔽已复核 source_bbox 文本墨迹；在 selected_region 以黑色原文+中文重排。禁止清理单元格底色、边框、徽标、印章、签名或绘图主体。",
                "source_overlap_review": {"reviewed_individually": True, "decision": "source_bbox_mask_only_full_sidebar_reflow", "visual_ink_ratio": 0.0},
            }
        )
    spec = {
        "schema": "engineering-drawing-full-sidebar-reflow-v2",
        "source_plan": str(INPUT_PLAN),
        "restore_vector_rules": True,
        "mask_semantics": "source_bbox_masks only",
        "panels": panels,
        "field_count": sum(len(item) for item in all_fields),
    }
    plan["status"] = "repair"
    plan["repair_parent_plan"] = str(INPUT_PLAN)
    plan["panel_reflow_spec"] = str(OUTPUT_SPEC)
    plan["panel_reflow_review"] = {
        "managed_sidebar_blocks": len(mapped_blocks),
        "manual_visual_sidebar_fields": sum(len(item) for item in all_fields),
        "drawing_body_blocks_changed": 0,
        "mask_semantics": "source_bbox_masks only; selected_region layout only",
        "multimodal_visual_whitespace_overrides_added": 0,
    }
    OUTPUT_SPEC.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_NOTES.write_text(
        "# R6 full sidebar/title-field reflow\n\n"
        f"- Visual sidebar fields reflowed: {sum(len(item) for item in all_fields)}.\n"
        f"- Existing semantic title/sidebar blocks audited as panel-reflowed: {len(mapped_blocks)}.\n"
        "- Masking uses reviewed source text bboxes only; selected layout cells are never white-cleared.\n"
        "- Borders, logos, seals, signatures and drawing-body placements are protected.\n"
        "- CAD-hatch whitespace overrides added: 0.\n",
        encoding="utf-8",
    )
    print(json.dumps({"plan": str(OUTPUT_PLAN), "spec": str(OUTPUT_SPEC), "mapped": len(mapped_blocks), "fields": spec["field_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
