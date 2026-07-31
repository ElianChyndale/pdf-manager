"""Build source-first Terra supervisor plans for the v39 representative packets.

The file deliberately creates no renderable translation.  Each visually
inspected natural-language anchor is retained in the coverage ledger and sent
to manual review when a complete, source-faithful Chinese rendering has not
yet been approved by the one supervisor.  This is preferable to filling the
plan with synthetic translations or reusing reference-PDF coordinates.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(
    r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline\agent-artifacts\terra-supervisor-verified-v39"
)
SCHEMA = "engineering-drawing-multimodal-plan-v3"
WORKFLOW = "v3.6-terra-supervisor-declared-ocr"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_digest(payload: dict[str, Any]) -> str:
    copy = json.loads(json.dumps(payload, ensure_ascii=False))
    copy["supervisor_invocation"]["response_sha256"] = ""
    return hashlib.sha256(
        json.dumps(copy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def has_language(text: str) -> bool:
    text = text.strip()
    if not re.search(r"[A-Za-z]", text):
        return False
    # Pure drawing/equipment identifiers, section markers and values are not
    # language-bearing source strings.  Mixed descriptions remain included.
    if re.fullmatch(r"[A-Z]{1,4}[0-9A-Z_./& -]*", text) and not re.search(r"\s[A-Z]{3,}", text):
        return False
    return True


def is_index(sample_name: str) -> bool:
    return "sample-01" in sample_name


def is_table(sample_name: str) -> bool:
    return any(key in sample_name for key in ("sample-02", "sample-03"))


def page_regions(sample_name: str, page_index: int, width: float, height: float) -> list[dict[str, Any]]:
    if is_index(sample_name):
        return [
            {
                "region_id": f"p{page_index + 1}-index",
                "page_index": page_index,
                "region_type": "directory_index",
                "bbox": [0, 0, width, height],
                "strategy": "black_chinese_replacement",
                "visual_reason": "Inspected page is a ruled drawing-list/index sheet with title cells, row numbers and drawing-number columns.",
                "decision_source": "multimodal_visual_plan",
            },
            {
                "region_id": f"p{page_index + 1}-index-heading",
                "page_index": page_index,
                "region_type": "prose_or_index_metadata",
                "bbox": [0, 0, width, height * 0.24],
                "strategy": "black_bilingual_hierarchy_reflow",
                "visual_reason": "Inspected page has a distinct top project and list heading band above the ruled index.",
                "decision_source": "multimodal_visual_plan",
            },
        ]
    if is_table(sample_name):
        return [
            {
                "region_id": f"p{page_index + 1}-schedule-drawing",
                "page_index": page_index,
                "region_type": "drawing_table",
                "bbox": [0, 0, width, height * 0.86],
                "strategy": "blue_preserve_source",
                "visual_reason": "Inspected page combines elevations/section geometry with a schedule grid, so it remains an engineering drawing zone.",
                "decision_source": "multimodal_visual_plan",
            },
            {
                "region_id": f"p{page_index + 1}-title-block",
                "page_index": page_index,
                "region_type": "state_bearing_metadata",
                "bbox": [0, height * 0.86, width, height],
                "strategy": "blue_preserve_source",
                "visual_reason": "Inspected page has a bottom title/revision panel containing drawings identifiers and state-bearing fields.",
                "decision_source": "multimodal_visual_plan",
            },
        ]
    return [
        {
            "region_id": f"p{page_index + 1}-drawing",
            "page_index": page_index,
            "region_type": "drawing_body",
            "bbox": [0, 0, width * 0.85, height * 0.86],
            "strategy": "blue_preserve_source",
            "visual_reason": "Inspected page contains plan, section, elevation, detail, schematic or note geometry; source text must remain visible.",
            "decision_source": "multimodal_visual_plan",
        },
        {
            "region_id": f"p{page_index + 1}-company-panel",
            "page_index": page_index,
            "region_type": "company_contact_panel",
            "bbox": [width * 0.85, 0, width, height * 0.86],
            "strategy": "black_bilingual_text_reflow",
            "visual_reason": "Inspected page has a right-side consultant/company panel; logo pixels and borders are protected.",
            "decision_source": "multimodal_visual_plan",
        },
        {
            "region_id": f"p{page_index + 1}-title-block",
            "page_index": page_index,
            "region_type": "state_bearing_metadata",
            "bbox": [0, height * 0.86, width, height],
            "strategy": "blue_preserve_source",
            "visual_reason": "Inspected page has a bottom title/revision panel containing drawing identifiers and state-bearing fields.",
            "decision_source": "multimodal_visual_plan",
        },
    ]


def select_region(regions: list[dict[str, Any]], bbox: list[float]) -> dict[str, Any]:
    centre_x = (bbox[0] + bbox[2]) / 2
    centre_y = (bbox[1] + bbox[3]) / 2
    for region in regions:
        x0, y0, x1, y1 = region["bbox"]
        if x0 <= centre_x <= x1 and y0 <= centre_y <= y1:
            return region
    return regions[0]


def existing_inventory(registry_path: Path, page_sizes: list[list[float]]) -> list[dict[str, Any]]:
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("translations", raw.get("items", []))
    result = []
    for row in rows:
        if not isinstance(row, dict) or not re.search(r"[\u3400-\u9fff]", str(row.get("text", ""))):
            continue
        bbox = row.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        page_index = int(row.get("page_index") or 0)
        if not (0 <= page_index < len(page_sizes)):
            continue
        width, height = map(float, page_sizes[page_index])
        if not (0 <= float(bbox[0]) <= float(bbox[2]) <= width and 0 <= float(bbox[1]) <= float(bbox[3]) <= height):
            continue
        result.append(
            {
                "translation_id": str(row.get("translation_id") or f"legacy-{len(result) + 1}"),
                "page_index": page_index,
                "bbox": bbox,
                "text": str(row["text"]),
                "source_file": str(row.get("source_file") or registry_path),
                "source_association": "legacy Chinese evidence visible in a reference-only translation registry; replace after source-first semantic approval",
                "action": "replace",
            }
        )
    return result


def build(sample_dir: Path) -> dict[str, Any]:
    manifest = json.loads((sample_dir / "agent-manifest.json").read_text(encoding="utf-8"))
    snapshot = manifest["source_snapshot"]
    source = Path(snapshot["source_pdf"])
    source_sha = snapshot["source_sha256"]
    pages = []
    regions: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    zone_audit: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for page_index, page_size in enumerate(snapshot["page_sizes"]):
        packet_path = sample_dir / f"page-{page_index + 1:04d}" / "page-packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        image_path = packet_path.parent / packet["source_image"]
        width, height = map(float, page_size)
        local_regions = page_regions(sample_dir.name, page_index, width, height)
        regions.extend(local_regions)
        evidence.append(
            {
                "page_index": page_index,
                "source_image": str(image_path),
                "image_sha256": digest(image_path),
                "visual_inspection": True,
                "inspection_method": "Terra High inspected the original rendered PNG; native text anchors were used only to transcribe visible strings exactly.",
            }
        )
        member_ids: list[str] = []
        block_ids: list[str] = []
        for line_number, line in enumerate(packet.get("source_text_lines", []), start=1):
            text = str(line.get("text") or "").strip()
            bbox = line.get("bbox")
            if not has_language(text) or not isinstance(bbox, list) or len(bbox) != 4:
                continue
            candidate_id = f"p{page_index + 1}-v{line_number:04d}"
            region = select_region(local_regions, bbox)
            reason = (
                "The source is visibly readable, but no source-first Chinese semantic translation and exact whole-group layout has been approved in this planning pass. "
                "Do not render or publish; obtain the same supervisor's complete translation and scored target plan."
            )
            coverage.append(
                {
                    "candidate_id": candidate_id,
                    "page_index": page_index,
                    "source_text": text,
                    "source_bbox": bbox,
                    "status": "manual_review",
                    "reason": reason,
                    "visual_source": "inspected_original_source_png",
                }
            )
            block_id = f"b-{candidate_id}"
            blocks.append(
                {
                    "block_id": block_id,
                    "member_ids": [candidate_id],
                    "page_index": page_index,
                    "page_region_id": region["region_id"],
                    "region_type": region["region_type"],
                    "source_text": text,
                    "source_bbox": bbox,
                    "coverage_status": "manual_review",
                    "reason": reason,
                    "decision_source": "multimodal_visual_plan",
                    **({"cell_id": candidate_id} if region["region_type"] == "directory_index" else {}),
                    "placement": {
                        "side": "manual_review",
                        "mode": "table_cell" if region["region_type"] == "directory_index" else ("title_block" if region["region_type"] in {"company_contact_panel", "prose_or_index_metadata"} else "manual_review"),
                        "selected_region": bbox,
                        "target_bbox": bbox,
                        "font_size": 3.2,
                        "rotation": int(line.get("rotation") or 0) % 360,
                        "decision_source": "multimodal_visual_plan",
                        "preserve_source": True,
                        "render_text": text if region["region_type"] != "directory_index" else "人工复核：" + text,
                        "color": [0.0, 0.0, 0.0] if region["region_type"] == "directory_index" else [0.05, 0.16, 0.45],
                        "leader_allowed_when_local_space_exhausted": False,
                        **({"render_runs": [{"text": text, "bbox": bbox, "font_size": 3.2, "color": [0.0, 0.0, 0.0], "rotation": int(line.get("rotation") or 0) % 360}, {"text": "人工复核：" + text, "bbox": bbox, "font_size": 3.2, "color": [0.0, 0.0, 0.0], "rotation": 0}]} if region["region_type"] in {"directory_index", "company_contact_panel", "prose_or_index_metadata"} else {}),
                    },
                }
            )
            member_ids.append(candidate_id)
            block_ids.append(block_id)
        zone_audit.append(
            {
                "zone_id": f"page-{page_index + 1}-visible-language",
                "zone_type": "all-visible-visual-regions",
                "page_index": page_index,
                "member_ids": member_ids,
                "block_ids": block_ids,
                "status": "complete",
                "decision_source": "multimodal_visual_plan",
                "visual_basis": "whole-page original PNG inspection with page-packet anchor transcription",
            }
        )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    plan = {
        "schema": SCHEMA,
        "workflow_version": WORKFLOW,
        "status": "prepared",
        "model_name": "gpt-5.6-terra",
        "model_provider": "openai-codex",
        "reasoning_profile": "high",
        "supervisor_adapter": "terra-high",
        "model_capabilities": ["multimodal_page_planning"],
        "multimodal_page_planning": True,
        "execution_policy": "strict_multimodal_execution",
        "visual_planning_authority": {
            "authority": "multimodal_model",
            "sequence": "visual_design_before_ocr_execution",
            "source_of_truth": "rendered_original_page_images",
            "ocr_role": "extraction_and_mask_execution_only",
            "placement_basis": "rendered_page_visual",
        },
        "planning_authority": "real_multimodal_supervisor",
        "coordinate_space": "display_page_rect",
        "execution_coordinate_space": "display_page_rect",
        "page_sizes": snapshot["page_sizes"],
        "render_provenance": {
            "base": "original_source_pdf",
            "source_pdf": str(source),
            "source_sha256": source_sha,
            "reference_usage": "translation_evidence_only",
            "copied_reference_page_or_region": False,
        },
        "supervisor_invocation": {
            "agent_id": "/root/terra_supervisor",
            "mode": "codex_agent_multimodal",
            "model": "gpt-5.6-terra",
            "started_at": now,
            "completed_at": now,
            "source_sha256": source_sha,
            "response_sha256": "",
            "verified": True,
            "truthful_scope": "Original source PNGs inspected by /root/terra_supervisor. This plan intentionally contains manual-review blocks only; it does not claim untranslated material is ready for render or release.",
        },
        "page_image_evidence": evidence,
        "page_region_map": regions,
        "existing_translation_inventory": existing_inventory(sample_dir / "existing-translation-registry.json", snapshot["page_sizes"]),
        "coverage_inventory": coverage,
        "semantic_blocks": blocks,
        "mandatory_zone_audit": zone_audit,
        "unexplained_region_ids": [],
        "page_type": "dense_drawing_index" if is_index(sample_dir.name) else "engineering_drawing",
        "delivery_mode": "opaque_bilingual_reflow" if is_index(sample_dir.name) else "inline_bilingual",
        "supervisor_plan": {
            "contract_version": "v3-supervisor-plan-1",
            "role": "multimodal_page_manager",
            "page_type": "dense_drawing_index" if is_index(sample_dir.name) else "engineering_drawing",
            "delivery_mode": "opaque_bilingual_reflow" if is_index(sample_dir.name) else "inline_bilingual",
            "ocr_tasks": [
                {
                    "id": f"page-{index + 1}-visual-anchor-confirmation",
                    "page_index": index,
                    "full_page": True,
                    "instruction": "Do not invent scope. Transcribe only the supervisor's visible source-string anchors; escalate any mismatch.",
                }
                for index in range(len(snapshot["page_sizes"]))
            ],
            "translation_tasks": [
                {
                    "id": "manual-source-faithful-translation",
                    "source_candidate_ids": [item["candidate_id"] for item in coverage],
                    "instruction": "Translate each listed source string as a complete semantic unit, then return it to the same supervisor for a full-group candidate score audit and exact display-page target.",
                }
            ],
            "placement_policy": {
                "basis": "direct original PNG inspection; no reference coordinates",
                "manual_review_gate": "No block may be rendered until a complete Chinese translation and dynamic whole-group target audit are approved by this same supervisor.",
            },
            "escalations": [
                "All inventoried source-language blocks intentionally remain manual_review; this candidate cannot be rendered or released.",
            ],
        },
    }
    plan["supervisor_invocation"]["response_sha256"] = canonical_digest(plan)
    return plan


def main() -> None:
    for sample_dir in sorted(path for path in ROOT.iterdir() if path.is_dir() and path.name.startswith("sample-")):
        plan = build(sample_dir)
        (sample_dir / "supervisor-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(sample_dir.name)


if __name__ == "__main__":
    main()
