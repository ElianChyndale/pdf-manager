# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
"""Run ten representative source PDFs through the verified single-supervisor workflow.

This entry point deliberately has no planner fallback.  The supervisor must
write the plan after inspecting the source page images; this script only
packetizes, runs declared OCR, renders a candidate, and gates publication on
the same supervisor's final visual review.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

REPO = Path(__file__).resolve().parents[3]
SAMPLE_ROOT = REPO / "output" / "pdf" / "engineering-drawing" / "01_Bilingual_Inline"
RUN_VERSION = "v3.11"
ARTIFACT_ROOT = SAMPLE_ROOT / "agent-artifacts" / "sol-light-supervisor-verified-v311"
CANDIDATE_ROOT = SAMPLE_ROOT / "translated" / "v3.11_verified_supervisor_candidates"
RELEASE_ROOT = SAMPLE_ROOT / "translated" / "v3.11_verified_supervisor"
SOURCE_ROOT = REPO.parent / "WROK-CONTENT" / "malasia"
RECORDS_PATH = ARTIFACT_ROOT / "sample-records.json"

sys.path.insert(0, str(REPO / "backend" / "scripts"))

from services.engineering_drawing.agent_system import EngineeringDrawingAgent
from services.engineering_drawing.batch import (
    _safe_slug,
    discover_references,
    discover_sources,
    match_reference,
)
from services.engineering_drawing.existing_translation_registry import (
    extract_native_existing_translations,
)
from services.engineering_drawing.supervisor_contract import (
    build_review_gate,
    validate_real_supervisor_plan,
)
from services.engineering_drawing.authorization import authorize_release
from services.engineering_drawing.visual_qa import analyze_visual_qa


SELECTED = (
    ("00_LIST OF DRAWING_A3 FORMAT.pdf", "A3 DETAIL DRAWING"),
    ("02_REV. JULAI 2025 JADUAL PINTU & TINGKAP.pdf", "A3 DETAIL DRAWING"),
    ("03_REV JULAI 2025 JADUAL PANEL KACA.pdf", "A3 DETAIL DRAWING"),
    ("05_REV. JULAI 2025 PERINCIAN TANDAS.pdf", "A3 DETAIL DRAWING"),
    ("10_REV. JULAI 2025 ROOF DETAIL.pdf", "A3 DETAIL DRAWING"),
    ("1310-CN-ELEC-A001_Site Plan.pdf", "报审图纸"),
    ("1310-CN-ELEC-A002_Elevation.pdf", "报审图纸"),
    ("1310-CN-ELEC-ELPS-B001_Main Earth Grid.pdf", "报审图纸"),
    ("1310-CN-ELEC-SCH-C001_275kV SLD.pdf", "报审图纸"),
    ("1312-CN-MECH-ACMV-A001.pdf", "报审图纸"),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def command(args: list[str]) -> tuple[bool, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO / "backend" / "scripts")
    result = subprocess.run(
        [sys.executable, "-m", "services.engineering_drawing.cli", *args],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, (result.stdout + result.stderr)[-8000:]


def select_records() -> list[dict[str, Any]]:
    sources = discover_sources(SOURCE_ROOT)
    references = discover_references(SOURCE_ROOT)
    records: list[dict[str, Any]] = []
    for filename, top_level in SELECTED:
        candidates = [
            path
            for path in sources
            if path.name == filename
            and path.relative_to(SOURCE_ROOT).parts
            and path.relative_to(SOURCE_ROOT).parts[0] == top_level
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                f"expected one source for {filename!r} under {top_level!r}, got {len(candidates)}"
            )
        source = candidates[0]
        reference = match_reference(source, references, SOURCE_ROOT)
        slug = f"sample-{len(records) + 1:02d}__{_safe_slug(source, SOURCE_ROOT)}"
        records.append(
            {
                "sample_index": len(records) + 1,
                "source_pdf": str(source.resolve()),
                "reference_pdf": str(reference.resolve()) if reference else None,
                "slug": slug,
            }
        )
    return records


def prepare() -> list[dict[str, Any]]:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    agent = EngineeringDrawingAgent()
    records = select_records()
    for record in records:
        source = Path(record["source_pdf"])
        reference = Path(record["reference_pdf"]) if record.get("reference_pdf") else None
        work = ARTIFACT_ROOT / record["slug"]
        work.mkdir(parents=True, exist_ok=True)
        manifest = agent.build_manifest(source, reference_pdf=reference)
        registry = (
            extract_native_existing_translations(reference)
            if reference is not None
            else {"items": [], "required_next_step": "real_supervisor_visual_inventory"}
        )
        registry_path = work / "existing-translation-registry.json"
        write_json(registry_path, registry)
        page_packets: list[dict[str, Any]] = []
        for page_index in range(manifest["source_snapshot"]["page_count"]):
            page_dir = work / f"page-{page_index + 1:04d}"
            evidence = [
                item for item in registry.get("items", [])
                if item.get("page_index") == page_index
            ]
            packet = agent.build_page_packet(
                source,
                page_index,
                manifest=manifest,
                evidence=evidence,
                output_dir=page_dir,
                dpi=180,
            )
            page_packets.append(
                {
                    "page_index": page_index,
                    "packet": str((page_dir / "page-packet.json").resolve()),
                    "source_image": str((page_dir / packet["source_image"]).resolve()),
                    "image_sha256": _sha256(page_dir / packet["source_image"]),
                }
            )
        manifest["pages"] = page_packets
        manifest["existing_translation_registry"] = str(registry_path.resolve())
        manifest["status"] = "awaiting_real_multimodal_supervisor_plan"
        write_json(work / "agent-manifest.json", manifest)
        record["artifact_dir"] = str(work.resolve())
        record["page_count"] = manifest["source_snapshot"]["page_count"]
    write_json(RECORDS_PATH, {"schema": "verified-sample-records-v311", "run_version": RUN_VERSION, "records": records})
    return records


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_records() -> list[dict[str, Any]]:
    payload = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != len(SELECTED):
        raise RuntimeError("verified sample records are missing or incomplete")
    return [dict(item) for item in records]


def execute() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for record in load_records():
        source = Path(record["source_pdf"])
        work = Path(record["artifact_dir"])
        plan_path = work / "supervisor-plan.json"
        status: dict[str, Any] = {
            "sample_index": record["sample_index"],
            "source_pdf": str(source),
            "started_at": now(),
            "status": "started",
        }
        try:
            if not plan_path.exists():
                raise RuntimeError("waiting for a real supervisor plan")
            plan = validate_real_supervisor_plan(
                json.loads(plan_path.read_text(encoding="utf-8")),
                source_pdf_path=source,
                require_final_review=False,
            )
            write_json(plan_path, plan)
            status["coverage"] = {
                "total": len(plan["coverage_inventory"]),
                "translated": sum(item["status"] == "translated" for item in plan["coverage_inventory"]),
                "manual_review": sum(item["status"] == "manual_review" for item in plan["coverage_inventory"]),
            }
            if status["coverage"]["manual_review"]:
                raise RuntimeError("manual_review coverage blocks execution")
            ok, output = command(
                [
                    "v3-supervisor-handoff",
                    "--source", str(source),
                    "--plan", str(plan_path),
                    "--output-dir", str(work / "handoff"),
                ]
            )
            if not ok:
                raise RuntimeError(f"supervisor handoff failed: {output}")
            ocr_path = work / "ocr" / "ocr.json"
            ok, output = command(
                [
                    "ocr",
                    "--pdf", str(source),
                    "--output", str(ocr_path),
                    "--cache-dir", str(ARTIFACT_ROOT / "ocr-cache"),
                    "--supervisor-plan", str(plan_path),
                    "--start-page", "1",
                    "--end-page", str(record["page_count"]),
                    "--no-deepseek",
                ]
            )
            if not ok:
                raise RuntimeError(f"declared OCR failed: {output}")
            candidate = CANDIDATE_ROOT / f"{record['slug']}.pdf"
            candidate.parent.mkdir(parents=True, exist_ok=True)
            ok, output = command(
                [
                    "v3-render",
                    "--source", str(source),
                    "--plan", str(plan_path),
                    "--regions-json", str(ocr_path),
                    "--output", str(candidate),
                    "--agent-manifest", str(work / "agent-manifest.json"),
                    "--supervisor-bundle", str(work / "supervisor-run"),
                ]
            )
            if not ok:
                raise RuntimeError(f"deterministic render failed: {output}")
            placement_audit = candidate.with_suffix(".inline-placement.json")
            status.update(
                {
                    "status": "candidate_ready_for_same_supervisor_review",
                    "candidate_pdf": str(candidate),
                    "placement_audit": str(placement_audit),
                    "deterministic_visual_qa": analyze_visual_qa(
                        output_pdf_path=candidate,
                        placement_audit_path=placement_audit,
                    ),
                }
            )
        except Exception as error:
            status.update({"status": "blocked", "error": str(error)})
        status["finished_at"] = now()
        write_json(work / "execute-status.json", status)
        results.append(status)
    write_json(ARTIFACT_ROOT / "execute-summary.json", {"records": results})
    return results


def publish() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for record in load_records():
        source = Path(record["source_pdf"])
        work = Path(record["artifact_dir"])
        plan_path = work / "supervisor-plan.json"
        candidate = CANDIDATE_ROOT / f"{record['slug']}.pdf"
        status = {"sample_index": record["sample_index"], "source_pdf": str(source), "status": "blocked"}
        try:
            review_path = work / "final-visual-review.json"
            if not review_path.exists():
                raise RuntimeError("same supervisor final visual review is missing")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            review = json.loads(review_path.read_text(encoding="utf-8"))
            plan["final_visual_review"] = review
            write_json(plan_path, plan)
            validated = validate_real_supervisor_plan(
                plan,
                source_pdf_path=source,
                require_final_review=True,
            )
            write_json(plan_path, validated)
            placement_audit = candidate.with_suffix(".inline-placement.json")
            visual_qa = analyze_visual_qa(
                output_pdf_path=candidate,
                placement_audit_path=placement_audit,
            )
            gate = build_review_gate(review=review, visual_qa=visual_qa)
            write_json(work / "final-review-gate.json", gate)
            if not gate["passed"]:
                status.update({"status": "manual_review", "gate": gate, "candidate_pdf": str(candidate)})
            else:
                render_authorization = json.loads(
                    candidate.with_suffix(".render-authorization.json").read_text(encoding="utf-8")
                )
                release_authorization = authorize_release(
                    render_authorization=render_authorization,
                    candidate_pdf_path=candidate,
                    review=review,
                    deterministic_visual_qa=gate["deterministic_visual_qa"],
                )
                write_json(work / "release-authorization.json", release_authorization)
                target = RELEASE_ROOT / f"{record['slug']}.pdf"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, target)
                status.update({"status": "published", "output_pdf": str(target), "gate": gate})
        except Exception as error:
            status["error"] = str(error)
        status["finished_at"] = now()
        write_json(work / "publish-status.json", status)
        results.append(status)
    write_json(ARTIFACT_ROOT / "publish-summary.json", {"records": results})
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("prepare", "execute", "publish"), required=True)
    args = parser.parse_args()
    if args.phase == "prepare":
        result: Any = prepare()
    elif args.phase == "execute":
        result = execute()
    else:
        result = publish()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
