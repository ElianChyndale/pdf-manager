# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""R13 masked-callout variant: replace only source glyph ink, never CAD areas."""

import json
import math

from build_masjid_r12_mandatory_body import OUTPUT_PLAN as R12_PLAN, main as build_r12


OUTPUT_PLAN = R12_PLAN.parent / "v3.4-r13-masked-body-plan.json"


def _callout_target(source: list[float], text: str) -> list[float]:
    """A fixed within-footprint text box; its background is never painted."""
    width = max(source[2] - source[0], min(148.0, 12.0 + len(text) * 3.15))
    lines = max(1, math.ceil((len(text) * 3.15) / max(width - 4.0, 1.0)))
    height = max(source[3] - source[1] + 3.0, lines * 4.0 + 4.0)
    return [source[0], source[1], min(1036.0, source[0] + width), min(834.0, source[1] + height)]


def main() -> None:
    build_r12()
    plan = json.loads(R12_PLAN.read_text(encoding="utf-8"))
    for block in plan["semantic_blocks"]:
        block_id = str(block["block_id"])
        placement = block.get("placement") or {}
        if block_id.startswith("r12-mandatory-"):
            source = [float(value) for value in block["source_bbox"]]
            placement.update({
                "mode": "table_cell", "side": "below",
                "selected_region": _callout_target(source, str(block["translated_text"])),
                "candidate_regions": [], "font_size": 2.8, "rotation": 0,
                "render_text": str(block["translated_text"]), "color": [0.06, 0.18, 0.52],
                "preserve_source": False, "exact_ink_masks": [source],
                "instruction": "R13: exact source-glyph mask only; retype parameter-complete Chinese in the original annotation footprint. Do not paint a panel or erase leaders/CAD geometry.",
            })
        # Keep the sidebar companion close to its source cell; the R12 remote
        # bottom workaround is intentionally not carried forward.
        if block_id in {"r8-sidebar-p001-mechanical", "r8-sidebar-p004-mechanical"}:
            placement.update({
                "selected_region": [966.0, 515.0, 1034.0, 527.0],
                "render_text": "机械工程", "font_size": 3.0,
                "instruction": "R13 concise black companion in the nearest left annotation band; original mechanical firm cell remains intact.",
            })
            block["translated_text"] = "机械工程"
        block["placement"] = placement
    plan["r13_masked_callout_policy"] = "Only exact source glyph masks may be erased; no broad white drawing-body panels."
    OUTPUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(OUTPUT_PLAN), "masked_callouts": 27}, ensure_ascii=False))


if __name__ == "__main__":
    main()
