from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from services.translation.llm.shared.control_context import TranslationControlContext
from services.translation.llm.shared.orchestration import translate_batch
from services.translation.memory import JobMemoryStore

from services.translation.batching.executor import _submit_parallel_translation_batches
from services.translation.batching.executor import _translate_batch_or_keep_origin
from services.translation.results.flush import TranslationFlushState
from services.translation.results.applier import TranslationResultApplier


def run_translation_batches_sequential(
    batches: list[list[dict]],
    *,
    api_key: str,
    model: str,
    base_url: str,
    domain_guidance: str,
    mode: str,
    translation_context: TranslationControlContext | None,
    memory_store: JobMemoryStore | None,
    result_applier: TranslationResultApplier,
    flush_state: TranslationFlushState,
) -> None:
    total_batches = len(batches)
    for index, batch in enumerate(batches, start=1):
        batch_label = f"book: batch {index}/{total_batches}"
        translated = _translate_batch_or_keep_origin(
            batch,
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_label=batch_label,
            domain_guidance=domain_guidance,
            mode=mode,
            context=translation_context,
            memory_store=memory_store,
            translate_fn=translate_batch,
        )
        touched_pages = result_applier.apply_batch(batch, translated)
        flush_state.record_progress(index, touched_pages)
        flush_state.flush_if_due(index, label=f"flushed after batch {index}/{total_batches}")
    flush_state.final_flush()


def _submit_all_parallel_batches(
    *,
    batched_fast_batches: list[list[dict]],
    single_fast_batches: list[list[dict]],
    single_slow_batches: list[list[dict]],
    queue_workers: dict[str, int],
    api_key: str,
    model: str,
    base_url: str,
    domain_guidance: str,
    mode: str,
    translation_context: TranslationControlContext | None,
    memory_store: JobMemoryStore | None,
    executors: list[ThreadPoolExecutor],
) -> dict[object, tuple[str, list[dict]]]:
    futures: dict[object, tuple[str, list[dict]]] = {}
    queue_specs = (
        ("batched_fast", batched_fast_batches),
        ("single_fast", single_fast_batches),
        ("single_slow", single_slow_batches),
    )
    for queue_name, batches in queue_specs:
        futures.update(
            _submit_parallel_translation_batches(
                batches,
                worker_count=queue_workers[queue_name],
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
        )
    return futures


def run_translation_batches_parallel(
    *,
    batched_fast_batches: list[list[dict]],
    single_fast_batches: list[list[dict]],
    single_slow_batches: list[list[dict]],
    queue_workers: dict[str, int],
    api_key: str,
    model: str,
    base_url: str,
    domain_guidance: str,
    mode: str,
    translation_context: TranslationControlContext | None,
    memory_store: JobMemoryStore | None,
    result_applier: TranslationResultApplier,
    flush_state: TranslationFlushState,
) -> None:
    executors: list[ThreadPoolExecutor] = []
    futures = _submit_all_parallel_batches(
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
        executors=executors,
    )
    completed = 0
    try:
        for future in as_completed(futures):
            translated = future.result()
            _queue_name, batch = futures[future]
            touched_pages = result_applier.apply_batch(batch, translated)
            completed += 1
            flush_state.record_progress(completed, touched_pages)
            flush_state.flush_if_due(completed, label=f"flushed after completed batch {completed}/{len(futures)}")
            print(f"book: completed batch {completed}/{len(futures)}", flush=True)
    finally:
        for executor in executors:
            executor.shutdown(wait=True, cancel_futures=False)
    flush_state.final_flush()


__all__ = [
    "run_translation_batches_parallel",
    "run_translation_batches_sequential",
]
