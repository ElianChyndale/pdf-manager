"""Held-out validation-set discipline for the engineering-drawing benchmark.

The benchmark corpus (core-01..12) was a single undifferentiated evaluation set.
This module adds an immutable split manifest that partitions samples into
``dev / regression / validation / heldout`` so a candidate pipeline can no
longer tune against every sample.  The split manifest is the authority and is
kept separate from ``core-set.v1.json`` (whose schema enforces a closed field
set).  When no split manifest is present, every benchmark command behaves as it
did before (legacy, no guard).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

SPLIT_SCHEMA = "engineering-drawing-benchmark-split-v1"
VALID_SPLITS = ("dev", "regression", "validation", "heldout")


@dataclass(frozen=True)
class SplitManifest:
    schema: str
    benchmark_version: str
    author: str
    created_at: str
    assignments: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "benchmark_version": self.benchmark_version,
            "author": self.author,
            "created_at": self.created_at,
            "assignments": dict(self.assignments),
        }


def default_split_assignment(core_sample_ids: Iterable[str]) -> dict[str, str]:
    """Propose a deterministic default: regression = 01-08, validation = 09-10,
    heldout = 11-12, dev = none."""
    ids = sorted(str(value) for value in core_sample_ids)
    assignments: dict[str, str] = {}
    for index, sample_id in enumerate(ids, start=1):
        if index <= 8:
            assignments[sample_id] = "regression"
        elif index <= 10:
            assignments[sample_id] = "validation"
        else:
            assignments[sample_id] = "heldout"
    return assignments


def _validate_assignments(assignments: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for sample_id, split in assignments.items():
        sample_id = str(sample_id or "").strip()
        split = str(split or "").strip()
        if not sample_id:
            raise ValueError("split manifest assignments require a sample_id")
        if split not in VALID_SPLITS:
            raise ValueError(f"unsupported split {split!r} (must be one of {VALID_SPLITS})")
        if sample_id in normalized:
            raise ValueError(f"duplicate sample_id in split manifest: {sample_id}")
        normalized[sample_id] = split
    return normalized


def write_split_manifest(
    *,
    path: Path,
    assignments: Mapping[str, str],
    benchmark_version: str,
    author: str,
    created_at: str,
    force: bool = False,
) -> Path:
    """Write an immutable split manifest.

    Refuses to overwrite an existing manifest whose assignments differ, unless
    ``force`` is given.
    """
    path = Path(path)
    normalized = _validate_assignments(assignments)
    manifest = SplitManifest(
        schema=SPLIT_SCHEMA,
        benchmark_version=benchmark_version,
        author=str(author or "").strip() or "unknown",
        created_at=created_at,
        assignments=normalized,
    )
    payload = manifest.to_dict()
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if path.exists():
        existing = load_split_manifest(path)
        if existing.assignments != normalized and not force:
            raise ValueError("refusing to overwrite a different split manifest; pass --force to override")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical, encoding="utf-8")
    return path


def load_split_manifest(path: Path) -> SplitManifest:
    """Load and validate a split manifest from disk."""
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SPLIT_SCHEMA:
        raise ValueError("split manifest has an unexpected schema")
    assignments = _validate_assignments(payload.get("assignments") or {})
    return SplitManifest(
        schema=SPLIT_SCHEMA,
        benchmark_version=str(payload.get("benchmark_version") or ""),
        author=str(payload.get("author") or ""),
        created_at=str(payload.get("created_at") or ""),
        assignments=assignments,
    )


def heldout_sample_ids(split_manifest: Mapping[str, str] | SplitManifest) -> set[str]:
    """Return the set of sample_ids assigned to the heldout split."""
    if isinstance(split_manifest, SplitManifest):
        assignments = split_manifest.assignments
    else:
        assignments = dict(split_manifest or {})
    return {sample_id for sample_id, split in assignments.items() if split == "heldout"}


def guard_heldout(
    *,
    sample_ids: Iterable[str],
    split_path: Path | None,
    use_heldout: bool,
) -> set[str]:
    """Refuse to run on heldout samples unless ``use_heldout`` is set.

    When ``split_path`` is None (no split manifest present), this is a no-op —
    legacy behavior.  Returns the set of heldout sample_ids that would be
    touched.
    """
    sample_ids = {str(value) for value in sample_ids}
    if split_path is None or not Path(split_path).is_file():
        return set()
    manifest = load_split_manifest(split_path)
    heldout = heldout_sample_ids(manifest)
    blocked = heldout & sample_ids
    if blocked and not use_heldout:
        raise ValueError(
            "heldout samples require --use-heldout: " + ", ".join(sorted(blocked))
        )
    return blocked


__all__ = [
    "SPLIT_SCHEMA",
    "VALID_SPLITS",
    "SplitManifest",
    "default_split_assignment",
    "guard_heldout",
    "heldout_sample_ids",
    "load_split_manifest",
    "write_split_manifest",
]
