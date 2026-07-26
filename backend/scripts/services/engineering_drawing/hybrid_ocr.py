from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import fitz
from PIL import Image

from .legacy_audit import _action, _language, _page_lines
from .models import Action, LegacyStatus, Placement, Provenance


def _local_deepseek_model() -> str:
    repo_root = Path(__file__).resolve().parents[4]
    local_model = repo_root / ".runtime" / "ocr" / "models" / "deepseek-ocr-2"
    return str(local_model) if (local_model / "config.json").exists() else "deepseek-ai/DeepSeek-OCR-2"


@dataclass(frozen=True)
class HybridOcrConfig:
    pipeline_version: int = 5
    dpi: int = 220
    tile_size: int = 2200
    tile_overlap: int = 180
    deepseek_review_threshold: float = 0.82
    min_paddle_confidence: float = 0.25
    deepseek_max_regions_per_page: int = 6
    paddle_det_model: str = "PP-OCRv5_server_det"
    paddle_rec_model: str = "PP-OCRv5_server_rec"
    deepseek_model: str = field(default_factory=_local_deepseek_model)


@dataclass(frozen=True)
class HybridOcrResult:
    output_path: Path
    region_count: int
    native_region_count: int
    paddle_region_count: int
    deepseek_review_count: int
    cache_hit: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _runtime_python(engine: str) -> Path:
    return _repo_root() / ".runtime" / "ocr" / engine / "Scripts" / "python.exe"


def _runner_path(name: str) -> Path:
    return Path(__file__).resolve().parent / "ocr_runners" / f"{name}_runner.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, timeout: int) -> None:
    process = subprocess.run(
        command,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if process.returncode:
        tail = (process.stderr or process.stdout)[-4000:]
        raise RuntimeError(f"OCR subprocess failed ({process.returncode}): {tail}")


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", (text or "").casefold())


def _similar(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalized(left), _normalized(right)).ratio()


def _rect_iou(left: fitz.Rect, right: fitz.Rect) -> float:
    intersection = left & right
    if intersection.is_empty:
        return 0.0
    union = left.get_area() + right.get_area() - intersection.get_area()
    return intersection.get_area() / union if union > 0 else 0.0


def _native_regions(page: fitz.Page, page_number: int) -> list[dict]:
    regions = []
    for index, line in enumerate(_page_lines(page), start=1):
        action = _action(line.text)
        regions.append(
            {
                "region_id": f"p{page_number:03d}-native-{index:04d}",
                "page_index": page_number - 1,
                "page_number": page_number,
                "source_text": line.text,
                "translated_text": "",
                "source_language": _language(line.text).value,
                "bbox": [line.bbox.x0, line.bbox.y0, line.bbox.x1, line.bbox.y1],
                "rotation": line.rotation,
                "provenance": Provenance.NATIVE_TEXT.value,
                "action": action.value,
                "legacy_status": LegacyStatus.MISSING.value if action == Action.TRANSLATE else LegacyStatus.ACCEPTED.value,
                "placement": Placement.UNCHANGED.value if action == Action.KEEP_LITERAL else Placement.UNPLACED.value,
                "qa_flags": [],
                "ocr_confidence": 1.0,
            }
        )
    return regions


def _render_page(page: fitz.Page, path: Path, dpi: int) -> tuple[int, int]:
    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    pixmap.save(path)
    return pixmap.width, pixmap.height


def _paddle_regions(
    payload: dict,
    *,
    page: fitz.Page,
    page_number: int,
    image_width: int,
    image_height: int,
    min_confidence: float,
) -> list[dict]:
    if "pages" in payload:
        pages = payload.get("pages") or []
        payload = pages[0] if pages else {}
    items = payload.get("items", [])
    meta = payload.get("meta", {})
    source_id = re.sub(r"[^a-zA-Z0-9-]+", "-", str(payload.get("id") or "full"))
    offset_x = int(meta.get("offset_x", 0) or 0)
    offset_y = int(meta.get("offset_y", 0) or 0)
    sx = page.rect.width / image_width
    sy = page.rect.height / image_height
    regions = []
    for index, item in enumerate(items, start=1):
        confidence = float(item.get("confidence", 0) or 0)
        if confidence < min_confidence:
            continue
        box = item.get("bbox") or []
        if len(box) != 4:
            polygon = item.get("polygon") or []
            if not polygon:
                continue
            xs = [float(point[0]) for point in polygon]
            ys = [float(point[1]) for point in polygon]
            box = [min(xs), min(ys), max(xs), max(ys)]
        bbox = [
            (float(box[0]) + offset_x) * sx,
            (float(box[1]) + offset_y) * sy,
            (float(box[2]) + offset_x) * sx,
            (float(box[3]) + offset_y) * sy,
        ]
        text = str(item.get("text", "") or "").strip()
        action = _action(text)
        orientation = int(item.get("orientation", -1) or -1)
        rotation = 180 if orientation == 1 else 0
        compact = _normalized(text)
        provenance = (
            Provenance.VECTOR_OUTLINE
            if ("depoh" in compact or "lori" in compact)
            else Provenance.PADDLE_OCR
        )
        flags = []
        if confidence < 0.6:
            flags.append("low_paddle_confidence")
        regions.append(
            {
                "region_id": f"p{page_number:03d}-paddle-{source_id}-{index:04d}",
                "page_index": page_number - 1,
                "page_number": page_number,
                "source_text": text,
                "translated_text": "",
                "source_language": _language(text).value,
                "bbox": bbox,
                "rotation": rotation,
                "provenance": provenance.value,
                "action": action.value,
                "legacy_status": LegacyStatus.MISSING.value if action == Action.TRANSLATE else LegacyStatus.ACCEPTED.value,
                "placement": Placement.UNCHANGED.value if action == Action.KEEP_LITERAL else Placement.UNPLACED.value,
                "qa_flags": flags,
                "ocr_confidence": confidence,
            }
        )
    return regions


def _tile_manifest(image_path: Path, *, output_dir: Path, tile_size: int, overlap: int) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(image_path).convert("RGB")
    entries = [{"id": "full", "image_path": str(image_path), "meta": {"offset_x": 0, "offset_y": 0}}]
    if tile_size <= 0 or image.width <= tile_size and image.height <= tile_size:
        return entries
    step = max(256, tile_size - max(0, overlap))
    x_positions = list(range(0, max(1, image.width - tile_size + 1), step))
    y_positions = list(range(0, max(1, image.height - tile_size + 1), step))
    final_x = max(0, image.width - tile_size)
    final_y = max(0, image.height - tile_size)
    if not x_positions or x_positions[-1] != final_x:
        x_positions.append(final_x)
    if not y_positions or y_positions[-1] != final_y:
        y_positions.append(final_y)
    for y in sorted(set(y_positions)):
        for x in sorted(set(x_positions)):
            tile_path = output_dir / f"tile-{x:05d}-{y:05d}.png"
            image.crop((x, y, min(image.width, x + tile_size), min(image.height, y + tile_size))).save(tile_path)
            entries.append(
                {
                    "id": f"tile-{x}-{y}",
                    "image_path": str(tile_path),
                    "meta": {"offset_x": x, "offset_y": y},
                }
            )
    return entries


def _dedupe_visual(regions: list[dict]) -> list[dict]:
    selected: list[dict] = []
    for candidate in sorted(regions, key=lambda item: float(item.get("ocr_confidence", 0) or 0), reverse=True):
        rect = fitz.Rect(candidate["bbox"])
        duplicate = any(
            _rect_iou(rect, fitz.Rect(existing["bbox"])) >= 0.5
            and _similar(candidate["source_text"], existing["source_text"]) >= 0.7
            for existing in selected
        )
        if not duplicate:
            selected.append(candidate)
    return sorted(selected, key=lambda item: (item["bbox"][1], item["bbox"][0]))


def _merge_native_and_visual(native: list[dict], visual: list[dict]) -> list[dict]:
    result = list(native)
    native_pairs = [(fitz.Rect(item["bbox"]), item) for item in native]
    for candidate in visual:
        rect = fitz.Rect(candidate["bbox"])
        duplicate = any(
            _rect_iou(rect, native_rect) >= 0.45
            and _similar(candidate["source_text"], native_item["source_text"]) >= 0.72
            for native_rect, native_item in native_pairs
        )
        if not duplicate:
            result.append(candidate)
    return result


def _needs_deepseek(region: dict, threshold: float) -> bool:
    if region.get("provenance") == Provenance.NATIVE_TEXT.value:
        return False
    text = _normalized(str(region.get("source_text", "")))
    confidence = float(region.get("ocr_confidence", 0) or 0)
    return (
        confidence < threshold
        or region.get("rotation") not in (0, None)
        or any(marker in text for marker in ("setbackl", "depoh", "lori", "distributionwater", "treatedwater"))
    )


def _crop_review_regions(
    image_path: Path,
    regions: list[dict],
    *,
    page: fitz.Page,
    output_dir: Path,
    limit: int,
    threshold: float,
) -> list[dict]:
    image = Image.open(image_path).convert("RGB")
    sx = image.width / page.rect.width
    sy = image.height / page.rect.height
    regression_markers = (
        "depoh",
        "lori",
        "setback",
        "distributionstoragetank",
        "treatedwater",
        "trectedwater",
    )

    def review_priority(item: dict) -> tuple[int, float]:
        text = _normalized(str(item.get("source_text", "")))
        is_regression = any(marker in text for marker in regression_markers)
        return (0 if is_regression else 1, float(item.get("ocr_confidence", 0) or 0))

    candidates = sorted(
        (region for region in regions if _needs_deepseek(region, threshold)),
        key=review_priority,
    )
    selected = []
    seen_texts: set[str] = set()
    for region in candidates:
        normalized = _normalized(str(region.get("source_text", "")))
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)
        selected.append(region)
        if len(selected) >= limit:
            break
    manifest_items = []
    for region in selected:
        rect = fitz.Rect(region["bbox"])
        padding = max(12, round(max(rect.width * sx, rect.height * sy) * 0.18))
        crop = (
            max(0, round(rect.x0 * sx) - padding),
            max(0, round(rect.y0 * sy) - padding),
            min(image.width, round(rect.x1 * sx) + padding),
            min(image.height, round(rect.y1 * sy) + padding),
        )
        crop_path = output_dir / f"{region['region_id']}.png"
        image.crop(crop).save(crop_path)
        manifest_items.append(
            {
                "id": region["region_id"],
                "image_path": str(crop_path),
                "prompt": "<image>\nFree OCR.",
                "source_text": region["source_text"],
            }
        )
    return manifest_items


def run_hybrid_ocr(
    *,
    pdf_path: Path,
    output_path: Path,
    cache_dir: Path,
    start_page: int = 1,
    end_page: int = -1,
    config: HybridOcrConfig | None = None,
    enable_deepseek: bool = True,
) -> HybridOcrResult:
    config = config or HybridOcrConfig()
    pdf_path = Path(pdf_path).resolve()
    cache_dir = Path(cache_dir)
    cache_key = hashlib.sha256(
        json.dumps(
            {"sha256": _sha256(pdf_path), "config": asdict(config), "start": start_page, "end": end_page, "deepseek": enable_deepseek},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    cached_path = cache_dir / cache_key[:2] / f"{cache_key}.json"
    if cached_path.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(cached_path.read_bytes())
        payload = json.loads(cached_path.read_text(encoding="utf-8"))
        stats = payload["stats"]
        return HybridOcrResult(output_path, stats["region_count"], stats["native_region_count"], stats["paddle_region_count"], stats["deepseek_review_count"], True)

    paddle_python = _runtime_python("paddle")
    deepseek_python = _runtime_python("deepseek")
    if not paddle_python.exists():
        raise RuntimeError(f"PaddleOCR runtime missing: {paddle_python}")
    all_regions: list[dict] = []
    native_count = paddle_count = deepseek_count = deepseek_correction_count = 0
    with fitz.open(pdf_path) as document, tempfile.TemporaryDirectory(prefix="engineering-ocr-") as temp:
        temp_dir = Path(temp)
        stop = document.page_count if end_page < 0 else min(document.page_count, end_page)
        for page_number in range(max(1, start_page), stop + 1):
            page = document[page_number - 1]
            image_path = temp_dir / f"page-{page_number:03d}.png"
            width, height = _render_page(page, image_path, config.dpi)
            paddle_output = temp_dir / f"page-{page_number:03d}-paddle.json"
            paddle_manifest = temp_dir / f"page-{page_number:03d}-paddle-manifest.json"
            paddle_inputs = _tile_manifest(
                image_path,
                output_dir=temp_dir / f"page-{page_number:03d}-tiles",
                tile_size=config.tile_size,
                overlap=config.tile_overlap,
            )
            paddle_manifest.write_text(json.dumps({"items": paddle_inputs}, ensure_ascii=False), encoding="utf-8")
            _run(
                [
                    str(paddle_python),
                    str(_runner_path("paddle")),
                    "--manifest",
                    str(paddle_manifest),
                    "--output",
                    str(paddle_output),
                    "--det-model",
                    config.paddle_det_model,
                    "--rec-model",
                    config.paddle_rec_model,
                ],
                timeout=1800,
            )
            native = _native_regions(page, page_number)
            paddle_payload = json.loads(paddle_output.read_text(encoding="utf-8"))
            paddle = _dedupe_visual(
                [
                    region
                    for paddle_page in paddle_payload.get("pages", [])
                    for region in _paddle_regions(
                        paddle_page,
                        page=page,
                        page_number=page_number,
                        image_width=width,
                        image_height=height,
                        min_confidence=config.min_paddle_confidence,
                    )
                ]
            )
            native_count += len(native)
            paddle_count += len(paddle)
            merged = _merge_native_and_visual(native, paddle)
            review_manifest = _crop_review_regions(
                image_path,
                merged,
                page=page,
                output_dir=temp_dir,
                limit=config.deepseek_max_regions_per_page,
                threshold=config.deepseek_review_threshold,
            )
            if enable_deepseek and review_manifest:
                if not deepseek_python.exists():
                    raise RuntimeError(f"DeepSeek OCR runtime missing: {deepseek_python}")
                manifest_path = temp_dir / f"page-{page_number:03d}-deepseek-manifest.json"
                result_path = temp_dir / f"page-{page_number:03d}-deepseek.json"
                manifest_path.write_text(json.dumps({"items": review_manifest}, ensure_ascii=False), encoding="utf-8")
                _run(
                    [
                        str(deepseek_python),
                        str(_runner_path("deepseek")),
                        "--manifest",
                        str(manifest_path),
                        "--output",
                        str(result_path),
                        "--model",
                        config.deepseek_model,
                    ],
                    timeout=3600,
                )
                corrections = {
                    item["id"]: item
                    for item in json.loads(result_path.read_text(encoding="utf-8")).get("items", [])
                }
                for region in merged:
                    correction = corrections.get(region["region_id"])
                    if not correction:
                        continue
                    if correction.get("text"):
                        deepseek_count += 1
                        candidate_text = str(correction["text"]).strip()
                        paddle_text = str(region["source_text"]).strip()
                        confidence = float(region.get("ocr_confidence", 0) or 0)
                        similarity = _similar(candidate_text, paddle_text)
                        flags = region.setdefault("qa_flags", [])
                        flags.append("deepseek_ocr_reviewed")
                        length_ratio = len(candidate_text) / max(1, len(paddle_text))
                        conflict = (
                            confidence >= config.deepseek_review_threshold
                            and similarity < 0.65
                        ) or similarity < 0.25 or length_ratio > 3.0
                        if conflict:
                            region["deepseek_candidate_text"] = candidate_text
                            flags.append("deepseek_ocr_conflict")
                        else:
                            region["paddle_source_text"] = paddle_text
                            region["source_text"] = candidate_text
                            region["source_language"] = _language(candidate_text).value
                            region["action"] = _action(candidate_text).value
                            region["provenance"] = Provenance.DEEPSEEK_OCR.value
                            deepseek_correction_count += 1
                    elif correction.get("error"):
                        region.setdefault("qa_flags", []).append("deepseek_ocr_failed")
            all_regions.extend(merged)

    payload = {
        "schema": "engineering_drawing_ocr_v1",
        "source_pdf": str(pdf_path),
        "config": asdict(config),
        "regions": all_regions,
        "stats": {
            "region_count": len(all_regions),
            "native_region_count": native_count,
            "paddle_region_count": paddle_count,
            "deepseek_review_count": deepseek_count,
            "deepseek_correction_count": deepseek_correction_count,
            "paddle_calls": max(0, stop - max(1, start_page) + 1),
            "deepseek_model_loads": 1 if enable_deepseek and deepseek_count else 0,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(output_path.read_bytes())
    return HybridOcrResult(output_path, len(all_regions), native_count, paddle_count, deepseek_count, False)
