# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""Build the Masjid R8 sidebar repair using two readable text zones per cell.

R7 proved that a single mixed-language paragraph is too dense for these title
cells.  R8 keeps the original compact source at the top/right and puts the
Chinese equivalent in a separate lower strip.  The strips are independently
fitted and every white mask is a reviewed source-ink rectangle, never a logo
or a cell-wide redaction.
"""

import json
from copy import deepcopy

from build_masjid_r6_full_sidebar_reflow import ARTIFACT, INPUT_PLAN, fields_for_page
from build_masjid_r7_grouped_sidebar_reflow import GROUPS, center_in, union


OUTPUT_PLAN = ARTIFACT / "v3.3-r8-two-zone-sidebar-reflow-plan.json"
OUTPUT_SPEC = ARTIFACT / "v3.3-r8-two-zone-sidebar-reflow.json"
OUTPUT_NOTES = ARTIFACT / "v3.3-r8-two-zone-sidebar-reflow-notes.md"


# [source box, Chinese box].  Company logos live to the left of x=1093 and are
# deliberately outside the reflow zones.  The Chinese strip has the larger
# usable lower/right area and is kept at 3pt or above where the cell permits.
ZONES = {
    "land-owner": ([1097, 76, 1164, 93], [1097, 94, 1164, 108]),
    "building-owner": ([1097, 128, 1164, 145], [1097, 147, 1164, 162]),
    "project": ([1044, 176, 1164, 190], [1044, 192, 1164, 207]),
    "revision": ([1044, 242, 1164, 247], [1044, 248, 1164, 253]),
    "agency": ([1097, 279, 1164, 299], [1097, 301, 1164, 321]),
    "applicant": ([1079, 352, 1164, 369], [1079, 371, 1164, 390]),
    "architect": ([1097, 398, 1164, 416], [1097, 418, 1164, 435]),
    "civil": ([1097, 450, 1164, 466], [1097, 468, 1164, 482]),
    "mechanical": ([1097, 498, 1164, 515], [1097, 517, 1164, 532]),
    "electrical": ([1097, 548, 1164, 565], [1097, 567, 1164, 580]),
    "quantity": ([1097, 597, 1164, 614], [1097, 616, 1164, 630]),
    "landscape": ([1097, 646, 1164, 662], [1097, 664, 1164, 680]),
    "notes": ([1044, 682, 1164, 691], [1044, 692, 1164, 701]),
    "status": ([1044, 703, 1164, 712], [1044, 714, 1164, 724]),
    "title": ([1044, 727, 1114, 746], [1044, 748, 1114, 769]),
    "metadata": ([1044, 772, 1164, 789], [1044, 791, 1164, 812]),
}


def texts(page: int) -> dict[str, tuple[str, str]]:
    title_source = (
        "MASJID | PELAN TINGKAT BAWAH",
        "MASJID | PELAN BUMBUNG / MENARA",
        "MASJID | PANDANGAN HADAPAN / BELAKANG / SISI",
        "MASJID | KERATAN A-A HINGGA E-E",
    )[page]
    title_zh = (
        "清真寺｜底层平面图",
        "清真寺｜屋面及塔楼平面图",
        "清真寺｜正、后及侧立面图",
        "清真寺｜A-A 至 E-E 剖面图",
    )[page]
    return {
        "land-owner": ("PEMILIK TANAH | MAJLIS AGAMA ISLAM SELANGOR\nTINGKAT 9 & 10, MENARA UTARA, SHAH ALAM", "土地所有者｜雪兰莪伊斯兰宗教理事会\n地址：莎阿南苏丹依德理斯沙大厦北塔 9–10 层"),
        "building-owner": ("PEMILIK BANGUNAN | JABATAN AGAMA ISLAM SELANGOR\nMENARA SELATAN, SHAH ALAM", "建筑业主｜雪兰莪伊斯兰宗教局\n地址：莎阿南苏丹依德理斯沙大厦南塔"),
        "project": ("PROJEK | CADANGAN BINA SEMULA MASJID AL-EHSAN\nKAMPUNG TOK MUDA, KAPAR, KLANG", "项目｜拟拆除并重建 Al-Ehsan 清真寺\n地点：雪兰莪州巴生县卡帕托穆达村"),
        "revision": ("BIL. | TARIKH | PINDAAN | DISEMAK", "编号｜日期｜修订｜审核"),
        "agency": ("AGENSI PELAKSANA | JABATAN KERJA RAYA SELANGOR\nKOMPLEKS JKR, SEKSYEN 17, SHAH ALAM", "实施机构｜雪兰莪公共工程局\n地址：莎阿南第 17 区州公共工程局总部"),
        "applicant": ("PEMOHON | AR. MOHD AZAHARI BIN MAD ATAN\nARKITEK | LAM A/M 91", "申请人｜莫哈末·阿扎哈里·本·马德·阿坦\n建筑师｜马来西亚建筑师委员会注册 A/M 91"),
        "architect": ("ARKITEK | AC ARCHITECTS SDN BHD\nPANDAN INDAH, SELANGOR", "建筑师｜AC Architects 有限公司\n地址：雪兰莪州班登英达"),
        "civil": ("JURUTERA SIVIL & STRUKTUR | UNITI CONSULTANTS\nSEREMBAN, NEGERI SEMBILAN", "土木与结构工程师｜UNITI 顾问有限公司\n地址：森美兰州芙蓉"),
        "mechanical": ("JURUTERA MEKANIKAL | JKR SELANGOR\nSEKSYEN 17, SHAH ALAM", "机械工程师｜雪兰莪公共工程局\n地址：莎阿南第 17 区"),
        "electrical": ("JURUTERA ELEKTRIK | JKR SELANGOR\nSEKSYEN 17, SHAH ALAM", "电气工程师｜雪兰莪公共工程局\n地址：莎阿南第 17 区"),
        "quantity": ("JURUKUR BAHAN | AZIZI, AZIZI & PARTNERS\nSEKSYEN 13, SHAH ALAM", "工料测量师｜Azizi, Azizi & Partners\n地址：莎阿南第 13 区"),
        "landscape": ("PERUNDING LANDSKAP | LAMAN TBG SDN BHD\nKAJANG, SELANGOR", "景观顾问｜Laman TBG 有限公司\n地址：雪兰莪州加影"),
        "notes": ("COPYRIGHT | CHECK ALL DIMENSIONS ON SITE", "版权说明｜承包商须现场核对全部尺寸"),
        "status": ("DRAWING STATUS | CONSTRUCTION", "图纸状态｜施工"),
        "title": (title_source, title_zh),
        "metadata": (f"SKALA 1:200 | DILUKIS apiz | JULAI 2025\nACASB 2401/MTM/M/WD-0{page + 1}", f"比例 1:200｜绘图 apiz｜日期：2025 年 7 月\n图纸编号：ACASB 2401/MTM/M/WD-0{page + 1}"),
    }


def safe_masks(field_members: list[dict]) -> list[list[float]]:
    masks = [list(mask) for item in field_members for mask in item["source_masks"]]
    # This particular lower-left rectangle is the LAMAN TBG logo wordmark,
    # not reflowable text.  It must remain untouched.
    return [
        mask for mask in masks
        if not (650 <= mask[1] <= 680 and mask[0] < 1093)
    ]


def reflow_masks(group_key: str, masks: list[list[float]]) -> list[list[float]]:
    """Keep source role labels when a logo/company cell has no room for them.

    The original left-side Malay role label is already a compact source cue.
    Reflow only the right text column, which prevents a third text layer from
    competing with the crest/logo and gives the Chinese lower strip a clean
    visual hierarchy.
    """
    company_cells = {"land-owner", "building-owner", "agency", "applicant", "architect", "civil", "mechanical", "electrical", "quantity", "landscape"}
    if group_key in company_cells:
        return [mask for mask in masks if mask[0] >= 1090]
    return masks


def main() -> None:
    plan = json.loads(INPUT_PLAN.read_text(encoding="utf-8"))
    title_blocks = [block for block in plan["semantic_blocks"] if block["source_bbox"][0] >= 1035]
    body_blocks = [block for block in plan["semantic_blocks"] if block["source_bbox"][0] < 1035]
    inventory = list(plan["coverage_inventory"])
    grouped: list[dict] = []
    panels: list[dict] = []
    assigned: set[str] = set()

    for page_index in range(4):
        original = {item["key"]: item for item in fields_for_page(page_index)}
        content = texts(page_index)
        panel_id = f"masjid-r8-sidebar-p{page_index + 1:03d}"
        fields: list[dict] = []
        clears: list[list[float]] = []
        for group_key, member_keys, _layout_key in GROUPS:
            members = [original[key] for key in member_keys]
            coverage_masks = [list(mask) for item in members for mask in item["source_masks"]]
            masks = reflow_masks(group_key, safe_masks(members))
            label_masks = [mask for mask in safe_masks(members) if mask[0] < 1090]
            source_zone, chinese_zone = ZONES[group_key]
            source_text, chinese_text = content[group_key]
            # The original role label remains at the left.  A single compact
            # source company/name line above the Chinese strip is materially
            # clearer than retyping a microscopic postal address.
            if group_key in {"land-owner", "building-owner", "agency", "applicant", "architect", "civil", "mechanical", "electrical", "quantity", "landscape"}:
                source_lines = source_text.splitlines()
                source_text = "\n".join([
                    source_lines[0].split("|", 1)[-1].strip(),
                    *source_lines[1:],
                ])
                chinese_text = "\n".join(
                    line.split("｜", 1)[-1].strip() if "｜" in line else line
                    for line in chinese_text.splitlines()
                )
            field_root = f"{panel_id}-{group_key}"
            role_text = content[group_key][0].splitlines()[0].split("|", 1)[0].strip()
            role_fields = []
            if label_masks and group_key in {"land-owner", "building-owner", "agency", "applicant", "architect", "civil", "mechanical", "electrical", "quantity", "landscape"}:
                role_fields.append({
                    "field_id": f"{field_root}-role-source",
                    "selected_region": union(label_masks),
                    "text": role_text,
                    "font": "hebo",
                    "max_size": 2.7,
                    "min_size": 2.2,
                    "lineheight": 0.86,
                    "source_bbox_masks": label_masks,
                    "mask_semantics": "reviewed_role_text_glyph_bounds_only",
                })
            fields.extend((
                *role_fields,
                {
                    "field_id": f"{field_root}-source",
                    "selected_region": source_zone,
                    "text": source_text,
                    "font": "hebo",
                    "max_size": 2.8 if group_key not in {"revision", "notes", "status"} else 3.0,
                    "min_size": 2.3,
                    "lineheight": 0.9,
                    "source_bbox_masks": masks,
                    "mask_semantics": "reviewed_text_glyph_bounds_only",
                },
                {
                    "field_id": f"{field_root}-zh",
                    "selected_region": chinese_zone,
                    "text": chinese_text,
                    "font": "simhei",
                    "max_size": 3.5 if group_key not in {"revision", "notes", "status"} else 3.1,
                    "min_size": 3.0 if group_key not in {"revision", "notes", "status"} else 2.8,
                    "lineheight": 0.9,
                    "source_bbox_masks": [],
                    "mask_semantics": "no_source_mask_chinese_lower_strip",
                },
            ))
            clears.extend([*label_masks, *masks])
            owned = [
                block for block in title_blocks
                if block["page_index"] == page_index
                and any(center_in(mask, block["source_bbox"]) for mask in coverage_masks)
            ]
            # A visual cell owns the native source plus all supervised OCR
            # observations whose centres fall in its reviewed source text
            # masks.  This is semantic duplicate grouping, not an inventory
            # exemption: every such candidate receives the same visible
            # Chinese lower strip.
            inventory_members = [
                item for item in inventory
                if int(item.get("page_index", -1)) == page_index
                and any(center_in(mask, item.get("source_bbox") or []) for mask in coverage_masks)
            ]
            assigned.update(block["block_id"] for block in owned)
            if not owned:
                continue
            source_bbox = union([block["source_bbox"] for block in owned])
            target = union([source_zone, chinese_zone])
            grouped.append({
                "block_id": f"r8-sidebar-p{page_index + 1:03d}-{group_key}",
                "member_ids": list(dict.fromkeys([
                    *(member_id for block in owned for member_id in block["member_ids"]),
                    *(str(item["candidate_id"]) for item in inventory_members),
                ])),
                "page_index": page_index,
                "coverage_status": "translated",
                "source_text": "\n".join(str(block["source_text"]) for block in owned),
                "translated_text": chinese_text,
                "source_bbox": source_bbox,
                "layout_role": "title_sidebar_two_zone_cell",
                "placement": {
                    "side": "below", "mode": "title_block", "selected_region": target,
                    "candidate_regions": [], "font_size": 3.0, "rotation": 0, "leader_path": [],
                    "panel_reflow_managed": True, "panel_reflow_panel_id": panel_id,
                    "panel_reflow_field_id": f"{field_root}-zh", "panel_reflow_target_bbox": target,
                    "text_color": "#000000", "opaque_background": "reviewed_source_glyph_masks_two_zone_reflow",
                    "preserve_source": False, "allow_source_overlap": False,
                    "allow_dense_source_overlap": False, "multimodal_visual_whitespace_override": False,
                    "instruction": "R8：原文紧凑重排在上/右区；完整中文置于独立下方条带。仅清理逐项复核的原始文本墨迹，绝不清理徽标、边框或绘图主体。",
                },
            })
        panels.append({
            "panel_id": panel_id, "page_index": page_index, "clear_mode": "white_overlay",
            "clear_regions": clears, "fields": fields,
            "visual_review": {
                "mask_rule": "reviewed source text glyph bboxes only; never selected layout zones",
                "layout_rule": "two fields per visual cell: compact original upper/right plus Chinese lower strip",
                "protected": "logos, seals, borders, signatures and drawing body",
            },
        })
    expected = {block["block_id"] for block in title_blocks}
    if assigned != expected:
        raise ValueError(f"unassigned title/sidebar blocks: {sorted(expected - assigned)}")
    grouped_member_ids = {member_id for block in grouped for member_id in block["member_ids"]}
    # Coverage inventory status must agree with the semantic ownership above:
    # an OCR duplicate in a translated visual cell is translated, not
    # ``not_needed``.
    for item in plan["coverage_inventory"]:
        if str(item.get("candidate_id")) in grouped_member_ids:
            item["status"] = "translated"
            item["reason"] = "semantic duplicate owned by reviewed R8 visual cell"
    plan["semantic_blocks"] = [*body_blocks, *grouped]
    spec = {"schema": "engineering-drawing-two-zone-sidebar-reflow-v3", "source_plan": str(INPUT_PLAN),
            "restore_vector_rules": True, "mask_semantics": "reviewed source glyph bboxes only", "panels": panels,
            "visual_cell_count": len(grouped), "fields_per_visual_cell": 2}
    plan.update({"status": "repair", "repair_parent_plan": str(INPUT_PLAN), "panel_reflow_spec": str(OUTPUT_SPEC),
                 "panel_reflow_review": {"prior_tiny_sidebar_blocks": len(title_blocks), "grouped_visual_cell_blocks": len(grouped),
                 "drawing_body_blocks_changed": 0, "two_zone_fields": len(grouped) * 2,
                 "mask_semantics": spec["mask_semantics"]}})
    OUTPUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_SPEC.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_NOTES.write_text(
        "# R8 two-zone sidebar reflow\n\n"
        f"- Sidebar semantic blocks regrouped: {len(title_blocks)} -> {len(grouped)}.\n"
        "- Every visual cell has a compact original upper/right field and a separate Chinese lower-strip field.\n"
        "- Only reviewed source text masks are cleared; logos and rules are not touched.\n", encoding="utf-8")
    print(json.dumps({"plan": str(OUTPUT_PLAN), "spec": str(OUTPUT_SPEC), "grouped": len(grouped)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
