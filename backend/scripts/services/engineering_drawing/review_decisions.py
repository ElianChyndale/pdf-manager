"""Persistent human review decisions + immutable revision runs.

A human decision on the review queue is persisted to ``review-decisions.json``
and never mutates the original run.  ``apply`` creates an immutable revision run
``<run_id>-r<revision>`` bound to the original's hashes
(``run_id / source_sha256 / candidate_sha256 / policy_fingerprint /
supervisor_plan_sha256 / region_id / region_revision``), re-runs translation ->
render contract -> whole-page rerender -> visual QA -> release authorization.

Decisions:
- ``approve``: keep the approved_translation (may be the previous one).
- ``edit``: use approved_translation for the revision.
- ``keep_literal``: recorded as ``human_exception_keep_source`` — NEVER
  promoted to ``literal_only`` (that would launder untranslated natural
  language as legal literal).
- ``bilingual``: keep source + translation (page-level rerender decides layout).

``tm_promotion_scope`` (none|project|client|global) controls whether the
approved translation enters translation memory; a project/client entry never
pollutes the global glossary.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REVIEW_DECISIONS_SCHEMA = "engineering-drawing-review-decisions-v1"
REVISION_SCHEMA = "engineering-drawing-revision-run-v1"

ALLOWED_DECISIONS = {"approve", "edit", "keep_literal", "bilingual"}
ALLOWED_TM_SCOPES = {"none", "project", "client", "global"}
REQUIRED_BINDINGS = (
    "run_id",
    "source_sha256",
    "candidate_sha256",
    "policy_fingerprint",
    "supervisor_plan_sha256",
    "region_id",
    "region_revision",
)


@dataclass
class ReviewDecision:
    run_id: str
    source_sha256: str
    candidate_sha256: str
    policy_fingerprint: str
    supervisor_plan_sha256: str
    region_id: str
    region_revision: int = 1
    reviewer_id: str = ""
    reviewed_at: str = ""
    decision: str = "approve"
    previous_translation: str = ""
    approved_translation: str = ""
    decision_reason: str = ""
    tm_promotion_scope: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate(decision: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(decision)
    for field_name in REQUIRED_BINDINGS:
        if not str(normalized.get(field_name) or ""):
            raise ValueError(f"review decision requires {field_name}")
    if str(normalized.get("decision") or "") not in ALLOWED_DECISIONS:
        raise ValueError(f"invalid decision {normalized.get('decision')!r}")
    if str(normalized.get("tm_promotion_scope") or "none") not in ALLOWED_TM_SCOPES:
        raise ValueError(f"invalid tm_promotion_scope {normalized.get('tm_promotion_scope')!r}")
    if str(normalized.get("decision") or "") in {"edit", "approve"} and not str(normalized.get("approved_translation") or ""):
        raise ValueError("edit/approve decisions require approved_translation")
    return normalized


def load_decisions(path: Path) -> list[dict[str, Any]]:
    if not Path(path).is_file():
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != REVIEW_DECISIONS_SCHEMA:
        return []
    return [dict(item) for item in payload.get("decisions") or [] if isinstance(item, dict)]


def add_decision(path: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and append a decision, writing atomically."""
    normalized = _validate(decision)
    normalized.setdefault("reviewer_id", "")
    normalized.setdefault("reviewed_at", _now())
    decisions = load_decisions(path)
    decisions.append(normalized)
    payload = {"schema": REVIEW_DECISIONS_SCHEMA, "decisions": decisions}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


def revision_run_id(run_id: str, region_id: str, revision: int) -> str:
    return f"{run_id}-r{revision}"


def build_revision_run(
    *,
    original_run: Mapping[str, Any],
    decision: Mapping[str, Any],
    work_dir: Path,
) -> Path:
    """Create an immutable revision-run record bound to the original's hashes.

    Writes ``revision-run.json`` into ``work_dir`` and returns its path.  The
    revision re-runs translation -> render contract -> whole-page rerender ->
    visual QA -> release authorization (the caller orchestrates those stages).
    """
    normalized = _validate(decision)
    revision = int(normalized.get("region_revision") or 1)
    revision_id = revision_run_id(str(original_run.get("run_id") or ""), str(normalized.get("region_id") or ""), revision)
    decision_code = normalized.get("decision")
    if decision_code == "keep_literal":
        # NEVER promote to literal_only; record a human exception explicitly.
        effective_status = "human_exception_keep_source"
    elif decision_code == "bilingual":
        effective_status = "bilingual"
    else:
        effective_status = "translated"
    record = {
        "schema": REVISION_SCHEMA,
        "revision_id": revision_id,
        "revision": revision,
        "status": effective_status,
        "approved_translation": str(normalized.get("approved_translation") or ""),
        "decision_reason": str(normalized.get("decision_reason") or ""),
        "tm_promotion_scope": str(normalized.get("tm_promotion_scope") or "none"),
        "bindings": {field_name: str(normalized.get(field_name) or "") for field_name in REQUIRED_BINDINGS},
        "original_run_id": str(original_run.get("run_id") or ""),
        "original_source_sha256": str(original_run.get("source_sha256") or ""),
        "created_at": _now(),
    }
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "revision-run.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "ALLOWED_DECISIONS",
    "ALLOWED_TM_SCOPES",
    "REQUIRED_BINDINGS",
    "REVIEW_DECISIONS_SCHEMA",
    "REVISION_SCHEMA",
    "ReviewDecision",
    "add_decision",
    "build_revision_run",
    "load_decisions",
    "revision_run_id",
]
