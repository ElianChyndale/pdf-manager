from __future__ import annotations

import argparse
import json
from pathlib import Path

from .inventory import build_inventory
from .legacy_audit import audit_inventory
from .reports import write_report_bundle


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
