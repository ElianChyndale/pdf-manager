"""Render private delivery-160 foundation JSON into readable reference PDFs.

This is deliberately a *reference-deliverable* renderer: every source page is
kept untouched and each translated natural-language block is made readable on
numbered reference pages.  It does not create a V4 release authorization or
write to ``formal-output``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping

import fitz

from services.rendering.output.engineering import render_bilingual_overlay


_CJK_START = "\u3400"
_CJK_END = "\u9fff"
_CONSTRUCTION_FOLDER = "清真寺施工图纸"
_SUBMISSION_FOLDER = "报审图纸"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_cjk(value: object) -> bool:
    return any(_CJK_START <= character <= _CJK_END for character in str(value or ""))


def _source_path(item: Mapping[str, Any], source_root: Path) -> Path:
    raw = Path(str(item.get("source_pdf") or ""))
    return raw if raw.is_absolute() else source_root / raw


def _category(item: Mapping[str, Any]) -> str:
    # The delivery manifest's output name is the batch-routing authority.  The
    # duplicate map contains only construction drawings and is routed with the
    # same marker below.
    return (
        _CONSTRUCTION_FOLDER
        if "CONSTRUCTION" in str(item.get("original_name") or item.get("relative_output") or "").upper()
        else _SUBMISSION_FOLDER
    )


def _output_name(item: Mapping[str, Any]) -> str:
    raw = Path(str(item.get("relative_output") or ""))
    if not raw.name or raw.suffix.casefold() != ".pdf":
        raise ValueError("delivery item lacks a PDF relative_output name")
    return f"{raw.stem}-zh-reference.pdf"


def _rect(value: object, *, label: str, page: fitz.Page) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{label} lacks a four-coordinate source_bbox")
    try:
        rect = fitz.Rect(*(float(number) for number in value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} has a nonnumeric source_bbox") from exc
    if rect.is_empty or rect.is_infinite or not page.rect.contains(rect):
        raise ValueError(f"{label} source_bbox is outside its display page")
    return list(rect)


def _foundation_regions(foundation: Mapping[str, Any], *, source: Path, expected_sha: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if foundation.get("schema") != "delivery-160-reference-foundation-v1":
        raise ValueError("unexpected foundation schema")
    if foundation.get("coordinate_space") != "display_page_rect":
        raise ValueError("foundation coordinate space is not display_page_rect")
    if str(foundation.get("source_sha256") or "") != expected_sha:
        raise ValueError("foundation source_sha256 differs from delivery manifest")
    pages = foundation.get("pages")
    if not isinstance(pages, list):
        raise ValueError("foundation pages is not a list")
    regions: list[dict[str, Any]] = []
    seen_block_ids: set[str] = set()
    counts = {"translated": 0, "literal_only": 0, "manual_review": 0}
    with fitz.open(source) as document:
        seen_pages: set[int] = set()
        for page_entry in pages:
            if not isinstance(page_entry, Mapping):
                raise ValueError("foundation page is not an object")
            page_index = int(page_entry.get("page_index") or 0)
            if not 0 <= page_index < document.page_count or page_index in seen_pages:
                raise ValueError("foundation has an invalid or duplicate page_index")
            seen_pages.add(page_index)
            if list(page_entry.get("unexplained_candidate_ids") or []):
                raise ValueError("foundation has unexplained candidate IDs")
            blocks = page_entry.get("blocks")
            if not isinstance(blocks, list):
                raise ValueError("foundation page blocks is not a list")
            for block in blocks:
                if not isinstance(block, Mapping):
                    raise ValueError("foundation block is not an object")
                block_id = str(block.get("block_id") or "")
                if not block_id or block_id in seen_block_ids:
                    raise ValueError("foundation has a missing or duplicate block_id")
                seen_block_ids.add(block_id)
                classification = str(block.get("classification") or "")
                if classification not in counts:
                    raise ValueError(f"block {block_id} has invalid classification")
                counts[classification] += 1
                source_text = str(block.get("source_text") or "").strip()
                if not source_text:
                    raise ValueError(f"block {block_id} has no visible source_text")
                rotation = int(block.get("rotation") or 0)
                if rotation not in {0, 90, 180, 270}:
                    raise ValueError(f"block {block_id} has non-orthogonal rotation")
                bbox = _rect(block.get("source_bbox"), label=block_id, page=document[page_index])
                if classification == "manual_review":
                    raise ValueError(f"block {block_id} remains manual_review")
                if classification == "translated":
                    translation = str(block.get("translated_text") or "").strip()
                    if not _has_cjk(translation):
                        raise ValueError(f"block {block_id} lacks Chinese translation")
                    regions.append(
                        {
                            "region_id": block_id,
                            "page_index": page_index,
                            "source_text": source_text,
                            "translated_text": translation,
                            "bbox": bbox,
                            "rotation": rotation,
                            "placement": "reference",
                            "action": "translate",
                            "coverage_status": "translated",
                        }
                    )
        if seen_pages != set(range(document.page_count)):
            raise ValueError("foundation does not account for every source page")
    completion = foundation.get("completion") if isinstance(foundation.get("completion"), Mapping) else {}
    if float(completion.get("closure") or 0) != 1.0:
        raise ValueError("foundation closure is not 1.0")
    if counts["manual_review"]:
        raise ValueError("foundation has manual-review blocks")
    if not regions:
        raise ValueError("foundation has no translated blocks")
    return regions, counts


def _copy_with_map(*, source_pdf: Path, source_map: Path, target_pdf: Path, target_map: Path) -> None:
    if not source_pdf.is_file() or not source_map.is_file():
        raise ValueError("accepted reference PDF or map is missing")
    target_pdf.parent.mkdir(parents=True, exist_ok=True)
    target_map.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, target_pdf)
    shutil.copy2(source_map, target_map)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delivery-manifest", type=Path, required=True)
    parser.add_argument("--foundations-dir", type=Path, required=True)
    parser.add_argument("--duplicate-map", type=Path, required=True)
    parser.add_argument("--accepted-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--accepted-item", action="append", default=[])
    parser.add_argument("--only-item", action="append", default=[])
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--include-duplicates", action="store_true")
    parser.add_argument("--clean-stale-partials", action="store_true")
    parser.add_argument("--clean-legacy-root-accepted", action="store_true")
    args = parser.parse_args()

    delivery = json.loads(args.delivery_manifest.read_text(encoding="utf-8"))
    duplicate_map = json.loads(args.duplicate_map.read_text(encoding="utf-8"))
    source_root = Path(str(delivery.get("source_root") or ""))
    if not source_root.is_absolute():
        source_root = args.delivery_manifest.parent / source_root
    if not source_root.is_dir():
        raise SystemExit("delivery manifest source_root is unavailable")
    items = [item for item in delivery.get("items") or [] if isinstance(item, Mapping)]
    accepted_ids = set(args.accepted_item)
    item_by_id = {str(item.get("item_id") or ""): item for item in items}
    if len(item_by_id) != len(items) or not accepted_ids.issubset(item_by_id):
        raise SystemExit("delivery item identities or accepted items are invalid")
    selected_ids = set(args.only_item) if args.only_item else set(item_by_id)
    if not selected_ids.issubset(item_by_id):
        raise SystemExit("--only-item includes an item absent from delivery manifest")

    output_dir = args.output_dir
    audit_dir = output_dir / "_audit"
    report: dict[str, Any] = {
        "schema": "delivery-160-reference-render-report-v1",
        "canonical_rendered": 0,
        "accepted_reused": 0,
        "duplicate_reused": 0,
        "translated_blocks": 0,
        "literal_only_blocks": 0,
        "folders": {_CONSTRUCTION_FOLDER: 0, _SUBMISSION_FOLDER: 0},
        "failures": [],
        "stale_partials_removed": 0,
        "legacy_root_accepted_removed": 0,
    }
    canonical_outputs: dict[str, tuple[Path, Path, str]] = {}

    if args.clean_stale_partials:
        # Only remove our clearly-labelled, never-authoritative scratch PDFs
        # from the two requested delivery folders.  Final and audit PDFs are
        # deliberately outside this exact filename pattern.
        for category in (_CONSTRUCTION_FOLDER, _SUBMISSION_FOLDER):
            for stale in (output_dir / category).glob("*.partial.pdf"):
                stale.unlink(missing_ok=True)
                report["stale_partials_removed"] += 1

    for item in items:
        item_id = str(item.get("item_id") or "")
        if item_id not in selected_ids:
            continue
        category = _category(item)
        output_pdf = output_dir / category / _output_name(item)
        output_map = audit_dir / category / f"{output_pdf.stem}.reference-map.json"
        source = _source_path(item, source_root)
        expected_sha = str(item.get("content_hash") or "")
        try:
            if args.skip_existing and output_pdf.is_file() and output_map.is_file():
                canonical_outputs[item_id] = (output_pdf, output_map, category)
                report["folders"][category] += 1
                continue
            if not source.is_file() or _sha256(source) != expected_sha:
                raise ValueError("source PDF is absent or no longer matches manifest hash")
            if item_id in accepted_ids:
                accepted_pdf = args.accepted_dir / f"{item_id}-zh-reference.pdf"
                accepted_map = args.accepted_dir / f"{item_id}-zh-reference.reference-map.json"
                _copy_with_map(source_pdf=accepted_pdf, source_map=accepted_map, target_pdf=output_pdf, target_map=output_map)
                report["accepted_reused"] += 1
            else:
                foundation_path = args.foundations_dir / f"foundation-{item_id}.json"
                if not foundation_path.is_file():
                    raise ValueError("foundation JSON is missing")
                foundation = json.loads(foundation_path.read_text(encoding="utf-8"))
                if str(foundation.get("item_id") or "") != item_id:
                    raise ValueError("foundation item_id does not match manifest item")
                regions, counts = _foundation_regions(foundation, source=source, expected_sha=expected_sha)
                # Use a unique audit-side temporary path.  The desktop host or
                # PDF previewer can briefly retain a timed-out output handle;
                # reusing a visible delivery filename would turn that harmless
                # stale scratch file into a blocked retry.
                scratch_dir = audit_dir / ".scratch"
                scratch_dir.mkdir(parents=True, exist_ok=True)
                temporary_pdf = scratch_dir / f"{item_id}-{uuid.uuid4().hex}.pdf"
                result = render_bilingual_overlay(
                    source_pdf_path=source,
                    output_pdf_path=temporary_pdf,
                    regions=regions,
                    optimize=False,
                )
                temporary_map = temporary_pdf.with_suffix(".reference-map.json")
                if result.reference_items != len(regions) or not temporary_map.is_file():
                    raise ValueError("reference renderer did not close every translated block")
                output_pdf.unlink(missing_ok=True)
                temporary_pdf.replace(output_pdf)
                output_map.parent.mkdir(parents=True, exist_ok=True)
                output_map.unlink(missing_ok=True)
                temporary_map.replace(output_map)
                report["canonical_rendered"] += 1
                report["translated_blocks"] += counts["translated"]
                report["literal_only_blocks"] += counts["literal_only"]
            if not output_pdf.is_file() or output_pdf.stat().st_size == 0:
                raise ValueError("output PDF was not written")
            canonical_outputs[item_id] = (output_pdf, output_map, category)
            report["folders"][category] += 1
        except Exception as exc:  # Finish with a complete, machine-readable failure report.
            report["failures"].append({"item_id": item_id, "reason": str(exc)})

    raw_duplicates = duplicate_map.get("duplicate_map")
    if args.include_duplicates and not isinstance(raw_duplicates, Mapping):
        report["failures"].append({"item_id": "duplicate-map", "reason": "duplicate_map is not an object"})
    elif args.include_duplicates:
        # A duplicate pass may run after several bounded canonical shards. Read
        # the existing, already-verified canonical artifacts rather than making
        # the caller hold a long-lived Python process.
        for item in items:
            item_id = str(item.get("item_id") or "")
            if item_id in canonical_outputs:
                continue
            category = _category(item)
            output_pdf = output_dir / category / _output_name(item)
            output_map = audit_dir / category / f"{output_pdf.stem}.reference-map.json"
            if output_pdf.is_file() and output_map.is_file():
                canonical_outputs[item_id] = (output_pdf, output_map, category)
            else:
                report["failures"].append({"item_id": item_id, "reason": "canonical output is unavailable for duplicate reuse"})
        for duplicate_source, canonical_id_raw in raw_duplicates.items():
            canonical_id = str(canonical_id_raw)
            try:
                canonical_pdf, canonical_map, _canonical_category = canonical_outputs[canonical_id]
                category = _CONSTRUCTION_FOLDER if "CONSTRUCTION" in str(duplicate_source).upper() else _SUBMISSION_FOLDER
                duplicate_name = f"{Path(str(duplicate_source)).stem}-zh-reference.pdf"
                target_pdf = output_dir / category / duplicate_name
                target_map = audit_dir / category / f"{Path(duplicate_name).stem}.reference-map.json"
                _copy_with_map(source_pdf=canonical_pdf, source_map=canonical_map, target_pdf=target_pdf, target_map=target_map)
                report["duplicate_reused"] += 1
                report["folders"][category] += 1
            except Exception as exc:
                report["failures"].append({"item_id": "duplicate", "reason": str(exc)})

    report["pdf_total"] = sum(report["folders"].values())
    if args.clean_legacy_root_accepted:
        for item_id in accepted_ids:
            item = item_by_id[item_id]
            target_pdf = output_dir / _category(item) / _output_name(item)
            target_map = audit_dir / _category(item) / f"{target_pdf.stem}.reference-map.json"
            if not target_pdf.is_file() or not target_map.is_file():
                report["failures"].append({"item_id": item_id, "reason": "cannot remove legacy root copy before categorized output is verified"})
                continue
            for legacy in (
                output_dir / f"{item_id}-zh-reference.pdf",
                output_dir / f"{item_id}-zh-reference.reference-map.json",
            ):
                if legacy.is_file():
                    legacy.unlink()
                    report["legacy_root_accepted_removed"] += 1
    expected_count = len(selected_ids) + (int(duplicate_map.get("count") or 0) if args.include_duplicates else 0)
    report["passed"] = not report["failures"] and report["pdf_total"] == expected_count
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "reference-render-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("canonical_rendered", "accepted_reused", "duplicate_reused", "pdf_total", "folders", "passed")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
