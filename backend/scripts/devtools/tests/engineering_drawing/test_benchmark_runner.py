from __future__ import annotations

import json
import hashlib
from pathlib import Path

import fitz
import pytest

import services.engineering_drawing.cli as engineering_cli
from services.engineering_drawing.benchmark.schema import CoreManifest, CoreSample
from services.engineering_drawing.cli import main


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _one_page(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((20, 30), text)
    document.save(path)
    document.close()


def _gold() -> dict:
    return {
        "schema": "engineering-drawing-gold-v1",
        "sample_id": "core-03",
        "gold_version": 2,
        "status": "locked",
        "page": {"width": 300, "height": 200, "rotation": 0},
        "blocks": [
            {
                "block_id": "core-03-b001",
                "source_text": "ROOF SYSTEM",
                "source_language": "en",
                "source_bbox": [20, 18, 100, 35],
                "rotation": 0,
                "reading_order": 1,
                "group_member_ids": ["r001"],
                "merge_decision": "single",
                "gold_translation": "屋面系统",
                "literal_tokens": [],
                "allowed_regions": [[120, 10, 220, 45]],
                "forbidden_zones": [[20, 18, 100, 35]],
                "font_size_range": [3.2, 6.5],
                "leader": {
                    "allowed": False,
                    "required": False,
                    "color": "dark_blue",
                    "width_points": 0.32,
                    "route": "orthogonal",
                    "arrow": False,
                },
                "manual_review_required": False,
                "legacy_fallback": False,
            }
        ],
        "audit": [
            {
                "action": "lock",
                "actor": "reviewer",
                "decided_at": "2026-07-28T10:00:00+08:00",
                "from_version": 1,
                "to_version": 2,
            }
        ],
    }


def _candidate_region() -> dict:
    return {
        "block_id": "core-03-b001",
        "translated_text": "屋面系统",
        "merge_decision": "single",
        "rotation": 0,
        "target_bbox": [120, 10, 180, 30],
        "font_size": 5,
        "leader": {"status": "not_needed"},
    }


def _seed_evaluation_tree(workspace: Path, candidate_root: Path) -> None:
    sample_dir = workspace / "samples" / "core-03"
    _one_page(sample_dir / "source.pdf", "ROOF SYSTEM")
    _one_page(candidate_root / "core-03.pdf", "ROOF SYSTEM")
    source_sha256 = hashlib.sha256(
        (sample_dir / "source.pdf").read_bytes()
    ).hexdigest()
    _write_json(
        workspace / "manifest.lock.json",
        {
            "schema": "engineering-drawing-benchmark-lock-v1",
            "benchmark_version": "test-v1",
            "sample_count": 1,
            "core_sample_count": 1,
            "challenge_sample_count": 0,
            "production_output_touched": False,
            "samples": [
                {
                    "sample_id": "core-03",
                    "set_name": "core",
                    "category": "roof_detail",
                    "relative_pdf": "roof.pdf",
                    "page_number": 1,
                    "source_file_sha256": "a" * 64,
                    "source_sha256": source_sha256,
                    "preview_sha256": "c" * 64,
                    "page_size": [300, 200],
                    "page_rotation": 0,
                    "dpi": 144,
                    "goals": ["semantic_block"],
                    "status": "candidate",
                }
            ],
        },
    )
    _write_json(sample_dir / "gold.locked.json", _gold())
    _write_json(
        candidate_root / "core-03.regions.json",
        {"regions": [_candidate_region()]},
    )
    _write_json(
        candidate_root / "core-03.inline-placement.json",
        {
            "placements": [
                {
                    "region_id": "core-03-b001",
                    "page_index": 0,
                    "source_bbox": [20, 18, 100, 35],
                    "target_bbox": [120, 10, 180, 30],
                    "translated_text": "屋面系统",
                    "status": "inline_near",
                    "coverage_status": "translated",
                    "leader": {"status": "not_needed", "path": []},
                }
            ]
        },
    )
    _write_json(
        candidate_root / "core-03.subjective.json",
        {
            "schema": "engineering-drawing-visual-review-v1",
            "prompt_version": "2026-07-benchmark-visual-v1",
            "sample_id": "core-03",
            "model": "gpt-5.6-sol",
            "layout_association": 20,
            "page_readability": 15,
            "findings": [],
        },
    )


def test_benchmark_seed_never_creates_production_translated_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "malasia" / "roof.pdf"
    _one_page(source, "ROOF SYSTEM")
    workspace = tmp_path / "output/pdf/engineering-drawing/benchmark"
    manifest = CoreManifest(
        schema="engineering-drawing-core-set-v1",
        benchmark_version="test-v1",
        samples=(
            CoreSample(
                "core-03",
                "roof_detail",
                "roof.pdf",
                1,
                ("semantic_block",),
            ),
        ),
    )
    challenge = CoreManifest(
        schema="engineering-drawing-challenge-set-v1",
        benchmark_version="challenge-test-v1",
        samples=(),
        set_name="challenge",
    )
    monkeypatch.setattr(engineering_cli, "load_core_manifest", lambda _path: manifest)
    monkeypatch.setattr(
        engineering_cli, "load_challenge_manifest", lambda _path: challenge
    )

    assert (
        main(
            [
                "benchmark-seed",
                "--source-root",
                str(tmp_path / "malasia"),
                "--workspace",
                str(workspace),
            ]
        )
        == 0
    )
    assert (workspace / "samples/core-03/source.pdf").exists()
    assert not list((tmp_path / "output").rglob("translated/*.pdf"))


def test_benchmark_seed_rejects_translated_delivery_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        engineering_cli,
        "seed_workspace",
        lambda *_args, **_kwargs: pytest.fail(
            "delivery path must be rejected before seeding"
        ),
    )

    with pytest.raises(ValueError, match="translated delivery"):
        main(
            [
                "benchmark-seed",
                "--source-root",
                str(tmp_path / "malasia"),
                "--workspace",
                str(
                    tmp_path
                    / "01_Bilingual_Inline"
                    / "translated"
                    / "benchmark"
                ),
            ]
        )


def test_model_backed_cli_rejects_sample_id_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    workspace.mkdir()
    monkeypatch.setattr(
        engineering_cli,
        "get_api_key",
        lambda: pytest.fail("invalid sample must be rejected before API access"),
    )

    with pytest.raises(ValueError, match="sample_id"):
        main(
            [
                "benchmark-prelabel",
                "--workspace",
                str(workspace),
                "--sample-id",
                "../escape",
                "--regions-json",
                str(tmp_path / "regions.json"),
            ]
        )


def test_single_sample_locked_gold_to_report_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.engineering_drawing.benchmark import runner

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    monkeypatch.setattr(
        runner,
        "analyze_visual_qa",
        lambda **_kwargs: {
            "visual_overlap_count": 0,
            "leader_collision_count": 0,
            "untranslated_candidate_count": 0,
        },
    )

    result = runner.evaluate_workspace(workspace, candidate_root)

    assert result["hard_failure_count"] == 0
    assert result["core_score"] == 100
    assert result["manual_review_rate"] == 0
    assert result["automation_rate"] == 1
    assert (workspace / "reports/benchmark-report.html").exists()
    assert (workspace / "comparisons/core-03.png").exists()


def test_evaluate_rejects_path_traversal_before_writing_artifacts(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    lock = json.loads((workspace / "manifest.lock.json").read_text(encoding="utf-8"))
    lock["samples"][0]["sample_id"] = "../escape"
    _write_json(workspace / "manifest.lock.json", lock)

    with pytest.raises(ValueError, match="sample_id"):
        evaluate_workspace(workspace, candidate_root)

    assert not (workspace / "comparisons").exists()
    assert not (workspace / "reports").exists()


def test_evaluate_requires_canonical_visual_review_before_writing_artifacts(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    subjective = candidate_root / "core-03.subjective.json"
    payload = json.loads(subjective.read_text(encoding="utf-8"))
    payload["sample_id"] = "wrong"
    _write_json(subjective, payload)

    with pytest.raises(ValueError, match="visual review"):
        evaluate_workspace(workspace, candidate_root)

    assert not (workspace / "comparisons").exists()
    assert not (workspace / "reports").exists()


def test_evaluate_rejects_tampered_frozen_source_before_writing_artifacts(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    source = workspace / "samples/core-03/source.pdf"
    source.write_bytes(source.read_bytes() + b"\n% tampered")

    with pytest.raises(ValueError, match="source hash"):
        evaluate_workspace(workspace, candidate_root)

    assert not (workspace / "comparisons").exists()
    assert not (workspace / "reports").exists()
