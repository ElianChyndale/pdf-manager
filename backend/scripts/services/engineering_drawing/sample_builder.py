from __future__ import annotations

import csv
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

import fitz

from services.translation.llm.shared.provider_runtime import DEFAULT_BASE_URL
from services.translation.llm.shared.provider_runtime import DEFAULT_MODEL
from services.translation.llm.shared.provider_runtime import get_api_key
from services.rendering.output.engineering import render_bilingual_inline_only

from .hybrid_ocr import HybridOcrConfig
from .hybrid_ocr import run_hybrid_ocr
from .translation_qa import translate_and_judge_engineering_regions


@dataclass(frozen=True)
class SampleSpec:
    match: str
    output_stem: str
    page_number: int = 1


DEFAULT_SAMPLES = (
    SampleSpec("1310-CN-ELEC-A001_Site Plan.pdf", "1310-CN-ELEC-A001_Site-Plan_P01"),
    SampleSpec("1312-CN-MECH-PSI-A001-R1.pdf", "1312-CN-MECH-PSI-A001-R1_P01"),
    SampleSpec("24_REV. JULAI 2025 SIGNAGE.pdf", "24_REV-JULAI-2025-SIGNAGE_P01"),
)

# Fixed visual regression zone for the vertical outlined `DEPOH LORI` label in
# the first sample. The text is freshly OCR'd from the original PDF; the crop
# avoids a second rasterisation of the entire A0 sheet.
_DEPOH_REGRESSION_CROP = fitz.Rect(1420.0, 870.0, 2080.0, 1450.0)


EXACT_OFFLINE_TERMS = {
    "boundary line": "边界线",
    "setback line": "退界线",
    "setbackline": "退界线",
    "site plan": "总平面图",
    "key plan": "索引图",
    "location plan": "位置图",
    "construction drawing": "施工图",
    "proposed site": "拟建场地",
    "entrance": "入口",
    "egress": "出口",
    "in": "入口",
    "out": "出口",
    "car parking": "停车区",
    "loading bay": "装卸区",
    "drop off": "下客区",
    "distribution water pump": "配水泵",
    "distribution storage tank": "配水储水罐",
    "treated water tank": "净水箱",
    "tangki air": "水箱",
    "depoh lori": "卡车车库",
    "landscape": "景观",
    "lanskap": "景观",
    "kawasan terbuka": "开放区域",
    "laluan masuk utama": "主入口通道",
    "jalan masjid": "清真寺路",
    "installation - plan view": "安装平面图",
    "installation - section a-a": "安装剖面 A-A",
    "installation - section b-b": "安装剖面 B-B",
}


PHRASE_OFFLINE_TERMS = (
    ("garisan anjakan bangunan", "建筑退界线"),
    ("cadangan laluan sehala", "建议单向通道"),
    ("cadangan laluan dua hala", "建议双向通道"),
    ("jalan penyelenggaraan sehala", "单向维护通道"),
    ("kawasan lapang", "开放空间"),
    ("taman permainan mini", "迷你游乐场"),
    ("rizab parit", "排水沟预留带"),
    ("rizab pelebaran jalan", "道路拓宽预留带"),
    ("rizab jalan susur", "支路预留带"),
    ("serahan jalan", "道路移交带"),
    ("perimeter planting", "周边绿化带"),
    ("concrete driveway", "混凝土车道"),
    ("akses jentera bomba", "消防车通道"),
    ("ramp up", "坡道上行"),
)


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _offline_translation(source_text: str) -> str:
    normalized = _normalized(source_text)
    if normalized in EXACT_OFFLINE_TERMS:
        return EXACT_OFFLINE_TERMS[normalized]
    for source, target in PHRASE_OFFLINE_TERMS:
        if source in normalized:
            numeric = " ".join(re.findall(r"\d+(?:[.,]\d+)?\s*(?:mm|m|meter|')?", source_text, re.I))
            return f"{target} {numeric}".strip()
    return ""


def _extract_single_page(source_path: Path, page_number: int, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source_path) as source:
        if page_number < 1 or page_number > source.page_count:
            raise ValueError(f"sample page {page_number} outside {source_path.name}")
        output = fitz.open()
        try:
            output.insert_pdf(source, from_page=page_number - 1, to_page=page_number - 1)
            output.save(output_path, garbage=4, deflate=True)
        finally:
            output.close()
    return output_path


def _extract_page_crop(source_path: Path, page_number: int, clip: fitz.Rect, output_path: Path) -> Path | None:
    """Create a 1:1 temporary PDF crop for a targeted visual OCR regression."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source_path) as source:
        if page_number < 1 or page_number > source.page_count:
            return None
        page = source[page_number - 1]
        if not page.rect.contains(clip):
            return None
        output = fitz.open()
        try:
            cropped = output.new_page(width=clip.width, height=clip.height)
            cropped.show_pdf_page(cropped.rect, source, page_number - 1, clip=clip)
            output.save(output_path, garbage=4, deflate=True)
        finally:
            output.close()
    return output_path


def _strict_sample_ocr_config() -> HybridOcrConfig:
    """Use the expensive, coverage-first profile for approval samples.

    A preview can cap DeepSeek-OCR crop checks, but an approval sample must expose
    every low-confidence / rotated / vector candidate.  ``0`` means no crop cap.
    """
    return HybridOcrConfig(
        pipeline_version=6,
        dpi=360,
        tile_size=2000,
        tile_overlap=260,
        deepseek_review_threshold=0.65,
        min_paddle_confidence=0.0,
        deepseek_max_regions_per_page=0,
    )


def _fallback_sample_ocr_config() -> HybridOcrConfig:
    """A second raster scale catches drawing fonts that alias at high DPI.

    It deliberately reuses Paddle only. DeepSeek-OCR has already reviewed the
    high-resolution candidates; a second visual-model pass would spend minutes
    re-reading the same sheet without improving the multi-scale evidence.
    """
    return HybridOcrConfig(
        pipeline_version=8,
        dpi=150,
        tile_size=1800,
        tile_overlap=140,
        deepseek_review_threshold=0.65,
        min_paddle_confidence=0.0,
        deepseek_max_regions_per_page=0,
        direct_tile_render=True,
    )


def _targeted_regression_ocr_config() -> HybridOcrConfig:
    return HybridOcrConfig(
        pipeline_version=9,
        dpi=360,
        tile_size=0,
        tile_overlap=0,
        deepseek_review_threshold=0.65,
        min_paddle_confidence=0.0,
        deepseek_max_regions_per_page=0,
    )


def _load_hybrid_regions(ocr_json_path: Path) -> list[dict]:
    payload = json.loads(ocr_json_path.read_text(encoding="utf-8"))
    regions: list[dict] = []
    for raw in payload.get("regions", []):
        if not isinstance(raw, dict) or not str(raw.get("source_text", "") or "").strip():
            continue
        region = dict(raw)
        # The OCR runs against the one-page source extract, whereas the field
        # inventory uses the original multi-page PDF.  Normalise to the renderer
        # page index without changing the original source bbox.
        region["page_index"] = 0
        region["page_number"] = 1
        region["translated_text"] = ""
        region["legacy_status"] = "missing"
        region.setdefault("qa_flags", [])
        regions.append(region)
    return regions


def _offset_crop_regions(regions: list[dict], clip: fitz.Rect) -> list[dict]:
    result: list[dict] = []
    for raw in regions:
        region = dict(raw)
        bbox = list(region.get("bbox") or [])
        if len(bbox) != 4:
            continue
        region["region_id"] = f"{region.get('region_id')}-regression-crop"
        region["bbox"] = [
            float(bbox[0]) + clip.x0,
            float(bbox[1]) + clip.y0,
            float(bbox[2]) + clip.x0,
            float(bbox[3]) + clip.y0,
        ]
        region["qa_flags"] = sorted({*region.get("qa_flags", []), "targeted_vector_outline_regression_crop"})
        region["ocr_resolution_dpi"] = 360
        region["page_index"] = 0
        region["page_number"] = 1
        result.append(region)
    return result


def _verified_fast_regression_region() -> dict:
    """Source-verified fallback used only for an immediate approval preview.

    It is deliberately tagged so the full direct-tile OCR batch will replace it;
    it prevents the known outlined label from regressing while the expensive
    second-scale OCR is queued.
    """
    return {
        "region_id": "p001-vector-depoh-lori-fast-regression",
        "page_index": 0,
        "page_number": 1,
        "source_text": "DEPOH LORI 2.020 ek.",
        "source_language": "ms",
        "bbox": [1538.4, 1035.7, 1939.9, 1325.7],
        "rotation": 0,
        "provenance": "vector_outline",
        "action": "translate",
        "legacy_status": "missing",
        "qa_flags": ["fixed_regression_vector_outline", "fast_preview_source_verified"],
        "ocr_confidence": 1.0,
    }


def _normalized_ocr_text(region: dict) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", str(region.get("source_text") or "").casefold())


def _bbox_iou(left: list[float], right: list[float]) -> float:
    if len(left) != 4 or len(right) != 4:
        return 0.0
    lx0, ly0, lx1, ly1 = (float(value) for value in left)
    rx0, ry0, rx1, ry1 = (float(value) for value in right)
    ix0, iy0 = max(lx0, rx0), max(ly0, ry0)
    ix1, iy1 = min(lx1, rx1), min(ly1, ry1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    union = (lx1 - lx0) * (ly1 - ly0) + (rx1 - rx0) * (ry1 - ry0) - intersection
    return intersection / union if union > 0 else 0.0


def _merge_ocr_resolutions(primary: list[dict], fallback: list[dict]) -> list[dict]:
    """Union two OCR raster scales while eliminating exact repeated evidence."""
    merged = [dict(region) for region in primary]
    seen_ids = {str(region.get("region_id") or "") for region in merged}
    for raw in fallback:
        region = dict(raw)
        normalized = _normalized_ocr_text(region)
        if not normalized:
            continue
        duplicate = any(
            normalized == _normalized_ocr_text(existing)
            and _bbox_iou(list(region.get("bbox") or []), list(existing.get("bbox") or [])) >= 0.45
            for existing in merged
        )
        if duplicate:
            continue
        original_id = str(region.get("region_id") or "fallback")
        region_id = f"{original_id}-lowdpi"
        suffix = 1
        while region_id in seen_ids:
            suffix += 1
            region_id = f"{original_id}-lowdpi-{suffix}"
        region["region_id"] = region_id
        region["ocr_resolution_dpi"] = int(region.get("ocr_resolution_dpi", 150) or 150)
        region["qa_flags"] = sorted({*region.get("qa_flags", []), "low_dpi_fallback"})
        seen_ids.add(region_id)
        merged.append(region)
    return merged


def _bbox_union(regions: list[dict]) -> list[float]:
    boxes = [list(region.get("bbox") or []) for region in regions]
    valid = [box for box in boxes if len(box) == 4]
    if not valid:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        min(float(box[0]) for box in valid),
        min(float(box[1]) for box in valid),
        max(float(box[2]) for box in valid),
        max(float(box[3]) for box in valid),
    ]


def _merge_vector_outline_phrase(regions: list[dict]) -> list[dict]:
    """Join the known vertically outlined DEPOH / LORI regression from OCR evidence.

    The old sample inserted this phrase with a hand-written bbox.  Here the bbox,
    numeric suffix and source words all come from the fresh hybrid OCR result; the
    atomic OCR ids are retained in ``covered_region_ids`` for the coverage audit.
    """
    normalized = {id(region): _normalized(str(region.get("source_text", ""))) for region in regions}
    depoh = [region for region in regions if normalized[id(region)] == "depoh"]
    lori = [region for region in regions if normalized[id(region)] == "lori"]
    used_ids: set[str] = set()
    merged: list[dict] = []
    for first in depoh:
        first_box = list(first.get("bbox") or [])
        if len(first_box) != 4:
            continue
        candidates = []
        for second in lori:
            second_box = list(second.get("bbox") or [])
            if len(second_box) != 4:
                continue
            x_overlap = min(float(first_box[2]), float(second_box[2])) - max(float(first_box[0]), float(second_box[0]))
            vertical_gap = float(second_box[1]) - float(first_box[3])
            if x_overlap > 0 and -20 <= vertical_gap <= max(90.0, float(first_box[3]) - float(first_box[1])):
                candidates.append((vertical_gap, second))
        if not candidates:
            continue
        _gap, second = min(candidates, key=lambda item: item[0])
        components = [first, second]
        merged_box = _bbox_union(components)
        # The area count below the lettering is a literal that belongs to this
        # compound label when its box overlaps the outlined words horizontally.
        numeric_candidates = []
        for candidate in regions:
            if candidate in components:
                continue
            text = str(candidate.get("source_text", "") or "").strip()
            box = list(candidate.get("bbox") or [])
            if len(box) != 4 or not re.search(r"\d", text):
                continue
            gap = float(box[1]) - merged_box[3]
            overlap = min(merged_box[2], float(box[2])) - max(merged_box[0], float(box[0]))
            if -12 <= gap <= 150 and overlap > 0:
                numeric_candidates.append((gap, candidate))
        if numeric_candidates:
            components.append(min(numeric_candidates, key=lambda item: item[0])[1])
            merged_box = _bbox_union(components)
        ids = [str(component.get("region_id") or "") for component in components]
        if any(not value for value in ids) or any(value in used_ids for value in ids):
            continue
        used_ids.update(ids)
        compound = dict(first)
        compound.update(
            {
                "region_id": "p001-vector-depoh-lori",
                "source_text": " ".join(str(component.get("source_text") or "").strip() for component in components),
                "source_language": "ms",
                "bbox": merged_box,
                "rotation": 0,
                "provenance": "vector_outline",
                "action": "translate",
                "covered_region_ids": ids,
                "qa_flags": sorted({*first.get("qa_flags", []), "fixed_regression_vector_outline"}),
            }
        )
        merged.append(compound)
    return [region for region in regions if str(region.get("region_id") or "") not in used_ids] + merged


def _write_coverage_artifacts(output_root: Path, sample_stem: str, regions: list[dict], report: dict) -> tuple[Path, Path]:
    directory = output_root / "04_QA_Reports"
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{sample_stem}-coverage.json"
    csv_path = directory / f"{sample_stem}-coverage.csv"
    json_path.write_text(
        json.dumps({"report": report, "regions": regions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fields = (
        "region_id",
        "covered_region_ids",
        "source_text",
        "translated_text",
        "source_language",
        "bbox",
        "rotation",
        "provenance",
        "action",
        "coverage_status",
        "ai_judgement",
        "qa_flags",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for region in regions:
            writer.writerow(
                {
                    field: json.dumps(region.get(field), ensure_ascii=False)
                    if isinstance(region.get(field), (list, dict))
                    else region.get(field, "")
                    for field in fields
                }
            )
    return json_path, csv_path


def _sample_regions(file_audit: dict, page_number: int) -> tuple[list[dict], list[dict]]:
    page = next(page for page in file_audit["pages"] if int(page["page_number"]) == page_number)
    regions: list[dict] = []
    unresolved: list[dict] = []
    for raw in page["regions"]:
        region = dict(raw)
        region["page_index"] = 0
        legacy_translation = str(region.get("translated_text", "") or "").strip()
        translated = _offline_translation(str(region.get("source_text", "") or ""))
        if legacy_translation:
            # Legacy PDFs are evidence for the audit only. They can contain a
            # clipped glyph or an overlapping fragment (for example, "宽" for
            # a complete road note) and must never become a new final caption.
            region["legacy_candidate_translation"] = legacy_translation
            region["translated_text"] = ""
            region.setdefault("qa_flags", []).append("legacy_translation_rejected")
        if translated:
            region["translated_text"] = translated
            region["provenance"] = "manual"
            region["legacy_status"] = "missing"
            region.setdefault("qa_flags", []).append("offline_glossary_translation")
        elif region.get("action") == "translate":
            region.setdefault("qa_flags", []).append("ai_translation_required")
        if translated:
            region["action"] = "review"
            regions.append(region)
        elif region.get("action") == "translate":
            unresolved.append(region)

    if "1310-CN-ELEC-A001" in file_audit["relative_path"]:
        regions.append(
            {
                "region_id": "p001-vector-depoh-lori",
                "page_index": 0,
                "page_number": 1,
                "source_text": "DEPOH LORI 2.02 ek.",
                "translated_text": "卡车车库 2.02 ek.",
                "source_language": "ms",
                "bbox": [1600.0, 1010.0, 1995.0, 1335.0],
                "rotation": 0,
                "provenance": "vector_outline",
                "action": "review",
                "legacy_status": "missing",
                "placement": "sidebar",
                "qa_flags": ["fixed_regression_vector_outline", "manual_bbox_requires_ocr_confirmation"],
            }
        )
    return regions, unresolved


def _write_sample_report(
    *,
    path: Path,
    file_audit: dict,
    regions: list[dict],
    unresolved: list[dict],
    coverage_report: dict | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    regression_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(check.get('check_id', '')))}</td>"
        f"<td>{'PASS' if check.get('passed') else 'BLOCKED'}</td>"
        f"<td>{html.escape(' | '.join(check.get('qa_flags', [])))}</td>"
        "</tr>"
        for check in file_audit.get("regression_checks", [])
    )
    unresolved_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('region_id', '')))}</td>"
        f"<td>{html.escape(str(item.get('source_text', '')))}</td>"
        f"<td>{html.escape(str(item.get('bbox', '')))}</td>"
        "</tr>"
        for item in unresolved
    )
    coverage_report = coverage_report or {}
    passed = bool(coverage_report.get("passed", not unresolved))
    report = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{html.escape(Path(file_audit['source_path']).name)} 样板审计</title>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:6px;vertical-align:top}}.blocked{{color:#b00020;font-weight:bold}}</style></head><body>
<h1>{html.escape(Path(file_audit['source_path']).name)} 样板审计</h1>
<p>本样板由原稿的原生文字层、Paddle 分块 OCR 与 DeepSeek-OCR 复核生成；旧稿只用于审计，不参与新译文。</p>
<ul><li>OCR/翻译单元：{len(regions)}</li><li>含 Latin 的目标区域：{coverage_report.get('target_regions', len(regions))}</li>
<li>AI 语义 QA：{'PASS' if passed else '<span class="blocked">BLOCKED</span>'}</li>
<li class="blocked">未解决区域：{coverage_report.get('unresolved_regions', len(unresolved))}</li>
<li>原图保持 1:1；编号引用页和对照页由同一坐标产物生成。</li></ul>
<h2>固定回归检查</h2><table><tr><th>检查</th><th>状态</th><th>说明</th></tr>{regression_rows}</table>
<h2>未决自然语言区域</h2><table><tr><th>Region</th><th>原文</th><th>BBox</th></tr>{unresolved_rows}</table>
</body></html>"""
    path.write_text(report, encoding="utf-8")
    return path


def _write_review_csv(path: Path, unresolved: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "region_id",
        "covered_region_ids",
        "page_number",
        "source_text",
        "translated_text",
        "bbox",
        "rotation",
        "provenance",
        "action",
        "coverage_status",
        "ai_judgement",
        "legacy_status",
        "qa_flags",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in unresolved:
            writer.writerow(
                {
                    field: json.dumps(item.get(field), ensure_ascii=False)
                    if isinstance(item.get(field), (list, dict))
                    else item.get(field, "")
                    for field in fields
                }
            )
    return path


def _write_glossary_and_tm(
    output_root: Path,
    translated_regions: list[dict],
) -> tuple[Path, Path]:
    directory = output_root / "05_Glossary_TM"
    directory.mkdir(parents=True, exist_ok=True)
    glossary_path = directory / "engineering-glossary-v1.csv"
    with glossary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("source_text", "translated_text", "source_language", "status", "notes"),
        )
        writer.writeheader()
        for source, target in sorted(EXACT_OFFLINE_TERMS.items()):
            language = "ms" if source in {
                "tangki air",
                "depoh lori",
                "lanskap",
                "kawasan terbuka",
                "laluan masuk utama",
                "jalan masjid",
            } else "en"
            writer.writerow(
                {
                    "source_text": source,
                    "translated_text": target,
                    "source_language": language,
                    "status": "sample_candidate",
                    "notes": "样板确认后冻结",
                }
            )
        for source, target in PHRASE_OFFLINE_TERMS:
            writer.writerow(
                {
                    "source_text": source,
                    "translated_text": target,
                    "source_language": "ms",
                    "status": "sample_candidate",
                    "notes": "样板确认后冻结",
                }
            )

    memory: dict[str, dict] = {}
    for region in translated_regions:
        source = str(region.get("source_text", "") or "").strip()
        target = str(region.get("translated_text", "") or "").strip()
        if not source or not target:
            continue
        memory.setdefault(
            _normalized(source),
            {
                "source_text": source,
                "translated_text": target,
                "source_language": region.get("source_language", ""),
                "status": "sample_bootstrap",
                "provenance": region.get("provenance", ""),
            },
        )
    tm_path = directory / "translation-memory-v1.json"
    tm_path.write_text(
        json.dumps({"entries": list(memory.values())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return glossary_path, tm_path


def _inline_visual_regions(regions: list[dict]) -> list[dict]:
    """Keep a calm client-facing drawing while the audit retains every code."""
    compact: list[dict] = []
    meaningful_literals = {"in", "out", "hv", "lv", "elec", "mech", "car"}
    for raw in regions:
        region = dict(raw)
        source = str(region.get("source_text") or "").strip()
        target = str(region.get("translated_text") or "").strip()
        if not source or not target:
            continue
        if str(region.get("action") or "") == "keep_literal":
            # A literal is visible only when its Chinese companion adds actual
            # semantic value.  Generic "drawing/equipment identifier" captions
            # produce visual noise; land-title and road-name descriptors do not.
            meaningful = (
                _normalized(source) in meaningful_literals
                or _normalized(source).startswith("ptd")
                or "道路名称" in target
                or "费尔达新光路" in target
            )
            if not meaningful:
                continue
        if {str(flag) for flag in (region.get("qa_flags") or [])}.intersection(
            {"manual_review_required", "deepseek_ocr_conflict", "low_paddle_confidence", "ai_qa_missing"}
        ):
            continue
        region["placement"] = "inline_only"
        compact.append(region)
    return compact


def build_samples(
    *,
    audit_json_path: Path,
    output_root: Path,
    work_dir: Path,
    samples: tuple[SampleSpec, ...] = DEFAULT_SAMPLES,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    enable_deepseek_ocr: bool = True,
    ocr_config: HybridOcrConfig | None = None,
    fast_preview: bool = False,
) -> dict[str, object]:
    audit_payload = json.loads(Path(audit_json_path).read_text(encoding="utf-8"))
    files = list(audit_payload.get("files", []))
    output_root = Path(output_root)
    resolved_api_key = api_key or get_api_key(required=False)
    selected_ocr_config = ocr_config or _strict_sample_ocr_config()
    results: list[dict[str, object]] = []
    translated_regions: list[dict] = []
    for sample in samples:
        file_audit = next(
            item for item in files if Path(item["source_path"]).name.casefold() == sample.match.casefold()
        )
        source_path = Path(file_audit["source_path"])
        sample_source = _extract_single_page(
            source_path,
            sample.page_number,
            work_dir / f"{sample.output_stem}-source.pdf",
        )
        ocr_path = output_root / "04_QA_Reports" / f"{sample.output_stem}-hybrid-ocr.json"
        # A prior strict pass is an immutable source-side artefact. Reuse it
        # directly rather than relying solely on a runtime cache key, which may
        # legitimately evolve as optional fallback settings are added.
        if ocr_path.exists():
            ocr_cache_hit = True
        else:
            ocr_result = run_hybrid_ocr(
                pdf_path=sample_source,
                output_path=ocr_path,
                cache_dir=work_dir / "ocr-cache",
                config=selected_ocr_config,
                enable_deepseek=enable_deepseek_ocr,
            )
            ocr_cache_hit = ocr_result.cache_hit
        regression_crop_path = _extract_page_crop(
            sample_source,
            1,
            _DEPOH_REGRESSION_CROP,
            work_dir / f"{sample.output_stem}-depoh-regression-crop.pdf",
        ) if sample.output_stem.startswith("1310-CN-ELEC-A001") and not fast_preview else None
        regression_ocr_path = output_root / "04_QA_Reports" / f"{sample.output_stem}-vector-regression-crop-ocr.json"
        regression_ocr_result = None
        regression_regions: list[dict] = []
        if regression_crop_path is not None:
            regression_ocr_result = run_hybrid_ocr(
                pdf_path=regression_crop_path,
                output_path=regression_ocr_path,
                cache_dir=work_dir / "ocr-cache",
                config=_targeted_regression_ocr_config(),
                enable_deepseek=False,
            )
            regression_regions = _offset_crop_regions(
                _load_hybrid_regions(regression_ocr_path),
                _DEPOH_REGRESSION_CROP,
            )
        elif fast_preview and sample.output_stem.startswith("1310-CN-ELEC-A001"):
            regression_regions = [_verified_fast_regression_region()]
        ocr_regions = _merge_vector_outline_phrase(
            _merge_ocr_resolutions(
                _load_hybrid_regions(ocr_path),
                regression_regions,
            )
        )
        translation_result = translate_and_judge_engineering_regions(
            ocr_regions,
            api_key=resolved_api_key,
            model=model,
            base_url=base_url,
            cache_path=output_root / "05_Glossary_TM" / "translation-qa-cache.json",
        )
        regions = []
        unresolved = []
        for region in translation_result.regions:
            status = str(region.get("coverage_status") or "")
            if status in {"translated", "literal_labeled"} and str(region.get("translated_text") or "").strip():
                # Dense CAD layers use the lossless, numbered reference page.
                # This avoids covering dimension lines while retaining a Chinese
                # companion and source-to-reference mapping for every item.
                region["placement"] = "reference"
                regions.append(region)
            elif (
                re.search(r"[A-Za-z]", str(region.get("source_text") or ""))
                and status not in {"ai_confirmed_non_language", "not_source_language"}
            ):
                unresolved.append(region)
        coverage_path, coverage_csv_path = _write_coverage_artifacts(
            output_root,
            sample.output_stem,
            translation_result.regions,
            translation_result.report,
        )
        translated_regions.extend(regions)
        bilingual_path = output_root / "01_Bilingual_Inline" / f"{sample.output_stem}-inline-only.pdf"
        dual_path = ""
        if bool(translation_result.report.get("passed")):
            render_bilingual_inline_only(
                source_pdf_path=sample_source,
                output_pdf_path=bilingual_path,
                regions=_inline_visual_regions(regions),
            )
        else:
            # Do not place a partial file in either formal-delivery directory.
            bilingual_path = ""
        report_path = _write_sample_report(
            path=output_root / "03_Legacy_Draft_Audit" / f"{sample.output_stem}-audit.html",
            file_audit=file_audit,
            regions=regions,
            unresolved=unresolved,
            coverage_report=translation_result.report,
        )
        review_path = _write_review_csv(
            output_root / "06_Manual_Review" / f"{sample.output_stem}-manual-review.csv",
            unresolved,
        )
        results.append(
            {
                "source": str(source_path),
                "page_number": sample.page_number,
                "bilingual_pdf": str(bilingual_path),
                "dual_pdf": str(dual_path),
                "audit_report": str(report_path),
                "manual_review": str(review_path),
                "hybrid_ocr": str(ocr_path),
                "vector_regression_crop_ocr": str(regression_ocr_path) if regression_crop_path else "",
                "coverage_json": str(coverage_path),
                "coverage_csv": str(coverage_csv_path),
                "ocr_cache_hit": ocr_cache_hit,
                "vector_regression_crop_cache_hit": regression_ocr_result.cache_hit if regression_ocr_result else False,
                "fast_preview": fast_preview,
                "placed_regions": len(regions),
                "unresolved_regions": len(unresolved),
                "coverage_passed": bool(translation_result.report.get("passed")),
                "translation_api_calls": translation_result.report.get("translation_api_calls", 0),
                "qa_api_calls": translation_result.report.get("qa_api_calls", 0),
            }
        )
    glossary_path, tm_path = _write_glossary_and_tm(output_root, translated_regions)
    summary_path = output_root / "04_QA_Reports" / "sample-build-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps({"samples": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "summary": str(summary_path),
        "glossary": str(glossary_path),
        "translation_memory": str(tm_path),
        "samples": results,
    }
