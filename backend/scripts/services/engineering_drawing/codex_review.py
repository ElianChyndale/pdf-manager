from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable

import fitz

from .workflow_policy import LAYOUT_POLICY
from .workflow_policy import PRODUCTION_TYPOGRAPHY
from .workflow_policy import SEMANTIC_GROUP_POLICY
from .workflow_policy import SUPERVISOR_POLICY
from .workflow_policy import VISUAL_QA_POLICY
from .workflow_policy import DEFAULT_MULTIMODAL_MODEL, WORKFLOW_VERSION


SCHEMA = "engineering-drawing-codex-review-v1"
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LAYOUT_ROLES = {
    "label",
    "dense_cad_label",
    "title_block",
    "table_cell",
    "address",
    "paragraph",
    "legend",
}
_PLACEMENT_MODES = {"inline", "leader", "title_block", "manual_review"}
_COVERAGE_STATUSES = {
    "translated",
    "no_translation_needed",
    "missing",
    "low_confidence",
}
_ZONE_MINIMUM_PT = {
    "directory_index": 6.8,
    "company_contact_panel": 6.4,
    "drawing_body": 5.8,
    "drawing_table": 5.8,
    "state_bearing_metadata": 5.8,
    "prose_or_index_metadata": 6.4,
}
_APPROVED_MULTIMODAL_MARKERS = (
    "sol",
)


def _rect(value: object, *, field: str) -> fitz.Rect:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{field} must contain four coordinates")
    try:
        rect = fitz.Rect(*(float(item) for item in value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} contains a non-numeric coordinate") from exc
    if rect.is_empty or rect.is_infinite:
        raise ValueError(f"{field} must be a finite, non-empty rectangle")
    return rect


def _page_sizes_from_pdf(source_pdf_path: Path) -> list[tuple[float, float]]:
    with fitz.open(source_pdf_path) as document:
        return [(page.rect.width, page.rect.height) for page in document]


def _normalized_page_sizes(values: Iterable[object]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"page_sizes[{index}] must contain width and height")
        width, height = float(value[0]), float(value[1])
        if width <= 0 or height <= 0:
            raise ValueError(f"page_sizes[{index}] must be positive")
        result.append((width, height))
    return result


def _validate_target(
    item: dict,
    *,
    page_index: int,
    page_sizes: list[tuple[float, float]],
    field: str = "target_bbox",
) -> fitz.Rect:
    if not 0 <= page_index < len(page_sizes):
        raise ValueError(f"page_index {page_index} is outside the source PDF")
    rect = _rect(item.get(field), field=field)
    width, height = page_sizes[page_index]
    if not fitz.Rect(0, 0, width, height).contains(rect):
        raise ValueError(f"{field} is outside page {page_index + 1}")
    rotation = float(item.get("rotation", 0) or 0) % 360
    if not 0 <= rotation < 360:
        raise ValueError("rotation must be a finite local source angle")
    region_type = str(item.get("region_type") or "").strip().casefold()
    if region_type not in _ZONE_MINIMUM_PT:
        raise ValueError("every placement requires a V4 region_type")
    font_size = float(item.get("font_size", 0) or 0)
    minimum = _ZONE_MINIMUM_PT[region_type]
    if not minimum <= font_size <= 18:
        raise ValueError(f"{region_type} font_size must be between {minimum:.1f} and 18 points")
    if not str(item.get("reason") or "").strip():
        raise ValueError("every multimodal decision requires a reason")
    return rect


def _normalize_layout_decision(
    item: dict,
    *,
    field: str,
    allow_planned_leaders: bool = False,
) -> None:
    """Validate layout semantics attached to a visual-review placement."""
    layout_role = str(item.get("layout_role") or "label").strip().casefold()
    if layout_role not in _LAYOUT_ROLES:
        raise ValueError(f"{field} layout_role is not supported")
    placement_mode = str(item.get("placement_mode") or "inline").strip().casefold()
    if placement_mode not in _PLACEMENT_MODES:
        raise ValueError(f"{field} placement_mode is not supported")
    leader = item.get("leader")
    leader_required = placement_mode == "leader" or leader is True or str(leader or "").casefold() in {"required", "leader"}
    if (
        leader_required
        and not allow_planned_leaders
        and layout_role in {"title_block", "table_cell", "address", "paragraph"}
    ):
        raise ValueError(f"{field} must not use a leader in a title block, table, address, or paragraph")
    if placement_mode == "title_block" and layout_role not in {"title_block", "table_cell", "address", "paragraph"}:
        raise ValueError(f"{field} title_block placement_mode requires a title/table layout_role")
    coverage_status = str(item.get("coverage_status") or "translated").strip().casefold()
    if coverage_status not in _COVERAGE_STATUSES:
        raise ValueError(f"{field} coverage_status is not supported")
    if coverage_status != "translated" and placement_mode != "manual_review":
        raise ValueError(f"{field} non-translated coverage must use manual_review placement_mode")
    item.update(
        {
            "layout_role": layout_role,
            "placement_mode": placement_mode,
            "leader_required": leader_required,
            "coverage_status": coverage_status,
        }
    )


def validate_codex_review_plan(
    payload: dict,
    *,
    page_sizes: Iterable[object] | None = None,
    source_pdf_path: Path | None = None,
) -> dict:
    """Validate a versioned handoff from an approved multimodal review."""
    if not isinstance(payload, dict):
        raise ValueError("Codex review plan must be a JSON object")
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"Codex review plan schema must be {SCHEMA}")
    model_name = str(payload.get("model") or "").strip().casefold()
    if model_name != DEFAULT_MULTIMODAL_MODEL.casefold():
        raise ValueError("Codex review plan must name the approved Sol model")
    if str(payload.get("reasoning_profile") or "").strip().casefold() != "light":
        raise ValueError("Codex review plan requires reasoning_profile=light")
    if str(payload.get("supervisor_adapter") or "").strip().casefold() != "codex-sol-light":
        raise ValueError("Codex review plan requires supervisor_adapter=codex-sol-light")
    if payload.get("status") != "approved":
        raise ValueError("Codex review plan must have status=approved")
    declared_workflow = str(payload.get("workflow_version") or "").strip()
    if declared_workflow != WORKFLOW_VERSION:
        raise ValueError(
            f"Codex review plan workflow_version must be {WORKFLOW_VERSION}"
        )
    if "sol" not in model_name:
        raise ValueError("non-Sol review plans have no production planning authority")
    allow_planned_leaders = declared_workflow == WORKFLOW_VERSION

    if source_pdf_path is not None:
        sizes = _page_sizes_from_pdf(Path(source_pdf_path))
    elif page_sizes is not None:
        sizes = _normalized_page_sizes(page_sizes)
    else:
        sizes = _normalized_page_sizes(payload.get("page_sizes") or [])
    if not sizes:
        raise ValueError("Codex review plan requires source page sizes")

    normalized = dict(payload)
    normalized["workflow_version"] = WORKFLOW_VERSION
    normalized["page_sizes"] = [[float(width), float(height)] for width, height in sizes]
    normalized["remove_region_ids"] = [
        str(region_id).strip()
        for region_id in payload.get("remove_region_ids", [])
        if str(region_id).strip()
    ]

    moves: list[dict] = []
    for index, raw in enumerate(payload.get("moves", [])):
        item = dict(raw)
        region_id = str(item.get("region_id") or "").strip()
        if not region_id:
            raise ValueError(f"moves[{index}] requires region_id")
        page_index = int(item.get("page_index", 0) or 0)
        target = _validate_target(item, page_index=page_index, page_sizes=sizes)
        corrected_translation = str(item.get("translated_text") or "").strip()
        if corrected_translation and not _CJK_RE.search(corrected_translation):
            raise ValueError(
                f"moves[{index}] translated_text correction must contain Chinese"
            )
        item.update(
            {
                "region_id": region_id,
                "page_index": page_index,
                "target_bbox": list(target),
                "rotation": float(item.get("rotation", 0) or 0) % 360,
                "font_size": float(item["font_size"]),
                "reason": str(item["reason"]).strip(),
            }
        )
        _normalize_layout_decision(
            item,
            field=f"moves[{index}]",
            allow_planned_leaders=allow_planned_leaders,
        )
        if corrected_translation:
            item["translated_text"] = corrected_translation
        moves.append(item)
    normalized["moves"] = moves

    additions: list[dict] = []
    for index, raw in enumerate(payload.get("additions", [])):
        item = dict(raw)
        region_id = str(item.get("region_id") or "").strip()
        if not region_id:
            raise ValueError(f"additions[{index}] requires region_id")
        translated = str(item.get("translated_text") or "").strip()
        if not _CJK_RE.search(translated):
            raise ValueError(f"additions[{index}] translated_text must contain Chinese")
        source_text = str(item.get("source_text") or "").strip()
        if not source_text:
            raise ValueError(f"additions[{index}] requires visible source_text")
        page_index = int(item.get("page_index", 0) or 0)
        source_rect = _rect(item.get("source_bbox"), field="source_bbox")
        width, height = sizes[page_index]
        if not fitz.Rect(0, 0, width, height).contains(source_rect):
            raise ValueError(f"source_bbox is outside page {page_index + 1}")
        target = _validate_target(item, page_index=page_index, page_sizes=sizes)
        confidence = float(item.get("confidence", 0) or 0)
        if not 0.8 <= confidence <= 1:
            raise ValueError("multimodal additions require confidence between 0.8 and 1")
        item.update(
            {
                "region_id": region_id,
                "page_index": page_index,
                "source_text": source_text,
                "translated_text": translated,
                "source_bbox": list(source_rect),
                "target_bbox": list(target),
                "rotation": float(item.get("rotation", 0) or 0) % 360,
                "font_size": float(item["font_size"]),
                "confidence": confidence,
                "reason": str(item["reason"]).strip(),
            }
        )
        _normalize_layout_decision(
            item,
            field=f"additions[{index}]",
            allow_planned_leaders=allow_planned_leaders,
        )
        additions.append(item)
    normalized["additions"] = additions

    coverage: list[dict] = []
    for index, raw in enumerate(payload.get("coverage", [])):
        item = dict(raw)
        page_index = int(item.get("page_index", 0) or 0)
        if not 0 <= page_index < len(sizes):
            raise ValueError(f"coverage[{index}] page_index is outside the source PDF")
        source_text = str(item.get("source_text") or "").strip()
        if not source_text:
            raise ValueError(f"coverage[{index}] requires source_text")
        status = str(item.get("status") or "").strip().casefold()
        if status not in _COVERAGE_STATUSES:
            raise ValueError(f"coverage[{index}] status is not supported")
        reason = str(item.get("reason") or "").strip()
        if not reason:
            raise ValueError(f"coverage[{index}] requires a reason")
        source_bbox = item.get("source_bbox")
        if source_bbox is not None:
            rect = _rect(source_bbox, field=f"coverage[{index}].source_bbox")
            width, height = sizes[page_index]
            if not fitz.Rect(0, 0, width, height).contains(rect):
                raise ValueError(f"coverage[{index}].source_bbox is outside page {page_index + 1}")
            item["source_bbox"] = list(rect)
        item.update(
            {
                "page_index": page_index,
                "source_text": source_text,
                "status": status,
                "reason": reason,
            }
        )
        coverage.append(item)
    normalized["coverage"] = coverage
    expected_line_ids = [str(value).strip() for value in payload.get("source_line_ids", []) if str(value).strip()]
    if not expected_line_ids:
        raise ValueError("Codex review plan requires source_line_ids for closure validation")
    actual_line_ids = [str(item.get("line_id") or "").strip() for item in coverage]
    if any(not value for value in actual_line_ids):
        raise ValueError("every coverage item requires line_id")
    if len(actual_line_ids) != len(set(actual_line_ids)):
        raise ValueError("coverage line_id values must be unique")
    if set(actual_line_ids) != set(expected_line_ids):
        raise ValueError("coverage must close every source_line_id exactly once")
    if any(item["status"] != "translated" for item in coverage):
        raise ValueError("V4 production coverage requires every natural-language line translated")
    normalized["source_line_ids"] = expected_line_ids
    normalized["validated_v4_sol_light"] = True
    return normalized


def apply_codex_review_plan(regions: Iterable[dict], plan: dict) -> list[dict]:
    """Apply remove/move/add decisions without mutating the OCR source records."""
    if plan.get("validated_v4_sol_light") is not True:
        raise ValueError("apply requires a validated V4 Sol Light plan")
    model_name = str(plan.get("model") or "").casefold()
    review_source = "codex_sol"
    review_provenance = "codex_sol_review"
    review_flag = "codex_sol_visual_review"
    removed = set(plan.get("remove_region_ids", []))
    moves = {item["region_id"]: item for item in plan.get("moves", [])}
    reviewed: list[dict] = []
    seen: set[str] = set()
    for raw in regions:
        region = dict(raw)
        region_id = str(region.get("region_id") or "")
        if region_id in removed:
            continue
        if region_id in moves:
            decision = moves[region_id]
            region.update(
                {
                    "review_target_bbox": list(decision["target_bbox"]),
                    "review_font_size": float(decision["font_size"]),
                    "rotation": float(decision["rotation"]),
                    "placement_decision_source": review_source,
                    "review_reason": decision["reason"],
                    "layout_role": decision["layout_role"],
                    "placement_mode": decision["placement_mode"],
                    "leader_required": bool(decision["leader_required"]),
                    "coverage_status": decision["coverage_status"],
                }
            )
            if decision.get("translated_text"):
                region["translated_text"] = decision["translated_text"]
                region["translation_decision_source"] = review_source
            if decision["coverage_status"] != "translated":
                region["action"] = "review"
                region.setdefault("qa_flags", []).append("manual_review_required")
        reviewed.append(region)
        seen.add(region_id)

    missing_move_ids = set(moves) - seen
    if missing_move_ids:
        raise ValueError(
            "Multimodal move references unknown region ids: "
            + ", ".join(sorted(missing_move_ids))
        )

    for item in plan.get("additions", []):
        if item["region_id"] in seen:
            raise ValueError(f"duplicate multimodal addition id: {item['region_id']}")
        reviewed.append(
            {
                "region_id": item["region_id"],
                "page_index": item["page_index"],
                "page_number": item["page_index"] + 1,
                "source_text": item["source_text"],
                "translated_text": item["translated_text"],
                "bbox": list(item["source_bbox"]),
                "review_target_bbox": list(item["target_bbox"]),
                "review_font_size": float(item["font_size"]),
                "rotation": int(item["rotation"]),
                "provenance": review_provenance,
                "action": "translate",
                "placement": "inline_only",
                "placement_decision_source": review_source,
                "layout_role": item["layout_role"],
                "placement_mode": item["placement_mode"],
                "leader_required": bool(item["leader_required"]),
                "addition_approval": "ai_verified_source",
                "approval_evidence": item["reason"],
                "review_reason": item["reason"],
                "ocr_confidence": item["confidence"],
                "ai_judgement": "accepted",
                "coverage_status": item["coverage_status"],
                "qa_flags": [review_flag],
            }
        )
        seen.add(item["region_id"])
    return reviewed


def _page_text_lines(page: fitz.Page) -> list[dict]:
    lines: list[dict] = []
    page_rotation = int(page.rotation or 0) % 360
    matrix = page.rotation_matrix
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            text = " ".join(
                str(span.get("text") or "").strip()
                for span in line.get("spans", [])
                if str(span.get("text") or "").strip()
            ).strip()
            if text:
                bbox = fitz.Rect(line["bbox"])
                if page_rotation:
                    bbox = bbox * matrix
                lines.append(
                    {
                        "text": text,
                        "bbox": list(bbox),
                        "direction": list(line.get("dir", (1.0, 0.0))),
                    }
                )
    return lines


def build_codex_review_package(
    *,
    source_pdf_path: Path,
    draft_pdf_path: Path,
    regions: Iterable[dict],
    placement_audit: Iterable[dict],
    output_dir: Path,
    dpi: int = 144,
) -> Path:
    """Export visual and structural context for a Codex Sol review task."""
    source_pdf_path = Path(source_pdf_path)
    draft_pdf_path = Path(draft_pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72
    pages: list[dict] = []
    with fitz.open(source_pdf_path) as source, fitz.open(draft_pdf_path) as draft:
        if source.page_count != draft.page_count:
            raise ValueError("source and draft page counts differ")
        for page_index, (source_page, draft_page) in enumerate(zip(source, draft)):
            source_name = f"page-{page_index + 1:03d}-source.png"
            draft_name = f"page-{page_index + 1:03d}-draft.png"
            source_page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), alpha=False
            ).save(output_dir / source_name)
            draft_page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), alpha=False
            ).save(output_dir / draft_name)
            pages.append(
                {
                    "page_index": page_index,
                    "size": [source_page.rect.width, source_page.rect.height],
                    "source_image": source_name,
                    "draft_image": draft_name,
                    "source_text_lines": _page_text_lines(source_page),
                }
            )

    review_input = output_dir / "review-input.json"
    review_input.write_text(
        json.dumps(
            {
                "schema": "engineering-drawing-codex-review-input-v1",
                "required_model_family": DEFAULT_MULTIMODAL_MODEL,
                "workflow_version": WORKFLOW_VERSION,
                "source_pdf": str(source_pdf_path.resolve()),
                "draft_pdf": str(draft_pdf_path.resolve()),
                "layout_policy": {
                    **LAYOUT_POLICY,
                    "production_typography": PRODUCTION_TYPOGRAPHY,
                    "workflow_version": WORKFLOW_VERSION,
                    "semantic_group_policy": "block-level semantic grouping before translation and placement; merge related fragments into one complete block; never scatter one block into word-sized captions",
                    "semantic_grouping": SEMANTIC_GROUP_POLICY,
                    "supervisor": SUPERVISOR_POLICY,
                    "visual_qa": VISUAL_QA_POLICY,
                },
                "instructions": [
                    "Review the source image and the draft image as a pair. Classify every visible non-Chinese natural-language candidate, including English, Malay, Arabic/Jawi and other scripts, as translated, missing, or low_confidence in coverage. Reserve no_translation_needed for classifier-confirmed pure codes, numbers, units, email addresses or URLs only.",
                    "Treat adjacent OCR/native fragments that form one label, equipment name, voltage/unit/model string, or wrapped note as one semantic group. Translate a sentence-like title or note as one coherent Chinese block, preserving reading order and using line breaks when the source wraps. Supply one complete Chinese translation and one placement decision for the group, never a separate Chinese caption for each word, character, or OCR fragment.",
                    "Do not merge independent identifiers, dimensions, units, standards, room/equipment labels, phone/email/URL tokens, title-block field rows, table cells, legend entries, or separate callouts. If the grouping is uncertain, keep the records separate and mark the group for visual review.",
                    "For title blocks, directory cells, company panels, addresses, and project descriptions, inspect the actual blank rectangle and choose the largest readable Chinese size that fits with the required padding. No fixed direction has priority: keep the block in the same semantic cell when possible and choose right, below, above, or left from measured whitespace; use nearby external whitespace with a short orthogonal leader only when the cell cannot safely fit the complete block.",
                    "Classify drawing-index, sheet-index, and dense catalog-table pages as page_type=dense_drawing_index. Do not propose inline_bilingual or legacy overlay_pair captions for these pages; require delivery_mode=opaque_bilingual_reflow on the original PDF and preserve the row/grid/model hierarchy.",
                    "For dense CAD labels with no local whitespace, set placement_mode=leader and leader=required. Score whole semantic-group candidates in a bounded 12-48pt range, then use one short direct dark-blue 0.32pt callout with no arrow only when needed. The route must not cross the Chinese block; ordinary background-line crossings are advisory.",
                    "Existing Chinese is wording evidence only. Revalidate its completeness, zone, direction, size, and placement under V4 before reusing it. Every distinct equipment instance or identifier must receive its own translation, even when the source wording repeats.",
                    "Do not cover most of a source block, dimensions, symbols, equipment, linework, title-block rules, or prior Chinese captions. A direct target should use clear background; a small source/table-line overlap is acceptable only when the complete Chinese block remains readable and nearby.",
                    "A legacy translation or placement has no automatic authority. Revalidate it under V4; repair or replace it when incomplete, microscopic, wrongly oriented, or in the wrong zone.",
                    "Choose Chinese sizing per semantic group and hierarchy. Readability at normal review zoom is a release gate: directory text must be at least 6.8pt, company-panel text at least 6.4pt, and drawing-body text at least 5.8pt. Preserve locally readable orientation, never mirror or leave Chinese upside-down. Translate repeated visible titles on every page. For genuinely unreadable source text, keep it visible and request multimodal review rather than inventing meaning.",
                    "Review and approve one PDF page at a time; do not emit a batch plan spanning unrelated PDFs or pages.",
                    f"Return an approved {SCHEMA} JSON plan.",
                ],
                "pages": pages,
                "regions": list(regions),
                "placement_audit": list(placement_audit),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return review_input
