from hashlib import sha256
from pathlib import Path

import fitz

from services.engineering_drawing.benchmark.schema import CoreManifest, CoreSample
from services.engineering_drawing.benchmark.workspace import seed_workspace


def test_seed_workspace_extracts_page_and_writes_stable_hashes(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    pdf = source_root / "one.pdf"
    document = fitz.open()
    document.new_page(width=300, height=200).insert_text((20, 30), "ROOF SYSTEM")
    document.save(pdf)
    document.close()
    manifest = CoreManifest(
        schema="engineering-drawing-core-set-v1",
        benchmark_version="test-v1",
        samples=(
            CoreSample("core-03", "roof_detail", "one.pdf", 1, ("semantic_block",)),
        ),
    )

    result = seed_workspace(source_root, tmp_path / "benchmark", manifest, dpi=96)

    sample_dir = tmp_path / "benchmark/samples/core-03"
    frozen = sample_dir / "source.pdf"
    assert frozen.exists()
    assert (sample_dir / "source.png").exists()
    assert result["sample_count"] == 1
    assert result["samples"][0]["source_sha256"] == sha256(frozen.read_bytes()).hexdigest()
    assert result["production_output_touched"] is False
