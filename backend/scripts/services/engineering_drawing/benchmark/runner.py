from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Any

import fitz

from .prelabel import VISUAL_REVIEW_PROMPT_VERSION, VISUAL_REVIEW_SCHEMA
from .report import _validated_summary, render_comparison, write_benchmark_report
from .schema import (
    GoldSample,
    validate_gold_sample,
    validate_manifest_sample_fields,
)
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
_EVIDENCE_KEYS = {
    "schema",
    "sample_id",
    "benchmark_version",
    "manifest_record_sha256",
    "source_sha256",
    "preview_sha256",
    "locked_gold_sha256",
    "candidate_sha256",
    "candidate_page",
    "regions_sha256",
    "placement_sha256",
    "subjective_sha256",
}
_ROTATIONS = {0, 90, 180, 270}
def _is_reparse_point(path: Path) -> bool:
    try:
        return bool(
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    except OSError:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
    if (
        type(lock.get("benchmark_version")) is not str
        or not lock["benchmark_version"].strip()
        or len(lock["benchmark_version"]) > 128
    ):
        raise ValueError("manifest lock benchmark_version is invalid")
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
        if not sample_id.startswith(f"{record['set_name']}-"):
            raise ValueError("manifest lock sample_id does not match set_name")
        if (
            type(record.get("category")) is not str
            or not record["category"].strip()
            or record["category"] != record["category"].strip()
            or len(record["category"]) > 256
        ):
            raise ValueError("manifest lock category is invalid")
        try:
            validate_manifest_sample_fields(
                sample_id=sample_id,
                category=record.get("category"),
                relative_pdf=record.get("relative_pdf"),
                page_number=record.get("page_number"),
                goals=record.get("goals"),
                set_name=record["set_name"],
            )
        except ValueError as error:
            raise ValueError(f"manifest lock sample metadata: {error}") from error
        page_size = record.get("page_size")
        if (
            type(page_size) is not list
            or len(page_size) != 2
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value <= 0
                for value in page_size
            )
        ):
            raise ValueError("manifest lock page_size is invalid")
        if (
            type(record.get("page_rotation")) is not int
            or record["page_rotation"] not in _ROTATIONS
        ):
            raise ValueError("manifest lock page_rotation is invalid")
        if (
            record.get("status") != "candidate"
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
    if any(type(value) is not int for value in actual) or actual != expected:
        raise ValueError("manifest lock sample counts are inconsistent")
    return records


def validated_sample_context(workspace: Path, sample_id: str) -> dict[str, Any]:
    """Validate one frozen manifest member and return its immutable paths."""
    if type(sample_id) is not str or _SAMPLE_ID.fullmatch(sample_id) is None:
        raise ValueError("benchmark sample_id is invalid")
    workspace_path = _regular_directory(workspace, "workspace")
    lock = _read_json(workspace_path / "manifest.lock.json", "manifest lock")
    records = _manifest_records(lock)
    record = next(
        (item for item in records if item["sample_id"] == sample_id),
        None,
    )
    if record is None:
        raise ValueError("benchmark sample is not a manifest member")
    sample_dir = workspace_path / "samples" / sample_id
    if _is_reparse_point(sample_dir) or not sample_dir.is_dir():
        raise ValueError(f"sample directory is invalid for {sample_id}")
    resolved_sample = sample_dir.resolve(strict=True)
    if workspace_path not in resolved_sample.parents:
        raise ValueError(f"sample directory escapes workspace for {sample_id}")
    source_pdf = _child(resolved_sample, "source.pdf", f"{sample_id} source PDF")
    source_png = _child(
        resolved_sample, "source.png", f"{sample_id} source preview"
    )
    sample_json = _read_json(
        _child(
            resolved_sample, "sample.json", f"{sample_id} sample metadata"
        ),
        f"{sample_id} sample metadata",
    )
    if sample_json != record:
        raise ValueError(
            f"{sample_id} sample metadata does not match manifest lock"
        )
    if sha256_file(source_pdf) != record["source_sha256"]:
        raise ValueError(
            f"{sample_id} frozen source hash does not match manifest lock"
        )
    if sha256_file(source_png) != record["preview_sha256"]:
        raise ValueError(
            f"{sample_id} preview hash does not match manifest lock"
        )
    try:
        with fitz.open(source_pdf) as document:
            if document.page_count != 1:
                raise ValueError(f"{sample_id} frozen source must be one page")
            page = document[0]
            actual_size = (float(page.rect.width), float(page.rect.height))
            actual_rotation = page.rotation
    except (fitz.FileDataError, RuntimeError) as error:
        raise ValueError(f"{sample_id} frozen source PDF is invalid") from error
    if any(
        abs(actual - float(expected)) > 0.01
        for actual, expected in zip(actual_size, record["page_size"], strict=True)
    ):
        raise ValueError(f"{sample_id} page_size does not match frozen PDF")
    if actual_rotation != record["page_rotation"]:
        raise ValueError(f"{sample_id} page_rotation does not match frozen PDF")
    return {
        "workspace": workspace_path,
        "benchmark_version": lock["benchmark_version"],
        "record": record,
        "sample_dir": resolved_sample,
        "source_pdf": source_pdf,
        "source_png": source_png,
    }


def validate_page_identity(
    page: object,
    record: dict[str, Any],
    *,
    label: str,
) -> None:
    if type(page) is not dict or set(page) != {"width", "height", "rotation"}:
        raise ValueError(f"{label} page must use the closed page schema")
    for index, field in enumerate(("width", "height")):
        value = page[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or abs(float(value) - float(record["page_size"][index])) > 0.01
        ):
            raise ValueError(f"{label} page size does not match frozen source")
    if (
        type(page["rotation"]) is not int
        or page["rotation"] != record["page_rotation"]
    ):
        raise ValueError(f"{label} page rotation does not match frozen source")


def validate_candidate_pdf_identity(
    candidate_pdf: Path,
    source_pdf: Path,
    record: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    """Require one page with byte-independent but exact frozen page geometry."""
    try:
        with fitz.open(candidate_pdf) as candidate, fitz.open(source_pdf) as source:
            if candidate.page_count != 1 or source.page_count != 1:
                raise ValueError(f"{label} must contain exactly one page")
            candidate_page = candidate[0]
            source_page = source[0]
            identity = {
                "width": float(candidate_page.rect.width),
                "height": float(candidate_page.rect.height),
                "rotation": candidate_page.rotation,
                "mediabox": [float(value) for value in candidate_page.mediabox],
                "cropbox": [float(value) for value in candidate_page.cropbox],
            }
            source_mediabox = [
                float(value) for value in source_page.mediabox
            ]
            source_cropbox = [float(value) for value in source_page.cropbox]
    except (fitz.FileDataError, RuntimeError) as error:
        raise ValueError(f"{label} must be a readable PDF") from error
    if (
        identity["width"] != float(record["page_size"][0])
        or identity["height"] != float(record["page_size"][1])
    ):
        raise ValueError(f"{label} page dimensions do not match frozen source")
    if identity["rotation"] != record["page_rotation"]:
        raise ValueError(f"{label} page rotation does not match frozen source")
    if identity["mediabox"] != source_mediabox:
        raise ValueError(f"{label} mediabox does not match frozen source")
    if identity["cropbox"] != source_cropbox:
        raise ValueError(f"{label} cropbox does not match frozen source")
    return identity


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


def _fold_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _rect_value(value: object, label: str) -> tuple[float, float, float, float]:
    if (
        type(value) is not list
        or len(value) != 4
        or any(
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(float(number))
            for number in value
        )
    ):
        raise ValueError(f"{label} must be a finite rectangle")
    rect = tuple(float(number) for number in value)
    if rect[2] <= rect[0] or rect[3] <= rect[1]:
        raise ValueError(f"{label} must be nonempty")
    return rect


def _intersects(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])


def _intersection_area(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0.0, min(left[3], right[3]) - max(left[1], right[1])
    )


def _visible_translation_text(
    page: fitz.Page,
    translated_text: str,
    target: tuple[float, float, float, float],
) -> list[tuple[tuple[float, float, float, float], int]]:
    visible_chars: list[
        tuple[str, tuple[float, float, float, float], int]
    ] = []
    for span in page.get_texttrace():
        color = span.get("color")
        white = (
            isinstance(color, int)
            and color & 0xFFFFFF == 0xFFFFFF
        ) or (
            isinstance(color, (list, tuple))
            and bool(color)
            and all(float(component) >= 0.98 for component in color)
        )
        if (
            span.get("type") == 3
            or float(span.get("opacity", 1.0)) <= 0.01
            or white
        ):
            continue
        for raw in span.get("chars", ()):
            if len(raw) < 4:
                continue
            codepoint = raw[0]
            bbox = tuple(float(value) for value in raw[3])
            area = max(0.0, bbox[2] - bbox[0]) * max(
                0.0, bbox[3] - bbox[1]
            )
            if area <= 0 or _intersection_area(bbox, target) / area < 0.5:
                continue
            try:
                visible_chars.append(
                    (chr(codepoint), bbox, int(span.get("seqno", -1)))
                )
            except (TypeError, ValueError):
                continue
    expected = _fold_text(translated_text)
    compact = _fold_text("".join(char for char, _bbox, _seqno in visible_chars))
    start = compact.find(expected)
    if start < 0:
        return []
    # Engineering translations are predominantly CJK and whitespace folding
    # does not change their character count.
    return [
        (bbox, seqno)
        for _char, bbox, seqno in visible_chars[start : start + len(expected)]
    ]


def _later_opaque_coverage(
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
    text_seqno: int,
) -> float:
    """Measure the union of later paint coverage, including tiled objects.

    A single-object intersection test is insufficient because a white image or
    path can be split into several tiles. Sampling the union on a fixed grid is
    deterministic and deliberately conservative for a hard visibility gate.
    """
    later_boxes: list[tuple[float, float, float, float]] = []
    for seqno, item in enumerate(page.get_bboxlog()):
        if seqno <= text_seqno or len(item) < 2:
            continue
        paint_type = str(item[0])
        if paint_type not in {
            "fill-image",
            "fill-path",
            "fill-shade",
            "fill-text",
            "stroke-path",
            "stroke-text",
        }:
            continue
        try:
            paint_bbox = tuple(float(value) for value in item[1])
        except (TypeError, ValueError):
            continue
        if len(paint_bbox) == 4 and _intersection_area(bbox, paint_bbox) > 0:
            later_boxes.append(paint_bbox)
    for drawing in page.get_drawings():
        if (
            int(drawing.get("seqno", -1)) <= text_seqno
            or drawing.get("fill") is None
            or float(drawing.get("fill_opacity", 1.0)) < 0.99
        ):
            continue
        try:
            drawing_rect = tuple(float(value) for value in drawing["rect"])
        except (KeyError, TypeError, ValueError):
            continue
        if len(drawing_rect) == 4 and _intersection_area(bbox, drawing_rect) > 0:
            later_boxes.append(drawing_rect)

    if not later_boxes:
        return 0.0
    covered = 0
    grid_size = 16
    for row in range(grid_size):
        y = bbox[1] + (row + 0.5) * (bbox[3] - bbox[1]) / grid_size
        for column in range(grid_size):
            x = bbox[0] + (column + 0.5) * (bbox[2] - bbox[0]) / grid_size
            if any(
                paint[0] <= x <= paint[2] and paint[1] <= y <= paint[3]
                for paint in later_boxes
            ):
                covered += 1
    return covered / (grid_size * grid_size)


def _later_opaque_overpaint(
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
    text_seqno: int,
) -> bool:
    return _later_opaque_coverage(page, bbox, text_seqno) >= 0.5


def _region_raster_signal(
    source_page: fitz.Page,
    candidate_page: fitz.Page,
    glyphs: list[tuple[tuple[float, float, float, float], int]],
) -> bool:
    matrix = fitz.Matrix(2, 2)
    source = source_page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csGRAY)
    candidate = candidate_page.get_pixmap(
        matrix=matrix, alpha=False, colorspace=fitz.csGRAY
    )
    if source.width != candidate.width or source.height != candidate.height:
        return False
    source_bytes = source.samples
    candidate_bytes = candidate.samples
    visible_glyphs = 0
    for bbox, text_seqno in glyphs:
        if _later_opaque_overpaint(candidate_page, bbox, text_seqno):
            continue
        x0 = max(0, min(source.width, math.floor(bbox[0] * 2)))
        y0 = max(0, min(source.height, math.floor(bbox[1] * 2)))
        x1 = max(0, min(source.width, math.ceil(bbox[2] * 2)))
        y1 = max(0, min(source.height, math.ceil(bbox[3] * 2)))
        darker_points: list[tuple[int, int]] = []
        for y in range(y0, y1):
            row = y * source.stride
            for x in range(x0, x1):
                offset = row + x
                if candidate_bytes[offset] <= source_bytes[offset] - 12:
                    darker_points.append((x, y))
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        if not darker_points:
            continue
        ink_width = max(x for x, _y in darker_points) - min(
            x for x, _y in darker_points
        ) + 1
        ink_height = max(y for _x, y in darker_points) - min(
            y for _x, y in darker_points
        ) + 1
        if (
            len(darker_points) >= max(3, math.ceil(width * height * 0.015))
            and ink_width >= math.ceil(width * 0.25)
            and ink_height >= math.ceil(height * 0.25)
        ):
            visible_glyphs += 1
    return bool(glyphs) and visible_glyphs >= math.ceil(
        len(glyphs) * 0.75
    )


def _point_in_rect(point: tuple[float, float], rect: tuple[float, ...]) -> bool:
    return rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]


def _segment_hits_rect(
    start: tuple[float, float],
    end: tuple[float, float],
    rect: tuple[float, ...],
) -> bool:
    if start[0] == end[0]:
        return rect[0] <= start[0] <= rect[2] and max(
            min(start[1], end[1]), rect[1]
        ) <= min(max(start[1], end[1]), rect[3])
    return rect[1] <= start[1] <= rect[3] and max(
        min(start[0], end[0]), rect[0]
    ) <= min(max(start[0], end[0]), rect[2])


_LEADER_ANCHOR_TOLERANCE = 0.05  # points; endpoint contact only, never traversal


def _segment_only_touches_rect_at_anchor(
    segment: tuple[tuple[float, float], tuple[float, float]],
    rect: tuple[float, ...],
    anchor: tuple[float, float],
) -> bool:
    start, end = segment
    if not (
        math.dist(start, anchor) <= _LEADER_ANCHOR_TOLERANCE
        or math.dist(end, anchor) <= _LEADER_ANCHOR_TOLERANCE
    ):
        return False
    on_boundary = (
        abs(anchor[0] - rect[0]) <= _LEADER_ANCHOR_TOLERANCE
        or abs(anchor[0] - rect[2]) <= _LEADER_ANCHOR_TOLERANCE
        or abs(anchor[1] - rect[1]) <= _LEADER_ANCHOR_TOLERANCE
        or abs(anchor[1] - rect[3]) <= _LEADER_ANCHOR_TOLERANCE
    )
    if not on_boundary:
        return False
    if start[0] == end[0]:
        if not rect[0] <= start[0] <= rect[2]:
            return False
        low = max(min(start[1], end[1]), rect[1])
        high = min(max(start[1], end[1]), rect[3])
        return high - low <= _LEADER_ANCHOR_TOLERANCE
    if not rect[1] <= start[1] <= rect[3]:
        return False
    low = max(min(start[0], end[0]), rect[0])
    high = min(max(start[0], end[0]), rect[2])
    return high - low <= _LEADER_ANCHOR_TOLERANCE


def _segments_cross(
    left: tuple[tuple[float, float], tuple[float, float]],
    right: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    (ax, ay), (bx, by) = left
    (cx, cy), (dx, dy) = right
    left_vertical = ax == bx
    right_vertical = cx == dx
    if left_vertical and right_vertical:
        return ax == cx and max(min(ay, by), min(cy, dy)) <= min(
            max(ay, by), max(cy, dy)
        )
    if not left_vertical and not right_vertical:
        return ay == cy and max(min(ax, bx), min(cx, dx)) <= min(
            max(ax, bx), max(cx, dx)
        )
    vertical = left if left_vertical else right
    horizontal = right if left_vertical else left
    vx = vertical[0][0]
    hy = horizontal[0][1]
    return (
        min(vertical[0][1], vertical[1][1])
        <= hy
        <= max(vertical[0][1], vertical[1][1])
        and min(horizontal[0][0], horizontal[1][0])
        <= vx
        <= max(horizontal[0][0], horizontal[1][0])
    )


def _leader_segments(
    leader: object,
    *,
    page: tuple[float, float, float, float],
    source: tuple[float, ...],
    target: tuple[float, ...],
    label: str,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    if type(leader) is not dict or set(leader) != {"status", "path"}:
        raise ValueError(f"{label} leader must use the closed placement schema")
    status = leader["status"]
    path = leader["path"]
    if status == "not_needed":
        if path != []:
            raise ValueError(f"{label} unused leader path must be empty")
        return []
    if status != "drawn" or type(path) is not list or len(path) < 2:
        raise ValueError(f"{label} drawn leader requires a path")
    points = []
    for raw in path:
        if (
            type(raw) is not list
            or len(raw) != 2
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in raw
            )
        ):
            raise ValueError(f"{label} leader path point is invalid")
        point = (float(raw[0]), float(raw[1]))
        if not _point_in_rect(point, page):
            raise ValueError(f"{label} leader path leaves the page")
        points.append(point)
    if not (
        (_point_in_rect(points[0], source) and _point_in_rect(points[-1], target))
        or (
            _point_in_rect(points[-1], source)
            and _point_in_rect(points[0], target)
        )
    ):
        raise ValueError(f"{label} leader endpoints must bind source and target")
    segments = []
    for start, end in zip(points, points[1:]):
        if start == end or (start[0] != end[0] and start[1] != end[1]):
            raise ValueError(f"{label} leader path must be nonzero orthogonal segments")
        segments.append((start, end))
    return segments


def _bound_visual_evidence(
    *,
    sample_id: str,
    benchmark_version: str,
    record: dict[str, Any],
    source_pdf: Path,
    source_png: Path,
    locked_gold_path: Path,
    candidate_pdf: Path,
    regions_path: Path,
    placement_path: Path,
    subjective_path: Path,
    evidence: dict[str, Any],
) -> None:
    if (
        set(evidence) != _EVIDENCE_KEYS
        or evidence.get("schema") != "engineering-drawing-candidate-evidence-v1"
        or evidence.get("sample_id") != sample_id
    ):
        raise ValueError(f"{sample_id} candidate evidence is invalid")
    expected = {
        "benchmark_version": benchmark_version,
        "manifest_record_sha256": canonical_digest(record),
        "source_sha256": sha256_file(source_pdf),
        "preview_sha256": sha256_file(source_png),
        "locked_gold_sha256": sha256_file(locked_gold_path),
        "candidate_sha256": sha256_file(candidate_pdf),
        "candidate_page": validate_candidate_pdf_identity(
            candidate_pdf,
            source_pdf,
            record,
            label=f"{sample_id} evidence candidate page",
        ),
        "regions_sha256": sha256_file(regions_path),
        "placement_sha256": sha256_file(placement_path),
        "subjective_sha256": sha256_file(subjective_path),
    }
    if any(evidence.get(field) != digest for field, digest in expected.items()):
        raise ValueError(f"{sample_id} candidate evidence hash mismatch")


def _candidate_visual_qa(
    *,
    candidate_pdf: Path,
    source_pdf: Path,
    gold_blocks: list[dict],
    candidate_regions: list[dict],
    placements: list[dict],
) -> dict[str, Any]:
    gold_by_id = {block["block_id"]: block for block in gold_blocks}
    candidate_by_id: dict[str, dict] = {}
    for index, item in enumerate(candidate_regions):
        if type(item) is not dict:
            raise ValueError(f"candidate region {index} must be an object")
        region_id = item.get("block_id") or item.get("region_id")
        if type(region_id) is not str or not region_id.strip():
            raise ValueError(f"candidate region {index} has an invalid ID")
        if region_id in candidate_by_id:
            raise ValueError(f"duplicate candidate region ID: {region_id}")
        candidate_by_id[region_id] = item
    placement_by_id: dict[str, dict] = {}
    for index, item in enumerate(placements):
        if type(item) is not dict:
            raise ValueError(f"placement {index} must be an object")
        region_id = item.get("region_id")
        if type(region_id) is not str or region_id in placement_by_id:
            raise ValueError(f"placement {index} has an invalid or duplicate ID")
        placement_by_id[region_id] = item
    if set(candidate_by_id) != set(placement_by_id):
        raise ValueError("candidate regions and placements must have identical IDs")

    target_rects = []
    for region_id, candidate in candidate_by_id.items():
        placement = placement_by_id[region_id]
        gold = gold_by_id.get(region_id)
        if gold is None:
            raise ValueError(f"candidate region is absent from locked gold: {region_id}")
        if (
            candidate.get("translated_text") != placement.get("translated_text")
            or candidate.get("target_bbox") != placement.get("target_bbox")
            or placement.get("source_bbox") != gold.get("source_bbox")
            or placement.get("page_index") != 0
        ):
            raise ValueError(f"candidate placement evidence mismatch: {region_id}")
        target_rects.append(
            (region_id, _rect_value(candidate.get("target_bbox"), "target_bbox"))
        )

    try:
        with fitz.open(candidate_pdf) as candidate_document, fitz.open(
            source_pdf
        ) as source_document:
            if (
                candidate_document.page_count != 1
                or source_document.page_count != 1
            ):
                raise ValueError("benchmark frozen and candidate PDFs must be one page")
            candidate_document[0].get_pixmap(dpi=72, alpha=False)
            source_document[0].get_pixmap(dpi=72, alpha=False)
            actual_size = (
                candidate_document[0].rect.width,
                candidate_document[0].rect.height,
            )
            target_by_id = dict(target_rects)
            visible_presence = {}
            for region_id, candidate in candidate_by_id.items():
                glyph_bboxes = _visible_translation_text(
                        candidate_document[0],
                        str(candidate["translated_text"]),
                        target_by_id[region_id],
                    )
                visible_presence[region_id] = bool(glyph_bboxes) and _region_raster_signal(
                        source_document[0],
                        candidate_document[0],
                        glyph_bboxes,
                    )
    except (fitz.FileDataError, RuntimeError) as error:
        raise ValueError("benchmark candidate must be a renderable PDF") from error

    missing_region_ids = []
    for region_id, candidate in candidate_by_id.items():
        translated = _fold_text(candidate.get("translated_text"))
        placement = placement_by_id[region_id]
        if (
            not translated
            or not visible_presence[region_id]
            or str(placement.get("status", "")).startswith("rejected")
            or placement.get("coverage_status") in {"missing", "low_confidence"}
        ):
            missing_region_ids.append(region_id)
    overlap_ids = set()
    for index, (region_id, rect) in enumerate(target_rects):
        for other_id, other_rect in target_rects[index + 1 :]:
            if _intersects(rect, other_rect):
                overlap_ids.update((region_id, other_id))
    page_rect = (0.0, 0.0, float(actual_size[0]), float(actual_size[1]))
    leader_segments: dict[
        str, list[tuple[tuple[float, float], tuple[float, float]]]
    ] = {}
    for region_id, placement in placement_by_id.items():
        leader_segments[region_id] = _leader_segments(
            placement.get("leader"),
            page=page_rect,
            source=_rect_value(gold_by_id[region_id]["source_bbox"], "source_bbox"),
            target=dict(target_rects)[region_id],
            label=region_id,
        )
    obstacles = [
        (
            block_id,
            _rect_value(block["source_bbox"], "source_bbox"),
            "source",
        )
        for block_id, block in gold_by_id.items()
    ]
    obstacles.extend(
        (
            block_id,
            _rect_value(rect, "forbidden_zone"),
            "forbidden",
        )
        for block_id, block in gold_by_id.items()
        for rect in block["forbidden_zones"]
    )
    obstacles.extend(
        (region_id, rect, "target") for region_id, rect in target_rects
    )
    leader_collision_ids = set()
    for region_id, segments in leader_segments.items():
        own_source = _rect_value(
            gold_by_id[region_id]["source_bbox"], "source_bbox"
        )
        own_target = dict(target_rects)[region_id]
        endpoint_anchors = (
            [segments[0][0], segments[-1][1]] if segments else []
        )
        for segment in segments:
            for owner, obstacle, _kind in obstacles:
                if not _segment_hits_rect(*segment, obstacle):
                    continue
                own_bbox = owner == region_id and (
                    obstacle == own_source or obstacle == own_target
                )
                if own_bbox and any(
                    _point_in_rect(anchor, obstacle)
                    and _segment_only_touches_rect_at_anchor(
                        segment, obstacle, anchor
                    )
                    for anchor in endpoint_anchors
                ):
                    continue
                leader_collision_ids.add(region_id)
    flattened = [
        (region_id, segment)
        for region_id, segments in leader_segments.items()
        for segment in segments
    ]
    for index, (region_id, segment) in enumerate(flattened):
        for other_id, other_segment in flattened[index + 1 :]:
            if region_id != other_id and _segments_cross(segment, other_segment):
                leader_collision_ids.update((region_id, other_id))
    return {
        "visual_overlap_count": len(overlap_ids),
        "leader_collision_count": len(leader_collision_ids),
        "untranslated_candidate_count": len(missing_region_ids),
        "missing_region_ids": sorted(missing_region_ids),
    }


def _promotion_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    identities = sorted(
        f"{sample['sample_id']}/{identity}"
        for sample in value["samples"]
        for identity in sample["hard_failure_ids"]
    )
    return {
        "core_score": value["core_score"],
        "hard_failure_count": len(identities),
        "hard_failure_ids": identities,
        "manual_review_rate": value["manual_review_rate"],
        "category_scores": value["category_scores"],
        "challenge_pass_rate": value["challenge_pass_rate"],
    }


def _sample_universe(value: dict[str, Any]) -> list[tuple[str, str, str]]:
    return sorted(
        (
            sample["sample_id"],
            sample["set_name"],
            sample["category"],
        )
        for sample in value["samples"]
    )


def _baseline_summary(
    path: Path,
    *,
    benchmark_version: str,
    manifest_digest: str,
    universe: list[tuple[str, str, str]],
) -> dict[str, Any]:
    value = _read_json(Path(path), "baseline report")
    baseline_workspace = Path(path).resolve(strict=True).parent.parent
    try:
        _validated_summary(value, baseline_workspace)
    except ValueError as error:
        raise ValueError("baseline report is invalid") from error
    if (
        value.get("benchmark_version") != benchmark_version
        or value.get("manifest_digest") != manifest_digest
        or _sample_universe(value) != universe
    ):
        raise ValueError("baseline report does not match the current manifest universe")
    snapshot = _promotion_snapshot(value)
    decision = promotion_decision(snapshot, snapshot)
    if any(reason.startswith("invalid_") for reason in decision["reasons"]):
        raise ValueError("baseline report contains invalid promotion evidence")
    return snapshot


def _artifact_target(workspace: Path, name: str) -> Path:
    target = workspace / name
    if _is_reparse_point(target) or (target.exists() and not target.is_dir()):
        raise ValueError(f"workspace {name} must be a regular directory")
    if target.exists() and workspace not in target.resolve(strict=True).parents:
        raise ValueError(f"workspace {name} must stay inside workspace")
    return target


def _publish_artifact_directories(staging: Path, workspace: Path) -> None:
    names = ("comparisons", "reports")
    targets = {name: _artifact_target(workspace, name) for name in names}
    backups: dict[str, Path] = {}
    published: list[str] = []
    token = uuid.uuid4().hex
    try:
        for name, target in targets.items():
            if target.exists():
                backup = workspace / f".benchmark-backup-{token}-{name}"
                os.replace(target, backup)
                backups[name] = backup
        for name, target in targets.items():
            os.replace(staging / name, target)
            published.append(name)
    except BaseException:
        for name in reversed(published):
            target = targets[name]
            if target.exists():
                shutil.rmtree(target)
        for name, backup in backups.items():
            if backup.exists():
                os.replace(backup, targets[name])
        raise
    finally:
        for backup in backups.values():
            if backup.exists():
                shutil.rmtree(backup)


def _preflight(workspace: Path, candidate_root: Path) -> list[dict[str, Any]]:
    lock = _read_json(workspace / "manifest.lock.json", "manifest lock")
    records = _manifest_records(lock)
    prepared = []
    for record in records:
        sample_id = record["sample_id"]
        context = validated_sample_context(workspace, sample_id)
        resolved_sample = context["sample_dir"]
        source_pdf = context["source_pdf"]
        locked_gold_path = _child(
            resolved_sample, "gold.locked.json", f"{sample_id} locked gold"
        )
        gold_payload = _read_json(
            locked_gold_path,
            f"{sample_id} locked gold",
        )
        try:
            gold = GoldSample.from_dict(gold_payload)
            validate_gold_sample(gold)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{sample_id} locked gold is invalid") from error
        if gold.sample_id != sample_id or gold.status != "locked":
            raise ValueError(f"{sample_id} locked gold identity or status is invalid")
        validate_page_identity(
            gold_payload.get("page"),
            record,
            label=f"{sample_id} locked gold",
        )
        if not gold.blocks:
            raise ValueError(f"{sample_id} locked gold must contain blocks")

        candidate_pdf = _child(candidate_root, f"{sample_id}.pdf", f"{sample_id} candidate PDF")
        validate_candidate_pdf_identity(
            candidate_pdf,
            source_pdf,
            record,
            label=f"{sample_id} candidate page",
        )
        regions_path = _child(
            candidate_root,
            f"{sample_id}.regions.json",
            f"{sample_id} candidate regions",
        )
        regions_payload = _read_json(
            regions_path,
            f"{sample_id} candidate regions",
        )
        if set(regions_payload) != {"regions"} or type(regions_payload["regions"]) is not list:
            raise ValueError(f"{sample_id} candidate regions must use the closed schema")
        candidate_regions = regions_payload["regions"]
        region_ids = {
            str(item.get("block_id") or item.get("region_id"))
            for item in candidate_regions
            if type(item) is dict
            and (item.get("block_id") or item.get("region_id"))
        }
        placement_path = _child(
            candidate_root,
            f"{sample_id}.inline-placement.json",
            f"{sample_id} placement audit",
        )
        placement_payload = _read_json(placement_path, f"{sample_id} placement audit")
        if set(placement_payload) != {"placements"} or type(placement_payload["placements"]) is not list:
            raise ValueError(f"{sample_id} placement audit must use the closed schema")
        subjective_path = _child(
            candidate_root,
            f"{sample_id}.subjective.json",
            f"{sample_id} visual review",
        )
        subjective = _visual_review(
            _read_json(subjective_path, f"{sample_id} visual review"),
            sample_id,
            region_ids,
        )
        evidence_path = _child(
            candidate_root,
            f"{sample_id}.evidence.json",
            f"{sample_id} candidate evidence",
        )
        _bound_visual_evidence(
            sample_id=sample_id,
            benchmark_version=context["benchmark_version"],
            record=record,
            source_pdf=source_pdf,
            source_png=context["source_png"],
            locked_gold_path=locked_gold_path,
            candidate_pdf=candidate_pdf,
            regions_path=regions_path,
            placement_path=placement_path,
            subjective_path=subjective_path,
            evidence=_read_json(evidence_path, f"{sample_id} candidate evidence"),
        )
        visual = _candidate_visual_qa(
            candidate_pdf=candidate_pdf,
            source_pdf=source_pdf,
            gold_blocks=gold_payload["blocks"],
            candidate_regions=candidate_regions,
            placements=placement_payload["placements"],
        )
        diagnostics = _pdf_diagnostics(
            candidate_pdf, source_pdf, placement_payload["placements"]
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
                "visual": visual,
                "diagnostics": diagnostics,
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
    lock = _read_json(workspace_path / "manifest.lock.json", "manifest lock")
    records = _manifest_records(lock)
    manifest_digest = canonical_digest(lock)
    universe = sorted(
        (
            record["sample_id"],
            record["set_name"],
            record["category"],
        )
        for record in records
    )
    baseline = (
        _baseline_summary(
            Path(baseline_report),
            benchmark_version=lock["benchmark_version"],
            manifest_digest=manifest_digest,
            universe=universe,
        )
        if baseline_report is not None
        else None
    )
    _artifact_target(workspace_path, "comparisons")
    _artifact_target(workspace_path, "reports")
    prepared = _preflight(workspace_path, candidate_path)

    samples: list[dict[str, Any]] = []
    for item in prepared:
        missing_ids = set(item["visual"]["missing_region_ids"])
        scored_candidates = [
            {
                **candidate,
                "translated_text": (
                    ""
                    if str(
                        candidate.get("block_id") or candidate.get("region_id")
                    )
                    in missing_ids
                    else candidate.get("translated_text")
                ),
            }
            for candidate in item["candidate_regions"]
        ]
        scored = score_sample(
            gold_blocks=item["gold"]["blocks"],
            candidate_blocks=scored_candidates,
            visual_qa=item["visual"],
            pdf_diagnostics=item["diagnostics"],
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
        "benchmark_version": lock["benchmark_version"],
        "manifest_digest": manifest_digest,
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
    if baseline is not None:
        summary["promotion"] = promotion_decision(
            baseline, _promotion_snapshot(summary)
        )

    staging = Path(
        tempfile.mkdtemp(prefix=".benchmark-evaluate-", dir=workspace_path)
    )
    try:
        comparison_root = staging / "comparisons"
        comparison_root.mkdir()
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
                candidate_bbox = candidate_by_id.get(block_id, {}).get(
                    "target_bbox"
                )
                markers.append(
                    {
                        "side": "candidate",
                        "bbox": candidate_bbox
                        or gold_by_id[block_id]["source_bbox"],
                        "code": failure["code"],
                    }
                )
            render_comparison(
                item["source_pdf"],
                item["candidate_pdf"],
                comparison_root / f"{item['record']['sample_id']}.png",
                markers,
            )
        write_benchmark_report(summary, staging)
        _publish_artifact_directories(staging, workspace_path)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return summary
