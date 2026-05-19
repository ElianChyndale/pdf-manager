from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import fitz

from services.rendering.source.compression.pdf_copy import build_image_compressed_pdf_copy
from services.rendering.source.preparation.bbox_text_strip_candidates import build_bbox_text_strip_candidates
from services.rendering.source.preparation.bbox_text_strip import build_bbox_text_stripped_pdf_copy
from services.rendering.source.preparation.bbox_text_strip_types import BBoxTextStripCandidates
from services.rendering.source.preparation.hidden_text_strip import build_hidden_text_stripped_pdf_copy
from services.rendering.source.preparation.bbox_text_strip_page_probe import page_has_text_overlap
from services.rendering.source.preparation.bbox_text_strip_policy_adapter import split_rect_away_from_formula_guard_rects
from services.rendering.source.preparation.redact_restore_formula import build_redact_restore_formula_pdf_copy
from services.rendering.source.text_redaction import remove_text_under_rects_with_pymupdf_redaction
from services.rendering.output.typst.shared import default_typst_temp_root
from foundation.config import layout


@dataclass(frozen=True)
class RenderSourcePdf:
    path: Path
    temp_paths: list[Path]
    image_compressed: bool = False
    bbox_text_stripped_page_indices: frozenset[int] = frozenset()
    bbox_text_strip_skipped_page_indices: frozenset[int] = frozenset()
    source_text_precleaned_page_indices: frozenset[int] = frozenset()
    strict_replace_pages_targeted: frozenset[int] = frozenset()
    strict_replace_pages_escalated: frozenset[int] = frozenset()
    strict_replace_pages_verified_clean: frozenset[int] = frozenset()
    strict_replace_pages_failed: frozenset[int] = frozenset()


def _page_target_overlap_indices(
    source_pdf_path: Path,
    page_target_rects: dict[int, list[fitz.Rect]],
    page_indices: set[int],
) -> set[int]:
    if not page_indices:
        return set()
    overlaps: set[int] = set()
    with fitz.open(source_pdf_path) as doc:
        for page_idx in sorted(page_indices):
            if page_idx < 0 or page_idx >= len(doc):
                overlaps.add(page_idx)
                continue
            rects = page_target_rects.get(page_idx) or []
            if not rects:
                continue
            if page_has_text_overlap(doc[page_idx], rects):
                overlaps.add(page_idx)
    return overlaps


def _split_redaction_rects_away_from_guards(
    target_rects: list[fitz.Rect],
    guard_rects: list[fitz.Rect],
) -> list[fitz.Rect]:
    if not guard_rects:
        return [rect for rect in target_rects if not rect.is_empty]
    redaction_rects: list[fitz.Rect] = []
    for rect in target_rects:
        for segment in split_rect_away_from_formula_guard_rects(rect, guard_rects):
            if not segment.is_empty:
                redaction_rects.append(segment)
    return redaction_rects


def _apply_strict_replace_redaction_copy(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    page_indices: set[int],
    page_target_rects: dict[int, list[fitz.Rect]],
    page_protected_rects: dict[int, list[fitz.Rect]],
) -> tuple[bool, frozenset[int], frozenset[int]]:
    if not page_indices:
        return False, frozenset(), frozenset()
    changed = False
    with fitz.open(source_pdf_path) as doc:
        for page_idx in sorted(page_indices):
            if page_idx < 0 or page_idx >= len(doc):
                continue
            target_rects = page_target_rects.get(page_idx) or []
            if not target_rects:
                continue
            redaction_rects = _split_redaction_rects_away_from_guards(
                target_rects,
                page_protected_rects.get(page_idx) or [],
            )
            if not redaction_rects:
                continue
            remove_text_under_rects_with_pymupdf_redaction(doc[page_idx], redaction_rects)
            changed = True
        if not changed:
            return False, frozenset(), frozenset(page_indices)
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(output_pdf_path)
    failed = _page_target_overlap_indices(output_pdf_path, page_target_rects, page_indices)
    verified = frozenset(sorted(page_indices - failed))
    return True, verified, frozenset(sorted(failed))


def build_render_source_pdf(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    pdf_compress_dpi: int,
    translated_pages: dict[int, list[dict]] | None = None,
    strip_hidden_text: bool = True,
    start_page: int = 0,
    end_page: int = -1,
    artifact_mode: bool = False,
    bbox_text_strip_candidates: BBoxTextStripCandidates | None = None,
    source_cleanup_strategy: str = "strict_replace",
) -> RenderSourcePdf:
    temp_paths: list[Path] = []
    render_source_path = source_pdf_path
    typst_temp_root = default_typst_temp_root(output_pdf_path)
    work_root = output_pdf_path.parent if artifact_mode else typst_temp_root
    bbox_text_stripped_page_indices: frozenset[int] = frozenset()
    bbox_text_strip_skipped_page_indices: frozenset[int] = frozenset()
    source_text_precleaned_page_indices: frozenset[int] = frozenset()
    strict_replace_pages_targeted: frozenset[int] = frozenset()
    strict_replace_pages_escalated: frozenset[int] = frozenset()
    strict_replace_pages_verified_clean: frozenset[int] = frozenset()
    strict_replace_pages_failed: frozenset[int] = frozenset()

    if strip_hidden_text:
        hidden_started = time.perf_counter()
        hidden_text_stripped_path = work_root / f"{output_pdf_path.stem}.source-hidden-text-stripped.pdf"
        hidden_text_result = build_hidden_text_stripped_pdf_copy(
            render_source_path,
            hidden_text_stripped_path,
            start_page=start_page,
            end_page=end_page,
        )
        print(f"render source pdf: hidden-text strip elapsed={time.perf_counter() - hidden_started:.2f}s", flush=True)
        if hidden_text_result.changed and hidden_text_result.output_pdf_path is not None:
            render_source_path = hidden_text_result.output_pdf_path
            if not artifact_mode:
                temp_paths.append(render_source_path)
            print(f"render source pdf: using hidden-text stripped copy {render_source_path}", flush=True)
        else:
            hidden_text_stripped_path.unlink(missing_ok=True)
    else:
        print("render source pdf: hidden-text strip skipped", flush=True)

    if translated_pages and layout.use_bbox_text_strip_cleanup(source_cleanup_strategy):
        bbox_started = time.perf_counter()
        bbox_text_stripped_path = work_root / f"{output_pdf_path.stem}.source-bbox-text-stripped.pdf"
        strict_replace = layout.use_strict_replace_cleanup(source_cleanup_strategy)
        resolved_candidates = bbox_text_strip_candidates or build_bbox_text_strip_candidates(
            source_pdf_path=render_source_path,
            translated_pages=translated_pages,
            skip_formula_pages=False,
            strict_replace=strict_replace,
        )
        bbox_text_result = build_bbox_text_stripped_pdf_copy(
            source_pdf_path=render_source_path,
            output_pdf_path=bbox_text_stripped_path,
            translated_pages=translated_pages,
            candidates=resolved_candidates,
            skip_formula_pages=False,
            strict_replace=strict_replace,
        )
        print(f"render source pdf: bbox-text strip elapsed={time.perf_counter() - bbox_started:.2f}s", flush=True)
        bbox_text_stripped_page_indices = bbox_text_result.changed_page_indices
        bbox_text_strip_skipped_page_indices = bbox_text_result.skipped_complex_page_indices
        # Only pages with an actual source-text rewrite count as precleaned.
        # "No detected overlap" is a heuristic and can miss tightly packed or
        # vectorized English text, so those pages should still receive Typst
        # cover fallback during overlay.
        source_text_precleaned_page_indices = bbox_text_result.changed_page_indices
        if bbox_text_result.changed and bbox_text_result.output_pdf_path is not None:
            render_source_path = bbox_text_result.output_pdf_path
            if not artifact_mode:
                temp_paths.append(render_source_path)
            print(
                f"render source pdf: using bbox-text stripped copy {render_source_path}",
                flush=True,
            )
        else:
            bbox_text_stripped_path.unlink(missing_ok=True)

        if strict_replace:
            page_target_rects = resolved_candidates.fitz_page_target_rects() or resolved_candidates.fitz_page_rects()
            page_protected_rects = resolved_candidates.fitz_page_protected_rects()
            targeted_pages = set(page_target_rects)
            strict_replace_pages_targeted = frozenset(sorted(targeted_pages))
            unresolved_pages = set(bbox_text_result.skipped_complex_page_indices) | set(
                bbox_text_result.skipped_no_text_overlap_page_indices
            )
            unresolved_pages |= _page_target_overlap_indices(render_source_path, page_target_rects, targeted_pages)
            unresolved_pages &= targeted_pages
            verified_pages = targeted_pages - unresolved_pages
            strict_replace_pages_verified_clean = frozenset(sorted(verified_pages))
            if unresolved_pages:
                strict_replace_pages_escalated = frozenset(sorted(unresolved_pages))
                strict_replace_path = work_root / f"{output_pdf_path.stem}.source-strict-replace-redacted.pdf"
                escalated, escalated_verified, failed_pages = _apply_strict_replace_redaction_copy(
                    source_pdf_path=render_source_path,
                    output_pdf_path=strict_replace_path,
                    page_indices=unresolved_pages,
                    page_target_rects=page_target_rects,
                    page_protected_rects=page_protected_rects,
                )
                if escalated:
                    render_source_path = strict_replace_path
                    if not artifact_mode:
                        temp_paths.append(render_source_path)
                    print(
                        f"render source pdf: strict-replace escalation applied pages={len(unresolved_pages)} path={render_source_path}",
                        flush=True,
                    )
                else:
                    strict_replace_path.unlink(missing_ok=True)
                strict_replace_pages_verified_clean = frozenset(
                    sorted(set(strict_replace_pages_verified_clean) | set(escalated_verified))
                )
                strict_replace_pages_failed = failed_pages
            source_text_precleaned_page_indices = strict_replace_pages_verified_clean
            if strict_replace_pages_failed:
                failed_pages_text = ", ".join(str(page_idx + 1) for page_idx in sorted(strict_replace_pages_failed))
                raise RuntimeError(
                    "strict_replace cleanup failed to remove source text "
                    f"on pages={failed_pages_text}"
                )

    if translated_pages and layout.use_redact_restore_formula_cleanup(source_cleanup_strategy):
        restore_started = time.perf_counter()
        restored_source_path = work_root / f"{output_pdf_path.stem}.source-redact-restore-formulas.pdf"
        restored_result = build_redact_restore_formula_pdf_copy(
            source_pdf_path=render_source_path,
            output_pdf_path=restored_source_path,
            translated_pages=translated_pages,
        )
        print(f"render source pdf: redact-restore formulas elapsed={time.perf_counter() - restore_started:.2f}s", flush=True)
        if restored_result.changed and restored_result.output_pdf_path is not None:
            render_source_path = restored_result.output_pdf_path
            bbox_text_stripped_page_indices = restored_result.changed_page_indices
            source_text_precleaned_page_indices = restored_result.changed_page_indices
            if not artifact_mode:
                temp_paths.append(render_source_path)
            print(
                f"render source pdf: using redact-restore formula copy {render_source_path}",
                flush=True,
            )
        else:
            restored_source_path.unlink(missing_ok=True)

    if pdf_compress_dpi <= 0:
        return RenderSourcePdf(
            path=render_source_path,
            temp_paths=temp_paths,
            bbox_text_stripped_page_indices=bbox_text_stripped_page_indices,
            bbox_text_strip_skipped_page_indices=bbox_text_strip_skipped_page_indices,
            source_text_precleaned_page_indices=source_text_precleaned_page_indices,
            strict_replace_pages_targeted=strict_replace_pages_targeted,
            strict_replace_pages_escalated=strict_replace_pages_escalated,
            strict_replace_pages_verified_clean=strict_replace_pages_verified_clean,
            strict_replace_pages_failed=strict_replace_pages_failed,
        )
    compress_started = time.perf_counter()
    compressed_source_path = (
        work_root / f"{output_pdf_path.stem}.source-compressed.pdf"
    )
    if build_image_compressed_pdf_copy(render_source_path, compressed_source_path, dpi=pdf_compress_dpi):
        print(f"render source pdf: image compression elapsed={time.perf_counter() - compress_started:.2f}s", flush=True)
        print(f"render source pdf: using compressed copy {compressed_source_path}", flush=True)
        if not artifact_mode:
            temp_paths.append(compressed_source_path)
        return RenderSourcePdf(
            path=compressed_source_path,
            temp_paths=temp_paths,
            image_compressed=True,
            bbox_text_stripped_page_indices=bbox_text_stripped_page_indices,
            bbox_text_strip_skipped_page_indices=bbox_text_strip_skipped_page_indices,
            source_text_precleaned_page_indices=source_text_precleaned_page_indices,
            strict_replace_pages_targeted=strict_replace_pages_targeted,
            strict_replace_pages_escalated=strict_replace_pages_escalated,
            strict_replace_pages_verified_clean=strict_replace_pages_verified_clean,
            strict_replace_pages_failed=strict_replace_pages_failed,
        )
    compressed_source_path.unlink(missing_ok=True)
    print("render source pdf: source image compression skipped", flush=True)
    return RenderSourcePdf(
        path=render_source_path,
        temp_paths=temp_paths,
        bbox_text_stripped_page_indices=bbox_text_stripped_page_indices,
        bbox_text_strip_skipped_page_indices=bbox_text_strip_skipped_page_indices,
        source_text_precleaned_page_indices=source_text_precleaned_page_indices,
        strict_replace_pages_targeted=strict_replace_pages_targeted,
        strict_replace_pages_escalated=strict_replace_pages_escalated,
        strict_replace_pages_verified_clean=strict_replace_pages_verified_clean,
        strict_replace_pages_failed=strict_replace_pages_failed,
    )


def prepare_render_source_pdf(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    pdf_compress_dpi: int,
    translated_pages: dict[int, list[dict]] | None = None,
    strip_hidden_text: bool = True,
    start_page: int = 0,
    end_page: int = -1,
    artifact_mode: bool = False,
) -> tuple[Path, list[Path]]:
    prepared = build_render_source_pdf(
        source_pdf_path=source_pdf_path,
        output_pdf_path=output_pdf_path,
        pdf_compress_dpi=pdf_compress_dpi,
        translated_pages=translated_pages,
        strip_hidden_text=strip_hidden_text,
        start_page=start_page,
        end_page=end_page,
        artifact_mode=artifact_mode,
    )
    return prepared.path, prepared.temp_paths
