from __future__ import annotations

import html
import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def _page_image(path: Path, dpi: int) -> Image.Image:
    """Render the first PDF page to an RGB image at a fixed resolution."""
    with fitz.open(path) as document:
        pixmap = document[0].get_pixmap(dpi=dpi, alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def render_comparison(
    source_pdf: Path,
    candidate_pdf: Path,
    output_png: Path,
    markers: list[dict],
    dpi: int = 120,
) -> Path:
    """Render source and candidate first pages side-by-side with candidate markers."""
    source = _page_image(source_pdf, dpi)
    candidate = _page_image(candidate_pdf, dpi)
    scale = dpi / 72

    draw = ImageDraw.Draw(candidate)
    for marker in markers:
        if marker.get("side", "candidate") != "candidate":
            continue
        x0, y0, x1, y1 = (float(value) * scale for value in marker["bbox"])
        draw.rectangle(
            (x0, y0, x1, y1),
            outline=(220, 30, 30),
            width=max(2, round(scale)),
        )
        draw.text((x0, max(0, y0 - 12)), str(marker["code"]), fill=(220, 30, 30))

    canvas = Image.new(
        "RGB",
        (source.width + candidate.width, max(source.height, candidate.height)),
        "white",
    )
    canvas.paste(source, (0, 0))
    canvas.paste(candidate, (source.width, 0))

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_png, optimize=True)
    return output_png


def write_benchmark_report(summary: dict, workspace: Path) -> tuple[Path, Path]:
    """Write UTF-8 JSON and an escaped, reader-facing HTML benchmark report."""
    reports = Path(workspace) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    json_path = reports / "benchmark-report.json"
    html_path = reports / "benchmark-report.html"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('sample_id', '')))}</td>"
        f"<td>{html.escape(str(item.get('category', '')))}</td>"
        f"<td>{float(item.get('score', 0)):.1f}</td>"
        f"<td>{int(item.get('hard_failure_count', 0))}</td>"
        f"<td><a href='../{html.escape(str(item.get('comparison_png', '')))}'>查看</a></td>"
        "</tr>"
        for item in summary.get("samples", [])
    )
    html_path.write_text(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<title>Engineering Drawing Benchmark</title>"
        "<style>body{font-family:Arial,\"Microsoft YaHei\",sans-serif;margin:24px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px}</style>"
        "</head><body><h1>Engineering Drawing Benchmark</h1>"
        f"<p>Core score: {float(summary.get('core_score', 0)):.1f}</p>"
        "<table><thead><tr><th>样本</th><th>类别</th><th>得分</th><th>硬失败</th><th>对比</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></body></html>",
        encoding="utf-8",
    )
    return json_path, html_path
