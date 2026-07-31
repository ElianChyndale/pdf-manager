from __future__ import annotations

"""Model-neutral V3 multimodal planning contract.

V3 COMPATIBILITY CONTRACT — this module is NOT the V4 production authority.
V4 flows must use ``supervisor_contract.py`` + ``run_v4.py`` and the
``orchestration_harness.py`` five-stage state machine.  Keep this module for
historical V3 plans and the ``v3-*`` compatibility commands only.

The vision model owns coverage, semantic grouping, translation, and candidate
layout.  The renderer remains deterministic: it can only consume the selected
target or one of the declared candidate regions and it records every fallback.
"""

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import re
from typing import Iterable, Mapping

from .placement_scoring import score_candidates

import fitz

from .workflow_policy import DEFAULT_SUPERVISOR_ADAPTER, WORKFLOW_VERSION

V3_SCHEMA = "engineering-drawing-multimodal-plan-v3"
V3_STATUS = {"translated", "literal_only", "not_needed", "manual_review"}
V3_SIDES = {"right", "below", "above", "left", "external_gutter", "manual_review"}
V3_MODES = {"inline", "leader", "title_block", "table_cell", "manual_review"}
V3_DELIVERY_MODES = {
    "inline_bilingual",
    "overlay_pair",
    "opaque_bilingual_reflow",
    "source_only",
}
V3_INLINE_EXCLUDED_PAGE_TYPES = {
    "dense_drawing_index",
    "sheet_index",
    "catalog_table",
}
V3_SUPERVISOR_CONTRACT = "v3-supervisor-plan-1"
V3_REGION_TYPES = {
    "drawing_body",
    "drawing_table",
    "sidebar_footer",
    "sidebar_footer_table",
    "directory_index",
    "company_contact_panel",
    "state_bearing_metadata",
    "prose_or_index_metadata",
}
V3_REGION_STRATEGIES = {
    "drawing_body": "blue_preserve_source",
    "drawing_table": "blue_preserve_source",
    "sidebar_footer": "subdivide_before_rendering",
    "sidebar_footer_table": "subdivide_before_rendering",
    "directory_index": "black_bilingual_cell_reflow",
    "company_contact_panel": "black_bilingual_text_reflow",
    "state_bearing_metadata": "blue_preserve_source",
    "prose_or_index_metadata": "black_bilingual_hierarchy_reflow",
}
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PLACEHOLDER_SOURCE_RE = re.compile(
    r"\b(?:visible\s+ruled|placeholder|complete\s+semantic|title\s+cell|"
    r"company,?\s+address\s+and\s+contact\s+text|row\s+\d+)\b",
    re.IGNORECASE,
)


def _is_blue(color: list[float]) -> bool:
    return color[2] >= 0.25 and color[2] > color[0] and color[2] > color[1]


def _is_black(color: list[float]) -> bool:
    return max(color) <= 0.2


def _rectangles_overlap(first: list[float], second: list[float]) -> bool:
    return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and second[1] < first[3]


def _validate_six_x_manual_review(
    item: Mapping[str, object],
    *,
    source_bbox: list[float] | None,
    page_size: list[float],
    field: str,
) -> None:
    """Permit a review exception only after a documented original-PDF 6x scan."""

    if source_bbox is None:
        raise ValueError(f"{field} manual_review requires source_bbox")
    evidence = item.get("six_x_inspection")
    if not isinstance(evidence, Mapping):
        raise ValueError(f"{field} manual_review requires six_x_inspection")
    if _text(evidence.get("source")).casefold() != "original_source_pdf":
        raise ValueError(f"{field} manual_review evidence must inspect original_source_pdf")
    try:
        zoom_multiplier = float(evidence.get("zoom_multiplier"))
    except (TypeError, ValueError):
        zoom_multiplier = 0
    if zoom_multiplier != 6:
        raise ValueError(f"{field} manual_review requires 6x original-PDF inspection")
    if _text(evidence.get("result")).casefold() != "individual_glyph_illegible":
        raise ValueError(f"{field} manual_review is limited to one illegible glyph")
    if not _SHA256_RE.fullmatch(_text(evidence.get("source_pdf_sha256")).casefold()):
        raise ValueError(f"{field} manual_review requires original source_pdf_sha256")
    if not _text(evidence.get("crop_reference")) or not _text(evidence.get("observed_context")):
        raise ValueError(f"{field} manual_review requires crop_reference and observed_context")
    glyph_bbox = _rect(evidence.get("glyph_bbox"), field=f"{field}.six_x_inspection.glyph_bbox")
    if not _inside(glyph_bbox, page_size):
        raise ValueError(f"{field} manual_review glyph_bbox is outside page")
    if not _rectangles_overlap(glyph_bbox, source_bbox):
        raise ValueError(f"{field} manual_review glyph_bbox must overlap source_bbox")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_multimodal_plan_payload(
    payload: Mapping[str, object],
    *,
    source_pdf_path: Path | None = None,
) -> dict:
    """Select and normalize a model response before strict V3 validation.

    The Codex Sol Light supervisor returns one document containing the page plans.
    The renderer consumes one source PDF at a time, so this adapter selects the
    matching sample and converts readable mode/status aliases into the compact
    renderer contract. It does not invent translations or positions.
    """
    normalized = deepcopy(dict(payload))
    samples = normalized.pop("samples", None)
    if isinstance(samples, list):
        sample_id = ""
        if source_pdf_path is not None:
            match = re.search(r"(?:core|challenge)-\d{2,3}", str(Path(source_pdf_path)).casefold())
            sample_id = match.group(0) if match else ""
        selected = None
        for sample in samples:
            if not isinstance(sample, Mapping):
                continue
            if sample_id and str(sample.get("sample_id") or "").casefold() == sample_id:
                selected = sample
                break
        if selected is None and len(samples) == 1 and isinstance(samples[0], Mapping):
            selected = samples[0]
        if selected is None:
            raise ValueError("V3 plan contains samples but none matches the source PDF")
        merged = dict(normalized)
        merged.update(dict(selected))
        normalized = merged

    inventory = normalized.get("coverage_inventory")
    if isinstance(inventory, list):
        normalized_inventory: list[dict] = []
        for item in inventory:
            if not isinstance(item, Mapping):
                normalized_inventory.append(item)
                continue
            entry = dict(item)
            entry["candidate_id"] = entry.get("candidate_id") or entry.get("coverage_id") or entry.get("region_id")
            status = _text(entry.get("status")).casefold()
            if status == "translated_or_literal_only":
                status = "translated"
            entry["status"] = status
            normalized_inventory.append(entry)
        normalized["coverage_inventory"] = normalized_inventory

    blocks = normalized.get("semantic_blocks")
    if isinstance(blocks, list):
        normalized_blocks: list[dict] = []
        for raw_block in blocks:
            if not isinstance(raw_block, Mapping):
                normalized_blocks.append(raw_block)
                continue
            block = dict(raw_block)
            placement = dict(block.get("placement") or {})
            raw_mode = _text(placement.get("mode") or block.get("placement_mode") or "inline").casefold()
            if "table" in raw_mode:
                mode = "table_cell"
            elif "title" in raw_mode or "panel" in raw_mode or "address" in raw_mode:
                mode = "title_block"
            elif "leader" in raw_mode and "direct" not in raw_mode:
                mode = "leader"
            else:
                mode = "inline"
            placement["mode"] = mode
            block["placement"] = placement
            status = _text(block.get("coverage_status") or block.get("status") or "translated").casefold()
            if status == "translated_or_literal_only":
                status = "translated"
            block["coverage_status"] = status
            normalized_blocks.append(block)
        normalized["semantic_blocks"] = normalized_blocks

        # The model may enumerate page-level categories while using more
        # specific member IDs in blocks. Materialize those members into the
        # inventory so the validator can prove every emitted block is covered.
        existing = {
            str(item.get("candidate_id") or "")
            for item in normalized.get("coverage_inventory", [])
            if isinstance(item, Mapping)
        }
        expanded_inventory = list(normalized.get("coverage_inventory") or [])
        for block in normalized_blocks:
            if not isinstance(block, Mapping):
                continue
            for member_id in block.get("member_ids") or block.get("members") or []:
                member_id = _text(member_id)
                if not member_id or member_id in existing:
                    continue
                expanded_inventory.append(
                    {
                        "candidate_id": member_id,
                        "page_index": block.get("page_index", 0),
                        "source_text": block.get("source_text") or member_id,
                        "source_bbox": block.get("source_bbox"),
                        "status": block.get("coverage_status", "translated"),
                        "reason": "semantic block member enumerated by the multimodal planner",
                    }
                )
                existing.add(member_id)
        normalized["coverage_inventory"] = expanded_inventory

    supervisor = normalized.get("supervisor_plan")
    if isinstance(supervisor, Mapping) and isinstance(supervisor.get("pages"), list):
        sample_id = ""
        if source_pdf_path is not None:
            match = re.search(r"(?:core|challenge)-\d{2,3}", str(Path(source_pdf_path)).casefold())
            sample_id = match.group(0) if match else ""
        selected_supervisor = next(
            (
                item
                for item in supervisor["pages"]
                if isinstance(item, Mapping)
                and (not sample_id or _text(item.get("id") or item.get("sample_id")).casefold() == sample_id)
            ),
            None,
        )
        if selected_supervisor is not None:
            normalized["supervisor_plan"] = {
                "contract_version": supervisor.get("contract_version") or V3_SUPERVISOR_CONTRACT,
                "role": supervisor.get("role") or "multimodal_page_manager",
                **dict(selected_supervisor),
            }
    return normalized


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _translation_text(value: object) -> str:
    """Normalize a translation without flattening model-planned line breaks."""
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _rect(value: object, *, field: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{field} must contain four coordinates")
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} contains a non-numeric coordinate") from error
    if not all(math.isfinite(item) for item in result) or result[2] <= result[0] or result[3] <= result[1]:
        raise ValueError(f"{field} must be a finite non-empty rectangle")
    return result


def _page_sizes(source_pdf_path: Path) -> list[tuple[float, float]]:
    with fitz.open(Path(source_pdf_path)) as document:
        return [(float(page.rect.width), float(page.rect.height)) for page in document]


def _inside(rect: list[float], size: tuple[float, float]) -> bool:
    return 0 <= rect[0] <= rect[2] <= size[0] and 0 <= rect[1] <= rect[3] <= size[1]


def _page_index(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError) as error:
        raise ValueError("page_index must be an integer") from error


def _rotation(value: object) -> int:
    try:
        rotation = int(value or 0) % 360
    except (TypeError, ValueError) as error:
        raise ValueError("rotation must be an integer") from error
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("rotation must be 0, 90, 180, or 270")
    return rotation


def validate_multimodal_plan(
    payload: Mapping[str, object],
    *,
    source_pdf_path: Path | None = None,
    page_sizes: Iterable[object] | None = None,
) -> dict:
    """Validate and normalize an approved model plan before rendering."""
    if not isinstance(payload, Mapping) or payload.get("schema") != V3_SCHEMA:
        raise ValueError(f"multimodal plan schema must be {V3_SCHEMA}")
    declared_workflow = _text(payload.get("workflow_version"))
    if declared_workflow and declared_workflow != WORKFLOW_VERSION:
        raise ValueError(
            f"multimodal plan workflow_version must be {WORKFLOW_VERSION}; "
            "re-plan stale supervisor output under the current contract"
        )
    model_name = _text(payload.get("model_name") or payload.get("model"))
    if not model_name:
        raise ValueError("multimodal plan requires model_name")
    if payload.get("status") not in {"prepared", "approved", "repair"}:
        raise ValueError("multimodal plan status must be prepared, approved, or repair")
    if source_pdf_path is not None:
        sizes = _page_sizes(Path(source_pdf_path))
    else:
        sizes = []
        for index, value in enumerate(page_sizes or []):
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError(f"page_sizes[{index}] must contain width and height")
            sizes.append((float(value[0]), float(value[1])))
    if not sizes:
        raise ValueError("multimodal plan requires source page sizes")

    normalized = deepcopy(dict(payload))
    normalized["schema"] = V3_SCHEMA
    normalized["workflow_version"] = WORKFLOW_VERSION
    normalized["model_name"] = model_name
    normalized["model_provider"] = _text(payload.get("model_provider")) or "unknown"
    normalized["reasoning_profile"] = _text(payload.get("reasoning_profile")) or "unspecified"
    declared_adapter = _text(payload.get("supervisor_adapter"))
    model_key = model_name.casefold()
    reasoning_key = normalized["reasoning_profile"].casefold()
    inferred_adapter = "generic-multimodal"
    if (
        model_name == DEFAULT_SUPERVISOR_ADAPTER["model_name"]
        and normalized["reasoning_profile"] == DEFAULT_SUPERVISOR_ADAPTER["reasoning_profile"]
    ):
        inferred_adapter = DEFAULT_SUPERVISOR_ADAPTER["alias"]
    elif model_key == "gpt-5.6-sol" and reasoning_key == "light":
        inferred_adapter = "codex-sol-light"
    elif model_key == "gpt-5.6-terra":
        inferred_adapter = "terra-high" if reasoning_key == "high" else "terra"
    elif "luna" in model_key:
        inferred_adapter = "luna"
    normalized["supervisor_adapter"] = declared_adapter or inferred_adapter
    raw_capabilities = payload.get("model_capabilities")
    if isinstance(raw_capabilities, list):
        normalized["model_capabilities"] = [
            _text(item) for item in raw_capabilities if _text(item)
        ]
    else:
        normalized["model_capabilities"] = ["multimodal_page_planning"]
    if "multimodal_page_planning" not in normalized["model_capabilities"]:
        raise ValueError("supervisor adapter must declare multimodal_page_planning")
    normalized["multimodal_page_planning"] = bool(payload.get("multimodal_page_planning", True))
    if not normalized["multimodal_page_planning"]:
        raise ValueError("V3 plan must be produced by a multimodal page-planning model")
    execution_policy = _text(payload.get("execution_policy") or "planner_region_with_executor_fit").casefold()
    if execution_policy not in {"planner_region_with_executor_fit", "strict_multimodal_execution"}:
        raise ValueError("unsupported multimodal execution_policy")
    normalized["execution_policy"] = execution_policy
    if execution_policy == "strict_multimodal_execution":
        coordinate_space = _text(payload.get("coordinate_space")).casefold()
        if coordinate_space != "display_page_rect":
            raise ValueError(
                "strict execution requires coordinate_space=display_page_rect; "
                "PNG/reference/OCR pixel coordinates are not render coordinates"
            )
        normalized["coordinate_space"] = "display_page_rect"
        authority = payload.get("visual_planning_authority")
        if not isinstance(authority, Mapping):
            raise ValueError("strict execution requires visual_planning_authority")
        required_authority = {
            "authority": "multimodal_model",
            "sequence": "visual_design_before_ocr_execution",
            "ocr_role": "extraction_and_mask_execution_only",
            "placement_basis": "rendered_page_visual",
        }
        for key, expected in required_authority.items():
            if _text(authority.get(key)).casefold() != expected:
                raise ValueError(f"visual_planning_authority.{key} must be {expected}")
        normalized["visual_planning_authority"] = dict(required_authority)
        provenance = payload.get("render_provenance")
        if not isinstance(provenance, Mapping):
            raise ValueError("strict execution requires render_provenance")
        if _text(provenance.get("base")).casefold() != "original_source_pdf":
            raise ValueError("render_provenance.base must be original_source_pdf")
        if _text(provenance.get("reference_usage")).casefold() != "translation_evidence_only":
            raise ValueError("render_provenance.reference_usage must be translation_evidence_only")
        if provenance.get("copied_reference_page_or_region") is not False:
            raise ValueError("render_provenance forbids copied reference pages or regions")
        source_sha256 = _text(provenance.get("source_sha256")).casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
            raise ValueError("render_provenance.source_sha256 must be a SHA-256 hex digest")
        if source_pdf_path is not None and source_sha256 != _file_sha256(Path(source_pdf_path)):
            raise ValueError("render_provenance.source_sha256 does not match original source PDF")
        normalized["render_provenance"] = {
            **dict(provenance),
            "base": "original_source_pdf",
            "source_sha256": source_sha256,
            "reference_usage": "translation_evidence_only",
            "copied_reference_page_or_region": False,
        }
    normalized["page_sizes"] = [[width, height] for width, height in sizes]
    supervisor = payload.get("supervisor_plan")
    if supervisor is not None and not isinstance(supervisor, Mapping):
        raise ValueError("supervisor_plan must be an object")
    if isinstance(supervisor, Mapping):
        if _text(supervisor.get("contract_version")) not in {"", V3_SUPERVISOR_CONTRACT}:
            raise ValueError("unsupported supervisor_plan contract_version")
        for key in ("ocr_tasks", "translation_tasks", "placement_policy"):
            if key not in supervisor:
                raise ValueError(f"supervisor_plan requires {key}")
        if not isinstance(supervisor.get("ocr_tasks"), list) or not isinstance(supervisor.get("translation_tasks"), list):
            raise ValueError("supervisor_plan ocr_tasks and translation_tasks must be lists")
        for index, task in enumerate(supervisor.get("ocr_tasks") or []):
            if not isinstance(task, Mapping) or not _text(task.get("id")):
                raise ValueError(f"supervisor_plan.ocr_tasks[{index}] requires id")
            if not any(key in task for key in ("region_norm", "region", "crop", "full_page")):
                raise ValueError(f"supervisor_plan.ocr_tasks[{index}] requires a region/crop/full_page directive")
        for index, task in enumerate(supervisor.get("translation_tasks") or []):
            if not isinstance(task, Mapping) or not _text(task.get("id")):
                raise ValueError(f"supervisor_plan.translation_tasks[{index}] requires id")
            if not any(key in task for key in ("semantic_block", "source_task", "source_tasks", "source_candidate_ids")):
                raise ValueError(f"supervisor_plan.translation_tasks[{index}] requires semantic/source grouping")
        if not isinstance(supervisor.get("placement_policy"), Mapping):
            raise ValueError("supervisor_plan placement_policy must be an object")
        normalized["supervisor_plan"] = {
            **dict(supervisor),
            "contract_version": _text(supervisor.get("contract_version")) or V3_SUPERVISOR_CONTRACT,
            "role": _text(supervisor.get("role")) or "multimodal_page_manager",
        }
    page_type = _text(
        (supervisor.get("page_type") if isinstance(supervisor, Mapping) else None)
        or payload.get("page_type")
        or payload.get("document_type")
        or "engineering_drawing"
    ).casefold()
    delivery_mode = _text(
        (supervisor.get("delivery_mode") if isinstance(supervisor, Mapping) else None)
        or payload.get("delivery_mode")
        or "inline_bilingual"
    ).casefold()
    delivery_mode = {
        "inline": "inline_bilingual",
        "inline_bilingual_chinese": "inline_bilingual",
        "overlay": "overlay_pair",
        "opaque_cover_pair": "overlay_pair",
        "single_page_bilingual_reflow": "opaque_bilingual_reflow",
    }.get(delivery_mode, delivery_mode)
    if delivery_mode not in V3_DELIVERY_MODES:
        raise ValueError(f"unsupported V3 delivery_mode: {delivery_mode}")
    if page_type in V3_INLINE_EXCLUDED_PAGE_TYPES and delivery_mode != "opaque_bilingual_reflow":
        raise ValueError(
            f"{page_type} pages require opaque_bilingual_reflow"
        )
    normalized["page_type"] = page_type
    normalized["delivery_mode"] = delivery_mode

    region_map = payload.get("page_region_map")
    region_by_id: dict[str, dict] = {}
    if execution_policy == "strict_multimodal_execution":
        if not isinstance(region_map, list) or not region_map:
            raise ValueError("strict execution requires multimodal page_region_map")
        region_pages: set[int] = set()
        normalized_regions: list[dict] = []
        for index, raw_region in enumerate(region_map):
            if not isinstance(raw_region, Mapping):
                raise ValueError(f"page_region_map[{index}] must be an object")
            region = dict(raw_region)
            region_id = _text(region.get("region_id"))
            region_type = _text(region.get("region_type")).casefold()
            page_index = _page_index(region.get("page_index"))
            if not region_id or region_id in region_by_id:
                raise ValueError("page_region_map region IDs must be non-empty and unique")
            if region_type not in V3_REGION_TYPES:
                raise ValueError(f"page_region_map[{index}] has unsupported region_type")
            if not 0 <= page_index < len(sizes):
                raise ValueError(f"page_region_map[{index}] page_index is outside source PDF")
            bbox = _rect(region.get("bbox"), field=f"page_region_map[{index}].bbox")
            if not _inside(bbox, sizes[page_index]):
                raise ValueError(f"page_region_map[{index}].bbox is outside page")
            if _text(region.get("decision_source")).casefold() != "multimodal_visual_plan":
                raise ValueError(f"page_region_map[{index}] must be designed by multimodal_visual_plan")
            strategy = _text(region.get("strategy")).casefold()
            if strategy != V3_REGION_STRATEGIES[region_type]:
                raise ValueError(
                    f"page_region_map[{index}] strategy must be {V3_REGION_STRATEGIES[region_type]}"
                )
            normalized_region = {
                **region,
                "region_id": region_id,
                "region_type": region_type,
                "page_index": page_index,
                "bbox": bbox,
                "strategy": strategy,
                "decision_source": "multimodal_visual_plan",
            }
            normalized_regions.append(normalized_region)
            region_by_id[region_id] = normalized_region
            region_pages.add(page_index)
        missing_region_pages = set(range(len(sizes))) - region_pages
        if missing_region_pages:
            raise ValueError(f"page_region_map missing pages: {sorted(missing_region_pages)}")
        normalized["page_region_map"] = normalized_regions

        existing_inventory = payload.get("existing_translation_inventory")
        if not isinstance(existing_inventory, list):
            raise ValueError("strict execution requires existing_translation_inventory list")
        normalized_existing: list[dict] = []
        seen_existing: set[str] = set()
        for index, raw_existing in enumerate(existing_inventory):
            if not isinstance(raw_existing, Mapping):
                raise ValueError(f"existing_translation_inventory[{index}] must be an object")
            existing = dict(raw_existing)
            translation_id = _text(existing.get("translation_id"))
            page_index = _page_index(existing.get("page_index"))
            text = _translation_text(existing.get("text"))
            action = _text(existing.get("action") or existing.get("supervisor_action")).casefold()
            if not translation_id or translation_id in seen_existing:
                raise ValueError("existing translation IDs must be non-empty and unique")
            if not 0 <= page_index < len(sizes) or not _CJK_RE.search(text):
                raise ValueError(f"existing_translation_inventory[{index}] is invalid")
            bbox = _rect(existing.get("bbox"), field=f"existing_translation_inventory[{index}].bbox")
            if not _inside(bbox, sizes[page_index]):
                raise ValueError(f"existing_translation_inventory[{index}].bbox is outside page")
            if action not in {"reuse", "replace"}:
                raise ValueError(f"existing_translation_inventory[{index}] requires reuse/replace action")
            if not _text(existing.get("source_file")) or not _text(existing.get("source_association")):
                raise ValueError(
                    f"existing_translation_inventory[{index}] requires source_file and source_association"
                )
            normalized_existing.append(
                {
                    **existing,
                    "translation_id": translation_id,
                    "page_index": page_index,
                    "bbox": bbox,
                    "text": text,
                    "action": action,
                }
            )
            seen_existing.add(translation_id)
        normalized["existing_translation_inventory"] = normalized_existing

    inventory = payload.get("coverage_inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("V3 plan requires a non-empty page-wide coverage_inventory")
    normalized_inventory: list[dict] = []
    seen_coverage: set[str] = set()
    for index, raw in enumerate(inventory):
        if not isinstance(raw, Mapping):
            raise ValueError(f"coverage_inventory[{index}] must be an object")
        item = dict(raw)
        candidate_id = _text(item.get("candidate_id") or item.get("region_id"))
        source_text = _text(item.get("source_text"))
        status = _text(item.get("status")).casefold()
        page_index = _page_index(item.get("page_index"))
        if not candidate_id or candidate_id in seen_coverage:
            raise ValueError("coverage candidate IDs must be non-empty and unique")
        if not source_text:
            raise ValueError(f"coverage_inventory[{index}] requires source_text")
        if _PLACEHOLDER_SOURCE_RE.search(source_text):
            raise ValueError(
                f"coverage_inventory[{index}] contains a placeholder; supervisor must transcribe the visible source text"
            )
        if status not in V3_STATUS:
            raise ValueError(f"coverage_inventory[{index}] has unsupported status")
        if not 0 <= page_index < len(sizes):
            raise ValueError(f"coverage_inventory[{index}] page_index is outside source PDF")
        if status in {"not_needed", "manual_review"} and not _text(item.get("reason")):
            raise ValueError(f"coverage_inventory[{index}] requires a reason")
        if status in {"literal_only", "not_needed"} and not _literal_only_is_semantically_safe(source_text):
            if status != "not_needed" or not _has_verified_ocr_artifact_evidence(item):
                raise ValueError(
                    f"coverage_inventory[{index}] uses {status} for language-bearing text: "
                    f"{source_text[:80]!r}"
                )
        source_bbox = None
        if item.get("source_bbox") is not None:
            source_bbox = _rect(item["source_bbox"], field=f"coverage_inventory[{index}].source_bbox")
            if not _inside(source_bbox, sizes[page_index]):
                raise ValueError(f"coverage_inventory[{index}].source_bbox is outside page")
            item["source_bbox"] = source_bbox
        if status == "manual_review":
            _validate_six_x_manual_review(
                item,
                source_bbox=source_bbox,
                page_size=sizes[page_index],
                field=f"coverage_inventory[{index}]",
            )
        item.update({"candidate_id": candidate_id, "source_text": source_text, "status": status, "page_index": page_index})
        normalized_inventory.append(item)
        seen_coverage.add(candidate_id)
    normalized["coverage_inventory"] = normalized_inventory

    blocks = payload.get("semantic_blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("V3 plan requires semantic_blocks")
    normalized_blocks: list[dict] = []
    seen_blocks: set[str] = set()
    covered_members: set[str] = set()
    for index, raw in enumerate(blocks):
        if not isinstance(raw, Mapping):
            raise ValueError(f"semantic_blocks[{index}] must be an object")
        item = dict(raw)
        block_id = _text(item.get("block_id"))
        members = item.get("member_ids") or item.get("members") or []
        if not block_id or block_id in seen_blocks or not isinstance(members, list) or not members:
            raise ValueError(f"semantic_blocks[{index}] requires unique block_id and member_ids")
        member_ids = [_text(member) for member in members]
        if any(not member for member in member_ids):
            raise ValueError(f"semantic_blocks[{index}] member_ids must be non-empty")
        if any(member not in seen_coverage for member in member_ids):
            raise ValueError(f"semantic_blocks[{index}] references an unknown coverage candidate")
        page_index = _page_index(item.get("page_index"))
        if not 0 <= page_index < len(sizes):
            raise ValueError(f"semantic_blocks[{index}] page_index is outside source PDF")
        page_region_id = _text(item.get("page_region_id") or item.get("planning_region_id"))
        page_region = region_by_id.get(page_region_id)
        if execution_policy == "strict_multimodal_execution":
            if page_region is None:
                raise ValueError(f"semantic_blocks[{index}] requires a valid page_region_id")
            if page_region["page_index"] != page_index:
                raise ValueError(f"semantic_blocks[{index}] page_region_id belongs to another page")
        region_type = page_region["region_type"] if page_region else _text(item.get("region_type")).casefold()
        status = _text(item.get("coverage_status") or item.get("status") or "translated").casefold()
        if status not in V3_STATUS:
            raise ValueError(f"semantic_blocks[{index}] has unsupported coverage status")
        translated = _translation_text(item.get("translated_text") or item.get("gold_translation"))
        if status == "translated" and not _CJK_RE.search(translated):
            raise ValueError(f"semantic_blocks[{index}] translated block requires Chinese")
        if status == "translated" and _PLACEHOLDER_SOURCE_RE.search(
            _text(item.get("source_text"))
        ):
            raise ValueError(
                f"semantic_blocks[{index}] contains a placeholder; use the exact visible source block"
            )
        source_bbox = _rect(item.get("source_bbox"), field=f"semantic_blocks[{index}].source_bbox")
        if not _inside(source_bbox, sizes[page_index]):
            raise ValueError(f"semantic_blocks[{index}].source_bbox is outside page")
        placement = dict(item.get("placement") or {})
        side = _text(placement.get("side") or item.get("placement_side") or "manual_review").casefold()
        mode = _text(placement.get("mode") or item.get("placement_mode") or ("manual_review" if status != "translated" else "inline")).casefold()
        if side not in V3_SIDES or mode not in V3_MODES:
            raise ValueError(f"semantic_blocks[{index}] placement side/mode is unsupported")
        target = placement.get("selected_region") or placement.get("target_bbox") or item.get("target_bbox")
        if target is not None:
            target = _rect(target, field=f"semantic_blocks[{index}].target_bbox")
            if not _inside(target, sizes[page_index]):
                raise ValueError(f"semantic_blocks[{index}].target_bbox is outside page")
        candidates = []
        for candidate_index, candidate in enumerate(placement.get("candidate_regions") or item.get("candidate_regions") or []):
            candidate_rect = _rect(candidate, field=f"semantic_blocks[{index}].candidate_regions[{candidate_index}]")
            if not _inside(candidate_rect, sizes[page_index]):
                raise ValueError(f"semantic_blocks[{index}] candidate region is outside page")
            candidates.append(candidate_rect)
        if status == "translated" and target is None and not candidates:
            raise ValueError(f"semantic_blocks[{index}] requires a target or candidate region")
        if execution_policy == "strict_multimodal_execution":
            if _text(item.get("decision_source") or placement.get("decision_source")).casefold() != "multimodal_visual_plan":
                raise ValueError(
                    f"semantic_blocks[{index}] strict execution requires multimodal_visual_plan decision_source"
                )
            if target is None:
                raise ValueError(f"semantic_blocks[{index}] strict execution requires selected_region")
            if candidates:
                raise ValueError(f"semantic_blocks[{index}] strict execution forbids candidate fallbacks")
            if region_type in {"drawing_body", "drawing_table", "state_bearing_metadata"} and status == "translated":
                score_audit = placement.get("candidate_score_audit")
                if not isinstance(score_audit, list) or not score_audit:
                    raise ValueError(
                        f"semantic_blocks[{index}] requires candidate_score_audit for dynamic blue placement"
                    )
                radius = float(placement.get("search_radius_pt") or 24)
                weights = placement.get("dynamic_weights")
                recomputed = score_candidates(
                    region_type,
                    score_audit,
                    search_radius_pt=radius,
                    weights=weights if isinstance(weights, Mapping) else None,
                )
                selected = [entry for entry in recomputed if entry["selected"]]
                if len(selected) != 1:
                    raise ValueError(
                        f"semantic_blocks[{index}] candidate_score_audit has no legal selected candidate"
                    )
                selected_bbox = _rect(selected[0].get("bbox"), field=f"semantic_blocks[{index}].candidate_score_audit.selected.bbox")
                if selected_bbox != target:
                    raise ValueError(f"semantic_blocks[{index}] selected_region is not the highest-scoring legal candidate")
                placement["candidate_score_audit"] = recomputed
                placement["dynamic_weights"] = recomputed[0]["weights"]
                placement["search_radius_pt"] = radius
            if len(member_ids) > 1 and status == "translated":
                group_layout = placement.get("group_layout")
                if not isinstance(group_layout, Mapping):
                    raise ValueError(f"semantic_blocks[{index}] multi-member translation requires group_layout")
                if _text(group_layout.get("placement_scope")).casefold() != "semantic_block":
                    raise ValueError(f"semantic_blocks[{index}] group_layout must use semantic_block scope")
                anchor = group_layout.get("group_anchor")
                if not isinstance(anchor, (list, tuple)) or len(anchor) != 2:
                    raise ValueError(f"semantic_blocks[{index}] group_layout requires one group_anchor")
                if bool(group_layout.get("independent_fragment_placement", True)):
                    raise ValueError(f"semantic_blocks[{index}] forbids independent fragment placement")
                if _text(group_layout.get("line_break_policy")).casefold() != "semantic_boundaries_only":
                    raise ValueError(f"semantic_blocks[{index}] requires semantic-boundary line breaks")
                if float(group_layout.get("group_internal_dispersion_points", -1)) != 0:
                    raise ValueError(f"semantic_blocks[{index}] group internal dispersion must be zero")
                score_audit = group_layout.get("candidate_score_audit")
                if not isinstance(score_audit, list) or not score_audit:
                    raise ValueError(f"semantic_blocks[{index}] group_layout requires candidate score audit")
            render_runs = placement.get("render_runs") or []
            if render_runs:
                if mode not in {"title_block", "table_cell"}:
                    raise ValueError(
                        f"semantic_blocks[{index}] render_runs require title_block/table_cell exact renderer"
                    )
                if not isinstance(render_runs, list):
                    raise ValueError(f"semantic_blocks[{index}] render_runs must be a list")
                normalized_runs = []
                for run_index, raw_run in enumerate(render_runs):
                    if not isinstance(raw_run, Mapping):
                        raise ValueError(f"semantic_blocks[{index}].render_runs[{run_index}] must be an object")
                    run = dict(raw_run)
                    run_text = _translation_text(run.get("text"))
                    run_bbox = _rect(run.get("bbox"), field=f"semantic_blocks[{index}].render_runs[{run_index}].bbox")
                    run_color = run.get("color", run.get("colour"))
                    run_size = float(run.get("font_size") or 0)
                    if not run_text or not _inside(run_bbox, sizes[page_index]):
                        raise ValueError(f"semantic_blocks[{index}].render_runs[{run_index}] is invalid")
                    if not 1.8 <= run_size <= 18:
                        raise ValueError(f"semantic_blocks[{index}].render_runs[{run_index}] font_size is invalid")
                    if not isinstance(run_color, (list, tuple)) or len(run_color) != 3 or any(
                        not 0 <= float(channel) <= 1 for channel in run_color
                    ):
                        raise ValueError(f"semantic_blocks[{index}].render_runs[{run_index}] requires RGB color")
                    normalized_runs.append(
                        {
                            **run,
                            "text": run_text,
                            "bbox": run_bbox,
                            "font_size": run_size,
                            "color": [float(channel) for channel in run_color],
                            "rotation": _rotation(run.get("rotation", 0)),
                        }
                    )
                placement["render_runs"] = normalized_runs
            else:
                render_text = _translation_text(placement.get("render_text") or item.get("render_text"))
                if not render_text:
                    raise ValueError(f"semantic_blocks[{index}] strict execution requires render_text or render_runs")
                color = placement.get("color", placement.get("colour"))
                if (
                    not isinstance(color, (list, tuple))
                    or len(color) != 3
                    or any(not 0 <= float(channel) <= 1 for channel in color)
                ):
                    raise ValueError(f"semantic_blocks[{index}] strict execution requires RGB color")
                placement["render_text"] = render_text
                placement["color"] = [float(channel) for channel in color]
            colors = [run["color"] for run in placement.get("render_runs", [])] or [placement.get("color")]
            if region_type in {"drawing_body", "drawing_table", "state_bearing_metadata"}:
                if not bool(placement.get("preserve_source")):
                    raise ValueError(f"semantic_blocks[{index}] drawing region must preserve source")
                if placement.get("exact_ink_masks"):
                    raise ValueError(f"semantic_blocks[{index}] drawing region cannot cover source text")
                if any(not isinstance(color, list) or not _is_blue(color) for color in colors):
                    raise ValueError(f"semantic_blocks[{index}] drawing-region Chinese must be blue")
            elif region_type in {"sidebar_footer", "sidebar_footer_table"}:
                raise ValueError(f"semantic_blocks[{index}] generic sidebar/footer must be semantically subdivided")
            elif region_type in {"company_contact_panel", "prose_or_index_metadata"}:
                if not placement.get("render_runs"):
                    raise ValueError(f"semantic_blocks[{index}] bilingual reflow requires black render_runs")
                if any(not _is_black(color) for color in colors):
                    raise ValueError(f"semantic_blocks[{index}] bilingual reflow render_runs must be black")
                combined_runs = " ".join(run["text"] for run in placement["render_runs"])
                if not _CJK_RE.search(combined_runs) or not re.search(r"[A-Za-z]", combined_runs):
                    raise ValueError(f"semantic_blocks[{index}] bilingual reflow requires source plus Chinese")
            elif region_type == "directory_index":
                if any(not isinstance(color, list) or not _is_black(color) for color in colors):
                    raise ValueError(f"semantic_blocks[{index}] directory Chinese must be black")
                combined = " ".join(run["text"] for run in placement.get("render_runs", [])) or placement.get("render_text", "")
                if not _CJK_RE.search(combined) or not re.search(r"[A-Za-z]", combined):
                    raise ValueError(f"semantic_blocks[{index}] directory bilingual reflow requires source plus Chinese")
            if mode in {"title_block", "table_cell"} and not bool(placement.get("preserve_source")):
                masks = placement.get("exact_ink_masks") or []
                if not isinstance(masks, list) or not masks:
                    raise ValueError(
                        f"semantic_blocks[{index}] strict opaque execution requires exact_ink_masks or preserve_source"
                    )
        font_size = float(placement.get("font_size") or item.get("font_size") or 0)
        if status == "translated" and not 2.8 <= font_size <= 18:
            raise ValueError(f"semantic_blocks[{index}] font_size must be 2.8..18")
        rotation = _rotation(placement.get("rotation", item.get("rotation", 0)))
        leader_path = placement.get("leader_path") or item.get("leader_path") or []
        if mode == "leader" and not leader_path and not candidates and target is None:
            raise ValueError(f"semantic_blocks[{index}] leader placement needs a route or target")
        item.update(
            {
                "block_id": block_id,
                "member_ids": member_ids,
                "page_index": page_index,
                "page_region_id": page_region_id,
                "region_type": region_type,
                "coverage_status": status,
                "translated_text": translated,
                "source_bbox": source_bbox,
                "placement": {
                    **placement,
                    "side": side,
                    "mode": mode,
                    "selected_region": target,
                    "candidate_regions": candidates,
                    "font_size": font_size,
                    "rotation": rotation,
                    "leader_path": leader_path,
                    "leader_allowed_when_local_space_exhausted": bool(
                        placement.get("leader_allowed_when_local_space_exhausted", mode == "leader")
                    ),
                },
            }
        )
        normalized_blocks.append(item)
        seen_blocks.add(block_id)
        covered_members.update(member_ids)
    if not covered_members.issubset(seen_coverage):
        raise ValueError("internal V3 coverage/member mismatch")
    if execution_policy == "strict_multimodal_execution":
        zone_audit = payload.get("mandatory_zone_audit")
        if not isinstance(zone_audit, list) or not zone_audit:
            raise ValueError("strict execution requires mandatory_zone_audit")
        normalized_zones: list[dict] = []
        audited_pages: set[int] = set()
        for index, raw_zone in enumerate(zone_audit):
            if not isinstance(raw_zone, Mapping):
                raise ValueError(f"mandatory_zone_audit[{index}] must be an object")
            zone = dict(raw_zone)
            zone_id = _text(zone.get("zone_id"))
            zone_type = _text(zone.get("zone_type"))
            page_index = _page_index(zone.get("page_index"))
            member_ids = [_text(value) for value in (zone.get("member_ids") or [])]
            block_ids = [_text(value) for value in (zone.get("block_ids") or [])]
            if not zone_id or not zone_type or zone.get("status") != "complete":
                raise ValueError(f"mandatory_zone_audit[{index}] must be complete and identified")
            if _text(zone.get("decision_source")).casefold() != "multimodal_visual_plan":
                raise ValueError(
                    f"mandatory_zone_audit[{index}] must be designed by multimodal_visual_plan"
                )
            if not 0 <= page_index < len(sizes):
                raise ValueError(f"mandatory_zone_audit[{index}] page_index is outside source PDF")
            if not member_ids or not block_ids:
                raise ValueError(f"mandatory_zone_audit[{index}] requires member_ids and block_ids")
            if any(value not in seen_coverage for value in member_ids):
                raise ValueError(f"mandatory_zone_audit[{index}] references unknown coverage members")
            if any(value not in seen_blocks for value in block_ids):
                raise ValueError(f"mandatory_zone_audit[{index}] references unknown semantic blocks")
            if any(value not in covered_members for value in member_ids):
                raise ValueError(f"mandatory_zone_audit[{index}] contains members without visible semantic blocks")
            audited_pages.add(page_index)
            normalized_zones.append(
                {
                    **zone,
                    "zone_id": zone_id,
                    "zone_type": zone_type,
                    "page_index": page_index,
                    "member_ids": member_ids,
                    "block_ids": block_ids,
                    "status": "complete",
                }
            )
        missing_pages = set(range(len(sizes))) - audited_pages
        if missing_pages:
            raise ValueError(f"mandatory_zone_audit missing pages: {sorted(missing_pages)}")
        normalized["mandatory_zone_audit"] = normalized_zones
    normalized["semantic_blocks"] = normalized_blocks
    normalized.setdefault("coverage_evidence", [])
    return normalized


def apply_multimodal_plan(regions: Iterable[dict], plan: Mapping[str, object]) -> list[dict]:
    """Merge model blocks into renderer regions without inventing translations."""
    source_regions = [dict(region) for region in regions]
    removed = {str(item) for item in (plan.get("remove_region_ids") or [])}
    by_id = {str(region.get("region_id") or region.get("id") or ""): region for region in source_regions}
    output: list[dict] = []
    claimed: set[str] = set()
    for block in plan.get("semantic_blocks", []):
        block = dict(block)
        member_ids = [str(item) for item in block.get("member_ids", [])]
        members = [by_id[item] for item in member_ids if item in by_id]
        placement = dict(block.get("placement") or {})
        translated = str(block.get("translated_text") or "").strip()
        if members:
            base = deepcopy(members[0])
            claimed.update(member_ids)
            if len(members) > 1:
                base["source_text"] = str(block.get("source_text") or " ".join(str(item.get("source_text") or "") for item in members)).strip()
                base["bbox"] = list(block.get("source_bbox") or base.get("bbox") or [])
            base["region_id"] = str(block.get("block_id"))
        else:
            base = {
                "region_id": str(block.get("block_id")),
                "page_index": int(block.get("page_index", 0)),
                "page_number": int(block.get("page_index", 0)) + 1,
                "source_text": str(block.get("source_text") or "").strip(),
                "bbox": list(block.get("source_bbox") or []),
                "provenance": "multimodal_plan",
                "action": "translate",
                "legacy_status": "missing",
                "qa_flags": [],
                "ocr_confidence": 1.0,
            }
        base.update(
            {
                "translated_text": translated,
                "source_text": str(block.get("source_text") or base.get("source_text") or "").strip(),
                "source_group_text": str(block.get("source_text") or base.get("source_text") or "").strip(),
                "source_group_bbox": list(block.get("source_bbox") or base.get("bbox") or []),
                "review_target_bbox": placement.get("selected_region"),
                "review_candidate_regions": placement.get("candidate_regions") or [],
                "review_font_size": float(placement.get("font_size") or block.get("font_size") or 0),
                "render_text": placement.get("render_text") or translated,
                "planned_color": placement.get("color") or [0.05, 0.16, 0.45],
                "rotation": int(placement.get("rotation", block.get("rotation", base.get("rotation", 0))) or 0) % 360,
                "placement_decision_source": "multimodal_v3",
                "strict_multimodal_execution": plan.get("execution_policy") == "strict_multimodal_execution",
                "translation_decision_source": "multimodal_v3",
                "placement_mode": placement.get("mode", "inline"),
                "placement_side": placement.get("side", "manual_review"),
                # A side is a location choice, not an implicit request for a
                # leader.  The supervisor must explicitly choose leader mode
                # (or set leader_required) when a connector is needed; this
                # keeps a close left/right inline caption from becoming a
                # spurious manual-review failure.
                "leader_required": bool(
                    placement.get("mode") == "leader"
                    or placement.get("leader_required") is True
                ),
                "leader_path": placement.get("leader_path") or [],
                "leader_caption_rotation": placement.get("leader_caption_rotation"),
                "leader_caption_orientation": placement.get("leader_caption_orientation"),
                "allow_source_overlap": bool(placement.get("allow_source_overlap")),
                "allow_dense_source_overlap": bool(placement.get("allow_dense_source_overlap")),
                "multimodal_visual_whitespace_override": bool(
                    placement.get("multimodal_visual_whitespace_override")
                ),
                # Some reviewed title-block cells are deliberately rendered by
                # the black bilingual panel-reflow pass before this inline
                # renderer runs.  Keep that ownership explicit: the inline
                # renderer must record the block as delivered, rather than
                # trying to add a second blue caption into the same tiny cell.
                "panel_reflow_managed": bool(placement.get("panel_reflow_managed")),
                "panel_reflow_panel_id": str(placement.get("panel_reflow_panel_id") or ""),
                "panel_reflow_field_id": str(placement.get("panel_reflow_field_id") or ""),
                "panel_reflow_target_bbox": list(
                    placement.get("panel_reflow_target_bbox") or placement.get("selected_region") or []
                ),
                "layout_role": block.get("layout_role", "label"),
                "coverage_status": block.get("coverage_status", "translated"),
                "semantic_group_id": str(block.get("block_id")),
                "member_count": len(member_ids),
                "qa_flags": sorted({*(base.get("qa_flags") or []), "multimodal_v3_plan"}),
            }
        )
        if base["coverage_status"] != "translated":
            base["action"] = "review"
            base["qa_flags"] = sorted({*(base.get("qa_flags") or []), "manual_review_required"})
        output.append(base)
    # Preserve source regions that the model explicitly marked literal/not-needed
    # or that have no block yet; the coverage gate can report them instead of the
    # renderer silently dropping visible source text.
    for region in source_regions:
        region_id = str(region.get("region_id") or region.get("id") or "")
        if region_id not in claimed and region_id not in removed:
            output.append(region)
    return output


def build_supervisor_handoff(
    plan: Mapping[str, object],
    *,
    source_pdf_path: Path | None = None,
) -> dict:
    """Create the explicit handoff consumed by OCR/translation executors.

    The multimodal supervisor is upstream of both tools.  This function keeps
    that decision visible instead of letting OCR geometry or a word-level
    translator silently invent work after the page has been planned.
    """

    supervisor = plan.get("supervisor_plan")
    if not isinstance(supervisor, Mapping):
        raise ValueError("supervisor_plan is required before OCR/translation execution")
    ocr_tasks = supervisor.get("ocr_tasks")
    translation_tasks = supervisor.get("translation_tasks")
    placement_policy = supervisor.get("placement_policy")
    if not isinstance(ocr_tasks, list) or not isinstance(translation_tasks, list) or not isinstance(placement_policy, Mapping):
        raise ValueError("supervisor_plan must declare OCR, translation, and placement tasks")
    return {
        "schema": "engineering-drawing-supervisor-handoff-v1",
        "contract_version": supervisor.get("contract_version") or V3_SUPERVISOR_CONTRACT,
        "workflow_version": plan.get("workflow_version") or WORKFLOW_VERSION,
        "model_name": plan.get("model_name") or supervisor.get("model_name"),
        "model_provider": plan.get("model_provider") or supervisor.get("model_provider"),
        "reasoning_profile": plan.get("reasoning_profile") or supervisor.get("reasoning_profile"),
        "supervisor_adapter": plan.get("supervisor_adapter") or supervisor.get("supervisor_adapter"),
        "model_capabilities": deepcopy(plan.get("model_capabilities") or []),
        "source_pdf": str(Path(source_pdf_path).resolve()) if source_pdf_path is not None else None,
        "page_type": plan.get("page_type") or supervisor.get("page_type"),
        "delivery_mode": plan.get("delivery_mode") or supervisor.get("delivery_mode"),
        "ocr_tasks": deepcopy(ocr_tasks),
        "ocr_execution_contract": {
            "authority": "multimodal_supervisor",
            "mode": "supervisor_declared_task_crops",
            "generic_full_page_fallback": False,
            "crop_expansion_or_relocation": False,
            "multi_page_requires_page_index": True,
        },
        "translation_tasks": deepcopy(translation_tasks),
        "placement_policy": deepcopy(dict(placement_policy)),
        "coverage_inventory": deepcopy(plan.get("coverage_inventory") or []),
        "escalations": deepcopy(supervisor.get("escalations") or []),
        "execution_rule": "execute_only_declared_tasks; escalate OCR/visual conflicts to supervisor",
    }


__all__ = [
    "V3_SCHEMA",
    "V3_DELIVERY_MODES",
    "V3_INLINE_EXCLUDED_PAGE_TYPES",
    "V3_SUPERVISOR_CONTRACT",
    "apply_multimodal_plan",
    "build_supervisor_handoff",
    "prepare_multimodal_plan_payload",
    "to_pdf_write_coordinates",
    "validate_multimodal_plan",
]
def _literal_only_is_semantically_safe(source_text: str) -> bool:
    """Return true only for bare values/codes that carry no prose semantics.

    V3.3 treats ``literal_only`` as a narrow exemption.  Natural-language
    labels, names, addresses and notes must be translated even when another OCR
    candidate looks similar; duplicate candidates belong to the same semantic
    block instead of disappearing behind a coverage status.
    """
    value = " ".join(str(source_text or "").split())
    if not re.search(r"[A-Za-z]", value):
        return True
    if re.fullmatch(r"(?:https?://|www\.)\S+|\S+@\S+", value, re.I):
        return True
    # Grid axes, section marks and detail callouts are often emitted by OCR as
    # a bare capital (or a compact pair such as ``AA``).  These are drawing
    # identifiers, not translatable prose.
    if re.fullmatch(r"[A-Z]{1,3}", value):
        return True
    if re.fullmatch(r"(?:N\.?T\.?S\.?|A[0-4]|P\d+|D\d+|R\d+|CL\.?\d+)", value, re.I):
        return True
    # Drawing/model/value identifiers must contain a digit and code punctuation
    # or be a compact number+unit token. Plain words such as FALL, ROOF, CSE,
    # company suffixes and role names are intentionally not exempt.
    if re.fullmatch(r"[A-Z0-9]+(?:[./:_-][A-Z0-9]+)+", value, re.I) and re.search(r"\d", value):
        return True
    # OCR commonly joins a dimension callout into one token (for example
    # ``500MM(H)...25MM...``).  With no word boundary it is a compact drawing
    # specification/value, not a readable natural-language note; retain it as
    # a literal while keeping ordinary spaced prose subject to translation.
    if (
        re.search(r"\d", value)
        and not re.search(r"\s", value)
        and re.fullmatch(r"[A-Z0-9×x().,/&+_\-\[\]{}'’µωε]+", value, re.I)
    ):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?\s*[A-Za-z]{1,5}", value):
        return True
    if re.fullmatch(r"[A-Z]{1,3}\d+", value):
        return True
    return False


def to_pdf_write_coordinates(
    plan: Mapping[str, object],
    *,
    source_pdf_path: Path,
) -> dict:
    """Normalize the coordinate contract consumed by the PyMuPDF renderer.

    Supervisor packets and the renderer both use ``page.rect``: the displayed
    page coordinate system after /Rotate. Native PDF extraction is converted to
    this system in ``agent_system._source_text_lines`` using rotation_matrix.
    Therefore a rendered-page supervisor target must *not* be derotated again
    before ``insert_textbox`` / drawing operations; doing so sends an otherwise
    valid visible target outside page.rect on 90/270-degree pages.
    """
    coordinate_space = _text(plan.get("coordinate_space") or "display_page_rect")
    if coordinate_space not in {"display_page_rect", "pdf_write_rect"}:
        raise ValueError("coordinate_space must be display_page_rect or pdf_write_rect")
    converted = deepcopy(dict(plan))
    converted["coordinate_space"] = coordinate_space
    converted["execution_coordinate_space"] = "display_page_rect"
    return converted


def _has_verified_ocr_artifact_evidence(item: Mapping[str, object]) -> bool:
    """Allow a natural-language OCR rejection only with auditable evidence.

    A low-confidence Paddle fragment can be visually confirmed as garbage or a
    false text detection.  It is not a translation exemption: native text,
    high-confidence OCR, and duplicate observations must still be represented
    by a semantic block.  Keeping this narrow protects the page-wide coverage
    gate while making artifact removal traceable.
    """
    evidence = item.get("ocr_artifact_evidence")
    if not isinstance(evidence, Mapping):
        return False
    try:
        confidence = float(evidence.get("ocr_confidence"))
    except (TypeError, ValueError):
        return False
    return (
        str(evidence.get("provenance") or "") == "paddle_ocr"
        and 0.0 <= confidence <= 0.65
        and evidence.get("visual_reviewed") is True
        and str(evidence.get("decision") or "") in {"garbled_fragment", "false_text_detection"}
        and bool(str(evidence.get("crop_reference") or "").strip())
    )
