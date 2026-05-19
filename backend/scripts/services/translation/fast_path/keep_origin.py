from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from services.translation.item_reader import item_is_caption_like
from services.translation.item_reader import item_policy_translate
from services.translation.llm.result_payload import result_entry
from services.translation.llm.validation.placeholder_tokens import strip_placeholders
from services.translation.policy.metadata_filter import looks_like_hard_nontranslatable_metadata


@dataclass(frozen=True)
class _PlanItemView:
    item: dict
    source: str
    compact: str
    policy_translate: bool | None
    layout_zone: str


@dataclass(frozen=True)
class _KeepOriginRule:
    reason: str
    predicate: Callable[["_PlanItemView"], bool]


def _source_text(item: dict) -> str:
    return str(
        item.get("translation_unit_protected_source_text")
        or item.get("group_protected_source_text")
        or item.get("protected_source_text")
        or item.get("source_text")
        or ""
    )


def _normalized_text_without_placeholders(item: dict) -> str:
    return " ".join(strip_placeholders(_source_text(item)).split())


def _plan_item_view(item: dict) -> _PlanItemView:
    return _PlanItemView(
        item=item,
        source=_source_text(item),
        compact=_normalized_text_without_placeholders(item),
        policy_translate=item_policy_translate(item),
        layout_zone=str(item.get("layout_zone", "") or "").strip().lower(),
    )


def _fast_path_keep_origin_result(item: dict, reason: str) -> dict[str, dict[str, str]]:
    payload = result_entry("keep_origin", "")
    payload["translation_diagnostics"] = {
        "item_id": item.get("item_id", ""),
        "page_idx": item.get("page_idx"),
        "route_path": ["block_level", "fast_path_keep_origin"],
        "output_mode_path": [],
        "fallback_to": "keep_origin",
        "degradation_reason": reason,
        "final_status": "kept_origin",
    }
    return {str(item.get("item_id", "") or ""): payload}


def _is_short_alnum_label(view: _PlanItemView) -> bool:
    return len(view.compact) <= 4 and view.compact.replace(" ", "").isalnum()


_FAST_PATH_KEEP_ORIGIN_RULES: tuple[_KeepOriginRule, ...] = (
    _KeepOriginRule("empty_source_text", lambda view: not view.source.strip()),
    _KeepOriginRule("placeholder_only", lambda view: not view.compact),
    _KeepOriginRule("policy_skip", lambda view: view.policy_translate is False),
    _KeepOriginRule("hard_metadata_fragment", lambda view: looks_like_hard_nontranslatable_metadata(view.item)),
    _KeepOriginRule(
        "short_non_body_label",
        lambda view: _is_short_alnum_label(view) and item_is_caption_like(view.item),
    ),
    _KeepOriginRule(
        "short_non_body_label",
        lambda view: _is_short_alnum_label(view) and not view.policy_translate and view.layout_zone == "non_flow",
    ),
)


def _is_fast_path_keep_origin_item(item: dict) -> tuple[bool, str]:
    view = _plan_item_view(item)
    matched_rule = next((rule for rule in _FAST_PATH_KEEP_ORIGIN_RULES if rule.predicate(view)), None)
    return (True, matched_rule.reason) if matched_rule is not None else (False, "")


__all__ = [
    "_FAST_PATH_KEEP_ORIGIN_RULES",
    "_KeepOriginRule",
    "_PlanItemView",
    "_fast_path_keep_origin_result",
    "_is_fast_path_keep_origin_item",
    "_is_short_alnum_label",
    "_normalized_text_without_placeholders",
    "_plan_item_view",
    "_source_text",
]
