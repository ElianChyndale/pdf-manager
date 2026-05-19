from __future__ import annotations

import time
from pathlib import Path

from services.translation.batching.pending_units import translate_pending_units
from services.translation.workflow.pages import save_pages
from services.translation.workflow.page_policies import apply_page_policies
from services.translation.workflow.page_policies import finalize_page_payloads
from services.translation.workflow.page_policies import review_and_apply_continuations
from services.pipeline_shared.events import emit_stage_progress
from services.pipeline_shared.events import emit_stage_transition
from services.translation.diagnostics import TranslationRunDiagnostics
from services.translation.llm.shared.control_context import TranslationControlContext
from services.translation.policy import TranslationPolicyConfig
from services.translation.postprocess import reconstruct_garbled_page_payloads


def format_translation_progress_message(current: int, total: int, touched_pages: set[int]) -> str:
    if touched_pages:
        sorted_pages = sorted(page_idx + 1 for page_idx in touched_pages)
        if len(sorted_pages) == 1:
            page_suffix = f"（最近页: {sorted_pages[0]}）"
        else:
            preview = ",".join(str(page) for page in sorted_pages[:4])
            if len(sorted_pages) > 4:
                preview = f"{preview}..."
            page_suffix = f"（最近页: {preview}）"
    else:
        page_suffix = ""
    return f"已完成第 {current}/{total} 批翻译{page_suffix}"


def run_initial_continuation_pass(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
) -> None:
    stage_started = time.perf_counter()
    finalize_page_payloads(
        page_payloads=page_payloads,
        translation_paths=translation_paths,
    )
    emit_stage_progress(
        stage="continuation_review",
        message="初始连续段整理完成",
        elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        payload={"page_count": len(page_payloads)},
    )
    print(f"book: initial continuation pass in {time.perf_counter() - stage_started:.2f}s", flush=True)


def run_continuation_review(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
    api_key: str,
    model: str,
    base_url: str,
    workers: int,
    run_diagnostics: TranslationRunDiagnostics | None,
) -> None:
    review_started = time.perf_counter()
    emit_stage_transition(
        stage="continuation_review",
        message="开始复核跨栏/跨页连续段",
        progress_current=0,
        progress_total=len(page_payloads),
    )
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_start("continuation_review")
    review_and_apply_continuations(
        page_payloads=page_payloads,
        translation_paths=translation_paths,
        api_key=api_key,
        model=model,
        base_url=base_url,
        workers=workers,
        progress_callback=lambda current, total: emit_stage_progress(
            stage="continuation_review",
            message=f"正在判断跨栏/跨页连续段，第 {current}/{total} 批",
            progress_current=current,
            progress_total=total,
            payload={"progress_unit": "page"},
        ),
    )
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_end("continuation_review")
    emit_stage_progress(
        stage="continuation_review",
        message="跨栏/跨页连续段复核完成",
        progress_current=len(page_payloads),
        progress_total=len(page_payloads),
        elapsed_ms=int((time.perf_counter() - review_started) * 1000),
    )
    print(f"book: continuation review in {time.perf_counter() - review_started:.2f}s", flush=True)


def run_page_policy_stage(
    *,
    page_payloads: dict[int, list[dict]],
    mode: str,
    classify_batch_size: int,
    workers: int,
    api_key: str,
    model: str,
    base_url: str,
    skip_title_translation: bool,
    sci_cutoff_page_idx: int | None,
    sci_cutoff_block_idx: int | None,
    policy_config: TranslationPolicyConfig | None,
    run_diagnostics: TranslationRunDiagnostics | None,
) -> int:
    policy_started = time.perf_counter()
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_start("page_policies")
    emit_stage_transition(
        stage="page_policies",
        message="开始执行页面策略和块分类",
        progress_current=0,
        progress_total=len(page_payloads),
    )
    print("book: page policies start", flush=True)
    print(f"book: page policies mode={mode} total_pages={len(page_payloads)}", flush=True)
    classified_items = apply_page_policies(
        page_payloads=page_payloads,
        mode=mode,
        classify_batch_size=max(1, classify_batch_size),
        workers=max(1, workers),
        api_key=api_key,
        model=model,
        base_url=base_url,
        skip_title_translation=skip_title_translation,
        sci_cutoff_page_idx=sci_cutoff_page_idx,
        sci_cutoff_block_idx=sci_cutoff_block_idx,
        policy_config=policy_config,
        progress_callback=lambda current, total, page_idx, page_classified: emit_stage_progress(
            stage="page_policies",
            message=f"正在执行页面策略，第 {current}/{total} 页",
            progress_current=current,
            progress_total=total,
            payload={
                "page_idx": page_idx,
                "page_number": page_idx + 1,
                "page_classified_items": page_classified,
            },
        ),
    )
    if classified_items:
        print(f"book: classified {classified_items} items", flush=True)
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_end("page_policies")
    emit_stage_progress(
        stage="page_policies",
        message="页面策略和块分类完成",
        progress_current=len(page_payloads),
        progress_total=len(page_payloads),
        elapsed_ms=int((time.perf_counter() - policy_started) * 1000),
        payload={"classified_items": classified_items},
    )
    print(f"book: page policies in {time.perf_counter() - policy_started:.2f}s", flush=True)
    return int(classified_items)


def run_translation_batch_stage(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
    batch_size: int,
    workers: int,
    api_key: str,
    model: str,
    base_url: str,
    domain_guidance: str,
    mode: str,
    translation_context: TranslationControlContext | None,
    run_diagnostics: TranslationRunDiagnostics | None,
) -> dict:
    translate_started = time.perf_counter()
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_start("translation_batches")
    emit_stage_transition(
        stage="translating",
        message="开始批量翻译",
    )
    batch_summary = translate_pending_units(
        page_payloads=page_payloads,
        translation_paths=translation_paths,
        batch_size=batch_size,
        workers=max(1, workers),
        api_key=api_key,
        model=model,
        base_url=base_url,
        domain_guidance=domain_guidance,
        mode=mode,
        translation_context=translation_context,
        progress_callback=lambda current, total, touched_pages: emit_stage_progress(
            stage="translating",
            message=format_translation_progress_message(current, total, touched_pages),
            progress_current=current,
            progress_total=total,
            payload={
                "touched_page_indexes": sorted(touched_pages),
                "touched_page_numbers": [page_idx + 1 for page_idx in sorted(touched_pages)],
            },
        ),
    )
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_end("translation_batches")
        run_diagnostics.set_effective_translation_batch_size(batch_summary["effective_batch_size"])
        run_diagnostics.set_workload(
            pending_items=batch_summary["pending_items"],
            total_batches=batch_summary["total_batches"],
        )
    emit_stage_progress(
        stage="translating",
        message="翻译批次完成",
        progress_current=batch_summary["total_batches"],
        progress_total=batch_summary["total_batches"],
        elapsed_ms=int((time.perf_counter() - translate_started) * 1000),
        payload={
            "pending_items": batch_summary["pending_items"],
            "effective_batch_size": batch_summary["effective_batch_size"],
        },
    )
    print(f"book: translation batches in {time.perf_counter() - translate_started:.2f}s", flush=True)
    return batch_summary


def run_garbled_reconstruction_stage(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
    api_key: str,
    model: str,
    base_url: str,
    workers: int,
    run_diagnostics: TranslationRunDiagnostics | None,
) -> None:
    reconstruct_started = time.perf_counter()
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_start("garbled_reconstruction")
    emit_stage_transition(
        stage="garbled_repair",
        message="开始修复乱码候选段",
        progress_current=0,
        progress_total=len(page_payloads),
    )
    summary = reconstruct_garbled_page_payloads(
        page_payloads,
        api_key=api_key,
        model=model,
        base_url=base_url,
        workers=workers,
        progress_callback=lambda current, total, dirty_pages: emit_stage_progress(
            stage="garbled_repair",
            message=f"正在修复乱码候选段，第 {current}/{total} 项",
            progress_current=current,
            progress_total=total,
            payload={
                "progress_unit": "page",
                "dirty_pages": sorted(dirty_pages),
            },
        ),
    )
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_end("garbled_reconstruction")
    reconstructed_items = int(summary["garbled_reconstructed"])
    garbled_candidates = int(summary["garbled_candidates"])
    dirty_pages = {int(page_idx) for page_idx in summary.get("dirty_pages", [])}
    if dirty_pages:
        save_pages(page_payloads, translation_paths, dirty_pages)
    emit_stage_progress(
        stage="garbled_repair",
        message="乱码候选段修复完成",
        progress_current=len(page_payloads),
        progress_total=len(page_payloads),
        elapsed_ms=int((time.perf_counter() - reconstruct_started) * 1000),
        payload={
            "progress_unit": "page",
            "garbled_candidates": garbled_candidates,
            "garbled_reconstructed": reconstructed_items,
            "dirty_pages": sorted(dirty_pages),
        },
    )
    print(
        f"book: garbled reconstruction candidates={garbled_candidates} reconstructed={reconstructed_items} "
        f"in {time.perf_counter() - reconstruct_started:.2f}s",
        flush=True,
    )


__all__ = [
    "format_translation_progress_message",
    "run_continuation_review",
    "run_garbled_reconstruction_stage",
    "run_initial_continuation_pass",
    "run_page_policy_stage",
    "run_translation_batch_stage",
]
