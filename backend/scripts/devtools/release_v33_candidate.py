# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

import fitz

from services.engineering_drawing.batch import _safe_slug, _translated_category
from services.engineering_drawing.multimodal_plan import (
    prepare_multimodal_plan_payload,
    validate_multimodal_plan,
)


REQUIRED_VISUAL_CHECKS = {
    "all_natural_language_translated",
    "translated_text_readable",
    "translated_text_local",
    "no_text_overlap_or_crowding",
    "no_white_body_blocks",
    "logos_grids_numbers_preserved",
    "original_page_geometry_preserved",
}


def _require_secure_release_path() -> None:
    raise SystemExit(
        "Legacy v3.4 release is disabled; use run_verified_samples with a "
        "secure supervisor bundle and release authorization"
    )


def _load_visual_pass(review_path: Path) -> dict:
    if review_path.suffix.casefold() != ".json":
        raise SystemExit("Independent multimodal review must be structured JSON")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if str(review.get("verdict", "")).upper() != "PASS":
        raise SystemExit("Independent multimodal review is not PASS; refusing release")
    inspection = review.get("inspection") or {}
    if inspection.get("source_and_candidate_full_page") is not True:
        raise SystemExit("Independent review did not inspect source and candidate full pages")
    if int(inspection.get("four_x_crops") or 0) < 1:
        raise SystemExit("Independent review requires high-resolution zone crops")
    checks = review.get("hard_checks") or {}
    missing = sorted(key for key in REQUIRED_VISUAL_CHECKS if checks.get(key) is not True)
    if missing:
        raise SystemExit("Independent visual hard checks failed or missing: " + ", ".join(missing))
    return review


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    _require_secure_release_path()
    parser = argparse.ArgumentParser(description="Atomically release one independently approved strict V3.4 candidate.")
    parser.add_argument("--queue", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--content-hash", required=True)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--independent-review", required=True, type=Path)
    args = parser.parse_args()

    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    matches = [row for row in queue["items"] if row["content_hash"] == args.content_hash]
    if len(matches) != 1:
        raise SystemExit(f"Expected one queue item for hash, found {len(matches)}")
    item = matches[0]
    review = _load_visual_pass(args.independent_review)
    if not args.candidate.is_file() or not args.plan.is_file():
        raise SystemExit("Candidate PDF or V3 plan is missing")
    source = Path(item["canonical_source"])
    raw_plan = json.loads(args.plan.read_text(encoding="utf-8"))
    validated = validate_multimodal_plan(
        prepare_multimodal_plan_payload(raw_plan, source_pdf_path=source),
        source_pdf_path=source,
    )
    if validated.get("execution_policy") != "strict_multimodal_execution":
        raise SystemExit("Production release requires strict_multimodal_execution")
    with fitz.open(source) as original, fitz.open(args.candidate) as candidate:
        if original.page_count != candidate.page_count:
            raise SystemExit("Candidate page count differs from source")
        for index in range(original.page_count):
            if (
                abs(original[index].rect.width - candidate[index].rect.width) > 0.5
                or abs(original[index].rect.height - candidate[index].rect.height) > 0.5
            ):
                raise SystemExit(f"Candidate geometry differs on page {index + 1}")

    translated_root = Path(queue["translated_root"]).resolve()
    outputs: list[str] = []
    for physical in item["physical_paths"]:
        physical_path = Path(physical)
        category = _translated_category(physical_path, args.source_root)
        target = (translated_root / category / f"{_safe_slug(physical_path, args.source_root)}.pdf").resolve()
        if translated_root not in target.parents:
            raise SystemExit(f"Unsafe release target: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_suffix(".v3.4-staging.pdf")
        shutil.copyfile(args.candidate, staging)
        staging.replace(target)
        outputs.append(str(target))

    marker = {
        "schema": "engineering-drawing-v3.4-release-v1",
        "status": "passed_and_published",
        "content_hash": item["content_hash"],
        "canonical_source": str(source),
        "page_count": item["page_count"],
        "physical_output_count": len(outputs),
        "semantic_block_count": len(validated["semantic_blocks"]),
        "coverage_candidate_count": len(validated["coverage_inventory"]),
        "visual_planning_authority": validated["visual_planning_authority"],
        "independent_review_verdict": review["verdict"],
        "independent_multimodal_review": str(args.independent_review.resolve()),
        "candidate_pdf": str(args.candidate.resolve()),
        "candidate_sha256": _sha256(args.candidate),
        "plan": str(args.plan.resolve()),
        "plan_sha256": _sha256(args.plan),
        "published_outputs": outputs,
    }
    marker_path = Path(item["artifact_dir"]) / "v3.4-release.json"
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(marker, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
