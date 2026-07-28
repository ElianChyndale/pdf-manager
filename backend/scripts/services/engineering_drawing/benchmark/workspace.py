from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import fitz

from .schema import CoreManifest, CoreSample


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _sample_dir(samples_root: Path, sample_id: str) -> Path:
    sample_path = Path(sample_id)
    if (
        not sample_id
        or sample_id in {".", ".."}
        or len(sample_path.parts) != 1
        or sample_path.name != sample_id
    ):
        raise ValueError(f"sample_id must be a safe single path component: {sample_id!r}")
    sample_dir = (samples_root / sample_id).resolve()
    if samples_root not in sample_dir.parents:
        raise ValueError(f"sample_id must stay within workspace samples: {sample_id!r}")
    return sample_dir


def _preflight(
    source_root: Path,
    workspace: Path,
    manifest_sets: list[tuple[str, CoreManifest]],
) -> list[tuple[str, CoreSample, Path]]:
    samples_root = (workspace / "samples").resolve()
    selected: list[tuple[str, CoreSample, Path]] = []
    sample_ids = set()
    target_paths = [workspace / "manifest.lock.json"]
    for set_name, selected_manifest in manifest_sets:
        for spec in selected_manifest.samples:
            if spec.sample_id in sample_ids:
                raise ValueError(f"duplicate sample_id across manifests: {spec.sample_id}")
            sample_ids.add(spec.sample_id)
            sample_dir = _sample_dir(samples_root, spec.sample_id)
            if spec.page_number < 1:
                raise ValueError("page_number must be at least 1")
            if set_name == "core" and spec.page_number != 1:
                raise ValueError("core samples must use page 1")
            source = (source_root / spec.relative_pdf).resolve()
            if source_root not in source.parents or not source.is_file():
                raise FileNotFoundError(f"core source is missing or outside root: {source}")
            with fitz.open(source) as document:
                if spec.page_number > document.page_count:
                    raise ValueError(f"{spec.sample_id} page is outside source PDF")
            target_paths.extend(
                [
                    sample_dir / "source.pdf",
                    sample_dir / "source.png",
                    sample_dir / "sample.json",
                ]
            )
            selected.append((set_name, spec, sample_dir))
    existing_target = next((path for path in target_paths if path.exists()), None)
    if existing_target is not None:
        raise FileExistsError(f"benchmark target already exists: {existing_target}")
    return selected


def seed_workspace(
    source_root: Path,
    workspace: Path,
    manifest: CoreManifest,
    dpi: int = 144,
    challenge_manifest: CoreManifest | None = None,
) -> dict:
    source_root = Path(source_root).resolve()
    workspace = Path(workspace).resolve()
    manifest_sets = [(manifest.set_name, manifest)]
    if challenge_manifest is not None:
        manifest_sets.append((challenge_manifest.set_name, challenge_manifest))
    selected = _preflight(source_root, workspace, manifest_sets)
    records = []
    for set_name, spec, sample_dir in selected:
        source = (source_root / spec.relative_pdf).resolve()
        sample_dir.mkdir(parents=True, exist_ok=True)
        frozen_pdf = sample_dir / "source.pdf"
        with fitz.open(source) as document:
            frozen_document = fitz.open()
            frozen_document.insert_pdf(
                document,
                from_page=spec.page_number - 1,
                to_page=spec.page_number - 1,
            )
            frozen_document.save(
                frozen_pdf,
                garbage=4,
                deflate=True,
                no_new_id=True,
            )
            frozen_document.close()
        with fitz.open(frozen_pdf) as frozen_document:
            page = frozen_document[0]
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            pixmap.save(sample_dir / "source.png")
            page_size = [page.rect.width, page.rect.height]
            page_rotation = page.rotation
        record = {
            "sample_id": spec.sample_id,
            "set_name": set_name,
            "category": spec.category,
            "relative_pdf": spec.relative_pdf,
            "page_number": spec.page_number,
            "source_file_sha256": _hash(source),
            "source_sha256": _hash(frozen_pdf),
            "preview_sha256": _hash(sample_dir / "source.png"),
            "page_size": page_size,
            "page_rotation": page_rotation,
            "dpi": dpi,
            "goals": list(spec.goals),
            "status": "candidate",
        }
        _write_json(sample_dir / "sample.json", record)
        records.append(record)
    lock = {
        "schema": "engineering-drawing-benchmark-lock-v1",
        "benchmark_version": manifest.benchmark_version,
        "sample_count": len(records),
        "core_sample_count": sum(item["set_name"] == "core" for item in records),
        "challenge_sample_count": sum(
            item["set_name"] == "challenge" for item in records
        ),
        "production_output_touched": False,
        "samples": records,
    }
    _write_json(workspace / "manifest.lock.json", lock)
    return lock
