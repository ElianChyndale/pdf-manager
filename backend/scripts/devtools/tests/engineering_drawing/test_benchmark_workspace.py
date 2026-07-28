import json
from hashlib import sha256
from pathlib import Path

import fitz
import pytest

from services.engineering_drawing.benchmark.schema import CoreManifest, CoreSample
from services.engineering_drawing.benchmark.workspace import seed_workspace


def _write_pdf(path: Path, page_count: int = 1) -> None:
    document = fitz.open()
    for page_number in range(page_count):
        document.new_page(width=300, height=200).insert_text(
            (20, 30), f"ROOF SYSTEM {page_number + 1}"
        )
    document.save(path)
    document.close()


def _manifest(*samples: CoreSample, set_name: str = "core") -> CoreManifest:
    return CoreManifest(
        schema=f"engineering-drawing-{set_name}-set-v1",
        benchmark_version=f"{set_name}-v1",
        samples=samples,
        set_name=set_name,
    )


def _sample(sample_id: str = "core-03", page_number: int = 1) -> CoreSample:
    return CoreSample(
        sample_id, "roof_detail", "one.pdf", page_number, ("semantic_block",)
    )


def test_seed_workspace_extracts_one_page_and_writes_complete_lock(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_pdf(source_root / "one.pdf", page_count=2)

    result = seed_workspace(source_root, tmp_path / "benchmark", _manifest(_sample()), dpi=96)

    sample_dir = tmp_path / "benchmark/samples/core-03"
    frozen = sample_dir / "source.pdf"
    preview = sample_dir / "source.png"
    metadata = json.loads((sample_dir / "sample.json").read_text(encoding="utf-8"))
    lock = json.loads(
        (tmp_path / "benchmark/manifest.lock.json").read_text(encoding="utf-8")
    )
    with fitz.open(frozen) as document:
        assert document.page_count == 1
    assert preview.exists()
    assert metadata == result["samples"][0]
    assert lock == result
    assert set(result) == {
        "schema",
        "benchmark_version",
        "sample_count",
        "core_sample_count",
        "challenge_sample_count",
        "production_output_touched",
        "samples",
    }
    assert set(metadata) == {
        "sample_id",
        "set_name",
        "category",
        "relative_pdf",
        "page_number",
        "source_file_sha256",
        "source_sha256",
        "preview_sha256",
        "page_size",
        "page_rotation",
        "dpi",
        "goals",
        "status",
    }
    assert metadata["source_sha256"] == sha256(frozen.read_bytes()).hexdigest()
    assert metadata["preview_sha256"] == sha256(preview.read_bytes()).hexdigest()
    assert result["sample_count"] == result["core_sample_count"] == 1
    assert result["challenge_sample_count"] == 0
    assert result["production_output_touched"] is False


def test_seed_workspace_includes_challenge_samples_and_counts(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_pdf(source_root / "one.pdf")
    core = _manifest(_sample("core-03"))
    challenge = _manifest(_sample("challenge-01"), set_name="challenge")

    result = seed_workspace(source_root, tmp_path / "benchmark", core, challenge_manifest=challenge)

    assert [record["set_name"] for record in result["samples"]] == ["core", "challenge"]
    assert result["sample_count"] == 2
    assert result["core_sample_count"] == 1
    assert result["challenge_sample_count"] == 1
    assert (tmp_path / "benchmark/samples/challenge-01/source.pdf").exists()


def test_seed_workspace_rejects_traversal_sample_id_without_external_write(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_pdf(source_root / "one.pdf")
    manifest = _manifest(_sample("../../outside"))

    with pytest.raises(ValueError, match="sample_id"):
        seed_workspace(source_root, tmp_path / "benchmark", manifest)

    assert not (tmp_path / "outside").exists()
    assert not (tmp_path / "benchmark").exists()


@pytest.mark.parametrize(
    ("relative_pdf", "goals"),
    [
        ("../escape.pdf", ("semantic_block",)),
        ("C:/escape.pdf", ("semantic_block",)),
        (r"C:\escape.pdf", ("semantic_block",)),
        (r"\\server\share\escape.pdf", ("semantic_block",)),
        (r"\\?\C:\escape.pdf", ("semantic_block",)),
        (r"\\.\NUL.pdf", ("semantic_block",)),
        ("one.pdf", ("semantic_block", "semantic_block")),
        ("one.pdf", ("unknown_goal",)),
    ],
)
def test_seed_workspace_rejects_invalid_manifest_before_any_write(
    tmp_path: Path, relative_pdf: str, goals: tuple[str, ...]
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_pdf(source_root / "one.pdf")
    workspace = tmp_path / "benchmark"

    with pytest.raises(ValueError):
        sample = CoreSample("core-03", "roof_detail", relative_pdf, 1, goals)
        seed_workspace(source_root, workspace, _manifest(sample))

    assert not workspace.exists()
    assert not list(tmp_path.rglob("*.tmp"))
    assert not list(tmp_path.rglob("manifest.lock.json"))


def test_seed_workspace_rejects_cross_set_duplicate_ids_before_writing(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_pdf(source_root / "one.pdf")
    core = _manifest(_sample("shared-01"))
    challenge = _manifest(_sample("shared-01"), set_name="challenge")

    with pytest.raises(ValueError, match="duplicate sample_id"):
        seed_workspace(source_root, tmp_path / "benchmark", core, challenge_manifest=challenge)

    assert not (tmp_path / "benchmark").exists()


@pytest.mark.parametrize(
    ("page_number", "match"),
    [
        (0, "page_number must be at least 1"),
        (2, "core samples must use page 1"),
    ],
)
def test_seed_workspace_rejects_invalid_requested_pages_before_writing(
    tmp_path: Path, page_number: int, match: str
):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_pdf(source_root / "one.pdf", page_count=2)

    with pytest.raises(ValueError, match=match):
        manifest = _manifest(_sample(page_number=page_number))
        seed_workspace(source_root, tmp_path / "benchmark", manifest)

    assert not (tmp_path / "benchmark").exists()


def test_seed_workspace_rejects_page_beyond_source_page_count_before_writing(
    tmp_path: Path,
):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_pdf(source_root / "one.pdf")
    manifest = _manifest(_sample("challenge-01", page_number=2), set_name="challenge")

    with pytest.raises(ValueError, match="page is outside source PDF"):
        seed_workspace(source_root, tmp_path / "benchmark", manifest)

    assert not (tmp_path / "benchmark").exists()


@pytest.mark.parametrize(
    "existing_target",
    [
        Path("samples/core-03/source.pdf"),
        Path("samples/core-03/source.png"),
        Path("samples/core-03/sample.json"),
        Path("manifest.lock.json"),
    ],
)
def test_seed_workspace_rejects_existing_owned_targets_without_mutation(
    tmp_path: Path, existing_target: Path
):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_pdf(source_root / "one.pdf")
    workspace = tmp_path / "benchmark"
    existing = workspace / existing_target
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"preserve me")

    with pytest.raises(FileExistsError, match="benchmark target already exists"):
        seed_workspace(source_root, workspace, _manifest(_sample()))

    assert existing.read_bytes() == b"preserve me"
    assert not (workspace / "manifest.lock.json").exists() or existing.name == "manifest.lock.json"


def test_seed_workspace_rejects_reseeding_without_mutating_existing_workspace(
    tmp_path: Path,
):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_pdf(source_root / "one.pdf")
    workspace = tmp_path / "benchmark"
    manifest = _manifest(_sample())
    seed_workspace(source_root, workspace, manifest)
    original_lock = (workspace / "manifest.lock.json").read_bytes()

    with pytest.raises(FileExistsError, match="benchmark target already exists"):
        seed_workspace(source_root, workspace, manifest)

    assert (workspace / "manifest.lock.json").read_bytes() == original_lock
