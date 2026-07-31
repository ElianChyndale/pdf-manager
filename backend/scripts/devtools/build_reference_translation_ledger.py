# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.engineering_drawing.reference_translation_ledger import (
    build_reference_translation_ledger,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build evidence-only source/Chinese candidates from original and reference PDFs.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    ledger = build_reference_translation_ledger(args.source, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"entries": len(ledger["entries"]), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
