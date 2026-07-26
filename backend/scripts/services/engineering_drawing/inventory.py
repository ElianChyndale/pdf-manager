from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import fitz


LEGACY_DIR_MARKERS = ("translated drawing", "图纸翻译", "翻译")
COPY_DIR_MARKERS = ("a3 detail drawing",)
LEGACY_STEM_SUFFIXES = (
    "_translated",
    "-translated",
    " translated",
    "_翻译",
    "-翻译",
    " 翻译",
)


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_text(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _has_marker(path: Path, root: Path, markers: tuple[str, ...]) -> bool:
    relative = _relative_text(path, root).casefold()
    return any(marker.casefold() in relative for marker in markers)


def normalized_drawing_name(path: Path) -> str:
    stem = path.stem.strip()
    lowered = stem.casefold()
    changed = True
    while changed:
        changed = False
        for suffix in LEGACY_STEM_SUFFIXES:
            if lowered.endswith(suffix.casefold()):
                stem = stem[: -len(suffix)].rstrip(" _-")
                lowered = stem.casefold()
                changed = True
                break
    return re.sub(r"[\s_\-]+", "", lowered)


def drawing_version(path: Path) -> str:
    stem = path.stem
    for pattern in (
        r"(?:^|[-_\s])R(\d+[A-Za-z]?)\b",
        r"(?:^|[-_\s])REV(?:ISION)?\.?\s*[-_]?\s*([A-Za-z0-9]+)",
    ):
        match = re.search(pattern, stem, flags=re.IGNORECASE)
        if match:
            return match.group(1).casefold()
    return ""


def _page_count(path: Path) -> int:
    with fitz.open(path) as document:
        return document.page_count


@dataclass
class InventoryItem:
    content_hash: str
    source_path: str
    relative_path: str
    page_count: int
    legacy_translation_path: str = ""
    legacy_page_count: int = 0
    duplicate_paths: list[str] = field(default_factory=list)
    pairing_status: str = "missing_legacy"
    source_bytes: int = 0
    source_version: str = ""
    legacy_version: str = ""
    version_matches: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class Inventory:
    root: str
    items: list[InventoryItem]
    source_pdf_count: int
    unique_source_count: int
    duplicate_source_count: int
    legacy_pdf_count: int
    paired_count: int
    unpaired_source_count: int
    unpaired_legacy_paths: list[str]
    total_unique_source_pages: int
    total_legacy_pages: int

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "summary": {
                "source_pdf_count": self.source_pdf_count,
                "unique_source_count": self.unique_source_count,
                "duplicate_source_count": self.duplicate_source_count,
                "legacy_pdf_count": self.legacy_pdf_count,
                "paired_count": self.paired_count,
                "unpaired_source_count": self.unpaired_source_count,
                "unpaired_legacy_count": len(self.unpaired_legacy_paths),
                "total_unique_source_pages": self.total_unique_source_pages,
                "total_legacy_pages": self.total_legacy_pages,
            },
            "items": [item.to_dict() for item in self.items],
            "unpaired_legacy_paths": self.unpaired_legacy_paths,
        }

    def write(self, output_dir: Path) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "batch-manifest.json"
        csv_path = output_dir / "batch-manifest.csv"
        json_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        fieldnames = list(InventoryItem.__dataclass_fields__)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for item in self.items:
                row = item.to_dict()
                row["duplicate_paths"] = json.dumps(
                    row["duplicate_paths"], ensure_ascii=False
                )
                writer.writerow(row)
        return json_path, csv_path


def _select_canonical(paths: Iterable[Path], root: Path) -> Path:
    return min(
        paths,
        key=lambda path: (
            _has_marker(path, root, COPY_DIR_MARKERS),
            len(path.relative_to(root).parts),
            _relative_text(path, root).casefold(),
        ),
    )


def build_inventory(root: str | Path) -> Inventory:
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(f"inventory root does not exist: {root_path}")

    pdf_paths = sorted(
        (path for path in root_path.rglob("*.pdf") if path.is_file()),
        key=lambda path: _relative_text(path, root_path).casefold(),
    )
    legacy_paths = [
        path
        for path in pdf_paths
        if _has_marker(path, root_path, LEGACY_DIR_MARKERS)
    ]
    legacy_path_set = set(legacy_paths)
    source_paths = [path for path in pdf_paths if path not in legacy_path_set]

    sources_by_hash: dict[str, list[Path]] = {}
    for path in source_paths:
        sources_by_hash.setdefault(file_sha256(path), []).append(path)

    legacy_by_name: dict[str, list[Path]] = {}
    for path in legacy_paths:
        legacy_by_name.setdefault(normalized_drawing_name(path), []).append(path)

    matched_legacy: set[Path] = set()
    items: list[InventoryItem] = []
    for content_hash, duplicates in sources_by_hash.items():
        canonical = _select_canonical(duplicates, root_path)
        candidates = legacy_by_name.get(normalized_drawing_name(canonical), [])
        legacy = _select_canonical(candidates, root_path) if candidates else None
        if legacy:
            matched_legacy.add(legacy)
        source_version = drawing_version(canonical)
        legacy_version = drawing_version(legacy) if legacy else ""
        source_pages = _page_count(canonical)
        legacy_pages = _page_count(legacy) if legacy else 0
        status = "missing_legacy"
        if legacy:
            status = (
                "paired" if source_pages == legacy_pages else "page_count_mismatch"
            )
        items.append(
            InventoryItem(
                content_hash=content_hash,
                source_path=str(canonical),
                relative_path=_relative_text(canonical, root_path),
                page_count=source_pages,
                legacy_translation_path=str(legacy) if legacy else "",
                legacy_page_count=legacy_pages,
                duplicate_paths=[
                    _relative_text(path, root_path)
                    for path in duplicates
                    if path != canonical
                ],
                pairing_status=status,
                source_bytes=canonical.stat().st_size,
                source_version=source_version,
                legacy_version=legacy_version,
                version_matches=not legacy
                or not source_version
                or not legacy_version
                or source_version == legacy_version,
            )
        )

    items.sort(key=lambda item: item.relative_path.casefold())
    unpaired_legacy = [
        _relative_text(path, root_path)
        for path in legacy_paths
        if path not in matched_legacy
    ]
    return Inventory(
        root=str(root_path),
        items=items,
        source_pdf_count=len(source_paths),
        unique_source_count=len(items),
        duplicate_source_count=len(source_paths) - len(items),
        legacy_pdf_count=len(legacy_paths),
        paired_count=sum(bool(item.legacy_translation_path) for item in items),
        unpaired_source_count=sum(not item.legacy_translation_path for item in items),
        unpaired_legacy_paths=unpaired_legacy,
        total_unique_source_pages=sum(item.page_count for item in items),
        total_legacy_pages=sum(item.legacy_page_count for item in items),
    )
