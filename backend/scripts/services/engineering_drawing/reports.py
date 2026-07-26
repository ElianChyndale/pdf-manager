from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Iterable

import fitz
from PIL import Image, ImageDraw

from .legacy_audit import AuditResult, FileAudit
from .models import LegacyStatus


FLAGGED_STATUSES = {
    LegacyStatus.MISSING.value,
    LegacyStatus.PARTIAL.value,
    LegacyStatus.BAD_TRANSLATION.value,
    LegacyStatus.LAYOUT_DEFECT.value,
}


def _rows(result: AuditResult) -> Iterable[dict[str, object]]:
    for file_audit in result.files:
        for page in file_audit.pages:
            for region in page.regions:
                if region.legacy_status.value not in FLAGGED_STATUSES:
                    continue
                yield {
                    "relative_path": file_audit.relative_path,
                    "legacy_translation_path": file_audit.legacy_translation_path,
                    "page_number": page.page_number,
                    "region_id": region.region_id,
                    "source_text": region.source_text,
                    "translated_text": region.translated_text,
                    "source_language": region.source_language.value,
                    "bbox": json.dumps(region.bbox.to_list()),
                    "rotation": region.rotation,
                    "provenance": region.provenance.value,
                    "action": region.action.value,
                    "legacy_status": region.legacy_status.value,
                    "placement": region.placement.value,
                    "qa_flags": "|".join(region.qa_flags),
                }


def write_json(result: AuditResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def write_csv(result: AuditResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "relative_path",
        "legacy_translation_path",
        "page_number",
        "region_id",
        "source_text",
        "translated_text",
        "source_language",
        "bbox",
        "rotation",
        "provenance",
        "action",
        "legacy_status",
        "placement",
        "qa_flags",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_rows(result))
    return path


def _status_table(file_audit: FileAudit) -> str:
    counts = file_audit.status_counts()
    cells = "".join(
        f"<td>{html.escape(status)}: {count}</td>"
        for status, count in counts.items()
    )
    return f"<table class='counts'><tr>{cells}</tr></table>"


def write_html(
    result: AuditResult,
    path: Path,
    *,
    screenshot_dir: Path | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []
    for file_audit in result.files:
        flagged = [
            row
            for row in _rows(AuditResult({}, [file_audit]))
        ]
        rows = "".join(
            "<tr>"
            f"<td>{row['page_number']}</td>"
            f"<td>{html.escape(str(row['source_text']))}</td>"
            f"<td>{html.escape(str(row['translated_text']))}</td>"
            f"<td>{html.escape(str(row['legacy_status']))}</td>"
            f"<td>{html.escape(str(row['qa_flags']))}</td>"
            "</tr>"
            for row in flagged
        )
        screenshots = ""
        if screenshot_dir:
            matches = sorted(screenshot_dir.glob(f"{file_audit.content_hash[:12]}-p*.png"))
            screenshots = "".join(
                f"<a href='screenshots/{html.escape(image.name)}'><img src='screenshots/{html.escape(image.name)}' alt='flagged page'></a>"
                for image in matches
            )
        sections.append(
            "<section>"
            f"<h2>{html.escape(file_audit.relative_path)}</h2>"
            f"<p>Legacy: {html.escape(file_audit.legacy_translation_path or 'missing')}</p>"
            f"{_status_table(file_audit)}"
            f"<div class='screens'>{screenshots}</div>"
            "<table><thead><tr><th>Page</th><th>Source</th><th>Legacy Chinese</th>"
            "<th>Status</th><th>Flags</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            "</section>"
        )
    status_counts = result.to_dict()["status_counts"]
    summary = " · ".join(f"{key}: {value}" for key, value in status_counts.items())
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Engineering Drawing Legacy Draft Audit</title>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;color:#202124}}
h1{{margin-bottom:4px}}section{{border-top:2px solid #ddd;margin-top:30px;padding-top:14px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border:1px solid #ddd;padding:6px;vertical-align:top}}
.counts{{width:auto;margin:8px 0}}.screens{{display:flex;gap:8px;overflow:auto}}
.screens img{{max-width:440px;max-height:320px;border:1px solid #ccc}}
</style></head><body>
<h1>Engineering Drawing Legacy Draft Audit</h1>
<p>{html.escape(summary)}</p>
{''.join(sections)}
</body></html>"""
    path.write_text(document, encoding="utf-8")
    return path


def _render_page(page: fitz.Page, dpi: int) -> Image.Image:
    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def write_flagged_screenshots(
    file_audit: FileAudit,
    output_dir: Path,
    *,
    dpi: int = 110,
) -> list[Path]:
    if not file_audit.legacy_translation_path:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with fitz.open(file_audit.source_path) as source_doc, fitz.open(
        file_audit.legacy_translation_path
    ) as legacy_doc:
        scale = dpi / 72
        for page_audit in file_audit.pages:
            flagged = [
                region
                for region in page_audit.regions
                if region.legacy_status.value in FLAGGED_STATUSES
            ]
            if not flagged or page_audit.page_number > legacy_doc.page_count:
                continue
            page_index = page_audit.page_number - 1
            source_image = _render_page(source_doc[page_index], dpi)
            legacy_image = _render_page(legacy_doc[page_index], dpi)
            draw_source = ImageDraw.Draw(source_image)
            for region in flagged:
                x0, y0, x1, y1 = region.bbox.to_list()
                draw_source.rectangle(
                    (x0 * scale, y0 * scale, x1 * scale, y1 * scale),
                    outline=(220, 30, 30),
                    width=max(2, round(scale)),
                )
            canvas = Image.new(
                "RGB",
                (source_image.width + legacy_image.width, max(source_image.height, legacy_image.height)),
                "white",
            )
            canvas.paste(source_image, (0, 0))
            canvas.paste(legacy_image, (source_image.width, 0))
            output_path = (
                output_dir
                / f"{file_audit.content_hash[:12]}-p{page_audit.page_number:03d}.png"
            )
            canvas.save(output_path, optimize=True)
            written.append(output_path)
    return written


def write_report_bundle(
    result: AuditResult,
    output_dir: str | Path,
    *,
    screenshots: bool = False,
    dpi: int = 110,
) -> dict[str, object]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    screenshot_dir = output_path / "screenshots"
    screenshot_paths: list[Path] = []
    if screenshots:
        for file_audit in result.files:
            screenshot_paths.extend(
                write_flagged_screenshots(file_audit, screenshot_dir, dpi=dpi)
            )
    json_path = write_json(result, output_path / "legacy-audit.json")
    csv_path = write_csv(result, output_path / "legacy-audit.csv")
    html_path = write_html(
        result,
        output_path / "legacy-audit.html",
        screenshot_dir=screenshot_dir if screenshots else None,
    )
    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
        "screenshots": [str(path) for path in screenshot_paths],
    }
