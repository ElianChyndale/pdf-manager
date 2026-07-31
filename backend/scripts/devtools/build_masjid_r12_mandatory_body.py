# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""R12: parameter-specific rebuild of the Masjid mandatory drawing zones.

R11 proved that a clean sidebar alone is not a valid translation delivery.
This builder replaces every generic room summary, restores the omitted readable
technical callouts, and records a page-by-page mandatory-zone audit.  The
placement helper emits a single final rectangle per block; the renderer is not
allowed to move, shrink, or select an alternative.
"""

import json
import re
from pathlib import Path

from build_masjid_r11_left_companion_strict import OUTPUT_PLAN as R11_PLAN, main as build_r11


ARTIFACT = R11_PLAN.parent
OCR = ARTIFACT / "v3.3-supervised-hybrid-ocr.json"
OUTPUT_PLAN = ARTIFACT / "v3.4-r12-mandatory-body-plan.json"

GENERIC_REPLACEMENTS = {
    "postocr-0054-p001-native-0094": "房间／区域",
    "postocr-0062-p001-native-0103": "房间／区域",
    "postocr-0081-p001-native-0122": "房间／区域",
    "r9-room-p003-001": "溢出空间",
    "r9-room-p003-002": "走廊",
    "r9-room-p003-003": "溢出空间",
    "r9-room-p003-004": "走廊",
    "postocr-0228-p004-native-0062": "小净区",
    "r9-room-p004-001": "溢出空间",
    "r9-room-p004-002": "走廊",
    "r9-room-p004-003": "祈祷室",
    "r9-room-p004-004": "男用区",
    "r9-room-p004-005": "溢出空间",
    "r9-room-p004-006": "走廊",
}

# The source OCR occasionally loses spaces, but these readings preserve every
# recoverable size, material and instruction instead of replacing a callout
# with a generic "see original" sentence.
MISSING = {
    "p001-paddle-full-0027": "内侧12毫米厚抹灰；外侧采用耐候涂料。",
    "p001-paddle-full-0097": "混凝土踏步，饰面及构造按工程师详图施工。",
    "p001-paddle-full-0098": "钢筋混凝土坡道，坡度1:12；饰面按工程师详图施工。",
    "p001-paddle-full-0123": "450×450毫米混凝土集水坑，按工程师详图施工。",
    "p001-paddle-full-0316": "防水砂浆浆料／防水层按图示配比及专业规范施工。",
    "p001-paddle-full-0334": "12毫米厚水泥砂浆抹面，外涂耐候涂料。",
    "p002-paddle-full-0110": "60毫米×650毫米、17毫米厚钢筋混凝土平屋面，按工程师详图施工。",
    "p002-paddle-full-0221": "按工程师详图施工，并设置防水层。",
    "p002-paddle-full-0355": "虚线表示下方梁的位置。",
    "p002-paddle-full-0466": "科技屋面系统，坡度2°，按制造商规范施工。",
    "p003-paddle-full-0053": "科技屋面系统，坡度2°，按制造商规范施工。",
    "p003-paddle-full-0059": "900毫米双层铝制圆顶，按专业详图施工。",
    "p003-paddle-full-0173": "1200毫米高、150毫米厚黏土砖墙；水泥砂浆抹灰并做饰面。",
    "p003-paddle-full-0180": "150×150毫米混凝土构件，按工程师详图施工。",
    "p003-paddle-full-0266": "洁净科技屋面系统，坡度5°，按制造商规范施工。",
    "p003-paddle-full-0274": "轻型屋架，坡度2°，按工程师详图施工。",
    "p003-paddle-full-0276": "轻型屋架，坡度2°，按工程师详图施工。",
    "p003-paddle-full-0318": "拱架采用100毫米金属框架，并作防锈处理。",
    "p003-paddle-full-0474": "1600毫米单层铝制圆顶，按专业详图施工。",
    "p003-paddle-full-0528": "500×150毫米钢筋混凝土柱，按工程师详图施工。",
    "p003-paddle-full-0554": "300×300毫米预制水泥构件，按图示施工。",
    "p004-paddle-full-0164": "暗藏式重型UPVC管道／配件，按图示安装。",
    "p004-paddle-full-0252": "1200毫米双层铝制圆顶，按专业详图施工。",
    "p004-paddle-full-0365": "2100毫米高瓷砖墙面饰面。",
    "p004-paddle-full-0414": "2个带立柱洗手盆，按建筑师详图施工。",
    "p004-paddle-full-0571": "内侧12毫米厚抹灰，外涂耐候涂料。",
    "p004-paddle-full-0579": "1000毫米宽×500毫米高混凝土种植箱，配混凝土构造。",
}

# R12 visual review reserved these exact alternate caption lanes after R11's
# former targets proved occupied. They are page-specific final decisions, not
# candidate fallbacks.
FINAL_TARGET_OVERRIDES = {
    "r8-sidebar-p001-mechanical": [4.0, 812.0, 74.0, 824.0],
    "postocr-0123-p002-native-0066": [800.0, 468.0, 870.0, 482.0],
    "r9-room-p003-004": [900.0, 520.0, 950.0, 532.0],
    "postocr-0229-p004-native-0063": [700.0, 488.0, 730.0, 500.0],
    "r8-sidebar-p004-mechanical": [4.0, 812.0, 74.0, 824.0],
    "r12-mandatory-p004-paddle-full-0579": [400.0, 806.0, 501.0, 828.0],
}

ZONES = {
    "elevation_detail_callouts": r"ENGR|ARCH|DETAIL|ROOF|GUTTER|WATER.?PROOF|DOME|WALL|CONC|PLASTER|PAINT|CEMENT|PORCEL|TRUSS|SLAB|BEAM|COPING|RENDER",
    "general_notes": r"NOTA\s*UMUM|CONTRACTOR|DIMENSION|DRAWING|SPECIFICATION|WORK",
    "schedules": r"JADUAL|TABLE|PINTU|TINGKAP|KELUASAN|PENCAHAYAAN|PENGUDARAAN|KEMASAN",
    "tower_plans": r"PELAN\s*MENARA|MENARA|RASUK",
    "elevations_sections": r"PANDANGAN|ELEVATION|SECTION|ARAS\s*(RASUK|TANAH|JALAN)",
    "room_labels": r"RUANG|BILIK|TANDAS|WUDHU|MUSLIM|KORIDOR|LALUAN|PANTRI|JENAZAH",
}


def _intersects(a: list[float], b: list[float], pad: float = 1.5) -> bool:
    return max(a[0], b[0]) < min(a[2], b[2]) + pad and max(a[1], b[1]) < min(a[3], b[3]) + pad


def _target_for(source: list[float], text: str, occupied: list[list[float]]) -> list[float]:
    """Choose a deterministic nearby final box; no renderer fallback exists."""
    width = min(176.0, max(74.0, 10.0 + len(text) * 3.25))
    height = 15.0 if len(text) <= 30 else 22.0
    sx, sy = source[0], source[3] + 4.0
    proposals: list[tuple[float, float]] = []
    for radius in (0, 18, 36, 54, 72, 96, 120):
        for dx, dy in ((0, radius), (radius, 0), (-radius, 0), (0, -radius), (radius, radius), (-radius, radius)):
            proposals.append((sx + dx, sy + dy))
    # The secondary pass stays left of the title sidebar and is only used if a
    # local callout cluster has no free caption lane.
    for y in range(12, 810, 18):
        for x in range(12, 930, 38):
            proposals.append((float(x), float(y)))
    for x, y in proposals:
        x = min(950.0 - width, max(4.0, x))
        y = min(823.0 - height, max(4.0, y))
        rect = [round(x, 3), round(y, 3), round(x + width, 3), round(y + height, 3)]
        if not any(_intersects(rect, other) for other in occupied):
            occupied.append(rect)
            return rect
    raise RuntimeError("no non-overlapping strict caption region available")


def _readable(region: dict) -> bool:
    return bool(re.search(r"[A-Za-z]", str(region.get("source_text") or ""))) and float(region.get("ocr_confidence") or 0) >= 0.60


def main() -> None:
    build_r11()
    plan = json.loads(R11_PLAN.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))["regions"]
    regions = {str(item["region_id"]): item for item in ocr}
    blocks = plan["semantic_blocks"]
    for block in blocks:
        replacement = GENERIC_REPLACEMENTS.get(str(block["block_id"]))
        if replacement:
            block["translated_text"] = replacement
            block["placement"]["render_text"] = replacement
        override = FINAL_TARGET_OVERRIDES.get(str(block["block_id"]))
        if override:
            block["placement"]["selected_region"] = override

    occupied: dict[int, list[list[float]]] = {index: [] for index in range(4)}
    for block in blocks:
        rect = list((block.get("placement") or {}).get("selected_region") or [])
        if len(rect) == 4:
            occupied[int(block["page_index"])].append([float(value) for value in rect])
    for region_id, translation in MISSING.items():
        region = regions[region_id]
        page_index = int(region["page_index"])
        bbox = [float(value) for value in region["bbox"]]
        target = _target_for(bbox, translation, occupied[page_index])
        blocks.append({
            "block_id": f"r12-mandatory-{region_id}",
            "member_ids": [region_id], "page_index": page_index,
            "coverage_status": "translated", "source_text": str(region["source_text"]),
            "translated_text": translation, "source_bbox": bbox,
            "layout_role": "mandatory_parameter_callout",
            "placement": {
                "side": "below", "mode": "inline", "selected_region": target,
                "candidate_regions": [], "font_size": 2.8, "rotation": 0,
                "leader_path": [], "render_text": translation, "color": [0.09, 0.27, 0.72],
                "preserve_source": True, "allow_source_overlap": True,
                "allow_dense_source_overlap": True, "multimodal_visual_whitespace_override": True,
                "instruction": "R12 exact parameter-complete Chinese caption; no executor fallback, movement, or font reduction.",
            },
        })
        for item in plan["coverage_inventory"]:
            if item.get("candidate_id") == region_id:
                item.update({"status": "translated", "reason": "R12 mandatory parameter-specific caption"})

    for block in blocks:
        override = FINAL_TARGET_OVERRIDES.get(str(block["block_id"]))
        if override:
            block["placement"]["selected_region"] = override

    member_to_block = {member: str(block["block_id"]) for block in blocks for member in block.get("member_ids", [])}
    audit: list[dict] = []
    for page_index in range(4):
        for zone_type, pattern in ZONES.items():
            members = [
                str(region["region_id"])
                for region in ocr
                if int(region.get("page_index", -1)) == page_index and _readable(region)
                and re.search(pattern, str(region.get("source_text") or ""), re.I)
            ]
            if members:
                missing = [member for member in members if member not in member_to_block]
                if missing:
                    raise RuntimeError(f"R12 zone {page_index + 1}/{zone_type} still has unbound members: {missing}")
                audit.append({
                    "zone_id": f"p{page_index + 1:03d}-{zone_type}", "zone_type": zone_type,
                    "page_index": page_index, "status": "complete", "member_ids": members,
                    "block_ids": sorted({member_to_block[member] for member in members}),
                    "verification": "R12 source-member binding plus parameter-specific Chinese review",
                })
    plan["mandatory_zone_audit"] = audit
    plan["r12_body_rebuild"] = {"new_parameter_blocks": len(MISSING), "generic_replacements": len(GENERIC_REPLACEMENTS), "mandatory_zones": len(audit)}
    OUTPUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(OUTPUT_PLAN), **plan["r12_body_rebuild"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
