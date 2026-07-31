# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""Regroup Masjid title/sidebar text into one bilingual paragraph per cell."""

import json
from copy import deepcopy
from pathlib import Path

from build_masjid_r6_full_sidebar_reflow import ARTIFACT, INPUT_PLAN, fields_for_page, wrap_for_cell


OCR = ARTIFACT / "v3.3-supervised-hybrid-ocr.json"
OUTPUT_PLAN = ARTIFACT / "v3.3-r7-grouped-sidebar-reflow-plan.json"
OUTPUT_SPEC = ARTIFACT / "v3.3-r7-grouped-sidebar-reflow.json"
OUTPUT_NOTES = ARTIFACT / "v3.3-r7-grouped-sidebar-reflow-notes.md"


GROUPS = (
    ("land-owner", ("land-owner-label", "land-owner-detail"), "land-owner-detail"),
    ("building-owner", ("building-owner-label", "building-owner-detail"), "building-owner-detail"),
    ("project", ("project",), "project"),
    ("revision", ("revision-header",), "revision-header"),
    ("agency", ("agency-label", "agency-detail"), "agency-detail"),
    ("applicant", ("applicant-label", "applicant-detail"), "applicant-detail"),
    ("architect", ("architect-label", "architect-detail"), "architect-detail"),
    ("civil", ("civil-label", "civil-detail"), "civil-detail"),
    ("mechanical", ("mechanical-label", "mechanical-detail"), "mechanical-detail"),
    ("electrical", ("electrical-label", "electrical-detail"), "electrical-detail"),
    ("quantity", ("quantity-label", "quantity-detail"), "quantity-detail"),
    ("landscape", ("landscape-label", "landscape-detail"), "landscape-detail"),
    ("notes", ("copyright-and-notes",), "copyright-and-notes"),
    ("status", ("drawing-status",), "drawing-status"),
    ("title", ("drawing-title",), "drawing-title"),
    ("metadata", ("drawing-metadata",), "drawing-metadata"),
)


def center_in(rect: list[float], bbox: list[float]) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return rect[0] - 0.5 <= cx <= rect[2] + 0.5 and rect[1] - 0.5 <= cy <= rect[3] + 0.5


def union(rects: list[list[float]]) -> list[float]:
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]


def unwrapped_text(raw: str) -> str:
    # R6 prewrapped physical lines. R7 needs one coherent field paragraph;
    # preserve paragraph breaks but join artificial wraps with spaces.
    return " ".join(part.strip() for part in str(raw).splitlines() if part.strip())


def source_masks_from_ocr(ocr_regions: list[dict], areas: list[list[float]]) -> list[list[float]]:
    masks: list[list[float]] = []
    for region in ocr_regions:
        bbox = region.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        if not any(center_in(area, bbox) for area in areas):
            continue
        # The left lower landscape wordmark is part of the protected logo, not
        # a text field.  Do not make a text mask over it.
        if bbox[1] >= 650 and bbox[0] < 1093:
            continue
        masks.append([round(float(v), 3) for v in bbox])
    unique: list[list[float]] = []
    for item in masks:
        if item not in unique:
            unique.append(item)
    return unique


def main() -> None:
    plan = json.loads(INPUT_PLAN.read_text(encoding="utf-8"))
    ocr = json.loads(OCR.read_text(encoding="utf-8"))["regions"]
    title_blocks = [block for block in plan["semantic_blocks"] if block["source_bbox"][0] >= 1035]
    body_blocks = [block for block in plan["semantic_blocks"] if block["source_bbox"][0] < 1035]
    grouped_blocks: list[dict] = []
    panels: list[dict] = []
    assigned: set[str] = set()

    for page_index in range(4):
        originals = {item["key"]: item for item in fields_for_page(page_index)}
        page_ocr = [item for item in ocr if int(item.get("page_index", -1)) == page_index]
        panel_id = f"masjid-r7-sidebar-p{page_index + 1:03d}"
        panel_fields: list[dict] = []
        clear_regions: list[list[float]] = []
        for group_key, member_keys, layout_key in GROUPS:
            field_members = [originals[key] for key in member_keys]
            layout = originals[layout_key]
            mask_areas = [rect for item in field_members for rect in item["source_masks"]]
            # Paddle supplies the matched source observations, but its small
            # glyph rectangles fragment and occasionally miss a character in
            # these raster company panels.  The supervisor has reconciled each
            # observation into its exact visual *source text bbox* below.  We
            # mask only those source bboxes -- never the larger selected layout
            # cell -- so rules and logos are still protected.
            masks = [list(rect) for rect in mask_areas]
            # A one-cell semantic block owns every original V3 title/sidebar
            # block whose source anchor belongs to its reviewed text areas.
            members = [
                block
                for block in title_blocks
                if block["page_index"] == page_index
                and any(center_in(area, block["source_bbox"]) for area in mask_areas)
            ]
            for block in members:
                assigned.add(block["block_id"])
            source_text = "\n".join(str(block["source_text"]) for block in members).strip()
            # The visible paragraph is exactly once per visual cell. It keeps
            # source then Chinese content together, while the plan records a
            # single coherent Chinese semantic target for the whole field.
            visible_text = wrap_for_cell(
                "\n".join(unwrapped_text(item["text"]) for item in field_members),
                layout["selected_region"][2] - layout["selected_region"][0],
            )
            field_id = f"{panel_id}-{group_key}"
            panel_fields.append(
                {
                    "field_id": field_id,
                    "selected_region": layout["selected_region"],
                    "text": visible_text,
                    "font": "simhei",
                    "max_size": layout["max_size"],
                    "min_size": max(1.8, float(layout["min_size"])),
                    "lineheight": 0.94,
                    "source_bbox_masks": masks,
                    "mask_semantics": "reviewed_source_text_bboxes_only",
                }
            )
            clear_regions.extend(masks)
            if not members:
                continue
            source_bbox = union([block["source_bbox"] for block in members])
            translated = "；".join(dict.fromkeys(str(block["translated_text"]) for block in members if str(block["translated_text"]).strip()))
            grouped_blocks.append(
                {
                    "block_id": f"r7-sidebar-p{page_index + 1:03d}-{group_key}",
                    "member_ids": [member_id for block in members for member_id in block["member_ids"]],
                    "page_index": page_index,
                    "coverage_status": "translated",
                    "source_text": source_text,
                    "translated_text": translated or "标题栏字段中文重排",
                    "source_bbox": source_bbox,
                    "layout_role": "title_sidebar_visual_cell",
                    "placement": {
                        "side": "below",
                        "mode": "title_block",
                        "selected_region": layout["selected_region"],
                        "candidate_regions": [],
                        "font_size": max(2.8, min(6.0, float(layout["max_size"]))),
                        "rotation": 0,
                        "leader_path": [],
                        "panel_reflow_managed": True,
                        "panel_reflow_panel_id": panel_id,
                        "panel_reflow_field_id": field_id,
                        "panel_reflow_target_bbox": layout["selected_region"],
                        "text_color": "#000000",
                        "opaque_background": "matched_ocr_glyph_masks_then_one_bilingual_paragraph",
                        "preserve_source": False,
                        "allow_source_overlap": False,
                        "allow_dense_source_overlap": False,
                        "multimodal_visual_whitespace_override": False,
                        "instruction": "R7 单视觉单元：仅清理该单元匹配 OCR 字形框；在右侧文字列或完整无徽标单元内一次性排版黑色原文+中文段落。",
                    },
                }
            )
        panels.append(
            {
                "panel_id": panel_id,
                "page_index": page_index,
                "clear_mode": "white_overlay",
                "clear_regions": clear_regions,
                "fields": panel_fields,
                "visual_review": {
                    "mask_rule": "reviewed matched source text bboxes only",
                    "layout_rule": "one bilingual paragraph in selected_region per visual cell",
                    "protected": "logos, seals, borders, signatures and drawing body",
                },
            }
        )
    expected = {block["block_id"] for block in title_blocks}
    if assigned != expected:
        raise ValueError(f"unassigned title/sidebar blocks: {sorted(expected - assigned)}")
    plan["semantic_blocks"] = [*body_blocks, *grouped_blocks]
    spec = {
        "schema": "engineering-drawing-grouped-sidebar-reflow-v3",
        "source_plan": str(INPUT_PLAN),
        "restore_vector_rules": True,
        "mask_semantics": "reviewed matched source text bboxes only",
        "panels": panels,
        "visual_cell_count": len(grouped_blocks),
    }
    plan["status"] = "repair"
    plan["repair_parent_plan"] = str(INPUT_PLAN)
    plan["panel_reflow_spec"] = str(OUTPUT_SPEC)
    plan["panel_reflow_review"] = {
        "prior_tiny_sidebar_blocks": len(title_blocks),
        "grouped_visual_cell_blocks": len(grouped_blocks),
        "drawing_body_blocks_changed": 0,
        "mask_semantics": spec["mask_semantics"],
        "multimodal_visual_whitespace_overrides_added": 0,
    }
    OUTPUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_SPEC.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_NOTES.write_text(
        "# R7 grouped sidebar visual-cell reflow\n\n"
        f"- Tiny sidebar/title semantic blocks regrouped: {len(title_blocks)} -> {len(grouped_blocks)}.\n"
        "- Each company/sidebar visual cell renders exactly one black bilingual paragraph.\n"
        "- Only matched OCR glyph source bboxes are masked; selected layout regions are not redactions.\n"
        "- Logos, borders, seals, signatures and drawing-body layouts remain protected.\n",
        encoding="utf-8",
    )
    print(json.dumps({"plan": str(OUTPUT_PLAN), "spec": str(OUTPUT_SPEC), "grouped": len(grouped_blocks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
