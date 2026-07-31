# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""R11 strict V3.4: preserve sidebar source, add left Chinese companions."""

import json
from pathlib import Path

from build_masjid_r9_hierarchical_plan import OUTPUT_PLAN as R9_PLAN, main as build_r9


OUTPUT_PLAN = R9_PLAN.parent / "v3.4-r11-left-companion-strict-plan.json"
R10_AUDIT = R9_PLAN.parent / "v3.3-r10-hierarchical-candidate.inline-placement.json"

COMPANION = {
    "land-owner": "土地业主：雪兰莪伊教理事会",
    "building-owner": "建筑业主：雪兰莪宗教局",
    "project": "项目：重建 Al-Ehsan 清真寺",
    "revision": "修订记录／审核",
    "agency": "实施机构：雪兰莪公共工程局",
    "applicant": "申请人：莫哈末·阿扎哈里",
    "architect": "建筑师：AC Architects",
    "civil": "土木结构：UNITI 顾问",
    "mechanical": "机械：雪兰莪公共工程局",
    "electrical": "电气：雪兰莪公共工程局",
    "quantity": "工料测量：Azizi & Partners",
    "landscape": "景观：Laman TBG",
    "notes": "版权及施工说明",
    "status": "图纸状态：施工",
    "title": "清真寺施工图",
    "metadata": "比例、日期与图号见原文",
}

CELL_Y = {
    "land-owner": (78, 88), "building-owner": (130, 140), "project": (181, 203),
    "revision": (242, 252), "agency": (282, 294), "applicant": (353, 367),
    "architect": (401, 412), "civil": (452, 463), "mechanical": (501, 512),
    "electrical": (551, 562), "quantity": (601, 612), "landscape": (650, 661),
    "notes": (684, 696), "status": (705, 718), "title": (731, 753), "metadata": (775, 801),
}

# These are manually checked V3.4 targets for the few legacy R10 captions that
# either had no accepted R10 target or share a former sidebar-adjacent slot.
# They are fixed coordinates, not executor fallbacks.
EXACT_OVERRIDES = {
    "postocr-0055-p001-native-0095": ([228.0, 330.0, 263.0, 341.0], 2.8),
    "postocr-0074-p001-native-0115": ([621.0, 108.0, 657.0, 120.0], 2.8),
    "postocr-0102-p001-native-0144": ([928.0, 650.0, 962.0, 664.0], 2.8),
    "postocr-0120-p002-native-0063": ([1000.0, 313.0, 1034.0, 328.0], 2.8),
    "postocr-0122-p002-native-0065": ([920.0, 341.0, 960.0, 354.0], 2.8),
    "postocr-0123-p002-native-0066": ([1000.0, 451.0, 1034.0, 465.0], 2.8),
    "r9-room-p003-004": ([950.0, 500.0, 1034.0, 518.0], 2.8),
    "postocr-0215-p004-native-0048": ([273.0, 225.0, 303.0, 235.0], 2.8),
    "postocr-0229-p004-native-0063": ([730.0, 468.0, 760.0, 478.0], 2.8),
}

COMPANION_OVERRIDES = {
    # The immediate strip is occupied by an approved adjacent body caption in
    # these two cells.  The nearest clear band is immediately to its left.
    "title": [895.0, 731.0, 963.0, 753.0],
    "mechanical": [895.0, 501.0, 963.0, 512.0],
}


def companion_rect(key: str) -> list[float]:
    if key in COMPANION_OVERRIDES:
        return COMPANION_OVERRIDES[key]
    y0, y1 = CELL_Y[key]
    # The 68pt strip immediately left of the sidebar is the closest available
    # annotation band.  It may cross minor linework but is clear of primary
    # plan geometry; no source/sidebar ink is touched.
    return [966.0, float(y0), 1034.0, float(y1)]


def main() -> None:
    build_r9()
    plan = json.loads(R9_PLAN.read_text(encoding="utf-8"))
    r10_targets = {
        str(item.get("region_id")): item
        for item in json.loads(R10_AUDIT.read_text(encoding="utf-8")).get("placements", [])
        if str(item.get("status")) not in {"rejected_v3_declared_target_collision", "rejected_text_did_not_fit"}
        and isinstance(item.get("target_bbox"), list) and len(item["target_bbox"]) == 4
    }
    plan["execution_policy"] = "strict_multimodal_execution"
    plan.pop("panel_reflow_spec", None)
    for block in plan["semantic_blocks"]:
        placement = dict(block.get("placement") or {})
        block_id = str(block["block_id"])
        if block_id.startswith("r8-sidebar-"):
            key = "-".join(block_id.split("-")[3:])
            block["translated_text"] = COMPANION[key]
            placement.update({
                "side": "left", "mode": "inline", "selected_region": companion_rect(key),
                "candidate_regions": [], "font_size": 3.0 if key not in {"project", "title", "metadata"} else 2.8,
                "rotation": 0, "leader_path": [], "render_text": COMPANION[key],
                "color": [0.0, 0.0, 0.0], "preserve_source": True,
                "allow_source_overlap": True, "allow_dense_source_overlap": True,
                "multimodal_visual_whitespace_override": True,
                "panel_reflow_managed": False, "panel_reflow_panel_id": "", "panel_reflow_field_id": "",
                "panel_reflow_target_bbox": [],
                "instruction": "R11 exact Chinese companion immediately left of intact source sidebar; no source mask or white fill.",
            })
        else:
            prior = r10_targets.get(block_id)
            if prior is not None:
                target = [float(value) for value in prior["target_bbox"]]
                placement["selected_region"] = target
                placement["font_size"] = 2.8 if target[3] - target[1] < 8.0 else min(3.4, float(placement.get("font_size") or 3.4))
            if block_id in EXACT_OVERRIDES:
                target, font_size = EXACT_OVERRIDES[block_id]
                placement["selected_region"] = target
                placement["font_size"] = font_size
            placement.update({
                "candidate_regions": [], "render_text": str(block.get("translated_text") or ""),
                "color": [0.09, 0.27, 0.72], "preserve_source": True,
                "allow_source_overlap": True, "allow_dense_source_overlap": True,
                "multimodal_visual_whitespace_override": True,
                "panel_reflow_managed": False, "panel_reflow_panel_id": "", "panel_reflow_field_id": "",
                "panel_reflow_target_bbox": [],
            })
            # Strict V3.4 never uses opaque fallback for sidebar/table source;
            # the source remains visible and the approved caption is exact.
            if placement.get("mode") in {"title_block", "table_cell"}:
                placement["mode"] = "inline"
        block["placement"] = placement
    OUTPUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(OUTPUT_PLAN), "blocks": len(plan["semantic_blocks"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
