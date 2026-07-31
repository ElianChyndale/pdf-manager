"""V4 typography policy: the single source of font-size floors for the V4 path.

The V4 production spec (WORKFLOW_SPEC_V4.md) mandates hard minimum font sizes
per zone, and ``workflow_policy.PRODUCTION_TYPOGRAPHY`` is the executable
authority.  No V4 rendering pipeline may define its own font-size constants:
every renderer that runs under ``run_v4.run_v4_flow`` must read the floor from
this module, which reads it from the policy snapshot.

This module also provides the two-stage gate:
- **Pre-render** (``validate_plan_fonts``): the supervisor plan must not
  declare a font below the V4 floor for its zone.
- **Post-render** (``validate_placement_audit_fonts``): the actual font size
  recorded in the placement audit must not be below the V4 floor.  A missing
  ``font_size`` in a V4 renderer's audit fails closed.

Each violation is recorded with ``region_id / zone / actual_font_size /
required_floor / renderer / target_bbox`` so the failure is actionable, and the
hard finding code ``font_below_v4_floor`` is emitted at most once per run (the
details live in ``font-floor-violations.json``).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .workflow_policy import PRODUCTION_TYPOGRAPHY

# Hard finding code used by the orchestration harness.
FONT_BELOW_V4_FLOOR = "font_below_v4_floor"

# Zone -> the PRODUCTION_TYPOGRAPHY block that carries its hard minimum.
_ZONE_TYPOGRAPHY_KEY = {
    "drawing_body": "drawing_body",
    "drawing_table": "drawing_body",
    "state_bearing_metadata": "drawing_body",
    "directory_index": "directory_index",
    "company_contact_panel": "company_contact_panel",
    "prose_or_index_metadata": "drawing_body",
    "sidebar_footer": "drawing_body",
    "sidebar_footer_table": "drawing_body",
}

# Default floor for any zone not explicitly listed (body floor).
_DEFAULT_FLOOR = float(PRODUCTION_TYPOGRAPHY["drawing_body"]["hard_minimum_pt"])

# Expected placement-audit fields for every V4 renderer (fail-closed).
REQUIRED_AUDIT_FIELDS = ("region_id", "zone", "renderer", "font_size", "target_bbox", "render_status")


def zone_font_floor(zone: str | None) -> float:
    """Return the V4 hard minimum font size for a zone."""
    key = _ZONE_TYPOGRAPHY_KEY.get(str(zone or ""))
    if key is None:
        return _DEFAULT_FLOOR
    try:
        return float(PRODUCTION_TYPOGRAPHY[key]["hard_minimum_pt"])
    except (KeyError, TypeError, ValueError):
        return _DEFAULT_FLOOR


def validate_plan_fonts(
    *,
    plan: Mapping[str, Any],
    renderer: str,
) -> list[dict[str, Any]]:
    """Pre-render gate: any translated block whose plan font is below its
    zone floor blocks the run.

    Returns the violations list (empty == pass).  The caller turns a non-empty
    list into a hard failure.
    """
    violations: list[dict[str, Any]] = []
    for raw in plan.get("semantic_blocks") or []:
        if not isinstance(raw, Mapping):
            continue
        placement = raw.get("placement") if isinstance(raw.get("placement"), Mapping) else {}
        zone = str(raw.get("region_type") or "")
        if str(raw.get("coverage_status") or "") != "translated":
            continue
        font_size = placement.get("font_size")
        if font_size is None:
            continue  # pre-render: plan may omit font; post-render decides
        try:
            actual = float(font_size)
        except (TypeError, ValueError):
            violations.append(_violation(str(raw.get("block_id") or ""), zone, None, renderer, None, "invalid_plan_font_size"))
            continue
        floor = zone_font_floor(zone)
        if actual < floor:
            violations.append(_violation(str(raw.get("block_id") or ""), zone, actual, renderer, placement.get("target_bbox"), "plan_below_v4_floor"))
    return violations


def validate_placement_audit_fonts(
    *,
    placement_audit: Iterable[Mapping[str, Any]],
    renderer: str,
) -> list[dict[str, Any]]:
    """Post-render gate: actual font sizes from the placement audit.

    ``placement_audit`` is the ``placements`` list (each item the audit record
    written by a V4 renderer).  A record that lacks ``font_size`` for a
    translated placement fails closed.
    """
    violations: list[dict[str, Any]] = []
    for raw in placement_audit:
        if not isinstance(raw, Mapping):
            continue
        region_id = str(raw.get("region_id") or "")
        status = str(raw.get("status") or "")
        if status in {"rejected_invalid", "rejected_unverified_ocr"}:
            continue  # never rendered; handled by placement closure, not font
        zone = str(raw.get("zone") or "")
        target_bbox = raw.get("target_bbox")
        font_size = raw.get("font_size")
        if font_size is None:
            # Fail closed: a V4 renderer must record the size it used.
            if status and not status.startswith("rejected"):
                violations.append(_violation(region_id, zone, None, renderer, target_bbox, "missing_font_size_fail_closed"))
            continue
        try:
            actual = float(font_size)
        except (TypeError, ValueError):
            violations.append(_violation(region_id, zone, None, renderer, target_bbox, "invalid_font_size"))
            continue
        floor = zone_font_floor(zone)
        if actual < floor:
            violations.append(_violation(region_id, zone, actual, renderer, target_bbox, "below_v4_floor"))
    return violations


def _violation(region_id: str, zone: str, actual: float | None, renderer: str, target_bbox: Any, reason: str) -> dict[str, Any]:
    return {
        "region_id": region_id,
        "zone": zone,
        "actual_font_size": actual,
        "required_floor": zone_font_floor(zone),
        "renderer": renderer,
        "target_bbox": list(target_bbox) if isinstance(target_bbox, (list, tuple)) else [],
        "reason": reason,
    }


def render_path_contract() -> dict[str, Any]:
    """Return the V4 renderer -> font-source contract for policy_runtime_audit."""
    return {
        "schema": "engineering-drawing-render-path-contract-v1",
        "font_source": "workflow_policy.PRODUCTION_TYPOGRAPHY",
        "renderers": {
            "inline_plus_opaque": {"font_source": "workflow_policy", "zones": sorted(_ZONE_TYPOGRAPHY_KEY)},
            "dense_index": {"font_source": "workflow_policy", "zones": ["directory_index"]},
            "human_gate_rumah": {"font_source": "workflow_policy", "zones": sorted(_ZONE_TYPOGRAPHY_KEY)},
        },
        "floors": {
            zone: zone_font_floor(zone) for zone in sorted(set(_ZONE_TYPOGRAPHY_KEY) | {"unknown"})
        },
        "required_audit_fields": list(REQUIRED_AUDIT_FIELDS),
    }


__all__ = [
    "FONT_BELOW_V4_FLOOR",
    "REQUIRED_AUDIT_FIELDS",
    "render_path_contract",
    "validate_placement_audit_fonts",
    "validate_plan_fonts",
    "zone_font_floor",
]
