from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path

from services.translation.llm.shared.provider_runtime import DEFAULT_BASE_URL
from services.translation.llm.shared.provider_runtime import DEFAULT_MODEL
from services.translation.llm.shared.provider_runtime import get_api_key
from services.translation.llm.shared.provider_runtime import request_chat_content

from .benchmark.adjudication import apply_adjudication, lock_gold
from .benchmark.prelabel import (
    request_prelabels,
    request_visual_review,
    select_adjudication_queue,
)
from .benchmark.runner import evaluate_workspace
from .benchmark.schema import load_challenge_manifest, load_core_manifest
from .benchmark.workspace import seed_workspace
from .inventory import build_inventory
from .legacy_audit import audit_inventory
from .reports import write_report_bundle
from .sample_builder import build_samples
from .hybrid_ocr import HybridOcrConfig
from .hybrid_ocr import run_hybrid_ocr
from .harness import GeographicResolver
from .harness import run_full_coverage_harness
from .harness import write_harness_reports


def _benchmark_seed_workspace(workspace: Path) -> Path:
    resolved = Path(workspace).resolve()
    folded_parts = [part.casefold() for part in resolved.parts]
    for index in range(len(folded_parts) - 1):
        if folded_parts[index : index + 2] == [
            "01_bilingual_inline",
            "translated",
        ]:
            raise ValueError(
                "benchmark workspace cannot be inside the translated delivery directory"
            )
    return resolved


def _benchmark_sample_dir(workspace: Path, sample_id: str) -> Path:
    if re.fullmatch(r"(?:core|challenge)-[0-9]{2,3}", sample_id) is None:
        raise ValueError("benchmark sample_id is invalid")
    workspace_root = Path(workspace).resolve(strict=True)
    sample_dir = workspace_root / "samples" / sample_id
    resolved = sample_dir.resolve(strict=True)
    if (
        workspace_root not in resolved.parents
        or sample_dir.is_symlink()
        or not resolved.is_dir()
    ):
        raise ValueError("benchmark sample directory must stay inside workspace")
    return resolved


def _benchmark_candidate_file(
    candidate_root: Path, sample_id: str, suffix: str
) -> Path:
    root = Path(candidate_root).resolve(strict=True)
    target = root / f"{sample_id}{suffix}"
    resolved = target.resolve(strict=True)
    if root not in resolved.parents or target.is_symlink() or not resolved.is_file():
        raise ValueError("benchmark candidate file must stay inside candidate root")
    return resolved


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory and audit legacy bilingual engineering drawings."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "audit", "all"):
        command = subparsers.add_parser(name)
        command.add_argument("--root", required=True, type=Path)
        command.add_argument("--output", required=True, type=Path)
        if name in ("audit", "all"):
            command.add_argument("--screenshots", action="store_true")
            command.add_argument("--dpi", type=int, default=110)
            command.add_argument("--only-paired", action="store_true")
    samples = subparsers.add_parser("samples")
    samples.add_argument("--audit-json", required=True, type=Path)
    samples.add_argument("--output-root", required=True, type=Path)
    samples.add_argument("--work-dir", required=True, type=Path)
    samples.add_argument("--model", default=DEFAULT_MODEL)
    samples.add_argument("--base-url", default=DEFAULT_BASE_URL)
    samples.add_argument("--no-deepseek-ocr", action="store_true")
    samples.add_argument("--no-geographic-lookup", action="store_true")
    ocr = subparsers.add_parser("ocr")
    ocr.add_argument("--pdf", required=True, type=Path)
    ocr.add_argument("--output", required=True, type=Path)
    ocr.add_argument("--cache-dir", required=True, type=Path)
    ocr.add_argument("--start-page", type=int, default=1)
    ocr.add_argument("--end-page", type=int, default=-1)
    ocr.add_argument("--dpi", type=int, default=220)
    ocr.add_argument("--no-deepseek", action="store_true")
    harness = subparsers.add_parser("harness")
    harness.add_argument("--coverage-json", required=True, type=Path)
    harness.add_argument("--placement-audit", type=Path)
    harness.add_argument("--output", required=True, type=Path)
    harness.add_argument("--geo-cache", type=Path)
    harness.add_argument("--online-geo", action="store_true")
    harness.add_argument("--context", action="append", default=[])
    benchmark_seed = subparsers.add_parser("benchmark-seed")
    benchmark_seed.add_argument("--source-root", required=True, type=Path)
    benchmark_seed.add_argument("--workspace", required=True, type=Path)
    benchmark_seed.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("benchmark") / "core-set.v1.json",
    )
    benchmark_seed.add_argument(
        "--challenge-manifest",
        type=Path,
        default=Path(__file__).with_name("benchmark") / "challenge-set.v1.json",
    )
    benchmark_seed.add_argument("--dpi", type=int, default=144)
    benchmark_prelabel = subparsers.add_parser("benchmark-prelabel")
    benchmark_prelabel.add_argument("--workspace", required=True, type=Path)
    benchmark_prelabel.add_argument("--sample-id", required=True)
    benchmark_prelabel.add_argument("--regions-json", required=True, type=Path)
    benchmark_prelabel.add_argument("--model", default="gpt-5.6-sol")
    benchmark_prelabel.add_argument("--base-url", default=DEFAULT_BASE_URL)
    benchmark_adjudicate = subparsers.add_parser("benchmark-adjudicate")
    benchmark_adjudicate.add_argument("--workspace", required=True, type=Path)
    benchmark_adjudicate.add_argument("--sample-id", required=True)
    benchmark_adjudicate.add_argument("--decisions", required=True, type=Path)
    benchmark_adjudicate.add_argument("--actor", default="user")
    benchmark_adjudicate.add_argument("--decided-at", required=True)
    benchmark_adjudicate.add_argument("--lock", action="store_true")
    benchmark_visual = subparsers.add_parser("benchmark-visual-review")
    benchmark_visual.add_argument("--workspace", required=True, type=Path)
    benchmark_visual.add_argument("--candidate-root", required=True, type=Path)
    benchmark_visual.add_argument("--sample-id", required=True)
    benchmark_visual.add_argument("--model", default="gpt-5.6-sol")
    benchmark_visual.add_argument("--base-url", default=DEFAULT_BASE_URL)
    benchmark_evaluate = subparsers.add_parser("benchmark-evaluate")
    benchmark_evaluate.add_argument("--workspace", required=True, type=Path)
    benchmark_evaluate.add_argument("--candidate-root", required=True, type=Path)
    benchmark_evaluate.add_argument("--baseline-report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "benchmark-seed":
        result = seed_workspace(
            args.source_root,
            _benchmark_seed_workspace(args.workspace),
            load_core_manifest(args.manifest),
            dpi=args.dpi,
            challenge_manifest=load_challenge_manifest(args.challenge_manifest),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "benchmark-prelabel":
        import base64

        sample_dir = _benchmark_sample_dir(args.workspace, args.sample_id)
        image_data_url = "data:image/png;base64," + base64.b64encode(
            (sample_dir / "source.png").read_bytes()
        ).decode("ascii")
        regions = json.loads(args.regions_json.read_text(encoding="utf-8"))[
            "regions"
        ]
        sample_record = json.loads(
            (sample_dir / "sample.json").read_text(encoding="utf-8")
        )
        result = request_prelabels(
            sample_id=args.sample_id,
            image_data_url=image_data_url,
            regions=regions,
            page={
                "width": sample_record["page_size"][0],
                "height": sample_record["page_size"][1],
                "rotation": sample_record["page_rotation"],
            },
            api_key=get_api_key(),
            model=args.model,
            base_url=args.base_url,
            request_fn=request_chat_content,
        )
        (sample_dir / "prelabel.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (sample_dir / "adjudication-queue.json").write_text(
            json.dumps(
                {"items": select_adjudication_queue(result)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0
    if args.command == "benchmark-adjudicate":
        sample_dir = _benchmark_sample_dir(args.workspace, args.sample_id)
        prelabel = json.loads(
            (sample_dir / "prelabel.json").read_text(encoding="utf-8")
        )
        decisions = json.loads(args.decisions.read_text(encoding="utf-8"))[
            "decisions"
        ]
        gold = apply_adjudication(
            prelabel, decisions, args.actor, args.decided_at
        )
        if args.lock:
            gold = lock_gold(gold, args.actor, args.decided_at)
        output_name = (
            "gold.locked.json"
            if gold.status == "locked"
            else "gold.adjudicated.json"
        )
        (sample_dir / output_name).write_text(
            json.dumps(gold.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    if args.command == "benchmark-visual-review":
        import base64
        import fitz

        sample_dir = _benchmark_sample_dir(args.workspace, args.sample_id)
        source_url = "data:image/png;base64," + base64.b64encode(
            (sample_dir / "source.png").read_bytes()
        ).decode("ascii")
        candidate_pdf = _benchmark_candidate_file(
            args.candidate_root, args.sample_id, ".pdf"
        )
        with fitz.open(candidate_pdf) as document:
            candidate_png = document[0].get_pixmap(
                dpi=144, alpha=False
            ).tobytes("png")
        candidate_url = "data:image/png;base64," + base64.b64encode(
            candidate_png
        ).decode("ascii")
        candidate_regions = json.loads(
            _benchmark_candidate_file(
                args.candidate_root, args.sample_id, ".regions.json"
            ).read_text(encoding="utf-8")
        )["regions"]
        candidate_region_ids = [
            str(item.get("block_id") or item.get("region_id"))
            for item in candidate_regions
        ]
        result = request_visual_review(
            sample_id=args.sample_id,
            source_image_data_url=source_url,
            candidate_image_data_url=candidate_url,
            candidate_region_ids=candidate_region_ids,
            api_key=get_api_key(),
            model=args.model,
            base_url=args.base_url,
            request_fn=request_chat_content,
        )
        (candidate_pdf.parent / f"{args.sample_id}.subjective.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    if args.command == "benchmark-evaluate":
        result = evaluate_workspace(
            args.workspace,
            args.candidate_root,
            args.baseline_report,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["hard_failure_count"] == 0 else 2
    if args.command == "samples":
        print(
            json.dumps(
                build_samples(
                    audit_json_path=args.audit_json,
                    output_root=args.output_root,
                    work_dir=args.work_dir,
                    model=args.model,
                    base_url=args.base_url,
                    enable_deepseek_ocr=not args.no_deepseek_ocr,
                    enable_geographic_lookup=not args.no_geographic_lookup,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "ocr":
        result = run_hybrid_ocr(
            pdf_path=args.pdf,
            output_path=args.output,
            cache_dir=args.cache_dir,
            start_page=args.start_page,
            end_page=args.end_page,
            config=HybridOcrConfig(dpi=args.dpi),
            enable_deepseek=not args.no_deepseek,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
        return 0
    if args.command == "harness":
        coverage = json.loads(args.coverage_json.read_text(encoding="utf-8"))
        placement = []
        if args.placement_audit and args.placement_audit.exists():
            placement = json.loads(args.placement_audit.read_text(encoding="utf-8")).get("placements", [])
        result = run_full_coverage_harness(
            coverage.get("regions", []),
            placement_audit=placement,
            geographic_resolver=GeographicResolver(cache_path=args.geo_cache, allow_online=args.online_geo),
            context_hints=args.context,
        )
        json_path, csv_path = write_harness_reports(result, output_json=args.output)
        print(json.dumps({"report": result.report, "json": str(json_path), "csv": str(csv_path)}, ensure_ascii=False, indent=2))
        return 0 if bool(result.report["passed"]) else 2
    inventory = build_inventory(args.root)
    manifest_json, manifest_csv = inventory.write(args.output)
    response: dict[str, object] = {
        "manifest_json": str(manifest_json),
        "manifest_csv": str(manifest_csv),
        "summary": inventory.to_dict()["summary"],
    }
    if args.command in ("audit", "all"):
        result = audit_inventory(inventory, only_paired=args.only_paired)
        response["reports"] = write_report_bundle(
            result,
            args.output,
            screenshots=args.screenshots,
            dpi=args.dpi,
        )
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
