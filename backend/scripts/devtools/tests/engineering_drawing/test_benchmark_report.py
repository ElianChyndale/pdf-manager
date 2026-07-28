from pathlib import Path

import fitz
from PIL import Image

from services.engineering_drawing.benchmark.report import (
    render_comparison,
    write_benchmark_report,
)


def _pdf(path: Path, text: str, *, width: float = 200, height: float = 120) -> None:
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    page.insert_text((10, 20), text)
    document.save(path)
    document.close()


def test_report_writes_side_by_side_png_json_and_html(tmp_path: Path):
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    _pdf(source, "ROOF SYSTEM")
    _pdf(candidate, "ROOF SYSTEM")

    image = render_comparison(
        source,
        candidate,
        tmp_path / "comparison.png",
        [{"side": "candidate", "bbox": [10, 10, 80, 30], "code": "missing_translation"}],
        dpi=72,
    )

    with Image.open(image) as opened:
        assert opened.width == 400
        assert opened.height == 120

    json_path, html_path = write_benchmark_report(
        {
            "schema": "engineering-drawing-benchmark-report-v1",
            "samples": [],
            "core_score": 0,
        },
        tmp_path,
    )

    assert json_path == tmp_path / "reports" / "benchmark-report.json"
    assert json_path.exists()
    assert "Engineering Drawing Benchmark" in html_path.read_text(encoding="utf-8")


def test_report_uses_candidate_page_width_and_escapes_reader_content(tmp_path: Path):
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    _pdf(source, "SOURCE", width=200, height=120)
    _pdf(candidate, "CANDIDATE", width=300, height=180)

    image = render_comparison(
        source,
        candidate,
        tmp_path / "nested" / "comparison.png",
        [{"side": "source", "bbox": [10, 10, 80, 30], "code": "ignore_me"}],
        dpi=72,
    )

    with Image.open(image) as opened:
        assert opened.size == (500, 180)

    json_path, html_path = write_benchmark_report(
        {
            "core_score": 84.25,
            "samples": [
                {
                    "sample_id": "<sample>",
                    "category": "<script>alert(1)</script>",
                    "score": 84.25,
                    "hard_failure_count": 1,
                    "comparison_png": "comparisons/<unsafe>.png",
                }
            ],
        },
        tmp_path,
    )

    assert "<sample>" in json_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")
    assert "&lt;sample&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "comparisons/&lt;unsafe&gt;.png" in html
