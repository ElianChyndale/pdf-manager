"""Single-supervisor engineering-drawing translation agent contract.

This module is intentionally independent from OCR and rendering.  It freezes the
original PDF, assembles the page-level visual planning packet, and exposes the
release gates agreed during the design review.  A renderer may run only after an
approved multimodal page plan has been attached to the packet.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import fitz

from .orchestration_harness import HARNESS_SCHEMA, STAGES, canonical_policy_fingerprint
from .semantic_knowledge import supervisor_knowledge_context
from .workflow_policy import (
    DEFAULT_MULTIMODAL_MODEL,
    SUPERVISOR_POLICY,
    VISUAL_QA_POLICY,
    WORKFLOW_VERSION,
    policy_snapshot,
)


AGENT_SCHEMA = "engineering-drawing-translation-agent-v1"
AGENT_NAME = "engineering-drawing-translator"
AGENT_ROLE = "single_multimodal_page_supervisor"
MAX_AUTOMATIC_REPAIRS = 1


STRICT_GATES = {
    "important_natural_language_complete": True,
    "engineering_meaning_and_parameters_correct": True,
    "semantic_group_understandable": True,
    "source_object_association_clear": True,
    "no_blue_paint_stacking": True,
    "table_row_model_relationships_correct": True,
    "major_geometry_logo_dimension_device_wiring_protected": True,
    "normal_zoom_readability": True,
}

SOFT_CONCERNS = {
    "leader_crosses_ordinary_engineering_line": True,
    "minor_table_or_fill_line_overlap": True,
    "distance_not_absolute_shortest": True,
    "font_size_not_identical_to_source": True,
    "two_or_three_line_or_diagonal_translation": True,
    "different_font_sizes_on_one_page": True,
    "local_visual_density": True,
    "leader_not_beautiful_but_short_and_clear": True,
}

IGNORED_METRICS = {
    "perfect_ink_avoidance_for_each_leader": True,
    "same_font_size_for_every_translation": True,
    "one_ocr_box_per_translation_box": True,
    "zero_automatic_collision_score": True,
    "fixed_region_count_in_json": True,
    "four_x_pixel_level_difference": True,
    "fixed_direction_priority": True,
}

REVIEW_QUESTIONS = (
    "If only the Chinese is read, can an engineer understand the main content?",
    "Is each Chinese block clearly associated with its source text or engineering object?",
    "Are there obvious omissions or serious visual damage?",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SourceSnapshot:
    source_pdf: str
    source_sha256: str
    page_count: int
    page_sizes: list[list[float]]

    @classmethod
    def from_pdf(cls, path: Path) -> "SourceSnapshot":
        path = Path(path).resolve()
        with fitz.open(path) as document:
            page_sizes = [[float(page.rect.width), float(page.rect.height)] for page in document]
            page_count = document.page_count
        return cls(str(path), sha256_file(path), page_count, page_sizes)


def _source_text_lines(page: fitz.Page) -> list[dict[str, Any]]:
    """Return native text anchors in the same display space as the page image."""
    lines: list[dict[str, Any]] = []
    for block in page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = " ".join(str(span.get("text") or "").strip() for span in spans).strip()
            if not text:
                continue
            bbox = fitz.Rect(line["bbox"])
            if page.rotation:
                bbox = bbox * page.rotation_matrix
            dx, dy = line.get("dir") or (1, 0)
            if abs(dx) >= abs(dy):
                local_rotation = 0 if dx >= 0 else 180
            else:
                local_rotation = 90 if dy < 0 else 270
            rotation = (local_rotation - int(page.rotation or 0)) % 360
            lines.append(
                {
                    "line_id": f"p{page.number + 1:03d}-line-{len(lines) + 1:05d}",
                    "text": text,
                    "bbox": [round(float(value), 3) for value in bbox],
                    "rotation": rotation,
                    "provenance": "native_text",
                }
            )
    return lines


def _normalized_words(value: object) -> list[str]:
    return re.findall(r"[0-9a-z]+", str(value or "").casefold())


def validate_decision_ledger_coverage(
    *, source_lines: Iterable[Mapping[str, Any]], ledger: Mapping[str, Any]
) -> dict[str, Any]:
    """Prove that the supervisor's render ledger closes every source line once."""

    lines = [dict(item) for item in source_lines]
    by_id = {str(item.get("line_id") or ""): item for item in lines}
    if not by_id or "" in by_id or len(by_id) != len(lines):
        raise ValueError("source lines require unique stable line_id values")
    literal_ids = {str(value) for value in (ledger.get("literal_only_ids") or [])}
    if not literal_ids.issubset(by_id):
        raise ValueError("literal_only_ids contain unknown source lines")
    claimed: dict[str, str] = {}
    zone_claimed: dict[str, set[str]] = {}
    blocks = ledger.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("decision ledger requires rendered blocks")
    for index, raw in enumerate(blocks):
        if not isinstance(raw, Mapping):
            raise ValueError(f"ledger block {index} must be an object")
        block_id = str(raw.get("block_id") or "").strip()
        member_ids = [str(value) for value in (raw.get("source_ids") or [])]
        if not block_id or not member_ids:
            raise ValueError(f"ledger block {index} requires block_id and source_ids")
        unknown = [value for value in member_ids if value not in by_id]
        if unknown:
            raise ValueError(f"ledger block {block_id} references unknown source lines: {unknown}")
        duplicate = [value for value in member_ids if value in claimed]
        if duplicate:
            raise ValueError(f"source lines are claimed by multiple blocks: {duplicate}")
        block_words = _normalized_words(raw.get("source_text"))
        remaining = list(block_words)
        for member_id in member_ids:
            for word in _normalized_words(by_id[member_id].get("text")):
                if word not in remaining:
                    raise ValueError(f"ledger block {block_id} does not preserve all member text")
                remaining.remove(word)
            claimed[member_id] = block_id
            zone = str(by_id[member_id].get("zone_hint") or raw.get("zone") or "unclassified")
            zone_claimed.setdefault(zone, set()).add(member_id)
        if not re.search(r"[\u3400-\u9fff]", str(raw.get("translation") or "")):
            raise ValueError(f"ledger block {block_id} requires Chinese translation")
        source_word_count = len(re.findall(r"[A-Za-z]+", str(raw.get("source_text") or "")))
        chinese_count = len(re.findall(r"[\u3400-\u9fff]", str(raw.get("translation") or "")))
        minimum_chinese = max(2, math.ceil(source_word_count * 0.35))
        if source_word_count >= 6 and chinese_count < minimum_chinese:
            raise ValueError(
                f"ledger block {block_id} has an implausibly short Chinese translation "
                f"({chinese_count} CJK characters for {source_word_count} source words)"
            )
    covered = set(claimed) | literal_ids
    unbound = sorted(set(by_id) - covered)
    if unbound:
        raise ValueError(f"unbound source lines: {', '.join(unbound)}")
    zone_totals: dict[str, set[str]] = {}
    for line_id, item in by_id.items():
        zone = str(item.get("zone_hint") or "unclassified")
        zone_totals.setdefault(zone, set()).add(line_id)
    zone_closure = {
        zone: len((zone_claimed.get(zone, set()) | literal_ids) & ids) / len(ids)
        for zone, ids in zone_totals.items()
    }
    return {
        "source_line_count": len(by_id),
        "render_bound_count": len(claimed),
        "literal_only_count": len(literal_ids),
        "unbound_source_ids": [],
        "overall_closure_ratio": len(covered) / len(by_id),
        "zone_closure": zone_closure,
    }


class EngineeringDrawingAgent:
    """One page manager plus deterministic executor handoff contract."""

    def __init__(self, *, model: str = DEFAULT_MULTIMODAL_MODEL, knowledge_path: Path | None = None):
        self.model = model
        self.knowledge_path = knowledge_path

    def snapshot(self, source_pdf: Path) -> SourceSnapshot:
        return SourceSnapshot.from_pdf(Path(source_pdf))

    def build_manifest(self, source_pdf: Path, *, reference_pdf: Path | None = None) -> dict[str, Any]:
        snapshot = self.snapshot(source_pdf)
        reference = None
        if reference_pdf is not None:
            reference = {
                "reference_pdf": str(Path(reference_pdf).resolve()),
                "reference_sha256": sha256_file(Path(reference_pdf)),
                "usage": "translation_evidence_only",
                "may_supply_page_pixels": False,
                "may_supply_target_coordinates": False,
            }
        return {
            "schema": AGENT_SCHEMA,
            "agent_name": AGENT_NAME,
            "agent_role": AGENT_ROLE,
            "workflow_version": WORKFLOW_VERSION,
            "model": self.model,
            "supervisor_count": 1,
            "parallel_supervisors_forbidden": True,
            "max_automatic_repairs": MAX_AUTOMATIC_REPAIRS,
            "source_snapshot": asdict(snapshot),
            "render_provenance": {
                "base": "original_source_pdf",
                "source_sha256": snapshot.source_sha256,
                "reference_usage": "translation_evidence_only",
                "copied_reference_page_or_region": False,
            },
            "reference": reference,
            "strict_gates": STRICT_GATES,
            "soft_concerns": SOFT_CONCERNS,
            "ignored_metrics": IGNORED_METRICS,
            "review_questions": list(REVIEW_QUESTIONS),
            "policy": policy_snapshot(),
            "status": "awaiting_multimodal_supervisor_plan",
            "pages": [],
        }

    def build_page_packet(
        self,
        source_pdf: Path,
        page_index: int,
        *,
        manifest: Mapping[str, Any],
        evidence: Iterable[Mapping[str, Any]] = (),
        output_dir: Path,
        dpi: int = 144,
    ) -> dict[str, Any]:
        source_pdf = Path(source_pdf).resolve()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        with fitz.open(source_pdf) as document:
            page = document[page_index]
            image_name = f"page-{page_index + 1:04d}-source.png"
            page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False).save(output_dir / image_name)
            page_type = "engineering_drawing"
            knowledge = supervisor_knowledge_context(page_type=page_type, path=self.knowledge_path) if self.knowledge_path else supervisor_knowledge_context(page_type=page_type)
            packet = {
                "schema": "engineering-drawing-supervisor-page-packet-v1",
                "orchestration_harness": {
                    "schema": HARNESS_SCHEMA,
                    "workflow_stages": list(STAGES),
                    "policy_fingerprint": canonical_policy_fingerprint(),
                    "rule": "Every handoff preserves run_id, source_sha256, workflow_version, policy fingerprint, stable source IDs, zones and render modes. No stage may reinterpret or weaken an upstream decision.",
                },
                "agent_manifest": str((output_dir / ".." / "agent-manifest.json").resolve()),
                "source_pdf": str(source_pdf),
                "source_sha256": manifest["source_snapshot"]["source_sha256"],
                "page_index": page_index,
                "page_size": [float(page.rect.width), float(page.rect.height)],
                "coordinate_space": "display_page_rect",
                "page_rotation": int(page.rotation or 0) % 360,
                "source_image": image_name,
                "source_text_lines": _source_text_lines(page),
                "reference_evidence": [dict(item) for item in evidence],
                "engineering_knowledge": knowledge,
                "supervisor_instructions": {
                    "look_at_rendered_page_first": True,
                    "ocr_is_execution_only": True,
                    "classify_regions_before_ocr": True,
                    "group_before_translation_and_placement": True,
                    "plan_complete_translation_and_layout": True,
                    "exclusive_render_mode": {
                        "required_exactly_one_per_translated_block": ["preserve_source_blue_chinese", "opaque_bilingual_reflow"],
                        "preserve_source_blue_chinese": "Keep source visible, add nearby blue Chinese, and use no mask or redaction.",
                        "opaque_bilingual_reflow": "Completely remove or cover old natural-language glyphs, then render black source plus Chinese; old glyph visibility and partial-mask overlap are hard failures.",
                        "zone_defaults": {"company_contact_panel": "opaque_bilingual_reflow", "drawing_body": "preserve_source_blue_chinese", "state_bearing_metadata": "preserve_source_blue_chinese"},
                        "logo_overlap": "soft_preference_only; avoid when practical, but minor logo overlap alone may release",
                    },
                    "source_line_closure": {
                        "required": True,
                        "rule": "Every source_text_lines.line_id must appear exactly once in a rendered semantic block source_ids or in literal_only_ids.",
                        "paragraph_grouping": "Grouping may reduce rendered block count but may never drop member line IDs or wording.",
                        "sidebar_footer_rule": "Every readable company, role, address, contact, project, service, drawing-title, revision and status line must be bound and translated under its zone rule.",
                        "pass_threshold": 1.0,
                    },
                    "company_panel_typography": {
                        "policy": "fit_to_each_cells_actual_whitespace",
                        "batch_scale": 1.18,
                        "minimum_chinese_font_size": 6.4,
                        "preferred_minimum_chinese_font_size": 6.8,
                        "maximum_chinese_font_size": 12.0,
                        "rule": "Use the largest fitting Chinese size in each company-information cell; do not reuse one small fixed size across panels.",
                    },
                    "directory_typography": {
                        "policy": "largest_readable_fit_per_cell_close_to_table_rules",
                        "batch_scale": 1.20,
                        "preferred_minimum_chinese_font_size": 7.2,
                        "hard_minimum_chinese_font_size": 6.8,
                        "cell_padding_points": [1.5, 3.0],
                        "target_usable_cell_height_ratio": [0.72, 0.90],
                        "rule": "For every natural-language directory cell, retain source plus Chinese, measure the usable cell rectangle, wrap semantically, and use the largest fitting size. Keep the bilingual block visually anchored near its corresponding grid lines without touching or crossing them; never use one batch-wide tiny font.",
                        "mask_rule": "Masks may cover only verified natural-language glyph unions. Intersection with row-number, drawing-number and size columns or table rules must be zero; every source row number must remain visible and unchanged, with at least 1.5pt clearance from protected fields.",
                        "required_mask_audit": ["protected_bboxes", "mask_bboxes", "intersection_area_zero", "row_numbers_source_match"],
                    },
                    "typography_fit_evidence": {
                        "required_for": ["directory_index", "company_contact_panel"],
                        "fields": ["usable_bbox", "chosen_font_size", "largest_fit_font_size", "padding_points", "source_visual_font_size", "local_rotation"],
                        "rule": "The chosen size must equal the largest safe fit within normal rounding tolerance and must satisfy the zone hard minimum; otherwise the plan must use another blank area or bounded reflow rather than shrink below the gate.",
                    },
                    "review_questions": list(REVIEW_QUESTIONS),
                    "max_repairs": MAX_AUTOMATIC_REPAIRS,
                    "bounded_workflow": [
                        {
                            "name": "plan_once",
                            "action": "Visually partition the page, reconcile the deduplicated native/OCR/reference wording inventory, translate, and place all blocks in one coherent plan.",
                        },
                        {
                            "name": "targeted_difference_scan_once",
                            "action": "Scan only for omissions, wrong local rotation, directory bilingual rows, and unclassified sidebar/footer content; amend the existing plan without restarting it.",
                        },
                        {
                            "name": "rendered_candidate_review_once",
                            "action": "Compare source and rendered candidate once at whole-page and targeted crop scale; report page-specific evidence.",
                        },
                    ],
                    "repair_policy": {
                        "maximum_local_repairs": MAX_AUTOMATIC_REPAIRS,
                        "repair_scope": "only_blocks_with_hard_findings",
                        "full_page_replan_for_soft_findings": False,
                        "hard_findings": [
                            "omission",
                            "unbound_source_line",
                            "implausibly_short_translation",
                            "wrong_translation",
                            "wrong_rotation",
                            "wrong_zone_rule",
                            "directory_not_source_plus_chinese",
                            "serious_visual_damage",
                        ],
                        "soft_findings": [
                            "minor_leader_crossing",
                            "minor_density",
                            "non_optimal_spacing",
                        ],
                    },
                },
                "strict_gates": STRICT_GATES,
                "soft_concerns": SOFT_CONCERNS,
                "ignored_metrics": IGNORED_METRICS,
                "plan_status": "awaiting_multimodal_supervisor_plan",
            }
        (output_dir / "page-packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return packet

    @staticmethod
    def validate_single_supervisor_plan(plan: Mapping[str, Any]) -> None:
        if plan.get("agent_name") not in {None, AGENT_NAME}:
            raise ValueError("plan belongs to a different agent")
        if int(plan.get("supervisor_count", 1)) != 1:
            raise ValueError("exactly one multimodal supervisor is required")
        if bool(plan.get("parallel_supervisors")) or bool(plan.get("parallel_agents")):
            raise ValueError("parallel supervisors/agents are forbidden")
        if plan.get("render_provenance", {}).get("base") != "original_source_pdf":
            raise ValueError("original source PDF must be the render base")
        if plan.get("render_provenance", {}).get("copied_reference_page_or_region") is not False:
            raise ValueError("reference pixels cannot be copied")

    @staticmethod
    def validate_execution_binding(manifest: Mapping[str, Any], source_pdf: Path) -> None:
        """Ensure an approved plan is executed against the frozen original PDF."""
        if manifest.get("schema") != AGENT_SCHEMA:
            raise ValueError("agent manifest schema is invalid")
        snapshot = manifest.get("source_snapshot")
        if not isinstance(snapshot, Mapping):
            raise ValueError("agent manifest has no source snapshot")
        actual = SourceSnapshot.from_pdf(Path(source_pdf))
        if str(snapshot.get("source_pdf")) != actual.source_pdf:
            raise ValueError("execution source path does not match the agent manifest")
        if str(snapshot.get("source_sha256")) != actual.source_sha256:
            raise ValueError("execution source SHA-256 does not match the agent manifest")
        if int(snapshot.get("page_count", -1)) != actual.page_count:
            raise ValueError("execution page count does not match the agent manifest")
        render_provenance = manifest.get("render_provenance") or {}
        if render_provenance.get("base") != "original_source_pdf":
            raise ValueError("agent execution must use the original source PDF as base")
        if render_provenance.get("copied_reference_page_or_region") is not False:
            raise ValueError("agent execution cannot copy reference page or region pixels")

    @staticmethod
    def release_decision(review: Mapping[str, Any]) -> dict[str, Any]:
        """Apply only the three human questions and strict gates to a review."""
        findings = review.get("findings") or []
        hard_failure_codes = {
            "omission", "wrong_translation", "fragmented_translation", "unclear_association",
            "blue_paint_overlap", "table_misalignment", "major_geometry_damage", "duplicate_translation",
        }
        blocking = [item for item in findings if str(item.get("code", "")).casefold() in hard_failure_codes]
        return {
            "passed": not blocking and review.get("status") in {"accepted", "pass", True},
            "blocking_findings": blocking,
            "soft_findings": [item for item in findings if item not in blocking],
            "review_questions": list(REVIEW_QUESTIONS),
            "normal_zoom_readability_is_release_gate": True,
        }


__all__ = [
    "AGENT_NAME", "AGENT_ROLE", "AGENT_SCHEMA", "EngineeringDrawingAgent",
    "IGNORED_METRICS", "MAX_AUTOMATIC_REPAIRS", "REVIEW_QUESTIONS", "STRICT_GATES",
    "SOFT_CONCERNS", "SourceSnapshot", "sha256_file",
    "validate_decision_ledger_coverage",
]
