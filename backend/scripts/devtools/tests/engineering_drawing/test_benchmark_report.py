import math
import os
from pathlib import Path

import fitz
from PIL import Image
import pytest

from services.engineering_drawing.benchmark import report
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


def _comparison(workspace: Path, name: str = "comparison.png") -> str:
    path = workspace / "comparisons" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1, 1), "white").save(path)
    return path.relative_to(workspace).as_posix()


def _summary(workspace: Path, **changes: object) -> dict:
    value = {
        "schema": "engineering-drawing-benchmark-report-v1",
        "core_score": 84.25,
        "samples": [
            {
                "sample_id": "sample-01",
                "category": "table",
                "score": 84.25,
                "hard_failure_count": 1,
                "comparison_png": _comparison(workspace),
            }
        ],
    }
    value.update(changes)
    return value


def _directory_link_or_skip(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory links unavailable on this host: {error}")


def _file_link_or_skip(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except OSError as error:
        pytest.skip(f"file links unavailable on this host: {error}")


def test_render_comparison_scales_candidate_marker_and_is_deterministic(tmp_path: Path):
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _pdf(source, "ROOF SYSTEM")
    _pdf(candidate, "ROOF SYSTEM")
    marker = {"side": "candidate", "bbox": [10, 10, 80, 30], "code": "missing"}

    render_comparison(source, candidate, first, [marker], dpi=144)
    render_comparison(source, candidate, second, [marker], dpi=144)

    with Image.open(first) as opened:
        assert opened.size == (800, 240)
        assert opened.getpixel((420, 20)) == (220, 30, 30)
        assert opened.getpixel((20, 20)) != (220, 30, 30)
    assert first.read_bytes() == second.read_bytes()


def test_render_comparison_accepts_differing_page_geometries(tmp_path: Path):
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    _pdf(source, "SOURCE", width=200, height=120)
    _pdf(candidate, "CANDIDATE", width=300, height=180)

    image = render_comparison(
        source,
        candidate,
        tmp_path / "comparison.png",
        [{"side": "candidate", "bbox": [10, 10, 80, 30], "code": "missing"}],
        dpi=72,
    )

    with Image.open(image) as opened:
        assert opened.size == (500, 180)


def test_report_accepts_an_empty_canonical_sample_list(tmp_path: Path):
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


@pytest.mark.parametrize("dpi", [0, 301, True, 10**100])
def test_render_comparison_rejects_invalid_dpi_before_opening_pdfs(
    tmp_path: Path, dpi: object
):
    with pytest.raises(ValueError, match="dpi"):
        render_comparison(
            tmp_path / "missing.pdf",
            tmp_path / "also-missing.pdf",
            tmp_path / "comparison.png",
            [],
            dpi=dpi,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "marker",
    [
        {},
        {"side": "source", "bbox": [10, 10, 80, 30], "code": "missing"},
        {"side": "candidate", "bbox": [10, 10, 80, 30], "code": ""},
        {"side": "candidate", "bbox": [10, 10, 80, 30], "code": "x" * 129},
        {"side": "candidate", "bbox": [10, 10, 10, 30], "code": "missing"},
        {"side": "candidate", "bbox": [-1, 10, 80, 30], "code": "missing"},
        {"side": "candidate", "bbox": [10, 10, math.nan, 30], "code": "missing"},
        {"side": "candidate", "bbox": [True, 10, 80, 30], "code": "missing"},
        {"side": "candidate", "bbox": [10, 10, 201, 30], "code": "missing"},
        {
            "side": "candidate",
            "bbox": [10, 10, 80, 30],
            "code": "missing",
            "extra": True,
        },
    ],
)
def test_render_comparison_rejects_malformed_markers(tmp_path: Path, marker: dict):
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    output = tmp_path / "comparison.png"
    _pdf(source, "SOURCE")
    _pdf(candidate, "CANDIDATE")

    with pytest.raises(ValueError, match="marker"):
        render_comparison(source, candidate, output, [marker], dpi=72)

    assert not output.exists()
    assert not list(tmp_path.glob(".comparison-*.tmp"))


@pytest.mark.parametrize("bad_input", ["empty.pdf", "not-a-pdf.txt"])
def test_render_comparison_rejects_unusable_pdf_inputs(
    tmp_path: Path, bad_input: str
):
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    output = tmp_path / "comparison.png"
    _pdf(source, "SOURCE")
    if bad_input == "empty.pdf":
        candidate.write_bytes(b"")
    else:
        candidate = tmp_path / bad_input
        candidate.write_text("not a PDF", encoding="utf-8")

    with pytest.raises((ValueError, fitz.FileDataError)):
        render_comparison(source, candidate, output, [], dpi=72)

    assert not output.exists()


def test_render_comparison_rejects_non_png_destination(tmp_path: Path):
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    _pdf(source, "SOURCE")
    _pdf(candidate, "CANDIDATE")

    with pytest.raises(ValueError, match="output_png"):
        render_comparison(source, candidate, tmp_path / "comparison.jpg", [], dpi=72)


def test_render_comparison_rejects_dangling_symlink_destination(tmp_path: Path):
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    output = tmp_path / "comparison.png"
    outside = tmp_path / "outside.png"
    _pdf(source, "SOURCE")
    _pdf(candidate, "CANDIDATE")
    _file_link_or_skip(output, outside)

    with pytest.raises(ValueError, match="output_png"):
        render_comparison(source, candidate, output, [], dpi=72)

    assert not outside.exists()
    assert not list(tmp_path.glob(".comparison-*.tmp"))


def test_render_comparison_rejects_reparse_parent_destination(tmp_path: Path):
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    outside = tmp_path / "outside"
    output_parent = tmp_path / "linked-output"
    _pdf(source, "SOURCE")
    _pdf(candidate, "CANDIDATE")
    outside.mkdir()
    _directory_link_or_skip(output_parent, outside)

    with pytest.raises(ValueError, match="output_png parent"):
        render_comparison(source, candidate, output_parent / "comparison.png", [], dpi=72)

    assert not (outside / "comparison.png").exists()
    assert not list(outside.glob(".comparison-*.tmp"))


def test_report_writes_atomic_json_html_and_url_quoted_escaped_links(tmp_path: Path):
    comparison = _comparison(tmp_path, "comparison test #1.png")
    summary = _summary(
        tmp_path,
        samples=[
            {
                "sample_id": "<sample>",
                "category": "<script>alert(1)</script>",
                "score": 84.25,
                "hard_failure_count": 1,
                "comparison_png": comparison,
            }
        ],
    )

    json_path, html_path = write_benchmark_report(summary, tmp_path)

    assert json_path == tmp_path / "reports" / "benchmark-report.json"
    assert '"<sample>"' in json_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")
    assert "&lt;sample&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "href='../comparisons/comparison%20test%20%231.png'" in html
    assert "Engineering Drawing Benchmark" in html


def test_report_rejects_comparisons_directory_linked_outside_workspace(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    _directory_link_or_skip(workspace / "comparisons", outside)
    Image.new("RGB", (1, 1), "white").save(outside / "comparison.png")
    summary = {
        "schema": "engineering-drawing-benchmark-report-v1",
        "core_score": 84.25,
        "samples": [
            {
                "sample_id": "sample-01",
                "category": "table",
                "score": 84.25,
                "hard_failure_count": 0,
                "comparison_png": "comparisons/comparison.png",
            }
        ],
    }

    with pytest.raises(ValueError, match="comparison_png"):
        write_benchmark_report(summary, workspace)


@pytest.mark.parametrize(
    "comparison_png",
    [
        "comparison.png",
        "../comparisons/comparison.png",
        "comparisons/../comparison.png",
        "comparisons\\comparison.png",
        "/comparisons/comparison.png",
        "comparisons/comparison.jpg",
    ],
)
def test_report_rejects_unsafe_or_outside_comparison_links(
    tmp_path: Path, comparison_png: str
):
    with pytest.raises(ValueError, match="comparison_png"):
        write_benchmark_report(_summary(tmp_path, samples=[{
            "sample_id": "sample-01",
            "category": "table",
            "score": 84.25,
            "hard_failure_count": 1,
            "comparison_png": comparison_png,
        }]), tmp_path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("schema"),
        lambda value: value.update(schema="wrong"),
        lambda value: value.update(core_score=math.inf),
        lambda value: value.update(core_score=True),
        lambda value: value.update(samples="not-a-list"),
        lambda value: value.update(samples=[{"sample_id": "missing-fields"}]),
        lambda value: value.update(samples=[{
            **value["samples"][0], "sample_id": "x" * 129
        }]),
        lambda value: value.update(samples=[{
            **value["samples"][0], "score": math.nan
        }]),
        lambda value: value.update(samples=[{
            **value["samples"][0], "hard_failure_count": True
        }]),
    ],
)
def test_report_validation_never_replaces_existing_pair(
    tmp_path: Path, mutate: object
):
    reports = tmp_path / "reports"
    reports.mkdir()
    json_path = reports / "benchmark-report.json"
    html_path = reports / "benchmark-report.html"
    json_path.write_text("old-json", encoding="utf-8")
    html_path.write_text("old-html", encoding="utf-8")
    summary = _summary(tmp_path)
    mutate(summary)  # type: ignore[operator]

    with pytest.raises(ValueError):
        write_benchmark_report(summary, tmp_path)

    assert json_path.read_text(encoding="utf-8") == "old-json"
    assert html_path.read_text(encoding="utf-8") == "old-html"
    assert not list(reports.glob(".benchmark-report-*"))


def test_report_rolls_back_pair_when_final_html_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    reports = tmp_path / "reports"
    reports.mkdir()
    json_path = reports / "benchmark-report.json"
    html_path = reports / "benchmark-report.html"
    old_json = b"{\r\n  \"old\": true\r\n}\r\n"
    old_html = b"<html>\r\n<body>old</body>\r\n</html>\r\n"
    json_path.write_bytes(old_json)
    html_path.write_bytes(old_html)
    real_replace = report.os.replace

    def fail_html_replace(source: object, destination: object) -> None:
        if Path(destination).name == "benchmark-report.html":
            raise OSError("simulated publish failure")
        real_replace(source, destination)

    monkeypatch.setattr(report.os, "replace", fail_html_replace)

    with pytest.raises(OSError, match="simulated publish failure"):
        write_benchmark_report(_summary(tmp_path), tmp_path)

    assert json_path.read_bytes() == old_json
    assert html_path.read_bytes() == old_html
    assert not list(reports.glob(".benchmark-report-*"))


def test_report_cleans_staged_files_when_html_staging_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    reports = tmp_path / "reports"
    reports.mkdir()
    json_path = reports / "benchmark-report.json"
    html_path = reports / "benchmark-report.html"
    json_path.write_text("old-json", encoding="utf-8")
    html_path.write_text("old-html", encoding="utf-8")
    real_stage = report._stage_text
    calls = 0

    def fail_second_stage(directory: Path, content: str) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated staging failure")
        return real_stage(directory, content)

    monkeypatch.setattr(report, "_stage_text", fail_second_stage)

    with pytest.raises(OSError, match="simulated staging failure"):
        write_benchmark_report(_summary(tmp_path), tmp_path)

    assert json_path.read_text(encoding="utf-8") == "old-json"
    assert html_path.read_text(encoding="utf-8") == "old-html"
    assert not list(reports.glob(".benchmark-report-*"))
