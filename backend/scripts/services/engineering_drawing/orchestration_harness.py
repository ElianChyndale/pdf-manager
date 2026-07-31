from __future__ import annotations

"""Single-contract harness for the engineering-drawing agent workflow.

Every stage receives and returns the same run identity.  Stage-specific tools
may add evidence, but may not reinterpret zones, drop source lines, change the
chosen render mode, or substitute another policy snapshot.
"""

from hashlib import sha256
import json
from typing import Any, Mapping

from .workflow_policy import WORKFLOW_VERSION, policy_snapshot


HARNESS_SCHEMA = "engineering-drawing-orchestration-harness-v1"
STAGES = (
    "supervisor_plan",
    "extraction_ledger",
    "render_contract",
    "rendered_candidate",
    "release_authorization",
)
RENDER_MODES = {"preserve_source_blue_chinese", "opaque_bilingual_reflow"}
# Optional per-run document context that is part of the immutable run identity.
# It never enters the policy snapshot / canonical policy fingerprint.
DOCUMENT_CONTEXT_FIELDS = frozenset(
    {
        "project_name",
        "drawing_discipline",
        "drawing_type",
        "client",
        "site",
        "preferred_terminology",
        "language_policy",
        "units",
    }
)


def canonicalize_document_context(context: Mapping[str, Any] | str | None) -> str:
    """Deterministic canonical JSON for identity purposes ("" when absent).

    Accepts either a raw Mapping or the canonical JSON string produced by a
    prior ``new_run_identity`` call, so stage payloads that carry the stored
    string are re-canonicalized losslessly.
    """
    if not context:
        return ""
    if isinstance(context, str):
        try:
            parsed = json.loads(context)
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError("document_context string must be canonical JSON") from error
        if not isinstance(parsed, Mapping):
            raise ValueError("document_context must be an object")
        return json.dumps(dict(parsed), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if not isinstance(context, Mapping):
        raise ValueError("document_context must be an object")
    return json.dumps(dict(context), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
HARD_FINDINGS = {
    "omission",
    "semantic_coverage_gap",
    "ink_coverage_gap",
    "wrong_zone",
    "mixed_render_mode",
    "old_source_glyph_visible_after_opaque_reflow",
    "partial_mask_overlap",
    "unreadable_type",
    "wrong_rotation",
    "serious_visual_damage",
    # V4 typography gate: a candidate with text below the zone font floor.
    "font_below_v4_floor",
    # Production QA: rasterized residual English outside authorized zones.
    "raster_residual_english",
    # Geometry integrity: page-count / page-size / severe damage changes.
    "page_geometry_changed",
    "severe_page_damage",
    # Token integrity: real numeric/identifier/unit loss.
    "token_preservation_failure",
}


def canonical_policy_fingerprint() -> str:
    encoded = json.dumps(policy_snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def new_run_identity(
    *,
    run_id: str,
    source_sha256: str,
    document_context: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    if not run_id.strip() or len(source_sha256) != 64:
        raise ValueError("run identity requires run_id and a SHA-256 source digest")
    identity: dict[str, str] = {
        "schema": HARNESS_SCHEMA,
        "run_id": run_id,
        "source_sha256": source_sha256.lower(),
        "workflow_version": WORKFLOW_VERSION,
        "policy_fingerprint": canonical_policy_fingerprint(),
    }
    if document_context is not None:
        identity["document_context"] = canonicalize_document_context(document_context)
    return identity


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _identity(payload: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    _require(payload.get("schema") == HARNESS_SCHEMA, "invalid orchestration harness schema")
    _require(payload.get("workflow_version") == WORKFLOW_VERSION, "stale or ambiguous workflow version")
    _require(payload.get("policy_fingerprint") == canonical_policy_fingerprint(), "policy fingerprint drift")
    values = tuple(str(payload.get(key) or "") for key in ("run_id", "source_sha256", "workflow_version", "policy_fingerprint"))
    _require(bool(values[0]) and len(values[1]) == 64, "invalid run identity")
    context = payload.get("document_context")
    context_fingerprint = (
        sha256(canonicalize_document_context(context).encode("utf-8")).hexdigest() if context else ""
    )
    return (*values, context_fingerprint)


def validate_handoff(payload: Mapping[str, Any], *, previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate one immutable stage handoff and its link to the prior stage."""
    normalized = dict(payload)
    identity = _identity(normalized)
    stage = str(normalized.get("stage") or "")
    _require(stage in STAGES, "unsupported orchestration stage")
    if previous is not None:
        prior_identity = _identity(previous)
        _require(identity == prior_identity, "handoff changed run/source/workflow/policy identity")
        prior_stage = str(previous.get("stage") or "")
        _require(STAGES.index(stage) == STAGES.index(prior_stage) + 1, "handoff skipped or reordered a workflow stage")

    blocks = normalized.get("blocks") or []
    _require(isinstance(blocks, list) and blocks, "handoff requires non-empty blocks")
    block_ids: set[str] = set()
    source_ids: set[str] = set()
    for index, raw in enumerate(blocks):
        _require(isinstance(raw, Mapping), f"blocks[{index}] must be an object")
        block_id = str(raw.get("block_id") or "")
        _require(block_id and block_id not in block_ids, f"duplicate/empty block_id at {index}")
        block_ids.add(block_id)
        member_ids = [str(value) for value in (raw.get("source_ids") or []) if str(value)]
        _require(member_ids, f"block {block_id} requires source_ids")
        _require(not source_ids.intersection(member_ids), f"source line bound more than once in block {block_id}")
        source_ids.update(member_ids)
        _require(str(raw.get("zone") or ""), f"block {block_id} requires a zone")
        if raw.get("status") == "translated":
            _require(raw.get("render_mode") in RENDER_MODES, f"block {block_id} requires exactly one render mode")

    expected_ids = {str(value) for value in (normalized.get("expected_source_ids") or []) if str(value)}
    literal_ids = {str(value) for value in (normalized.get("literal_only_ids") or []) if str(value)}
    _require(expected_ids and source_ids.isdisjoint(literal_ids), "translated and literal IDs must be disjoint")
    _require(source_ids | literal_ids == expected_ids, "source-line closure must equal 1.0")

    if previous is not None:
        previous_modes = {str(item["block_id"]): item.get("render_mode") for item in previous.get("blocks", []) if item.get("status") == "translated"}
        current_modes = {str(item["block_id"]): item.get("render_mode") for item in blocks if item.get("status") == "translated"}
        _require(previous_modes == current_modes, "handoff weakened or changed a supervisor render-mode decision")

    if stage in {"rendered_candidate", "release_authorization"}:
        _require(float(normalized.get("whole_page_closure", 0)) == 1.0, "whole-page closure must be 1.0")
        _require(float(normalized.get("ink_closure", 0)) == 1.0, "rendered-ink closure must be 1.0")
        zone_closure = normalized.get("zone_closure") or {}
        _require(zone_closure and all(float(value) == 1.0 for value in zone_closure.values()), "every declared zone must close at 1.0")
        findings = {str(value) for value in (normalized.get("hard_findings") or [])}
        _require(not findings.intersection(HARD_FINDINGS), "hard findings block the workflow")

    if stage == "release_authorization":
        _require(normalized.get("render_review_passed") is True, "release requires rendered-page review")
        _require(len(str(normalized.get("candidate_sha256") or "")) == 64, "release requires the reviewed candidate SHA-256")
        _require(len(str(normalized.get("review_evidence_sha256") or "")) == 64, "release requires crop-review evidence SHA-256")
        _require(normalized.get("release_separate_from_renderer") is True, "renderer may not self-authorize or publish")
        _require(normalized.get("authorization") == "release", "release authorization must be explicit")
    return normalized


__all__ = [
    "DOCUMENT_CONTEXT_FIELDS",
    "HARNESS_SCHEMA",
    "HARD_FINDINGS",
    "RENDER_MODES",
    "STAGES",
    "canonical_policy_fingerprint",
    "canonicalize_document_context",
    "new_run_identity",
    "validate_handoff",
]
