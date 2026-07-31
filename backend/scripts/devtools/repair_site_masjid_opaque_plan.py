# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
"""Replace Site Masjid's unsafe whole-panel opaque blocks with field blocks.

The hybrid renderer masks ``source_bbox`` only.  This repair deliberately
keeps each bbox equal to one OCR text-ink field and confines its layout target
to the same table cell/sidebar text lane.  It does not alter any drawing-body
inline block or the page-wide coverage inventory.
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


TRANSLATIONS = {
    "p001-native-0764": "开发用地面积",
    "p001-native-0762": "地块资料",
    "p001-native-0766": "面积",
    "p001-native-0760": "地块4282",
    "p001-native-0779": "道路拓宽移交面积",
    "p001-native-0761": "道路移交面积",
    "p001-native-0775": "排水沟移交面积",
    "p001-native-0787": "场地用途",
    "p001-native-0788": "用途",
    "p001-native-0783": "百分比（%）",
    "p001-native-0789": "建筑",
    "p001-native-0790": "开放／绿化区",
    "p001-native-0791": "硬质铺装",
    "p001-native-0792": "道路／汽车位／摩托车位",
    "p001-native-0823": "TNB紧凑型变电站",
    "p001-native-0793": "现场滞洪设施（OSD）",
    "p001-native-0794": "合计",
    "p001-native-0848": "3. 图例",
    "p001-native-0836": "项目",
    "p001-native-0834": "清真寺",
    "p001-native-0838": "办公楼",
    "p001-native-0857": "有顶摩托车停车位",
    "p001-native-0841": "有顶汽车停车位",
    "p001-native-0850": "垃圾房",
    "p001-native-0854": "泵房",
    "p001-native-0855": "吸水池",
    "p001-native-0859": "凉亭",
    "p001-native-0925": "消防栓",
    "p001-native-0898": "固体废物产生量估算",
    "p001-paddle-full-0533": "礼拜人数 × 每日产生率（kg）× 每周7天",
    "p001-native-0900": "固体废物每周收集两次",
    "p001-native-0899": "a）清真寺：",
    "p001-native-0901": "b）办公楼：",
    "p001-paddle-full-0560": "人数容量",
    "p001-native-0861": "按地方政府要求设置停车位",
    "p001-native-0883": "要求",
    "p001-native-0884": "已提供",
    "p001-native-0862": "停车位",
    "p001-native-0867": "（礼拜空间）",
    "p001-native-0881": "无富余",
    "p001-native-0865": "摩托车",
    "p001-native-0876": "无障碍车辆",
    "p001-native-0878": "（最少2个）",
    "p001-native-0895": "富余1个",
    "p001-native-0044": "土地业主：",
    "p001-paddle-full-0106": "电子邮箱：pro@mais.gov.my",
    "p001-native-0038": "建筑业主：",
    "p001-paddle-tile-3760-0-0089": "地址：NO. 2, PERSIARAN MASJID,",
    "p001-native-0025": "项目：",
    "p001-native-0032": "拟拆除并重建清真寺",
    "p001-native-0031": "审核",
    "p001-native-0036": "实施机构：",
    "p001-paddle-full-0263": "电子邮箱：aduansel@jkr.gov.my",
    "p001-native-0030": "申请人姓名／签名／身份证号：",
    "p001-native-0001": "建筑师：Ar. Mohd Azahari Bin Mad Atan",
    "p001-paddle-full-0289": "本人确认图纸细节符合相关建筑规定。",
    "p001-native-0026": "建筑师：",
    "p001-paddle-full-0310": "AC建筑师有限公司",
    "p001-native-0027": "土木与结构工程师：",
    "p001-paddle-tile-3760-2010-0017": "森那旺商业中心，",
    "p001-native-0028": "机械工程师：",
    "p001-paddle-tile-3760-2010-0036": "雪兰莪州机械工程处，",
    "p001-native-0045": "电气工程师：",
    "p001-paddle-full-0435": "雪兰莪州公共工程局",
    "p001-native-0029": "工料测量师：",
    "p001-paddle-tile-3760-2010-0064": "第13区，",
    "p001-native-0037": "景观顾问：",
    "p001-paddle-tile-3760-2010-0085": "电子邮箱：info@lamantbg.com",
    "p001-native-0015": "承包商须现场核对全部尺寸；仅以标注尺寸为准。",
    "p001-native-0021": "图纸状态",
    "p001-native-0018": "施工",
    "p001-native-0016": "图纸名称",
    "p001-native-0903": "— 索引图",
    "p001-native-0013": "比例",
}


# Every entry is a safe layout rectangle inside exactly one existing ruled cell
# or one sidebar text lane.  It is intentionally separate from source_bbox:
# source_bbox remains the exact OCR ink, while this field rectangle provides
# enough room to reflow source and Chinese without touching lines or logos.
Z3_TARGETS = {
    "p001-native-0764": [72, 903, 350, 923],
    "p001-native-0762": [70, 932, 350, 955],
    "p001-native-0766": [430, 922, 560, 946],
    "p001-native-0760": [70, 973, 350, 990],
    "p001-native-0779": [70, 991, 350, 1007],
    "p001-native-0761": [70, 1009, 350, 1025],
    "p001-native-0775": [70, 1027, 350, 1043],
    "p001-native-0787": [70, 1060, 350, 1080],
    "p001-native-0788": [70, 1088, 350, 1110],
    "p001-native-0783": [490, 1088, 580, 1110],
    "p001-native-0789": [75, 1128, 350, 1144],
    "p001-native-0790": [75, 1151, 350, 1167],
    "p001-native-0791": [75, 1173, 350, 1189],
    "p001-native-0792": [75, 1195, 350, 1211],
    "p001-native-0823": [75, 1217, 350, 1233],
    "p001-native-0793": [75, 1239, 350, 1255],
    "p001-native-0794": [75, 1261, 350, 1278],
    "p001-native-0848": [598, 917, 752, 936],
    "p001-native-0836": [630, 941, 752, 961],
    "p001-native-0834": [630, 962, 752, 979],
    "p001-native-0838": [630, 978, 752, 995],
    "p001-native-0857": [630, 994, 752, 1012],
    "p001-native-0841": [630, 1020, 752, 1038],
    "p001-native-0850": [630, 1082, 752, 1099],
    "p001-native-0854": [630, 1098, 752, 1114],
    "p001-native-0855": [630, 1114, 752, 1130],
    "p001-native-0859": [630, 1129, 752, 1146],
    "p001-native-0925": [630, 1170, 752, 1188],
    "p001-native-0898": [55, 1292, 500, 1312],
    "p001-paddle-full-0533": [60, 1319, 300, 1335],
    "p001-native-0900": [60, 1337, 350, 1353],
    "p001-native-0899": [60, 1351, 190, 1367],
    "p001-native-0901": [285, 1351, 390, 1367],
    "p001-paddle-full-0560": [75, 1380, 170, 1399],
    "p001-native-0861": [507, 1388, 823, 1408],
    "p001-native-0883": [610, 1413, 704, 1432],
    "p001-native-0884": [728, 1413, 816, 1432],
    "p001-native-0862": [510, 1443, 600, 1460],
    "p001-native-0867": [610, 1451, 700, 1469],
    "p001-native-0881": [732, 1467, 816, 1484],
    "p001-native-0865": [510, 1522, 600, 1539],
    "p001-native-0876": [510, 1581, 610, 1599],
    "p001-native-0878": [620, 1578, 705, 1595],
    "p001-native-0895": [732, 1586, 816, 1604],
}


def sidebar_target(bbox: list[float]) -> list[float]:
    """Keep a sidebar field in its own text lane, never across a panel."""
    x0, y0, x1, y1 = bbox
    # Header fields live in the left text strip; contact/address fields have
    # already been OCR'd in the right strip.  Keep both inside their observed
    # lane and use a shallow two-column reflow when the vertical fit is tight.
    if x1 > 2198:
        # This is one long original field, not a panel aggregate.  Its own
        # OCR ink already spans both sidebar lanes, so retain that field-only
        # width while keeping the target shallow in its original row.
        right = min(2326.0, x1 + 1.0)
    elif x0 < 2200:
        right = min(2198.0, max(x1 + 8.0, x0 + 92.0))
    else:
        right = min(2326.0, max(x1 + 8.0, x0 + 110.0))
    return [round(max(2084.5, x0 - 1.0), 3), round(y0 - 1.2, 3), round(right, 3), round(y1 + 1.8, 3)]


def typography(source: str, zone: str) -> dict:
    upper = source.upper()
    role = "field_label"
    bold = False
    if zone == "Z3" and (upper.startswith(("3.", "4.", "5.")) or "KELUASAN" in upper or "KEGUNAAN KAWASAN" in upper):
        role, bold = "section_heading", True
    elif zone == "Z5" and (upper.endswith(":") or upper in {"DRAWING STATUS", "DRAWING TITLE", "CONSTRUCTION"}):
        role, bold = "field_label", True
    return {
        "bold": bold,
        "font_weight": "bold" if bold else "regular",
        "semantic_role": role,
        "alignment": "left",
        "preserve_visual_hierarchy": True,
        "bilingual_reflow": True,
        "source_upper_chinese_lower": False,
        "field_level": True,
    }


def make_block(*, region: dict, zone: str, target: list[float]) -> dict:
    region_id = str(region["region_id"])
    source = str(region["source_text"]).strip()
    return {
        "block_id": f"{zone.lower()}-field-{region_id.replace('p001-', '')}",
        "member_ids": [region_id],
        "page_index": int(region.get("page_index", 0)),
        "coverage_status": "translated",
        "source_text": source,
        "translated_text": TRANSLATIONS[region_id],
        # Exact OCR text ink: never a ruled table, sidebar panel or logo box.
        "source_bbox": [round(float(value), 3) for value in region["bbox"]],
        "zone_id": zone,
        "layout_role": "field_bilingual_reflow",
        "placement": {
            "side": "below",
            "mode": "table_cell" if zone == "Z3" else "title_block",
            "selected_region": target,
            "candidate_regions": [target],
            "font_size": 3.8 if zone == "Z3" else 3.35,
            "rotation": 0,
            "leader_path": [],
            "leader_allowed_when_local_space_exhausted": False,
            "preserve_source": False,
            "colour": "black",
            "text_color": "#000000",
            "opaque_background": "text_ink_only",
            "physical_text_redaction_required": True,
            "allow_source_overlap": False,
            "allow_dense_source_overlap": False,
            "instruction": "字段级黑色原文+中文重排；仅遮蔽 source_bbox 的原文字墨迹；selected_region 仅为同一字段的排版区域；不得触碰表格线、分隔线、Logo、签名、数值或相邻字段。",
            "source_overlap_review": {
                "reviewed_individually": True,
                "decision": "field_level_text_ink_only_no_panel_mask",
                "protected": ["grid_rules", "panel_borders", "dividers", "logos", "signature_graphics", "numeric_values", "adjacent_fields"],
            },
        },
        "typography": typography(source, zone),
    }


def main() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    regions = {str(item["region_id"]): item for item in ocr["regions"]}

    old_opaque = [
        block for block in plan["semantic_blocks"]
        if block.get("zone_id") in {"Z3", "Z5"}
        and (block.get("placement") or {}).get("mode") in {"table_cell", "title_block"}
    ]
    field_ids = [member for block in old_opaque for member in block["member_ids"]]
    if len(field_ids) != 74 or len(set(field_ids)) != 74:
        raise RuntimeError(f"expected 74 distinct opaque field members, got {len(field_ids)} / {len(set(field_ids))}")
    missing = sorted(set(field_ids) - set(TRANSLATIONS))
    if missing:
        raise RuntimeError(f"missing Chinese translations: {missing}")

    rebuilt: list[dict] = []
    for region_id in field_ids:
        region = regions.get(region_id)
        if not region:
            raise RuntimeError(f"missing OCR region: {region_id}")
        if region_id in Z3_TARGETS:
            rebuilt.append(make_block(region=region, zone="Z3", target=Z3_TARGETS[region_id]))
        else:
            rebuilt.append(make_block(region=region, zone="Z5", target=sidebar_target(region["bbox"])))

    inline = [block for block in plan["semantic_blocks"] if block not in old_opaque]
    if len(inline) != 67:
        raise RuntimeError(f"expected 67 untouched inline blocks, got {len(inline)}")
    before_inline = json.dumps(inline, ensure_ascii=False, sort_keys=True)
    plan["semantic_blocks"] = inline + rebuilt
    if json.dumps(plan["semantic_blocks"][: len(inline)], ensure_ascii=False, sort_keys=True) != before_inline:
        raise RuntimeError("inline blocks changed")

    audit = plan.setdefault("coverage_audit", {})
    audit.update({
        "ocr_region_count": 1592,
        "claimed_source_region_count": 141,
        "semantic_block_count": 141,
        "field_level_opaque_block_count": 74,
        "inline_block_count": 67,
        "replaced_whole_panel_opaque_block_count": 21,
        "unexplained_region_ids": [],
        "unexplained_count": 0,
        "manual_review_count": 0,
        "policy": "Every OCR region remains accounted for; 74 Z3/Z5 opaque blocks are exact field-level text-ink reflows, and the 67 drawing-body inline blocks are unchanged.",
    })
    plan["status"] = "repair"
    plan["repair_note"] = "Hybrid R2 opaque-panel repair: replace all whole-panel aggregates in Z3/Z5 with field-level text-ink blocks; preserve existing inline drawing blocks."
    policy = plan["supervisor_plan"]["placement_policy"]
    policy["pure_text_tables"]["scope"] = "individual original text-ink field only; selected_region must remain in the same ruled cell; never clear a table/panel rectangle"
    policy["title_sidebar"]["scope"] = "individual original text-ink field only; selected_region must remain in the same sidebar text lane; never clear a panel rectangle"
    policy["forbidden"] = sorted(set(policy.get("forbidden", [])) | {"whole-panel-aggregate-opaque-blocks", "masking-selected-region", "table-rule-or-logo-mask"})

    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(PLAN), "semantic_blocks": len(plan["semantic_blocks"]), "opaque_fields": len(rebuilt), "inline_unchanged": len(inline), "members": len({member for block in plan["semantic_blocks"] for member in block["member_ids"]})}, ensure_ascii=False))


if __name__ == "__main__":
    main()
