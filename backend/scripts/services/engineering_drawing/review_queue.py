"""Risk-ranked human-review queue for V4 engineering-drawing candidates.

Manual review today is a flat dump of regions.  This module ranks every
translated block by a transparent risk score (low OCR confidence, model QA
disagreement, unseen terminology, microtext, rotated text, title-block/company
zones, residual English, and translation length growth) and renders a static
decision sheet with 4x zoom crops.  The sheet is an export: it posts nowhere,
and decisions must be recorded back manually.
"""

from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import fitz

REVIEW_QUEUE_SCHEMA = "engineering-drawing-review-queue-v1"

RISK_WEIGHTS = {
    "low_ocr_confidence": 25,
    "translation_qa_disagreement": 30,
    "unseen_term": 15,
    "microtext_tiny_font": 20,
    "rotated_text": 10,
    "title_block_company_panel": 8,
    "residual_english": 35,
    "translation_length_growth": 12,
}

_HIGH_RISK_ZONES = {
    "company_contact_panel",
    "state_bearing_metadata",
    "directory_index",
}
_CJK_RE = re.compile(r"[㐀-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# A "significant" glossary/TM token is one the source shares with the term
# bank; a single incidental token (e.g. "water") must not mark a phrase as
# fully recognized when the bulk of it is new.
_UNSEEN_SIGNIFICANT_TOKENS = 2


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


def _normalized_terms(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(str(text or "").casefold()) if len(token) >= 3}


def _load_glossary_terms(glossary_csv: Path | None) -> set[str]:
    terms: set[str] = set()
    if glossary_csv is None or not Path(glossary_csv).is_file():
        return terms
    try:
        with Path(glossary_csv).open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                source = row.get("source_text") or row.get("source") or ""
                if source:
                    terms.update(_normalized_terms(source))
    except (OSError, csv.Error):
        return terms
    return terms


def _load_tm_sources(translation_memory_json: Path | None) -> set[str]:
    sources: set[str] = set()
    if translation_memory_json is None or not Path(translation_memory_json).is_file():
        return sources
    payload = _load_json(Path(translation_memory_json))
    entries = (payload or {}).get("entries") or []
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            sources.update(_normalized_terms(entry.get("source_text") or ""))
    return sources


def _load_translation_candidates(
    translation_qa_report: Mapping[str, Any] | None,
    work_dir: Path,
) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = {}
    report = translation_qa_report or _load_json(work_dir / "translation-qa-report.json")
    for raw in (report or {}).get("regions") or []:
        if not isinstance(raw, dict):
            continue
        region_id = str(raw.get("region_id") or "")
        if not region_id:
            continue
        translated = str(raw.get("translated_text") or "")
        corrected = str(raw.get("corrected_translation") or raw.get("corrected") or "")
        pool = [value for value in (translated, corrected) if value]
        if pool:
            candidates[region_id] = pool
    return candidates


def _residual_english_ids(visual_qa: Mapping[str, Any] | None) -> set[str]:
    if not visual_qa:
        return set()
    ids: set[str] = set()
    for item in visual_qa.get("untranslated_candidate_items") or []:
        if isinstance(item, dict) and item.get("region_id"):
            ids.add(str(item["region_id"]))
    return ids


def _write_crop_png(
    *,
    candidate_pdf: Path,
    page_index: int,
    bbox: list[float],
    output_path: Path,
    zoom: float = 4.0,
) -> Path | None:
    """Render a zoomed crop of a region bbox from the candidate PDF."""
    if not Path(candidate_pdf).is_file() or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        rect = fitz.Rect(*(float(value) for value in bbox))
        with fitz.open(candidate_pdf) as document:
            if not 0 <= page_index < document.page_count:
                return None
            page = document[page_index]
            if rect.is_empty or rect.is_infinite:
                return None
            matrix = fitz.Matrix(zoom, zoom)
            clip = rect & page.rect
            if clip.is_empty:
                return None
            pixmap = page.get_pixmap(matrix=matrix, clip=clip)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(output_path))
            return output_path
    except Exception:
        return None


def build_review_queue(
    *,
    work_dir: Path,
    candidate_pdf: Path | None = None,
    visual_qa: Mapping[str, Any] | None = None,
    translation_qa_report: Mapping[str, Any] | None = None,
    glossary_csv: Path | None = None,
    translation_memory_json: Path | None = None,
) -> dict[str, Any]:
    """Rank every translated block in a run by risk, descending."""
    work_dir = Path(work_dir)
    stage4 = _load_json(work_dir / "stage4-rendered-candidate.json")
    if stage4 is None:
        raise ValueError(f"no stage4-rendered-candidate.json in {work_dir}")
    resolved_candidate = Path(candidate_pdf) if candidate_pdf else Path(str(stage4.get("candidate_pdf") or ""))
    resolved_visual_qa = visual_qa or _load_json(work_dir / "visual-qa.json") or {}

    placement_audit = _load_list(work_dir / "inline-placement.json")
    if placement_audit is None and resolved_candidate and resolved_candidate.is_file():
        placement_audit = _load_list(resolved_candidate.with_suffix(".inline-placement.json"))
    status_by_id = {
        str(item.get("region_id") or ""): dict(item)
        for item in placement_audit or []
        if isinstance(item, dict)
    }

    glossary_terms = _load_glossary_terms(glossary_csv)
    tm_sources = _load_tm_sources(translation_memory_json)
    candidates_by_id = _load_translation_candidates(translation_qa_report, work_dir)
    residual_ids = _residual_english_ids(resolved_visual_qa)

    blocks = stage4.get("blocks") or []
    items: list[dict[str, Any]] = []
    crop_dir = work_dir / "review-queue" / "crops"
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        region_id = str(block.get("block_id") or "")
        source_text = str(block.get("source_text") or "")
        translated_text = str(block.get("translated_text") or "")
        zone = str(block.get("zone") or "")
        placement = status_by_id.get(region_id, {})
        risk_factors: list[str] = []

        confidence = placement.get("confidence") if isinstance(placement, dict) else None
        try:
            confidence_f = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_f = None
        if confidence_f is not None and confidence_f < 0.55:
            risk_factors.append("low_ocr_confidence")

        flags = {str(flag) for flag in (placement.get("qa_flags") or []) if isinstance(placement, dict)}
        if flags.intersection({"manual_review_required", "ai_translation_missing", "deepseek_ocr_conflict"}):
            risk_factors.append("translation_qa_disagreement")

        source_terms = _normalized_terms(source_text)
        known = glossary_terms | tm_sources
        # n-gram coverage: a phrase is only "recognized" when at least two
        # significant source tokens (or every token) are in the term bank; a
        # single incidental shared token must not suppress the flag.
        significant_unseen = source_terms - known
        if source_terms and len(significant_unseen) >= _UNSEEN_SIGNIFICANT_TOKENS:
            risk_factors.append("unseen_term")

        font_size = placement.get("font_size") if isinstance(placement, dict) else None
        try:
            font_f = float(font_size) if font_size is not None else None
        except (TypeError, ValueError):
            font_f = None
        zone_min = 5.8 if zone not in _HIGH_RISK_ZONES else 6.8
        if font_f is not None and font_f < zone_min:
            risk_factors.append("microtext_tiny_font")

        rotation = 0
        if isinstance(placement, dict):
            try:
                rotation = int(placement.get("rotation") or 0) % 360
            except (TypeError, ValueError):
                rotation = 0
        if rotation != 0:
            risk_factors.append("rotated_text")

        if zone in _HIGH_RISK_ZONES:
            risk_factors.append("title_block_company_panel")

        if region_id in residual_ids:
            risk_factors.append("residual_english")

        # Length-growth applies to the standard EN->ZH workflow: the source is
        # Latin (no CJK) and the target is Chinese. The previous gate required
        # CJK in BOTH, which never fired for native English source text.
        if _CJK_RE.search(translated_text) and _LATIN_RE.search(source_text):
            growth = len(translated_text) / max(1, len(source_text))
            if growth > 2.5:
                risk_factors.append("translation_length_growth")

        risk_score = sum(RISK_WEIGHTS[factor] for factor in risk_factors)
        target_bbox = placement.get("target_bbox") or placement.get("source_bbox") or []
        page_index = 0
        try:
            page_index = int(placement.get("page_index") or 0) if isinstance(placement, dict) else 0
        except (TypeError, ValueError):
            page_index = 0
        crop_path = None
        if isinstance(target_bbox, (list, tuple)) and len(target_bbox) == 4 and resolved_candidate and resolved_candidate.is_file():
            crop_path = _write_crop_png(
                candidate_pdf=resolved_candidate,
                page_index=page_index,
                bbox=[float(value) for value in target_bbox],
                output_path=crop_dir / f"page-{page_index + 1:04d}-{region_id}.png",
            )

        items.append(
            {
                "region_id": region_id,
                "page_index": page_index,
                "zone": zone,
                "source_text": source_text,
                "translated_text": translated_text,
                "translation_candidates": candidates_by_id.get(region_id, [translated_text]),
                "confidence": confidence_f,
                "qa_flags": sorted(flags),
                "target_bbox": list(target_bbox) if isinstance(target_bbox, (list, tuple)) else [],
                "crop_path": str(crop_path) if crop_path else None,
                "risk_factors": sorted(risk_factors),
                "risk_score": risk_score,
            }
        )

    items.sort(key=lambda item: (item["risk_score"], item["region_id"]), reverse=True)
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank

    return {
        "schema": REVIEW_QUEUE_SCHEMA,
        "run_id": str(stage4.get("run_id") or ""),
        "source_sha256": str(stage4.get("source_sha256") or ""),
        "workflow_version": str(stage4.get("workflow_version") or ""),
        "hard_findings": list(stage4.get("hard_findings") or []),
        "candidate_pdf": str(resolved_candidate) if resolved_candidate and resolved_candidate.is_file() else "",
        "crop_root": str(crop_dir.resolve()),
        "items": items,
    }


def build_review_queue_html(queue: Mapping[str, Any]) -> str:
    """Static self-contained decision sheet (posts nowhere)."""
    rows = []
    for item in queue.get("items") or []:
        crop = (
            f'<img src="crops/{Path(str(item["crop_path"])).name}" alt="crop" '
            'style="max-width:240px;border:1px solid #ccc">'
            if item.get("crop_path")
            else "<em>no crop</em>"
        )
        source = html.escape(str(item.get("source_text") or ""))
        translated = html.escape(str(item.get("translated_text") or ""))
        flags = html.escape(", ".join(item.get("qa_flags") or []))
        factors = html.escape(", ".join(item.get("risk_factors") or []))
        candidates = "".join(
            f"<option value=\"{html.escape(str(candidate))}\">{html.escape(str(candidate))}</option>"
            for candidate in (item.get("translation_candidates") or [])
        )
        rows.append(
            "<tr>"
            f"<td>{item.get('rank')}</td>"
            f"<td>{item.get('risk_score')}</td>"
            f"<td>{factors}</td>"
            f"<td>{html.escape(str(item.get('region_id') or ''))}</td>"
            f"<td>{html.escape(str(item.get('zone') or ''))}</td>"
            f"<td>{crop}</td>"
            f"<td>{source}<br><small>{translated}</small><br><small>flags: {flags}</small></td>"
            "<td>"
            '<select name="decision" data-region="{region}">'
            "<option>approve</option><option>edit</option><option>keep_literal</option><option>bilingual</option>"
            "</select>"
            "<br><textarea name=\"edit\" rows=\"2\" cols=\"22\"></textarea>"
            "<br><label><input type=\"checkbox\" name=\"flag_review\"> flag for human review</label>"
            "<input type=\"hidden\" name=\"region_id\" value=\"{region}\">"
            "</td>"
            "</tr>".replace("{region}", html.escape(str(item.get("region_id") or "")))
        )
    header = (
        "<tr><th>rank</th><th>risk</th><th>factors</th><th>region</th><th>zone</th>"
        "<th>crop</th><th>source / translation / flags</th><th>decision</th></tr>"
    )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Engineering-Drawing V4 Review Queue</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px;vertical-align:top}"
        "</style></head><body>"
        "<h1>Engineering-Drawing V4 Review Queue</h1>"
        "<p style=\"color:#b00020\"><strong>Static export — this sheet posts "
        "nowhere. No data is submitted; record decisions manually.</strong></p>"
        f"<p>run_id: {html.escape(str(queue.get('run_id') or ''))} · "
        f"source_sha256: {html.escape(str(queue.get('source_sha256') or ''))} · "
        f"workflow_version: {html.escape(str(queue.get('workflow_version') or ''))}</p>"
        f"<p>hard findings: {html.escape(', '.join(queue.get('hard_findings') or []) or 'none')}</p>"
        "<form action=\"#\"><table>" + header + "".join(rows) + "</table></form>"
        "</body></html>"
    )


__all__ = [
    "REVIEW_QUEUE_SCHEMA",
    "RISK_WEIGHTS",
    "build_review_queue",
    "build_review_queue_html",
]
