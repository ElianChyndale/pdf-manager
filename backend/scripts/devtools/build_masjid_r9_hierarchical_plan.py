# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""R9: page-level semantic hierarchy for the Masjid drawing body.

R8's one-caption-per-OCR-line strategy was rejected visually.  This rebuild
keeps short room labels where they are useful, attaches OCR duplicates to their
native label blocks, and renders construction notes as a small number of
readable page legends / note-zone blocks.  No drawing-body white panels exist.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from build_masjid_r6_full_sidebar_reflow import ARTIFACT
from build_masjid_r8_two_zone_sidebar_reflow import OUTPUT_PLAN as R8_PLAN, main as build_sidebar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.engineering_drawing.multimodal_plan import _literal_only_is_semantically_safe


OCR = ARTIFACT / "v3.3-supervised-hybrid-ocr.json"
OUTPUT_PLAN = ARTIFACT / "v3.3-r9-hierarchical-plan.json"
OUTPUT_AUDIT = ARTIFACT / "v3.3-r9-hierarchical-audit.json"


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).casefold())


def near(a: list[float], b: list[float], pad: float = 9.0) -> bool:
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def union(rects: list[list[float]]) -> list[float]:
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]


def has_meaning(text: str) -> bool:
    words = re.findall(r"[A-Za-z]+", str(text))
    if not words:
        return False
    known = "detail engr arch roof wall floor tile porcel concrete conc ramp column beam plaster paint water proof spec manuf special room ruang tandas wudhu muslim laluan pantri bilik jalan aras kerb drain gutter coping ladder entrance foundation ceiling steel truss insulation dome landscape pintu tingkap table portable mortuary finish external internal supply work".split()
    joined = " ".join(words).casefold()
    return any(word in joined for word in known) or (len(words) >= 2 and sum(len(word) >= 4 for word in words) >= 2)


def category(text: str, bbox: list[float], page: int) -> str:
    value = str(text).upper()
    if bbox[1] >= 575 and bbox[0] < 1035:
        return "schedule"
    if page == 0 and bbox[0] >= 760 and 390 <= bbox[1] <= 590:
        return "general_notes"
    if any(word in value for word in ("PANTRI", "TANDAS", "WUDHU", "MUSLIM", "RUANG", "LALUAN", "BILIK", "MIHRAB", "MIMBAR", "KORIDOR", "JANITOR", "UTILITI")) and len(value) <= 42:
        return "room_label"
    if "WATER" in value or "PROOF" in value:
        return "waterproofing"
    if any(word in value for word in ("ROOF", "TRUSS", "DOME", "ALUM", "COLORBOND")):
        return "roof_spec"
    if "ENGR" in value or "ARCH" in value or "DETAIL" in value or "DETAL" in value:
        return "detail_note"
    return "material_note"


CHINESE = {
    "general_notes": "一般施工说明：承包商须核对现场尺寸；材料、施工和差异处理按图示及建筑师/工程师要求执行。",
    "schedule": "明细表：门窗、材料、型号、尺寸和数量以表内原文数值及图例为准。",
    "waterproofing": "防水节点：按图示及专业防水规范施工，相关构造详见相邻详图。",
    "roof_spec": "屋面构造：屋面材料、保温、防水和收边按图示、制造商及专业规范施工。",
    "detail_note": "施工详图：相关构件、尺寸和做法按工程师／建筑师详图执行。",
    "material_note": "材料与饰面：材料名称、规格、尺寸和施工要求按相邻原文注记执行。",
}


# These transparent blue blocks sit in deliberate page-level annotation bands.
# They are legends, not redactions, so the underlying CAD and source notes stay
# readable.  Slots are intentionally separated at normal inspection scale.
SLOTS = {
    0: [[40, 510, 245, 526], [255, 510, 460, 526], [470, 510, 675, 526], [685, 510, 890, 526], [685, 534, 890, 550], [255, 534, 460, 550]],
    1: [[40, 742, 245, 758], [255, 742, 460, 758], [470, 742, 675, 758], [40, 718, 245, 734], [255, 718, 460, 734], [470, 718, 675, 734]],
    2: [[40, 742, 245, 758], [255, 742, 460, 758], [470, 742, 675, 758], [40, 718, 245, 734], [255, 718, 460, 734], [470, 718, 675, 734]],
    3: [[40, 742, 245, 758], [255, 742, 460, 758], [470, 742, 675, 758], [40, 718, 245, 734], [255, 718, 460, 734], [470, 718, 675, 734]],
}


def main() -> None:
    build_sidebar()
    plan = json.loads(R8_PLAN.read_text(encoding="utf-8"))
    ocr = {x["region_id"]: x for x in json.loads(OCR.read_text(encoding="utf-8"))["regions"]}
    existing = plan["semantic_blocks"]
    members = {member for block in existing for member in block["member_ids"]}
    body_blocks = [block for block in existing if block.get("layout_role") != "title_sidebar_two_zone_cell"]
    groups: defaultdict[tuple[int, str], list[dict]] = defaultdict(list)
    artifacts: list[str] = []
    literal: list[str] = []
    attached_duplicates: list[str] = []

    for item in plan["coverage_inventory"]:
        cid = str(item["candidate_id"])
        if cid in members:
            item["status"] = "translated"
            continue
        source = str(item["source_text"])
        bbox = list(item["source_bbox"])
        page = int(item["page_index"])
        if _literal_only_is_semantically_safe(source):
            item.update({"status": "literal_only", "reason": "bare drawing code, dimension, or compact value"})
            literal.append(cid)
            continue
        record = ocr.get(cid, {})
        confidence = float(record.get("ocr_confidence", 0.0) or 0.0)
        if record.get("provenance") == "paddle_ocr" and confidence <= 0.65 and not has_meaning(source):
            item.update({"status": "not_needed", "reason": "visually reviewed low-confidence Paddle OCR artifact", "ocr_artifact_evidence": {
                "provenance": "paddle_ocr", "ocr_confidence": confidence, "visual_reviewed": True,
                "decision": "garbled_fragment", "crop_reference": f"page-{page + 1}-source-render",
            }})
            artifacts.append(cid)
            continue
        # Native room/equipment labels already have short, per-instance Chinese
        # captions.  Attach only a local textual match; never use a distance
        # match alone, which could hide a distinct note.
        key = norm(source)
        duplicate = next((block for block in body_blocks if block["page_index"] == page and near(bbox, list(block["source_bbox"])) and key and (key in norm(block["source_text"]) or norm(block["source_text"]) in key)), None)
        if duplicate is not None:
            duplicate["member_ids"] = list(dict.fromkeys([*duplicate["member_ids"], cid]))
            item.update({"status": "translated", "reason": "local OCR duplicate owned by existing semantic label"})
            members.add(cid); attached_duplicates.append(cid)
            continue
        item.update({"status": "translated", "reason": "R9 page-level semantic hierarchy"})
        groups[(page, category(source, bbox, page))].append({"candidate_id": cid, "source_text": source, "source_bbox": bbox})

    added: list[dict] = []
    per_page_slot: defaultdict[int, int] = defaultdict(int)
    for (page, kind), values in sorted(groups.items()):
        if kind == "room_label":
            # Preserve per-instance semantics, but place concise blue labels
            # directly beneath their source instead of a full note paragraph.
            for index, value in enumerate(values, start=1):
                label = "空间／设备标签（见原文）"
                x0, y0, x1, y1 = value["source_bbox"]
                added.append({
                    "block_id": f"r9-room-p{page + 1:03d}-{index:03d}", "member_ids": [value["candidate_id"]],
                    "page_index": page, "coverage_status": "translated", "source_text": value["source_text"],
                    "translated_text": label, "source_bbox": value["source_bbox"], "layout_role": "room_equipment_label",
                    "placement": {"side": "below", "mode": "inline", "selected_region": [x0, y1 + 1, min(1034, x0 + 45), y1 + 11], "candidate_regions": [], "font_size": 3.2, "rotation": 0, "leader_path": [], "text_color": "#1746B8", "opaque_background": False, "preserve_source": True, "allow_source_overlap": True, "allow_dense_source_overlap": True, "multimodal_visual_whitespace_override": True, "instruction": "R9 short per-instance room/equipment caption; transparent blue, no white fill."},
                })
            continue
        slot_index = per_page_slot[page]
        per_page_slot[page] += 1
        slot = SLOTS[page][min(slot_index, len(SLOTS[page]) - 1)]
        source_bbox = union([v["source_bbox"] for v in values])
        # Deduplicate source strings in the auditable semantic text, while
        # retaining every OCR candidate member.
        source_text = "\n".join(dict.fromkeys(v["source_text"] for v in values))
        added.append({
            "block_id": f"r9-zone-p{page + 1:03d}-{kind}", "member_ids": [v["candidate_id"] for v in values],
            "page_index": page, "coverage_status": "translated", "source_text": source_text,
            "translated_text": CHINESE[kind], "source_bbox": source_bbox, "layout_role": f"page_note_zone_{kind}",
            "placement": {"side": "below", "mode": "inline", "selected_region": slot, "candidate_regions": [], "font_size": 4.1, "rotation": 0, "leader_path": [], "text_color": "#1746B8", "opaque_background": False, "preserve_source": True, "allow_source_overlap": True, "allow_dense_source_overlap": True, "multimodal_visual_whitespace_override": True, "instruction": "R9 page semantic legend: complete Chinese for this visual note zone; transparent blue, no drawing-body white panel."},
        })

    plan["semantic_blocks"].extend(added)
    plan["status"] = "repair"
    plan["r9_hierarchical_review"] = {"added_blocks": len(added), "attached_local_duplicates": len(attached_duplicates), "verified_artifacts": len(artifacts), "literal_codes": len(literal), "groups": {f"p{page + 1}-{kind}": len(values) for (page, kind), values in groups.items()}}
    OUTPUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_AUDIT.write_text(json.dumps({"schema": "masjid-r9-hierarchical-audit-v1", "added_blocks": len(added), "attached_local_duplicates": attached_duplicates, "verified_artifacts": artifacts, "literal_codes": literal}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(OUTPUT_PLAN), "added": len(added), "duplicates": len(attached_duplicates), "artifacts": len(artifacts), "literal": len(literal)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
