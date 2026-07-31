"""Portable CJK font resolution tests."""

from __future__ import annotations

from pathlib import Path

from services.engineering_drawing.fonts.resolve import (
    CJK_BOLD_FALLBACKS,
    CJK_FALLBACKS,
    font_identity,
    font_sha256,
    resolve_cjk_font,
)


def test_bundled_font_preferred() -> None:
    font = resolve_cjk_font()
    assert font.is_file()
    # The repo bundle must be resolved first (not the Windows simhei).
    assert "SourceHanSerifSC" in font.name


def test_font_sha256_is_stable() -> None:
    digest = font_sha256()
    assert digest is not None and len(digest) == 64
    assert digest == font_sha256()


def test_font_identity_carries_hash() -> None:
    identity = font_identity()
    assert identity["sha256"] and len(str(identity["sha256"])) == 64
    assert identity["family"] == "SourceHanSerifSC"


def test_fallback_order_puts_bundle_first() -> None:
    assert CJK_FALLBACKS[0].name.startswith("SourceHanSerifSC")
    assert CJK_BOLD_FALLBACKS[0].name.startswith("SourceHanSerifSC")
