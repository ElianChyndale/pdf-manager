"""Release gates for a real single multimodal engineering-drawing supervisor.

The old batch runner accepted self-declared ``model_name`` and
``decision_source`` fields.  Those fields describe a plan, but do not prove
that a vision model actually inspected the source page.  This module keeps the
deterministic renderer honest: a plan must carry an explicit supervisor
invocation record, page-image evidence, a complete zone/coverage inventory,
and (before release) the same supervisor's final visual decision.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

import fitz

from .workflow_policy import PRODUCTION_TYPOGRAPHY


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PLACEHOLDER_SOURCE_RE = re.compile(
    r"\b(?:visible\s+ruled|placeholder|complete\s+semantic|title\s+cell|"
    r"company,?\s+address\s+and\s+contact\s+text|row\s+\d+)\b",
    re.IGNORECASE,
)
_REGION_TYPES = {
    "drawing_body",
    "drawing_table",
    "sidebar_footer",
    "sidebar_footer_table",
    "directory_index",
    "company_contact_panel",
    "state_bearing_metadata",
    "prose_or_index_metadata",
}
_COVERAGE_STATUSES = {"translated", "literal_only", "not_needed", "manual_review"}
_HARD_REVIEW_CODES = {
    "omission",
    "wrong_translation",
    "fragmented_translation",
    "unclear_association",
    "blue_paint_overlap",
    "table_misalignment",
    "major_geometry_damage",
    "duplicate_translation",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object) -> str:
    return str(value or "").strip()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{field} must be an object")
    return value  # type: ignore[return-value]


def _normal_text(value: object) -> str:
    return re.sub(r"[^0-9a-z]+", "", _text(value).casefold())


def _one_edit_apart(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    short, long = (left, right) if len(left) < len(right) else (right, left)
    for index in range(len(long)):
        if long[:index] + long[index + 1 :] == short:
            return True
    return False


def _native_source_lines(path: Path) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    with fitz.open(path) as document:
        for page_index, page in enumerate(document):
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    text = " ".join(
                        str(span.get("text") or "").strip()
                        for span in line.get("spans", [])
                        if str(span.get("text") or "").strip()
                    ).strip()
                    normalized = _normal_text(text)
                    if len(normalized) < 2 or not re.search(r"[a-z]", normalized):
                        continue
                    dx, dy = line.get("dir") or (1, 0)
                    if abs(dx) >= abs(dy):
                        rotation = 0 if dx >= 0 else 180
                    else:
                        rotation = 90 if dy < 0 else 270
                    lines.append(
                        {
                            "page_index": page_index,
                            "text": text,
                            "normalized": normalized,
                            "rotation": rotation,
                        }
                    )
    return lines


def _validate_six_x_manual_review(
    item: Mapping[str, Any], candidate_id: str, *, source_sha256: str
) -> None:
    """Reject page/region/OCR-batch deferrals that lack original-PDF 6x proof."""

    _require(_text(item.get("source_bbox")), f"manual coverage item {candidate_id} requires source_bbox")
    evidence = _mapping(item.get("six_x_inspection"), f"manual coverage item {candidate_id}.six_x_inspection")
    _require(
        _text(evidence.get("source")).casefold() == "original_source_pdf",
        f"manual coverage item {candidate_id} must inspect original_source_pdf",
    )
    try:
        zoom_multiplier = float(evidence.get("zoom_multiplier"))
    except (TypeError, ValueError):
        zoom_multiplier = 0
    _require(zoom_multiplier == 6, f"manual coverage item {candidate_id} requires 6x original-PDF inspection")
    _require(
        _text(evidence.get("result")).casefold() == "individual_glyph_illegible",
        f"manual coverage item {candidate_id} is limited to one illegible glyph",
    )
    _require(
        _text(evidence.get("source_pdf_sha256")).casefold() == source_sha256.casefold(),
        f"manual coverage item {candidate_id} evidence does not bind to original source PDF",
    )
    _require(_text(evidence.get("crop_reference")), f"manual coverage item {candidate_id} requires crop_reference")
    _require(_text(evidence.get("observed_context")), f"manual coverage item {candidate_id} requires observed_context")
    glyph_bbox = evidence.get("glyph_bbox")
    _require(
        isinstance(glyph_bbox, (list, tuple)) and len(glyph_bbox) == 4,
        f"manual coverage item {candidate_id} requires one glyph_bbox",
    )


def _review_passed(review: Mapping[str, Any]) -> bool:
    status = _text(review.get("status")).casefold()
    if status not in {"pass", "passed", "accepted", "approved", "true"}:
        return False
    if review.get("passed") is False:
        return False
    findings = review.get("findings") or []
    if not isinstance(findings, list):
        return False
    return not any(
        isinstance(item, Mapping)
        and _text(item.get("code")).casefold() in _HARD_REVIEW_CODES
        for item in findings
    )


def validate_real_supervisor_plan(
    plan: Mapping[str, Any],
    *,
    source_pdf_path: Path | None = None,
    require_final_review: bool = False,
) -> dict[str, Any]:
    """Validate provenance and completeness before deterministic execution.

    This is intentionally stricter than the renderer schema.  The renderer can
    validate geometry and colours, but it cannot know whether a model really
    saw the page or whether a whole visual zone was omitted from the plan.
    """

    _require(isinstance(plan, Mapping), "supervisor plan must be an object")
    normalized = dict(plan)
    _require(
        _text(normalized.get("planning_authority")).casefold()
        == "real_multimodal_supervisor",
        "plan must declare planning_authority=real_multimodal_supervisor",
    )
    invocation = _mapping(
        normalized.get("supervisor_invocation"), "supervisor_invocation"
    )
    _require(
        invocation.get("verified") is True,
        "supervisor_invocation.verified must be true",
    )
    _require(
        _text(invocation.get("mode")).casefold()
        in {"codex_agent_multimodal", "agent_multimodal"},
        "supervisor_invocation.mode must identify a multimodal agent call",
    )
    model_name = _text(invocation.get("model") or normalized.get("model_name"))
    _require(model_name, "supervisor invocation requires model")
    _require(model_name == "gpt-5.6-sol", "production supervisor model must be gpt-5.6-sol")
    _require(
        _text(invocation.get("reasoning_profile") or normalized.get("reasoning_profile")).casefold() == "light",
        "production supervisor reasoning_profile must be light",
    )
    _require(_text(invocation.get("agent_id")), "supervisor invocation requires agent_id")
    _require(_text(invocation.get("started_at")), "supervisor invocation requires started_at")
    _require(_text(invocation.get("completed_at")), "supervisor invocation requires completed_at")
    _require(_text(invocation.get("response_sha256")), "supervisor invocation requires response_sha256")
    _require(
        bool(_SHA256_RE.fullmatch(_text(invocation.get("response_sha256")).casefold())),
        "supervisor invocation response_sha256 must be a SHA-256 digest",
    )
    source = normalized.get("render_provenance") or {}
    source = _mapping(source, "render_provenance")
    _require(
        _text(source.get("base")).casefold() == "original_source_pdf",
        "plan must render from original_source_pdf",
    )
    _require(
        source.get("copied_reference_page_or_region") is False,
        "reference pixels cannot be used as render base",
    )
    if source_pdf_path is not None:
        expected = file_sha256(Path(source_pdf_path))
        _require(
            _text(source.get("source_sha256")).casefold() == expected,
            "plan source_sha256 does not match original PDF",
        )
        _require(
            _text(invocation.get("source_sha256")).casefold() == expected,
            "supervisor invocation source_sha256 does not match original PDF",
        )

    _require(
        _text(normalized.get("coordinate_space")).casefold() == "display_page_rect",
        "plan coordinate_space must be display_page_rect",
    )

    page_images = normalized.get("page_image_evidence")
    _require(isinstance(page_images, list) and page_images, "plan requires page_image_evidence")
    for index, item in enumerate(page_images):
        evidence = _mapping(item, f"page_image_evidence[{index}]")
        _require(evidence.get("visual_inspection") is True, f"page_image_evidence[{index}] lacks visual inspection")
        _require(_text(evidence.get("image_sha256")), f"page_image_evidence[{index}] requires image_sha256")

    regions = normalized.get("page_region_map")
    _require(isinstance(regions, list) and regions, "plan requires page_region_map")
    region_ids: set[str] = set()
    for index, raw in enumerate(regions):
        region = _mapping(raw, f"page_region_map[{index}]")
        region_id = _text(region.get("region_id"))
        _require(region_id and region_id not in region_ids, f"duplicate/empty region id at {index}")
        region_ids.add(region_id)
        region_type = _text(region.get("region_type"))
        _require(region_type in _REGION_TYPES, f"unsupported region type: {region_type}")
        _require(
            _text(region.get("visual_reason")),
            f"page_region_map[{index}] requires visual_reason",
        )
        _require(
            _text(region.get("decision_source")).casefold()
            in {"multimodal_visual_plan", "real_multimodal_supervisor"},
            f"page_region_map[{index}] is not supervisor-authored",
        )

    coverage = normalized.get("coverage_inventory")
    _require(isinstance(coverage, list) and coverage, "plan requires coverage_inventory")
    coverage_ids: set[str] = set()
    for index, raw in enumerate(coverage):
        item = _mapping(raw, f"coverage_inventory[{index}]")
        candidate_id = _text(item.get("candidate_id"))
        _require(candidate_id and candidate_id not in coverage_ids, f"duplicate/empty coverage id at {index}")
        coverage_ids.add(candidate_id)
        status = _text(item.get("status")).casefold()
        _require(status in _COVERAGE_STATUSES, f"unsupported coverage status at {index}: {status}")
        _require(_text(item.get("source_text")), f"coverage_inventory[{index}] requires source_text")
        _require(
            not _PLACEHOLDER_SOURCE_RE.search(_text(item.get("source_text"))),
            f"coverage_inventory[{index}] contains a placeholder instead of visible source text",
        )
        if status in {"translated", "literal_only"}:
            _require(_text(item.get("source_bbox")), f"coverage_inventory[{index}] requires source_bbox")
        if status == "manual_review":
            _require(_text(item.get("reason")), f"manual coverage item {candidate_id} requires reason")
            _validate_six_x_manual_review(
                item,
                candidate_id,
                source_sha256=_text(source.get("source_sha256")),
            )

    evidence_items = normalized.get("coverage_evidence")
    _require(isinstance(evidence_items, list) and evidence_items, "plan requires non-empty coverage_evidence")
    evidenced_ids: set[str] = set()
    evidenced_pages: set[int] = set()
    for index, raw in enumerate(evidence_items):
        evidence = _mapping(raw, f"coverage_evidence[{index}]")
        _require(
            _text(evidence.get("source")).casefold() in {"native_pdf_text", "ocr", "native_plus_ocr"},
            f"coverage_evidence[{index}] requires a supported independent source",
        )
        candidate_ids = {_text(value) for value in (evidence.get("candidate_ids") or [])}
        _require(candidate_ids, f"coverage_evidence[{index}] requires candidate_ids")
        _require(candidate_ids.issubset(coverage_ids), f"coverage_evidence[{index}] references unknown candidates")
        _require(not (evidence.get("uncovered_candidate_ids") or []), f"coverage_evidence[{index}] reports uncovered candidates")
        evidenced_ids.update(candidate_ids)
        evidenced_pages.add(int(evidence.get("page_index", -1)))
    _require(evidenced_ids == coverage_ids, "coverage_evidence does not close every coverage candidate")

    if source_pdf_path is not None:
        coverage_texts = [_normal_text(item.get("source_text")) for item in coverage]
        for native in _native_source_lines(Path(source_pdf_path)):
            source_text = native["normalized"]
            if not any(
                source_text in candidate or candidate in source_text or _one_edit_apart(source_text, candidate)
                for candidate in coverage_texts
                if candidate
            ):
                raise ValueError(f"native source text is not covered: {native['text']}")

    unexplained = normalized.get("unexplained_region_ids") or []
    _require(not unexplained, "unexplained visible regions block release")
    blocks = normalized.get("semantic_blocks")
    _require(isinstance(blocks, list) and blocks, "plan requires semantic_blocks")
    block_ids: set[str] = set()
    for index, raw in enumerate(blocks):
        block = _mapping(raw, f"semantic_blocks[{index}]")
        block_id = _text(block.get("block_id"))
        _require(block_id and block_id not in block_ids, f"duplicate/empty block id at {index}")
        block_ids.add(block_id)
        _require(_text(block.get("page_region_id")) in region_ids, f"block {block_id} has no declared zone")
        status = _text(block.get("coverage_status")).casefold()
        _require(status in _COVERAGE_STATUSES, f"block {block_id} has invalid coverage status")
        if status in {"translated", "literal_only"}:
            source_bbox = block.get("source_bbox")
            _require(
                isinstance(source_bbox, (list, tuple)) and len(source_bbox) == 4,
                f"block {block_id} requires source_bbox for executable placement",
            )
        if status == "translated":
            _require(bool(_CJK_RE.search(_text(block.get("translated_text")))), f"block {block_id} lacks Chinese translation")
            _require(
                not _PLACEHOLDER_SOURCE_RE.search(_text(block.get("source_text"))),
                f"block {block_id} contains a placeholder instead of visible source text",
            )
        placement = _mapping(block.get("placement"), f"semantic_blocks[{index}].placement")
        _require(_text(placement.get("target_bbox") or placement.get("selected_region")), f"block {block_id} lacks selected target")
        region_type = _text(block.get("region_type"))
        if status == "translated":
            render_mode = _text(placement.get("render_mode")).casefold()
            _require(
                render_mode in {"preserve_source_blue_chinese", "opaque_bilingual_reflow"},
                f"translated block {block_id} requires exactly one approved render_mode",
            )
            masks = placement.get("exact_ink_masks") or []
            runs = placement.get("render_runs") or []
            if render_mode == "preserve_source_blue_chinese":
                _require(not masks, f"source-preserving block {block_id} must not use masks")
                color = placement.get("color")
                _require(color is None or color in ("blue", "dark_blue") or color == [0.05, 0.16, 0.45], f"source-preserving block {block_id} requires blue Chinese")
            else:
                combined = " ".join(_text(run.get("text")) for run in runs if isinstance(run, Mapping))
                _require(masks, f"opaque bilingual block {block_id} requires complete old-glyph masks")
                _require(bool(_CJK_RE.search(combined)) and bool(re.search(r"[A-Za-z]", combined)), f"opaque bilingual block {block_id} requires black source plus Chinese render runs")
                _require(placement.get("old_source_glyphs_visible") is False, f"opaque bilingual block {block_id} must leave no old source glyph visible")
                _require(placement.get("partial_mask_overlap") in {False, 0}, f"opaque bilingual block {block_id} must not mix old and new text")
        member_rotations = {
            int(item.get("rotation", 0) or 0) % 360
            for item in coverage
            if _text(item.get("candidate_id")) in set(block.get("member_ids") or [])
        }
        placement_rotation = int(placement.get("rotation", 0) or 0) % 360
        _require(
            len(member_rotations) == 1 and placement_rotation in member_rotations,
            f"block {block_id} translation rotation must match source rotation",
        )
        mode = _text(placement.get("mode")).casefold()
        if region_type == "directory_index":
            _require(mode in {"table_cell", "title_block"}, f"directory block {block_id} must use table_cell/title_block")
            _require(_text(block.get("cell_id") or block.get("row_key")), f"directory block {block_id} requires cell_id/row_key")
            runs = placement.get("render_runs") or []
            combined = " ".join(_text(run.get("text")) for run in runs if isinstance(run, Mapping))
            _require(
                bool(_CJK_RE.search(combined)) and bool(re.search(r"[A-Za-z]", combined)),
                f"directory block {block_id} bilingual reflow requires source plus Chinese render runs",
            )
            minimum = float(PRODUCTION_TYPOGRAPHY["directory_index"]["hard_minimum_pt"])
            _require(
                all(float(run.get("font_size") or 0) >= minimum for run in runs if isinstance(run, Mapping)),
                f"directory block {block_id} requires typography of at least {minimum:.1f}pt",
            )
            if placement.get("exact_ink_masks"):
                mask_audit = _mapping(placement.get("mask_protection_audit"), f"directory block {block_id} mask_protection_audit")
                _require(
                    float(mask_audit.get("protected_intersection_area", -1)) == 0.0,
                    f"directory block {block_id} mask intersects a protected column or table rule",
                )
                _require(
                    mask_audit.get("row_numbers_source_match") is True,
                    f"directory block {block_id} must preserve every source row number visibly",
                )
                _require(
                    float(mask_audit.get("minimum_clearance_pt", 0)) >= 1.5,
                    f"directory block {block_id} mask requires at least 1.5pt protected-field clearance",
                )
        elif region_type == "company_contact_panel":
            minimum = float(PRODUCTION_TYPOGRAPHY["company_contact_panel"]["hard_minimum_pt"])
            runs = placement.get("render_runs") or []
            sizes = [float(run.get("font_size") or 0) for run in runs if isinstance(run, Mapping)]
            if sizes:
                _require(min(sizes) >= minimum, f"company block {block_id} requires typography of at least {minimum:.1f}pt")
            else:
                _require(float(placement.get("font_size") or 0) >= minimum, f"company block {block_id} requires typography of at least {minimum:.1f}pt")
        elif region_type in {"drawing_body", "drawing_table", "state_bearing_metadata"}:
            minimum = float(PRODUCTION_TYPOGRAPHY["drawing_body"]["hard_minimum_pt"])
            _require(float(placement.get("font_size") or 0) >= minimum, f"drawing block {block_id} requires typography of at least {minimum:.1f}pt")
        if len(block.get("member_ids") or []) > 1:
            group_layout = placement.get("group_layout")
            _require(isinstance(group_layout, Mapping), f"grouped block {block_id} requires group_layout")
            _require(
                group_layout.get("independent_fragment_placement") is False,
                f"grouped block {block_id} cannot scatter fragments",
            )
            if region_type in {"drawing_body", "drawing_table", "state_bearing_metadata"} and source_pdf_path is not None:
                member_set = set(block.get("member_ids") or [])
                member_boxes = [
                    item.get("source_bbox")
                    for item in coverage
                    if _text(item.get("candidate_id")) in member_set
                    and isinstance(item.get("source_bbox"), (list, tuple))
                    and len(item.get("source_bbox")) == 4
                ]
                if len(member_boxes) > 1:
                    centers_x = [(float(box[0]) + float(box[2])) / 2 for box in member_boxes]
                    centers_y = [(float(box[1]) + float(box[3])) / 2 for box in member_boxes]
                    with fitz.open(Path(source_pdf_path)) as document:
                        page = document[int(block.get("page_index", 0) or 0)]
                        incoherent = (
                            max(centers_x) - min(centers_x) > page.rect.width * 0.30
                            or max(centers_y) - min(centers_y) > page.rect.height * 0.20
                        )
                    _require(not incoherent, f"grouped block {block_id} is spatially incoherent")

    if _text(normalized.get("page_type")).casefold() in {"dense_drawing_index", "sheet_index", "catalog_table"}:
        _require(
            _text(normalized.get("delivery_mode")).casefold() == "opaque_bilingual_reflow",
            "dense index pages require opaque_bilingual_reflow",
        )
        _require(
            any(_text(item.get("region_type")) == "directory_index" for item in regions),
            "dense index pages require a directory_index zone",
        )

    if require_final_review:
        review = _mapping(normalized.get("final_visual_review"), "final_visual_review")
        _require(review.get("same_supervisor") is True, "final review must be performed by the same supervisor")
        _require(_review_passed(review), "final visual review did not pass")
        questions = review.get("questions")
        _require(isinstance(questions, Mapping), "final visual review requires the three review questions")
        for key in ("chinese_understandable", "association_clear", "no_omission_or_damage"):
            _require(questions.get(key) is True, f"final visual review question failed: {key}")

    normalized["supervisor_invocation"] = dict(invocation)
    normalized["planning_authority"] = "real_multimodal_supervisor"
    normalized["page_image_evidence"] = [dict(item) for item in page_images]
    return normalized


def build_review_gate(*, review: Mapping[str, Any], visual_qa: Mapping[str, Any]) -> dict[str, Any]:
    """Combine deterministic diagnostics with the supervisor's three questions."""
    result = dict(review)
    effective_qa = dict(visual_qa)
    # The detector deliberately errs on the side of caution. A same-supervisor
    # page review may downgrade source-only overlap alerts when the rendered
    # page proves that the original remains readable and association is clear.
    # Translation-to-translation collisions and unresolved layout can never be
    # downgraded through this path.
    soft_ids = set(review.get("soft_advisory_region_ids") or [])
    hard_items = list(effective_qa.get("visual_overlap_items") or [])
    downgraded = [x for x in hard_items if x.get("region_id") in soft_ids and not x.get("target_overlap_region_ids")]
    remaining = [x for x in hard_items if x not in downgraded]
    if downgraded:
        effective_qa["visual_overlap_items"] = remaining
        effective_qa["visual_overlap_count"] = len(remaining)
        effective_qa["visual_overlap_advisory_items"] = list(effective_qa.get("visual_overlap_advisory_items") or []) + [dict(x, reason="same_supervisor_visual_soft_advisory") for x in downgraded]
        effective_qa["visual_overlap_advisory_count"] = len(effective_qa["visual_overlap_advisory_items"])
        effective_qa["passed"] = not remaining and not effective_qa.get("leader_collision_count") and not effective_qa.get("untranslated_candidate_count") and not effective_qa.get("manual_review_count")
    result["deterministic_visual_qa"] = effective_qa
    # A renderer can report ``passed`` while retaining an item it could not
    # place (for example, text that did not fit).  That is not a publishable
    # result under the user's completeness gate: let the supervisor see the
    # candidate, but block release until the item is planned again or marked
    # for human handling.
    unresolved_layout = int(effective_qa.get("manual_review_count") or 0) > 0
    result["passed"] = (
        bool(_review_passed(review))
        and bool(effective_qa.get("passed"))
        and not unresolved_layout
    )
    result["release_blocking_reasons"] = []
    if not effective_qa.get("passed"):
        result["release_blocking_reasons"].append("deterministic_visual_qa_failed")
    if unresolved_layout:
        result["release_blocking_reasons"].append("unresolved_layout_manual_review")
    if not _review_passed(review):
        result["release_blocking_reasons"].append("supervisor_visual_review_failed")
    return result


__all__ = ["build_review_gate", "file_sha256", "validate_real_supervisor_plan"]
