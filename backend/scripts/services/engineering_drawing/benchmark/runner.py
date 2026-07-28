from __future__ import annotations

import json
import hashlib
import math
import re
import stat
from pathlib import Path
from typing import Any

import fitz

from services.engineering_drawing.visual_qa import analyze_visual_qa

from .prelabel import VISUAL_REVIEW_PROMPT_VERSION, VISUAL_REVIEW_SCHEMA
from .report import render_comparison, write_benchmark_report
from .schema import GoldSample, validate_gold_sample
from .scoring import promotion_decision, score_sample


_SAMPLE_ID = re.compile(r"(?:core|challenge)-[0-9]{2,3}")
_LOCK_KEYS = {
    "schema",
    "benchmark_version",
    "sample_count",
    "core_sample_count",
    "challenge_sample_count",
    "production_output_touched",
    "samples",
}
_RECORD_KEYS = {
    "sample_id",
    "set_name",
    "category",
    "relative_pdf",
    "page_number",
    "source_file_sha256",
    "source_sha256",
    "preview_sha256",
    "page_size",
    "page_rotation",
    "dpi",
    "goals",
    "status",
}
_VISUAL_REVIEW_KEYS = {
    "schema",
    "prompt_version",
    "sample_id",
    "model",
    "layout_association",
    "page_readability",
    "findings",
}
_FINDING_KEYS = {"code", "region_id", "reason"}


def _is_reparse_point(path: Path) -> bool:
    try:
        return bool(
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if _is_reparse_point(path) or not path.is_file():
        raise ValueError(f"{label} must be a regular JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must contain valid UTF-8 JSON") from error
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    return value


def _regular_directory(path: Path, label: str) -> Path:
    candidate = Path(path)
    if _is_reparse_point(candidate) or not candidate.is_dir():
        raise ValueError(f"{label} must be an existing regular directory")
    return candidate.resolve(strict=True)


def _child(root: Path, name: str, label: str) -> Path:
    target = root / name
    try:
        resolved = target.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{label} is missing") from error
    if (
        root not in resolved.parents
        or _is_reparse_point(target)
        or not resolved.is_file()
    ):
        raise ValueError(f"{label} must be a regular file inside its root")
    return resolved


def _finite_score(value: object, maximum: float, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= maximum
    ):
        raise ValueError(f"visual review {label} must be between 0 and {maximum:g}")
    return float(value)


def _visual_review(
    value: dict[str, Any],
    sample_id: str,
    candidate_region_ids: set[str],
) -> dict[str, Any]:
    if set(value) != _VISUAL_REVIEW_KEYS:
        raise ValueError("visual review must use the canonical closed schema")
    if (
        value["schema"] != VISUAL_REVIEW_SCHEMA
        or value["prompt_version"] != VISUAL_REVIEW_PROMPT_VERSION
        or value["sample_id"] != sample_id
        or type(value["model"]) is not str
        or not value["model"].strip()
    ):
        raise ValueError("visual review identity is invalid")
    layout = _finite_score(value["layout_association"], 20, "layout_association")
    readability = _finite_score(value["page_readability"], 15, "page_readability")
    findings = value["findings"]
    if type(findings) is not list:
        raise ValueError("visual review findings must be a list")
    for finding in findings:
        if type(finding) is not dict or set(finding) != _FINDING_KEYS:
            raise ValueError("visual review finding must use the canonical schema")
        if not all(type(finding[key]) is str and finding[key].strip() for key in _FINDING_KEYS):
            raise ValueError("visual review finding fields must be nonempty strings")
        if finding["region_id"] not in candidate_region_ids:
            raise ValueError("visual review finding region_id is not a candidate region")
    return {
        "layout_association": layout,
        "page_readability": readability,
        "findings": findings,
    }


def _manifest_records(lock: dict[str, Any]) -> list[dict[str, Any]]:
    if set(lock) != _LOCK_KEYS or lock.get("schema") != "engineering-drawing-benchmark-lock-v1":
        raise ValueError("manifest lock must use the canonical closed schema")
    if lock.get("production_output_touched") is not False:
        raise ValueError("manifest lock must preserve the production-output safety boundary")
    records = lock.get("samples")
    if type(records) is not list or not records:
        raise ValueError("manifest lock samples must be a nonempty list")
    seen: set[str] = set()
    for record in records:
        if type(record) is not dict or set(record) != _RECORD_KEYS:
            raise ValueError("manifest lock sample must use the canonical closed schema")
        sample_id = record.get("sample_id")
        if type(sample_id) is not str or not _SAMPLE_ID.fullmatch(sample_id):
            raise ValueError("manifest lock sample_id is invalid")
        if sample_id in seen:
            raise ValueError("manifest lock sample_id values must be unique")
        seen.add(sample_id)
        if record.get("set_name") not in {"core", "challenge"}:
            raise ValueError("manifest lock set_name is invalid")
        if type(record.get("category")) is not str or not record["category"].strip():
            raise ValueError("manifest lock category is invalid")
        if (
            record.get("status") != "candidate"
            or type(record.get("page_number")) is not int
            or record["page_number"] < 1
            or type(record.get("dpi")) is not int
            or not 36 <= record["dpi"] <= 300
        ):
            raise ValueError("manifest lock sample metadata is invalid")
        if any(
            type(record.get(field)) is not str
            or re.fullmatch(r"[0-9a-f]{64}", record[field]) is None
            for field in ("source_file_sha256", "source_sha256", "preview_sha256")
        ):
            raise ValueError("manifest lock sample hashes are invalid")
    core_count = sum(record["set_name"] == "core" for record in records)
    challenge_count = len(records) - core_count
    expected = (len(records), core_count, challenge_count)
    actual = (
        lock.get("sample_count"),
        lock.get("core_sample_count"),
        lock.get("challenge_sample_count"),
    )
    if actual != expected:
        raise ValueError("manifest lock sample counts are inconsistent")
    return records


def _pdf_diagnostics(candidate_pdf: Path, source_pdf: Path, placements: list[dict]) -> dict:
    try:
        with fitz.open(candidate_pdf) as document, fitz.open(source_pdf) as source:
            if document.page_count < 1 or source.page_count < 1:
                raise ValueError("benchmark PDFs must contain at least one page")
            text = "\n".join(page.get_text() for page in document)
            geometry_equal = document.page_count == source.page_count and all(
                abs(document[index].rect.width - source[index].rect.width) <= 0.5
                and abs(document[index].rect.height - source[index].rect.height) <= 0.5
                for index in range(source.page_count)
            )
    except (fitz.FileDataError, RuntimeError) as error:
        raise ValueError("benchmark candidate and source must be readable PDFs") from error
    rejected = sum(
        type(item) is dict and str(item.get("status", "")).startswith("rejected")
        for item in placements
    )
    return {
        "replacement_characters": text.count("\ufffd"),
        "private_use_characters": sum("\ue000" <= char <= "\uf8ff" for char in text),
        "clipped_or_outside_count": (0 if geometry_equal else 1) + rejected,
    }


def _preflight(workspace: Path, candidate_root: Path) -> list[dict[str, Any]]:
    lock = _read_json(workspace / "manifest.lock.json", "manifest lock")
    records = _manifest_records(lock)
    prepared = []
    for record in records:
        sample_id = record["sample_id"]
        sample_dir = workspace / "samples" / sample_id
        if _is_reparse_point(sample_dir) or not sample_dir.is_dir():
            raise ValueError(f"sample directory is invalid for {sample_id}")
        resolved_sample = sample_dir.resolve(strict=True)
        if workspace not in resolved_sample.parents:
            raise ValueError(f"sample directory escapes workspace for {sample_id}")
        source_pdf = _child(resolved_sample, "source.pdf", f"{sample_id} source PDF")
        if _sha256(source_pdf) != record["source_sha256"]:
            raise ValueError(f"{sample_id} frozen source hash does not match manifest lock")
        gold_payload = _read_json(
            _child(resolved_sample, "gold.locked.json", f"{sample_id} locked gold"),
            f"{sample_id} locked gold",
        )
        try:
            gold = GoldSample.from_dict(gold_payload)
            validate_gold_sample(gold)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{sample_id} locked gold is invalid") from error
        if gold.sample_id != sample_id or gold.status != "locked":
            raise ValueError(f"{sample_id} locked gold identity or status is invalid")

        candidate_pdf = _child(candidate_root, f"{sample_id}.pdf", f"{sample_id} candidate PDF")
        regions_payload = _read_json(
            _child(
                candidate_root,
                f"{sample_id}.regions.json",
                f"{sample_id} candidate regions",
            ),
            f"{sample_id} candidate regions",
        )
        if set(regions_payload) != {"regions"} or type(regions_payload["regions"]) is not list:
            raise ValueError(f"{sample_id} candidate regions must use the closed schema")
        candidate_regions = regions_payload["regions"]
        region_ids = {
            str(item.get("block_id") or item.get("region_id"))
            for item in candidate_regions
            if type(item) is dict and item.get("block_id") or type(item) is dict and item.get("region_id")
        }
        placement_path = _child(
            candidate_root,
            f"{sample_id}.inline-placement.json",
            f"{sample_id} placement audit",
        )
        placement_payload = _read_json(placement_path, f"{sample_id} placement audit")
        if set(placement_payload) != {"placements"} or type(placement_payload["placements"]) is not list:
            raise ValueError(f"{sample_id} placement audit must use the closed schema")
        subjective = _visual_review(
            _read_json(
                _child(
                    candidate_root,
                    f"{sample_id}.subjective.json",
                    f"{sample_id} visual review",
                ),
                f"{sample_id} visual review",
            ),
            sample_id,
            region_ids,
        )
        prepared.append(
            {
                "record": record,
                "sample_dir": resolved_sample,
                "source_pdf": source_pdf,
                "gold": gold.to_dict(),
                "candidate_pdf": candidate_pdf,
                "candidate_regions": candidate_regions,
                "placement_path": placement_path,
                "placements": placement_payload["placements"],
                "subjective": subjective,
            }
        )
    return prepared


def evaluate_workspace(
    workspace: Path,
    candidate_root: Path,
    baseline_report: Path | None = None,
) -> dict:
    """Evaluate frozen candidates without writing any translated delivery PDF."""
    workspace_path = _regular_directory(workspace, "workspace")
    candidate_path = _regular_directory(candidate_root, "candidate_root")
    prepared = _preflight(workspace_path, candidate_path)

    samples: list[dict[str, Any]] = []
    for item in prepared:
        visual = analyze_visual_qa(
            output_pdf_path=item["candidate_pdf"],
            placement_audit_path=item["placement_path"],
        )
        diagnostics = _pdf_diagnostics(
            item["candidate_pdf"], item["source_pdf"], item["placements"]
        )
        scored = score_sample(
            gold_blocks=item["gold"]["blocks"],
            candidate_blocks=item["candidate_regions"],
            visual_qa=visual,
            pdf_diagnostics=diagnostics,
            subjective=item["subjective"],
        )
        samples.append(
            {
                "sample_id": item["record"]["sample_id"],
                "set_name": item["record"]["set_name"],
                "category": item["record"]["category"],
                "comparison_png": (
                    f"comparisons/{item['record']['sample_id']}.png"
                ),
                **scored,
            }
        )

    comparison_root = workspace_path / "comparisons"
    if _is_reparse_point(comparison_root):
        raise ValueError("workspace comparisons must be a regular directory")
    comparison_root.mkdir(parents=True, exist_ok=True)
    resolved_comparisons = comparison_root.resolve(strict=True)
    if (
        not resolved_comparisons.is_dir()
        or workspace_path not in resolved_comparisons.parents
    ):
        raise ValueError("workspace comparisons must stay inside workspace")
    for item, scored in zip(prepared, samples, strict=True):
        gold_by_id = {
            block["block_id"]: block for block in item["gold"]["blocks"]
        }
        candidate_by_id = {
            str(block.get("block_id") or block.get("region_id")): block
            for block in item["candidate_regions"]
            if type(block) is dict
        }
        markers = []
        for failure in scored["hard_failures"]:
            block_id = failure.get("block_id")
            if not block_id or block_id not in gold_by_id:
                continue
            candidate_bbox = candidate_by_id.get(block_id, {}).get("target_bbox")
            markers.append(
                {
                    "side": "candidate",
                    "bbox": candidate_bbox or gold_by_id[block_id]["source_bbox"],
                    "code": failure["code"],
                }
            )
        render_comparison(
            item["source_pdf"],
            item["candidate_pdf"],
            comparison_root / f"{item['record']['sample_id']}.png",
            markers,
        )

    core_items = [item for item in samples if item["set_name"] == "core"]
    challenge_items = [item for item in samples if item["set_name"] == "challenge"]
    all_gold_blocks = [
        block for item in prepared for block in item["gold"]["blocks"]
    ]
    manual_count = sum(
        block["manual_review_required"] for block in all_gold_blocks
    )
    block_count = max(1, len(all_gold_blocks))
    summary: dict[str, Any] = {
        "schema": "engineering-drawing-benchmark-report-v1",
        "samples": samples,
        "core_score": sum(item["score"] for item in core_items)
        / max(1, len(core_items)),
        "hard_failure_count": sum(item["hard_failure_count"] for item in samples),
        "manual_review_rate": manual_count / block_count,
        "automation_rate": (len(all_gold_blocks) - manual_count) / block_count,
        "category_scores": {
            category: sum(
                item["score"] for item in core_items if item["category"] == category
            )
            / sum(1 for item in core_items if item["category"] == category)
            for category in sorted({item["category"] for item in core_items})
        },
        "challenge_pass_rate": (
            sum(item["passed"] for item in challenge_items) / len(challenge_items)
            if challenge_items
            else 1.0
        ),
        "challenge_sample_count": len(challenge_items),
    }
    if baseline_report is not None:
        summary["promotion"] = promotion_decision(
            _read_json(Path(baseline_report), "baseline report"), summary
        )
    write_benchmark_report(summary, workspace_path)
    return summary
