# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


def _slug(relative_path: str) -> str:
    relative = Path(relative_path)
    category = re.sub(r"[^A-Za-z0-9]+", "_", relative.parts[0]).strip("_")
    stem = re.sub(r"[^A-Za-z0-9]+", "_", relative.stem).strip("_")
    digest = hashlib.sha1(str(relative).encode("utf-8")).hexdigest()[:10]
    return f"{category or 'drawing'}__{stem or 'sheet'}__{digest}"


def _is_current_release(marker: dict) -> bool:
    authority = marker.get("visual_planning_authority") or {}
    required_authority = {
        "authority": "multimodal_model",
        "sequence": "visual_design_before_ocr_execution",
        "ocr_role": "extraction_and_mask_execution_only",
        "placement_basis": "rendered_page_visual",
    }
    return (
        marker.get("schema") == "engineering-drawing-v3.4-release-v1"
        and marker.get("status") == "passed_and_published"
        and marker.get("independent_review_verdict") == "PASS"
        and all(authority.get(key) == value for key, value in required_authority.items())
        and bool(marker.get("candidate_sha256"))
        and bool(marker.get("plan_sha256"))
        and bool(marker.get("published_outputs"))
        and all(Path(path).is_file() for path in marker.get("published_outputs", []))
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build resumable strict V3.4 unique/physical PDF queue.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--translated-root", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    source_root = Path(manifest["root"])
    queue = []
    physical_count = 0
    physical_pages = 0
    for item in manifest["items"]:
        duplicate_paths = []
        for value in item.get("duplicate_paths", []):
            duplicate = Path(value)
            duplicate_paths.append(str(duplicate if duplicate.is_absolute() else source_root / duplicate))
        physical_paths = [item["source_path"], *duplicate_paths]
        physical_count += len(physical_paths)
        physical_pages += int(item["page_count"]) * len(physical_paths)
        relative = item["relative_path"]
        slug = _slug(relative)
        category = "01_报审图纸" if relative.startswith("报审图纸/") else "02_清真寺施工图纸"
        artifact_dir = args.artifact_root / slug
        # V3.3 markers predate the strict visual-planning-authority contract.
        # Keep them as audit history, but never count them as a V3.4 release.
        release_marker = artifact_dir / "v3.4-release.json"
        released = False
        marker = None
        if release_marker.exists():
            marker = json.loads(release_marker.read_text(encoding="utf-8"))
            released = _is_current_release(marker)
        queue.append(
            {
                "content_hash": item["content_hash"],
                "canonical_source": item["source_path"],
                "relative_path": relative,
                "physical_paths": physical_paths,
                "physical_count": len(physical_paths),
                "page_count": int(item["page_count"]),
                "reference_pdf": item.get("legacy_translation_path"),
                "work_class": "reference_assisted" if item.get("legacy_translation_path") else "from_scratch",
                "artifact_dir": str(artifact_dir),
                "release_marker": str(release_marker),
                "status": "released" if released else "pending",
                "published_outputs": (marker or {}).get("published_outputs", []),
                "translated_category": category,
            }
        )

    payload = {
        "schema": "engineering-drawing-v3.4-production-queue-v1",
        "source_manifest": str(args.manifest.resolve()),
        "translated_root": str(args.translated_root.resolve()),
        "summary": {
            "unique_pdf_count": len(queue),
            "physical_pdf_count": physical_count,
            "physical_page_count": physical_pages,
            "reference_assisted_unique": sum(row["work_class"] == "reference_assisted" for row in queue),
            "from_scratch_unique": sum(row["work_class"] == "from_scratch" for row in queue),
            "released_unique": sum(row["status"] == "released" for row in queue),
            "pending_unique": sum(row["status"] == "pending" for row in queue),
        },
        "items": queue,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
