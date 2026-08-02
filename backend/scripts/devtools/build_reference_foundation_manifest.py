"""Prepare the canonical (non-duplicate) worklist for DeepSeek foundation data.

The emitted manifest contains paths and hashes only.  DeepSeek must use it to
write *foundation* JSON per canonical source; it must not render or publish a
PDF.  Duplicate reuse stays a Codex-owned deterministic operation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delivery-manifest", type=Path, required=True)
    parser.add_argument("--duplicate-map", type=Path, required=True)
    parser.add_argument("--accepted-item", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    delivery = json.loads(args.delivery_manifest.read_text(encoding="utf-8"))
    duplicate_map = json.loads(args.duplicate_map.read_text(encoding="utf-8"))
    accepted = set(args.accepted_item)
    items = [item for item in delivery.get("items") or [] if isinstance(item, Mapping)]
    work_items = [
        {
            "item_id": str(item.get("item_id") or ""),
            "source_pdf": str(item.get("source_pdf") or ""),
            "content_hash": str(item.get("content_hash") or ""),
            "document_context": dict(item.get("document_context") or {}),
        }
        for item in items
        if str(item.get("item_id") or "") not in accepted
    ]
    if any(not item["item_id"] or not item["source_pdf"] or not item["content_hash"] for item in work_items):
        raise SystemExit("delivery manifest includes a canonical work item without id/path/hash")
    result: dict[str, Any] = {
        "schema": "delivery-160-reference-foundation-work-v1",
        "batch_id": str(delivery.get("batch_id") or ""),
        "accepted_reference_item_ids": sorted(accepted),
        "canonical_total": len(items),
        "canonical_remaining": len(work_items),
        "duplicate_reuse_count": int(duplicate_map.get("count") or 0),
        "duplicate_map_path": str(args.duplicate_map),
        "foundation_output_dir": str(args.output.parent / "foundations"),
        "items": work_items,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"canonical_remaining": len(work_items), "duplicate_reuse_count": result["duplicate_reuse_count"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
