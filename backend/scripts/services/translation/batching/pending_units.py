from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from services.translation.llm.shared.control_context import TranslationControlContext
from services.translation.llm.shared.orchestration import translate_batch
from services.translation.memory import JobMemoryStore
from services.translation.payload import pending_translation_items

from services.translation.batching.executor import _keep_origin_results_for_transport_batch
from services.translation.batching.executor import _submit_parallel_translation_batches as _submit_parallel_translation_batches_impl
from services.translation.batching.executor import _translate_batch_or_keep_origin as _translate_batch_or_keep_origin_impl
from services.translation.workflow.batch_runner import run_translation_batches_parallel
from services.translation.workflow.batch_runner import run_translation_batches_sequential
from services.translation.results.flush import TranslationFlushState
from services.translation.results.applier import TranslationResultApplier
from services.translation.results.applier import expand_duplicate_results as _expand_duplicate_results
from services.translation.results.applier import touched_pages_for_batch
from services.translation.batching.plan import _allocate_translation_queue_workers
from services.translation.batching.plan import _build_translation_batches
from services.translation.batching.plan import _classify_translation_batches
from services.translation.batching.plan import _dedupe_pending_items
from services.translation.batching.plan import _effective_translation_batch_size
from services.translation.batching.plan import _save_flush_interval
from services.translation.batching.plan import TranslationBatchRunStats


def _translate_batch_or_keep_origin(
    batch: list[dict],
    *,
    api_key: str,
    model: str,
    base_url: str,
    request_label: str,
    domain_guidance: str,
    mode: str,
    context: TranslationControlContext | None,
    memory_store: JobMemoryStore | None = None,
    translate_fn: Callable[..., dict[str, dict[str, str]]] | None = None,
) -> dict[str, dict[str, str]]:
    return _translate_batch_or_keep_origin_impl(
        batch,
        api_key=api_key,
        model=model,
        base_url=base_url,
        request_label=request_label,
        domain_guidance=domain_guidance,
        mode=mode,
        context=context,
        memory_store=memory_store,
        translate_fn=translate_batch if translate_fn is None else translate_fn,
    )


def _submit_parallel_translation_batches(
    batches: list[list[dict]],
    *,
    worker_count: int,
    queue_name: str,
    api_key: str,
    model: str,
    base_url: str,
    domain_guidance: str,
    mode: str,
    translation_context: TranslationControlContext | None,
    memory_store: JobMemoryStore | None,
    executors: list[ThreadPoolExecutor],
) -> dict[object, tuple[str, list[dict]]]:
    return _submit_parallel_translation_batches_impl(
        batches,
        worker_count=worker_count,
        queue_name=queue_name,
        api_key=api_key,
        model=model,
        base_url=base_url,
        domain_guidance=domain_guidance,
        mode=mode,
        translation_context=translation_context,
        memory_store=memory_store,
        executors=executors,
        translate_fn=translate_batch,
    )


def _infer_job_memory_path(translation_paths: dict[int, Path]) -> Path:
    first_path = next(iter(translation_paths.values()))
    return first_path.parent / "job-memory.json"


def translate_pending_units(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
    batch_size: int,
    workers: int,
    api_key: str,
    model: str,
    base_url: str,
    domain_guidance: str = "",
    mode: str = "fast",
    translation_context: TranslationControlContext | None = None,
    progress_callback: Callable[[int, int, set[int]], None] | None = None,
) -> dict[str, int]:
    flat_payload: list[dict] = []
    item_to_page: dict[str, int] = {}
    for page_idx in sorted(page_payloads):
        for item in page_payloads[page_idx]:
            flat_payload.append(item)
            item_to_page[item.get("item_id", "")] = page_idx

    pending = pending_translation_items(flat_payload)
    pending, duplicate_items_by_rep_id = _dedupe_pending_items(pending)
    effective_batch_size = _effective_translation_batch_size(
        batch_size=batch_size,
        model=model,
        base_url=base_url,
        translation_context=translation_context,
    )
    batches, immediate_results = _build_translation_batches(
        pending,
        effective_batch_size=effective_batch_size,
        translation_context=translation_context,
    )
    batched_fast_batches, single_fast_batches, single_slow_batches = _classify_translation_batches(batches)
    total_batches = len(batches)
    flush_interval = _save_flush_interval(workers=workers, total_batches=total_batches)
    queue_workers = _allocate_translation_queue_workers(
        workers,
        batched_fast_count=len(batched_fast_batches),
        single_fast_count=len(single_fast_batches),
        single_slow_count=len(single_slow_batches),
    )
    run_stats = TranslationBatchRunStats(
        pending_items=len(pending),
        total_batches=total_batches,
        effective_batch_size=effective_batch_size,
        flush_interval=flush_interval,
        effective_workers=max(1, workers),
        batched_fast_batches=len(batched_fast_batches),
        single_fast_batches=len(single_fast_batches),
        single_slow_batches=len(single_slow_batches),
    )
    print(
        f"book: pending items={len(pending)} batches={total_batches} workers={max(1, workers)} "
        f"mode={mode} effective_batch_size={effective_batch_size}",
        flush=True,
    )
    if immediate_results:
        print(f"book: fast-path keep_origin items={len(immediate_results)}", flush=True)
    duplicate_count = sum(len(items) for items in duplicate_items_by_rep_id.values())
    if duplicate_count:
        print(f"book: deduped duplicate items={duplicate_count}", flush=True)
    if total_batches:
        print(f"book: save flush interval={flush_interval} batches", flush=True)
        print(
            "book: queue split "
            f"batched_fast={len(batched_fast_batches)} "
            f"single_fast={len(single_fast_batches)} "
            f"single_slow={len(single_slow_batches)} "
            f"workers(batched_fast={queue_workers['batched_fast']}, "
            f"single_fast={queue_workers['single_fast']}, "
            f"single_slow={queue_workers['single_slow']})",
            flush=True,
        )
    flush_state = TranslationFlushState(
        page_payloads=page_payloads,
        translation_paths=translation_paths,
        flush_interval=flush_interval,
        total_batches=total_batches,
        progress_callback=progress_callback,
    )
    memory_store = JobMemoryStore(_infer_job_memory_path(translation_paths)) if translation_paths else None
    result_applier = TranslationResultApplier(
        flat_payload=flat_payload,
        item_to_page=item_to_page,
        duplicate_items_by_rep_id=duplicate_items_by_rep_id,
        flush_state=flush_state,
        memory_store=memory_store,
    )
    for immediate in immediate_results:
        result_applier.apply_immediate(immediate)
    if immediate_results and not batches:
        flush_state.flush(label="final flush for fast-path items")
    if workers <= 1:
        run_translation_batches_sequential(
            batches,
            api_key=api_key,
            model=model,
            base_url=base_url,
            domain_guidance=domain_guidance,
            mode=mode,
            translation_context=translation_context,
            memory_store=memory_store,
            result_applier=result_applier,
            flush_state=flush_state,
        )
        return run_stats.as_dict()

    run_translation_batches_parallel(
        batched_fast_batches=batched_fast_batches,
        single_fast_batches=single_fast_batches,
        single_slow_batches=single_slow_batches,
        queue_workers=queue_workers,
        api_key=api_key,
        model=model,
        base_url=base_url,
        domain_guidance=domain_guidance,
        mode=mode,
        translation_context=translation_context,
        memory_store=memory_store,
        result_applier=result_applier,
        flush_state=flush_state,
    )
    return run_stats.as_dict()
