# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.engineering_drawing.existing_translation_registry import (
    extract_native_existing_translations,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record existing native Chinese text as evidence for one multimodal supervisor.")
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    registry = extract_native_existing_translations(args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"items": len(registry["items"]), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
