# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json, hashlib

ROOT = Path(r"D:\AmyProjects\business\pdf-manager")
SOURCE = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\A3 DETAIL DRAWING\28_REV. JULAI 2025 GAZEBO.pdf")
OLD = ROOT / r"output/pdf/engineering-drawing/01_Bilingual_Inline/agent-artifacts/v3.11-cost-balanced-final-3/sample-03__28_REV._JULAI_2025_GAZEBO/supervisor-plan.json"
WORK = ROOT / r"output/pdf/engineering-drawing/01_Bilingual_Inline/agent-artifacts/v4.0-readable-zone-complete/10-specialized"

TRANSLATIONS = [
"屋脊及脊瓦盖板按专业承包商详图", "现有4根木柱尺寸须现场复测",
"饰面；坡向；100毫米厚水洗卵石混凝土板；圆角木收边；专业详图",
"虚线表示125毫米宽×25毫米厚木板；现有木柱从原清真寺拆除并重建，涂Woodshield室外清漆",
"水洗卵石饰面",
"4根200×200毫米现有木柱拆除后重建；屋面坡度35°；125×25毫米木板涂Woodshield室外清漆",
"75毫米宽×40毫米厚木楼板搁栅；125×25毫米木板均涂Woodshield室外清漆，并按要求布置",
"平面图，比例1:50", "选用铺地砖", "屋面平面图，比例1:50",
"125毫米宽×40毫米厚外露木桁架，涂Woodshield室外清漆", "圆角木收边",
"梁标高4.800",
"125×40毫米木联系梁、木檐口板及屋脊盖板按专业详图，涂Woodshield室外清漆",
"平台标高2.700",
"200×25毫米木边梁；125×25毫米木板；4根200×200毫米现有木柱拆除后重建，统一涂Woodshield室外清漆",
"125×40毫米木梁涂Woodshield室外清漆；不锈钢转角连接板及螺钉按制造商详图",
"详图1，比例1:5",
"正立面比例1:50；道路标高2.100；地面标高2.000；项目：拆除并重建Al-Ehsan清真寺",
"图纸名称：正立面",
"X-X剖面，比例1:50；100毫米厚水洗卵石板；AC建筑设计私人有限公司5层8-AD室",
"基础按工程师详图；木构件涂Woodshield室外清漆；图号及日期",
"备注；施工图；修订；更正",
"地点：雪兰莪州巴生县加帕尔Tok Muda村", "阿尔-埃赫桑清真寺",
"凉亭详图：底层平面图、屋面图、正立面、X-X剖面及详图1",
"AC建筑设计私人有限公司；Pandan Indah MPAJ大道，55100雪兰莪；邮箱acarch.sb@gmail.com",
"Pandan Kapital A座5层8-AD室",
"绘制APIZ；日期2025年7月；修订00；比例1:50",
"图号ACASB 2401/MTM/GZ/DT-01",
]

SOURCES = [
"HIP AND RIDGE CAP TO SPECIALIST'S DETAIL",
"NOTE: THE SIZE FOR (4 NOS.) EXISTING TIMBER COLUMN NEED TO BE MEASURED AGAIN ON SITE FOR ACTUAL MEASUREMENT",
"FINISH; FALL; 100MM THK. SLAB WITH PEEBLE WASH FINISH; BULLNOSE TIMBER EDGING; SPECIALIST'S DETAIL",
"DOTTED LINE INDICATED 125MM(W) × 25MM THK. TIMBER PLANK FINISHED WITH WOODSHIELD EXTERIOR VARNISH; EXISTING COLUMN TO BE DISMANTLED AND RECONSTRUCTED",
"PEEBLE WASH",
"(4 NOS.) 200MM × 200MM EXISTING TIMBER COLUMN TO BE DISMANTLED FROM EXISTING MOSQUE AND RECONSTRUCTED AS COLUMN; PITCH 35°; 125MM(W) × 25MM THK. TIMBER PLANK FINISHED WITH WOODSHIELD EXTERIOR VARNISH",
"75MM(W) × 40MM THK. TIMBER FLOOR JOIST; 125MM(W) × 25MM THK. TIMBER PLANK FINISHED WITH WOODSHIELD EXTERIOR VARNISH AND ARRANGED ACCORDINGLY",
"PELAN; SKALA 1:50", "SEL. PAVING BLOCK", "PELAN BUMBUNG; SKALA 1:50",
"125MM(W) × 40MM THK. EXPOSED TIMBER TRUSSES FINISHED WITH WOODSHIELD EXTERIOR VARNISH",
"BULLNOSE TIMBER EDGING", "ARAS RASUK (LVL 4.800)",
"125MM(W) × 40MM THK. TIMBER TIE BEAM; TIMBER FASCIA BOARD; HIP AND RIDGE CAP TO SPECIALIST'S DETAIL; FINISHED WITH WOODSHIELD EXTERIOR VARNISH",
"PLATFORM (FL 2.700)",
"200MM(W) × 25MM THK. TIMBER RIM JOIST; 125MM(W) × 25MM THK. TIMBER PLANK; (4 NOS.) 200MM × 200MM EXISTING TIMBER COLUMN DISMANTLED AND RECONSTRUCTED; FINISHED WITH WOODSHIELD EXTERIOR VARNISH",
"125MM(W) × 40MM THK. TIMBER TIE BEAM FINISHED WITH WOODSHIELD EXTERIOR VARNISH; STAINLESS STEEL CORNER PLATE AND SCREW TO MANUFACTURER'S DETAIL",
"BUTIRAN 1; SKALA 1:5",
"PANDANGAN HADAPAN; SKALA 1:50; ARAS JALAN (FL 2.100); ARAS TANAH (FL 2.000); PROJECT TITLE: CADANGAN MEROBOH DAN MEMBINA SEMULA MASJID AL-EHSAN",
"DRAWING TITLE: PANDANGAN HADAPAN",
"KERATAN X-X; SKALA 1:50; 100MM THK. SLAB WITH PEEBLE WASH FINISH; AC ARCHITECTS SDN BHD; SUITE 8-AD, 5TH LEVEL",
"FOUNDATION TO ENGINEER'S DETAIL; TIMBER FINISHED WITH WOODSHIELD EXTERIOR VARNISH; DRAWING NO.; DATE",
"REMARKS; CONSTRUCTION DRAWING; REVISION; CORRECTION",
"KAMPUNG TOK MUDA, KAPAR, DAERAH KLANG, SELANGOR DARUL EHSAN",
"MASJID AL-EHSAN",
"PERINCIAN GAZEBO: PELAN TINGKAT BAWAH; PELAN BUMBUNG; PANDANGAN HADAPAN; KERATAN X-X; BUTIRAN 1",
"AC ARCHITECTS SDN BHD; PERSIARAN MPAJ, PANDAN INDAH, 55100 SELANGOR DARUL EHSAN; EMAIL: acarch.sb@gmail.com",
"SUITE 8-AD, 5TH LEVEL, TOWER A, PANDAN KAPITAL",
"DRAWN BY: APIZ; DATE: JULAI 2025; REVISION: 00; SCALE: 1:50",
"DRAWING NO. ACASB 2401/MTM/GZ/DT-01",
]

GROUPS = {
    "plan": {1, 3, 5, 8, 9},
    "roof_plan": {2, 4, 6, 7, 10, 11, 12},
    "front_elevation": {13, 14, 15, 16, 19, 20},
    "section_detail": {17, 18, 21, 22},
    "title_sidebar_footer": set(range(23, 31)),
}


def main():
    plan = json.loads(OLD.read_text(encoding="utf8"))
    old_blocks = plan["semantic_blocks"]
    if len(old_blocks) != len(TRANSLATIONS) or len(SOURCES) != len(TRANSLATIONS):
        raise RuntimeError("semantic inventory and translation count differ")
    blocks = []
    for idx, (old, translated) in enumerate(zip(old_blocks, TRANSLATIONS), 1):
        view = next(name for name, members in GROUPS.items() if idx in members)
        zone = "drawing_body" if idx <= 22 else (
            "company_contact_panel" if idx in {27, 28} else
            "state_bearing_metadata" if idx in {23, 29, 30} else
            "prose_or_index_metadata")
        blocks.append({
            "block_id": f"gazebo-{idx:02d}",
            "source_ids": old.get("member_ids") or [f"gazebo-source-{idx:02d}"],
            "source_text": SOURCES[idx - 1], "translated_text": translated,
            "bbox": old["source_bbox"], "page_index": 0, "view": view,
            "rotation": 0, "zone": zone,
            "render_mode": "preserve_source_blue_chinese" if idx <= 22 else "opaque_bilingual_reflow",
            "status": "translated", "reference_usage": "translation_evidence_only",
        })
    payload = {"schema": "v4-sample10-new-semantic-ledger",
               "source_pdf": str(SOURCE),
               "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
               "block_count": len(blocks), "blocks": blocks,
               "whole_page_closure": 1.0, "uncovered_source_ids": []}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "new-semantic-ledger.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"blocks": len(blocks), "output": str(WORK / 'new-semantic-ledger.json')}, ensure_ascii=False))


if __name__ == "__main__":
    main()
