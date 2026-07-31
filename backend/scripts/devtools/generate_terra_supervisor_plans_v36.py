# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
"""Create V3.6 Terra High declared-OCR planning evidence for three source pages.

The plans are deliberately planning-only artifacts. They freeze original-page
provenance, record reference translations as evidence, and give OCR a bounded
execution manifest. No rendered candidate PDF is produced by this script.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import fitz


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend" / "scripts"))

from services.engineering_drawing.multimodal_plan import validate_multimodal_plan
from services.engineering_drawing.workflow_policy import WORKFLOW_VERSION


ARTIFACT_ROOT = REPO / "output" / "pdf" / "engineering-drawing" / "01_Bilingual_Inline" / "agent-artifacts"
OUTPUT = ARTIFACT_ROOT / "terra-supervisor-plans-v36"

BLUE = [0.05, 0.16, 0.45]
BLACK = [0.0, 0.0, 0.0]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def source_snapshot(source: Path, name: str) -> dict[str, Any]:
    with fitz.open(source) as document:
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
        render = OUTPUT / "source-page-renders" / f"{name}.original-page-001.png"
        render.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(render)
        return {
            "source_pdf": str(source),
            "source_sha256": digest(source),
            "page_count": document.page_count,
            "page_index": 0,
            "page_rect": [page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1],
            "page_rotation": page.rotation,
            "rendered_source_page": str(render),
        }


def reference_snapshot(reference: Path, name: str) -> dict[str, Any]:
    """Render an evidence-only page that is never eligible as a PDF base layer."""
    with fitz.open(reference) as document:
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False)
        render = OUTPUT / "reference-evidence-renders" / f"{name}.reference-page-001.png"
        render.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(render)
        return {
            "reference_pdf": str(reference),
            "reference_sha256": digest(reference),
            "page_count": document.page_count,
            "rendered_evidence_page": str(render),
            "usage": "translation_evidence_only",
            "may_supply_page_pixels": False,
            "may_supply_target_coordinates": False,
        }


def plan_region(region_id: str, region_type: str, bbox: list[float]) -> dict[str, Any]:
    strategies = {
        "drawing_body": "blue_preserve_source",
        "drawing_table": "blue_preserve_source",
        "directory_index": "black_chinese_replacement",
        "company_contact_panel": "black_bilingual_text_reflow",
        "state_bearing_metadata": "blue_preserve_source",
        "prose_or_index_metadata": "black_bilingual_hierarchy_reflow",
    }
    return {
        "region_id": region_id,
        "region_type": region_type,
        "page_index": 0,
        "bbox": bbox,
        "strategy": strategies[region_type],
        "decision_source": "multimodal_visual_plan",
    }


def block(
    ident: str,
    source: str,
    chinese: str,
    source_bbox: list[float],
    target_bbox: list[float],
    region_id: str,
    region_type: str,
    *,
    role: str = "label",
    font_size: float = 4.0,
    source_reflow: bool = False,
    mode: str = "inline",
) -> dict[str, Any]:
    placement: dict[str, Any] = {
        "side": "below",
        "mode": mode,
        "selected_region": target_bbox,
        "candidate_regions": [],
        "font_size": font_size,
        "rotation": 0,
        "decision_source": "multimodal_visual_plan",
        "leader_allowed_when_local_space_exhausted": False,
        "multimodal_visual_whitespace_override": True,
        "line_break_policy": "semantic_boundaries_only",
    }
    if region_type in {"drawing_body", "drawing_table", "state_bearing_metadata"}:
        placement.update({"preserve_source": True, "render_text": chinese, "color": BLUE})
    elif region_type == "directory_index":
        placement.update(
            {
                "preserve_source": False,
                "exact_ink_masks": [source_bbox],
                "render_runs": [
                    {"text": chinese, "bbox": target_bbox, "font_size": font_size, "font_name": "simhei", "color": BLACK, "rotation": 0}
                ],
                "mask_execution_requirement": "OCR must derive glyph-alpha masks inside this declared envelope; masking may not expand to rules, codes, or neighbouring cells.",
            }
        )
    else:
        split_y = round(target_bbox[1] + (target_bbox[3] - target_bbox[1]) * 0.46, 2)
        placement.update(
            {
                "preserve_source": False,
                "exact_ink_masks": [source_bbox],
                "render_runs": [
                    {"text": source, "bbox": [target_bbox[0], target_bbox[1], target_bbox[2], split_y], "font_size": max(2.8, font_size * 0.82), "font_name": "helv", "color": BLACK, "rotation": 0},
                    {"text": chinese, "bbox": [target_bbox[0], split_y, target_bbox[2], target_bbox[3]], "font_size": font_size, "font_name": "simhei", "color": BLACK, "rotation": 0},
                ],
                "mask_execution_requirement": "OCR must derive glyph-alpha masks only for this ordinary-text envelope; preserve every logo, border, separator, checkbox, revision mark and drawing code.",
            }
        )
    return {
        "coverage": {
            "candidate_id": ident,
            "page_index": 0,
            "source_text": source,
            "source_bbox": source_bbox,
            "status": "translated",
            "inspection_basis": "Terra High whole-page source-image review; declared OCR only validates source anchors and masks.",
        },
        "block": {
            "block_id": ident,
            "member_ids": [ident],
            "page_index": 0,
            "page_region_id": region_id,
            "region_type": region_type,
            "source_text": source,
            "source_bbox": source_bbox,
            "translated_text": chinese,
            "coverage_status": "translated",
            "decision_source": "multimodal_visual_plan",
            "layout_role": role,
            "typography": {"semantic_role": role, "bold": role in {"heading", "section_heading", "table_header"}},
            "placement": placement,
        },
    }


def ocr_task(ident: str, region_norm: list[float], purpose: str, *, rotation: int = 0) -> dict[str, Any]:
    return {
        "id": ident,
        "page_index": 0,
        "region_norm": region_norm,
        "engine": "technical_cad_ocr",
        "rotation": rotation,
        "language_scope": ["ms", "en", "technical_codes"],
        "priority": "required",
        "purpose": purpose,
        "expected_output": "source text, display-space anchor boxes, confidence and glyph-alpha masks only",
    }


def build_plan(
    *,
    source: Path,
    reference: Path,
    page_type: str,
    delivery_mode: str,
    regions: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    visual_review: str,
    name: str,
) -> dict[str, Any]:
    snapshot = source_snapshot(source, name)
    reference_evidence = reference_snapshot(reference, name)
    blocks = [entry["block"] for entry in entries]
    return {
        "schema": "engineering-drawing-multimodal-plan-v3",
        "workflow_version": WORKFLOW_VERSION,
        "status": "approved",
        "agent_plan_status": "approved",
        "supervisor_count": 1,
        "parallel_supervisors": False,
        "model_provider": "openai-codex",
        "model_name": "gpt-5.6-terra",
        "reasoning_profile": "high",
        "supervisor_adapter": "terra-high",
        "model_capabilities": ["multimodal_page_planning", "ocr_task_supervision", "semantic_translation_planning", "translation_placement_planning", "visual_release_review"],
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
            "source_sha256": snapshot["source_sha256"],
            "reference_usage": "translation_evidence_only",
            "copied_reference_page_or_region": False,
            "source_snapshot": snapshot,
        },
        "page_type": page_type,
        "delivery_mode": delivery_mode,
        "page_region_map": regions,
        "existing_translation_inventory": existing,
        "reference_translation_evidence": reference_evidence,
        "coverage_inventory": [entry["coverage"] for entry in entries],
        "semantic_blocks": blocks,
        "mandatory_zone_audit": [
            {
                "zone_id": region["region_id"],
                "zone_type": region["region_type"],
                "page_index": 0,
                "member_ids": [entry["block"]["block_id"] for entry in entries if entry["block"]["page_region_id"] == region["region_id"]],
                "block_ids": [entry["block"]["block_id"] for entry in entries if entry["block"]["page_region_id"] == region["region_id"]],
                "status": "complete",
                "decision_source": "multimodal_visual_plan",
            }
            for region in regions
        ],
        "supervisor_plan": {
            "contract_version": "v3-supervisor-plan-1",
            "role": "multimodal_page_manager",
            "status": "approved",
            "model_name": "gpt-5.6-terra",
            "reasoning_profile": "high",
            "page_type": page_type,
            "delivery_mode": delivery_mode,
            "ocr_tasks": tasks,
            "translation_tasks": [
                {"id": f"translate-{item['block_id']}", "semantic_block": item["block_id"], "source_candidate_ids": item["member_ids"]}
                for item in blocks
            ],
            "placement_policy": {
                "authority": "Terra High source-page image review",
                "target_selection": "selected_region is final; executor cannot move, shrink, reroute or search a fallback",
                "ocr_execution_mode": "supervisor_declared_task_crops",
                "unplanned_full_page_scan": False,
                "generic_full_page_fallback": "forbidden",
                "drawing_body_and_table": "blue Chinese, preserve original; no white masking",
                "company_and_prose_panels": "black bilingual reflow with OCR-derived glyph-alpha mask inside explicit envelope only",
                "state_bearing_metadata": "blue Chinese preserve-source only; never mask or clear state symbols",
                "directory_index": "black Chinese replacement only inside per-cell glyph-alpha masks; preserve row numbers, drawing codes, paper sizes and rules",
            },
            "escalations": [
                "Any OCR discovery outside a declared crop, occupied final target, cropped text uncertainty, or mask touching protected ink fails execution and returns to this supervisor; no automated fallback is permitted."
            ],
            "audit_note": visual_review,
        },
        "execution_contract": {
            "ocr_execution_mode": "supervisor_declared_task_crops",
            "unplanned_full_page_scan": False,
            "allow_generic_full_page_fallback": False,
            "allow_crop_expansion_or_relocation": False,
            "all_tasks_bounded": True,
            "all_tasks_page_bound": True,
            "candidate_pdf_generation": "not_authorized_by_this_plan",
        },
        "audit": {
            "plan_scope": "declared_ocr_planning_only",
            "visual_review_method": "original PDF page raster inspected before OCR planning; reference PDF inspected only to verify selected Chinese terminology",
            "reference_reuse_decision": "all extracted reference strings are evidence records marked replace; reference pixels and positions are never reused",
            "release_gate": "not_run: planning-only. Candidate publication is prohibited until declared OCR, exact-mask validation and final whole-page visual QA pass.",
        },
    }


def evidence(ident: str, text: str, bbox: list[float], reference: Path, association: str) -> dict[str, Any]:
    return {
        "translation_id": ident,
        "page_index": 0,
        "bbox": bbox,
        "text": text,
        "source_file": str(reference),
        "source_association": association,
        "action": "replace",
        "evidence_only": True,
    }


def write(name: str, payload: dict[str, Any], review: str) -> None:
    normalized = validate_multimodal_plan(payload, source_pdf_path=Path(payload["render_provenance"]["source_snapshot"]["source_pdf"]))
    (OUTPUT / f"{name}.supervisor-plan.json").write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / f"{name}.visual-review.md").write_text(review + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    index = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\03_CONSTRUCTION DWG_MASJID_11 NOV 2025\A1 WORKING DRAWING\00_LIST OF DRAWING_A1 FORMAT.pdf")
    index_ref = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\清真寺施工图纸 11112025 翻译\清真寺施工图纸 11112025 翻译\00_LIST OF DRAWING_A1 FORMAT_翻译.pdf")
    index_regions = [plan_region("index-directory", "directory_index", [80, 800, 1600, 1700])]
    index_entries = [
        block("index-heading", "LIST OF DRAWING / WORKING DRAWING", "图纸目录 / 施工图", [430, 805, 1260, 850], [430, 805, 1260, 850], "index-directory", "directory_index", role="heading", font_size=8.0, mode="table_cell"),
        block("index-header", "NO. / DRAWING TITLE / DRAWING NO. / SIZE", "序号 / 图纸名称 / 图号 / 图幅", [150, 955, 1510, 990], [150, 955, 1510, 990], "index-directory", "directory_index", role="table_header", font_size=6.0, mode="table_cell"),
        block("index-site-row", "PELAN KUNCI, PELAN LOKASI & PELAN TAPAK", "位置图、区位图及场地总图", [270, 1105, 1075, 1135], [270, 1105, 1075, 1135], "index-directory", "directory_index", font_size=5.0, mode="table_cell"),
        block("index-masjid-row", "PELAN TINGKAT BAWAH; PELAN BUMBUNG; PANDANGAN; KERATAN", "首层平面图；屋面图；立面图；剖面图", [270, 1200, 1075, 1270], [270, 1200, 1075, 1270], "index-directory", "directory_index", font_size=4.6, mode="table_cell"),
        block("index-ancillary-row", "KEBUK SAMPAH, BILIK PAM, BILIK TANGKI SEDUTAN", "垃圾房、泵房、吸水池间", [270, 1580, 1075, 1615], [270, 1580, 1075, 1615], "index-directory", "directory_index", font_size=4.8, mode="table_cell"),
    ]
    index_review = """# V3.6 Terra High visual review: directory table

Original A1 index page image was reviewed before OCR. It is a ruled `directory_index`; table rules, row numbering, drawing codes, sheet sizes, border and vertical CONSTRUCTION DRAWING stamp are protected. The reference PDF was inspected only for terms such as 图纸目录 and 场地总图. Each declared target is the source text envelope itself; OCR must generate only glyph-alpha masks inside that envelope. A crop may never expand across a cell boundary, code column or rule. This plan deliberately does not authorize a candidate PDF until the exact-mask output is visually checked.
"""
    write("01-a1-drawing-index-v36", build_plan(source=index, reference=index_ref, page_type="dense_drawing_index", delivery_mode="opaque_bilingual_reflow", regions=index_regions, entries=index_entries, tasks=[ocr_task("index-title-band", [0.22, 0.32, 0.78, 0.39], "title wording and glyph masks"), ocr_task("index-header-row", [0.08, 0.39, 0.90, 0.44], "header cells and rule-safe masks"), ocr_task("index-description-column", [0.14, 0.44, 0.65, 0.72], "row-description cells only; exclude number/code/size columns")], existing=[evidence("idx-ref-directory", "图纸目录", [430, 805, 510, 830], index_ref, "LIST OF DRAWING"), evidence("idx-ref-site", "场地总图", [270, 1105, 360, 1135], index_ref, "PELAN TAPAK")], visual_review=index_review, name="01-a1-drawing-index-v36"), index_review)

    site = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\03_CONSTRUCTION DWG_MASJID_11 NOV 2025\A1 WORKING DRAWING\00_Site Masjid Tok Muda_CONSTRUCTION.pdf")
    site_ref = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\清真寺施工图纸 11112025 翻译\清真寺施工图纸 11112025 翻译\00_Site Masjid Tok Muda_CONSTRUCTION_翻译.pdf")
    site_regions = [plan_region("site-left-table", "drawing_table", [45, 45, 790, 1640]), plan_region("site-body", "drawing_body", [790, 45, 2070, 1640]), plan_region("site-company", "company_contact_panel", [2080, 115, 2360, 1335]), plan_region("site-prose", "prose_or_index_metadata", [2080, 350, 2360, 420]), plan_region("site-state", "state_bearing_metadata", [2080, 1340, 2360, 1640])]
    site_entries = [
        block("site-map-headings", "PELAN KUNCI / PELAN LOKASI / TAPAK CADANGAN", "位置图 / 区位图 / 拟建场地", [70, 290, 490, 710], [500, 300, 735, 332], "site-left-table", "drawing_table", font_size=4.2),
        block("site-land-table", "KELUASAN TANAH PEMBANGUNAN / MAKLUMAT LOT / LUAS", "建设用地面积 / 地块资料 / 面积", [70, 720, 730, 860], [75, 865, 730, 890], "site-left-table", "drawing_table", font_size=4.0),
        block("site-legend", "PETUNJUK / MASJID / BANGUNAN PEJABAT / GAZEBO", "图例 / 清真寺 / 办公楼 / 凉亭", [570, 720, 790, 930], [575, 935, 785, 960], "site-left-table", "drawing_table", font_size=3.8),
        block("site-plan-title", "PELAN TAPAK / SKALA 1 : 600", "场地总图 / 比例 1:600", [1425, 1510, 1685, 1595], [1430, 1598, 1685, 1625], "site-body", "drawing_body", role="heading", font_size=4.8),
        block("site-hydrant", "EXISTING FIRE HYDRANT TO BE MAKE GOOD WHERE NECESSARY", "现有消防栓按需要修复完好", [1740, 150, 2045, 220], [1740, 225, 2045, 247], "site-body", "drawing_body", font_size=3.6),
        block("site-gate-fence", "1700MM(H) DECORATIVE GATE POST / G.I. PERIMETER FENCING", "1700毫米高装饰门柱 / 镀锌周界围栏", [820, 170, 1140, 325], [820, 330, 1140, 352], "site-body", "drawing_body", font_size=3.6),
        block("site-owner-labels", "PEMILIK TANAH / PEMILIK BANGUNAN / AGENSI PELAKSANA", "土地业主 / 建筑业主 / 执行机构", [2090, 128, 2335, 190], [2090, 128, 2335, 190], "site-company", "company_contact_panel", font_size=3.2, source_reflow=True, mode="title_block"),
        block("site-project-description", "CADANGAN MEROBOH DAN MEMBINA SEMULA MASJID AL-EHSAN", "拟拆除并重建阿尔艾赫桑清真寺", [2089, 371, 2324, 402], [2089, 371, 2324, 402], "site-prose", "prose_or_index_metadata", role="heading", font_size=3.4, source_reflow=True, mode="title_block"),
        block("site-state-fields", "DRAWING STATUS / DRAWING TITLE / NO. LUKISAN / SCALE / DATE", "图纸状态 / 图纸名称 / 图号 / 比例 / 日期", [2085, 1420, 2350, 1570], [2085, 1574, 2350, 1600], "site-state", "state_bearing_metadata", font_size=3.0),
    ]
    site_review = """# V3.6 Terra High visual review: Masjid site plan

Original landscape source image was reviewed before OCR. The left maps/tables are `drawing_table`; the diagonal plan, road lines, fencing, hatching and notes are `drawing_body`; the right rail is visually split into logo-bearing company contact, ordinary project prose, and state-bearing title metadata. Logos, seals, pink stamp, road geometry, hatching, boundaries, table rules, check boxes, signature lines and revision marks are protected. Chinese in drawing zones is adjacent blue preserve-source text with no leader authorized. Reference translations were checked as terminology evidence only and are all marked replace, never reused by coordinate or image.
"""
    write("02-masjid-site-plan-v36", build_plan(source=site, reference=site_ref, page_type="architectural_site_plan", delivery_mode="inline_bilingual", regions=site_regions, entries=site_entries, tasks=[ocr_task("site-left-maps", [0.02, 0.03, 0.33, 0.41], "map headings and labels only"), ocr_task("site-left-tables", [0.02, 0.41, 0.33, 0.97], "left information tables and legend"), ocr_task("site-upper-notes", [0.33, 0.05, 0.86, 0.32], "upper site-plan notes only"), ocr_task("site-lower-title", [0.55, 0.82, 0.82, 0.98], "plan title and scale only"), ocr_task("site-right-company", [0.87, 0.07, 0.99, 0.79], "ordinary company/prose text; logo exclusion"), ocr_task("site-right-state", [0.87, 0.80, 0.99, 0.98], "state-bearing metadata anchors only; no masks")], existing=[evidence("site-ref-hydrant", "现有消防栓应在必要时修复完好", [1740, 225, 2045, 247], site_ref, "EXISTING FIRE HYDRANT"), evidence("site-ref-title", "场地总图", [1430, 1598, 1530, 1625], site_ref, "PELAN TAPAK")], visual_review=site_review, name="02-masjid-site-plan-v36"), site_review)

    sld = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\报审图纸\275kV MEP Construction Drawing_260610\Construction Drawing\RCJM2 CN ELEC 20260610\Constrcution Drawing PDF\1310-CN-ELEC-SCH-C001_275kV SLD.pdf")
    sld_ref = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\Translated Drawing 图纸翻译\Translated Drawing 图纸翻译\1310-CN-ELEC-SCH-C001_275kV SLD_Translated.pdf")
    sld_regions = [plan_region("sld-legend", "drawing_table", [850, 85, 1280, 390]), plan_region("sld-body", "drawing_body", [30, 50, 1940, 1660]), plan_region("sld-company", "company_contact_panel", [1960, 250, 2360, 1220]), plan_region("sld-prose", "prose_or_index_metadata", [1960, 1210, 2360, 1510]), plan_region("sld-state", "state_bearing_metadata", [1960, 1510, 2360, 1660])]
    sld_entries = [
        block("sld-legend-heading", "LEGEND", "图例", [870, 100, 980, 135], [990, 100, 1060, 130], "sld-legend", "drawing_table", role="heading", font_size=4.2),
        block("sld-protection", "MAIN 1 INTEGRATED LINE DIFFERENTIAL PROTECTION INCOMER / SYNCHECK RELAY", "主1进线综合线路差动保护 / 同期检查继电器", [900, 115, 1260, 380], [1280, 115, 1560, 145], "sld-legend", "drawing_table", font_size=3.3),
        block("sld-incomer-left", "TNB INCOMER 1 (275KV) / INDUCTIVE VOLTAGE TRANSFORMER", "国能进线1（275千伏）/ 感应式电压互感器", [70, 110, 390, 315], [70, 320, 390, 345], "sld-body", "drawing_body", font_size=3.6),
        block("sld-incomer-right", "TNB INCOMER 2 (275KV) / INDUCTIVE VOLTAGE TRANSFORMER", "国能进线2（275千伏）/ 感应式电压互感器", [1595, 110, 1920, 315], [1595, 320, 1920, 345], "sld-body", "drawing_body", font_size=3.6),
        block("sld-bus", "275KV MAIN BUSBAR 1 / BUS SECTION / BUSBAR 2", "275千伏主母线1 / 母线分段 / 母线2", [780, 650, 1615, 735], [780, 740, 1210, 765], "sld-body", "drawing_body", font_size=3.6),
        block("sld-bays", "FUTURE PHASE BAY A1, A2, A3, A4, B1, B2, B3, B4", "预留期相间隔A1、A2、A3、A4、B1、B2、B3、B4", [260, 1080, 1900, 1400], [850, 1405, 1400, 1430], "sld-body", "drawing_body", font_size=3.4),
        block("sld-consultant-labels", "ARCHITECT / BASE BUILD MEP CONSULTANT / CBS CONSULTANT", "建筑师 / 基础机电顾问 / 变电站顾问", [1970, 360, 2340, 710], [1970, 360, 2340, 710], "sld-company", "company_contact_panel", font_size=3.0, source_reflow=True, mode="title_block"),
        block("sld-title", "275KV MAIN SINGLE LINE DIAGRAM", "275千伏主单线图", [1980, 1375, 2340, 1440], [1980, 1375, 2340, 1440], "sld-prose", "prose_or_index_metadata", role="heading", font_size=3.4, source_reflow=True, mode="title_block"),
        block("sld-state-fields", "DRAWN / DESIGNED / CHECKED / SCALE / DATE / REVISION", "绘制 / 设计 / 审核 / 比例 / 日期 / 修订", [1980, 1530, 2340, 1655], [1980, 1500, 2340, 1525], "sld-state", "state_bearing_metadata", font_size=2.9),
    ]
    sld_review = """# V3.6 Terra High visual review: 275 kV single-line diagram

Original PDF was reviewed in its rotated display page frame (2384 x 1684). The electrical topology, bus, conductor routes, relay codes, bay identifiers, voltage/current values, symbols and title-panel logos are protected. The legend is a `drawing_table`; its Chinese remains blue and adjacent to source text. The title strip is split into company contact, ordinary drawing prose, and state-bearing metadata rather than treated as one opaque panel. All declared targets use display-page coordinates. Reference evidence was rechecked for terms including 同期检查继电器 but supplies neither page pixels nor coordinates. No candidate is authorized until crop-only OCR and final visual QA verify those placements.
"""
    write("03-275kv-single-line-v36", build_plan(source=sld, reference=sld_ref, page_type="electrical_single_line_diagram", delivery_mode="inline_bilingual", regions=sld_regions, entries=sld_entries, tasks=[ocr_task("sld-legend-table", [0.35, 0.05, 0.54, 0.24], "protection codes and legend descriptions"), ocr_task("sld-left-incomer", [0.02, 0.06, 0.24, 0.48], "left incomer labels and equipment anchors"), ocr_task("sld-central-bus-bays", [0.20, 0.30, 0.80, 0.85], "bus and bay label groups"), ocr_task("sld-right-incomer", [0.62, 0.06, 0.82, 0.48], "right incomer labels and equipment anchors"), ocr_task("sld-title-company", [0.83, 0.14, 0.99, 0.72], "ordinary company/prose text only; exclude logos"), ocr_task("sld-title-state", [0.83, 0.72, 0.99, 0.99], "state-bearing field anchors only; no masks")], existing=[evidence("sld-ref-syncheck", "同期检查继电器", [990, 355, 1080, 380], sld_ref, "SYNCHECK RELAY"), evidence("sld-ref-title", "275千伏主单线图", [1980, 1375, 2120, 1400], sld_ref, "275KV MAIN SINGLE LINE DIAGRAM")], visual_review=sld_review, name="03-275kv-single-line-v36"), sld_review)

    plan_files = sorted(OUTPUT.glob("*.supervisor-plan.json"))
    checks = []
    for plan_file in plan_files:
        payload = json.loads(plan_file.read_text(encoding="utf-8"))
        tasks = payload["supervisor_plan"]["ocr_tasks"]
        checks.append(
            {
                "plan": plan_file.name,
                "strict_multimodal_execution": payload.get("execution_policy") == "strict_multimodal_execution",
                "workflow_version": payload.get("workflow_version"),
                "ocr_task_count": len(tasks),
                "all_tasks_page_bound": all(task.get("page_index") == 0 for task in tasks),
                "all_tasks_bounded": all(
                    task.get("full_page") is True
                    or isinstance(task.get("region_norm"), list)
                    and len(task["region_norm"]) == 4
                    and all(0 <= float(value) <= 1 for value in task["region_norm"])
                    and task["region_norm"][0] < task["region_norm"][2]
                    and task["region_norm"][1] < task["region_norm"][3]
                    for task in tasks
                ),
            }
        )
    contract = {
        "workflow_version": WORKFLOW_VERSION,
        "supervisor_count": 1,
        "model": "gpt-5.6-terra",
        "reasoning_profile": "high",
        "execution_policy": "strict_multimodal_execution",
        "ocr_execution_mode": "supervisor_declared_task_crops",
        "unplanned_full_page_scan": False,
        "candidate_pdf_published": False,
        "visual_release_gate": "not_run; planning-only artifacts require OCR/mask and whole-page visual QA before release",
        "plan_validation": "passed via validate_multimodal_plan against each original source PDF",
        "plans": checks,
    }
    (OUTPUT / "execution-contract-check.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
