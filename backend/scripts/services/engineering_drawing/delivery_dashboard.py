"""Live production dashboard + canary-based resource prediction.

Aggregates batch state into a human-readable dashboard (Total / Completed /
Planning / OCR / Review / Failed / Estimated completion) and, once a canary has
produced real per-page timings, projects the full 273-page (or actual) batch
completion using measured minutes/page, DeepSeek calls/page and review
regions/page instead of theoretical estimates.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

DASHBOARD_SCHEMA = "engineering-drawing-delivery-dashboard-v1"

_STATE_GROUPS = {
    "completed": {"released", "release_ready"},
    "planning": {"awaiting_supervisor_plan", "supervisor_plan_ready", "supervisor_plan_invalid"},
    "ocr": {"ocr", "translation"},
    "review": {"review_required", "repairing", "qa"},
    "failed": {"failed"},
}


def build_dashboard(*, batch: Mapping[str, Any], capacity: Mapping[str, Any] | None = None) -> dict[str, Any]:
    items = list(batch.get("items") or [])
    counts: dict[str, int] = {"pending": 0, "preflight": 0, "released": 0, "release_ready": 0}
    for item in items:
        state = str(item.get("state") or "pending")
        counts[state] = counts.get(state, 0) + 1
    total = len(items)
    completed = counts.get("released", 0) + counts.get("release_ready", 0)
    failed = counts.get("failed", 0)

    # Capacity projection (from preflight estimate_capacity, refreshed by canary).
    cap = dict(capacity or {})
    total_pages = int(cap.get("total_pages") or 0)
    minutes_per_page = _float(cap.get("average_minutes_per_page"))
    estimated_hours = None
    if minutes_per_page:
        remaining_pages = total_pages - int(cap.get("completed_pages") or 0)
        estimated_hours = round(remaining_pages * minutes_per_page / 60, 1)

    return {
        "schema": DASHBOARD_SCHEMA,
        "batch_id": batch.get("batch_id"),
        "phase": batch.get("phase"),
        "phase_status": batch.get("phase_status"),
        "blocking_reasons": batch.get("blocking_reasons") or [],
        "total": total,
        "completed": completed,
        "planning": sum(counts.get(s, 0) for s in _STATE_GROUPS["planning"]),
        "ocr": sum(counts.get(s, 0) for s in _STATE_GROUPS["ocr"]),
        "review": sum(counts.get(s, 0) for s in _STATE_GROUPS["review"]),
        "failed": failed,
        "by_state": counts,
        "estimated_completion_hours": estimated_hours,
        "capacity": cap,
    }


def predict_from_canary(*, canary_metrics: Mapping[str, Any], total_pages: int) -> dict[str, Any]:
    """Project the full batch from measured canary per-page averages."""
    minutes_per_page = _float(canary_metrics.get("minutes_per_page"))
    deepseek_calls_per_page = _float(canary_metrics.get("deepseek_calls_per_page"))
    review_regions_per_page = _float(canary_metrics.get("review_regions_per_page"))
    return {
        "schema": "engineering-drawing-resource-prediction-v1",
        "total_pages": total_pages,
        "predicted_total_hours": round(total_pages * minutes_per_page / 60, 1) if minutes_per_page else None,
        "predicted_deepseek_calls": int(total_pages * deepseek_calls_per_page) if deepseek_calls_per_page else None,
        "predicted_review_regions": int(total_pages * review_regions_per_page) if review_regions_per_page else None,
        "basis": "canary_measured",
    }


def build_dashboard_html(dashboard: Mapping[str, Any]) -> str:
    def cell(label: str, value: Any) -> str:
        return f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(value))}</td></tr>"

    rows = "".join(
        cell(label, dashboard.get(key))
        for label, key in (
            ("Total", "total"),
            ("Completed", "completed"),
            ("Planning", "planning"),
            ("OCR/Translation", "ocr"),
            ("Review", "review"),
            ("Failed", "failed"),
            ("Estimated completion (h)", "estimated_completion_hours"),
        )
    )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Engineering-Drawing Delivery Dashboard</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px}table{border-collapse:collapse}"
        "th,td{border:1px solid #ccc;padding:6px}</style></head><body>"
        f"<h1>Delivery Dashboard — {html.escape(str(dashboard.get('batch_id') or ''))}</h1>"
        f"<p>phase: {html.escape(str(dashboard.get('phase') or ''))} · "
        f"status: {html.escape(str(dashboard.get('phase_status') or ''))}</p>"
        "<table>" + rows + "</table>"
        "</body></html>"
    )


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = ["DASHBOARD_SCHEMA", "build_dashboard", "build_dashboard_html", "predict_from_canary"]
