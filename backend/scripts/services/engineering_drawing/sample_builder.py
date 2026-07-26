from __future__ import annotations

import csv
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

import fitz

from services.rendering.output.engineering import render_bilingual_overlay
from services.rendering.output.engineering import render_source_chinese_dual


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


def _sample_regions(file_audit: dict, page_number: int) -> tuple[list[dict], list[dict]]:
    page = next(page for page in file_audit["pages"] if int(page["page_number"]) == page_number)
    regions: list[dict] = []
    unresolved: list[dict] = []
    for raw in page["regions"]:
        region = dict(raw)
        region["page_index"] = 0
        translated = str(region.get("translated_text", "") or "").strip()
        if not translated:
            translated = _offline_translation(str(region.get("source_text", "") or ""))
            if translated:
                region["translated_text"] = translated
                region["provenance"] = "manual"
                region["legacy_status"] = "missing"
                region.setdefault("qa_flags", []).append("offline_glossary_translation")
        else:
            region.setdefault("qa_flags", []).append("legacy_bootstrap_requires_fresh_translation")
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
    report = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{html.escape(Path(file_audit['source_path']).name)} 样板审计</title>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:6px;vertical-align:top}}.blocked{{color:#b00020;font-weight:bold}}</style></head><body>
<h1>{html.escape(Path(file_audit['source_path']).name)} 样板审计</h1>
<p>本报告是无云端凭证条件下的布局与缺漏修复样板，不是术语冻结后的正式译稿。</p>
<ul><li>已放置中文伴随项：{len(regions)}</li><li class="blocked">仍需 OCR/新翻译：{len(unresolved)}</li>
<li>原稿保持 1:1；旧稿未覆盖，仅用于缺漏审计和临时布局验证。</li></ul>
<h2>固定回归检查</h2><table><tr><th>检查</th><th>状态</th><th>说明</th></tr>{regression_rows}</table>
<h2>未决自然语言区域</h2><table><tr><th>Region</th><th>原文</th><th>BBox</th></tr>{unresolved_rows}</table>
</body></html>"""
    path.write_text(report, encoding="utf-8")
    return path


def _write_review_csv(path: Path, unresolved: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ("region_id", "page_number", "source_text", "bbox", "rotation", "provenance", "action", "legacy_status", "qa_flags")
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


def build_samples(
    *,
    audit_json_path: Path,
    output_root: Path,
    work_dir: Path,
    samples: tuple[SampleSpec, ...] = DEFAULT_SAMPLES,
) -> dict[str, object]:
    audit_payload = json.loads(Path(audit_json_path).read_text(encoding="utf-8"))
    files = list(audit_payload.get("files", []))
    output_root = Path(output_root)
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
        regions, unresolved = _sample_regions(file_audit, sample.page_number)
        translated_regions.extend(regions)
        bilingual_path = output_root / "01_Bilingual_Inline" / f"{sample.output_stem}-bilingual.pdf"
        dual_path = output_root / "02_Source_Chinese_Dual" / f"{sample.output_stem}-dual.pdf"
        render_bilingual_overlay(
            source_pdf_path=sample_source,
            output_pdf_path=bilingual_path,
            regions=regions,
        )
        render_source_chinese_dual(
            source_pdf_path=sample_source,
            output_pdf_path=dual_path,
            regions=regions,
        )
        report_path = _write_sample_report(
            path=output_root / "03_Legacy_Draft_Audit" / f"{sample.output_stem}-audit.html",
            file_audit=file_audit,
            regions=regions,
            unresolved=unresolved,
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
                "placed_regions": len(regions),
                "unresolved_regions": len(unresolved),
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
