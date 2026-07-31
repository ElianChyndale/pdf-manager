from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping

from .semantic_knowledge import supervisor_knowledge_context


POST_OCR_SCHEMA = "engineering-drawing-post-ocr-supervision-v1"


def _candidate_union(
    native_lines: object, ocr_regions: list[dict]
) -> list[dict]:
    merged: list[dict] = []
    by_key: dict[tuple[str, tuple[float, ...], int], dict] = {}
    inputs = [
        ("native_pdf_text", item)
        for item in (native_lines if isinstance(native_lines, list) else [])
        if isinstance(item, Mapping)
    ] + [("ocr", item) for item in ocr_regions]
    for provenance, raw in inputs:
        text = str(raw.get("source_text") or raw.get("text") or "").strip()
        bbox = raw.get("bbox")
        if not text or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        normalized = re.sub(r"\W+", "", text.casefold())
        key = (normalized, tuple(round(float(value), 1) for value in bbox), int(raw.get("rotation", 0) or 0) % 360)
        if key in by_key:
            by_key[key]["provenance"] = sorted(set(by_key[key]["provenance"] + [provenance]))
            continue
        item = {
            "candidate_id": str(raw.get("region_id") or f"candidate-{len(merged) + 1:04d}"),
            "source_text": text,
            "bbox": [float(value) for value in bbox],
            "rotation": key[2],
            "provenance": [provenance],
        }
        by_key[key] = item
        merged.append(item)
    return merged


def build_post_ocr_supervision_package(
    *,
    source_pdf: Path,
    page_image: Path,
    ocr_payload: Mapping[str, object],
    initial_supervisor_plan: Mapping[str, object],
    knowledge_path: Path | None = None,
) -> dict:
    regions = [
        dict(item)
        for item in ocr_payload.get("regions", [])
        if isinstance(item, Mapping)
        and str(item.get("source_text") or "").strip()
    ]
    page_type = str(
        initial_supervisor_plan.get("page_type")
        or initial_supervisor_plan.get("document_type")
        or "engineering_drawing"
    )
    knowledge = supervisor_knowledge_context(
        page_type=page_type,
        **({"path": knowledge_path} if knowledge_path else {}),
    )
    candidates = _candidate_union(initial_supervisor_plan.get("source_text_lines"), regions)
    return {
        "schema": POST_OCR_SCHEMA,
        "supervisor_role": "multimodal_page_manager",
        "stage": "after_ocr_before_translation_and_placement",
        "source_pdf": str(Path(source_pdf).resolve()),
        "page_image": str(Path(page_image).resolve()),
        "page_type": page_type,
        "delivery_mode": initial_supervisor_plan.get(
            "delivery_mode", "inline_bilingual"
        ),
        "initial_supervisor_plan": dict(initial_supervisor_plan),
        "ocr_regions": regions,
        "ocr_region_count": len(regions),
        "candidate_union": candidates,
        "candidate_union_count": len(candidates),
        "supervisor_budget": {
            "maximum_model_passes_per_page": 3,
            "passes": ["plan_once", "targeted_difference_scan_once", "rendered_candidate_review_once"],
            "maximum_local_repairs": 1,
            "full_page_replan_for_soft_findings": False,
        },
        "engineering_semantic_knowledge": knowledge,
        "required_manager_actions": [
            "inspect the page image directly",
            "perform one full-page visual planning pass using the deduplicated candidate_union",
            "zoom suspected microtext until its smallest glyphs are at least 12 rendered pixels high",
            "compare every OCR region and coordinate against visible page content",
            "add visible natural-language blocks missed by OCR",
            "remove OCR noise and classify literal-only tokens",
            "group adjacent OCR fragments into complete engineering semantic blocks",
            "inventory every spatially distinct repeated functional label",
            "inventory tiny embedded labels such as FLOW, FALL, PITCH, ROOF and VOID even when OCR found nothing",
            "bind arrows, slope marks, degree values and direction symbols to the same semantic block as their words",
            "assign one coverage status to every OCR region and every visual addition",
            "plan nearby Chinese target boxes, font sizes, wrapping, rotation, and short leaders",
            "emit a release-blocking unexplained-region list",
            "perform one targeted difference scan limited to omissions, local rotation, directory bilingual rows, and sidebar/footer zoning",
            "do not restart the page plan for soft spacing, density, or leader concerns",
        ],
        "required_output": {
            "schema": "engineering-drawing-reconciled-supervisor-plan-v1",
            "fields": [
                "page_type",
                "delivery_mode",
                "coverage_inventory",
                "semantic_blocks",
                "translation_tasks",
                "placement_policy",
                "ocr_false_positives",
                "visual_additions",
                "microtext_scan_report",
                "symbol_relationships",
                "unexplained_region_ids",
            ],
            "release_rule": (
                "unexplained_region_ids must be empty and every visible natural-language "
                "instance must be represented before translation or rendering; "
                "OCR absence is never a reason to omit a visible label"
            ),
        },
    }


def load_ocr_payload(path: Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload.get("regions"), list):
        raise ValueError("OCR payload must contain a regions array")
    return payload


__all__ = [
    "POST_OCR_SCHEMA",
    "build_post_ocr_supervision_package",
    "load_ocr_payload",
]
