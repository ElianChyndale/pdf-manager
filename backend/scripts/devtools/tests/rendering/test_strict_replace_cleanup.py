from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.rendering.policy.cleanup_policy import item_should_strict_replace_text_strip
from services.rendering.source.render_source import build_render_source_pdf
import services.rendering.source.render_source as render_source_module


def _build_source_pdf(path: Path, *, text: str = "body source text", at: tuple[float, float] = (40.0, 60.0)) -> None:
    doc = fitz.open()
    page = doc.new_page(width=240, height=240)
    page.insert_text(at, text, fontsize=12)
    doc.save(path)
    doc.close()


def test_strict_replace_scope_only_targets_body_and_caption_text() -> None:
    body_item = {
        "item_id": "p001-b001",
        "block_kind": "text",
        "block_type": "text",
        "layout_role": "paragraph",
        "semantic_role": "body",
        "structure_role": "body",
        "bbox": [10.0, 10.0, 150.0, 40.0],
        "protected_source_text": "body source",
    }
    caption_item = {
        "item_id": "p001-b002",
        "block_kind": "text",
        "block_type": "text",
        "layout_role": "caption",
        "semantic_role": "caption",
        "structure_role": "caption",
        "bbox": [10.0, 42.0, 150.0, 72.0],
        "protected_source_text": "caption source",
    }
    metadata_item = {
        "item_id": "p001-b003",
        "block_kind": "text",
        "block_type": "text",
        "layout_role": "paragraph",
        "semantic_role": "metadata",
        "structure_role": "metadata",
        "policy_translate": False,
        "bbox": [10.0, 74.0, 150.0, 104.0],
        "protected_source_text": "metadata source",
    }

    assert item_should_strict_replace_text_strip(body_item) is True
    assert item_should_strict_replace_text_strip(caption_item) is True
    assert item_should_strict_replace_text_strip(metadata_item) is False


def test_strict_replace_escalates_no_text_overlap_page(tmp_path: Path) -> None:
    source_pdf = tmp_path / "source.pdf"
    output_pdf = tmp_path / "out.pdf"
    _build_source_pdf(source_pdf, text="outside", at=(20.0, 20.0))
    translated_pages = {
        0: [
            {
                "item_id": "p001-b001",
                "page_idx": 0,
                "block_kind": "text",
                "block_type": "text",
                "layout_role": "paragraph",
                "semantic_role": "body",
                "structure_role": "body",
                "bbox": [120.0, 160.0, 220.0, 220.0],
                "protected_source_text": "body source",
                "protected_translated_text": "译文",
            }
        ]
    }

    prepared = build_render_source_pdf(
        source_pdf_path=source_pdf,
        output_pdf_path=output_pdf,
        pdf_compress_dpi=0,
        translated_pages=translated_pages,
        strip_hidden_text=False,
        source_cleanup_strategy="strict_replace",
    )

    assert prepared.strict_replace_pages_targeted == frozenset({0})
    assert prepared.strict_replace_pages_escalated == frozenset({0})
    assert prepared.strict_replace_pages_verified_clean == frozenset({0})
    assert prepared.strict_replace_pages_failed == frozenset()
    assert prepared.source_text_precleaned_page_indices == frozenset({0})


def test_strict_replace_raises_when_escalation_still_has_residual_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_pdf = tmp_path / "source.pdf"
    output_pdf = tmp_path / "out.pdf"
    _build_source_pdf(source_pdf, text="residual source text", at=(50.0, 80.0))
    translated_pages = {
        0: [
            {
                "item_id": "p001-b001",
                "page_idx": 0,
                "block_kind": "text",
                "block_type": "text",
                "layout_role": "paragraph",
                "semantic_role": "body",
                "structure_role": "body",
                "bbox": [150.0, 150.0, 220.0, 220.0],
                "protected_source_text": "residual source text",
                "protected_translated_text": "译文",
            }
        ]
    }

    monkeypatch.setattr(
        render_source_module,
        "_apply_strict_replace_redaction_copy",
        lambda **_kwargs: (False, frozenset(), frozenset({0})),
    )

    with pytest.raises(RuntimeError, match="strict_replace cleanup failed"):
        build_render_source_pdf(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            pdf_compress_dpi=0,
            translated_pages=translated_pages,
            strip_hidden_text=False,
            source_cleanup_strategy="strict_replace",
        )
