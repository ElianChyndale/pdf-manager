# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
"""Write Terra High's reviewed three-page engineering-drawing handoff plans.

The coordinates in this file were authored from the source-page renders.  Native
text/OCR is deliberately used only as an execution anchor and exact-mask aid;
it is not used to infer page regions or the selected caption locations.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend" / "scripts"))

from services.engineering_drawing.multimodal_plan import validate_multimodal_plan


ARTIFACT_ROOT = REPO / "output" / "pdf" / "engineering-drawing" / "01_Bilingual_Inline" / "agent-artifacts"
OUTPUT = ARTIFACT_ROOT / "terra-supervisor-plans"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def item(
    ident: str,
    source: str,
    chinese: str,
    bbox: list[float],
    target: list[float],
    region: str,
    *,
    mode: str = "inline",
    side: str = "below",
    font: float = 4.2,
    preserve: bool = True,
    opaque: bool = False,
    role: str = "label",
) -> dict[str, Any]:
    coverage = {
        "candidate_id": ident,
        "page_index": 0,
        "source_text": source,
        "source_bbox": bbox,
        "status": "translated",
        "inspection_basis": "Terra High rendered-page visual review; OCR only anchors execution",
    }
    placement: dict[str, Any] = {
        "side": side,
        "mode": mode,
        "selected_region": target,
        "candidate_regions": [],
        "font_size": font,
        "rotation": 0,
        "preserve_source": preserve,
        "render_text": chinese,
        "color": [0.05, 0.16, 0.45] if preserve else [0.0, 0.0, 0.0],
        "decision_source": "multimodal_visual_plan",
        "leader_allowed_when_local_space_exhausted": mode == "leader",
        "multimodal_visual_whitespace_override": True,
    }
    if mode == "leader":
        placement["leader_path"] = [[bbox[2], (bbox[1] + bbox[3]) / 2], [target[0], (target[1] + target[3]) / 2]]
    if opaque:
        if region == "index-table":
            runs = [
                {
                    "text": chinese,
                    "bbox": target,
                    "font_size": font,
                    "font_name": "simhei",
                    "color": [0.0, 0.0, 0.0],
                    "rotation": 0,
                }
            ]
        else:
            split = target[1] + (target[3] - target[1]) * 0.48
            runs = [
                {
                    "text": source,
                    "bbox": [target[0], target[1], target[2], split],
                    "font_size": max(1.8, font * 0.82),
                    "font_name": "helv",
                    "color": [0.0, 0.0, 0.0],
                    "rotation": 0,
                },
                {
                    "text": chinese,
                    "bbox": [target[0], split, target[2], target[3]],
                    "font_size": font,
                    "font_name": "simhei",
                    "color": [0.0, 0.0, 0.0],
                    "rotation": 0,
                },
            ]
        placement.update(
            {
                "preserve_source": False,
                "exact_ink_masks": [bbox],
                "render_runs": runs,
            }
        )
    return {
        "coverage": coverage,
        "block": {
            "block_id": ident,
            "member_ids": [ident],
            "page_index": 0,
            "page_region_id": region,
            "source_text": source,
            "source_bbox": bbox,
            "translated_text": chinese,
            "coverage_status": "translated",
            "decision_source": "multimodal_visual_plan",
            "layout_role": role,
            "typography": {"semantic_role": role, "bold": role in {"heading", "section_heading", "table_header"}},
            "placement": placement,
        },
    }


def plan(
    *,
    source: Path,
    page_type: str,
    delivery_mode: str,
    regions: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    ocr_regions: list[dict[str, Any]],
    review: str,
) -> dict[str, Any]:
    blocks = [entry["block"] for entry in entries]
    return {
        "schema": "engineering-drawing-multimodal-plan-v3",
        "status": "approved",
        "agent_plan_status": "approved",
        "agent_name": "engineering-drawing-translator",
        "supervisor_count": 1,
        "parallel_supervisors": False,
        "model_name": "gpt-5.6-terra",
        "model_provider": "openai-codex",
        "reasoning_profile": "high",
        "supervisor_adapter": "terra-high",
        "model_capabilities": [
            "multimodal_page_planning",
            "ocr_task_supervision",
            "semantic_translation_planning",
            "translation_placement_planning",
            "visual_release_review",
        ],
        "multimodal_page_planning": True,
        "execution_policy": "strict_multimodal_execution",
        "visual_planning_authority": {
            "authority": "multimodal_model",
            "sequence": "visual_design_before_ocr_execution",
            "ocr_role": "extraction_and_mask_execution_only",
            "placement_basis": "rendered_page_visual",
        },
        "render_provenance": {
            "base": "original_source_pdf",
            "source_sha256": sha256(source),
            "reference_usage": "translation_evidence_only",
            "copied_reference_page_or_region": False,
        },
        "page_type": page_type,
        "delivery_mode": delivery_mode,
        "page_region_map": regions,
        "existing_translation_inventory": [],
        "coverage_inventory": [entry["coverage"] for entry in entries],
        "semantic_blocks": blocks,
        "mandatory_zone_audit": [
            {
                "zone_id": region["region_id"],
                "zone_type": region["region_type"],
                "page_index": 0,
                "member_ids": [block["block_id"] for block in blocks if block["page_region_id"] == region["region_id"]],
                "block_ids": [block["block_id"] for block in blocks if block["page_region_id"] == region["region_id"]],
                "status": "complete",
                "decision_source": "multimodal_visual_plan",
            }
            for region in regions
        ],
        "supervisor_plan": {
            "contract_version": "v3-supervisor-plan-1",
            "role": "multimodal_page_manager",
            "status": "approved",
            "page_type": page_type,
            "delivery_mode": delivery_mode,
            "model_name": "gpt-5.6-terra",
            "reasoning_profile": "high",
            "ocr_tasks": ocr_regions,
            "translation_tasks": [
                {"id": f"translate-{block['block_id']}", "semantic_block": block["block_id"], "source_candidate_ids": block["member_ids"]}
                for block in blocks
            ],
            "placement_policy": {
                "authority": "Terra High page-image review",
                "target_selection": "selected_region is final; no executor fallback",
                "drawing_body": "blue, preserve source, nearby visual whitespace, short leader only when declared",
                "information_panels": "exact source-glyph masks only; preserve borders, rules and logo protection boxes",
                "leader": {"color": "dark_blue", "width_points": 0.32, "arrow": False, "route": "shortest_direct"},
            },
            "escalations": [],
            "audit_note": review,
        },
        "audit": {
            "visual_review_method": "full-page source PNG reviewed before packet text; high-density zones visually checked at source resolution",
            "ocr_usage": "supervisor-declared crop execution and source-anchor confirmation only",
            "reference_pdf_usage": "not rendered or copied; translation evidence only",
        },
    }


def region(region_id: str, region_type: str, bbox: list[float]) -> dict[str, Any]:
    strategy = {
        "drawing_body": "blue_preserve_source",
        "drawing_table": "blue_preserve_source",
        "directory_index": "black_chinese_replacement",
        "company_contact_panel": "black_bilingual_text_reflow",
        "state_bearing_metadata": "blue_preserve_source",
    }[region_type]
    return {
        "region_id": region_id,
        "region_type": region_type,
        "page_index": 0,
        "bbox": bbox,
        "strategy": strategy,
        "decision_source": "multimodal_visual_plan",
    }


def write(name: str, payload: dict[str, Any], source: Path, review: str) -> None:
    normalized = validate_multimodal_plan(payload, source_pdf_path=source)
    (OUTPUT / f"{name}.supervisor-plan.json").write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / f"{name}.visual-review.md").write_text(review + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    index_source = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\03_CONSTRUCTION DWG_MASJID_11 NOV 2025\A1 WORKING DRAWING\00_LIST OF DRAWING_A1 FORMAT.pdf")
    index_regions = [region("index-table", "directory_index", [40, 40, 1644, 2340])]
    index_entries = [
        item("idx-title", "CONSTRUCTION DRAWING", "施工图纸", [430, 520, 1260, 585], [430, 520, 1260, 585], "index-table", mode="table_cell", side="right", font=10, preserve=False, opaque=True, role="heading"),
        item("idx-project", "CADANGAN MEROBOH DAN MEMBINA SEMULA MASJID AL-EHSAN KAMPUNG TOK MUDA, KAPAR, DAERAH KLANG, SELANGOR DARUL EHSAN", "拆除并重建雪兰莪州巴生县加帛托慕达村阿尔艾赫桑清真寺", [160, 633, 1511, 710], [160, 633, 1511, 710], "index-table", mode="table_cell", side="below", font=7.2, preserve=False, opaque=True, role="heading"),
        item("idx-list", "LIST OF ARCHITECTURAL DRAWINGS / WORKING DRAWING", "建筑施工图纸目录", [420, 800, 1260, 910], [420, 800, 1260, 910], "index-table", mode="table_cell", side="below", font=9, preserve=False, opaque=True, role="heading"),
        item("idx-table-header", "LUKISAN KERJA / NO. / TAJUK / NO. DRAWING / SIZE", "施工图 / 序号 / 图名 / 图号 / 图幅", [160, 965, 1510, 1065], [160, 965, 1510, 1065], "index-table", mode="table_cell", side="below", font=7, preserve=False, opaque=True, role="table_header"),
        item("idx-site-section", "PELAN TAPAK", "场地总图", [273, 1070, 455, 1105], [273, 1070, 455, 1105], "index-table", mode="table_cell", side="right", font=6.2, preserve=False, opaque=True, role="section_heading"),
        item("idx-site-row", "PELAN KUNCI, PELAN LOKASI, & PELAN TAPAK", "位置图、区位图及场地总图", [275, 1110, 1080, 1145], [275, 1110, 1080, 1145], "index-table", mode="table_cell", side="right", font=5.2, preserve=False, opaque=True),
        item("idx-masjid-section", "MASJID", "清真寺", [273, 1162, 376, 1197], [273, 1162, 376, 1197], "index-table", mode="table_cell", side="right", font=6.2, preserve=False, opaque=True, role="section_heading"),
        item("idx-masjid-rows", "PELAN TINGKAT BAWAH; PELAN BUMBUNG 1, PELAN MENARA 1 & 2, PELAN BUMBUNG KESELURUHAN; PANDANGAN HADAPAN, BELAKANG, SISI KANAN & KIRI; KERATAN A-A, B-B, C-C, D-D, & E-E", "首层平面图；屋面图1、宣礼塔图1及2、总体屋面图；前立面、后立面、右立面及左立面；A-A、B-B、C-C、D-D及E-E剖面图", [275, 1200, 1080, 1390], [275, 1200, 1080, 1390], "index-table", mode="table_cell", side="right", font=4.4, preserve=False, opaque=True),
        item("idx-office-section", "BANGUNAN PEJABAT", "办公楼", [273, 1400, 540, 1438], [273, 1400, 540, 1438], "index-table", mode="table_cell", side="right", font=6, preserve=False, opaque=True, role="section_heading"),
        item("idx-office-rows", "PELAN TINGKAT BAWAH & PELAN BUMBUNG; PANDANGAN HADAPAN, SISI KANAN, BELAKANG, SISI KIRI, KERATAN X-X & Y-Y", "首层平面及屋面图；前立面、右立面、后立面、左立面及X-X、Y-Y剖面", [275, 1445, 1080, 1530], [275, 1445, 1080, 1530], "index-table", mode="table_cell", side="right", font=4.8, preserve=False, opaque=True),
        item("idx-ancillary-section", "ANCILLARY", "附属建筑", [273, 1540, 540, 1578], [273, 1540, 540, 1578], "index-table", mode="table_cell", side="right", font=6, preserve=False, opaque=True, role="section_heading"),
        item("idx-ancillary-row", "KEBUK SAMPAH, BILIK PAM, BILIK TANGKI SEDUTAN, & PENCAWANG TNB SUB-PADAT", "垃圾房、泵房、吸水池间及国能紧凑型变电站", [275, 1585, 1080, 1630], [275, 1585, 1080, 1630], "index-table", mode="table_cell", side="right", font=4.8, preserve=False, opaque=True),
    ]
    index_review = """# Terra High whole-page visual review\n\nSource render reviewed: A1 drawing-list page. The page is a sparse cover and ruled directory table, not a drawing body. Visual region map: page border and construction stamp protected; all table rules, sequence numbers, drawing numbers and A1 size values are immutable. The title band and every title column cell are `directory_index`, so only exact source glyph envelopes may be masked and replacement Chinese is black. OCR is tasked only to confirm those glyph envelopes; it cannot select a target or reclassify rows. The plan inventories every visible heading, section heading and row-description group while preserving every code/number column.\n"""
    write("01-a1-drawing-index", plan(source=index_source, page_type="dense_drawing_index", delivery_mode="opaque_bilingual_reflow", regions=index_regions, entries=index_entries, ocr_regions=[{"id": "index-title-and-table", "region_norm": [0.06, 0.20, 0.88, 0.70], "engine": "technical_cad_ocr", "purpose": "confirm source glyph masks for the visually approved table cells"}], review=index_review), index_source, index_review)

    site_source = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\03_CONSTRUCTION DWG_MASJID_11 NOV 2025\A1 WORKING DRAWING\00_Site Masjid Tok Muda_CONSTRUCTION.pdf")
    site_regions = [region("site-left-information", "drawing_table", [40, 40, 780, 1640]), region("site-engineering-body", "drawing_body", [780, 40, 2075, 1640]), region("site-right-metadata", "company_contact_panel", [2075, 40, 2365, 1640])]
    site_entries = [
        item("site-key-location", "PELAN KUNCI / PELAN LOKASI / TAPAK CADANGAN", "位置图 / 区位图 / 拟建场地", [80, 380, 490, 870], [500, 390, 720, 440], "site-left-information", mode="leader", side="right", font=4.4),
        item("site-land-area", "KELUASAN TANAH PEMBANGUNAN / MAKLUMAT LOT / LUAS", "建设用地面积 / 地块资料 / 面积", [80, 900, 730, 1040], [90, 1040, 730, 1075], "site-left-information", font=4.4),
        item("site-land-use", "KEGUNAAN KAWASAN / BANGUNAN / KAWASAN LAPANG / HIJAU / HARDSCAPE", "用地用途 / 建筑 / 开放及绿化区 / 硬质景观", [80, 1080, 730, 1225], [90, 1228, 730, 1265], "site-left-information", font=4.2),
        item("site-legend", "PETUNJUK / MASJID / BANGUNAN PEJABAT / TEMPAT LETAK MOTOSIKAL / GAZEBO", "图例 / 清真寺 / 办公楼 / 摩托车停车位 / 凉亭", [600, 920, 780, 1160], [780, 920, 1005, 960], "site-left-information", mode="leader", side="right", font=4.1),
        item("site-budget-parking", "PENGIRAAN ANGGARAN PENJANAAN SISA PEPEJAL / TEMPAT LETAK KENDERAAN MENGIKUT KEPERLUAN PBT", "固体废弃物产生量估算 / 按地方政府要求配置的停车位", [60, 1265, 780, 1590], [790, 1450, 1040, 1490], "site-left-information", mode="leader", side="right", font=3.8),
        item("site-plan-title", "PELAN TAPAK / SKALA 1 : 600", "场地总图 / 比例 1:600", [1430, 1510, 1680, 1595], [1690, 1515, 1920, 1550], "site-engineering-body", mode="leader", side="right", font=5.0, role="heading"),
        item("site-roads", "CADANGAN LALUAN SEHALA (6100MM LEBAR) / CADANGAN LALUAN DUA HALA (7400MM LEBAR)", "拟建单行车道（宽6100毫米）/ 拟建双向车道（宽7400毫米）", [1180, 1100, 1745, 1335], [1760, 1120, 2020, 1170], "site-engineering-body", mode="leader", side="right", font=3.8),
        item("site-main-callouts", "EXISTING FIRE HYDRANT TO BE MAKE GOOD WHERE NECESSARY / PROPOSED FIRE HYDRANT / COVERED CARPARK / COVERED WALKWAY", "现有消防栓按需要修复 / 拟设消防栓 / 有盖停车场 / 有盖步道", [1690, 140, 2050, 760], [1755, 760, 2045, 820], "site-engineering-body", mode="leader", side="below", font=3.8),
        item("site-fencing-notes", "1700MM(H) DECORATIVE GATE POST TO DETAIL FINISHED WITH WEATHERPROOF PAINT / G.I. PERIMETER FENCING", "1700毫米高装饰门柱，按详图并涂耐候漆 / 镀锌周界围栏", [800, 120, 1160, 370], [800, 380, 1110, 425], "site-engineering-body", mode="leader", side="below", font=3.8),
        item("site-project", "CADANGAN MEROBOH DAN MEMBINA SEMULA MASJID AL-EHSAN KAMPUNG TOK MUDA, KAPAR, DAERAH KLANG, SELANGOR DARUL EHSAN", "拆除并重建雪兰莪州巴生县加帛托慕达村阿尔艾赫桑清真寺", [2085, 360, 2330, 410], [2085, 360, 2330, 410], "site-right-metadata", mode="title_block", side="below", font=4.0, preserve=False, opaque=True, role="heading"),
        item("site-title-fields", "DRAWING STATUS / DRAWING TITLE / NO. LUKISAN / SCALE / DATE / DRAWN / CHECKED", "图纸状态 / 图纸名称 / 图号 / 比例 / 日期 / 绘制 / 审核", [2080, 1370, 2340, 1635], [2080, 1370, 2340, 1635], "site-right-metadata", mode="title_block", side="below", font=3.2, preserve=False, opaque=True, role="table_header"),
        item("site-owner-role", "PEMILIK TANAH / PEMILIK BANGUNAN / AGENSI PELAKSANA / ARKITEK / JURUTERA STRUKTUR / JURUTERA MEKANIKAL / JURUTERA ELEKTRIK", "土地业主 / 建筑业主 / 执行机构 / 建筑师 / 结构工程师 / 机械工程师 / 电气工程师", [2080, 150, 2345, 1330], [2080, 150, 2345, 1330], "site-right-metadata", mode="title_block", side="below", font=2.8, preserve=False, opaque=True),
    ]
    site_review = """# Terra High whole-page visual review\n\nSource render reviewed: A1 Masjid site plan. Visual region map was made before reading packet text: left map/table column is a drawing-table zone; the diagonal site plan and its notes form a single engineering-body zone; the right rail is a logo-bearing company/title panel. Logos, seals, pink construction stamp, boundaries, road geometry, hatching, dimensions and every table rule are protected. Body captions are blue, preserve the source, and use only the visually selected adjacent white bands with short direct leaders. Right rail reflow is limited to declared ordinary text glyph masks; no mask can enter a visible logo or rule line. OCR tasks cover the three visual zones only after this decision, including micro-note confirmation.\n"""
    write("02-masjid-site-plan", plan(source=site_source, page_type="architectural_site_plan", delivery_mode="inline_bilingual", regions=site_regions, entries=site_entries, ocr_regions=[{"id": "site-left-tables", "region_norm": [0.02, 0.02, 0.33, 0.98], "engine": "technical_cad_ocr", "purpose": "confirm source anchors in visually approved left map/table zones"}, {"id": "site-plan-micro-notes", "region_norm": [0.33, 0.02, 0.87, 0.98], "engine": "technical_cad_ocr", "purpose": "high-resolution execution only for supervisor-inventoried plan notes"}, {"id": "site-right-panel", "region_norm": [0.87, 0.02, 0.99, 0.98], "engine": "technical_cad_ocr", "purpose": "confirm exact ordinary-text masks; exclude all logos"}], review=site_review), site_source, site_review)

    electrical_source = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\报审图纸\275kV MEP Construction Drawing_260610\Construction Drawing\RCJM2 CN ELEC 20260610\Constrcution Drawing PDF\1310-CN-ELEC-SCH-C001_275kV SLD.pdf")
    electrical_regions = [region("sld-drawing-body", "drawing_body", [20, 20, 1950, 1660]), region("sld-title-panel", "company_contact_panel", [1950, 20, 2365, 1660])]
    electrical_entries = [
        item("sld-legend-heading", "LEGEND", "图例", [870, 100, 980, 135], [990, 100, 1060, 130], "sld-drawing-body", mode="leader", side="right", font=4.5, role="heading"),
        item("sld-protection-list", "MAIN 1 / MAIN 2 INTEGRATED LINE DIFFERENTIAL PROTECTION INCOMER; DIRECTIONAL OVERCURRENT PROTECTION; TRANSFORMER BIAS DIFFERENTIAL PROTECTION; RESTRICTED EARTH FAULT PROTECTION (HV/LV SIDE); STANDBY EARTH FAULT PROTECTION; INSTANTANEOUS/TIME-DELAY OVERCURRENT/EARTH FAULT PROTECTION; BACKUP DISTANCE PROTECTION; MAIN BUSBAR LOW IMPEDANCE PROTECTION; SYNCHECK RELAY", "主1/主2进线综合线路差动保护；方向过流保护；变压器偏置差动保护；高压/低压侧限制接地故障保护；后备接地故障保护；瞬时/延时过流及接地故障保护；后备距离保护；主母线低阻抗保护；同期检查继电器", [870, 110, 1260, 380], [1280, 115, 1570, 210], "sld-drawing-body", mode="leader", side="right", font=3.4),
        item("sld-incomer-left", "TNB INCOMER 1 (275KV) / INDUCTIVE VOLTAGE TRANSFORMER / CABLE LAID IN TRENCH", "国能进线1（275千伏）/ 感应式电压互感器 / 电缆敷设于电缆沟内", [80, 80, 390, 390], [400, 100, 620, 145], "sld-drawing-body", mode="leader", side="right", font=3.8),
        item("sld-incomer-right", "TNB INCOMER 2 (275KV) / INDUCTIVE VOLTAGE TRANSFORMER / CABLE LAID IN TRENCH", "国能进线2（275千伏）/ 感应式电压互感器 / 电缆敷设于电缆沟内", [1610, 80, 1935, 390], [1630, 400, 1900, 445], "sld-drawing-body", mode="leader", side="below", font=3.8),
        item("sld-meters", "TNB METER (FUTURE) / TNB MAIN METER / TNB CHECK METER", "国能电表（预留）/ 国能主电表 / 国能校验电表", [720, 170, 1130, 330], [720, 340, 980, 385], "sld-drawing-body", mode="leader", side="below", font=3.7),
        item("sld-bus-section", "275KV MAIN BUSBAR 1 / BUS SECTION / BUSBAR 2", "275千伏主母线1 / 母线分段 / 母线2", [760, 650, 1620, 970], [980, 800, 1170, 840], "sld-drawing-body", mode="leader", side="above", font=3.8),
        item("sld-bays", "FUTURE PHASE BAY A1, A2, A3, A4, B1, B2, B3, B4 / TO 11KV SWITCHGEAR", "预留期相间隔A1、A2、A3、A4、B1、B2、B3、B4 / 至11千伏开关柜", [280, 1010, 1930, 1450], [1000, 1450, 1300, 1490], "sld-drawing-body", mode="leader", side="below", font=3.6),
        item("sld-transformer-earthing", "TRANSFORMER 1 / TRANSFORMER 2 / NEUTRAL EARTHING NO. 1 / NEUTRAL EARTHING NO. 2", "变压器1 / 变压器2 / 中性点接地1 / 中性点接地2", [180, 1340, 1700, 1620], [730, 1560, 1050, 1605], "sld-drawing-body", mode="leader", side="above", font=3.6),
        item("sld-bottom-cables", "CABLE LAID IN TRENCHES / TO LVAC / TO 11KV SWITCHGEAR 1-A, 1-B, 2-A, 2-B", "电缆敷设于电缆沟内 / 至低压交流电源 / 至11千伏开关柜1-A、1-B、2-A、2-B", [50, 1510, 1950, 1660], [1050, 1605, 1450, 1645], "sld-drawing-body", mode="leader", side="above", font=3.4),
        item("sld-drawing-title", "275KV MAIN SINGLE LINE DIAGRAM / CONSTRUCTION DRAWING", "275千伏主单线图 / 施工图纸", [1955, 1320, 2350, 1540], [1955, 1320, 2350, 1540], "sld-title-panel", mode="title_block", side="below", font=3.3, preserve=False, opaque=True, role="heading"),
        item("sld-title-fields", "LANDOWNER / DEVELOPER / MAIN CONTRACTOR / SERVICES TITLE / DRAWING TITLE / DRAWING NO. / DRAWN / DESIGNED / CHECKED / SCALE / DATE / REVISION", "土地业主/开发商 / 总承包商 / 专业名称 / 图纸名称 / 图号 / 绘制 / 设计 / 审核 / 比例 / 日期 / 修订", [1955, 120, 2350, 1650], [1955, 120, 2350, 1650], "sld-title-panel", mode="title_block", side="below", font=2.8, preserve=False, opaque=True),
    ]
    electrical_review = """# Terra High whole-page visual review\n\nSource render reviewed: 275 kV single-line diagram. The horizontal bus, breakers, CT/VT symbols, conductor runs, feeder hierarchy, voltage/current values, relay codes and bay identifiers are protected engineering objects. The legend is a visually distinct, dense central table; every protection description is translated as one grouped Chinese description while retaining the code/relay token. Repeated cable/trench and meter labels are explicitly inventoried by local diagram group rather than globally deduplicated. The right-hand commercial/title strip contains logos and ordinary text; only the declared ordinary text masks are eligible for black reflow. OCR may rotate/read micro labels and confirm anchors but cannot change the blue caption locations, leader paths or protected electrical topology.\n"""
    write("03-275kv-single-line", plan(source=electrical_source, page_type="electrical_single_line_diagram", delivery_mode="inline_bilingual", regions=electrical_regions, entries=electrical_entries, ocr_regions=[{"id": "sld-legend", "region_norm": [0.36, 0.05, 0.67, 0.25], "engine": "technical_cad_ocr", "purpose": "execute protection-code and description extraction after visual grouping"}, {"id": "sld-body-tiles", "region_norm": [0.02, 0.03, 0.82, 0.98], "engine": "technical_cad_ocr", "purpose": "overlapping high-resolution labels; retain symbol/direction association"}, {"id": "sld-title-panel", "region_norm": [0.82, 0.03, 0.99, 0.98], "engine": "technical_cad_ocr", "purpose": "ordinary text mask confirmation only; logo exclusion mandatory"}], review=electrical_review), electrical_source, electrical_review)


if __name__ == "__main__":
    main()
