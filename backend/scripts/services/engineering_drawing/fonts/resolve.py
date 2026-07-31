"""Portable CJK font resolution for the V4 rendering path.

The legacy renderers hardcoded ``C:\\Windows\\Fonts\\simhei.ttf``, which breaks
Linux/Docker and produces cross-machine layout drift.  This module resolves a
licensed project font deterministically:

1. Prefer the bundled repo font ``backend/fonts/SourceHanSerifSC-Regular.otf``
   (and its Bold variant for emphasized text).
2. Fall back to platform paths (Windows simhei, Linux Noto) only if the bundled
   font is missing — never as the primary path.
3. Expose ``font_sha256`` so preflight and the delivery manifest can pin the
   exact font asset that produced a deliverable.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[4]
FONTS_DIR = BACKEND_DIR / "fonts"

# Bundle order: repo font first, then per-platform fallbacks.
CJK_FALLBACKS = (
    FONTS_DIR / "SourceHanSerifSC-Regular.otf",
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
)

CJK_BOLD_FALLBACKS = (
    FONTS_DIR / "SourceHanSerifSC-Bold.otf",
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
)


def resolve_cjk_font(*, bold: bool = False) -> Path:
    """Return the first existing CJK font path (bundled repo font preferred)."""
    candidates = CJK_BOLD_FALLBACKS if bold else CJK_FALLBACKS
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "No CJK font found. Install a CJK font or place SourceHanSerifSC-"
        "Regular.otf under the project fonts/ directory. Tried: "
        + ", ".join(str(c) for c in candidates)
    )


def font_sha256(path: Path | None = None) -> str | None:
    """SHA-256 of the resolved font file (None when no font is available)."""
    try:
        font_path = Path(path) if path else resolve_cjk_font()
    except FileNotFoundError:
        return None
    return sha256(font_path.read_bytes()).hexdigest()


def font_identity() -> dict[str, object]:
    """Return the resolved font name, path and hash for the delivery manifest."""
    try:
        font_path = resolve_cjk_font()
        return {
            "family": "SourceHanSerifSC" if "SourceHanSerifSC" in str(font_path) else font_path.stem,
            "path": str(font_path),
            "sha256": font_sha256(font_path),
        }
    except FileNotFoundError:
        return {"family": "unknown", "path": "", "sha256": None}


__all__ = [
    "CJK_BOLD_FALLBACKS",
    "CJK_FALLBACKS",
    "font_identity",
    "font_sha256",
    "resolve_cjk_font",
]
