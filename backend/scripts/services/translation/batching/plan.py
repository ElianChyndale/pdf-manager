from __future__ import annotations

from services.translation.batching.batching import _build_translation_batches as _build_translation_batches_impl
from services.translation.batching.batching import _classify_translation_batches
from services.translation.batching.batching import _effective_translation_batch_size
from services.translation.batching.batching import _save_flush_interval
from services.translation.batching.batching import chunked
from services.translation.batching.dedupe import _dedupe_pending_items
from services.translation.batching.dedupe import _dedupe_signature
from services.translation.batching.dedupe import _source_text
from services.translation.fast_path.keep_origin import _fast_path_keep_origin_result
from services.translation.fast_path.keep_origin import _is_fast_path_keep_origin_item
from services.translation.fast_path.keep_origin import _normalized_text_without_placeholders
from services.translation.fast_path.keep_origin import _plan_item_view
from services.translation.workflow.workers import TranslationBatchRunStats
from services.translation.workflow.workers import _allocate_translation_queue_workers


def _build_translation_batches(
    pending: list[dict],
    *,
    effective_batch_size: int,
    translation_context,
) -> tuple[list[list[dict]], list[dict[str, dict[str, str]]]]:
    return _build_translation_batches_impl(
        pending,
        effective_batch_size=effective_batch_size,
        translation_context=translation_context,
        is_fast_path_keep_origin_item_fn=_is_fast_path_keep_origin_item,
        fast_path_keep_origin_result_fn=_fast_path_keep_origin_result,
        plan_item_view_fn=_plan_item_view,
    )


__all__ = [
    "chunked",
    "TranslationBatchRunStats",
    "_allocate_translation_queue_workers",
    "_build_translation_batches",
    "_classify_translation_batches",
    "_dedupe_pending_items",
    "_dedupe_signature",
    "_effective_translation_batch_size",
    "_fast_path_keep_origin_result",
    "_is_fast_path_keep_origin_item",
    "_normalized_text_without_placeholders",
    "_plan_item_view",
    "_save_flush_interval",
    "_source_text",
]
