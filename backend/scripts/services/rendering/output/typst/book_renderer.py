from __future__ import annotations

from pathlib import Path
import time

import fitz

from foundation.config import fonts
from services.rendering.output.pdf_writer import save_fast_pdf
from services.rendering.output.pdf_writer import save_optimized_pdf
from services.rendering.output.pdf_writer import strip_page_links
from services.rendering.source.background.stage import build_clean_background_pdf
from services.rendering.document.page_map import RenderPageMap
from services.rendering.document.metadata import copy_toc
from services.rendering.document.pikepdf_pages import extract_pages_with_pikepdf
from services.rendering.output.typst.book_support import build_dual_doc_pages
from services.rendering.output.typst.book_support import collect_background_page_specs
from services.rendering.output.typst.book_support import prepare_background_work_dir
from services.rendering.output.typst.book_support import prepare_single_page_items
from services.rendering.output.typst.book_support import prepare_translated_pages_for_render
from services.rendering.output.typst.book_support import resolve_typst_temp_root
from services.rendering.output.typst.book_support import save_background_pdf_to_output
from services.rendering.layout.page_specs import build_render_page_specs
from services.rendering.output.typst.compiler import compile_typst_render_pages_pdf
from services.rendering.output.typst.overlay_ops import overlay_translated_items_on_page
from services.rendering.output.typst.overlay_ops import overlay_translated_pages_on_doc
from services.rendering.output.typst.sanitize import sanitize_page_specs_for_typst_book_background


def _build_overlay_base_doc(source_pdf_path: Path) -> fitz.Document:
    started = time.perf_counter()
    doc = fitz.open(source_pdf_path)
    print(f"overlay base doc: open source elapsed={time.perf_counter() - started:.2f}s", flush=True)
    return doc


def _compile_render_pages_pdf_resilient(
    *,
    source_pdf_path: Path,
    background_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    page_specs: list,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    work_dir: Path,
) -> Path:
    try:
        return compile_typst_render_pages_pdf(
            background_pdf_path=background_pdf_path,
            page_specs=page_specs,
            stem="book-background-overlay",
            font_family=font_family,
            font_paths=font_paths,
            work_dir=work_dir,
        )
    except RuntimeError as exc:
        print("typst background render compile failed; sanitizing pages", flush=True)
        print(str(exc), flush=True)
        background_page_specs = collect_background_page_specs(source_pdf_path, translated_pages)
        sanitized_background_specs = sanitize_page_specs_for_typst_book_background(
            background_page_specs,
            stem="book-background-overlay",
            api_key=api_key,
            model=model,
            base_url=base_url,
            font_family=font_family,
            font_paths=font_paths,
            work_dir=work_dir,
        )
        sanitized_pages = {page_idx: items for page_idx, _w, _h, items in sanitized_background_specs}
        sanitized_render_page_specs = build_render_page_specs(
            source_pdf_path=source_pdf_path,
            translated_pages=sanitized_pages,
            prepared=True,
        )
        return compile_typst_render_pages_pdf(
            background_pdf_path=background_pdf_path,
            page_specs=sanitized_render_page_specs,
            stem="book-background-overlay-sanitized",
            font_family=font_family,
            font_paths=font_paths,
            work_dir=work_dir,
        )


def build_single_page_typst_pdf(
    source_pdf_path: Path,
    output_pdf_path: Path,
    translated_items: list[dict],
    page_idx: int,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    temp_root: Path | None = None,
    cover_only: bool = False,
    redaction_strategy: str | None = None,
) -> None:
    prepared_items = prepare_single_page_items(translated_items, page_idx, source_pdf_path=source_pdf_path)
    temp_source_path = resolve_typst_temp_root(output_pdf_path, temp_root) / f"page-{page_idx + 1}-source.pdf"
    extract_pages_with_pikepdf(
        source_pdf_path=source_pdf_path,
        output_pdf_path=temp_source_path,
        start_page=page_idx,
        end_page=page_idx,
    )
    source_doc = fitz.open(source_pdf_path)
    temp_doc = fitz.open(temp_source_path)
    copy_toc(source_doc, temp_doc, start_page=page_idx, end_page=page_idx)
    page = temp_doc[0]
    strip_page_links(page)
    overlay_translated_items_on_page(
        page,
        prepared_items,
        stem=f"page-{page_idx + 1}",
        api_key=api_key,
        model=model,
        base_url=base_url,
        font_family=font_family,
        font_paths=font_paths,
        temp_root=resolve_typst_temp_root(output_pdf_path, temp_root),
        cover_only=cover_only,
        redaction_strategy=redaction_strategy,
    )
    save_optimized_pdf(temp_doc, output_pdf_path)
    temp_doc.close()
    source_doc.close()


def build_book_typst_pdf(
    source_pdf_path: Path,
    output_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    compile_workers: int | None = None,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    temp_root: Path | None = None,
    cover_only: bool = False,
    redaction_strategy: str | None = None,
    fast_save: bool = False,
    indent_detection_pdf_path: Path | None = None,
    first_line_indent_lookup: dict[str, float] | None = None,
    effective_inner_bbox_lookup: dict[str, list[float]] | None = None,
    source_text_precleaned_page_indices: frozenset[int] = frozenset(),
    prebuilt_source_path: Path | None = None,
    source_cleanup_strategy: str = "typst_fill",
) -> dict[str, object]:
    doc = _build_overlay_base_doc(source_pdf_path)
    try:
        typst_temp_root = resolve_typst_temp_root(output_pdf_path, temp_root)
        overlay_started = time.perf_counter()
        overlay_diagnostics = overlay_translated_pages_on_doc(
            doc,
            translated_pages,
            stem="book-overlay",
            compile_workers=compile_workers,
            api_key=api_key,
            model=model,
            base_url=base_url,
            font_family=font_family,
            font_paths=font_paths,
            temp_root=typst_temp_root,
            cover_only=cover_only,
            redaction_strategy=redaction_strategy,
            source_pdf_path=indent_detection_pdf_path or source_pdf_path,
            first_line_indent_lookup=first_line_indent_lookup,
            effective_inner_bbox_lookup=effective_inner_bbox_lookup,
            source_text_precleaned_page_indices=source_text_precleaned_page_indices,
            prebuilt_source_path=prebuilt_source_path,
            source_base_pdf_path=source_pdf_path,
            pikepdf_output_pdf_path=output_pdf_path,
            source_cleanup_strategy=source_cleanup_strategy,
        )
        overlay_elapsed = time.perf_counter() - overlay_started
        print(
            "overlay diagnostics: "
            f"mode={overlay_diagnostics.get('mode')} "
            f"pages={overlay_diagnostics.get('page_count', 0)} "
            f"sanitize={float(overlay_diagnostics.get('sanitize_elapsed_seconds', 0.0) or 0.0):.2f}s "
            f"prepare={float(overlay_diagnostics.get('payload_prepare_elapsed_seconds', 0.0) or 0.0):.2f}s "
            f"color={float(overlay_diagnostics.get('color_adapt_elapsed_seconds', 0.0) or 0.0):.2f}s "
            f"specs={float(overlay_diagnostics.get('page_specs_elapsed_seconds', 0.0) or 0.0):.2f}s "
            f"compile={float(overlay_diagnostics.get('compile_elapsed_seconds', 0.0) or 0.0):.2f}s "
            f"source_cleanup={float(overlay_diagnostics.get('source_overlay_elapsed_seconds', 0.0) or 0.0):.2f}s "
            f"merge={float(overlay_diagnostics.get('overlay_merge_elapsed_seconds', 0.0) or 0.0):.2f}s "
            f"raw_rects={int(overlay_diagnostics.get('raw_removable_rects', 0) or 0)} "
            f"merged_rects={int(overlay_diagnostics.get('merged_removable_rects', 0) or 0)} "
            f"cover_rects={int(overlay_diagnostics.get('cover_rects', 0) or 0)} "
            f"fast_cover_pages={int(overlay_diagnostics.get('fast_page_cover_pages', 0) or 0)} "
            f"item_fast_cover={int(overlay_diagnostics.get('item_fast_cover_count', 0) or 0)} "
            f"legacy_redaction_pages={int(overlay_diagnostics.get('legacy_pymupdf_redaction_pages', 0) or 0)} "
            f"legacy_overlay_pages={int(overlay_diagnostics.get('legacy_pymupdf_overlay_pages', 0) or 0)} "
            f"total={overlay_elapsed:.2f}s",
            flush=True,
        )
        if "pikepdf" in str(overlay_diagnostics.get("mode", "")):
            return overlay_diagnostics
        if fast_save:
            save_fast_pdf(doc, output_pdf_path)
        else:
            save_optimized_pdf(doc, output_pdf_path)
        return overlay_diagnostics
    finally:
        doc.close()


def build_dual_book_pdf(
    source_pdf_path: Path,
    output_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    start_page: int = 0,
    end_page: int = -1,
    compile_workers: int | None = None,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    temp_root: Path | None = None,
    cover_only: bool = False,
    redaction_strategy: str | None = None,
    indent_detection_pdf_path: Path | None = None,
    first_line_indent_lookup: dict[str, float] | None = None,
    effective_inner_bbox_lookup: dict[str, list[float]] | None = None,
) -> None:
    source_doc = fitz.open(source_pdf_path)
    translated_doc = fitz.open(source_pdf_path)
    dual_doc = fitz.open()
    try:
        typst_temp_root = resolve_typst_temp_root(output_pdf_path, temp_root)
        overlay_translated_pages_on_doc(
            translated_doc,
            translated_pages,
            stem="book-overlay-dual",
            compile_workers=compile_workers,
            api_key=api_key,
            model=model,
            base_url=base_url,
            font_family=font_family,
            font_paths=font_paths,
            temp_root=typst_temp_root,
            cover_only=cover_only,
            redaction_strategy=redaction_strategy,
            source_pdf_path=indent_detection_pdf_path or source_pdf_path,
            first_line_indent_lookup=first_line_indent_lookup,
            effective_inner_bbox_lookup=effective_inner_bbox_lookup,
        )
        build_dual_doc_pages(
            source_doc,
            translated_doc,
            dual_doc,
            start_page=start_page,
            end_page=end_page,
        )
        copy_toc(source_doc, dual_doc, start_page=start_page, end_page=end_page)
        save_optimized_pdf(dual_doc, output_pdf_path)
    finally:
        dual_doc.close()
        translated_doc.close()
        source_doc.close()


def build_book_typst_background_pdf(
    source_pdf_path: Path,
    output_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    temp_root: Path | None = None,
    redaction_strategy: str | None = None,
    indent_detection_pdf_path: Path | None = None,
    first_line_indent_lookup: dict[str, float] | None = None,
    effective_inner_bbox_lookup: dict[str, list[float]] | None = None,
) -> None:
    work_dir = prepare_background_work_dir(output_pdf_path, temp_root)
    translated_pages = prepare_translated_pages_for_render(
        indent_detection_pdf_path or source_pdf_path,
        translated_pages,
        first_line_indent_lookup=first_line_indent_lookup,
        effective_inner_bbox_lookup=effective_inner_bbox_lookup,
    )
    page_specs = build_render_page_specs(
        source_pdf_path=source_pdf_path,
        translated_pages=translated_pages,
        prepared=True,
    )
    page_map = RenderPageMap.from_page_specs(page_specs)
    cleaned_background_pdf = build_clean_background_pdf(
        source_pdf_path=source_pdf_path,
        translated_pages=translated_pages,
        output_pdf_path=work_dir / "book-background-cleaned.pdf",
        redaction_strategy=redaction_strategy,
        page_specs=page_specs,
    )
    background_pdf = _compile_render_pages_pdf_resilient(
        source_pdf_path=source_pdf_path,
        background_pdf_path=cleaned_background_pdf,
        translated_pages=translated_pages,
        page_specs=page_specs,
        api_key=api_key,
        model=model,
        base_url=base_url,
        font_family=font_family,
        font_paths=font_paths,
        work_dir=work_dir,
    )
    save_background_pdf_to_output(
        background_pdf,
        output_pdf_path,
        source_pdf_path=source_pdf_path,
        page_map=page_map,
    )
