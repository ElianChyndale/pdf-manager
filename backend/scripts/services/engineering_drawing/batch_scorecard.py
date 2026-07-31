"""Batch-level KPI scorecard for V4 engineering-drawing deliveries.

Single-page metrics already exist per run (``visual_qa.analyze_visual_qa``,
the translation-QA coverage report, and the stage closure values in the
orchestration harness).  This module aggregates them into a batch scorecard so
a deliverable can be judged by critical-error rate, unprocessed-English rate,
manual-review rate and closure pass rate instead of a single accuracy number.

All metrics degrade gracefully: when an artifact is missing the metric is
reported as ``None`` and the missing artifact is recorded in
``missing_artifacts`` — the scorecard never raises on incomplete input.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

SCORECARD_SCHEMA = "engineering-drawing-batch-scorecard-v1"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _load_list(path: Path) -> list[Any] | None:
    payload = _load_json(path)
    if payload is None:
        return None
    items = payload.get("placements", payload) if isinstance(payload, dict) else payload
    return items if isinstance(items, list) else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    num, den = _float(numerator), _float(denominator)
    if num is None or den is None or den <= 0:
        return None
    return round(num / den, 4)


def compute_run_metrics(
    *,
    work_dir: Path,
    translation_qa_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate one run's work_dir artifacts into per-run KPIs."""
    work_dir = Path(work_dir)
    missing: list[str] = []
    metrics: dict[str, Any] = {}

    stage4 = _load_json(work_dir / "stage4-rendered-candidate.json")
    if stage4 is None:
        missing.append("stage4-rendered-candidate.json")
    visual_qa = _load_json(work_dir / "visual-qa.json")
    if visual_qa is None:
        missing.append("visual-qa.json")
    timing = _load_json(work_dir / "timing.json")
    if timing is None:
        missing.append("timing.json")
    delivery = _load_json(work_dir / "delivery-manifest.json")

    # run identity
    metrics["run_id"] = str((stage4 or {}).get("run_id") or "")
    metrics["workflow_version"] = str((stage4 or {}).get("workflow_version") or "")
    metrics["policy_fingerprint"] = str((stage4 or {}).get("policy_fingerprint") or "")
    if delivery:
        metrics["delivery_id"] = str(delivery.get("delivery_id") or "")
        metrics["renderer"] = str((delivery.get("renderer") or {}).get("name") or "")
        metrics["operator"] = dict(delivery.get("operator") or {})
    else:
        missing.append("delivery-manifest.json")

    # page count
    pages = None
    page_pngs = sorted(work_dir.glob("page-*.png"))
    if page_pngs:
        pages = len(page_pngs)
    if pages is None and stage4 and stage4.get("candidate_pdf"):
        try:
            import fitz

            with fitz.open(str(stage4["candidate_pdf"])) as document:
                pages = document.page_count
        except Exception:
            pages = None
    metrics["pages"] = pages

    # coverage counts
    qa_report = translation_qa_report or _load_json(work_dir / "translation-qa-report.json")
    total = translated = literal = manual = unresolved = None
    if qa_report:
        total = int(qa_report.get("source_regions") or 0)
        translated = int(qa_report.get("translated_regions") or 0)
        literal = int(qa_report.get("literal_labeled_regions") or 0)
        manual = int(qa_report.get("manual_review_regions") or 0)
        unresolved = int(qa_report.get("unresolved_regions") or 0)
    elif stage4:
        blocks = stage4.get("blocks") or []
        total = len(blocks)
        translated = sum(1 for b in blocks if str(b.get("status") or "") == "translated")
        literal = 0
        manual = sum(1 for b in blocks if str(b.get("status") or "") == "manual_review")
        unresolved = manual
    metrics["total_regions"] = total
    metrics["translated_regions"] = translated
    metrics["literal_labeled_regions"] = literal
    metrics["manual_review_regions"] = manual
    metrics["unresolved_regions"] = unresolved

    # error rates
    hard_findings = list((stage4 or {}).get("hard_findings") or [])
    untranslated = int((visual_qa or {}).get("untranslated_candidate_count") or 0)
    critical_errors = len(hard_findings) + untranslated + int(unresolved or 0)
    metrics["hard_finding_count"] = len(hard_findings)
    metrics["critical_error_rate"] = _safe_ratio(critical_errors, total)
    metrics["unprocessed_english_rate"] = _safe_ratio(untranslated, total)
    metrics["numeric_identifier_preservation"] = _safe_ratio(literal, total)
    metrics["manual_review_rate"] = _safe_ratio(manual, total)

    # closure
    whole_page = _float((stage4 or {}).get("whole_page_closure"))
    metrics["whole_page_closure"] = whole_page
    metrics["closure_pass_rate"] = 1.0 if whole_page == 1.0 else (None if whole_page is None else 0.0)

    # visual collisions
    overlap = int((visual_qa or {}).get("visual_overlap_count") or 0)
    leaders = int((visual_qa or {}).get("leader_collision_count") or 0)
    metrics["visual_collision_count"] = overlap + leaders

    # timing
    stage_ms = dict((timing or {}).get("stage_ms") or {})
    for key, value in (timing or {}).items():
        if key.endswith("_ms") and isinstance(value, (int, float)):
            stage_ms[key] = round(float(value), 1)
    metrics["stage_ms"] = stage_ms
    total_elapsed = sum(value for value in stage_ms.values() if isinstance(value, (int, float)))
    metrics["total_elapsed_ms"] = round(total_elapsed, 1)
    metrics["per_page_elapsed_ms"] = _safe_ratio(total_elapsed, pages)

    metrics["missing_artifacts"] = sorted(set(missing))
    return metrics


def scorecard_from_work_dirs(
    *,
    work_roots: Iterable[Path],
    translation_qa_reports: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Aggregate a batch report over many run work directories."""
    roots = [Path(path) for path in work_roots]
    runs = []
    qa_reports = dict(translation_qa_reports or {})
    for work_dir in roots:
        if not work_dir.is_dir():
            continue
        report_path = qa_reports.get(str(work_dir), work_dir / "translation-qa-report.json")
        qa_payload = _load_json(Path(report_path))
        runs.append(compute_run_metrics(work_dir=work_dir, translation_qa_report=qa_payload))
    return _aggregate(runs)


def scorecard_from_formal_dir(*, formal_dir: Path) -> dict[str, Any]:
    """Aggregate a batch report from a formal directory (sidecars + manifests).

    Without per-run work_dir artifacts the coverage/KPI metrics are unavailable;
    the report records page counts and delivery manifest provenance for each PDF
    and reports the rest as missing.
    """
    formal_dir = Path(formal_dir)
    runs: list[dict[str, Any]] = []
    for pdf in sorted(formal_dir.glob("*.pdf")):
        stem = pdf.stem
        manifest = _load_json(formal_dir / f"{stem}.delivery-manifest.json")
        sidecar = _load_json(formal_dir / f"{stem}.release-authorization.json")
        run: dict[str, Any] = {
            "run_id": str((manifest or {}).get("run_id") or stem),
            "workflow_version": str((manifest or {}).get("workflow_version") or ""),
            "policy_fingerprint": str((manifest or {}).get("policy_fingerprint") or ""),
            "delivery_id": str((manifest or {}).get("delivery_id") or ""),
            "renderer": str((manifest or {}).get("renderer") or {}).get("name", "") if isinstance((manifest or {}).get("renderer"), dict) else "",
            "pages": _formal_pdf_page_count(pdf),
            "release_authorization": {
                "schema": str((sidecar or {}).get("schema") or ""),
                "authorization_kind": str((sidecar or {}).get("authorization_kind") or ""),
            },
        }
        if manifest is None:
            run["missing_artifacts"] = ["delivery-manifest.json"]
        if sidecar is None:
            run["missing_artifacts"] = run.get("missing_artifacts", []) + ["release-authorization.json"]
        runs.append(run)
    return _aggregate(runs)


def _formal_pdf_page_count(pdf: Path) -> int | None:
    try:
        import fitz

        with fitz.open(pdf) as document:
            return document.page_count
    except Exception:
        return None


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute batch-level averages over the per-run rows."""
    def _avg(key: str) -> float | None:
        values = [run[key] for run in runs if run.get(key) is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 4)

    return {
        "schema": SCORECARD_SCHEMA,
        "runs": runs,
        "run_count": len(runs),
        "pages_total": sum(run["pages"] for run in runs if run.get("pages") is not None) or None,
        "translated_total": sum(run["translated_regions"] for run in runs if run.get("translated_regions") is not None) or None,
        "literal_only_total": sum(run["literal_labeled_regions"] for run in runs if run.get("literal_labeled_regions") is not None) or None,
        "manual_review_total": sum(run["manual_review_regions"] for run in runs if run.get("manual_review_regions") is not None) or None,
        "critical_error_rate_avg": _avg("critical_error_rate"),
        "unprocessed_english_rate_avg": _avg("unprocessed_english_rate"),
        "numeric_identifier_preservation_avg": _avg("numeric_identifier_preservation"),
        "manual_review_rate_avg": _avg("manual_review_rate"),
        "closure_pass_rate_avg": _avg("closure_pass_rate"),
        "visual_collision_total": sum(run["visual_collision_count"] for run in runs if run.get("visual_collision_count") is not None) or None,
        "total_elapsed_ms": sum(run["total_elapsed_ms"] for run in runs if run.get("total_elapsed_ms") is not None) or None,
    }


def build_scorecard_html(report: Mapping[str, Any]) -> str:
    """Static escaped HTML table for a scorecard report."""
    rows = []
    for run in report.get("runs") or []:
        cells = [
            html.escape(str(run.get("run_id") or "")),
            html.escape(str(run.get("delivery_id") or "")),
            html.escape(str(run.get("renderer") or "")),
            _html_value(run.get("pages")),
            _html_value(run.get("total_regions")),
            _html_value(run.get("translated_regions")),
            _html_value(run.get("literal_labeled_regions")),
            _html_value(run.get("manual_review_regions")),
            _html_value(run.get("critical_error_rate")),
            _html_value(run.get("unprocessed_english_rate")),
            _html_value(run.get("manual_review_rate")),
            _html_value(run.get("closure_pass_rate")),
            _html_value(run.get("visual_collision_count")),
            _html_value(run.get("total_elapsed_ms")),
            html.escape(", ".join(run.get("missing_artifacts") or [])),
        ]
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")

    header = (
        "<tr><th>run_id</th><th>delivery_id</th><th>renderer</th><th>pages</th>"
        "<th>regions</th><th>translated</th><th>literal</th><th>manual_review</th>"
        "<th>crit_error</th><th>unprocessed_en</th><th>manual_rate</th>"
        "<th>closure</th><th>collisions</th><th>elapsed_ms</th><th>missing</th></tr>"
    )
    summary = [
        ("run_count", _html_value(report.get("run_count"))),
        ("pages_total", _html_value(report.get("pages_total"))),
        ("critical_error_rate_avg", _html_value(report.get("critical_error_rate_avg"))),
        ("unprocessed_english_rate_avg", _html_value(report.get("unprocessed_english_rate_avg"))),
        ("manual_review_rate_avg", _html_value(report.get("manual_review_rate_avg"))),
        ("closure_pass_rate_avg", _html_value(report.get("closure_pass_rate_avg"))),
        ("visual_collision_total", _html_value(report.get("visual_collision_total"))),
    ]
    summary_rows = "".join(
        f"<tr><td>{html.escape(key)}</td><td>{value}</td></tr>" for key, value in summary
    )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Engineering-Drawing V4 Batch Scorecard</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px}"
        "</style></head><body>"
        "<h1>Engineering-Drawing V4 Batch Scorecard</h1>"
        "<p>Metrics are aggregated from per-run work-dir artifacts. Missing "
        "artifacts are reported, never a hard failure.</p>"
        "<h2>Batch summary</h2><table>" + summary_rows + "</table>"
        "<h2>Per-run rows</h2><table>" + header + "".join(rows) + "</table>"
        "</body></html>"
    )


def _html_value(value: Any) -> str:
    if value is None:
        return "<em>n/a</em>"
    return html.escape(str(value))


__all__ = [
    "SCORECARD_SCHEMA",
    "build_scorecard_html",
    "compute_run_metrics",
    "scorecard_from_formal_dir",
    "scorecard_from_work_dirs",
]
