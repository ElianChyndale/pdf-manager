from __future__ import annotations

"""Legacy sequential batch runner retained for audit compatibility only.

The production entry point is ``agent_batch.run_agent_bootstrap`` followed by
an approved single-supervisor plan. This module must not publish a PDF by
itself; the explicit environment override below exists only for historical
tests and forensic reproduction.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Iterable

import fitz

from services.rendering.output.engineering import render_bilingual_inline_only

from .codex_review import apply_codex_review_plan
from .codex_review import build_codex_review_package
from .codex_review import validate_codex_review_plan
from .legacy_transfer import extract_legacy_translation_regions
from .semantic_grouping import build_semantic_groups
from .visual_qa import analyze_visual_qa
from .workflow_policy import LAYOUT_POLICY
from .workflow_policy import SEMANTIC_GROUP_POLICY
from .workflow_policy import SOL_MODEL
from .workflow_policy import WORKFLOW_VERSION


SCHEMA = "engineering-drawing-batch-v2"
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_SOURCE_DIR_NAMES = (
    "报审图纸",
    "A3 DETAIL DRAWING",
    "03_CONSTRUCTION DWG_MASJID_11 NOV 2025",
)
_REFERENCE_DIR_NAMES = (
    "Translated Drawing 图纸翻译",
    "清真寺施工图纸 11112025 翻译",
)
_INLINE_POLICY = dict(LAYOUT_POLICY)
_INLINE_POLICY.update(
    {
        "workflow_version": WORKFLOW_VERSION,
        "semantic_group_policy": "block-level semantic grouping before translation and placement",
        "semantic_grouping": SEMANTIC_GROUP_POLICY,
    }
)


# These are deliberately conservative labels used only for the two source PDFs
# that have no human-translated reference file. They seed a reference layer so
# the same renderer and audit path can still be used; they are not a replacement
# for a future human/Sol review of those sheets.
_OFFLINE_TERMS = {
    "sprinkler tank": "喷淋水箱",
    "ballast stone": "压载石",
    "trenches": "沟槽",
    "depth": "深度",
    "genset": "发电机组",
    "canopy type": "雨棚型",
    "sump pit": "集水坑",
    "hose reel tank": "消防软管卷盘水箱",
    "rwht tank": "雨水收集水箱",
    "effective volume": "有效容积",
    "layer": "层",
    "nos.": "个",
    "pvc pipe": "PVC 管",
    "clamp core": "箝位铁芯",
    "hv-side": "高压侧",
    "lv-side": "低压侧",
    "lanskap": "景观",
    "landscape": "景观",
    "masjid": "清真寺",
    "pelan bumbung keseluruhan": "总屋顶平面图",
    "pelan bumbung": "屋顶平面图",
    "pelan menara": "宣礼塔平面图",
    "pandangan hadapan": "正立面图",
    "pandangan belakang": "后立面图",
    "pandangan sisi kanan": "右侧立面图",
    "pandangan sisi kiri": "左侧立面图",
    "keratan": "剖面",
    "ruang solat muslimah": "女士礼拜区",
    "ruang solat muslimin": "男士礼拜区",
    "ruang solat": "礼拜区",
    "ruang wudhu muslimah": "女士小净室",
    "ruang wudhu muslimin": "男士小净室",
    "ruang wudhu": "小净室",
    "bilik jenazah": "殡仪室",
    "bilik jamuan": "宴会厅",
    "bilik imam": "伊玛目室",
    "bilik msb": "主配电室",
    "ruang limpah": "储物间",
    "ruang": "区域",
    "tandas muslimah": "女士卫生间",
    "tandas muslimin": "男士卫生间",
    "tandas": "卫生间",
    "koridor": "走廊",
    "laluan masuk": "入口通道",
    "laluan pejalan kaki": "人行通道",
    "laluan": "通道",
    "pantri": "茶水间",
    "janitor": "清洁间",
    "kolah": "水池",
    "qiblat": "朝向",
    "menara": "宣礼塔",
    "bumbung": "屋顶",
    "tingkat bawah": "首层",
    "jadual pintu": "门表",
    "jadual tingkap": "窗表",
    "tender table": "招标表",
    "construction drawing": "施工图",
    "zon solat utama / ruang limpah": "主礼拜区/储物间",
    "zon tandas / ruang wudhu / bilik jenazah / bilik jamuan/ utiliti": "卫生间/小净室/殡仪室/宴会厅/设备间",
    "zon tandas / ruang wudhu / bilik jenazah / bilik jamuan / utiliti": "卫生间/小净室/殡仪室/宴会厅/设备间",
    "laluan": "通道",
    "pelan tingkat bawah": "首层平面图",
    "jadual tingkap": "窗表",
    "jadual pintu": "门表",
    "drawing title": "图纸标题",
    "drawing status": "图纸状态",
    "tender": "招标",
    "construction": "施工",
    "preliminary": "初步",
    "information": "资料",
    "tarikh": "日期",
    "dilukis oleh": "绘图",
    "disemak oleh": "审核",
    "no. lukisan": "图纸编号",
    "skala": "比例",
    "bil .": "编号",
    "bil.": "编号",
    "pindaan": "修订",
    "projek": "项目",
    "arkitek": "建筑师",
    "jurutera sivil dan struktur": "土木与结构工程师",
    "jurutera mekanikal": "机械工程师",
    "jurukur bahan": "工料测量师",
    "agensi pelaksana": "执行机构",
    "perunding landskap": "景观顾问",
    "pemilik bangunan": "建筑业主",
    "cadangan meroboh dan membina semula masjid": "拆除并重建清真寺建议",
    "discrepancies must be reported": "如有差异，施工前必须立即报告建筑师",
    "contractors must check all dimensions on site": "承包商必须在现场核对所有尺寸",
    "only figured dimensions are to be worked": "施工仅按标注尺寸进行",
}


def _normalized_stem(value: str) -> str:
    text = Path(value).stem
    text = re.sub(r"[_\-]?translated$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[_\-]?翻译$", "", text)
    text = re.sub(r"[_\-]?r1(?=\b|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def _safe_slug(source: Path, root: Path) -> str:
    relative = source.relative_to(root)
    category = re.sub(r"[^A-Za-z0-9]+", "_", relative.parts[0]).strip("_") or "drawing"
    stem = re.sub(r"[^A-Za-z0-9]+", "_", source.stem).strip("_") or "sheet"
    digest = hashlib.sha1(str(relative).encode("utf-8")).hexdigest()[:10]
    return f"{category}__{stem}__{digest}"


def _translated_category(source: Path, root: Path) -> str:
    """Keep report drawings separate from the mosque construction set."""
    relative = source.relative_to(root)
    return "01_报审图纸" if relative.parts and relative.parts[0] == "报审图纸" else "02_清真寺施工图纸"


def _page_geometry(path: Path) -> list[tuple[float, float]]:
    with fitz.open(path) as document:
        return [(float(page.rect.width), float(page.rect.height)) for page in document]


def _same_geometry(left: Path, right: Path) -> bool:
    a, b = _page_geometry(left), _page_geometry(right)
    return len(a) == len(b) and all(
        abs(width_a - width_b) <= 0.5 and abs(height_a - height_b) <= 0.5
        for (width_a, height_a), (width_b, height_b) in zip(a, b)
    )


def discover_sources(root: Path) -> list[Path]:
    sources: list[Path] = []
    for directory_name in _SOURCE_DIR_NAMES:
        directory = root / directory_name
        if directory.exists():
            sources.extend(sorted(directory.rglob("*.pdf"), key=lambda path: str(path).casefold()))
    return sources


def discover_references(root: Path) -> list[Path]:
    references: list[Path] = []
    for directory_name in _REFERENCE_DIR_NAMES:
        directory = root / directory_name
        if directory.exists():
            references.extend(sorted(directory.rglob("*.pdf"), key=lambda path: str(path).casefold()))
    return references


def match_reference(source: Path, references: Iterable[Path], root: Path) -> Path | None:
    candidates = [path for path in references if _normalized_stem(path.name) == _normalized_stem(source.name)]
    if not candidates:
        return None
    same_geometry = [path for path in candidates if _same_geometry(source, path)]
    if same_geometry:
        candidates = same_geometry
    preferred = "Translated Drawing 图纸翻译" if source.relative_to(root).parts[0] == "报审图纸" else "清真寺施工图纸 11112025 翻译"
    candidates.sort(key=lambda path: (0 if preferred in path.parts else 1, str(path).casefold()))
    return candidates[0]


def _baseline_plan(source: Path) -> dict:
    return {
        "schema": "engineering-drawing-codex-review-v1",
        "model": SOL_MODEL,
        "status": "approved",
        "review_mode": "codex_sol_v2_block_semantic_layout_policy",
        "review_version": WORKFLOW_VERSION,
        "page_sizes": [[width, height] for width, height in _page_geometry(source)],
        "remove_region_ids": [],
        "moves": [],
        "additions": [],
        "coverage": [],
        "layout_policy": _INLINE_POLICY,
        "reason": "V2 semantic grouping and visual-safe placement are required before sheet-specific Sol review; preserve authoritative legacy captions only as explicit manual-review fallbacks.",
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_text_lines(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    result: list[tuple[str, fitz.Rect]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = " ".join(
                str(span.get("text") or "").strip()
                for span in line.get("spans", [])
                if str(span.get("text") or "").strip()
            ).strip()
            if text:
                result.append((text, fitz.Rect(line["bbox"])))
    return result


def _offline_translation(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip().casefold()
    if not normalized or not re.search(r"[a-z]", normalized):
        return ""
    for source, target in sorted(_OFFLINE_TERMS.items(), key=lambda item: len(item[0]), reverse=True):
        if source in normalized:
            if normalized == source:
                return target
            suffix = re.sub(re.escape(source), "", text, flags=re.IGNORECASE).strip(" :,-")
            return f"{target} {suffix}".strip()
    return ""


def build_offline_reference(source: Path, output: Path, font_path: Path) -> int:
    """Create a conservative CJK reference layer for a source with no reference."""
    inserted = 0
    source_document = fitz.open(source)
    output_document = fitz.open()
    try:
        output_document.insert_pdf(source_document)
        for page_index, source_page in enumerate(source_document):
            page = output_document[page_index]
            for text, source_rect in _extract_text_lines(source_page):
                translated = _offline_translation(text)
                if not translated:
                    continue
                font_size = max(4.0, min(8.0, source_rect.height * 0.72))
                width = min(max(44.0, source_rect.width), page.rect.width - source_rect.x1 - 4.0)
                if width < 44.0:
                    width = min(180.0, page.rect.width - 8.0)
                    target = fitz.Rect(source_rect.x0, source_rect.y1 + 3.0, source_rect.x0 + width, source_rect.y1 + 3.0 + font_size * 1.6)
                else:
                    target = fitz.Rect(source_rect.x1 + 4.0, source_rect.y0, source_rect.x1 + 4.0 + width, source_rect.y0 + font_size * 1.6)
                target = target & page.rect
                if target.is_empty:
                    continue
                # CJK glyph metrics need more vertical leading than the source
                # line height. Grow the box until the text actually fits so an
                # offline fallback never silently produces a zero-translation page.
                result = -1.0
                for height_factor in (1.6, 2.0, 2.4, 2.8):
                    candidate = fitz.Rect(
                        target.x0,
                        target.y0,
                        target.x1,
                        min(page.rect.y1, target.y0 + font_size * height_factor),
                    )
                    result = page.insert_textbox(
                        candidate,
                        translated,
                        fontname="engineering_zh",
                        fontsize=font_size,
                        fontfile=str(font_path),
                        color=(0.08, 0.20, 0.58),
                        overlay=True,
                    )
                    if result >= 0:
                        inserted += 1
                        break
        output.parent.mkdir(parents=True, exist_ok=True)
        output_document.save(output, garbage=4, deflate=True)
    finally:
        output_document.close()
        source_document.close()
    return inserted


def _discover_existing_plans(output_root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    manifests = sorted(output_root.rglob("*.translation-sources.json"), key=lambda path: path.stat().st_mtime)
    for manifest in manifests:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            source = str(payload.get("source_pdf") or "")
            plan = str((payload.get("sol_review") or {}).get("plan") or "")
            if source and plan and Path(plan).exists():
                found[str(Path(source).resolve()).casefold()] = Path(plan)
        except (OSError, ValueError, TypeError):
            continue
    return found


def _render_manifest(
    source: Path,
    reference: Path,
    regions: list[dict],
    result,
    audit_path: Path,
    plan: dict | None,
    *,
    source_legacy_region_count: int | None = None,
) -> dict:
    return {
        "schema": "engineering-drawing-legacy-transfer-v2",
        "workflow_version": WORKFLOW_VERSION,
        "source_pdf": str(source.resolve()),
        "legacy_pdf": str(reference.resolve()),
        "legacy_regions": regions,
        "semantic_groups": regions,
        "source_legacy_region_count": source_legacy_region_count or len(regions),
        "semantic_group_count": len(regions),
        "paragraph_block_count": sum(
            str(region.get("semantic_group_kind") or "") == "paragraph_block"
            for region in regions
        ),
        "strict_additions": [],
        "sol_review": {
            "model": SOL_MODEL,
            "status": plan.get("status") if plan else "approved",
            "review_mode": plan.get("review_mode", "codex_sol_policy_baseline") if plan else "codex_sol_policy_baseline",
            "removed": len(plan.get("remove_region_ids", [])) if plan else 0,
            "moves": len(plan.get("moves", [])) if plan else 0,
            "additions": len(plan.get("additions", [])) if plan else 0,
            "coverage": len(plan.get("coverage", [])) if plan else 0,
        },
        "render": {
            "inline_placements": result.inline_placements,
            "review_items": result.review_items,
            "placement_audit": str(audit_path.resolve()),
        },
    }


def _qa(source: Path, output: Path, audit_path: Path, manifest: dict) -> dict:
    with fitz.open(source) as source_document, fitz.open(output) as output_document:
        output_page_count = output_document.page_count
        geometry_equal = source_document.page_count == output_document.page_count and all(
            abs(source_document[index].rect.width - output_document[index].rect.width) <= 0.5
            and abs(source_document[index].rect.height - output_document[index].rect.height) <= 0.5
            for index in range(source_document.page_count)
        )
        text = "\n".join(page.get_text() for page in output_document)
    placements = json.loads(audit_path.read_text(encoding="utf-8")).get("placements", [])
    statuses = Counter(str(item.get("status") or "") for item in placements)
    bad_statuses = [status for status in statuses if status.startswith("rejected")]
    visual = analyze_visual_qa(
        output_pdf_path=output,
        placement_audit_path=audit_path,
    )
    qa = {
        "pages": output_page_count,
        "geometry_equal": geometry_equal,
        "legacy_regions": int(manifest.get("source_legacy_region_count", len(manifest.get("legacy_regions", []))),),
        "semantic_groups": int(manifest.get("semantic_group_count", len(manifest.get("legacy_regions", []))),),
        "inline_placements": len(placements),
        "review_items": int(manifest.get("render", {}).get("review_items", 0)),
        "placement_statuses": dict(statuses),
        "rejected_statuses": bad_statuses,
        "cjk_characters": sum(1 for char in text if _CJK_RE.search(char)),
        "replacement_characters": text.count("\ufffd"),
        "private_use_characters": sum(1 for char in text if "\ue000" <= char <= "\uf8ff"),
        **visual,
    }
    qa["passed"] = (
        geometry_equal
        and not bad_statuses
        and text.count("\ufffd") == 0
        and sum(1 for char in text if "\ue000" <= char <= "\uf8ff") == 0
        and bool(visual["passed"])
    )
    return qa


def run_batch(*, root: Path, output_root: Path) -> dict:
    if os.environ.get("ENGINEERING_DRAWING_ALLOW_LEGACY_BATCH") != "1":
        raise RuntimeError(
            "legacy engineering-drawing batch is disabled; use "
            "services.engineering_drawing.cli agent-bootstrap and an approved "
            "single-supervisor plan"
        )
    root = Path(root)
    output_root = Path(output_root)
    final_dir = output_root / "translated"
    artifact_root = output_root / "batch-artifacts"
    final_dir.mkdir(parents=True, exist_ok=True)
    for category in ("01_报审图纸", "02_清真寺施工图纸"):
        (final_dir / category).mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir(parents=True, exist_ok=True)
    font_path = Path(__file__).resolve().parents[3] / "fonts" / "SourceHanSerifSC-Regular.otf"

    sources = discover_sources(root)
    references = discover_references(root)
    existing_plans = _discover_existing_plans(output_root)
    results: list[dict] = []
    for index, source in enumerate(sources, start=1):
        slug = _safe_slug(source, root)
        artifact_dir = artifact_root / slug
        artifact_dir.mkdir(parents=True, exist_ok=True)
        reference = match_reference(source, references, root)
        offline_reference = False
        if reference is None:
            reference = artifact_dir / "offline-reference.pdf"
            inserted = build_offline_reference(source, reference, font_path)
            offline_reference = True
        print(f"[{index}/{len(sources)}] {source.name} -> {reference.name}{' (offline)' if offline_reference else ''}", flush=True)
        record = {
            "source_pdf": str(source.resolve()),
            "reference_pdf": str(reference.resolve()),
            "output_pdf": "",
            "artifact_dir": str(artifact_dir.resolve()),
            "offline_reference": offline_reference,
            "status": "error",
        }
        try:
            legacy_regions = extract_legacy_translation_regions(
                source_pdf_path=source,
                legacy_pdf_path=reference,
            )
            regions = build_semantic_groups(legacy_regions)
            draft_path = artifact_dir / "draft.pdf"
            draft_result = render_bilingual_inline_only(
                source_pdf_path=source,
                output_pdf_path=draft_path,
                regions=regions,
                max_local_distance=96.0,
                draw_leaders=True,
                preserve_legacy_position=True,
            )
            draft_audit = draft_path.with_suffix(".inline-placement.json")
            draft_manifest = _render_manifest(
                source,
                reference,
                regions,
                draft_result,
                draft_audit,
                None,
                source_legacy_region_count=len(legacy_regions),
            )
            _write_json(draft_path.with_suffix(".translation-sources.json"), draft_manifest)
            build_codex_review_package(
                source_pdf_path=source,
                draft_pdf_path=draft_path,
                regions=regions,
                placement_audit=json.loads(draft_audit.read_text(encoding="utf-8")).get("placements", []),
                output_dir=artifact_dir / "sol-review-package",
                dpi=96,
            )

            plan_source = existing_plans.get(str(source.resolve()).casefold())
            plan_payload = None
            if plan_source is not None:
                candidate = json.loads(plan_source.read_text(encoding="utf-8"))
                if candidate.get("review_version") == WORKFLOW_VERSION:
                    plan_payload = candidate
            plan = validate_codex_review_plan(
                plan_payload or _baseline_plan(source),
                source_pdf_path=source,
            )
            if plan_payload is not None:
                plan["review_mode"] = "codex_sol_v2_sheet_specific"
            plan_path = artifact_dir / "sol-review-plan.json"
            _write_json(plan_path, plan)
            reviewed_regions = apply_codex_review_plan(regions, plan)
            final_work_path = artifact_dir / "final.pdf"
            final_result = render_bilingual_inline_only(
                source_pdf_path=source,
                output_pdf_path=final_work_path,
                regions=reviewed_regions,
                max_local_distance=96.0,
                draw_leaders=True,
                preserve_legacy_position=True,
            )
            final_audit = final_work_path.with_suffix(".inline-placement.json")
            final_manifest = _render_manifest(
                source,
                reference,
                reviewed_regions,
                final_result,
                final_audit,
                plan,
                source_legacy_region_count=len(legacy_regions),
            )
            _write_json(final_work_path.with_suffix(".translation-sources.json"), final_manifest)
            build_codex_review_package(
                source_pdf_path=source,
                draft_pdf_path=final_work_path,
                regions=reviewed_regions,
                placement_audit=json.loads(final_audit.read_text(encoding="utf-8")).get("placements", []),
                output_dir=artifact_dir / "final-review-package",
                dpi=96,
            )
            qa = _qa(source, final_work_path, final_audit, final_manifest)
            _write_json(artifact_dir / "qa.json", qa)
            output_pdf = final_dir / _translated_category(source, root) / f"{slug}.pdf"
            # Never publish a draft before every release gate has passed.  In
            # particular, a geometry-valid PDF can still fail coverage or
            # visual QA.  Stage the accepted file beside the destination and
            # atomically replace the prior delivery only after PASS.
            # Legacy batch output is audit-only. Production publication is
            # exclusively authorized by authorization.authorize_release().
            record.update(
                {
                    "output_pdf": "",
                    "status": "legacy_candidate_only" if qa["passed"] else "qa_failed",
                    "legacy_regions": len(legacy_regions),
                    "semantic_groups": len(regions),
                    "inline_placements": final_result.inline_placements,
                    "review_items": final_result.review_items,
                    "qa": qa,
                }
            )
        except Exception as exc:  # Keep the batch moving and preserve the failure context.
            record["error"] = f"{type(exc).__name__}: {exc}"
            _write_json(artifact_dir / "error.json", record)
        results.append(record)
        print(f"    {record['status']}", flush=True)
    summary = {
        "schema": SCHEMA,
        "workflow_version": WORKFLOW_VERSION,
        "model": SOL_MODEL,
        "source_count": len(sources),
        "passed": sum(item.get("status") == "passed" for item in results),
        "qa_failed": sum(item.get("status") == "qa_failed" for item in results),
        "errors": sum(item.get("status") == "error" for item in results),
        "offline_reference_count": sum(bool(item.get("offline_reference")) for item in results),
        "translated_dir": str(final_dir.resolve()),
        "translated_categories": {
            "report": str((final_dir / "01_报审图纸").resolve()),
            "mosque": str((final_dir / "02_清真寺施工图纸").resolve()),
        },
        "artifact_dir": str(artifact_root.resolve()),
        "items": results,
    }
    _write_json(artifact_root / "batch-index.json", summary)
    print(json.dumps({key: summary[key] for key in ("source_count", "passed", "qa_failed", "errors", "offline_reference_count")}, ensure_ascii=False, indent=2))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sequentially translate all engineering drawing PDFs.")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    summary = run_batch(root=args.root, output_root=args.output_root)
    return 0 if not summary["errors"] and not summary["qa_failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
