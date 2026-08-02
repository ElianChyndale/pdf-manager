"""Resumable delivery batch controller for the 160-PDF Codex production run.

This module turns the next Codex delivery session into a set of persisted,
resumable commands.  It provides:

- **Plan packets**: per-page immutable inputs for the Codex supervisor
  (page image, native-text candidates, OCR suggestions, document context,
  glossary/TM refs).  ``export-plan-packets`` → Codex plans → ``import-supervisor-plans``.
- **Shards**: plan/review work is split into bounded shards so a Codex context
  or credit interruption loses nothing already persisted.
- **Delivery controller**: per-item state machine with per-stage concurrency,
  failure isolation, phase-level stop (canary/pilot), stratified selection and
  atomic batch state.
- **Preflight**: environment + capacity checks; Codex quota is a manual gate.

The controller *orchestrates and gates* — it never fabricates supervisor plans.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import fitz

BATCH_SCHEMA = "engineering-drawing-delivery-batch-v1"
PACKET_SCHEMA = "engineering-drawing-plan-packet-v1"
PLAN_SCHEMA = "engineering-drawing-supervisor-plan-v1"
SHARD_SCHEMA = "engineering-drawing-delivery-shard-v1"

ITEM_STATES = (
    "pending",
    "preflight",
    "awaiting_supervisor_plan",
    "supervisor_plan_ready",
    "supervisor_plan_invalid",
    "ocr",
    "translation",
    "rendering",
    "qa",
    "review_required",
    "repairing",
    "release_ready",
    "released",
    "failed",
)
PHASES = ("preflight", "canary", "pilot", "production")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


# --------------------------------------------------------------------------
# Plan packets
# --------------------------------------------------------------------------

def build_plan_packet(
    *,
    packet_id: str,
    source_pdf: Path,
    page_index: int,
    page_count: int,
    page_image: Path,
    native_text_candidates: list[dict[str, Any]],
    ocr_suggested_regions: list[dict[str, Any]],
    document_context: Mapping[str, Any] | None,
    glossary_tm_refs: Mapping[str, str] | None,
) -> dict[str, Any]:
    """One immutable page packet consumed by the Codex supervisor."""
    source_sha256 = file_sha256(source_pdf)
    with fitz.open(source_pdf) as document:
        page = document[page_index]
        page_size = [float(page.rect.width), float(page.rect.height)]
        page_rotation = int(page.rotation or 0) % 360
    return {
        "schema": PACKET_SCHEMA,
        "packet_id": packet_id,
        "source_pdf": str(source_pdf.resolve()),
        "source_sha256": source_sha256,
        "page_index": page_index,
        "page_count": page_count,
        "page_size": page_size,
        "page_rotation": page_rotation,
        "page_image": str(Path(page_image).resolve()),
        "native_text_candidates": native_text_candidates,
        "ocr_suggested_regions": ocr_suggested_regions,
        "document_context": dict(document_context) if document_context else None,
        "glossary_tm_refs": dict(glossary_tm_refs) if glossary_tm_refs else None,
    }


def export_plan_packets(
    *,
    manifest: Mapping[str, Any],
    source_root: Path,
    out_dir: Path,
    document_context: Mapping[str, Any] | None = None,
) -> list[Path]:
    """Generate one plan packet per page for every item in the manifest."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for item in manifest.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id") or "")
        source_pdf = Path(source_root) / Path(str(item.get("source_pdf") or ""))
        if not source_pdf.is_file():
            raise FileNotFoundError(f"delivery item source missing: {source_pdf}")
        ctx = item.get("document_context") or document_context
        with fitz.open(source_pdf) as document:
            page_count = document.page_count
            for page_index in range(page_count):
                image_path = out_dir / item_id / f"page-{page_index + 1:04d}.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                pixmap = document[page_index].get_pixmap(matrix=fitz.Matrix(144 / 72, 144 / 72))
                pixmap.save(str(image_path))
                packet = build_plan_packet(
                    packet_id=f"{item_id}-p{page_index + 1:04d}",
                    source_pdf=source_pdf,
                    page_index=page_index,
                    page_count=page_count,
                    page_image=image_path,
                    native_text_candidates=_native_text_candidates(document[page_index]),
                    ocr_suggested_regions=[],
                    document_context=ctx,
                    glossary_tm_refs=item.get("glossary_tm_refs"),
                )
                packet_path = out_dir / item_id / f"packet-{page_index + 1:04d}.json"
                _write_atomic(packet_path, packet)
                written.append(packet_path)
    return written


def _native_text_candidates(page: fitz.Page) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for block in page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = " ".join(
                str(span.get("text") or "").strip()
                for span in line.get("spans", [])
                if str(span.get("text") or "").strip()
            ).strip()
            if not text:
                continue
            bbox = list(line.get("bbox") or [])
            dx, dy = line.get("dir") or (1, 0)
            rotation = 0 if abs(dx) >= abs(dy) else (90 if dy < 0 else 270)
            candidates.append({"text": text, "bbox": bbox, "rotation": rotation})
    return candidates


def validate_plan_against_packet(plan: Mapping[str, Any], packet: Mapping[str, Any]) -> list[str]:
    """Return a list of validation problems (empty == plan accepted)."""
    problems: list[str] = []
    if plan.get("schema") != PLAN_SCHEMA:
        problems.append(f"plan schema {plan.get('schema')!r} != {PLAN_SCHEMA}")
    if str(plan.get("packet_id") or "") != str(packet.get("packet_id") or ""):
        problems.append("plan packet_id does not match")
    if str(plan.get("source_sha256") or "") != str(packet.get("source_sha256") or ""):
        problems.append("plan source_sha256 does not match packet")
    if int(plan.get("page_index", -1) or -1) != int(packet.get("page_index", -1) or -1):
        problems.append("plan page_index does not match packet")
    # Closure: every packet native candidate must be represented in the plan.
    packet_candidates = [str(c.get("text") or "") for c in packet.get("native_text_candidates") or []]
    plan_sources = [
        str(b.get("source_text") or "")
        for b in (plan.get("semantic_blocks") or []) if isinstance(b, dict)
    ] + [
        str(c.get("source_text") or "")
        for c in (plan.get("coverage_inventory") or []) if isinstance(c, dict)
    ]
    joined = " ".join(plan_sources).casefold()
    for candidate in packet_candidates:
        if candidate.casefold() and candidate.casefold() not in joined:
            problems.append(f"packet native candidate not covered: {candidate!r}")
    return problems


def import_supervisor_plans(*, plans_dir: Path, packets_dir: Path, out_dir: Path) -> dict[str, Any]:
    """Validate each imported plan against its packet and record verdicts."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    imported = {"schema": "engineering-drawing-plan-import-v1", "items": []}
    for plan_path in sorted(Path(plans_dir).glob("**/plan-*.json")):
        plan = _read_json(plan_path)
        packet_id = str(plan.get("packet_id") or "")
        packet_path = _find_packet(packets_dir, packet_id)
        if packet_path is None:
            imported["items"].append({"plan": str(plan_path), "packet_id": packet_id, "status": "invalid", "problems": ["packet not found"]})
            continue
        packet = _read_json(packet_path)
        problems = validate_plan_against_packet(plan, packet)
        status = "valid" if not problems else "invalid"
        imported["items"].append({
            "plan": str(plan_path),
            "packet_id": packet_id,
            "status": status,
            "problems": problems,
        })
    _write_atomic(out_dir / "plan-import.json", imported)
    return imported


def _find_packet(packets_dir: Path, packet_id: str) -> Path | None:
    for path in sorted(Path(packets_dir).rglob("packet-*.json")):
        try:
            payload = _read_json(path)
        except (OSError, ValueError):
            continue
        if str(payload.get("packet_id") or "") == packet_id:
            return path
    return None


# --------------------------------------------------------------------------
# Shards
# --------------------------------------------------------------------------

def build_plan_shards(
    *,
    packet_paths: Iterable[Path],
    out_dir: Path,
    max_pages: int = 8,
    max_image_bytes: int = 20 * 1024 * 1024,
    max_regions: int = 500,
    max_est_context_tokens: int = 60000,
) -> list[Path]:
    """Group packets into bounded shards; pages of the same PDF stay together."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shards: list[dict[str, Any]] = []
    current: dict[str, Any] = {"packet_ids": [], "pages": 0, "image_bytes": 0, "regions": 0, "est_tokens": 0}
    item_bucket: dict[str, list[str]] = {}
    for packet_path in sorted(Path(p) for p in packet_paths):
        packet = _read_json(packet_path)
        packet_id = str(packet.get("packet_id") or "")
        item_id = packet_id.split("-p")[0]
        image_bytes = Path(str(packet.get("page_image") or "")).stat().st_size if Path(str(packet.get("page_image") or "")).exists() else 0
        regions = len(packet.get("native_text_candidates") or []) + len(packet.get("ocr_suggested_regions") or [])
        est_tokens = int(regions * 40 + image_bytes / 1000)
        # Same-PDF pages stay together: buffer by item.
        item_bucket.setdefault(item_id, []).append(packet_id)
        if current["packet_ids"] and (
            current["pages"] >= max_pages
            or current["image_bytes"] + image_bytes > max_image_bytes
            or current["regions"] + regions > max_regions
            or current["est_tokens"] + est_tokens > max_est_context_tokens
        ):
            shards.append(current)
            current = {"packet_ids": [], "pages": 0, "image_bytes": 0, "regions": 0, "est_tokens": 0}
        current["packet_ids"].append(packet_id)
        current["pages"] += 1
        current["image_bytes"] += image_bytes
        current["regions"] += regions
        current["est_tokens"] += est_tokens
    if current["packet_ids"]:
        shards.append(current)

    written: list[Path] = []
    for index, shard in enumerate(shards, start=1):
        shard_path = out_dir / f"plan-shard-{index:03d}.json"
        _write_atomic(
            shard_path,
            {"schema": SHARD_SCHEMA, "kind": "plan", "shard_index": index, **shard},
        )
        written.append(shard_path)
    return written


# --------------------------------------------------------------------------
# Delivery controller
# --------------------------------------------------------------------------

def new_batch(
    *,
    batch_id: str,
    items: list[Mapping[str, Any]],
    output_root: Path,
) -> Path:
    """Create the initial batch state file with per-item pending records."""
    records = []
    for index, item in enumerate(items):
        records.append(
            {
                "item_id": str(item.get("item_id") or f"item-{index + 1:04d}"),
                "source_pdf": str(item.get("source_pdf") or ""),
                "relative_output": str(item.get("relative_output") or ""),
                "document_context": dict(item.get("document_context") or {}),
                "priority": str(item.get("priority") or "normal"),
                "state": "pending",
                "attempts": 0,
                "failure_reason": None,
                "work_dir": None,
            }
        )
    batch = {
        "schema": BATCH_SCHEMA,
        "batch_id": batch_id,
        "phase": "preflight",
        "phase_status": "not_started",
        "blocking_reasons": [],
        "items": records,
    }
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    state_path = output_root / "batch-state.json"
    _write_atomic(state_path, batch)
    return state_path


def load_batch(state_path: Path) -> dict[str, Any]:
    return _read_json(state_path)


def save_batch(state_path: Path, batch: dict[str, Any]) -> None:
    _write_atomic(state_path, batch)


def _set_item_state(batch: dict[str, Any], item_id: str, state: str, **extra: Any) -> None:
    for item in batch.get("items") or []:
        if str(item.get("item_id") or "") == item_id:
            item["state"] = state
            for key, value in extra.items():
                item[key] = value
            return
    raise ValueError(f"unknown item_id {item_id}")


def phase_gate(batch: dict[str, Any]) -> list[str]:
    """Return blocking reasons that stop progression to the next phase."""
    reasons: list[str] = []
    if batch.get("phase") in ("canary", "pilot"):
        for item in batch.get("items") or []:
            failure = item.get("failure_reason")
            if failure and "font_below_v4_floor" in str(failure):
                reasons.append(f"font_floor_violation:{item.get('item_id')}")
            if failure and "token_preservation" in str(failure):
                reasons.append(f"token_loss:{item.get('item_id')}")
            if failure and "severe_page_damage" in str(failure):
                reasons.append(f"severe_page_damage:{item.get('item_id')}")
    if batch.get("phase_status") == "blocked":
        reasons.extend(batch.get("blocking_reasons") or [])
    return reasons


def select_phase_items(
    batch: dict[str, Any],
    *,
    phase: str,
    canary_size: int = 5,
    pilot_size: int = 20,
    risk_profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """Choose items for a phase.

    Canary uses risk-stratified selection: highest-risk + a representative
    spread.  Pilot covers all disciplines/source types.  Production takes the
    remaining pending items.
    """
    pending = [str(item.get("item_id") or "") for item in batch.get("items") or [] if item.get("state") == "pending"]
    if phase == "production":
        return pending
    if phase == "canary":
        profiles = dict(risk_profiles or {})
        scored = sorted(
            pending,
            key=lambda item_id: _risk_score(profiles.get(item_id, {})),
            reverse=True,
        )
        # Highest-risk first, then a representative tail for spread.
        return scored[:max(1, canary_size // 2)] + scored[-(canary_size - max(1, canary_size // 2)):]
    if phase == "pilot":
        profiles = dict(risk_profiles or {})
        disciplines: dict[str, list[str]] = {}
        for item_id in pending:
            discipline = str(profiles.get(item_id, {}).get("discipline") or "unknown")
            disciplines.setdefault(discipline, []).append(item_id)
        chosen: list[str] = []
        for bucket in disciplines.values():
            chosen.extend(bucket[: max(1, pilot_size // max(1, len(disciplines)))])
        return chosen[:pilot_size]
    return []


def _risk_score(profile: Mapping[str, Any]) -> int:
    score = 0
    if str(profile.get("raster") or "").casefold() == "scanned":
        score += 30
    score += min(30, int(profile.get("page_count") or 1)) * 2
    if int(profile.get("rotated_text_likely") or 0):
        score += 15
    if int(profile.get("catalog_density") or 0):
        score += 15
    if int(profile.get("small_text_density") or 0):
        score += 10
    return score


# --------------------------------------------------------------------------
# Batch summary
# --------------------------------------------------------------------------

def build_delivery_report(
    *,
    manifest: Mapping[str, Any],
    source_root: Path,
    duplicate_map: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Delivery-clarity report: source vs unique-processed vs delivered.

    Resolves the 130-vs-160 business question.  When ``duplicate_map`` is
    provided (original path -> eng-<id>), the report shows the duplicate set
    that is REUSED, so the customer sees the delivered file count (161).
    """
    items = list(manifest.get("items") or [])
    unique_processed = len(items)
    dup_map = dict(duplicate_map or {})
    duplicates_reused = len(dup_map)
    delivered_files = unique_processed + duplicates_reused

    # Raw source count = unique content hashes + the duplicates that reuse them.
    hashes = [str(item.get("content_hash") or "") for item in items]
    unique_hashes = set(h for h in hashes if h)
    source_count = len(unique_hashes) + duplicates_reused

    return {
        "schema": "engineering-drawing-delivery-report-v1",
        "source_count": source_count,
        "unique_processed": unique_processed,
        "duplicates_reused": duplicates_reused,
        "delivered_files": delivered_files,
        "source_hashes_unique": len(unique_hashes),
        "note": (
            "source_count = unique processed + duplicates reused; "
            "delivered_files = unique_processed + duplicates reused"
        ),
    }


def build_duplicate_map(
    *,
    manifest: Mapping[str, Any],
    source_root: Path,
    all_sources: Iterable[Path],
) -> dict[str, str]:
    """Map every duplicate source path to its canonical eng-<id>.

    ``all_sources`` is the full raw inventory (including duplicates).  For each
    raw PDF whose content hash matches a manifest item, the map records
    ``original_path -> eng-<id>``.  Items already canonical (their own name) are
    excluded; only genuine duplicates are mapped.
    """
    items = list(manifest.get("items") or [])
    hash_to_id = {
        str(item.get("content_hash") or ""): str(item.get("item_id") or "")
        for item in items
        if str(item.get("content_hash") or "")
    }
    # Count occurrences of each content hash in the raw tree: a canonical file
    # is the FIRST occurrence; every later occurrence is a genuine duplicate.
    occurrence_by_hash: dict[str, list[Path]] = {}
    for raw in all_sources:
        raw = Path(raw)
        try:
            content_hash = file_sha256(raw)
        except OSError:
            continue
        if content_hash in hash_to_id:
            occurrence_by_hash.setdefault(content_hash, []).append(raw)
    duplicate_map: dict[str, str] = {}
    for content_hash, paths in occurrence_by_hash.items():
        canonical_id = hash_to_id[content_hash]
        # The canonical raw source is the first path; the rest are duplicates.
        for extra in paths[1:]:
            duplicate_map[str(extra)] = canonical_id
    return duplicate_map


def batch_summary(batch: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in batch.get("items") or []:
        state = str(item.get("state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    failures = [
        {"item_id": str(item.get("item_id") or ""), "failure_reason": item.get("failure_reason")}
        for item in batch.get("items") or []
        if item.get("state") == "failed" and item.get("failure_reason")
    ]
    return {
        "schema": BATCH_SCHEMA,
        "batch_id": batch.get("batch_id"),
        "phase": batch.get("phase"),
        "phase_status": batch.get("phase_status"),
        "blocking_reasons": batch.get("blocking_reasons") or [],
        "item_counts": counts,
        "failures": failures,
    }


__all__ = [
    "BATCH_SCHEMA",
    "ITEM_STATES",
    "PACKET_SCHEMA",
    "PHASES",
    "PLAN_SCHEMA",
    "SHARD_SCHEMA",
    "batch_summary",
    "build_delivery_report",
    "build_duplicate_map",
    "build_plan_packet",
    "build_plan_shards",
    "export_plan_packets",
    "file_sha256",
    "import_supervisor_plans",
    "load_batch",
    "new_batch",
    "phase_gate",
    "save_batch",
    "select_phase_items",
    "validate_plan_against_packet",
]
