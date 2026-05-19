from pathlib import Path

import fitz


ALL_META_KEYS = ["title", "author", "subject", "keywords", "creator", "producer"]


def read_metadata(input_path: Path) -> dict:
    """Read PDF metadata. Returns dict with available fields."""
    doc = fitz.open(input_path)
    meta = doc.metadata or {}
    doc.close()
    return {k: meta.get(k, "") for k in ALL_META_KEYS}


def write_metadata(input_path: Path, output_path: Path, updates: dict) -> dict:
    """Update PDF metadata fields. Only non-empty values are applied."""
    doc = fitz.open(input_path)
    meta = doc.metadata or {}
    for k in ALL_META_KEYS:
        if k in updates and updates[k]:
            meta[k] = str(updates[k])
    doc.set_metadata(meta)
    doc.save(output_path, deflate=True, garbage=4)
    doc.close()
    return {"updated_fields": [k for k in updates if k in ALL_META_KEYS and updates[k]]}
