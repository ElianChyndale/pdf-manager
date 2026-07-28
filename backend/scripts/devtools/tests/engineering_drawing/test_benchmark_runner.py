from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

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


def _candidate_page(path: Path, *, include_translation: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((20, 30), "ROOF SYSTEM")
    if include_translation:
        page.insert_text(
            (125, 25),
            "屋面系统",
            fontname="china-s",
            fontsize=5,
        )
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
    with fitz.open(sample_dir / "source.pdf") as document:
        document[0].get_pixmap(dpi=144, alpha=False).save(
            sample_dir / "source.png"
        )
    _candidate_page(candidate_root / "core-03.pdf")
    source_sha256 = hashlib.sha256(
        (sample_dir / "source.pdf").read_bytes()
    ).hexdigest()
    record = {
        "sample_id": "core-03",
        "set_name": "core",
        "category": "roof_detail",
        "relative_pdf": "roof.pdf",
        "page_number": 1,
        "source_file_sha256": "a" * 64,
        "source_sha256": source_sha256,
        "preview_sha256": hashlib.sha256(
            (sample_dir / "source.png").read_bytes()
        ).hexdigest(),
        "page_size": [300, 200],
        "page_rotation": 0,
        "dpi": 144,
        "goals": ["semantic_block"],
        "status": "candidate",
    }
    _write_json(
        workspace / "manifest.lock.json",
        {
            "schema": "engineering-drawing-benchmark-lock-v1",
            "benchmark_version": "test-v1",
            "sample_count": 1,
            "core_sample_count": 1,
            "challenge_sample_count": 0,
            "production_output_touched": False,
            "samples": [record],
        },
    )
    _write_json(sample_dir / "sample.json", record)
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
    _write_json(
        candidate_root / "core-03.evidence.json",
        {
            "schema": "engineering-drawing-candidate-evidence-v1",
            "sample_id": "core-03",
            "candidate_sha256": hashlib.sha256(
                (candidate_root / "core-03.pdf").read_bytes()
            ).hexdigest(),
            "regions_sha256": hashlib.sha256(
                (candidate_root / "core-03.regions.json").read_bytes()
            ).hexdigest(),
            "placement_sha256": hashlib.sha256(
                (
                    candidate_root / "core-03.inline-placement.json"
                ).read_bytes()
            ).hexdigest(),
            "subjective_sha256": hashlib.sha256(
                (candidate_root / "core-03.subjective.json").read_bytes()
            ).hexdigest(),
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


def test_single_sample_locked_gold_to_report_flow(tmp_path: Path) -> None:
    from services.engineering_drawing.benchmark import runner

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)

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


def _refresh_evidence_hash(
    candidate_root: Path, field: str, artifact_name: str
) -> None:
    evidence_path = candidate_root / "core-03.evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence[field] = hashlib.sha256(
        (candidate_root / artifact_name).read_bytes()
    ).hexdigest()
    _write_json(evidence_path, evidence)


def test_source_only_candidate_is_a_hard_failure(tmp_path: Path) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    candidate = candidate_root / "core-03.pdf"
    candidate.unlink()
    _candidate_page(candidate, include_translation=False)
    _refresh_evidence_hash(
        candidate_root, "candidate_sha256", "core-03.pdf"
    )

    result = evaluate_workspace(workspace, candidate_root)

    assert result["core_score"] < 100
    assert result["hard_failure_count"] >= 1
    assert "untranslated_candidate" in result["samples"][0]["hard_failure_ids"]


def test_evaluate_rejects_stale_candidate_hash_before_writes(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    candidate = candidate_root / "core-03.pdf"
    candidate.write_bytes(candidate.read_bytes() + b"\n% stale")

    with pytest.raises(ValueError, match="evidence hash mismatch"):
        evaluate_workspace(workspace, candidate_root)

    assert not (workspace / "comparisons").exists()
    assert not (workspace / "reports").exists()


def test_evaluate_rejects_region_placement_mismatch_before_writes(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    placement_path = candidate_root / "core-03.inline-placement.json"
    placement = json.loads(placement_path.read_text(encoding="utf-8"))
    placement["placements"][0]["translated_text"] = "错误文本"
    _write_json(placement_path, placement)
    _refresh_evidence_hash(
        candidate_root,
        "placement_sha256",
        "core-03.inline-placement.json",
    )

    with pytest.raises(ValueError, match="placement evidence mismatch"):
        evaluate_workspace(workspace, candidate_root)

    assert not (workspace / "comparisons").exists()
    assert not (workspace / "reports").exists()


def test_malformed_baseline_preserves_existing_artifacts(tmp_path: Path) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    old_comparison = workspace / "comparisons/old.png"
    old_report = workspace / "reports/benchmark-report.json"
    old_comparison.parent.mkdir()
    old_report.parent.mkdir()
    old_comparison.write_bytes(b"old comparison")
    old_report.write_bytes(b"old report")
    baseline = tmp_path / "baseline.json"
    _write_json(baseline, {"schema": "wrong"})

    with pytest.raises(ValueError, match="baseline report"):
        evaluate_workspace(workspace, candidate_root, baseline)

    assert old_comparison.read_bytes() == b"old comparison"
    assert old_report.read_bytes() == b"old report"
    assert not list(workspace.glob(".benchmark-*"))


def test_later_manifest_sample_failure_preserves_existing_artifacts(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    old_comparison = workspace / "comparisons/old.png"
    old_report = workspace / "reports/benchmark-report.json"
    old_comparison.parent.mkdir()
    old_report.parent.mkdir()
    old_comparison.write_bytes(b"old comparison")
    old_report.write_bytes(b"old report")
    lock_path = workspace / "manifest.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    later = dict(lock["samples"][0])
    later["sample_id"] = "core-04"
    later["category"] = "later_failure"
    lock["samples"].append(later)
    lock["sample_count"] = 2
    lock["core_sample_count"] = 2
    _write_json(lock_path, lock)

    with pytest.raises(ValueError, match="core-04"):
        evaluate_workspace(workspace, candidate_root)

    assert old_comparison.read_bytes() == b"old comparison"
    assert old_report.read_bytes() == b"old report"
    assert not list(workspace.glob(".benchmark-*"))


def test_adjudication_refuses_to_overwrite_existing_gold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    sample_dir = workspace / "samples/core-03"
    existing = sample_dir / "gold.locked.json"
    before = existing.read_bytes()
    decisions = tmp_path / "decisions.json"
    _write_json(decisions, {"decisions": [{"value": "different"}]})
    monkeypatch.setattr(
        engineering_cli,
        "apply_adjudication",
        lambda *_args: pytest.fail("existing gold must fail before adjudication"),
    )

    for _ in range(2):
        with pytest.raises(FileExistsError, match="gold artifact"):
            main(
                [
                    "benchmark-adjudicate",
                    "--workspace",
                    str(workspace),
                    "--sample-id",
                    "core-03",
                    "--decisions",
                    str(decisions),
                    "--decided-at",
                    "2026-07-28T10:00:00+08:00",
                    "--lock",
                ]
            )
        assert existing.read_bytes() == before


def test_adjudication_publishes_once_then_refuses_different_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    sample_dir = workspace / "samples/core-03"
    (sample_dir / "gold.locked.json").unlink()
    _write_json(sample_dir / "prelabel.json", {"placeholder": True})
    decisions = tmp_path / "decisions.json"
    _write_json(decisions, {"decisions": [{"value": "first"}]})
    fake_gold = SimpleNamespace(
        status="adjudicated",
        to_dict=lambda: {"schema": "test", "value": "first"},
    )
    monkeypatch.setattr(
        engineering_cli, "apply_adjudication", lambda *_args: fake_gold
    )

    assert (
        main(
            [
                "benchmark-adjudicate",
                "--workspace",
                str(workspace),
                "--sample-id",
                "core-03",
                "--decisions",
                str(decisions),
                "--decided-at",
                "2026-07-28T10:00:00+08:00",
            ]
        )
        == 0
    )
    output = sample_dir / "gold.adjudicated.json"
    before = output.read_bytes()
    _write_json(decisions, {"decisions": [{"value": "different"}]})

    with pytest.raises(FileExistsError, match="gold artifact"):
        main(
            [
                "benchmark-adjudicate",
                "--workspace",
                str(workspace),
                "--sample-id",
                "core-03",
                "--decisions",
                str(decisions),
                "--decided-at",
                "2026-07-28T11:00:00+08:00",
            ]
        )
    assert output.read_bytes() == before


def test_prelabel_preflight_blocks_provider_on_tampered_sample_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    sample_json = workspace / "samples/core-03/sample.json"
    payload = json.loads(sample_json.read_text(encoding="utf-8"))
    payload["category"] = "tampered"
    _write_json(sample_json, payload)
    regions = tmp_path / "regions.json"
    _write_json(regions, {"regions": []})
    monkeypatch.setattr(
        engineering_cli,
        "get_api_key",
        lambda: pytest.fail("provider access must follow lifecycle preflight"),
    )

    with pytest.raises(ValueError, match="sample metadata"):
        main(
            [
                "benchmark-prelabel",
                "--workspace",
                str(workspace),
                "--sample-id",
                "core-03",
                "--regions-json",
                str(regions),
            ]
        )


def test_prelabel_refuses_existing_gold_before_provider_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    regions = tmp_path / "regions.json"
    _write_json(regions, {"regions": []})
    monkeypatch.setattr(
        engineering_cli,
        "get_api_key",
        lambda: pytest.fail("provider access must follow gold-state preflight"),
    )

    with pytest.raises(FileExistsError, match="gold artifact"):
        main(
            [
                "benchmark-prelabel",
                "--workspace",
                str(workspace),
                "--sample-id",
                "core-03",
                "--regions-json",
                str(regions),
            ]
        )


def test_visual_review_requires_locked_gold_before_provider_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    (workspace / "samples/core-03/gold.locked.json").unlink()
    (candidate_root / "core-03.subjective.json").unlink()
    (candidate_root / "core-03.evidence.json").unlink()
    monkeypatch.setattr(
        engineering_cli,
        "get_api_key",
        lambda: pytest.fail("provider access must follow locked-gold preflight"),
    )

    with pytest.raises(ValueError, match="requires locked gold"):
        main(
            [
                "benchmark-visual-review",
                "--workspace",
                str(workspace),
                "--candidate-root",
                str(candidate_root),
                "--sample-id",
                "core-03",
            ]
        )


def test_visual_review_publishes_hash_bound_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    (candidate_root / "core-03.subjective.json").unlink()
    (candidate_root / "core-03.evidence.json").unlink()
    review = {
        "schema": "engineering-drawing-visual-review-v1",
        "prompt_version": "2026-07-benchmark-visual-v1",
        "sample_id": "core-03",
        "model": "gpt-5.6-sol",
        "layout_association": 20,
        "page_readability": 15,
        "findings": [],
    }
    monkeypatch.setattr(engineering_cli, "get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        engineering_cli, "request_visual_review", lambda **_kwargs: review
    )

    assert (
        main(
            [
                "benchmark-visual-review",
                "--workspace",
                str(workspace),
                "--candidate-root",
                str(candidate_root),
                "--sample-id",
                "core-03",
            ]
        )
        == 0
    )
    subjective = candidate_root / "core-03.subjective.json"
    evidence = json.loads(
        (candidate_root / "core-03.evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["candidate_sha256"] == hashlib.sha256(
        (candidate_root / "core-03.pdf").read_bytes()
    ).hexdigest()
    assert evidence["subjective_sha256"] == hashlib.sha256(
        subjective.read_bytes()
    ).hexdigest()


def test_pair_publish_rolls_back_and_cleans_temps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    real_link = engineering_cli.os.link
    calls = 0

    def fail_second_link(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated publish failure")
        real_link(source, target)

    monkeypatch.setattr(engineering_cli.os, "link", fail_second_link)

    with pytest.raises(OSError, match="simulated"):
        engineering_cli._publish_json_exclusive(
            [(first, {"value": 1}), (second, {"value": 2})]
        )

    assert not first.exists()
    assert not second.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_evaluation_publish_failure_restores_both_artifact_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.engineering_drawing.benchmark import runner

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    old_comparison = workspace / "comparisons/old.png"
    old_report = workspace / "reports/benchmark-report.json"
    old_comparison.parent.mkdir()
    old_report.parent.mkdir()
    old_comparison.write_bytes(b"old comparison")
    old_report.write_bytes(b"old report")
    real_replace = runner.os.replace

    def fail_reports_publish(source: Path, target: Path) -> None:
        if source.name == "reports" and target == workspace / "reports":
            raise OSError("simulated reports publish failure")
        real_replace(source, target)

    monkeypatch.setattr(runner.os, "replace", fail_reports_publish)

    with pytest.raises(OSError, match="simulated"):
        runner.evaluate_workspace(workspace, candidate_root)

    assert old_comparison.read_bytes() == b"old comparison"
    assert old_report.read_bytes() == b"old report"
    assert not list(workspace.glob(".benchmark-*"))
