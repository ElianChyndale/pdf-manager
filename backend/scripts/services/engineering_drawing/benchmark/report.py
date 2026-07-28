from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from urllib.parse import quote

import fitz
from PIL import Image, ImageDraw


_REPORT_SCHEMA = "engineering-drawing-benchmark-report-v1"
_MIN_DPI = 36
# 300 DPI keeps comparison rasterization bounded for the benchmark's page-one PDFs.
_MAX_DPI = 300
_MAX_MARKERS = 1_000
_MAX_SAMPLES = 1_000
_MAX_CODE_LENGTH = 128
_MAX_SAMPLE_ID_LENGTH = 128
_MAX_CATEGORY_LENGTH = 256
_MAX_COMPARISON_PATH_LENGTH = 512
_MAX_HARD_FAILURE_COUNT = 1_000_000
_MAX_FAILURE_FIELDS = 64
_MAX_FAILURE_TOKENS = 64
_MAX_PROMOTION_REASONS = 128
_MARKER_KEYS = {"side", "bbox", "code"}
_LEGACY_SUMMARY_KEYS = {"schema", "core_score", "samples"}
_FULL_SUMMARY_KEYS = {
    *_LEGACY_SUMMARY_KEYS,
    "hard_failure_count",
    "manual_review_rate",
    "automation_rate",
    "category_scores",
    "challenge_pass_rate",
    "challenge_sample_count",
}
_FULL_SUMMARY_WITH_PROMOTION_KEYS = {*_FULL_SUMMARY_KEYS, "promotion"}
_BOUND_SUMMARY_KEYS = {
    *_FULL_SUMMARY_KEYS,
    "benchmark_version",
    "manifest_digest",
}
_BOUND_SUMMARY_WITH_PROMOTION_KEYS = {*_BOUND_SUMMARY_KEYS, "promotion"}
_LEGACY_SAMPLE_KEYS = {
    "sample_id",
    "category",
    "score",
    "hard_failure_count",
    "comparison_png",
}
_FULL_SAMPLE_KEYS = {
    "sample_id",
    "set_name",
    "category",
    "comparison_png",
    "schema",
    "hard_failures",
    "hard_failure_ids",
    "hard_failure_count",
    "dimensions",
    "score",
    "passed",
}
_DIMENSION_MAXIMA = {
    "semantic_terminology": 30.0,
    "coverage_deduplication": 20.0,
    "semantic_grouping": 15.0,
    "layout_association": 20.0,
    "page_readability": 15.0,
}
_HARD_FAILURE_KEYS = {"code", "block_id", "region_id", "fields", "tokens"}
_PROMOTION_KEYS = {
    "promote",
    "reasons",
    "core_score_gain",
    "new_hard_failure_ids",
}


def _finite_number(value: object, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{label} is outside its allowed range")
    return number


def _bounded_string(value: object, label: str, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ValueError(f"{label} must be a non-empty string up to {maximum} characters")
    return value


def _validated_dpi(value: object) -> int:
    if type(value) is not int or not _MIN_DPI <= value <= _MAX_DPI:
        raise ValueError(f"dpi must be an integer in {_MIN_DPI}..{_MAX_DPI}")
    return value


def _regular_pdf(value: Path, label: str) -> Path:
    path = Path(value)
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"{label} must be a .pdf file")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{label} must be an existing regular .pdf file") from error
    if resolved.suffix.lower() != ".pdf" or not resolved.is_file():
        raise ValueError(f"{label} must be an existing regular .pdf file")
    return resolved


def _is_reparse_point(path: Path) -> bool:
    """Return true for symlinks and Windows junction/reparse-point entries."""
    try:
        status = os.lstat(path)
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & reparse_flag)


def _is_strict_descendant(path: Path, root: Path) -> bool:
    return path != root and root in path.parents


def _audit_output_parent(path: Path) -> None:
    parent = path.parent
    if path.is_absolute():
        current = Path(path.anchor)
        parts = parent.parts[1:]
    else:
        current = Path.cwd()
        parts = parent.parts
    for part in parts:
        if part in {"", "."}:
            continue
        current /= part
        if _is_reparse_point(current):
            raise ValueError("output_png parent must not use a symlink or reparse point")
        if current.exists() and not current.is_dir():
            raise ValueError("output_png parent must be a directory")


def _output_png(value: Path) -> Path:
    path = Path(value)
    if path.suffix.lower() != ".png":
        raise ValueError("output_png must use the .png extension")
    if _is_reparse_point(path):
        raise ValueError("output_png must not be a symlink or reparse point")
    _audit_output_parent(path)
    if path.exists() and not path.is_file():
        raise ValueError("output_png must be a regular file path")
    return path.absolute()


def _page_image(path: Path, dpi: int) -> tuple[Image.Image, tuple[float, float]]:
    try:
        with fitz.open(path) as document:
            if document.page_count < 1:
                raise ValueError(f"{path.name} has no usable first page")
            page = document[0]
            width, height = page.rect.width, page.rect.height
            if (
                not math.isfinite(width)
                or not math.isfinite(height)
                or width <= 0
                or height <= 0
            ):
                raise ValueError(f"{path.name} has invalid first-page geometry")
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    except fitz.FileDataError as error:
        raise ValueError(f"{path.name} is not a usable PDF") from error
    return image, (width, height)


def _markers(
    value: object,
    source_size: tuple[float, float],
    candidate_size: tuple[float, float],
) -> list[dict]:
    if type(value) is not list or len(value) > _MAX_MARKERS:
        raise ValueError("markers must be a bounded list")
    markers: list[dict] = []
    for index, marker in enumerate(value):
        label = f"marker {index}"
        if type(marker) is not dict or set(marker) != _MARKER_KEYS:
            raise ValueError(f"{label} must have exactly side, bbox, and code")
        if marker["side"] not in {"source", "candidate"}:
            raise ValueError(f"{label} side must be source or candidate")
        code = _bounded_string(marker["code"], f"{label} code", _MAX_CODE_LENGTH)
        bbox = marker["bbox"]
        if type(bbox) is not list or len(bbox) != 4:
            raise ValueError(f"{label} bbox must contain four coordinates")
        x0, y0, x1, y1 = (
            _finite_number(coordinate, f"{label} bbox", 0.0, float("inf"))
            for coordinate in bbox
        )
        page_width, page_height = (
            source_size if marker["side"] == "source" else candidate_size
        )
        if x0 >= x1 or y0 >= y1 or x1 > page_width or y1 > page_height:
            raise ValueError(f"{label} bbox must be ordered and inside its page")
        markers.append(
            {"side": marker["side"], "bbox": [x0, y0, x1, y1], "code": code}
        )
    return markers


def _save_png_atomically(canvas: Image.Image, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}-", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        canvas.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def render_comparison(
    source_pdf: Path,
    candidate_pdf: Path,
    output_png: Path,
    markers: list[dict],
    dpi: int = 120,
) -> Path:
    """Write an atomic, deterministic first-page comparison PNG at 36..300 DPI."""
    validated_dpi = _validated_dpi(dpi)
    source_path = _regular_pdf(source_pdf, "source_pdf")
    candidate_path = _regular_pdf(candidate_pdf, "candidate_pdf")
    output = _output_png(output_png)
    source: Image.Image | None = None
    candidate: Image.Image | None = None
    canvas: Image.Image | None = None
    try:
        source, source_size = _page_image(source_path, validated_dpi)
        candidate, candidate_size = _page_image(candidate_path, validated_dpi)
        validated_markers = _markers(markers, source_size, candidate_size)
        scale = validated_dpi / 72
        draw = ImageDraw.Draw(candidate)
        for marker in validated_markers:
            if marker["side"] != "candidate":
                continue
            x0, y0, x1, y1 = (coordinate * scale for coordinate in marker["bbox"])
            draw.rectangle(
                (x0, y0, x1, y1),
                outline=(220, 30, 30),
                width=max(2, round(scale)),
            )
            draw.text((x0, max(0, y0 - 12)), marker["code"], fill=(220, 30, 30))
        del draw
        canvas = Image.new(
            "RGB",
            (source.width + candidate.width, max(source.height, candidate.height)),
            "white",
        )
        canvas.paste(source, (0, 0))
        canvas.paste(candidate, (source.width, 0))
        _save_png_atomically(canvas, output)
        return output
    finally:
        if canvas is not None:
            canvas.close()
        if candidate is not None:
            candidate.close()
        if source is not None:
            source.close()


def _comparison_link(workspace: Path, value: object) -> str:
    raw = _bounded_string(value, "comparison_png", _MAX_COMPARISON_PATH_LENGTH)
    if "\\" in raw:
        raise ValueError("comparison_png must use normalized POSIX separators")
    relative = PurePosixPath(raw)
    if (
        relative.is_absolute()
        or relative.as_posix() != raw
        or len(relative.parts) < 2
        or relative.parts[0] != "comparisons"
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.suffix != ".png"
    ):
        raise ValueError("comparison_png must be a normalized comparisons/*.png path")
    comparison_root = workspace / "comparisons"
    try:
        root = comparison_root.resolve(strict=True)
        target = (workspace / relative).resolve(strict=True)
    except OSError as error:
        raise ValueError("comparison_png must name an existing comparison PNG") from error
    workspace_contains_root = _is_strict_descendant(root, workspace)
    workspace_contains_target = _is_strict_descendant(target, workspace)
    if (
        not root.is_dir()
        or not target.is_file()
        or not workspace_contains_root
        or not workspace_contains_target
        or root not in target.parents
    ):
        raise ValueError("comparison_png must stay inside workspace comparisons")
    return quote(relative.as_posix(), safe="/")


def _bounded_counter(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_HARD_FAILURE_COUNT:
        raise ValueError(f"{label} must be a bounded integer")
    return value


def _string_list(value: object, label: str, maximum: int) -> list[str]:
    if type(value) is not list or len(value) > maximum:
        raise ValueError(f"{label} must be a bounded list")
    return [_bounded_string(item, label, _MAX_CODE_LENGTH) for item in value]


def _failure_identity(value: dict) -> str:
    scope = value.get("block_id", value.get("region_id"))
    return value["code"] if scope is None else f"{value['code']}:{scope}"


def _validated_hard_failures(value: object, label: str) -> list[dict]:
    if type(value) is not list or len(value) > _MAX_HARD_FAILURE_COUNT:
        raise ValueError(f"{label} hard_failures must be a bounded list")
    failures: list[dict] = []
    for index, failure in enumerate(value):
        failure_label = f"{label} hard_failures[{index}]"
        if type(failure) is not dict or not {"code"} <= set(failure) <= _HARD_FAILURE_KEYS:
            raise ValueError(f"{failure_label} must use the score failure schema")
        if "block_id" in failure and "region_id" in failure:
            raise ValueError(f"{failure_label} cannot have both block_id and region_id")
        normalized = {"code": _bounded_string(failure["code"], failure_label, _MAX_CODE_LENGTH)}
        for scope in ("block_id", "region_id"):
            if scope in failure:
                normalized[scope] = _bounded_string(
                    failure[scope], f"{failure_label} {scope}", _MAX_SAMPLE_ID_LENGTH
                )
        if "fields" in failure:
            fields = _string_list(failure["fields"], f"{failure_label} fields", _MAX_FAILURE_FIELDS)
            if fields != sorted(set(fields)):
                raise ValueError(f"{failure_label} fields must be sorted and unique")
            normalized["fields"] = fields
        if "tokens" in failure:
            normalized["tokens"] = _string_list(
                failure["tokens"], f"{failure_label} tokens", _MAX_FAILURE_TOKENS
            )
        failures.append(normalized)
    return failures


def _validated_dimensions(value: object, label: str) -> dict[str, float]:
    if type(value) is not dict or set(value) != set(_DIMENSION_MAXIMA):
        raise ValueError(f"{label} dimensions must use the score dimension schema")
    return {
        key: _finite_number(value[key], f"{label} dimensions.{key}", 0.0, maximum)
        for key, maximum in _DIMENSION_MAXIMA.items()
    }


def _validated_full_sample(sample: dict, label: str) -> tuple[dict, dict]:
    if set(sample) != _FULL_SAMPLE_KEYS:
        raise ValueError(f"{label} must use the complete score sample schema")
    sample_id = _bounded_string(sample["sample_id"], f"{label} sample_id", _MAX_SAMPLE_ID_LENGTH)
    set_name = sample["set_name"]
    if set_name not in {"core", "challenge"}:
        raise ValueError(f"{label} set_name must be core or challenge")
    category = _bounded_string(sample["category"], f"{label} category", _MAX_CATEGORY_LENGTH)
    if sample["schema"] != "engineering-drawing-score-v1":
        raise ValueError(f"{label} has an unsupported score schema")
    failures = _validated_hard_failures(sample["hard_failures"], label)
    failure_ids = _string_list(
        sample["hard_failure_ids"], f"{label} hard_failure_ids", _MAX_HARD_FAILURE_COUNT
    )
    if len(set(failure_ids)) != len(failure_ids):
        raise ValueError(f"{label} hard_failure_ids must be unique")
    expected_ids = sorted(_failure_identity(failure) for failure in failures)
    if failure_ids != expected_ids:
        raise ValueError(f"{label} hard_failure_ids must match hard_failures")
    count = _bounded_counter(sample["hard_failure_count"], f"{label} hard_failure_count")
    if count != len(failures):
        raise ValueError(f"{label} hard_failure_count must match hard_failures")
    dimensions = _validated_dimensions(sample["dimensions"], label)
    score = _finite_number(sample["score"], f"{label} score", 0.0, 100.0)
    if abs(score - round(sum(dimensions.values()), 3)) > 1e-9:
        raise ValueError(f"{label} score must match dimensions")
    if type(sample["passed"]) is not bool or sample["passed"] != (count == 0):
        raise ValueError(f"{label} passed must match hard failures")
    row = {
        "sample_id": sample_id,
        "category": category,
        "score": score,
        "hard_failure_count": count,
        "comparison_link": None,
    }
    return row, {
        "set_name": set_name,
        "category": category,
        "score": score,
        "hard_failure_count": count,
        "passed": sample["passed"],
        "comparison_png": sample["comparison_png"],
    }


def _validated_promotion(value: object) -> None:
    if type(value) is not dict or set(value) != _PROMOTION_KEYS:
        raise ValueError("promotion must use the promotion decision schema")
    if type(value["promote"]) is not bool:
        raise ValueError("promotion promote must be boolean")
    reasons = _string_list(value["reasons"], "promotion reasons", _MAX_PROMOTION_REASONS)
    if len(set(reasons)) != len(reasons):
        raise ValueError("promotion reasons must be unique")
    gain = value["core_score_gain"]
    if gain is not None:
        _finite_number(gain, "promotion core_score_gain", -100.0, 100.0)
    new_failure_ids = _string_list(
        value["new_hard_failure_ids"],
        "promotion new_hard_failure_ids",
        _MAX_HARD_FAILURE_COUNT,
    )
    if new_failure_ids != sorted(set(new_failure_ids)):
        raise ValueError("promotion new_hard_failure_ids must be sorted and unique")


def _validated_aggregate(summary: dict, full_samples: list[dict]) -> None:
    total_failures = sum(sample["hard_failure_count"] for sample in full_samples)
    if _bounded_counter(summary["hard_failure_count"], "hard_failure_count") != total_failures:
        raise ValueError("hard_failure_count must match samples")
    _finite_number(summary["manual_review_rate"], "manual_review_rate", 0.0, 1.0)
    _finite_number(summary["automation_rate"], "automation_rate", 0.0, 1.0)
    _finite_number(summary["challenge_pass_rate"], "challenge_pass_rate", 0.0, 1.0)
    core_samples = [sample for sample in full_samples if sample["set_name"] == "core"]
    challenge_samples = [
        sample for sample in full_samples if sample["set_name"] == "challenge"
    ]
    if _bounded_counter(
        summary["challenge_sample_count"], "challenge_sample_count"
    ) != len(challenge_samples):
        raise ValueError("challenge_sample_count must match challenge samples")
    expected_challenge_rate = (
        sum(sample["passed"] for sample in challenge_samples) / len(challenge_samples)
        if challenge_samples
        else 1.0
    )
    if (
        abs(
            _finite_number(
                summary["challenge_pass_rate"], "challenge_pass_rate", 0.0, 1.0
            )
            - expected_challenge_rate
        )
        > 1e-9
    ):
        raise ValueError("challenge_pass_rate must match challenge samples")
    category_scores = summary["category_scores"]
    expected_categories = {sample["category"] for sample in core_samples}
    if (
        type(category_scores) is not dict
        or len(category_scores) > _MAX_SAMPLES
        or set(category_scores) != expected_categories
    ):
        raise ValueError("category_scores must match core sample categories")
    for category, score in category_scores.items():
        _bounded_string(category, "category_scores key", _MAX_CATEGORY_LENGTH)
        expected = sum(
            sample["score"] for sample in core_samples if sample["category"] == category
        ) / sum(1 for sample in core_samples if sample["category"] == category)
        if abs(_finite_number(score, f"category_scores.{category}", 0.0, 100.0) - expected) > 1e-9:
            raise ValueError(f"category_scores.{category} must match samples")
    expected_core = sum(sample["score"] for sample in core_samples) / max(1, len(core_samples))
    if abs(_finite_number(summary["core_score"], "core_score", 0.0, 100.0) - expected_core) > 1e-9:
        raise ValueError("core_score must match core samples")


def _validated_summary(summary: object, workspace: Path) -> tuple[dict, list[dict]]:
    if type(summary) is not dict or summary.get("schema") != _REPORT_SCHEMA:
        raise ValueError("summary must use the canonical report schema")
    keys = set(summary)
    if (
        keys != _LEGACY_SUMMARY_KEYS
        and keys != _FULL_SUMMARY_KEYS
        and keys != _FULL_SUMMARY_WITH_PROMOTION_KEYS
        and keys != _BOUND_SUMMARY_KEYS
        and keys != _BOUND_SUMMARY_WITH_PROMOTION_KEYS
    ):
        raise ValueError("summary must use a closed report schema")
    _finite_number(summary["core_score"], "core_score", 0.0, 100.0)
    samples = summary["samples"]
    if type(samples) is not list or len(samples) > _MAX_SAMPLES:
        raise ValueError("samples must be a bounded list")
    full_contract = keys != _LEGACY_SUMMARY_KEYS
    if keys == _BOUND_SUMMARY_KEYS or keys == _BOUND_SUMMARY_WITH_PROMOTION_KEYS:
        _bounded_string(
            summary["benchmark_version"], "benchmark_version", _MAX_CODE_LENGTH
        )
        manifest_digest = _bounded_string(
            summary["manifest_digest"], "manifest_digest", 64
        )
        if len(manifest_digest) != 64 or any(
            char not in "0123456789abcdef" for char in manifest_digest
        ):
            raise ValueError("manifest_digest must be a lowercase SHA-256")
    normalized_samples: list[dict] = []
    full_samples: list[dict] = []
    sample_ids = set()
    for index, sample in enumerate(samples):
        label = f"sample {index}"
        if type(sample) is not dict:
            raise ValueError(f"{label} must be an object")
        if full_contract:
            row, aggregate_sample = _validated_full_sample(sample, label)
            full_samples.append(aggregate_sample)
        else:
            if set(sample) != _LEGACY_SAMPLE_KEYS:
                raise ValueError(f"{label} must use the canonical sample schema")
            row = {
                "sample_id": _bounded_string(
                    sample["sample_id"], f"{label} sample_id", _MAX_SAMPLE_ID_LENGTH
                ),
                "category": _bounded_string(
                    sample["category"], f"{label} category", _MAX_CATEGORY_LENGTH
                ),
                "score": _finite_number(sample["score"], f"{label} score", 0.0, 100.0),
                "hard_failure_count": _bounded_counter(
                    sample["hard_failure_count"], f"{label} hard_failure_count"
                ),
                "comparison_link": None,
            }
        if row["sample_id"] in sample_ids:
            raise ValueError("sample_id values must be unique")
        sample_ids.add(row["sample_id"])
        row["comparison_link"] = _comparison_link(workspace, sample["comparison_png"])
        normalized_samples.append(row)
    if full_contract:
        _validated_aggregate(summary, full_samples)
        if "promotion" in summary:
            _validated_promotion(summary["promotion"])
    return dict(summary), normalized_samples


def _stage_text(directory: Path, content: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".benchmark-report-", suffix=".tmp", dir=directory
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _stage_bytes(directory: Path, content: bytes) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".benchmark-report-", suffix=".tmp", dir=directory
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _backup(target: Path, directory: Path) -> Path | None:
    if not target.exists():
        return None
    if target.is_symlink() or not target.is_file():
        raise ValueError(f"report target must be a regular file: {target.name}")
    return _stage_bytes(directory, target.read_bytes())


def _publish_pair(
    json_stage: Path, html_stage: Path, json_path: Path, html_path: Path, reports: Path
) -> None:
    json_backup = html_backup = None
    json_published = html_published = False
    try:
        json_backup = _backup(json_path, reports)
        html_backup = _backup(html_path, reports)
        os.replace(json_stage, json_path)
        json_published = True
        os.replace(html_stage, html_path)
        html_published = True
    except BaseException:
        if json_published:
            if json_backup is None:
                json_path.unlink(missing_ok=True)
            else:
                os.replace(json_backup, json_path)
                json_backup = None
        if html_published:
            if html_backup is None:
                html_path.unlink(missing_ok=True)
            else:
                os.replace(html_backup, html_path)
                html_backup = None
        raise
    finally:
        for temporary in (json_stage, html_stage, json_backup, html_backup):
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def write_benchmark_report(summary: dict, workspace: Path) -> tuple[Path, Path]:
    """Atomically publish validated UTF-8 JSON and escaped HTML in a workspace."""
    workspace_path = Path(workspace).resolve(strict=True)
    if not workspace_path.is_dir():
        raise ValueError("workspace must be an existing directory")
    normalized, rows = _validated_summary(summary, workspace_path)
    reports = workspace_path / "reports"
    if _is_reparse_point(reports):
        raise ValueError("workspace reports must be a regular directory")
    if reports.exists():
        try:
            resolved_reports = reports.resolve(strict=True)
        except OSError as error:
            raise ValueError("workspace reports must be a regular directory") from error
        if (
            not reports.is_dir()
            or not _is_strict_descendant(resolved_reports, workspace_path)
        ):
            raise ValueError("workspace reports must be a regular directory")
    json_content = json.dumps(
        normalized, ensure_ascii=False, indent=2, allow_nan=False
    )
    html_rows = "".join(
        "<tr>"
        f"<td>{html.escape(sample['sample_id'])}</td>"
        f"<td>{html.escape(sample['category'])}</td>"
        f"<td>{sample['score']:.1f}</td>"
        f"<td>{sample['hard_failure_count']}</td>"
        f"<td><a href='../{html.escape(sample['comparison_link'], quote=True)}'>查看</a></td>"
        "</tr>"
        for sample in rows
    )
    html_content = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<title>Engineering Drawing Benchmark</title>"
        "<style>body{font-family:Arial,\"Microsoft YaHei\",sans-serif;margin:24px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px}</style>"
        "</head><body><h1>Engineering Drawing Benchmark</h1>"
        f"<p>Core score: {normalized['core_score']:.1f}</p>"
        "<table><thead><tr><th>样本</th><th>类别</th><th>得分</th><th>硬失败</th><th>对比</th></tr></thead>"
        f"<tbody>{html_rows}</tbody></table></body></html>"
    )
    reports.mkdir(parents=True, exist_ok=True)
    json_path = reports / "benchmark-report.json"
    html_path = reports / "benchmark-report.html"
    json_stage = html_stage = None
    try:
        json_stage = _stage_text(reports, json_content)
        html_stage = _stage_text(reports, html_content)
        _publish_pair(json_stage, html_stage, json_path, html_path, reports)
        json_stage = html_stage = None
    finally:
        for temporary in (json_stage, html_stage):
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return json_path, html_path
