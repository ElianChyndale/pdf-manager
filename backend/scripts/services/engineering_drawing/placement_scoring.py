"""Recomputable, zone-aware candidate scoring for bilingual placements."""

from __future__ import annotations

from copy import deepcopy
from typing import Mapping, Sequence


FEATURES = {
    "source_overlap_ratio", "distance_pt", "protected_object_overlap_ratio",
    "translation_overlap_ratio", "engineering_ink_ratio", "semantic_association",
    "whitespace_utilization", "font_fit",
}
DEFAULT_WEIGHTS = {
    "drawing_body": {"source_overlap": 0.32, "distance": 0.18, "engineering_ink": 0.06, "semantic_association": 0.20, "whitespace": 0.10, "font_fit": 0.14},
    "drawing_table": {"source_overlap": 0.32, "distance": 0.16, "engineering_ink": 0.08, "semantic_association": 0.22, "whitespace": 0.08, "font_fit": 0.14},
    "state_bearing_metadata": {"source_overlap": 0.34, "distance": 0.16, "engineering_ink": 0.05, "semantic_association": 0.24, "whitespace": 0.07, "font_fit": 0.14},
}


def _validate_weights(weights: Mapping[str, float]) -> dict[str, float]:
    required = set(next(iter(DEFAULT_WEIGHTS.values())))
    if set(weights) != required:
        raise ValueError(f"dynamic weights must contain exactly {sorted(required)}")
    normalized = {key: float(value) for key, value in weights.items()}
    if any(value < 0 or value > 1 for value in normalized.values()) or abs(sum(normalized.values()) - 1) > 1e-9:
        raise ValueError("dynamic weights must be within 0..1 and sum to 1")
    if normalized["source_overlap"] <= normalized["distance"]:
        raise ValueError("source_overlap weight must remain greater than distance weight")
    if normalized["semantic_association"] < normalized["engineering_ink"]:
        raise ValueError("semantic association weight cannot be lower than engineering ink avoidance")
    return normalized


def score_candidates(
    region_type: str,
    candidates: Sequence[Mapping[str, object]],
    *,
    search_radius_pt: float,
    weights: Mapping[str, float] | None = None,
) -> list[dict]:
    if region_type not in DEFAULT_WEIGHTS:
        raise ValueError(f"dynamic scoring is unsupported for region type {region_type}")
    radius = float(search_radius_pt)
    if not 12 <= radius <= 48:
        raise ValueError("dynamic search radius must be within 12..48pt")
    selected_weights = _validate_weights(weights or DEFAULT_WEIGHTS[region_type])
    audit: list[dict] = []
    for raw in candidates:
        item = deepcopy(dict(raw))
        features = item.get("features")
        if not isinstance(features, Mapping) or set(features) != FEATURES:
            raise ValueError(f"candidate {item.get('candidate_id')} has incomplete scoring features")
        values = {key: float(value) for key, value in features.items()}
        legal = values["protected_object_overlap_ratio"] == 0 and values["translation_overlap_ratio"] == 0
        distance_score = max(0.0, 1.0 - values["distance_pt"] / radius)
        contributions = {
            # Source overlap is deliberately amplified: the policy requires its
            # penalty to dominate the local-distance benefit, not merely carry a
            # numerically larger coefficient.
            "source_overlap": -2.0 * selected_weights["source_overlap"] * values["source_overlap_ratio"],
            "distance": selected_weights["distance"] * distance_score,
            "engineering_ink": -selected_weights["engineering_ink"] * values["engineering_ink_ratio"],
            "semantic_association": selected_weights["semantic_association"] * values["semantic_association"],
            "whitespace": selected_weights["whitespace"] * values["whitespace_utilization"],
            "font_fit": selected_weights["font_fit"] * values["font_fit"],
        }
        audit.append({**item, "features": values, "weights": dict(selected_weights), "contributions": contributions, "total_score": sum(contributions.values()), "legal": legal, "selected": False})
    legal_items = [item for item in audit if item["legal"]]
    if legal_items:
        max(legal_items, key=lambda item: (item["total_score"], str(item.get("candidate_id"))))["selected"] = True
    return audit


__all__ = ["DEFAULT_WEIGHTS", "score_candidates"]
