from __future__ import annotations

from services.translation.llm.shared.orchestration.metadata import should_store_translation_result
from services.translation.llm.shared.orchestration.transport import DeferredTransportRetry
from services.translation.llm.shared.orchestration.transport import build_transport_tail_retry_context
from services.translation.llm.shared.orchestration.transport import mark_transport_result_dead_letter


def translate_uncached_items_single(
    uncached_batch: list[dict],
    *,
    api_key: str,
    model: str,
    base_url: str,
    request_label: str,
    context,
    diagnostics,
    single_item_translator,
    store_cached_batch_fn,
) -> tuple[dict[str, dict[str, str]], list[dict]]:
    merged: dict[str, dict[str, str]] = {}
    total_items = len(uncached_batch)
    deferred_transport_items: list[dict] = []
    for index, item in enumerate(uncached_batch, start=1):
        item_label = f"{request_label} item {index}/{total_items} {item['item_id']}" if request_label else ""
        try:
            result = single_item_translator(
                item,
                api_key=api_key,
                model=model,
                base_url=base_url,
                request_label=item_label,
                context=context,
                diagnostics=diagnostics,
                allow_transport_tail_defer=context.fallback_policy.transport_tail_retry_passes > 0,
            )
        except DeferredTransportRetry:
            deferred_transport_items.append(item)
            continue
        payload = result.get(item["item_id"], {})
        if should_store_translation_result(payload):
            store_cached_batch_fn(
                [item],
                result,
                model=model,
                base_url=base_url,
                domain_guidance=context.cache_guidance,
                mode=context.mode,
                target_lang=context.target_lang,
                target_language_name=context.target_language_name,
            )
        merged.update(result)
    return merged, deferred_transport_items


def retry_deferred_transport_items(
    deferred_transport_items: list[dict],
    *,
    api_key: str,
    model: str,
    base_url: str,
    request_label: str,
    context,
    diagnostics,
    single_item_translator,
    store_cached_batch_fn,
) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    if not deferred_transport_items or context.fallback_policy.transport_tail_retry_passes <= 0:
        return merged
    tail_context = build_transport_tail_retry_context(context)
    if request_label:
        print(
            f"{request_label}: start transport tail retry pass items={len(deferred_transport_items)} timeout={tail_context.timeout_policy.plain_text_seconds}s",
            flush=True,
        )
    for index, item in enumerate(deferred_transport_items, start=1):
        item_label = f"{request_label} tail item {index}/{len(deferred_transport_items)} {item['item_id']}" if request_label else ""
        result = single_item_translator(
            item,
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_label=item_label,
            context=tail_context,
            diagnostics=diagnostics,
            allow_transport_tail_defer=False,
        )
        result = mark_transport_result_dead_letter(
            result,
            item=item,
            context=tail_context,
            diagnostics=diagnostics,
        )
        payload = result.get(item["item_id"], {})
        if should_store_translation_result(payload):
            store_cached_batch_fn(
                [item],
                result,
                model=model,
                base_url=base_url,
                domain_guidance=tail_context.cache_guidance,
                mode=tail_context.mode,
                target_lang=tail_context.target_lang,
                target_language_name=tail_context.target_language_name,
            )
        merged.update(result)
    return merged
