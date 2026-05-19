from __future__ import annotations

from pathlib import Path
import re
import time

import fitz

from foundation.config import fonts
from services.rendering.document.pikepdf_overlay import overlay_pdf_pages_with_pikepdf
from services.rendering.output.typst.compiler import TypstCompileError
from services.rendering.output.typst.book_support import prepare_translated_pages_for_render
from services.rendering.output.typst.overlay_book import build_overlay_page_specs
from services.rendering.output.typst.overlay_book import overlay_pages_via_page_fallback
from services.rendering.output.typst.overlay_book import prepare_overlay_doc_pages
from services.rendering.output.typst.overlay_book import sanitize_overlay_page_specs
from services.rendering.output.typst.overlay_compile import compile_book_overlay_pdf
from services.rendering.output.typst.overlay_compile import compile_page_overlay_pdf
from services.rendering.output.typst.overlay_diagnostics import new_overlay_merge_diagnostics
from services.rendering.output.typst.source_builder import build_typst_book_overlay_source
from services.rendering.output.typst.source_page_overlay import apply_source_page_overlay
from services.rendering.output.typst.source_page_overlay import mark_image_page_overlay_mode
from services.rendering.output.typst.source_page_overlay import overlay_pages_from_single_pdf
from services.pipeline_shared.events import emit_stage_progress


_OVERLAY_STEM_RE = re.compile(r"\bbook-overlay-(\d{3,})\b")
_OVERLAY_BLOCK_ID_RE = re.compile(r"\bp(\d+)_")
_TYPST_PAGE_SIZE_RE = re.compile(
    r"#set\s+page\(\s*width:\s*(?P<width>[0-9.]+)pt,\s*height:\s*(?P<height>[0-9.]+)pt",
)
_FAST_PATCH_PAGE_THRESHOLD = 120
_PAGE_SIZE_TOLERANCE_PT = 0.5


def _can_use_pikepdf_book_overlay(
    *,
    apply_source_overlay: bool,
    use_typst_overlay_fill_only: bool,
    source_cleanup_strategy: str,
    source_text_precleaned_page_indices: frozenset[int],
    ordered_page_indices: list[int],
    translated_pages: dict[int, list[dict]],
) -> bool:
    if apply_source_overlay:
        return False
    if not ordered_page_indices:
        return False
    if use_typst_overlay_fill_only:
        return True
    if source_cleanup_strategy == "pikepdf_text_strip":
        return True
    return all(
        page_idx in source_text_precleaned_page_indices or not translated_pages.get(page_idx)
        for page_idx in ordered_page_indices
    )


def _extract_failed_overlay_indices(exc: BaseException, page_specs: list[tuple[int, float, float, list[dict], str]]) -> set[int]:
    details = str(exc)
    if isinstance(exc, TypstCompileError):
        details = "\n".join(
            part
            for part in (
                exc.stderr,
                exc.stdout,
                str(exc),
            )
            if part
        )

    candidates: set[int] = set()
    for match in _OVERLAY_STEM_RE.finditer(details):
        candidates.add(int(match.group(1)))
    for match in _OVERLAY_BLOCK_ID_RE.finditer(details):
        candidates.add(int(match.group(1)))

    max_index = len(page_specs) - 1
    return {index for index in candidates if 0 <= index <= max_index}


def _prebuilt_source_matches_page_specs(
    prebuilt_source_path: Path,
    book_specs: list[tuple[float, float, list[dict]]],
) -> bool:
    try:
        source = prebuilt_source_path.read_text(encoding="utf-8")
    except OSError:
        return False
    sizes = [
        (float(match.group("width")), float(match.group("height")))
        for match in _TYPST_PAGE_SIZE_RE.finditer(source)
    ]
    if len(sizes) != len(book_specs):
        return False
    for (actual_w, actual_h), (expected_w, expected_h, _items) in zip(sizes, book_specs):
        if abs(actual_w - float(expected_w)) > _PAGE_SIZE_TOLERANCE_PT:
            return False
        if abs(actual_h - float(expected_h)) > _PAGE_SIZE_TOLERANCE_PT:
            return False
    return True


def _overlay_pdf_size_mismatches(
    doc: fitz.Document,
    ordered_page_indices: list[int],
    overlay_pdf_path: Path,
) -> list[dict[str, object]]:
    mismatches: list[dict[str, object]] = []
    overlay_doc = fitz.open(overlay_pdf_path)
    try:
        for overlay_page_idx, page_idx in enumerate(ordered_page_indices):
            if overlay_page_idx >= len(overlay_doc):
                mismatches.append(
                    {
                        "page_index": page_idx,
                        "overlay_page_index": overlay_page_idx,
                        "reason": "overlay_page_missing",
                    }
                )
                continue
            source_page = doc[page_idx]
            overlay_page = overlay_doc[overlay_page_idx]
            source_w = float(source_page.rect.width)
            source_h = float(source_page.rect.height)
            overlay_w = float(overlay_page.rect.width)
            overlay_h = float(overlay_page.rect.height)
            if (
                abs(source_w - overlay_w) > _PAGE_SIZE_TOLERANCE_PT
                or abs(source_h - overlay_h) > _PAGE_SIZE_TOLERANCE_PT
            ):
                mismatches.append(
                    {
                        "page_index": page_idx,
                        "overlay_page_index": overlay_page_idx,
                        "source_page_width_pt": round(source_w, 3),
                        "source_page_height_pt": round(source_h, 3),
                        "overlay_page_width_pt": round(overlay_w, 3),
                        "overlay_page_height_pt": round(overlay_h, 3),
                    }
                )
    finally:
        overlay_doc.close()
    return mismatches


def overlay_translated_items_on_page(
    page: fitz.Page,
    translated_items: list[dict],
    stem: str,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    temp_root: Path | None = None,
    cover_only: bool = False,
    apply_source_overlay: bool = True,
    redaction_strategy: str | None = None,
) -> None:
    translated_items = mark_image_page_overlay_mode(page, translated_items)
    if apply_source_overlay:
        apply_source_page_overlay(
            page,
            translated_items,
            cover_only=cover_only,
            redaction_strategy=redaction_strategy,
        )
    overlay_pdf = compile_page_overlay_pdf(
        page.rect.width,
        page.rect.height,
        translated_items,
        stem=stem,
        api_key=api_key,
        model=model,
        base_url=base_url,
        font_family=font_family,
        include_cover_rect=False,
        font_paths=font_paths,
        temp_root=temp_root,
        work_subdir="single-page",
    )
    overlay_doc = fitz.open(overlay_pdf)
    try:
        page.show_pdf_page(page.rect, overlay_doc, 0, overlay=True)
    finally:
        overlay_doc.close()


def overlay_translated_pages_on_doc(
    doc: fitz.Document,
    translated_pages: dict[int, list[dict]],
    stem: str,
    compile_workers: int | None = None,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    temp_root: Path | None = None,
    cover_only: bool = False,
    apply_source_overlay: bool = True,
    redaction_strategy: str | None = None,
    source_pdf_path: Path | None = None,
    first_line_indent_lookup: dict[str, float] | None = None,
    effective_inner_bbox_lookup: dict[str, list[float]] | None = None,
    source_text_precleaned_page_indices: frozenset[int] = frozenset(),
    prebuilt_source_path: Path | None = None,
    source_base_pdf_path: Path | None = None,
    pikepdf_output_pdf_path: Path | None = None,
    source_cleanup_strategy: str = "typst_fill",
) -> dict[str, object]:
    prepare_started = time.perf_counter()
    translated_pages = prepare_translated_pages_for_render(
        source_pdf_path,
        translated_pages,
        first_line_indent_lookup=first_line_indent_lookup,
        effective_inner_bbox_lookup=effective_inner_bbox_lookup,
    )
    ordered_page_indices, translated_pages = prepare_overlay_doc_pages(doc, translated_pages)
    prepare_elapsed = time.perf_counter() - prepare_started
    if not ordered_page_indices:
        return {
            "compile_elapsed_seconds": 0.0,
            "sanitize_elapsed_seconds": 0.0,
            "source_overlay_elapsed_seconds": 0.0,
            "overlay_merge_elapsed_seconds": 0.0,
            "raw_removable_rects": 0,
            "merged_removable_rects": 0,
            "cover_rects": 0,
            "item_fast_cover_count": 0,
            "fast_page_cover_pages": 0,
            "page_count": 0,
            "mode": "empty",
            "pages": [],
            "compile_errors": [],
            "sanitize_page_diagnostics": [],
        }

    color_started = time.perf_counter()
    translated_pages = {
        page_idx: [
            {
                **item,
                "_render_cover_fill": item.get("_render_cover_fill", (1, 1, 1)),
                "_render_text_color": item.get("_render_text_color", (0, 0, 0)),
            }
            for item in translated_pages[page_idx]
        ]
        for page_idx in ordered_page_indices
    }
    color_elapsed = time.perf_counter() - color_started
    specs_started = time.perf_counter()
    page_specs = build_overlay_page_specs(doc, ordered_page_indices, translated_pages, stem=stem)
    book_specs = [(page_width, page_height, items) for _, page_width, page_height, items, _ in page_specs]
    specs_elapsed = time.perf_counter() - specs_started
    use_typst_overlay_fill_only = len(ordered_page_indices) >= _FAST_PATCH_PAGE_THRESHOLD
    source_prepare_started = time.perf_counter()
    active_prebuilt_source_path: Path | None = Path(prebuilt_source_path) if prebuilt_source_path is not None else None
    if (
        active_prebuilt_source_path is not None
        and active_prebuilt_source_path.exists()
        and _prebuilt_source_matches_page_specs(active_prebuilt_source_path, book_specs)
    ):
        print(f"typst book overlay source prewarm: hit {active_prebuilt_source_path}", flush=True)
    elif temp_root is not None:
        source_work_dir = temp_root / "book-overlay-sources"
        source_work_dir.mkdir(parents=True, exist_ok=True)
        active_prebuilt_source_path = source_work_dir / f"{stem}.typ.prebuilt"
        active_prebuilt_source_path.write_text(
            build_typst_book_overlay_source(
                book_specs,
                font_family=font_family,
                include_cover_rect=False,
            ),
            encoding="utf-8",
        )
    else:
        active_prebuilt_source_path = None
    source_prepare_elapsed = time.perf_counter() - source_prepare_started
    compile_started = time.perf_counter()
    try:
        emit_stage_progress(
            stage="compile",
            message=f"正在编译整本 Typst overlay，共 {len(ordered_page_indices)} 页",
            progress_current=1,
            progress_total=2,
            payload={"progress_unit": "step", "render_stage": "typst_book_compile"},
        )
        overlay_pdf = compile_book_overlay_pdf(
            book_specs,
            stem=stem,
            font_family=font_family,
            font_paths=font_paths,
            temp_root=temp_root,
            prebuilt_source_path=active_prebuilt_source_path,
        )
        compile_elapsed = time.perf_counter() - compile_started
        page_size_mismatches = _overlay_pdf_size_mismatches(doc, ordered_page_indices, overlay_pdf)
        if page_size_mismatches:
            print(
                f"typst book overlay page-size mismatch; using per-page fallback pages={len(page_size_mismatches)}",
                flush=True,
            )
            diagnostics = overlay_pages_via_page_fallback(
                doc,
                ordered_page_indices,
                page_specs,
                translated_pages,
                compile_workers=compile_workers,
                api_key=api_key,
                model=model,
                base_url=base_url,
                font_family=font_family,
                font_paths=font_paths,
                temp_root=temp_root,
                cover_only=cover_only,
                apply_source_overlay=False,
                redaction_strategy=redaction_strategy,
                source_base_pdf_path=source_base_pdf_path,
                pikepdf_output_pdf_path=pikepdf_output_pdf_path,
            )
            diagnostics["compile_elapsed_seconds"] = compile_elapsed
            diagnostics["sanitize_elapsed_seconds"] = 0.0
            diagnostics["page_count"] = len(ordered_page_indices)
            if diagnostics.get("mode") != "page_overlay_fallback_pikepdf":
                diagnostics["mode"] = "page_overlay_after_book_size_mismatch"
            diagnostics["typst_cover_blocks"] = False
            diagnostics["source_overlay_skipped_reason"] = "prepared_source_pdf"
            diagnostics["payload_prepare_elapsed_seconds"] = prepare_elapsed
            diagnostics["color_adapt_elapsed_seconds"] = color_elapsed
            diagnostics["page_specs_elapsed_seconds"] = specs_elapsed
            diagnostics["typst_source_prepare_elapsed_seconds"] = source_prepare_elapsed
            diagnostics["typst_prebuilt_source_path"] = str(active_prebuilt_source_path or "")
            diagnostics["overlay_page_size_mismatches"] = page_size_mismatches
            diagnostics.setdefault("compile_errors", [])
            diagnostics.setdefault("sanitize_page_diagnostics", [])
            return diagnostics
        if (
            source_base_pdf_path is not None
            and pikepdf_output_pdf_path is not None
            and _can_use_pikepdf_book_overlay(
                apply_source_overlay=False,
                use_typst_overlay_fill_only=use_typst_overlay_fill_only,
                source_cleanup_strategy=source_cleanup_strategy,
                source_text_precleaned_page_indices=source_text_precleaned_page_indices,
                ordered_page_indices=ordered_page_indices,
                translated_pages=translated_pages,
            )
        ):
            merge_started = time.perf_counter()
            pike_result = overlay_pdf_pages_with_pikepdf(
                source_pdf_path=source_base_pdf_path,
                overlay_pdf_path=overlay_pdf,
                output_pdf_path=pikepdf_output_pdf_path,
                source_page_indices=ordered_page_indices,
            )
            merge_elapsed = time.perf_counter() - merge_started
            diagnostics = new_overlay_merge_diagnostics()
            diagnostics["compile_elapsed_seconds"] = compile_elapsed
            diagnostics["sanitize_elapsed_seconds"] = 0.0
            diagnostics["source_overlay_elapsed_seconds"] = 0.0
            diagnostics["overlay_merge_elapsed_seconds"] = merge_elapsed
            diagnostics["page_count"] = len(ordered_page_indices)
            diagnostics["mode"] = "book_overlay_pikepdf"
            diagnostics["typst_cover_blocks"] = False
            diagnostics["source_overlay_skipped_reason"] = "prepared_source_pdf"
            diagnostics["payload_prepare_elapsed_seconds"] = prepare_elapsed
            diagnostics["color_adapt_elapsed_seconds"] = color_elapsed
            diagnostics["page_specs_elapsed_seconds"] = specs_elapsed
            diagnostics["typst_source_prepare_elapsed_seconds"] = source_prepare_elapsed
            diagnostics["typst_prebuilt_source_path"] = str(active_prebuilt_source_path or "")
            diagnostics["pikepdf_overlay_output_pdf_path"] = str(pike_result.output_pdf_path)
            diagnostics["pikepdf_overlay_pages"] = pike_result.pages_merged
            diagnostics["pikepdf_overlay_elapsed_seconds"] = pike_result.elapsed_seconds
            diagnostics.setdefault("compile_errors", [])
            diagnostics.setdefault("sanitize_page_diagnostics", [])
            return diagnostics
        diagnostics = overlay_pages_from_single_pdf(
            doc,
            ordered_page_indices,
            translated_pages,
            overlay_pdf,
            cover_only=cover_only,
            apply_source_overlay=False,
            redaction_strategy=redaction_strategy,
            source_text_precleaned_page_indices=source_text_precleaned_page_indices,
            skip_visual_cover=use_typst_overlay_fill_only,
            source_base_pdf_path=source_base_pdf_path,
            pikepdf_output_pdf_path=pikepdf_output_pdf_path,
        )
        diagnostics["compile_elapsed_seconds"] = compile_elapsed
        diagnostics["sanitize_elapsed_seconds"] = 0.0
        diagnostics["page_count"] = len(ordered_page_indices)
        diagnostics["mode"] = "book_overlay"
        diagnostics["typst_cover_blocks"] = False
        diagnostics["source_overlay_skipped_reason"] = "prepared_source_pdf"
        diagnostics["payload_prepare_elapsed_seconds"] = prepare_elapsed
        diagnostics["color_adapt_elapsed_seconds"] = color_elapsed
        diagnostics["page_specs_elapsed_seconds"] = specs_elapsed
        diagnostics["typst_source_prepare_elapsed_seconds"] = source_prepare_elapsed
        diagnostics["typst_prebuilt_source_path"] = str(active_prebuilt_source_path or "")
        diagnostics.setdefault("compile_errors", [])
        diagnostics.setdefault("sanitize_page_diagnostics", [])
        return diagnostics
    except RuntimeError as exc:
        first_compile_elapsed = time.perf_counter() - compile_started
        failed_overlay_indices = _extract_failed_overlay_indices(exc, page_specs)
        print("typst book compile failed; sanitizing pages before per-page fallback", flush=True)
        print(str(exc), flush=True)
        if failed_overlay_indices:
            failed_pages_text = ", ".join(
                str(page_specs[index][0] + 1) for index in sorted(failed_overlay_indices)
            )
            print(f"typst targeted sanitize pages={failed_pages_text}", flush=True)
            emit_stage_progress(
                stage="compile",
                message=f"整本 Typst 编译失败，优先修复不兼容页面：第 {failed_pages_text} 页",
                progress_current=0,
                progress_total=len(failed_overlay_indices),
                payload={
                    "progress_unit": "page",
                    "render_stage": "typst_targeted_sanitize",
                    "candidate_pages": [page_specs[index][0] for index in sorted(failed_overlay_indices)],
                },
            )
        else:
            print("typst compile failure page unknown; sanitizing all pages", flush=True)
        emit_stage_progress(
            stage="compile",
            message="整本 Typst 编译失败，开始检查不兼容页面",
            progress_current=2,
            progress_total=2,
            payload={"progress_unit": "step", "render_stage": "typst_book_compile_failed"},
        )
        compile_errors = [exc.to_dict() if isinstance(exc, TypstCompileError) else str(exc)]

    sanitize_started = time.perf_counter()
    sanitize_page_diagnostics: list[dict] = []
    sanitized_book_specs, sanitized_translated_pages, sanitized_page_specs = sanitize_overlay_page_specs(
        page_specs,
        api_key=api_key,
        model=model,
        base_url=base_url,
        font_family=font_family,
        font_paths=font_paths,
        page_diagnostics=sanitize_page_diagnostics,
        overlay_indices=failed_overlay_indices or None,
    )
    sanitize_elapsed = time.perf_counter() - sanitize_started
    sanitized_compile_started = time.perf_counter()
    sanitized_compile_elapsed = 0.0
    retry_sanitized_book_compile = len(ordered_page_indices) <= 120 or 0 < len(failed_overlay_indices) <= 8
    if retry_sanitized_book_compile:
        try:
            emit_stage_progress(
                stage="compile",
                message="正在重新编译修复后的整本 Typst overlay",
                progress_current=1,
                progress_total=2,
                payload={"progress_unit": "step", "render_stage": "typst_sanitized_book_compile"},
            )
            overlay_pdf = compile_book_overlay_pdf(
                sanitized_book_specs,
                stem=stem,
                font_family=font_family,
                font_paths=font_paths,
                temp_root=temp_root,
            )
            sanitized_compile_elapsed = time.perf_counter() - sanitized_compile_started
            if (
                source_base_pdf_path is not None
                and pikepdf_output_pdf_path is not None
                and _can_use_pikepdf_book_overlay(
                    apply_source_overlay=False,
                    use_typst_overlay_fill_only=use_typst_overlay_fill_only,
                    source_cleanup_strategy=source_cleanup_strategy,
                    source_text_precleaned_page_indices=source_text_precleaned_page_indices,
                    ordered_page_indices=ordered_page_indices,
                    translated_pages=sanitized_translated_pages,
                )
            ):
                merge_started = time.perf_counter()
                pike_result = overlay_pdf_pages_with_pikepdf(
                    source_pdf_path=source_base_pdf_path,
                    overlay_pdf_path=overlay_pdf,
                    output_pdf_path=pikepdf_output_pdf_path,
                    source_page_indices=ordered_page_indices,
                )
                merge_elapsed = time.perf_counter() - merge_started
                diagnostics = new_overlay_merge_diagnostics()
                diagnostics["compile_elapsed_seconds"] = first_compile_elapsed + sanitized_compile_elapsed
                diagnostics["sanitize_elapsed_seconds"] = sanitize_elapsed
                diagnostics["source_overlay_elapsed_seconds"] = 0.0
                diagnostics["overlay_merge_elapsed_seconds"] = merge_elapsed
                diagnostics["page_count"] = len(ordered_page_indices)
                diagnostics["mode"] = "book_overlay_sanitized_pikepdf"
                diagnostics["typst_cover_blocks"] = False
                diagnostics["source_overlay_skipped_reason"] = "prepared_source_pdf"
                diagnostics["payload_prepare_elapsed_seconds"] = prepare_elapsed
                diagnostics["color_adapt_elapsed_seconds"] = color_elapsed
                diagnostics["page_specs_elapsed_seconds"] = specs_elapsed
                diagnostics["typst_source_prepare_elapsed_seconds"] = source_prepare_elapsed
                diagnostics["typst_prebuilt_source_path"] = str(active_prebuilt_source_path or "")
                diagnostics["compile_errors"] = compile_errors
                diagnostics["sanitize_page_diagnostics"] = sanitize_page_diagnostics
                diagnostics["targeted_sanitize_overlay_indices"] = sorted(failed_overlay_indices)
                diagnostics["pikepdf_overlay_output_pdf_path"] = str(pike_result.output_pdf_path)
                diagnostics["pikepdf_overlay_pages"] = pike_result.pages_merged
                diagnostics["pikepdf_overlay_elapsed_seconds"] = pike_result.elapsed_seconds
                return diagnostics
            diagnostics = overlay_pages_from_single_pdf(
                doc,
                ordered_page_indices,
                sanitized_translated_pages,
                overlay_pdf,
                cover_only=cover_only,
                apply_source_overlay=False,
                redaction_strategy=redaction_strategy,
                source_text_precleaned_page_indices=source_text_precleaned_page_indices,
                skip_visual_cover=use_typst_overlay_fill_only,
                source_base_pdf_path=source_base_pdf_path,
                pikepdf_output_pdf_path=pikepdf_output_pdf_path,
            )
            diagnostics["compile_elapsed_seconds"] = first_compile_elapsed + sanitized_compile_elapsed
            diagnostics["sanitize_elapsed_seconds"] = sanitize_elapsed
            diagnostics["page_count"] = len(ordered_page_indices)
            diagnostics["mode"] = "book_overlay_sanitized"
            diagnostics["typst_cover_blocks"] = False
            diagnostics["source_overlay_skipped_reason"] = "prepared_source_pdf"
            diagnostics["payload_prepare_elapsed_seconds"] = prepare_elapsed
            diagnostics["color_adapt_elapsed_seconds"] = color_elapsed
            diagnostics["page_specs_elapsed_seconds"] = specs_elapsed
            diagnostics["typst_source_prepare_elapsed_seconds"] = source_prepare_elapsed
            diagnostics["typst_prebuilt_source_path"] = str(active_prebuilt_source_path or "")
            diagnostics["compile_errors"] = compile_errors
            diagnostics["sanitize_page_diagnostics"] = sanitize_page_diagnostics
            diagnostics["targeted_sanitize_overlay_indices"] = sorted(failed_overlay_indices)
            return diagnostics
        except RuntimeError as exc:
            print("typst sanitized book compile failed; falling back to per-page compilation", flush=True)
            print(str(exc), flush=True)
            compile_errors.append(exc.to_dict() if isinstance(exc, TypstCompileError) else str(exc))
    else:
        print(
            f"typst sanitized book compile skipped for large document pages={len(ordered_page_indices)}; "
            "falling back to per-page compilation",
            flush=True,
        )
        emit_stage_progress(
            stage="compile",
            message=f"大文档跳过整本重编译，改为逐页编译 {len(ordered_page_indices)} 页",
            progress_current=0,
            progress_total=len(ordered_page_indices),
            payload={"progress_unit": "page", "render_stage": "large_doc_page_overlay_compile"},
        )

    diagnostics = overlay_pages_via_page_fallback(
        doc,
        ordered_page_indices,
        sanitized_page_specs,
        sanitized_translated_pages,
        compile_workers=compile_workers,
        api_key=api_key,
        model=model,
        base_url=base_url,
        font_family=font_family,
        font_paths=font_paths,
        temp_root=temp_root,
        cover_only=cover_only,
        apply_source_overlay=apply_source_overlay,
        redaction_strategy=redaction_strategy,
        source_base_pdf_path=source_base_pdf_path,
        pikepdf_output_pdf_path=pikepdf_output_pdf_path,
    )
    diagnostics["compile_elapsed_seconds"] = (
        first_compile_elapsed
        + sanitized_compile_elapsed
        + diagnostics.get("page_overlay_compile_elapsed_seconds", 0.0)
    )
    diagnostics["sanitize_elapsed_seconds"] = sanitize_elapsed
    diagnostics["page_count"] = len(ordered_page_indices)
    if diagnostics.get("mode") != "page_overlay_fallback_pikepdf":
        diagnostics["mode"] = "page_overlay_fallback"
    diagnostics["compile_errors"] = compile_errors
    diagnostics["sanitize_page_diagnostics"] = sanitize_page_diagnostics
    return diagnostics
