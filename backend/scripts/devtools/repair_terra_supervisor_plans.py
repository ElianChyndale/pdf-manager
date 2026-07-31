# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
"""Targeted repair-1 mutations for the three Terra High trial plans."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend" / "scripts"))
from services.engineering_drawing.multimodal_plan import validate_multimodal_plan

ROOT = REPO / "output" / "pdf" / "engineering-drawing" / "01_Bilingual_Inline" / "agent-artifacts" / "terra-supervisor-plans"


def load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def block(plan: dict, block_id: str) -> dict:
    return next(value for value in plan["semantic_blocks"] if value["block_id"] == block_id)


def inventory(plan: dict, block_id: str, bbox: list[float]) -> None:
    block(plan, block_id)["source_bbox"] = bbox
    next(value for value in plan["coverage_inventory"] if value["candidate_id"] == block_id)["source_bbox"] = bbox


def narrow_mask(plan: dict, block_id: str, source: list[float], target: list[float]) -> None:
    value = block(plan, block_id)
    inventory(plan, block_id, source)
    place = value["placement"]
    place["selected_region"] = target
    place["exact_ink_masks"] = [source]
    for run in place.get("render_runs") or []:
        run["bbox"] = target


def main() -> None:
    output = ROOT / "repair-1"
    output.mkdir(parents=True, exist_ok=True)

    # Coordinates are visual display coordinates. Every table row is now an
    # independently bounded glyph mask, with the grid, item number and drawing
    # number columns explicitly outside every mask.
    index = load("01-a1-drawing-index.supervisor-plan.json")
    index.update({"status": "repair", "agent_plan_status": "approved", "coordinate_space": "display_page_rect"})
    index["audit"]["repair_pass"] = "repair-1: visual line masks only; no grid/number/code column mask"
    narrow = {
        "idx-title": ([430, 520, 1260, 585], [430, 520, 1260, 585]),
        "idx-project": ([160, 633, 1511, 710], [160, 633, 1511, 710]),
        "idx-list": ([420, 800, 1260, 910], [420, 800, 1260, 910]),
        "idx-table-header": ([170, 970, 1510, 1050], [170, 970, 1510, 1050]),
        "idx-site-section": ([190, 1070, 410, 1108], [190, 1070, 410, 1108]),
        "idx-site-row": ([190, 1112, 930, 1146], [190, 1112, 930, 1146]),
        "idx-masjid-section": ([190, 1160, 360, 1198], [190, 1160, 360, 1198]),
        "idx-masjid-rows": ([190, 1202, 1010, 1388], [190, 1202, 1010, 1388]),
        "idx-office-section": ([190, 1400, 520, 1440], [190, 1400, 520, 1440]),
        "idx-office-rows": ([190, 1448, 1010, 1532], [190, 1448, 1010, 1532]),
        "idx-ancillary-section": ([190, 1540, 520, 1580], [190, 1540, 520, 1580]),
        "idx-ancillary-row": ([190, 1585, 1030, 1632], [190, 1585, 1030, 1632]),
    }
    for key, (source, target) in narrow.items():
        narrow_mask(index, key, source, target)
    index["supervisor_plan"]["placement_policy"]["directory_masks"] = "one line or one ruled title cell only; never include grid, item number, drawing number or size columns"

    # The right rail is logo-bearing. Replace only project text and the lower
    # drawing-title list. Other role/company text remains source-preserving in
    # this targeted repair, not a broad white reflow experiment.
    site = load("02-masjid-site-plan.supervisor-plan.json")
    site.update({"status": "repair", "agent_plan_status": "approved", "coordinate_space": "display_page_rect"})
    site["audit"]["logo_protection_boxes"] = [
        [2080, 42, 2360, 145], [2080, 166, 2360, 250], [2080, 575, 2360, 665],
        [2080, 785, 2360, 875], [2080, 880, 2360, 970], [2080, 980, 2360, 1168],
        [2080, 1178, 2360, 1270], [2080, 1280, 2360, 1370],
    ]
    project = block(site, "site-project")
    project["source_text"] = "CADANGAN MEROBOH DAN MEMBINA SEMULA MASJID\nAL-EHSAN KAMPUNG TOK MUDA, KAPAR, DAERAH\nKLANG, SELANGOR DARUL EHSAN"
    project["translated_text"] = "拆除并重建雪兰莪州巴生县加帛托慕达村阿尔艾赫桑清真寺"
    project["placement"]["exact_ink_masks"] = [[2089, 371, 2324, 381], [2089, 382, 2306, 391], [2089, 392, 2236, 402]]
    project["placement"]["selected_region"] = [2087, 356, 2330, 405]
    project["placement"]["render_runs"][0]["bbox"] = [2087, 356, 2330, 379]
    project["placement"]["render_runs"][1]["bbox"] = [2087, 379, 2330, 405]
    inventory(site, "site-project", [2089, 371, 2324, 402])
    fields = block(site, "site-title-fields")
    fields["source_text"] = "- PELAN KUNCI\n- PELAN LOKASI\n- PELAN TAPAK"
    fields["translated_text"] = "- 位置图\n- 区位图\n- 场地总图"
    fields["placement"]["exact_ink_masks"] = [[2093, 1467, 2187, 1480], [2093, 1482, 2193, 1496], [2093, 1497, 2187, 1511]]
    fields["placement"]["selected_region"] = [2088, 1455, 2330, 1514]
    fields["placement"]["render_runs"][0]["bbox"] = [2088, 1455, 2330, 1483]
    fields["placement"]["render_runs"][1]["bbox"] = [2088, 1483, 2330, 1514]
    inventory(site, "site-title-fields", [2093, 1467, 2193, 1511])
    roles = block(site, "site-owner-role")
    roles["page_region_id"] = "site-engineering-body"
    roles["placement"].update({"mode": "leader", "side": "left", "preserve_source": True, "color": [0.05, 0.16, 0.45], "render_text": roles["translated_text"], "selected_region": [1840, 1160, 2040, 1210], "exact_ink_masks": [], "render_runs": [], "leader_path": [[2080, 1160], [2040, 1185]]})
    site["mandatory_zone_audit"] = [zone for zone in site["mandatory_zone_audit"] if zone["zone_id"] != "site-right-metadata"]
    site["mandatory_zone_audit"].append({"zone_id": "site-right-metadata", "zone_type": "company_contact_panel", "page_index": 0, "member_ids": ["site-project", "site-title-fields"], "block_ids": ["site-project", "site-title-fields"], "status": "complete", "decision_source": "multimodal_visual_plan"})

    # The SLD plan remains in display coordinates through validation. v3-render
    # uses page.derotation_matrix immediately before writing, so the local
    # leaders below are not interpreted in the 270-degree native coordinate
    # system. Keep only local, display-space anchors for this repair pass.
    sld = load("03-275kv-single-line.supervisor-plan.json")
    sld.update({"status": "repair", "agent_plan_status": "approved", "coordinate_space": "display_page_rect"})
    sld["audit"]["display_to_pdf_transform"] = {"page_rotation": 270, "executor": "page.derotation_matrix", "planning_space": "display_page_rect"}
    sld["audit"]["logo_protection_boxes"] = [[1950, 230, 2365, 1620]]
    # Exact display-space native anchors from the regenerated packet.
    legend = block(sld, "sld-legend-heading")
    inventory(sld, "sld-legend-heading", [867.84, 126.827, 904.827, 139.576])
    legend["placement"].update({"selected_region": [915, 122, 975, 143], "leader_path": [[904.827, 133.2], [915, 132.5]], "font_size": 4.0})
    bottom = block(sld, "sld-bottom-cables")
    inventory(sld, "sld-bottom-cables", [110.4, 1588.003, 213.693, 1598.341])
    bottom["placement"].update({"selected_region": [225, 1578, 450, 1612], "leader_path": [[213.693, 1593.2], [225, 1595]], "font_size": 3.8})
    for ident in ("sld-drawing-title", "sld-title-fields"):
        value = block(sld, ident)
        value["page_region_id"] = "sld-drawing-body"
        value["placement"].update({"mode": "leader", "side": "left", "preserve_source": True, "color": [0.05, 0.16, 0.45], "exact_ink_masks": [], "render_runs": [], "selected_region": [1840, 1480 if ident == "sld-drawing-title" else 1360, 1940, 1520 if ident == "sld-drawing-title" else 1410], "leader_path": []})
    sld["page_region_map"] = [region for region in sld["page_region_map"] if region["region_id"] != "sld-title-panel"]
    sld["mandatory_zone_audit"] = [zone for zone in sld["mandatory_zone_audit"] if zone["zone_id"] != "sld-title-panel"]
    for value in sld["semantic_blocks"]:
        if value["page_region_id"] == "sld-title-panel":
            value["page_region_id"] = "sld-drawing-body"
    for zone in sld["mandatory_zone_audit"]:
        if zone["zone_id"] == "sld-drawing-body":
            zone["member_ids"] = [value["block_id"] for value in sld["semantic_blocks"]]
            zone["block_ids"] = [value["block_id"] for value in sld["semantic_blocks"]]

    paths = [
        ("01-a1-drawing-index.repair-1.json", index, Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\03_CONSTRUCTION DWG_MASJID_11 NOV 2025\A1 WORKING DRAWING\00_LIST OF DRAWING_A1 FORMAT.pdf")),
        ("02-masjid-site-plan.repair-1.json", site, Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\03_CONSTRUCTION DWG_MASJID_11 NOV 2025\A1 WORKING DRAWING\00_Site Masjid Tok Muda_CONSTRUCTION.pdf")),
        ("03-275kv-single-line.repair-1.json", sld, Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\报审图纸\275kV MEP Construction Drawing_260610\Construction Drawing\RCJM2 CN ELEC 20260610\Constrcution Drawing PDF\1310-CN-ELEC-SCH-C001_275kV SLD.pdf")),
    ]
    for name, payload, source in paths:
        normalized = validate_multimodal_plan(payload, source_pdf_path=source)
        (output / name).write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
