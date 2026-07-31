# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
"""Build the Site Masjid R5.2 collision-free visual candidate plan."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from services.engineering_drawing.overlay_pair import _matched_ocr_rects


ARTIFACT = Path(
    r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing"
    r"\01_Bilingual_Inline\batch-artifacts"
    r"\03_CONSTRUCTION_DWG_MASJID_11_NOV_2025__00_Site_Masjid_Tok_Muda_CONSTRUCTION__eea8ec342c"
)
PLAN = ARTIFACT / "v3.3-post-ocr-executable-plan.json"
OCR = ARTIFACT / "v3.3-supervised-hybrid-ocr.json"
MASK_OCR = ARTIFACT / "v3.3-r5-ocr-mask-fields.json"


# Concise, complete-enough callout renderings.  Drawing numbers already remain
# visible in the source, so Chinese does not repeat them in dense margins.
CALLOUTS = {
    "z4-temporary-carpark": ("虚线：2.5×5m临时车位", [1257, 225, 1394, 234]),
    "z4-decorative-post": ("1700高装饰门柱；耐候漆", [1257, 284, 1396, 293]),
    "z4-demolish": ("虚线：拆除现有清真寺及附属建筑", [1257, 309, 1453, 318]),
    "z4-motorcycle-callout": ("有顶摩托车位：互锁砖；详见DT-01、02", [1257, 365, 1450, 374]),
    "z4-existing-hydrant": ("现有消防栓按需修复", [1884, 234, 1998, 243]),
    "z4-sliding-gate": ("1700高重型钢滑门；配件滚轮；防锈亮光漆", [1875, 318, 2041, 327]),
    "z4-side-gate": ("钢侧门：防锈及亮光漆", [1875, 340, 2041, 349]),
    "z4-meter-sub": ("水表间及紧凑型变电站；详见WD-01", [1875, 385, 2041, 394]),
    "z4-covered-carpark": ("有顶车位：硬化地坪；详见DT-01、02", [1876, 472, 2040, 481]),
    "z4-covered-walkway": ("有顶人行道；详见LJKB/DT-01", [1196, 659, 1330, 668]),
    "z4-planter": ("混凝土种植池及座椅；详见BP2/DT-01、02", [1774, 659, 1945, 668]),
    "z4-oku-carpark": ("3个无障碍车位；热塑标线及标志", [1742, 720, 1968, 729]),
    "z4-premix-kerb": ("预拌沥青及150高混凝土路缘石：按详图", [1742, 766, 1930, 775]),
    "z4-inspection-chamber": ("检查井每15m设置；按机电详图", [880, 850, 1005, 862]),
    "z4-paving": ("铺路砖按厂家规范并经建筑师批准", [1012, 965, 1164, 974]),
    "z4-qurban-pole": ("宰牲节钢柱；详见RCP/DT-01", [909, 1202, 1040, 1211]),
    "z4-ramp": ("混凝土坡道1:12；扫毛饰面", [1518, 1167, 1670, 1176]),
    "z4-drain-sump": ("1370见方砖砌集水井；镀锌格栅盖", [1519, 1210, 1665, 1219]),
    "z4-road-drain": ("虚线：600宽有盖预制道路排水沟", [1518, 1260, 1685, 1269]),
    "z4-grating-frame": ("450×450开口；5厚镀锌格栅及框架", [1517, 1281, 1728, 1290]),
    "z4-typical-carpark": ("2.5×5m典型车位；80厚重型植草砖", [1518, 1375, 1747, 1384]),
    "z4-gazebo-callout": ("凉亭详见GZ/DT-01", [1518, 1403, 1643, 1412]),
    "z4-fence": ("1700高镀锌周界围栏", [1518, 1445, 1686, 1454]),
}

NEW_CALLOUTS = [
    ("proposed-hydrant-west", "p001-paddle-tile-2020-2010-0035", "拟建消防栓", [1011, 1046, 1126, 1055]),
    ("loading-area", "p001-paddle-tile-2020-2010-0038", "装卸区", [1011, 1082, 1136, 1091]),
    ("proposed-hydrant-east", "p001-paddle-full-0361", "拟建消防栓", [1715, 960, 1800, 972]),
    ("construction-drawing", "p001-native-1029", "施工图", [1930, 1550, 2050, 1570]),
]

FORMULA_INLINE = {
    "z3-r5-waste-mosque-variables": ("人数×日产生率×7天÷每周收集频率", [64, 1373, 250, 1383]),
    "z3-r5-waste-office-variables": ("面积×日产生率×7天÷每周收集频率", [290, 1373, 477, 1383]),
    "z3-r5-waste-mosque-per-collection": ("每次收集量÷垃圾密度", [64, 1460, 250, 1470]),
    "z3-r5-waste-office-per-collection": ("每次收集量÷垃圾密度", [290, 1460, 477, 1470]),
    "z3-r5-waste-mobile-bin-summary": (
        "总容量4,270升；移动桶4个（1,100升/个）\n尺寸：1370宽×1115深×1470高（mm）",
        [285, 1552, 477, 1584],
    ),
}

GROUPS = [
    (
        "key-map-perepat",
        ["z1-perepat"],
        "柏勒巴花园",
        [500, 170, 620, 184],
    ),
    (
        "key-map-final-labels",
        ["z1-bukit-kapar", "z1-bukit-raja"],
        "武吉加埔；武吉拉惹",
        [500, 152, 650, 166],
    ),
    (
        "key-map-rejected-labels",
        ["z1-saujana", "z1-proposed", "z1-tok-muda", "z1-botani", "z1-sea", "z1-section-18", "z1-pulau-klang", "z1-klang", "z1-padamaran"],
        "索加纳花园；拟建场地；督慕达村；植物园花园\n马六甲海峡；第18区；巴生岛；巴生；班达马兰",
        [500, 105, 720, 145],
    ),
    (
        "location-map-rejected-labels",
        ["z2-idaman", "z2-proposed"],
        "依达曼花园；拟建场地",
        [500, 500, 650, 514],
    ),
    (
        "north-road-reserves",
        ["z4-jalan-masjid", "z4-road-widening-reserve", "z4-drain-reserve", "z4-slip-road-reserve", "z4-perimeter-planting"],
        "清真寺路；道路拓宽预留；排水预留\n辅路预留；周界绿化",
        [1000, 145, 1190, 177],
    ),
    (
        "south-road-labels",
        ["z4-road-handover", "z4-jalan-pusaka"],
        "移交道路；普萨卡路",
        [650, 1405, 790, 1420],
    ),
    (
        "northwest-demolition",
        ["z4-decorative-post", "z4-demolish"],
        "装饰门柱：高1700、耐候漆\n虚线：拆除现有清真寺及附属建筑",
        [1080, 270, 1248, 300],
    ),
    (
        "east-gates-services",
        ["z4-sliding-gate", "z4-side-gate", "z4-meter-sub"],
        "重型钢滑门：高1700，配件滚轮，防锈亮光漆\n钢侧门：防锈亮光漆\n水表间及紧凑型变电站：详见WD-01",
        [1875, 252, 2055, 298],
    ),
    (
        "oku-premix-kerb",
        ["z4-oku-carpark", "z4-premix-kerb"],
        "3个无障碍车位：热塑标线及标志\n预拌沥青及150高混凝土路缘石：按详图",
        [1742, 790, 1968, 816],
    ),
    (
        "south-detail-stack",
        ["z4-grating-frame", "z4-typical-carpark", "z4-gazebo-callout", "z4-fence"],
        "450×450开口：5厚镀锌格栅及框架\n典型车位：2.5×5m、80厚重型植草砖\n凉亭详见GZ/DT-01；周界围栏高1700",
        [1518, 1460, 1747, 1495],
    ),
    (
        "waste-per-collection",
        ["z3-r5-waste-mosque-per-collection", "z3-r5-waste-office-per-collection"],
        "每次收集量÷垃圾密度",
        [218, 1458, 288, 1470],
    ),
]


def compact_source(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= 4:
        return "\n".join(lines)
    company = lines[0]
    contacts = [line for line in lines if line.lower().startswith(("t:", "f:", "e:", "www"))]
    address = [line for line in lines[1:] if line not in contacts]
    contact_line = "  ".join(contacts)
    return "\n".join([company, " ".join(address), contact_line])


def inline_block(name: str, region_id: str, chinese: str, target: list[float], lookup: dict[str, dict]) -> dict:
    region = lookup[region_id]
    return {
        "block_id": f"z4-r5-2-{name}", "member_ids": [region_id], "page_index": 0,
        "coverage_status": "translated", "source_text": str(region["source_text"]),
        "translated_text": chinese, "source_bbox": [float(v) for v in region["bbox"]],
        "zone_id": "Z4", "layout_role": "drawing_callout_translation",
        "placement": {
            "side": "below", "mode": "inline", "selected_region": target,
            "candidate_regions": [], "font_size": 3.4, "rotation": 0, "leader_path": [],
            "leader_path": [], "leader_allowed_when_local_space_exhausted": False,
            "preserve_source": True, "colour": "blue", "allow_source_overlap": False,
            "allow_dense_source_overlap": False,
            "source_overlap_review": {"reviewed_individually": True, "decision": "r5_2_clear_single_line_target"},
        },
        "typography": {"bold": False, "font_weight": "regular", "semantic_role": "drawing_callout", "alignment": "left"},
    }


def grouped_block(name: str, originals: list[dict], chinese: str, target: list[float]) -> dict:
    member_ids = [member for item in originals for member in item["member_ids"]]
    boxes = [item["source_bbox"] for item in originals]
    source = "\n".join(str(item["source_text"]) for item in originals)
    return {
        "block_id": f"z4-r5-2-group-{name}", "member_ids": member_ids, "page_index": 0,
        "coverage_status": "translated", "source_text": source, "translated_text": chinese,
        "source_bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)],
        "zone_id": "Z4", "layout_role": "grouped_drawing_callout_translation",
        "placement": {
            "side": "left", "mode": "inline", "selected_region": target,
            "candidate_regions": [], "font_size": 3.2, "rotation": 0, "leader_path": [],
            "leader_path": [], "leader_allowed_when_local_space_exhausted": False,
            "preserve_source": True, "colour": "blue", "allow_source_overlap": False,
            "allow_dense_source_overlap": False,
            "source_overlap_review": {"reviewed_individually": True, "decision": "r5_2_grouped_clear_whitespace_target"},
        },
        "typography": {"bold": False, "font_weight": "regular", "semantic_role": "drawing_callout_group", "alignment": "left"},
    }


def main() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    lookup = {str(item["region_id"]): item for item in ocr["regions"]}
    existing_groups = {
        str(b.get("block_id") or ""): b
        for b in plan["semantic_blocks"]
        if str(b.get("block_id") or "").startswith("z4-r5-2-group-")
    }
    blocks = [
        b for b in plan["semantic_blocks"]
        if not str(b.get("block_id") or "").startswith("z4-r5-2-")
        or str(b.get("block_id") or "").startswith("z4-r5-2-group-")
    ]

    by_id = {str(item.get("block_id") or ""): item for item in blocks}
    grouped_ids = {block_id for _, ids, _, _ in GROUPS for block_id in ids}
    grouped = []
    for name, ids, chinese, target in GROUPS:
        missing = [block_id for block_id in ids if block_id not in by_id]
        group_id = f"z4-r5-2-group-{name}"
        if missing:
            if group_id not in existing_groups:
                raise RuntimeError(f"missing grouped blocks {name}: {missing}")
            item = existing_groups[group_id]
            item["translated_text"] = chinese
            item["placement"]["selected_region"] = target
            item["placement"]["candidate_regions"] = []
            item["placement"]["leader_path"] = []
            grouped.append(item)
        else:
            grouped.append(grouped_block(name, [by_id[block_id] for block_id in ids], chinese, target))
    blocks = [
        item for item in blocks
        if str(item.get("block_id") or "") not in grouped_ids
        and not str(item.get("block_id") or "").startswith("z4-r5-2-group-")
    ]

    for item in blocks:
        block_id = str(item.get("block_id") or "")
        if block_id in CALLOUTS:
            chinese, target = CALLOUTS[block_id]
            item["translated_text"] = chinese
            placement = item["placement"]
            placement.update({
                "side": "below", "mode": "inline", "selected_region": target,
                "candidate_regions": [], "font_size": 3.0 if block_id in FORMULA_INLINE else 3.2, "rotation": 0, "leader_path": [],
                "leader_path": [], "leader_allowed_when_local_space_exhausted": False,
                "preserve_source": True, "colour": "blue", "allow_source_overlap": False,
                "allow_dense_source_overlap": False,
            })
            placement["source_overlap_review"] = {"reviewed_individually": True, "decision": "r5_2_clear_single_line_target"}
        if block_id == "z4-site-title":
            item["translated_text"] = "场地平面图｜比例1:600"
            item["placement"].update({
                "selected_region": [1630, 1532, 1760, 1546], "candidate_regions": [], "leader_path": [],
                "font_size": 6.0, "side": "right", "mode": "inline", "allow_source_overlap": False,
                "allow_dense_source_overlap": False, "leader_path": [],
            })
        if block_id == "z4-site-notes":
            item["translated_text"] = "注：1 界址由测量师确认；2 朝向由主管部门确认\n3 每个无障碍车位设标志（共3个）"
            item["placement"].update({
                "selected_region": [500, 600, 800, 630], "candidate_regions": [],
                "font_size": 3.8, "side": "right", "mode": "inline",
                "allow_source_overlap": False, "allow_dense_source_overlap": False,
                "leader_path": [],
            })
        if block_id == "z1-key-title":
            item["translated_text"] = "索引图｜不按比例"
            item["placement"].update({"selected_region": [245, 410, 360, 425], "font_size": 4.5, "candidate_regions": [], "leader_path": []})
        if block_id == "z2-title":
            item["translated_text"] = "位置图｜不按比例"
            item["placement"].update({"selected_region": [260, 865, 375, 880], "font_size": 4.5, "candidate_regions": [], "leader_path": []})
        if block_id in FORMULA_INLINE:
            chinese, target = FORMULA_INLINE[block_id]
            item["translated_text"] = chinese
            placement = item["placement"]
            placement.update({
                "mode": "inline", "side": "below", "selected_region": target,
                "candidate_regions": [], "font_size": 3.2, "rotation": 0, "leader_path": [],
                "leader_path": [], "preserve_source": True, "colour": "blue",
                "allow_source_overlap": False, "allow_dense_source_overlap": False,
            })
            for key in ("opaque_background", "physical_text_redaction_required", "layout_variant"):
                placement.pop(key, None)
            item["layout_role"] = "solid_waste_inline_translation"
        if str(item.get("layout_role") or "").startswith("sidebar_company"):
            placement = item["placement"]
            placement["selected_region"] = [2194.0, item["source_bbox"][1] - 1.5, 2326.0, item["source_bbox"][3] + 2.8]
            placement["candidate_regions"] = []
            placement["leader_path"] = []
            placement["font_size"] = 3.7
            placement["render_source_text"] = compact_source(str(item.get("source_text") or ""))

    known = {member for item in blocks for member in item.get("member_ids", [])}
    for item in grouped:
        if any(member in known for member in item["member_ids"]):
            raise RuntimeError(f"grouped member already claimed: {item['block_id']}")
        blocks.append(item)
        known.update(item["member_ids"])
    for name, region_id, chinese, target in NEW_CALLOUTS:
        if region_id in known:
            raise RuntimeError(f"R5.2 member already claimed: {region_id}")
        new_block = inline_block(name, region_id, chinese, target, lookup)
        if name == "construction-drawing":
            new_block["placement"]["font_size"] = 4.5
        blocks.append(new_block)
        known.add(region_id)

    plan["execution_policy"] = "strict_multimodal_execution"
    mask_payload = json.loads(MASK_OCR.read_text(encoding="utf-8"))
    mask_regions = mask_payload.get("regions") or []
    for item in blocks:
        placement = item.setdefault("placement", {})
        placement["candidate_regions"] = []
        placement.setdefault("rotation", 0)
        placement.setdefault("leader_path", [])
        opaque = placement.get("mode") in {"title_block", "table_cell"}
        placement["color"] = [0.0, 0.0, 0.0] if opaque else [0.05, 0.16, 0.45]
        placement["render_text"] = (
            f"{placement.get('render_source_text') or item.get('source_text') or ''}\n"
            f"{item.get('translated_text') or ''}"
            if opaque and not placement.get("preserve_source")
            else str(item.get("translated_text") or "")
        ).strip()
        compact_metadata = {
            "z5-r4-metadata-scale": "Skala: 1:600 / 比例：1:600",
            "z5-r4-metadata-drawn": "Dilukis: Apiz / 绘制：Apiz",
            "z5-r4-metadata-checked": "Disemak: AR. AZAHARI / 校核：AR. AZAHARI",
            "z5-r4-metadata-date": "Tarikh: JULAI 2025 / 日期：2025年7月",
        }
        if item.get("block_id") in compact_metadata:
            placement["render_text"] = compact_metadata[item["block_id"]]
        if opaque and not placement.get("preserve_source"):
            fallback = fitz.Rect([float(value) for value in item["source_bbox"]])
            masks = _matched_ocr_rects(
                source_text=str(item.get("source_text") or ""),
                fallback=fallback,
                ocr_regions=mask_regions,
            )
            placement["exact_ink_masks"] = [list(rect) for rect in masks]
    plan["semantic_blocks"] = blocks
    zone_specs = [
        ("site-callouts", "site_plan_callouts", lambda block_id: block_id.startswith("z4-") and not any(token in block_id for token in ("key-map", "location-map", "waste"))),
        ("maps", "key_and_location_maps", lambda block_id: block_id.startswith(("z1-", "z2-")) or "key-map" in block_id or "location-map" in block_id),
        ("tables-formulas", "tables_calculations_and_formulas", lambda block_id: block_id.startswith("z3-") or "waste" in block_id),
        ("title-sidebar", "title_block_and_consultant_sidebar", lambda block_id: block_id.startswith("z5-")),
    ]
    audits = []
    assigned: set[str] = set()
    for zone_id, zone_type, predicate in zone_specs:
        zone_blocks = [item for item in blocks if predicate(str(item.get("block_id") or ""))]
        if zone_blocks:
            audits.append({
                "zone_id": zone_id,
                "zone_type": zone_type,
                "page_index": 0,
                "member_ids": [member for item in zone_blocks for member in item.get("member_ids", [])],
                "block_ids": [str(item["block_id"]) for item in zone_blocks],
                "status": "complete",
            })
            assigned.update(str(item["block_id"]) for item in zone_blocks)
    unassigned = [str(item["block_id"]) for item in blocks if str(item["block_id"]) not in assigned]
    if unassigned:
        raise RuntimeError(f"mandatory zone audit left blocks unassigned: {unassigned}")
    plan["mandatory_zone_audit"] = audits
    audit = plan.setdefault("coverage_audit", {})
    audit.update({
        "semantic_block_count": len(blocks), "r5_2_new_callouts": len(NEW_CALLOUTS),
        "r5_2_reflowed_callouts": len(CALLOUTS), "r5_2_formula_inline_groups": len(FORMULA_INLINE),
        "policy": "R5.2 uses concise near-source single-line blue translations without drawing-body white blocks; formula values/source remain untouched; sidebar ledgers use readable two-zone reflow.",
    })
    plan["status"] = "repair"
    plan["repair_note"] = "R5.2 candidate-only repair following independent Sol Light rejection; no publication."
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"semantic_blocks": len(blocks), "new_callouts": len(NEW_CALLOUTS), "reflowed": len(CALLOUTS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
