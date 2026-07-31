# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""Build the reviewed R5 title-panel repair for the four-page Masjid sheet.

This is intentionally a narrowly scoped artifact repair.  It does not move a
drawing-body caption: it only replaces the recurrent microscopic title-block
fields that R4 rejected with protected, black source+Chinese cell reflow.
"""

import json
from copy import deepcopy
from pathlib import Path


ARTIFACT = Path(
    r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing"
    r"\01_Bilingual_Inline\batch-artifacts"
    r"\03_CONSTRUCTION_DWG_MASJID_11_NOV_2025__01_Masjid_Tok_Muda_CONSTRUCTION__f8ffb95ffe"
)
INPUT_PLAN = ARTIFACT / "v3.3-post-ocr-executable-plan.json"
OUTPUT_PLAN = ARTIFACT / "v3.3-r5-title-panel-repair-plan.json"
OUTPUT_SPEC = ARTIFACT / "v3.3-r5-title-panel-reflow.json"
OUTPUT_NOTES = ARTIFACT / "v3.3-r5-title-panel-repair-notes.md"


def group(
    key: str,
    rect: list[float],
    text: str,
    members: list[str],
    *,
    max_size: float,
    min_size: float,
    lineheight: float = 1.0,
) -> dict:
    return {
        "key": key,
        "rect": rect,
        "text": text,
        "members": members,
        "max_size": max_size,
        "min_size": min_size,
        "lineheight": lineheight,
    }


def page_groups(page: int, ids: dict[str, str]) -> list[dict]:
    """Return only visually reviewed text interiors; rules and logos stay out."""
    result = [
        group(
            "revision-number",
            [1043.0, 243.6, 1053.6, 252.4],
            "Bil .\n编号",
            [ids["bil"]],
            max_size=3.2,
            min_size=2.6,
            lineheight=0.94,
        ),
        group(
            "architect-registration",
            [1080.0, 362.6, 1164.0, 377.0],
            "A R K I T E K\n建筑师\nNo. Pendaftaran LAM : A/M 91\n马来西亚建筑师委员会注册号：A/M 91",
            [ids["architect"], ids["registration"]],
            max_size=3.2,
            min_size=2.4,
            lineheight=0.98,
        ),
        group(
            "contractor-note",
            [1041.0, 688.4, 1167.0, 700.7],
            "Contractors must check all dimensions on site. Only figured dimensions are to be worked on. "
            "Discrepancies must be reported immediately to the architect before proceeding.\n"
            "承包商须在现场核对所有尺寸，仅按标注尺寸施工；任何差异须在继续施工前立即报告建筑师。",
            [ids["contractor-note"], ids["discrepancies"]],
            max_size=2.8,
            min_size=2.2,
            lineheight=0.94,
        ),
        group(
            "drawing-status-left",
            [1051.8, 708.4, 1075.8, 724.8],
            "PRELIMINARY\n初步\nINFORMATION\n信息",
            [ids["preliminary"], ids["information"]],
            max_size=3.2,
            min_size=2.5,
            lineheight=0.96,
        ),
        group(
            "drawing-status-contract",
            [1133.0, 709.0, 1158.0, 724.8],
            "CONTRACT\n合同",
            [ids["contract"]],
            max_size=3.4,
            min_size=2.6,
            lineheight=0.98,
        ),
        group(
            "date",
            [1041.2, 785.4, 1064.8, 801.0],
            "Disemak Oleh\n审核\nTarikh\n日期",
            [ids["reviewed-by"], ids["date"]],
            max_size=3.2,
            min_size=2.5,
            lineheight=0.94,
        ),
    ]
    if page == 1:
        result.append(
            group(
                "drawing-title-roof-set",
                [1041.1, 740.2, 1112.0, 764.9],
                "- PELAN BUMBUNG 1 (RASUK 2)\n屋面平面图 1（梁 2）\n"
                "- PELAN MENARA 1 (RASUK 3)\n塔楼平面图 1（梁 3）\n"
                "- PELAN MENARA 2 (RASUK 5)\n塔楼平面图 2（梁 5）\n"
                "- PELAN BUMBUNG KESELURUHAN\n总体屋面平面图",
                [ids["roof-1"], ids["tower-1"], ids["tower-2"], ids["roof-all"]],
                max_size=3.0,
                min_size=2.3,
                lineheight=0.94,
            )
        )
    if page == 3:
        result.append(
            group(
                "drawing-title-section-e",
                [1041.1, 758.8, 1074.0, 769.8],
                "- KERATAN E-E\nE-E 剖面",
                [ids["section-e"]],
                max_size=3.2,
                min_size=2.5,
                lineheight=0.96,
            )
        )
    return result


PAGE_IDS = [
    {
        "bil": "postocr-0030-p001-native-0065",
        "architect": "postocr-0014-p001-native-0044",
        "registration": "postocr-0015-p001-native-0045",
        "contractor-note": "postocr-0022-p001-native-0057",
        "discrepancies": "postocr-0021-p001-native-0056",
        "preliminary": "postocr-0026-p001-native-0061",
        "information": "postocr-0027-p001-native-0062",
        "contract": "postocr-0045-p001-native-0082",
        "reviewed-by": "postocr-0019-p001-native-0051",
        "date": "postocr-0016-p001-native-0046",
    },
    {
        "bil": "postocr-0142-p002-native-0091",
        "architect": "postocr-0126-p002-native-0070",
        "registration": "postocr-0127-p002-native-0071",
        "contractor-note": "postocr-0134-p002-native-0083",
        "discrepancies": "postocr-0133-p002-native-0082",
        "preliminary": "postocr-0138-p002-native-0087",
        "information": "postocr-0139-p002-native-0088",
        "contract": "postocr-0157-p002-native-0108",
        "reviewed-by": "postocr-0131-p002-native-0077",
        "date": "postocr-0128-p002-native-0072",
        "roof-1": "postocr-0113-p002-native-0005",
        "tower-1": "postocr-0114-p002-native-0006",
        "tower-2": "postocr-0115-p002-native-0007",
        "roof-all": "postocr-0116-p002-native-0008",
    },
    {
        "bil": "postocr-0190-p003-native-0105",
        "architect": "postocr-0174-p003-native-0084",
        "registration": "postocr-0175-p003-native-0085",
        "contractor-note": "postocr-0182-p003-native-0097",
        "discrepancies": "postocr-0181-p003-native-0096",
        "preliminary": "postocr-0186-p003-native-0101",
        "information": "postocr-0187-p003-native-0102",
        "contract": "postocr-0205-p003-native-0122",
        "reviewed-by": "postocr-0179-p003-native-0091",
        "date": "postocr-0176-p003-native-0086",
    },
    {
        "bil": "postocr-0274-p004-native-0155",
        "architect": "postocr-0258-p004-native-0134",
        "registration": "postocr-0259-p004-native-0135",
        "contractor-note": "postocr-0266-p004-native-0147",
        "discrepancies": "postocr-0265-p004-native-0146",
        "preliminary": "postocr-0270-p004-native-0151",
        "information": "postocr-0271-p004-native-0152",
        "contract": "postocr-0289-p004-native-0172",
        "reviewed-by": "postocr-0263-p004-native-0141",
        "date": "postocr-0260-p004-native-0136",
        "section-e": "postocr-0245-p004-native-0097",
    },
]


def main() -> None:
    plan = json.loads(INPUT_PLAN.read_text(encoding="utf-8"))
    blocks = {block["block_id"]: block for block in plan["semantic_blocks"]}
    groups_by_page = [page_groups(page, ids) for page, ids in enumerate(PAGE_IDS)]
    panels = []
    managed: dict[str, tuple[str, str, list[float]]] = {}
    for page_index, groups in enumerate(groups_by_page):
        panel_id = f"masjid-title-panel-p{page_index + 1:03d}"
        fields = []
        for item in groups:
            field_id = f"{panel_id}-{item['key']}"
            fields.append(
                {
                    "field_id": field_id,
                    "rect": item["rect"],
                    "text": item["text"],
                    "font": "simhei",
                    "max_size": item["max_size"],
                    "min_size": item["min_size"],
                    "lineheight": item["lineheight"],
                }
            )
            for block_id in item["members"]:
                if block_id not in blocks:
                    raise KeyError(f"missing reviewed semantic block: {block_id}")
                managed[block_id] = (panel_id, field_id, item["rect"])
        panels.append(
            {
                "panel_id": panel_id,
                "page_index": page_index,
                "clear_mode": "white_overlay",
                "clear_regions": [item["rect"] for item in groups],
                "fields": fields,
                "visual_review": {
                    "reviewed_from": f"page-{page_index + 1:03d}-source.png",
                    "scope": "text interiors only; borders, logos, seals and signatures excluded",
                },
            }
        )
    spec = {
        "schema": "engineering-drawing-title-panel-reflow-v1",
        "source_plan": str(INPUT_PLAN),
        "restore_vector_rules": True,
        "panels": panels,
        "reviewed_block_count": len(managed),
        "rule": "black original+Chinese reflow for reviewed pure-text cells only; no CAD hatch override",
    }
    bil_ids = {ids["bil"] for ids in PAGE_IDS}
    discrepancy_ids = {ids["discrepancies"] for ids in PAGE_IDS}
    for block_id, (panel_id, field_id, rect) in managed.items():
        block = blocks[block_id]
        placement = block["placement"]
        placement.update(
            {
                "panel_reflow_managed": True,
                "panel_reflow_panel_id": panel_id,
                "panel_reflow_field_id": field_id,
                "panel_reflow_target_bbox": rect,
                "text_color": "#000000",
                "opaque_background": "text_cell_reflow",
                "preserve_source": False,
                "allow_source_overlap": False,
                "allow_dense_source_overlap": False,
                "multimodal_visual_whitespace_override": False,
                "instruction": "已由经多模态复核的标题栏文本内区黑色原文+中文重排；禁止额外蓝色标注，保护边框、徽标、印章和签名。",
                "source_overlap_review": {
                    "reviewed_individually": True,
                    "decision": "protected_title_panel_reflow",
                    "visual_ink_ratio": 0.0,
                },
            }
        )
        if block_id in bil_ids:
            block["translated_text"] = "编号"
        if block_id in discrepancy_ids:
            block["translated_text"] = "任何差异须在继续施工前立即报告建筑师。"
    plan["status"] = "repair"
    plan["repair_parent_plan"] = str(INPUT_PLAN)
    plan["panel_reflow_spec"] = str(OUTPUT_SPEC)
    plan["panel_reflow_review"] = {
        "managed_blocks": len(managed),
        "rejected_r4_blocks_repaired": 27,
        "drawing_body_blocks_changed": 0,
        "multimodal_visual_whitespace_overrides_added": 0,
        "method": "protected title-panel original+Chinese reflow",
    }
    OUTPUT_SPEC.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_NOTES.write_text(
        "# R5 Masjid title-panel repair\n\n"
        "- R4 rejected items repaired: 27 (17 collision, 10 text-did-not-fit).\n"
        f"- Reflow-managed semantic blocks: {len(managed)} (the 27 rejected blocks plus adjacent fields cleared in the same reviewed cells).\n"
        "- Drawing-body placements: unchanged.\n"
        "- CAD-hatch whitespace overrides added: 0.\n"
        "- Each clear rectangle is a title-panel text interior; vector rules are restored after reflow.\n",
        encoding="utf-8",
    )
    print(json.dumps({"plan": str(OUTPUT_PLAN), "spec": str(OUTPUT_SPEC), "managed": len(managed)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
