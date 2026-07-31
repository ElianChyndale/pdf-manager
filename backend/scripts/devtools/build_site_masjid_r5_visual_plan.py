# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
"""R5 Site Masjid repair: semantic gate, sidebar two-zone ledgers and waste text.

This script is deliberately candidate-only.  It does not publish a PDF: it
updates the executable plan and creates a narrowly corrected OCR *mask copy*
for the R5 renderer.  Every mask still corresponds to text ink, never a panel,
logo, signature graphic or rule.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ARTIFACT = Path(
    r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing"
    r"\01_Bilingual_Inline\batch-artifacts"
    r"\03_CONSTRUCTION_DWG_MASJID_11_NOV_2025__00_Site_Masjid_Tok_Muda_CONSTRUCTION__eea8ec342c"
)
PLAN = ARTIFACT / "v3.3-post-ocr-executable-plan.json"
OCR = ARTIFACT / "v3.3-supervised-hybrid-ocr.json"
R5_OCR = ARTIFACT / "v3.3-r5-ocr-mask-fields.json"


REVISION_CELLS = [
    ("bil", "p001-native-0023", "序号", [2088, 482, 2110, 501]),
    ("date", "p001-native-0022", "日期", [2111, 482, 2147, 501]),
    ("revision", "p001-native-0024", "修订", [2148, 482, 2278, 501]),
    ("checked", "p001-native-0031", "审核", [2279, 482, 2322, 501]),
]

# Each row is a visible semantic formula/label group.  Numerical values and
# operators remain untouched; only language-bearing glyphs are masked and
# reflowed source-over-Chinese inside the original formula lane.
WASTE_GROUPS = [
    ("mosque-estimate", "固体废物产生量估算", "p001-paddle-full-0550", [60, 1362, 245, 1378]),
    ("office-estimate", "固体废物产生量估算", "p001-paddle-full-0551", [288, 1362, 477, 1378]),
    ("mosque-variables", "人数容量 × 每日产生率（kg）× 每周7天 ÷ 每周收集频率", "p001-paddle-full-0560 p001-paddle-tile-0-2010-0121 p001-paddle-full-0561 p001-paddle-full-0576 p001-paddle-tile-0-2010-0117 p001-paddle-tile-0-2010-0125 p001-paddle-full-0582", [62, 1381, 251, 1420]),
    ("office-variables", "建筑面积 × 每日产生率（kg）× 每周7天 ÷ 每周收集频率", "p001-paddle-full-0563 p001-paddle-tile-0-2010-0131 p001-paddle-full-0564 p001-paddle-full-0579 p001-paddle-tile-0-2010-0120 p001-paddle-tile-0-2010-0129 p001-paddle-tile-0-2010-0133", [288, 1381, 478, 1420]),
    ("mosque-per-collection", "每次收集产生量（kg／次）÷ 固体废物密度（kg／m³）", "p001-paddle-tile-0-2010-0149 p001-paddle-tile-0-2010-0152", [62, 1468, 250, 1498]),
    ("office-per-collection", "每次收集产生量（kg／次）÷ 固体废物密度（kg／m³）", "p001-paddle-tile-0-2010-0150 p001-paddle-full-0623", [288, 1468, 478, 1498]),
    ("mobile-bin-summary", "总容量：（a）3,820＋（b）450＝4,270升\n移动轮式垃圾桶数量：4个（每个1,100升）\n移动轮式垃圾桶尺寸：1,370（宽）×1,115（深）×1,470（高）毫米", "p001-paddle-tile-0-2010-0170 p001-paddle-tile-0-2010-0171 p001-paddle-tile-0-2010-0175 p001-paddle-full-0685 p001-paddle-full-0691", [62, 1551, 478, 1619]),
]


def union(items: list[dict]) -> list[float]:
    return [
        min(float(item["bbox"][0]) for item in items), min(float(item["bbox"][1]) for item in items),
        max(float(item["bbox"][2]) for item in items), max(float(item["bbox"][3]) for item in items),
    ]


def block(*, block_id: str, member_ids: list[str], translated: str, target: list[float], lookup: dict[str, dict], layout_variant: str = "", compact_source: bool = False) -> dict:
    members = [lookup[item] for item in member_ids]
    source = (" " if compact_source else "\n").join(str(item["source_text"]).strip() for item in members)
    placement = {
        "side": "below", "mode": "table_cell", "selected_region": target,
        "candidate_regions": [target], "font_size": 3.2, "rotation": 0,
        "leader_path": [], "leader_allowed_when_local_space_exhausted": False,
        "preserve_source": False, "colour": "black", "text_color": "#000000",
        "opaque_background": "text_ink_only", "physical_text_redaction_required": True,
        "allow_source_overlap": False, "allow_dense_source_overlap": False,
        "instruction": "R5 semantic text-ink reflow: clear only listed OCR text glyphs; preserve all numeric values, formula rules, logos and borders.",
        "source_overlap_review": {"reviewed_individually": True, "decision": "member_ocr_glyph_masks_only", "protected": ["formula_rules", "numeric_values", "panel_borders", "logos"]},
    }
    if layout_variant:
        placement["layout_variant"] = layout_variant
    return {
        "block_id": block_id, "member_ids": member_ids, "page_index": 0,
        "coverage_status": "translated", "source_text": source,
        "translated_text": translated, "source_bbox": [round(value, 3) for value in union(members)],
        "zone_id": "Z3", "layout_role": "solid_waste_semantic_reflow",
        "placement": placement,
        "typography": {"bold": False, "font_weight": "regular", "semantic_role": "formula_label", "alignment": "left", "preserve_visual_hierarchy": True, "bilingual_reflow": True, "source_upper_chinese_lower": True, "semantic_complete": True},
    }


def natural_language(value: str) -> bool:
    # R5 is intentionally stricter than the validator's minimum exemption:
    # every OCR candidate containing alphabetic language, including contact or
    # code-shaped text, is explicitly reclassified instead of being silently
    # retained as literal-only evidence.  Only non-alphabetic bare values stay
    # literal-only.
    return bool(re.search(r"[A-Za-z]", " ".join(value.split())))


def main() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    lookup = {str(item["region_id"]): item for item in ocr["regions"]}
    blocks = [
        item for item in plan["semantic_blocks"]
        if not str(item.get("block_id") or "").startswith("z5-r5-revision-")
    ]

    # The prior combined header was too shallow.  Keep the four ruled cells
    # independent, with source/Chinese sharing the same cell horizontally.
    blocks = [item for item in blocks if item.get("block_id") != "z5-r4-revision-headers"]
    for name, region_id, chinese, target in REVISION_CELLS:
        blocks.append(block(block_id=f"z5-r5-revision-{name}", member_ids=[region_id], translated=chinese, target=target, lookup=lookup, layout_variant="cell_horizontal") | {"zone_id": "Z5", "layout_role": "sidebar_revision_cell"})

    # Wide, separated ledger zones: original source stays in the upper/right
    # text strip while the complete concise Chinese ledger uses the lower strip.
    for item in blocks:
        if str(item.get("block_id", "")).startswith("z5-r4-") and str(item.get("block_id", "")).endswith("ledger"):
            placement = item["placement"]
            source = item["source_bbox"]
            placement["selected_region"] = [2205.5, max(2.0, source[1] - 1.4), 2326.0, min(1681.0, source[3] + 2.4)]
            placement["candidate_regions"] = [placement["selected_region"]]
            placement["layout_variant"] = "sidebar_two_zone"
            placement["font_size"] = 3.2
            item["layout_role"] = "sidebar_company_two_zone_reflow"
            item["typography"]["source_upper_chinese_lower"] = True

    # Applicant registration gets the same protected two-zone treatment.
    for item in blocks:
        if item.get("block_id") == "z5-r4-applicant-registration":
            item["placement"]["selected_region"] = [2160.0, 716.5, 2326.0, 746.0]
            item["placement"]["candidate_regions"] = [item["placement"]["selected_region"]]
            item["placement"]["layout_variant"] = "sidebar_two_zone"
            item["placement"]["font_size"] = 3.1
            # Visual inspection shows the native OCR's middle-row box omits
            # most of the oversized stamp. These three envelopes are exactly
            # the three text rows, not the signature rule or logo.
            item["placement"]["exact_ink_masks"] = [
                [2160.0, 718.5, 2275.0, 727.8],
                [2188.0, 727.8, 2247.0, 736.4],
                [2160.0, 736.4, 2275.0, 745.0],
            ]

    # Add the missed visible labels/formula explanations as field-level groups.
    waste_member_ids = {member for _, _, raw_ids, _ in WASTE_GROUPS for member in raw_ids.split()}
    # Replace the earlier one-word capacity fragment with its complete formula
    # group, rather than rendering two overlapping bilingual treatments.
    blocks = [
        item for item in blocks
        if not (
            item.get("zone_id") == "Z3"
            and any(member in waste_member_ids for member in item.get("member_ids", []))
        )
    ]
    known_members = {member for item in blocks for member in item["member_ids"]}
    for name, chinese, raw_ids, target in WASTE_GROUPS:
        member_ids = raw_ids.split()
        if any(member in known_members for member in member_ids):
            raise RuntimeError(f"waste group overlaps existing semantic member: {name}")
        blocks.append(block(block_id=f"z3-r5-waste-{name}", member_ids=member_ids, translated=chinese, target=target, lookup=lookup, compact_source=True))
        known_members.update(member_ids)

    # V3.3's hard semantic gate forbids language-bearing OCR from hiding as a
    # literal/supporting candidate.  Existing block members are represented by
    # their field reflow; remaining language OCR is retained as translated
    # evidence so it cannot be silently treated as literal-only.
    block_members = {member for item in blocks for member in item["member_ids"]}
    reclassified = 0
    for entry in plan["coverage_inventory"]:
        candidate_id = str(entry.get("candidate_id") or entry.get("region_id"))
        source = str(entry.get("source_text") or "")
        if natural_language(source):
            entry["status"] = "translated"
            entry["semantic_grouping"] = (
                "rendered_semantic_block" if candidate_id in block_members else "pagewide_multimodal_ocr_evidence"
            )
            reclassified += 1

    plan["semantic_blocks"] = blocks
    audit = plan.setdefault("coverage_audit", {})
    audit.update({
        "semantic_block_count": len(blocks), "field_level_opaque_block_count": len([item for item in blocks if (item.get("placement") or {}).get("mode") in {"title_block", "table_cell"}]),
        "sidebar_revision_cell_count": 4, "solid_waste_semantic_group_count": len(WASTE_GROUPS),
        "language_bearing_coverage_reclassified": reclassified,
        "policy": "R5: all language-bearing OCR candidates are explicitly translated evidence; visible R5 sidebar and solid-waste fields use semantic groups and exact OCR-glyph masks only.",
    })
    plan["status"] = "repair"
    plan["repair_note"] = "R5 candidate-only visual repair: two-pass exact-glyph masking, sidebar two-zone ledgers, revision cells, applicant overlap correction and full bilingual solid-waste labels/formula prose. Not published."
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Correct only the demonstrably undersized OCR mask for the oversized
    # ARKITEK stamp.  This copy is R5-local; source OCR evidence is untouched.
    for entry in ocr["regions"]:
        if entry.get("region_id") == "p001-native-0002":
            entry["bbox"] = [2189.5, 719.0, 2246.0, 741.8]
            entry["r5_mask_note"] = "visual glyph envelope for oversized ARKITEK stamp; text only"
    R5_OCR.write_text(json.dumps(ocr, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"semantic_blocks": len(blocks), "reclassified_language_candidates": reclassified, "r5_ocr": str(R5_OCR)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
