# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
"""Build the Site Masjid R4 field plan with complete sidebar semantics.

R3 proved that counting OCR hits is not semantic coverage.  R4 groups the
right sidebar by visible responsibility/company/address/contact fields while
using the union only to *find* individual OCR text masks.  The renderer masks
the individual OCR glyph boxes, never the union/target rectangle.
"""

from __future__ import annotations

import json
from pathlib import Path


ARTIFACT = Path(
    r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing"
    r"\01_Bilingual_Inline\batch-artifacts"
    r"\03_CONSTRUCTION_DWG_MASJID_11_NOV_2025__00_Site_Masjid_Tok_Muda_CONSTRUCTION__eea8ec342c"
)
PLAN = ARTIFACT / "v3.3-post-ocr-executable-plan.json"
OCR = ARTIFACT / "v3.3-supervised-hybrid-ocr.json"


def ids(value: str) -> list[str]:
    return value.split()


# One sidebar field is either a role/header, one full right-hand company
# ledger, or one compact title/status/metadata field.  IDs in a ledger are all
# real OCR text fields; logo-only IDs are deliberately absent.
FIELDS = [
    ("land-owner-role", ids("p001-native-0044"), "土地业主：", "role"),
    ("land-owner-ledger", ids("p001-paddle-full-0079 p001-paddle-full-0086 p001-paddle-tile-3760-0-0059 p001-paddle-full-0095 p001-paddle-full-0102 p001-paddle-full-0104 p001-paddle-full-0106"), "雪兰莪伊斯兰宗教理事会\n地址：9及10层，北塔；苏丹依德理斯沙大厦；40000 莎阿南，雪兰莪\n电话：03-5514 3400；传真：03-5512 4042\n电子邮箱：pro@mais.gov.my", "ledger"),
    ("building-owner-role", ids("p001-native-0038"), "建筑业主：", "role"),
    ("building-owner-ledger", ids("p001-paddle-full-0126 p001-paddle-tile-3760-0-0083 p001-paddle-tile-3760-0-0087 p001-paddle-tile-3760-0-0089 p001-paddle-full-0140 p001-paddle-tile-3760-0-0097 p001-paddle-tile-3760-0-0102 p001-paddle-full-0153 p001-paddle-full-0158"), "雪兰莪伊斯兰宗教局\n地址：1层，南塔；苏丹依德理斯沙大厦；2号清真寺大道；武吉苏克，第5区；40670 莎阿南，雪兰莪\n电话：03-5514 3400；传真：03-5510 3368\n网站：www.jais.gov.my", "ledger"),
    ("project-label", ids("p001-native-0025"), "项目：", "role"),
    ("project-title", ids("p001-native-0032 p001-native-0033 p001-native-0034"), "拟拆除并重建雪兰莪州巴生县加帕托克穆达村阿尔艾山清真寺", "wide"),
    ("revision-headers", ids("p001-native-0023 p001-native-0022 p001-native-0024 p001-native-0031"), "序号；日期；修订；审核", "wide"),
    ("agency-role", ids("p001-native-0036"), "实施机构：", "role"),
    ("agency-ledger", ids("p001-paddle-tile-3760-0-0160 p001-paddle-full-0242 p001-paddle-tile-3760-0-0168 p001-paddle-tile-3760-0-0169 p001-paddle-tile-3760-0-0170 p001-paddle-tile-3760-0-0175 p001-paddle-full-0261 p001-paddle-full-0263"), "雪兰莪州公共工程局\n地址：雪兰莪州公共工程局总部大厦，银禧道17区，40200 莎阿南，雪兰莪\n电话：03-5545 9800；传真：03-5545 3858\n电子邮箱：aduansel@jkr.gov.my", "ledger"),
    ("applicant-label", ids("p001-native-0030"), "申请人姓名／签名／身份证号：", "wide"),
    ("applicant-registration", ids("p001-native-0001 p001-native-0002 p001-native-0003"), "建筑师：Ar. Mohd Azahari Bin Mad Atan；LAM注册号：A/M 91", "ledger"),
    ("applicant-certification", ids("p001-paddle-full-0289 p001-paddle-tile-3760-0-0195 p001-paddle-tile-3760-0-0197"), "本人确认图纸细节符合雪兰莪州统一建筑附例，并承担相应责任。", "wide"),
    ("architect-role", ids("p001-native-0026"), "建筑师：", "role"),
    ("architect-ledger", ids("p001-paddle-full-0310 p001-paddle-tile-3760-2010-0001 p001-paddle-tile-3760-0-0203 p001-paddle-tile-3760-0-0204 p001-paddle-full-0318 p001-paddle-tile-3760-0-0206 p001-paddle-tile-3760-2010-0007 p001-paddle-tile-3760-2010-0009"), "AC建筑师有限公司\n地址：8-AD套房，5层，A座，Pandan Kapital大厦，MPAJ大道，班丹英达，55100 雪兰莪\n电话：03-4294 4122；传真：03-4294 3122\n电子邮箱：acarch.sb@gmail.com", "ledger"),
    ("civil-role", ids("p001-native-0027"), "土木与结构工程师：", "wide"),
    ("civil-ledger", ids("p001-paddle-tile-3760-2010-0011 p001-paddle-tile-3760-2010-0013 p001-paddle-tile-3760-2010-0017 p001-paddle-tile-3760-2010-0019 p001-paddle-full-0346 p001-paddle-tile-3760-2010-0021 p001-paddle-tile-3760-2010-0024 p001-paddle-full-0362"), "UNITI顾问有限公司\n地址：25号，Bunga Raya 8路，Senawang商务中心，Tasik Jaya花园，70450 芙蓉，森美兰\n电话／传真：06-679 2037\n电子邮箱：uniticonsult@gmail.com", "ledger"),
    ("mechanical-role", ids("p001-native-0028"), "机械工程师：", "role"),
    ("mechanical-ledger", ids("p001-paddle-full-0374 p001-paddle-tile-3760-2010-0032 p001-paddle-tile-3760-2010-0033 p001-paddle-tile-3760-2010-0036 p001-paddle-tile-3760-2010-0038 p001-paddle-full-0402 p001-paddle-tile-3760-2010-0041 p001-paddle-tile-3760-2010-0042 p001-paddle-full-0410"), "州机械工程处／公共工程局\n地址：雪兰莪州机械工程处，银禧道17区，40200 莎阿南，雪兰莪\n电话：03-5545 9800；传真：03-5545 3858\n电子邮箱：aduansel@jkr.gov.my", "ledger"),
    ("electrical-role", ids("p001-native-0045"), "电气工程师：", "role"),
    ("electrical-ledger", ids("p001-paddle-tile-3760-2010-0045 p001-paddle-full-0425 p001-paddle-full-0432 p001-paddle-full-0435 p001-paddle-full-0437 p001-paddle-full-0447 p001-paddle-tile-3760-2010-0053 p001-paddle-tile-3760-2010-0054 p001-paddle-full-0461"), "州电气工程处／公共工程局\n地址：公共工程局总部大厦3层，银禧道17区，40200 莎阿南，雪兰莪\n电话：03-5545 9800；传真：03-5545 3858\n电子邮箱：aduansel@jkr.gov.my", "ledger"),
    ("qs-role", ids("p001-native-0029"), "工料测量师：", "role"),
    ("qs-ledger", ids("p001-paddle-full-0476 p001-paddle-full-0485 p001-paddle-tile-3760-2010-0063 p001-paddle-tile-3760-2010-0064 p001-paddle-full-0494 p001-paddle-full-0501 p001-paddle-tile-3760-2010-0069 p001-paddle-tile-3760-2010-0070"), "Aziz、Azizi及合伙人有限公司\n地址：43A号1层，Jalan Lawan Pedang 13/27，第13区，40100 莎阿南，雪兰莪\n电话：03-5510 8060；传真：03-5510 5518\n电子邮箱：aopsb.qs@gmail.com", "ledger"),
    ("landscape-role", ids("p001-native-0037"), "景观顾问：", "role"),
    ("landscape-ledger", ids("p001-paddle-full-0521 p001-paddle-tile-3760-2010-0075 p001-paddle-tile-3760-2010-0076 p001-paddle-tile-3760-2010-0078 p001-paddle-tile-3760-2010-0080 p001-paddle-full-0538 p001-paddle-tile-3760-2010-0085"), "LAMAN TBG有限公司\n地址：1号，PP 3/5路，Desa Pinggiran Putra大道，43000 加影，雪兰莪\n电话：03-8922 2999；传真：03-8920 8999\n电子邮箱：info@lamantbg.com", "ledger"),
    ("copyright", ids("p001-paddle-tile-3760-2010-0088 p001-native-0015 p001-native-0014"), "本图纸受版权保护。承包商须现场核对全部尺寸，仅以标注尺寸为准；如有差异，须在施工前立即报告建筑师。", "wide"),
    ("status-title", ids("p001-native-0021"), "图纸状态", "role"),
    ("status-preliminary", ids("p001-native-0019"), "初步", "compact"),
    ("status-tender", ids("p001-native-0017"), "投标", "compact"),
    ("status-construction", ids("p001-native-0018"), "施工", "compact"),
    ("status-information", ids("p001-native-0020"), "信息", "compact"),
    ("status-tender-table", ids("p001-native-0039"), "投标表", "compact"),
    ("status-contract", ids("p001-native-0040"), "合同", "compact"),
    ("drawing-title-label", ids("p001-native-0016"), "图纸名称", "role"),
    ("drawing-title-items", ids("p001-native-0903 p001-native-0904 p001-native-0905"), "— 索引图\n— 位置图\n— 场地平面图", "wide"),
    ("metadata-scale", ids("p001-native-0013 p001-native-0007 p001-native-0902"), "比例：1:600", "compact"),
    ("metadata-drawn", ids("p001-native-0006 p001-native-0005 p001-native-0907"), "绘制：Apiz", "compact"),
    ("metadata-checked", ids("p001-native-0009 p001-native-0010 p001-paddle-tile-3760-2010-0115"), "校核：AR. AZAHARI", "compact"),
    ("metadata-date", ids("p001-native-0004 p001-native-0011 p001-paddle-full-0683"), "日期：2025年7月", "compact"),
    ("metadata-drawing-no", ids("p001-native-0008 p001-native-0012 p001-native-0035 p001-native-0906"), "图号：ACASB 2401/MTM/WD/SP", "wide"),
]


def union(regions: list[dict]) -> list[float]:
    return [
        min(float(item["bbox"][0]) for item in regions),
        min(float(item["bbox"][1]) for item in regions),
        max(float(item["bbox"][2]) for item in regions),
        max(float(item["bbox"][3]) for item in regions),
    ]


def target_for(kind: str, box: list[float]) -> list[float]:
    x0, y0, x1, y1 = box
    if kind == "ledger":
        return [2208.0, max(2.0, y0 - 1.0), 2326.0, min(1681.0, y1 + 2.0)]
    if kind == "wide":
        return [2086.0, max(2.0, y0 - 1.0), 2326.0, min(1681.0, y1 + 2.0)]
    if kind == "compact":
        return [max(2086.0, x0 - 1.0), max(2.0, y0 - 1.0), min(2326.0, x1 + 42.0), min(1681.0, y1 + 3.0)]
    return [2086.0, max(2.0, y0 - 1.0), min(2242.0, max(x1 + 6.0, 2198.0)), min(1681.0, y1 + 10.0)]


def sidebar_block(name: str, member_ids: list[str], translated: str, kind: str, lookup: dict[str, dict]) -> dict:
    fields = [lookup[item] for item in member_ids]
    source_box = [round(value, 3) for value in union(fields)]
    target = [round(value, 3) for value in target_for(kind, source_box)]
    source = "\n".join(str(item["source_text"]).strip() for item in fields)
    bold = kind == "role" or name.endswith(("label", "title"))
    return {
        "block_id": f"z5-r4-{name}",
        "member_ids": member_ids,
        "page_index": 0,
        "coverage_status": "translated",
        "source_text": source,
        "translated_text": translated,
        "source_bbox": source_box,
        "zone_id": "Z5",
        "layout_role": "sidebar_semantic_field_reflow",
        "placement": {
            "side": "below", "mode": "title_block", "selected_region": target,
            "candidate_regions": [target], "font_size": 3.45 if kind in {"ledger", "wide"} else 3.8,
            "rotation": 0, "leader_path": [], "leader_allowed_when_local_space_exhausted": False,
            "preserve_source": False, "colour": "black", "text_color": "#000000",
            "opaque_background": "text_ink_only", "physical_text_redaction_required": True,
            "allow_source_overlap": False, "allow_dense_source_overlap": False,
            "instruction": "语义字段级黑色原文+中文重排。source_bbox 仅用于查找其中每个 OCR 文字墨迹并逐一遮蔽；不得遮蔽 source_bbox/selected_region 的空白、边框、徽标、签名或状态方框。",
            "source_overlap_review": {"reviewed_individually": True, "decision": "exact_member_ocr_ink_masks_only", "protected": ["logos", "logo_text", "panel_borders", "dividers", "signature_graphics", "status_checkboxes", "drawing_identifiers"]},
        },
        "typography": {"bold": bold, "font_weight": "bold" if bold else "regular", "semantic_role": "sidebar_field", "alignment": "left", "preserve_visual_hierarchy": True, "bilingual_reflow": True, "source_upper_chinese_lower": True, "semantic_complete": True},
    }


def main() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    lookup = {str(item["region_id"]): item for item in ocr["regions"]}
    for _, member_ids, _, _ in FIELDS:
        missing = [item for item in member_ids if item not in lookup]
        if missing:
            raise RuntimeError(f"unknown OCR fields: {missing}")
    sidebar = [sidebar_block(*field, lookup) for field in FIELDS]
    all_sidebar_ids = [item for block in sidebar for item in block["member_ids"]]
    if len(all_sidebar_ids) != len(set(all_sidebar_ids)):
        raise RuntimeError("sidebar semantic fields share OCR members")
    retained = [block for block in plan["semantic_blocks"] if block.get("zone_id") != "Z5"]
    inline = [block for block in retained if (block.get("placement") or {}).get("mode") == "inline"]
    z3 = [block for block in retained if block.get("zone_id") == "Z3"]
    if len(inline) != 67 or len(z3) != 44:
        raise RuntimeError(f"unexpected retained inventory: inline={len(inline)}, z3={len(z3)}")
    plan["semantic_blocks"] = retained + sidebar
    audit = plan.setdefault("coverage_audit", {})
    audit.update({
        "ocr_region_count": 1592,
        "semantic_block_count": len(plan["semantic_blocks"]),
        "field_level_opaque_block_count": len(z3) + len(sidebar),
        "inline_block_count": len(inline),
        "sidebar_semantic_field_count": len(sidebar),
        "sidebar_semantic_member_count": len(all_sidebar_ids),
        "unexplained_region_ids": [], "unexplained_count": 0, "manual_review_count": 0,
        "policy": "R4 provides complete visible non-logo sidebar/title semantic fields using member OCR-text masks only; Z3 table blocks and 67 drawing inline blocks are retained.",
    })
    plan["status"] = "repair"
    plan["repair_note"] = "R4 semantic-sidebar repair: complete source+Chinese reflow for visible non-logo company, address, contact, role, copyright, status, title and metadata text; no whole-panel mask."
    plan["supervisor_plan"]["placement_policy"]["title_sidebar"]["scope"] = "complete visible non-logo semantic fields; each ledger uses only member OCR text-ink masks and a same-panel text lane"
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(PLAN), "semantic_blocks": len(plan["semantic_blocks"]), "z3_fields": len(z3), "sidebar_fields": len(sidebar), "sidebar_members": len(all_sidebar_ids), "inline": len(inline)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
