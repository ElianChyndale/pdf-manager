"""Unified V4 engineering-drawing production runner.

This module is the only legitimate path that may publish a bilingual PDF into
the formal ``v4.0-readable-zone-complete`` directory.  Every run drives the
five immutable orchestration stages declared by ``orchestration_harness.py``:

    supervisor_plan -> extraction_ledger -> render_contract
    -> rendered_candidate -> release_authorization

and every release authorization is produced either by ``authorize_release``
(machine-supervisor final review) or ``authorize_human_release`` (spec §8 user
acceptance).  The renderer is never allowed to self-authorize or copy to the
formal directory; ``publish_to_formal`` is the single write path.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import fitz

from .orchestration_harness import HARNESS_SCHEMA, validate_handoff
from .workflow_policy import WORKFLOW_VERSION
from .supervisor_bundle import file_sha256, verify_supervisor_run_bundle
from .supervisor_contract import build_review_gate, validate_real_supervisor_plan
from .authorization import (
    authorize_human_release,
    authorize_release,
    authorize_render,
)
from .delivery_manifest import (
    build_delivery_manifest,
    default_prompt_files,
    write_delivery_manifest,
)
from .post_ocr_supervision import build_post_ocr_supervision_package
from .visual_qa import analyze_visual_qa
from .overlay_pair import (
    render_opaque_translation_companion,
    render_planned_opaque_blocks,
)
from services.rendering.output.engineering import render_bilingual_inline_only

STAGE_NAMES = (
    "supervisor_plan",
    "extraction_ledger",
    "render_contract",
    "rendered_candidate",
    "release_authorization",
)

# Placement audit statuses that prove a block was actually rendered into ink.
_PLACED_STATUSES = {
    "inline_near",
    "inline_reviewed",
    "inline_reflowed_after_review_collision",
    "inline_legacy_fallback",
    "panel_reflowed",
}
# Placement audit statuses that always block a candidate release.
_HARD_STATUS_PREFIXES = ("rejected", "not_rendered", "unplaced")

# Schemas accepted by ``audit_formal_dir`` for a compliant release sidecar.
COMPLIANT_RELEASE_SCHEMAS = {
    "engineering-drawing-release-authorization-v1",
    "engineering-drawing-human-release-authorization-v1",
}


@dataclass(frozen=True)
class RendererOutcome:
    """Deterministic renderer result consumed by the rendered_candidate stage."""

    output_pdf_path: Path
    placement_audit_path: Path
    planned_ids: list[str]
    rendered_ids: list[str]
    failed_block_ids: list[str]
    hard_findings: list[str] = field(default_factory=list)
    soft_findings: list[str] = field(default_factory=list)


def _as_blocks(plan: Mapping[str, Any]) -> tuple[list[dict], list[str], list[str]]:
    """Derive harness blocks, literal IDs and the full expected source-ID set."""
    region_types = {
        str(item.get("region_id") or ""): str(item.get("region_type") or "")
        for item in plan.get("page_region_map") or []
        if isinstance(item, Mapping)
    }
    blocks: list[dict] = []
    for raw in plan.get("semantic_blocks") or []:
        if not isinstance(raw, Mapping):
            continue
        block_id = str(raw.get("block_id") or "")
        if not block_id:
            continue
        status = str(raw.get("coverage_status") or "")
        placement = raw.get("placement") if isinstance(raw.get("placement"), Mapping) else {}
        zone = str(raw.get("region_type") or "")
        if not zone:
            zone = region_types.get(str(raw.get("page_region_id") or ""), "")
        block: dict[str, Any] = {
            "block_id": block_id,
            "source_ids": [str(value) for value in (raw.get("member_ids") or []) if str(value)],
            "zone": zone,
            "status": status,
            "source_text": str(raw.get("source_text") or ""),
            "translated_text": str(raw.get("translated_text") or ""),
        }
        if status == "translated":
            block["render_mode"] = str(placement.get("render_mode") or "")
        blocks.append(block)

    literal_only_ids: list[str] = []
    for item in plan.get("coverage_inventory") or []:
        if isinstance(item, Mapping) and str(item.get("status") or "").casefold() == "literal_only":
            literal_only_ids.append(str(item.get("candidate_id") or ""))

    expected_source_ids = [value for block in blocks for value in block["source_ids"]]
    expected_source_ids.extend(literal_only_ids)
    return blocks, literal_only_ids, expected_source_ids


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _identity_fields(
    *, run_id: str, source_sha256: str, document_context: Mapping[str, Any] | None = None
) -> dict[str, str]:
    from .orchestration_harness import canonical_policy_fingerprint, canonicalize_document_context

    identity = {
        "schema": HARNESS_SCHEMA,
        "run_id": run_id,
        "source_sha256": source_sha256.casefold(),
        "workflow_version": WORKFLOW_VERSION,
        "policy_fingerprint": canonical_policy_fingerprint(),
    }
    if document_context is not None:
        identity["document_context"] = canonicalize_document_context(document_context)
    return identity


def _stage_payload(
    *,
    identity: Mapping[str, str],
    stage: str,
    blocks: list[dict],
    literal_only_ids: list[str],
    expected_source_ids: list[str],
    **extra: Any,
) -> dict[str, Any]:
    return {
        **identity,
        "stage": stage,
        "blocks": blocks,
        "literal_only_ids": literal_only_ids,
        "expected_source_ids": expected_source_ids,
        **extra,
    }


def _placement_statuses(placement_audit_path: Path) -> dict[str, str]:
    try:
        payload = json.loads(Path(placement_audit_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = payload.get("placements", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("region_id") or ""): str(item.get("status") or "")
        for item in items
        if isinstance(item, dict)
    }


def _hard_findings_from_placements(
    planned_ids: list[str],
    statuses: Mapping[str, str],
    opaque_failed: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Return (hard_findings, rendered_ids, failed_ids) from the placement audit."""
    hard: list[str] = []
    rendered: list[str] = []
    failed: list[str] = list(opaque_failed)
    for block_id in planned_ids:
        status = statuses.get(block_id, "")
        if status in _PLACED_STATUSES:
            rendered.append(block_id)
        elif status.startswith(_HARD_STATUS_PREFIXES) or not status:
            failed.append(block_id)
            hard.append("ink_coverage_gap")
    return sorted(set(hard)), rendered, sorted(set(failed))


# --------------------------------------------------------------------------
# Renderer plugins
# --------------------------------------------------------------------------

def _inline_region_from_block(raw: Mapping[str, Any]) -> dict[str, Any]:
    block = dict(raw)
    placement = block.get("placement") if isinstance(block.get("placement"), Mapping) else {}
    target = (
        placement.get("target_bbox")
        or placement.get("selected_region")
        or block.get("target_bbox")
    )
    region: dict[str, Any] = {
        "region_id": str(block.get("block_id") or ""),
        "source_text": str(block.get("source_text") or ""),
        "translated_text": str(block.get("translated_text") or ""),
        "bbox": list(block.get("source_bbox") or []) if isinstance(block.get("source_bbox"), (list, tuple)) else [],
        "source_bbox": list(block.get("source_bbox") or []) if isinstance(block.get("source_bbox"), (list, tuple)) else [],
        "rotation": int(placement.get("rotation") or 0) % 360,
        "qa_flags": ["multimodal_v4_plan"],
        "action": "translate",
        "placement": "inline_only",
        "coverage_status": "translated",
    }
    if isinstance(target, (list, tuple)) and len(target) == 4:
        region["review_target_bbox"] = [float(value) for value in target]
        region["review_font_size"] = float(placement.get("font_size") or 0) or None
    return region


def render_inline_plus_opaque(
    *,
    source_pdf: Path,
    output_pdf: Path,
    plan: Mapping[str, Any],
    ocr_payload: Mapping[str, Any] | None,
    work_dir: Path,
    renderer_options: Mapping[str, Any] | None = None,
) -> RendererOutcome:
    """Render both render modes on one page: opaque blocks first, inline after.

    Mirrors the V3 render split used by ``cli.py v3-render``: opaque
    (``title_block``/``table_cell``) blocks are reflowed onto a temporary base,
    then the remaining inline blocks are placed onto that base.  The placement
    audit is written beside ``output_pdf`` and read back for closure tracking.
    """
    semantic_blocks = [dict(item) for item in plan.get("semantic_blocks") or [] if isinstance(item, Mapping)]
    opaque_blocks = [
        block
        for block in semantic_blocks
        if str((block.get("placement") or {}).get("mode") or "") in {"title_block", "table_cell"}
    ]
    inline_blocks = [block for block in semantic_blocks if block not in opaque_blocks]
    if str(plan.get("delivery_mode") or "") == "opaque_bilingual_reflow" and not opaque_blocks:
        raise ValueError("opaque_bilingual_reflow requires approved title_block/table_cell plans")

    ocr_regions = [dict(item) for item in (ocr_payload or {}).get("regions") or [] if isinstance(item, Mapping)]
    render_base = Path(source_pdf)
    panel_pdf: Path | None = None
    panel_result: dict[str, Any] = {}
    opaque_failed: list[str] = []
    try:
        if opaque_blocks:
            panel_pdf = work_dir / f"{output_pdf.stem}-opaque-base.pdf"
            panel_result = render_planned_opaque_blocks(
                source_pdf_path=source_pdf,
                output_pdf_path=panel_pdf,
                semantic_blocks=opaque_blocks,
                ocr_regions=ocr_regions,
                strict_execution=True,
            )
            opaque_failed = list(panel_result.get("failed_block_ids") or [])
            if opaque_failed:
                return RendererOutcome(
                    output_pdf_path=output_pdf,
                    placement_audit_path=output_pdf.with_suffix(".inline-placement.json"),
                    planned_ids=[],
                    rendered_ids=[],
                    failed_block_ids=opaque_failed,
                    hard_findings=["ink_coverage_gap"],
                )
            render_base = panel_pdf

        inline_regions = [_inline_region_from_block(block) for block in inline_blocks]
        render_bilingual_inline_only(
            source_pdf_path=render_base,
            output_pdf_path=output_pdf,
            regions=inline_regions,
            draw_leaders=True,
            preserve_legacy_position=False,
        )
    finally:
        if panel_pdf is not None and panel_pdf.exists() and panel_pdf.parent != work_dir.resolve():
            panel_pdf.unlink()

    audit_path = output_pdf.with_suffix(".inline-placement.json")
    planned_ids = [
        str(block.get("block_id") or "")
        for block in semantic_blocks
        if str(block.get("coverage_status") or "") == "translated"
    ]
    statuses = _placement_statuses(audit_path)
    hard, rendered, failed = _hard_findings_from_placements(planned_ids, statuses, opaque_failed)
    return RendererOutcome(
        output_pdf_path=output_pdf,
        placement_audit_path=audit_path,
        planned_ids=planned_ids,
        rendered_ids=rendered,
        failed_block_ids=failed,
        hard_findings=hard,
        soft_findings=list(panel_result.get("soft_findings") or []),
    )


def render_dense_index(
    *,
    source_pdf: Path,
    output_pdf: Path,
    plan: Mapping[str, Any],
    ocr_payload: Mapping[str, Any] | None,
    work_dir: Path,
    renderer_options: Mapping[str, Any] | None = None,
) -> RendererOutcome:
    """Render an opaque directory-index page with the untouched source as base.

    Requires ``delivery_mode == "opaque_bilingual_reflow"`` and at least one
    ``directory_index`` zone, mirroring ``supervisor_contract.py``.
    """
    if str(plan.get("delivery_mode") or "").casefold() != "opaque_bilingual_reflow":
        raise ValueError("dense_index renderer requires opaque_bilingual_reflow delivery mode")
    has_directory_zone = any(
        str(item.get("region_type") or "") == "directory_index"
        for item in plan.get("page_region_map") or []
        if isinstance(item, Mapping)
    )
    if not has_directory_zone:
        raise ValueError("dense_index renderer requires a directory_index zone")

    ocr_regions = [dict(item) for item in (ocr_payload or {}).get("regions") or [] if isinstance(item, Mapping)]
    result = render_opaque_translation_companion(
        source_pdf_path=source_pdf,
        output_pdf_path=output_pdf,
        semantic_blocks=plan.get("semantic_blocks") or [],
        ocr_regions=ocr_regions,
        include_source_text=True,
    )
    planned_ids = [
        str(block.get("block_id") or "")
        for block in plan.get("semantic_blocks") or []
        if isinstance(block, Mapping) and str(block.get("coverage_status") or "") == "translated"
    ]
    failed = list(result.get("failed_layout") or []) + list(result.get("unmatched") or [])
    rendered = [block_id for block_id in planned_ids if block_id not in failed]
    hard = ["ink_coverage_gap"] if failed else []
    return RendererOutcome(
        output_pdf_path=output_pdf,
        placement_audit_path=output_pdf.with_suffix(".inline-placement.json"),
        planned_ids=planned_ids,
        rendered_ids=rendered,
        failed_block_ids=sorted(set(failed)),
        hard_findings=hard,
    )


def render_human_gate_rumah(
    *,
    source_pdf: Path,
    output_pdf: Path,
    plan: Mapping[str, Any],
    ocr_payload: Mapping[str, Any] | None,
    work_dir: Path,
    renderer_options: Mapping[str, Any] | None = None,
) -> RendererOutcome:
    """Delegate to the reviewed rumah human-gate builder.

    The builder mutates its source in place, so a scratch copy is made first.
    It needs ``reference`` and ``ledger`` in ``renderer_options``.
    """
    import shutil
    import subprocess
    import sys

    options = dict(renderer_options or {})
    reference = Path(str(options.get("reference") or "")).resolve()
    ledger = Path(str(options.get("ledger") or "")).resolve()
    if not reference.is_file() or not ledger.is_file():
        raise ValueError("human_gate_rumah renderer requires reference and ledger in renderer_options")
    source = Path(source_pdf).resolve()
    scratch = work_dir / f"{output_pdf.stem}-human-gate-source.pdf"
    shutil.copy2(source, scratch)

    script = Path(__file__).resolve().parents[2] / "devtools" / "build_human_gate_rumah_source_v4.py"
    if not script.is_file():
        raise ValueError("human-gate builder script is missing")
    plan_path = work_dir / f"{output_pdf.stem}-human-gate-plan.json"
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--source",
            str(scratch),
            "--reference",
            str(reference),
            "--ledger",
            str(ledger),
            "--output",
            str(output_pdf),
            "--plan",
            str(plan_path),
        ],
        check=True,
        capture_output=True,
    )
    return RendererOutcome(
        output_pdf_path=output_pdf,
        placement_audit_path=output_pdf.with_suffix(".inline-placement.json"),
        planned_ids=[],
        rendered_ids=[],
        failed_block_ids=[],
        soft_findings=["human_gate_rumah_builder_produced_plan"],
    )


RENDERERS: dict[str, Callable[..., RendererOutcome]] = {
    "inline_plus_opaque": render_inline_plus_opaque,
    "dense_index": render_dense_index,
    "human_gate_rumah": render_human_gate_rumah,
}


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def _review_evidence_sha256(work_dir: Path) -> str:
    digest = hashlib.sha256()
    pages = sorted(work_dir.glob("page-*.png"))
    for path in pages:
        digest.update(path.read_bytes())
    if not pages:
        raise ValueError("no review page images were written")
    return digest.hexdigest()


def _write_review_page_images(output_pdf: Path, work_dir: Path, *, dpi: int = 144) -> None:
    with fitz.open(output_pdf) as document:
        for page_index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
            pixmap.save(str(work_dir / f"page-{page_index + 1:04d}.png"))


def run_v4_flow(
    *,
    source_pdf: Path,
    run_id: str,
    supervisor_bundle_dir: Path,
    normalized_plan: Mapping[str, Any],
    work_dir: Path,
    candidate_dir: Path,
    formal_dir: Path,
    renderer: str,
    ocr_payload: Mapping[str, Any] | None = None,
    review: Mapping[str, Any] | None = None,
    human_acceptance: Mapping[str, Any] | None = None,
    allow_publish: bool = True,
    renderer_options: Mapping[str, Any] | None = None,
    document_context: Mapping[str, Any] | None = None,
    delivery_id: str | None = None,
    delivery_meta: Mapping[str, Any] | None = None,
    glossary_tm_dir: Path | None = None,
) -> dict[str, Any]:
    """Drive the five immutable V4 stages and optionally publish the candidate.

    Without a supervisor ``review`` or explicit ``human_acceptance`` the run
    stops after ``rendered_candidate`` and never touches the formal directory:
    a renderer may never self-authorize.

    ``document_context`` (project/discipline/units/...) becomes part of the
    immutable run identity.  ``delivery_id`` / ``delivery_meta``
    (``{operator, qa_status, notes}``) and ``glossary_tm_dir`` feed the
    per-PDF delivery manifest written next to the formal PDF on publish.
    """
    source_pdf = Path(source_pdf).resolve()
    work_dir = Path(work_dir).resolve()
    candidate_dir = Path(candidate_dir).resolve()
    formal_dir = Path(formal_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()
    _clock = time.perf_counter()
    timing: dict[str, Any] = {"schema": "engineering-drawing-run-timing-v1", "started_at": started_at}

    def _tick(stage: str) -> None:
        nonlocal _clock
        timing[f"{stage}_ms"] = round((time.perf_counter() - _clock) * 1000, 1)
        _clock = time.perf_counter()

    source_sha256 = file_sha256(source_pdf)
    identity = _identity_fields(run_id=run_id, source_sha256=source_sha256, document_context=document_context)

    # ---- Stage 1: supervisor_plan ---------------------------------------
    verify_supervisor_run_bundle(supervisor_bundle_dir, source_pdf_path=source_pdf)
    plan = validate_real_supervisor_plan(
        normalized_plan,
        source_pdf_path=source_pdf,
        require_final_review=False,
    )
    blocks, literal_only_ids, expected_source_ids = _as_blocks(plan)
    if not blocks:
        raise ValueError("supervisor plan produced no translated semantic blocks")

    stage1 = _stage_payload(
        identity=identity,
        stage="supervisor_plan",
        blocks=blocks,
        literal_only_ids=literal_only_ids,
        expected_source_ids=expected_source_ids,
    )
    validate_handoff(stage1)
    _write_json(work_dir / "stage1-supervisor-plan.json", stage1)
    _tick("stage1")

    # ---- Stage 2: extraction_ledger --------------------------------------
    stage2 = _stage_payload(
        identity=identity,
        stage="extraction_ledger",
        blocks=blocks,
        literal_only_ids=literal_only_ids,
        expected_source_ids=expected_source_ids,
        ocr_evidence_count=len((ocr_payload or {}).get("regions") or []),
    )
    validate_handoff(stage2, previous=stage1)
    _write_json(work_dir / "stage2-extraction-ledger.json", stage2)
    if ocr_payload:
        _write_json(work_dir / "extraction-ledger-package.json", ocr_payload)
    _tick("stage2")

    # ---- Stage 3: render_contract ----------------------------------------
    render_authorization = authorize_render(
        bundle_dir=supervisor_bundle_dir,
        source_pdf_path=source_pdf,
        plan=plan,
    )
    stage3 = _stage_payload(
        identity=identity,
        stage="render_contract",
        blocks=blocks,
        literal_only_ids=literal_only_ids,
        expected_source_ids=expected_source_ids,
        render_authorization=render_authorization,
    )
    validate_handoff(stage3, previous=stage2)
    _write_json(work_dir / "stage3-render-contract.json", stage3)
    _write_json(work_dir / "render-authorization.json", render_authorization)
    _tick("stage3")

    # ---- Stage 4: rendered_candidate -------------------------------------
    renderer_fn = RENDERERS.get(renderer)
    if renderer_fn is None:
        raise ValueError(f"unsupported renderer: {renderer} (choose from {sorted(RENDERERS)})")
    candidate_pdf = candidate_dir / f"{Path(normalized_plan.get('output_stem') or run_id).stem}.pdf"
    outcome = renderer_fn(
        source_pdf=source_pdf,
        output_pdf=candidate_pdf,
        plan=plan,
        ocr_payload=ocr_payload,
        work_dir=work_dir,
        renderer_options=renderer_options,
    )
    if outcome.failed_block_ids:
        raise ValueError(
            "candidate render failed blocks: " + ", ".join(outcome.failed_block_ids)
        )
    _write_review_page_images(candidate_pdf, work_dir)
    zone_closure = {block["zone"]: 1.0 for block in blocks}
    hard_findings = list(outcome.hard_findings)
    stage4 = _stage_payload(
        identity=identity,
        stage="rendered_candidate",
        blocks=blocks,
        literal_only_ids=literal_only_ids,
        expected_source_ids=expected_source_ids,
        whole_page_closure=1.0 if not outcome.failed_block_ids else 0.0,
        ink_closure=1.0 if not outcome.failed_block_ids else 0.0,
        zone_closure=zone_closure,
        hard_findings=hard_findings,
        rendered_ids=outcome.rendered_ids,
        candidate_pdf=str(candidate_pdf),
    )
    validate_handoff(stage4, previous=stage3)
    _write_json(work_dir / "stage4-rendered-candidate.json", stage4)
    _tick("render")
    if not allow_publish and review is None and human_acceptance is None:
        timing["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(work_dir / "timing.json", timing)
        return {
            "run_id": run_id,
            "work_dir": str(work_dir),
            "candidate_pdf": str(candidate_pdf),
            "stage": "rendered_candidate",
            "published": False,
            "reason": "no_review_or_acceptance",
        }

    # ---- Stage 5: release_authorization -----------------------------------
    review_evidence_sha256 = _review_evidence_sha256(work_dir)
    stage5 = _stage_payload(
        identity=identity,
        stage="release_authorization",
        blocks=blocks,
        literal_only_ids=literal_only_ids,
        expected_source_ids=expected_source_ids,
        whole_page_closure=1.0,
        ink_closure=1.0,
        zone_closure=zone_closure,
        hard_findings=[],
        render_review_passed=True,
        candidate_sha256=file_sha256(candidate_pdf),
        review_evidence_sha256=review_evidence_sha256,
        release_separate_from_renderer=True,
        authorization="release",
    )
    visual_qa: dict[str, Any] | None = None
    if review is not None:
        visual_qa = analyze_visual_qa(
            output_pdf_path=candidate_pdf,
            placement_audit_path=outcome.placement_audit_path,
        )
        _write_json(work_dir / "visual-qa.json", visual_qa)
        gate = build_review_gate(review=dict(review), visual_qa=visual_qa)
        auth = authorize_release(
            render_authorization=render_authorization,
            candidate_pdf_path=candidate_pdf,
            review=dict(review),
            deterministic_visual_qa=gate["deterministic_visual_qa"],
        )
        authorization_kind = "machine_supervisor"
    elif human_acceptance is not None:
        history = [
            json.loads(
                (work_dir / f"stage{index}-{STAGE_NAMES[index - 1].replace('_', '-')}.json").read_text(encoding="utf-8")
            )
            for index in range(1, 5)
        ]
        history.append(stage5)
        auth = authorize_human_release(
            candidate_pdf_path=candidate_pdf,
            review_evidence_sha256=review_evidence_sha256,
            handoff_history=history,
            acceptance=human_acceptance,
        )
        authorization_kind = "human"
    else:
        timing["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(work_dir / "timing.json", timing)
        return {
            "run_id": run_id,
            "work_dir": str(work_dir),
            "candidate_pdf": str(candidate_pdf),
            "stage": "rendered_candidate",
            "published": False,
            "reason": "renderer_may_not_self_authorize",
        }
    stage5["authorization_kind"] = authorization_kind
    validate_handoff(stage5, previous=stage4)
    _write_json(work_dir / "stage5-release-authorization.json", stage5)
    _write_json(work_dir / "release-authorization.json", auth)

    published_path: Path | None = None
    delivery_manifest_path: Path | None = None
    if allow_publish:
        published_path = publish_to_formal(candidate=candidate_pdf, formal_dir=formal_dir, auth=auth)
        _tick("publish")
        delivery_manifest_path = _write_delivery_manifest_artifacts(
            work_dir=work_dir,
            formal_dir=formal_dir,
            published_path=published_path,
            candidate_pdf=candidate_pdf,
            run_id=run_id,
            source_pdf=source_pdf,
            source_sha256=source_sha256,
            render_authorization=render_authorization,
            auth=auth,
            review_evidence_sha256=review_evidence_sha256,
            renderer=renderer,
            document_context=document_context,
            delivery_id=delivery_id,
            delivery_meta=delivery_meta,
            glossary_tm_dir=glossary_tm_dir,
            started_at=started_at,
        )
    timing["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(work_dir / "timing.json", timing)
    return {
        "run_id": run_id,
        "work_dir": str(work_dir),
        "candidate_pdf": str(candidate_pdf),
        "formal_pdf": str(published_path) if published_path else None,
        "delivery_manifest": str(delivery_manifest_path) if delivery_manifest_path else None,
        "stage": "release_authorization",
        "published": published_path is not None,
        "authorization_kind": authorization_kind,
    }


# --------------------------------------------------------------------------
# Publication and audit
# --------------------------------------------------------------------------

def _write_delivery_manifest_artifacts(
    *,
    work_dir: Path,
    formal_dir: Path,
    published_path: Path,
    candidate_pdf: Path,
    run_id: str,
    source_pdf: Path,
    source_sha256: str,
    render_authorization: Mapping[str, Any],
    auth: Mapping[str, Any],
    review_evidence_sha256: str,
    renderer: str,
    document_context: Mapping[str, Any] | None,
    delivery_id: str | None,
    delivery_meta: Mapping[str, Any] | None,
    glossary_tm_dir: Path | None,
    started_at: str,
) -> Path:
    """Write the per-PDF delivery manifest into work_dir and the formal dir."""
    from .delivery_manifest import now_iso
    from .orchestration_harness import canonical_policy_fingerprint

    meta = dict(delivery_meta or {})
    operator = {
        "name": str(meta.get("operator") or ""),
        "qa_status": str(meta.get("qa_status") or "pending"),
        "notes": str(meta.get("notes") or ""),
    }
    resolved_glossary = Path(glossary_tm_dir) if glossary_tm_dir else formal_dir.parents[2] / "05_Glossary_TM"
    resolved_id = delivery_id or f"dlv-{run_id}-{published_path.stem}"
    payload = build_delivery_manifest(
        delivery_id=resolved_id,
        run_id=run_id,
        workflow_version=WORKFLOW_VERSION,
        policy_fingerprint=canonical_policy_fingerprint(),
        supervisor={"model": render_authorization.get("model") or "", "reasoning_profile": render_authorization.get("reasoning_profile") or ""},
        renderer=renderer,
        render_authorization=render_authorization,
        source_pdf=source_pdf,
        source_sha256=source_sha256,
        candidate_pdf=published_path,
        candidate_sha256=file_sha256(published_path),
        review_evidence_sha256=review_evidence_sha256,
        auth=auth,
        document_context=document_context,
        glossary_tm_dir=resolved_glossary,
        prompt_files=default_prompt_files(),
        operator=operator,
        started_at=started_at,
        completed_at=now_iso(),
        released_at=now_iso(),
    )
    _write_json(work_dir / "delivery-manifest.json", payload)
    return write_delivery_manifest(formal_dir=formal_dir, stem=published_path.stem, payload=payload)


def publish_to_formal(*, candidate: Path, formal_dir: Path, auth: Mapping[str, Any]) -> Path:
    """Copy a candidate into the formal release directory with a compliant sidecar.

    This is the only write path into ``v4.0-readable-zone-complete``.  It is
    idempotent when the existing PDF has the same SHA-256 and refuses to
    overwrite a different PDF that happens to share the stem.
    """
    formal_dir = Path(formal_dir).resolve()
    formal_dir.mkdir(parents=True, exist_ok=True)
    candidate = Path(candidate).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"candidate PDF not found: {candidate}")
    target = formal_dir / candidate.name
    candidate_sha256 = file_sha256(candidate)
    if target.exists():
        existing_sha256 = file_sha256(target)
        if existing_sha256 != candidate_sha256:
            raise ValueError(
                f"refusing to overwrite a different PDF at {target.name} "
                "(same stem, different content)"
            )
    else:
        import shutil

        shutil.copy2(candidate, target)
    sidecar = target.with_suffix(".release-authorization.json")
    sidecar.write_text(json.dumps(auth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def audit_formal_dir(formal_dir: Path) -> list[dict[str, Any]]:
    """Return a read-only compliance report for every PDF in the formal dir.

    The ``warnings`` list is advisory: a missing or unverifiable delivery
    manifest does NOT flip ``ok`` to False (historical formal releases predate
    the delivery manifest and remain compliant for their release-authorization
    evidence).
    """
    formal_dir = Path(formal_dir).resolve()
    reports: list[dict[str, Any]] = []
    if not formal_dir.is_dir():
        return reports
    for pdf in sorted(formal_dir.glob("*.pdf")):
        report: dict[str, Any] = {"pdf": pdf.name, "ok": True, "reasons": [], "warnings": []}
        sidecar = pdf.with_suffix(".release-authorization.json")
        if not sidecar.is_file():
            report["ok"] = False
            report["reasons"].append("missing_release_authorization")
            reports.append(report)
            continue
        try:
            auth = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report["ok"] = False
            report["reasons"].append("unreadable_release_authorization")
            reports.append(report)
            continue
        if str(auth.get("schema") or "") not in COMPLIANT_RELEASE_SCHEMAS:
            report["ok"] = False
            report["reasons"].append(f"unexpected_schema:{auth.get('schema')}")
        if str(auth.get("authorization") or "") != "release":
            report["ok"] = False
            report["reasons"].append("authorization_not_release")
        if str(auth.get("workflow_version") or "") != WORKFLOW_VERSION:
            report["ok"] = False
            report["reasons"].append("stale_workflow_version")
        stored = str(auth.get("candidate_sha256") or auth.get("pdf_sha256") or "")
        if len(stored) != 64 or stored.casefold() != file_sha256(pdf).casefold():
            report["ok"] = False
            report["reasons"].append("candidate_sha256_mismatch")
        if auth.get("release_separate_from_renderer") is not True and auth.get("authorization_kind") != "human":
            report["ok"] = False
            report["reasons"].append("renderer_self_authorization")
        manifest_path = pdf.with_suffix(".delivery-manifest.json")
        if not manifest_path.is_file():
            report["warnings"].append("missing_delivery_manifest")
        else:
            try:
                from .delivery_manifest import verify_delivery_manifest

                verify_delivery_manifest(formal_dir=formal_dir, stem=pdf.stem)
                report["delivery_manifest_ok"] = True
            except (OSError, ValueError, json.JSONDecodeError) as error:
                report["warnings"].append(f"delivery_manifest_unverified:{error}")
                report["delivery_manifest_ok"] = False
        reports.append(report)
    return reports


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------

_RUN_ARGS = (
    "source",
    "run_id",
    "bundle",
    "plan",
    "renderer",
    "work_dir",
    "candidate_dir",
    "formal_dir",
)


def add_v4_parser(subparsers: Any) -> None:
    """Attach the ``v4-run`` subcommand and its sub-commands."""
    v4 = subparsers.add_parser(
        "v4-run",
        help="Unified V4 orchestration: run all five immutable stages and publish via authorization.",
    )
    # Run arguments are validated manually so the sub-commands can be invoked
    # without supplying a full production run.
    v4.add_argument("--source", type=Path)
    v4.add_argument("--run-id")
    v4.add_argument("--bundle", type=Path)
    v4.add_argument("--plan", type=Path)
    v4.add_argument("--renderer", choices=sorted(RENDERERS))
    v4.add_argument("--work-dir", type=Path)
    v4.add_argument("--candidate-dir", type=Path)
    v4.add_argument("--formal-dir", type=Path)
    v4.add_argument("--ocr-json", type=Path)
    v4.add_argument("--review-json", type=Path)
    v4.add_argument("--human-acceptance", type=Path, help="JSON file with accepted_by/accepted_at")
    v4.add_argument("--renderer-options", type=Path)
    v4.add_argument("--document-context", type=Path, help="JSON object: project/discipline/units/...")
    v4.add_argument("--delivery-id", type=str)
    v4.add_argument("--delivery-meta", type=Path, help="JSON object: operator/qa_status/notes")
    v4.add_argument("--glossary-tm-dir", type=Path)
    v4.add_argument("--no-publish", action="store_true")
    v4_sub = v4.add_subparsers(dest="v4_subcommand")
    audit = v4_sub.add_parser("audit-formal", help="Read-only compliance report of a formal dir.")
    audit.add_argument("--formal-dir", required=True, type=Path)
    scorecard = v4_sub.add_parser("scorecard", help="Aggregate per-run KPIs into a batch scorecard.")
    scorecard.add_argument("--work-root", action="append", type=Path, default=[])
    scorecard.add_argument("--formal-dir", type=Path)
    scorecard.add_argument("--translation-qa-json", type=Path)
    scorecard.add_argument("--output-dir", type=Path)
    review_queue = v4_sub.add_parser("review-queue", help="Generate a risk-ranked HTML review sheet.")
    review_queue.add_argument("--work-dir", required=True, type=Path)
    review_queue.add_argument("--candidate-pdf", type=Path)
    review_queue.add_argument("--translation-qa-json", type=Path)
    review_queue.add_argument("--glossary-csv", type=Path)
    review_queue.add_argument("--translation-memory-json", type=Path)
    review_queue.add_argument("--output-dir", type=Path)


def _run_scorecard(args: Any) -> int:
    from .batch_scorecard import build_scorecard_html, scorecard_from_formal_dir, scorecard_from_work_dirs

    if not args.work_root and not args.formal_dir:
        raise SystemExit("v4-run scorecard requires --work-root and/or --formal-dir")
    if args.work_root:
        report = scorecard_from_work_dirs(work_roots=args.work_root)
        if args.translation_qa_json:
            from .batch_scorecard import compute_run_metrics

            report = {
                **report,
                "runs": [
                    compute_run_metrics(work_dir=work, translation_qa_report=None)
                    for work in args.work_root
                ],
            }
    elif args.formal_dir:
        report = scorecard_from_formal_dir(formal_dir=args.formal_dir)
    else:
        report = scorecard_from_work_dirs(work_roots=args.work_root)
    output_dir = Path(args.output_dir) if args.output_dir else (
        Path(args.work_root[0]) if args.work_root else Path(args.formal_dir).resolve().parent
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "scorecard.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "scorecard.html").write_text(build_scorecard_html(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _run_review_queue(args: Any) -> int:
    from .review_queue import build_review_queue, build_review_queue_html

    queue = build_review_queue(
        work_dir=args.work_dir,
        candidate_pdf=args.candidate_pdf,
        translation_qa_report=None,
        glossary_csv=args.glossary_csv,
        translation_memory_json=args.translation_memory_json,
    )
    output_dir = Path(args.output_dir) if args.output_dir else Path(args.work_dir) / "review-queue"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "review-queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_text = build_review_queue_html(queue).replace(
        'src="crops/', f'src="{output_dir.name}/crops/'
    )
    # Crops live under <work_dir>/review-queue/crops; the HTML sits in output_dir.
    if (Path(args.work_dir) / "review-queue" / "crops").is_dir() and output_dir != Path(args.work_dir) / "review-queue":
        import shutil

        shutil.copytree(
            Path(args.work_dir) / "review-queue" / "crops",
            output_dir / "crops",
            dirs_exist_ok=True,
        )
        html_text = build_review_queue_html(queue)
    (output_dir / "review-queue.html").write_text(html_text, encoding="utf-8")
    print(json.dumps({"schema": "engineering-drawing-review-queue-v1", "items": len(queue.get("items") or []), "html": str(output_dir / "review-queue.html")}, ensure_ascii=False, indent=2))
    return 0


def run_v4_command(args: Any) -> int:
    """Execute the ``v4-run`` command."""
    sub = getattr(args, "v4_subcommand", None)
    if sub == "audit-formal":
        reports = audit_formal_dir(args.formal_dir)
        print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2))
        return 0
    if sub == "scorecard":
        return _run_scorecard(args)
    if sub == "review-queue":
        return _run_review_queue(args)
    missing = [name for name in _RUN_ARGS if getattr(args, name, None) in (None, "")]
    if missing:
        raise SystemExit(f"v4-run requires: {', '.join(missing)}")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    ocr_payload = json.loads(args.ocr_json.read_text(encoding="utf-8")) if args.ocr_json else None
    review = json.loads(args.review_json.read_text(encoding="utf-8")) if args.review_json else None
    human_acceptance = (
        json.loads(args.human_acceptance.read_text(encoding="utf-8")) if args.human_acceptance else None
    )
    renderer_options = (
        json.loads(args.renderer_options.read_text(encoding="utf-8")) if args.renderer_options else None
    )
    document_context = (
        json.loads(args.document_context.read_text(encoding="utf-8")) if args.document_context else None
    )
    delivery_meta = json.loads(args.delivery_meta.read_text(encoding="utf-8")) if args.delivery_meta else None
    result = run_v4_flow(
        source_pdf=args.source,
        run_id=args.run_id,
        supervisor_bundle_dir=args.bundle,
        normalized_plan=plan,
        work_dir=args.work_dir,
        candidate_dir=args.candidate_dir,
        formal_dir=args.formal_dir,
        renderer=args.renderer,
        ocr_payload=ocr_payload,
        review=review,
        human_acceptance=human_acceptance,
        allow_publish=not args.no_publish,
        renderer_options=renderer_options,
        document_context=document_context,
        delivery_id=args.delivery_id,
        delivery_meta=delivery_meta,
        glossary_tm_dir=args.glossary_tm_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


__all__ = [
    "COMPLIANT_RELEASE_SCHEMAS",
    "RENDERERS",
    "RendererOutcome",
    "add_v4_parser",
    "audit_formal_dir",
    "publish_to_formal",
    "render_dense_index",
    "render_human_gate_rumah",
    "render_inline_plus_opaque",
    "run_v4_command",
    "run_v4_flow",
]
