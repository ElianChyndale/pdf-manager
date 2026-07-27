from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from services.translation.llm.shared.provider_runtime import DEFAULT_BASE_URL
from services.translation.llm.shared.provider_runtime import DEFAULT_MODEL

from .inventory import build_inventory
from .legacy_audit import audit_inventory
from .reports import write_report_bundle
from .sample_builder import build_samples
from .hybrid_ocr import HybridOcrConfig
from .hybrid_ocr import run_hybrid_ocr


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
    ocr = subparsers.add_parser("ocr")
    ocr.add_argument("--pdf", required=True, type=Path)
    ocr.add_argument("--output", required=True, type=Path)
    ocr.add_argument("--cache-dir", required=True, type=Path)
    ocr.add_argument("--start-page", type=int, default=1)
    ocr.add_argument("--end-page", type=int, default=-1)
    ocr.add_argument("--dpi", type=int, default=220)
    ocr.add_argument("--no-deepseek", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
