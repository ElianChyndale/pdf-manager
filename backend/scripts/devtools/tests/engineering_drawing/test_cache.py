"""Stage-scoped cache: fingerprints, atomic writes, integrity, corruption."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.engineering_drawing.cache import (
    load_cache,
    save_cache,
    stage_code_fingerprint,
)


def test_stage_code_fingerprint_changes_with_relevant_file(tmp_path: Path) -> None:
    module = tmp_path / "stage_module.py"
    module.write_text("def run(): return 1", encoding="utf-8")
    first = stage_code_fingerprint(paths=[module])
    module.write_text("def run(): return 2", encoding="utf-8")
    second = stage_code_fingerprint(paths=[module])
    assert first != second
    # A different, unrelated file does NOT change the fingerprint.
    unrelated = tmp_path / "unrelated.py"
    unrelated.write_text("# comment", encoding="utf-8")
    assert stage_code_fingerprint(paths=[module]) == second


def test_stage_code_fingerprint_includes_extra_payload(tmp_path: Path) -> None:
    module = tmp_path / "m.py"
    module.write_text("x", encoding="utf-8")
    a = stage_code_fingerprint(paths=[module], extra_payload={"prompt_version": "v1"})
    b = stage_code_fingerprint(paths=[module], extra_payload={"prompt_version": "v2"})
    assert a != b


def test_cache_roundtrip_atomic(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    save_cache(cache_path, {"k1": {"translated": "屋顶"}}, schema="engineering-drawing-cache-v1-test")
    entries = load_cache(cache_path, schema="engineering-drawing-cache-v1-test")
    assert entries["k1"]["translated"] == "屋顶"
    # A second write replaces atomically (no leftover temp files).
    save_cache(cache_path, {"k2": {"translated": "门"}}, schema="engineering-drawing-cache-v1-test")
    assert not list(tmp_path.glob("*.tmp"))
    assert load_cache(cache_path, schema="engineering-drawing-cache-v1-test") == {"k2": {"translated": "门"}}


def test_cache_isolates_corrupt_file(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{corrupt", encoding="utf-8")
    assert load_cache(cache_path, schema="engineering-drawing-cache-v1-test") == {}
    # The corrupt file is renamed aside, not served or silently rewritten.
    assert cache_path.with_suffix(".json.corrupt").exists()


def test_cache_detects_tampered_content_hash(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    save_cache(cache_path, {"k": {"t": "x"}}, schema="engineering-drawing-cache-v1-test")
    # Tamper with the entries but leave the stored hash stale.
    import json

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["entries"]["k"]["t"] = "y"
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert load_cache(cache_path, schema="engineering-drawing-cache-v1-test") == {}
