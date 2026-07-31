"""Token preservation for numbers, units, identifiers and drawing codes.

Engineering deliverable correctness depends on identifiers being preserved
verbatim — ``DN200``, ``220 kV``, ``A-103``, ``ASTM A36``, ``1:100``, ``25 mm``.
But byte-identical comparison is too strict (OCR/Unicode/typography introduce
equivalent changes).  We compare in two layers:

- ``exact_preservation``: the token must appear byte-identical in the target.
- ``canonical_preservation``: the token is normalized first (NFKC, hyphens,
  full-width colon, unit case, optional space, ``×/x``, ``Ø/ø``) and then must
  appear in the normalized target.

A HARD failure is real loss (``DN200 -> DN20``, ``220 kV -> 22 kV``); a pure
typographic variation (``25 mm`` vs ``25mm``) is canonical-preserved, not lost.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping

TOKEN_PRESERVATION_SCHEMA = "engineering-drawing-token-preservation-v1"

# Tokens to verify: numbers-with-units, identifiers, model codes, scales.
_TOKEN_RE = re.compile(
    r"(?:\d+(?:[.,]\d+)?\s*(?:mm|cm|m|km|kV|V|A|kW|MW|Hz|bar|MPa|%|°|in|ft)\b"
    r"|(?:DN|A-|ASTM|ISO|EN|GB|JB|TB|CJ)\s?[A-Z0-9\-]+"
    r"|\d+\s*:\s*\d+"
    r"|Ø\s?\d+(?:\.\d+)?|ø\s?\d+(?:\.\d+)?"
    r"|\d+\s*[x×]\s*\d+)",
    re.IGNORECASE,
)


def _canonical(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("‐", "-").replace("‑", "-").replace("‒", "-").replace("–", "-").replace("—", "-")
    text = text.replace("：", ":")  # full-width colon
    text = text.replace("Ø", "ø")
    text = text.replace("×", "x")
    text = re.sub(r"\s+", "", text)  # optional space normalization
    return text.casefold()


def _tokens_in(source: str, target: str) -> list[dict[str, Any]]:
    tokens = [m.group(0) for m in _TOKEN_RE.finditer(source)]
    canonical_target = _canonical(target)
    records = []
    for token in tokens:
        token_canonical = _canonical(token)
        exact = token in target
        canonical = token_canonical in canonical_target
        records.append(
            {
                "token": token,
                "canonical_token": token_canonical,
                "exact_preserved": bool(exact),
                "canonical_preserved": bool(exact or canonical),
            }
        )
    return records


def check_token_preservation(
    *,
    source_text: str,
    target_text: str,
    region_id: str = "",
) -> dict[str, Any]:
    """Return per-token preservation for one source->target pair."""
    records = _tokens_in(source_text, target_text)
    lost = [r for r in records if not r["canonical_preserved"]]
    return {
        "region_id": region_id,
        "source_token_count": len(records),
        "preserved_numeric_token_count": sum(1 for r in records if r["canonical_preserved"]),
        "lost_tokens": lost,
        "preserved": not lost,
    }


def scan_regions(
    *,
    regions: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Scan a set of regions and aggregate token preservation."""
    results = []
    total = lost = 0
    unique_lost_region_ids: set[str] = set()
    for region in regions:
        if not isinstance(region, Mapping):
            continue
        source = str(region.get("source_text") or "")
        target = str(region.get("translated_text") or "")
        if not source or not target:
            continue
        result = check_token_preservation(source_text=source, target_text=target, region_id=str(region.get("region_id") or region.get("block_id") or ""))
        total += result["source_token_count"]
        lost += len(result["lost_tokens"])
        if result["lost_tokens"]:
            unique_lost_region_ids.add(result["region_id"])
        results.append(result)
    return {
        "schema": TOKEN_PRESERVATION_SCHEMA,
        "source_token_count": total,
        "preserved_numeric_token_count": total - lost,
        "identifier_preservation_accuracy": round((total - lost) / total, 4) if total else 0.0,
        "unique_lost_region_ids": sorted(unique_lost_region_ids),
        "regions": results,
    }


__all__ = ["TOKEN_PRESERVATION_SCHEMA", "check_token_preservation", "scan_regions"]
