"""Benchmark held-out split manifest and guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.engineering_drawing.benchmark.split import (
    SPLIT_SCHEMA,
    VALID_SPLITS,
    default_split_assignment,
    guard_heldout,
    heldout_sample_ids,
    load_split_manifest,
    write_split_manifest,
)


def test_valid_splits() -> None:
    assert VALID_SPLITS == ("dev", "regression", "validation", "heldout")


def test_default_assignment() -> None:
    assignments = default_split_assignment([f"core-{i:02d}" for i in range(1, 13)])
    assert assignments["core-01"] == "regression"
    assert assignments["core-08"] == "regression"
    assert assignments["core-09"] == "validation"
    assert assignments["core-10"] == "validation"
    assert assignments["core-11"] == "heldout"
    assert assignments["core-12"] == "heldout"


def test_write_load_and_refuse_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "split-manifest.json"
    write_split_manifest(
        path=path,
        assignments={"core-01": "regression", "core-11": "heldout"},
        benchmark_version="core-v1",
        author="tester",
        created_at="2026-07-31T00:00:00Z",
    )
    manifest = load_split_manifest(path)
    assert manifest.schema == SPLIT_SCHEMA
    assert manifest.assignments == {"core-01": "regression", "core-11": "heldout"}
    assert heldout_sample_ids(manifest) == {"core-11"}
    with pytest.raises(ValueError, match="overwrite a different split manifest"):
        write_split_manifest(
            path=path,
            assignments={"core-01": "heldout"},
            benchmark_version="core-v1",
            author="tester",
            created_at="2026-07-31T00:00:00Z",
        )
    write_split_manifest(
        path=path,
        assignments={"core-01": "heldout"},
        benchmark_version="core-v1",
        author="tester",
        created_at="2026-07-31T00:00:00Z",
        force=True,
    )
    assert load_split_manifest(path).assignments == {"core-01": "heldout"}


def test_guard_heldout_blocks_without_flag(tmp_path: Path) -> None:
    path = tmp_path / "split-manifest.json"
    write_split_manifest(
        path=path,
        assignments={"core-11": "heldout", "core-01": "regression"},
        benchmark_version="core-v1",
        author="tester",
        created_at="2026-07-31T00:00:00Z",
    )
    with pytest.raises(ValueError, match="--use-heldout"):
        guard_heldout(sample_ids=["core-01", "core-11"], split_path=path, use_heldout=False)
    blocked = guard_heldout(sample_ids=["core-01", "core-11"], split_path=path, use_heldout=True)
    assert blocked == {"core-11"}


def test_guard_heldout_noop_without_manifest(tmp_path: Path) -> None:
    assert guard_heldout(sample_ids=["core-11"], split_path=None, use_heldout=False) == set()
    assert guard_heldout(sample_ids=["core-11"], split_path=tmp_path / "missing.json", use_heldout=False) == set()


def test_write_manifest_rejects_invalid_split(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported split"):
        write_split_manifest(
            path=tmp_path / "bad.json",
            assignments={"core-01": "training"},
            benchmark_version="core-v1",
            author="tester",
            created_at="2026-07-31T00:00:00Z",
        )
