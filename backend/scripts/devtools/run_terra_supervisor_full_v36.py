# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
"""Single-supervisor V3.6 source-first production orchestrator.

It consumes the frozen agent-batch index, emits one strict plan per source PDF
covering every page, creates official handoff files, runs crop-only OCR, and
only renders PDFs whose reference-evidence associations leave no manual-review
translation gaps. Reference geometry is used transiently for textual evidence
association and is never emitted as a target coordinate or rendered pixel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend" / "scripts"))

from services.engineering_drawing.multimodal_plan import validate_multimodal_plan
from services.engineering_drawing.supervisor_contract import (
    build_review_gate,
    validate_real_supervisor_plan,
)
from services.engineering_drawing.visual_qa import analyze_visual_qa
from services.engineering_drawing.workflow_policy import WORKFLOW_VERSION


OUTPUT_ROOT = REPO / "output" / "pdf" / "engineering-drawing" / "01_Bilingual_Inline"
ARTIFACT_ROOT = OUTPUT_ROOT / "agent-artifacts" / "terra-supervisor-full-v36"
RELEASE_ROOT = OUTPUT_ROOT / "translated" / "v3.7_verified_supervisor"
INDEX_PATH = OUTPUT_ROOT / "agent-artifacts" / "agent-batch-index.json"
BLUE = [0.05, 0.16, 0.45]
BLACK = [0.0, 0.0, 0.0]
REFERENCE_CACHE: dict[tuple[str, int], tuple[dict[str, list[float]], list[tuple[str, fitz.Rect]]]] = {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def natural(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or "")) and len(text.strip()) >= 3


def normal(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").casefold())


def ref_lines(reference: Path, page_index: int) -> tuple[dict[str, list[float]], list[tuple[str, fitz.Rect]]]:
    key = (str(reference.resolve()), page_index)
    cached = REFERENCE_CACHE.get(key)
    if cached is not None:
        return cached
    source_like: dict[str, list[float]] = {}
    chinese: list[tuple[str, fitz.Rect]] = []
    with fitz.open(reference) as document:
        if page_index >= document.page_count:
            REFERENCE_CACHE[key] = (source_like, chinese)
            return source_like, chinese
        page = document[page_index]
        for raw in page.get_text("dict").get("blocks", []):
            if raw.get("type") != 0:
                continue
            for line in raw.get("lines", []):
                text = " ".join(str(span.get("text") or "").strip() for span in line.get("spans", [])).strip()
                if not text:
                    continue
                bbox = fitz.Rect(line["bbox"])
                if page.rotation:
                    bbox = bbox * page.rotation_matrix
                if re.search(r"[\u3400-\u9fff]", text):
                    chinese.append((text, bbox))
                elif natural(text):
                    source_like.setdefault(normal(text), [bbox.x0, bbox.y0, bbox.x1, bbox.y1])
    REFERENCE_CACHE[key] = (source_like, chinese)
    return source_like, chinese


def ref_translation(source_text: str, source_bbox: list[float], reference: Path | None, page_index: int) -> tuple[str, str]:
    """Return evidence text only; never return reference coordinates."""
    if reference is None or not reference.exists():
        return "", "no_matching_reference_pdf"
    reference_sources, chinese = ref_lines(reference, page_index)
    match = reference_sources.get(normal(source_text))
    if match is None or not chinese:
        return "", "reference_source_text_not_matched"
    sx = (match[0] + match[2]) / 2
    sy = (match[1] + match[3]) / 2
    ranked = sorted(chinese, key=lambda item: ((item[1].x0 + item[1].x1) / 2 - sx) ** 2 + ((item[1].y0 + item[1].y1) / 2 - sy) ** 2)
    candidate, bbox = ranked[0]
    distance = ((bbox.x0 + bbox.x1) / 2 - sx) ** 2 + ((bbox.y0 + bbox.y1) / 2 - sy) ** 2
    if distance > 260.0 ** 2:
        return "", "reference_chinese_evidence_too_distant"
    return candidate, "reference_text_evidence_only"


def classify(lines: list[dict[str, Any]], source_name: str) -> tuple[str, str, str]:
    text = " ".join(str(item.get("text") or "") for item in lines).casefold()
    if "list of" in text and "drawing" in text or "list of drawing" in source_name.casefold():
        return "dense_drawing_index", "opaque_bilingual_reflow", "directory_index"
    return "engineering_drawing", "inline_bilingual", "drawing_body"


def target_for(box: list[float], page_size: list[float], region_type: str) -> list[float]:
    if region_type == "directory_index":
        return box
    height = max(10.0, min(22.0, (box[3] - box[1]) * 1.4))
    y0 = min(page_size[1] - height, box[3] + 2.0)
    return [box[0], max(0.0, y0), min(page_size[0], max(box[0] + 36.0, box[2])), min(page_size[1], y0 + height)]


def inside_page(box: list[float], page_size: list[float]) -> list[float]:
    """Clamp packet anchors after native-to-display rotation conversion."""
    x0 = min(max(0.0, box[0]), page_size[0] - 0.1)
    y0 = min(max(0.0, box[1]), page_size[1] - 0.1)
    x1 = min(max(x0 + 0.1, box[2]), page_size[0])
    y1 = min(max(y0 + 0.1, box[3]), page_size[1])
    return [x0, y0, x1, y1]


def make_plan(record: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    raise RuntimeError(
        "synthetic supervisor planning is disabled; provide a plan written by "
        "the single multimodal supervisor"
    )


def _legacy_make_plan_disabled(record: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    """Retained below only as historical code; never called by production."""
    source = Path(record["source_pdf"])
    reference = Path(record["reference_pdf"]) if record.get("reference_pdf") else None
    manifest = json.loads((Path(record["artifact_dir"]) / "agent-manifest.json").read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = []
    regions: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    manual = translated = 0
    for page in manifest["pages"]:
        page_index = int(page["page_index"])
        packet = json.loads(Path(page["packet"]).read_text(encoding="utf-8"))
        page_size = [float(value) for value in packet["page_size"]]
        lines = [line for line in packet.get("source_text_lines", []) if natural(str(line.get("text") or ""))]
        page_type, delivery, region_type = classify(lines, source.name)
        region_id = f"p{page_index + 1:04d}-primary"
        strategy = "black_chinese_replacement" if region_type == "directory_index" else "blue_preserve_source"
        regions.append({"region_id": region_id, "region_type": region_type, "page_index": page_index, "bbox": [0.0, 0.0, *page_size], "strategy": strategy, "decision_source": "multimodal_visual_plan"})
        # Two explicit crops cover the visual page. They are supervisor tasks,
        # not executor fallback scans, and every task is page-bound.
        for half, crop in (("upper", [0.0, 0.0, 1.0, 0.52]), ("lower", [0.0, 0.48, 1.0, 1.0])):
            tasks.append({"id": f"p{page_index + 1:04d}-{half}", "page_index": page_index, "region_norm": crop, "engine": "technical_cad_ocr", "rotation": int(packet.get("page_rotation", 0)), "language_scope": ["ms", "en", "technical_codes"], "priority": "required", "purpose": "supervisor-declared source anchor and glyph-mask extraction", "expected_output": "text, display-space boxes, confidence and glyph-alpha masks only"})
        for line_index, line in enumerate(lines, start=1):
            source_text = str(line["text"]).strip()
            bbox = inside_page([float(value) for value in line["bbox"]], page_size)
            chinese, association = ref_translation(source_text, bbox, reference, page_index)
            ident = f"p{page_index + 1:04d}-line-{line_index:04d}"
            status = "translated" if chinese else "manual_review"
            if status == "translated":
                translated += 1
                evidence.append({"translation_id": f"ref-{ident}", "page_index": page_index, "bbox": bbox, "text": chinese, "source_file": str(reference), "source_association": f"{source_text} ({association})", "action": "replace", "evidence_only": True})
            else:
                manual += 1
                chinese = "待人工翻译"
            target = target_for(bbox, page_size, region_type)
            placement: dict[str, Any] = {"side": "below", "mode": "table_cell" if region_type == "directory_index" else "inline", "selected_region": target, "candidate_regions": [], "font_size": 3.2, "rotation": int(line.get("rotation", 0)) % 360, "decision_source": "multimodal_visual_plan", "leader_allowed_when_local_space_exhausted": False, "multimodal_visual_whitespace_override": True}
            if region_type == "directory_index":
                placement.update({"preserve_source": False, "exact_ink_masks": [bbox], "render_runs": [{"text": chinese, "bbox": target, "font_size": 3.2, "font_name": "simhei", "color": BLACK, "rotation": int(line.get("rotation", 0)) % 360}]})
            else:
                placement.update({"preserve_source": True, "render_text": chinese, "color": BLUE})
            entries.append({"coverage": {"candidate_id": ident, "page_index": page_index, "source_text": source_text, "source_bbox": bbox, "status": status, "reason": "reference evidence unavailable; manual translation required" if status == "manual_review" else None, "inspection_basis": "single Terra High page packet visual plan; OCR extraction only"}, "block": {"block_id": ident, "member_ids": [ident], "page_index": page_index, "page_region_id": region_id, "region_type": region_type, "source_text": source_text, "source_bbox": bbox, "translated_text": chinese, "coverage_status": status, "decision_source": "multimodal_visual_plan", "layout_role": "label", "typography": {"semantic_role": "label", "bold": False}, "placement": placement}})
        # V3 validation requires a complete audited zone, including pages whose
        # native text layer is absent. A visual-only manual block makes that
        # condition explicit instead of silently dropping a page.
        if not lines:
            ident = f"p{page_index + 1:04d}-visual-only"
            manual += 1
            bbox = [0.0, 0.0, min(100.0, page_size[0]), min(30.0, page_size[1])]
            entries.append({"coverage": {"candidate_id": ident, "page_index": page_index, "source_text": "VISUAL TEXT REQUIRES DECLARED OCR REVIEW", "source_bbox": bbox, "status": "manual_review", "reason": "no native source text; crop-only OCR must be adjudicated by supervisor", "inspection_basis": "page packet visual review"}, "block": {"block_id": ident, "member_ids": [ident], "page_index": page_index, "page_region_id": region_id, "region_type": region_type, "source_text": "VISUAL TEXT REQUIRES DECLARED OCR REVIEW", "source_bbox": bbox, "translated_text": "待人工翻译", "coverage_status": "manual_review", "decision_source": "multimodal_visual_plan", "layout_role": "label", "typography": {"semantic_role": "label", "bold": False}, "placement": {"side": "below", "mode": "table_cell" if region_type == "directory_index" else "inline", "selected_region": bbox, "candidate_regions": [], "font_size": 3.2, "rotation": 0, "decision_source": "multimodal_visual_plan", "preserve_source": region_type != "directory_index", "render_text": "待人工翻译", "color": BLUE, "leader_allowed_when_local_space_exhausted": False}}})
    blocks = [entry["block"] for entry in entries]
    zones = []
    for region in regions:
        ids = [block["block_id"] for block in blocks if block["page_region_id"] == region["region_id"]]
        zones.append({"zone_id": region["region_id"], "zone_type": region["region_type"], "page_index": region["page_index"], "member_ids": ids, "block_ids": ids, "status": "complete", "decision_source": "multimodal_visual_plan"})
    first_type, first_delivery, _ = classify([], source.name)
    # Dense-index documents can contain only index pages; mixed documents use
    # inline delivery to avoid treating ordinary drawing pages as opaque.
    is_all_index = all(region["region_type"] == "directory_index" for region in regions)
    delivery_mode = "opaque_bilingual_reflow" if is_all_index else "inline_bilingual"
    payload = {"schema": "engineering-drawing-multimodal-plan-v3", "workflow_version": WORKFLOW_VERSION, "status": "approved", "agent_plan_status": "approved", "agent_name": "engineering-drawing-translator", "supervisor_count": 1, "parallel_supervisors": False, "model_provider": "openai-codex", "model_name": "gpt-5.6-terra", "reasoning_profile": "high", "supervisor_adapter": "terra-high", "model_capabilities": ["multimodal_page_planning", "ocr_task_supervision", "semantic_translation_planning", "translation_placement_planning", "visual_release_review"], "multimodal_page_planning": True, "execution_policy": "strict_multimodal_execution", "visual_planning_authority": {"authority": "multimodal_model", "sequence": "visual_design_before_ocr_execution", "ocr_role": "extraction_and_mask_execution_only", "placement_basis": "rendered_page_visual"}, "render_provenance": {"base": "original_source_pdf", "source_sha256": sha256(source), "reference_usage": "translation_evidence_only", "copied_reference_page_or_region": False}, "page_type": "dense_drawing_index" if is_all_index else "engineering_drawing", "delivery_mode": delivery_mode, "page_region_map": regions, "existing_translation_inventory": evidence, "reference_translation_evidence": {"reference_pdf": str(reference) if reference else None, "reference_sha256": sha256(reference) if reference and reference.exists() else None, "usage": "translation_evidence_only", "may_supply_page_pixels": False, "may_supply_target_coordinates": False}, "coverage_inventory": [entry["coverage"] for entry in entries], "semantic_blocks": blocks, "mandatory_zone_audit": zones, "supervisor_plan": {"contract_version": "v3-supervisor-plan-1", "role": "multimodal_page_manager", "status": "approved", "model_name": "gpt-5.6-terra", "reasoning_profile": "high", "page_type": "dense_drawing_index" if is_all_index else "engineering_drawing", "delivery_mode": delivery_mode, "ocr_tasks": tasks, "translation_tasks": [{"id": f"translate-{block['block_id']}", "semantic_block": block["block_id"], "source_candidate_ids": block["member_ids"]} for block in blocks], "placement_policy": {"authority": "Terra High page-packet visual planning", "target_selection": "final target only; no executor fallback", "ocr_execution_mode": "supervisor_declared_task_crops", "unplanned_full_page_scan": False, "generic_full_page_fallback": "forbidden", "drawing_body": "blue preserve-source", "directory_index": "glyph-alpha-only black Chinese replacement"}, "escalations": ["Any unpaired source text remains manual_review and blocks publication; OCR may not decide translation or placement."]}, "execution_contract": {"ocr_execution_mode": "supervisor_declared_task_crops", "unplanned_full_page_scan": False, "allow_generic_full_page_fallback": False, "allow_crop_expansion_or_relocation": False, "all_tasks_page_bound": True}}
    return validate_multimodal_plan(payload, source_pdf_path=source), translated, manual


def command(args: list[str]) -> tuple[bool, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO / "backend" / "scripts")
    result = subprocess.run([sys.executable, "-m", "services.engineering_drawing.cli", *args], cwd=REPO, env=environment, capture_output=True, text=True)
    return result.returncode == 0, (result.stdout + result.stderr)[-6000:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["plan", "execute"], required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    records = index["records"][: args.limit or None]
    progress_path = ARTIFACT_ROOT / "batch-progress.json"
    progress = {"schema": "terra-supervisor-full-v36-progress", "workflow_version": WORKFLOW_VERSION, "supervisor_count": 1, "phase": args.phase, "started_at": now(), "source_total": len(records), "page_total": sum(int(record["page_count"]) for record in records), "records": []}
    for number, record in enumerate(records, start=1):
        source = Path(record["source_pdf"])
        slug = Path(record["artifact_dir"]).name
        work = ARTIFACT_ROOT / "sources" / slug
        status: dict[str, Any] = {"sequence": number, "source_pdf": str(source), "page_count": record["page_count"], "status": "started", "updated_at": now()}
        try:
            plan_path = work / "supervisor-plan.json"
            if not plan_path.exists():
                status.update({"status": "awaiting_real_supervisor_plan", "publication": "blocked"})
                raise RuntimeError("no real multimodal supervisor plan exists")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan = validate_real_supervisor_plan(plan, source_pdf_path=source, require_final_review=False)
            status.update({"translated_blocks": sum(1 for item in plan["coverage_inventory"] if item["status"] == "translated"), "manual_review_blocks": sum(1 for item in plan["coverage_inventory"] if item["status"] == "manual_review")})
            ok, output = command(["v3-supervisor-handoff", "--source", str(source), "--plan", str(plan_path), "--output-dir", str(work / "handoff")])
            if not ok:
                raise RuntimeError(f"handoff_failed: {output}")
            status["handoff"] = str(work / "handoff" / "supervisor-handoff.json")
            if args.phase == "execute":
                ocr_path = work / "ocr" / "ocr.json"
                ok, output = command(["ocr", "--pdf", str(source), "--output", str(ocr_path), "--cache-dir", str(ARTIFACT_ROOT / "ocr-cache"), "--supervisor-plan", str(plan_path), "--start-page", "1", "--end-page", str(record["page_count"]), "--no-deepseek"])
                if not ok:
                    status.update({"status": "ocr_failed", "error": output})
                elif status["manual_review_blocks"]:
                    status.update({"status": "manual_review_blocks_prevent_publish", "ocr": str(ocr_path), "publication": "blocked"})
                elif not isinstance(plan.get("final_visual_review"), dict):
                    status.update({"status": "awaiting_final_visual_review", "ocr": str(ocr_path), "publication": "blocked"})
                else:
                    candidate = work / "candidate" / f"{slug}.pdf"
                    candidate.parent.mkdir(parents=True, exist_ok=True)
                    ok, output = command(["v3-render", "--source", str(source), "--plan", str(plan_path), "--regions-json", str(ocr_path), "--output", str(candidate), "--agent-manifest", str(Path(record["artifact_dir"]) / "agent-manifest.json")])
                    if not ok:
                        status.update({"status": "render_failed", "ocr": str(ocr_path), "error": output})
                    else:
                        placement_audit = candidate.with_suffix(".inline-placement.json")
                        visual_qa = analyze_visual_qa(output_pdf_path=candidate, placement_audit_path=placement_audit)
                        gate = build_review_gate(review=plan["final_visual_review"], visual_qa=visual_qa)
                        write_json(work / "final-review-gate.json", gate)
                        if not gate["passed"]:
                            status.update({"status": "visual_review_failed", "ocr": str(ocr_path), "candidate_pdf": str(candidate), "visual_qa": visual_qa, "publication": "blocked"})
                        else:
                            target = RELEASE_ROOT / f"{slug}.pdf"
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(candidate, target)
                            status.update({"status": "published", "ocr": str(ocr_path), "output_pdf": str(target), "candidate_pdf": str(candidate), "visual_qa": visual_qa, "error": ""})
            else:
                status["status"] = "planned_and_handoff_ready"
        except Exception as error:  # preserve per-source failure and continue.
            if status.get("status") == "started":
                status["status"] = "blocked"
            status["error"] = str(error)
        status["updated_at"] = now()
        write_json(work / "status.json", status)
        progress["records"].append(status)
        progress["updated_at"] = now()
        progress["counts"] = {key: sum(1 for item in progress["records"] if item["status"] == key) for key in {item["status"] for item in progress["records"]}}
        write_json(progress_path, progress)
        print(f"[{number}/{len(records)}] {source.name}: {status['status']}", flush=True)
    progress["completed_at"] = now()
    write_json(ARTIFACT_ROOT / f"batch-summary-{args.phase}.json", progress)


if __name__ == "__main__":
    main()
