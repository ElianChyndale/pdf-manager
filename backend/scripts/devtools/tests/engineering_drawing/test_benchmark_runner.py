from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

import services.engineering_drawing.cli as engineering_cli
from services.engineering_drawing.benchmark.runner import canonical_digest
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


def _candidate_page(
    path: Path,
    *,
    include_translation: bool = True,
    translation_point: tuple[float, float] = (125, 25),
    render_mode: int = 0,
    opacity: float = 1.0,
    color: tuple[float, float, float] = (0, 0, 0),
    overpaint: bool = False,
    overpaint_with_glyph_dots: bool = False,
    overpaint_with_white_image_and_glyph_dots: bool = False,
    rotation: int = 0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((20, 30), "ROOF SYSTEM")
    if include_translation:
        page.insert_text(
            translation_point,
            "屋面系统",
            fontname="china-s",
            fontsize=5,
            render_mode=render_mode,
            fill_opacity=opacity,
            color=color,
        )
        traced_glyphs = [
            fitz.Rect(raw[3])
            for span in page.get_texttrace()
            for raw in span.get("chars", ())
            if len(raw) >= 4 and chr(raw[0]) in "屋面系统"
        ]
        if (
            overpaint
            or overpaint_with_glyph_dots
            or overpaint_with_white_image_and_glyph_dots
        ):
            if overpaint_with_white_image_and_glyph_dots:
                white = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 140, 100), 0)
                white.clear_with(255)
                page.insert_image(
                    fitz.Rect(120, 10, 155, 35),
                    pixmap=white,
                    overlay=True,
                )
            else:
                page.draw_rect(
                    fitz.Rect(120, 10, 155, 35),
                    color=(1, 1, 1),
                    fill=(1, 1, 1),
                    overlay=True,
                )
            if overpaint_with_glyph_dots:
                for glyph in traced_glyphs:
                    page.draw_circle(
                        ((glyph.x0 + glyph.x1) / 2, (glyph.y0 + glyph.y1) / 2),
                        0.275,
                        color=(0, 0, 0),
                        fill=(0, 0, 0),
                        overlay=True,
                    )
            elif overpaint_with_white_image_and_glyph_dots:
                for glyph in traced_glyphs:
                    for x_fraction, y_fraction in (
                        (0.2, 0.25),
                        (0.5, 0.75),
                        (0.8, 0.4),
                    ):
                        page.draw_circle(
                            (
                                glyph.x0 + glyph.width * x_fraction,
                                glyph.y0 + glyph.height * y_fraction,
                            ),
                            0.175,
                            color=(0, 0, 0),
                            fill=(0, 0, 0),
                            overlay=True,
                        )
            else:
                page.draw_circle(
                    (205, 20),
                    2,
                    color=(0, 0, 0),
                    fill=(0, 0, 0),
                    overlay=True,
                )
    page.set_rotation(rotation)
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
            "benchmark_version": "test-v1",
            "manifest_record_sha256": canonical_digest(record),
            "source_sha256": source_sha256,
            "preview_sha256": record["preview_sha256"],
            "locked_gold_sha256": hashlib.sha256(
                (sample_dir / "gold.locked.json").read_bytes()
            ).hexdigest(),
            "candidate_sha256": hashlib.sha256(
                (candidate_root / "core-03.pdf").read_bytes()
            ).hexdigest(),
            "candidate_page": {
                "width": 300.0,
                "height": 200.0,
                "rotation": 0,
                "mediabox": [0.0, 0.0, 300.0, 200.0],
                "cropbox": [0.0, 0.0, 300.0, 200.0],
            },
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


def test_benchmark_seed_cli_rejects_invalid_manifest_before_seed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = CoreManifest(
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
    challenge_path = tmp_path / "challenge.json"
    _write_json(
        challenge_path,
        {
            "schema": "engineering-drawing-challenge-set-v1",
            "benchmark_version": "challenge-v1",
            "samples": [
                {
                    "sample_id": "challenge-01",
                    "category": "detail",
                    "relative_pdf": r"\\?\C:\escape.pdf",
                    "page_number": 1,
                    "goals": ["semantic_block"],
                }
            ],
        },
    )
    monkeypatch.setattr(engineering_cli, "load_core_manifest", lambda _path: core)
    monkeypatch.setattr(
        engineering_cli,
        "seed_workspace",
        lambda *_args, **_kwargs: pytest.fail(
            "invalid manifest must be rejected before seed writes"
        ),
    )
    workspace = tmp_path / "benchmark"

    with pytest.raises(ValueError, match="relative_pdf"):
        main(
            [
                "benchmark-seed",
                "--source-root",
                str(tmp_path / "source"),
                "--workspace",
                str(workspace),
                "--challenge-manifest",
                str(challenge_path),
            ]
        )

    assert not workspace.exists()


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


def test_evaluate_rejects_changed_preview_with_same_candidate_sidecars(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    preview = workspace / "samples/core-03/source.png"
    preview.write_bytes(preview.read_bytes() + b"stale")

    with pytest.raises(ValueError, match="preview hash"):
        evaluate_workspace(workspace, candidate_root)


def test_evaluate_rejects_changed_locked_gold_with_same_evidence(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    gold_path = workspace / "samples/core-03/gold.locked.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    gold["blocks"][0]["manual_review_required"] = True
    _write_json(gold_path, gold)

    with pytest.raises(ValueError, match="evidence hash mismatch"):
        evaluate_workspace(workspace, candidate_root)


def test_evaluate_rejects_changed_manifest_record_with_same_evidence(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    lock_path = workspace / "manifest.lock.json"
    sample_path = workspace / "samples/core-03/sample.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["samples"][0]["category"] = "changed_category"
    _write_json(lock_path, lock)
    _write_json(sample_path, lock["samples"][0])

    with pytest.raises(ValueError, match="evidence hash mismatch"):
        evaluate_workspace(workspace, candidate_root)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("relative_pdf", "../escape.pdf", "relative_pdf"),
        ("relative_pdf", "C:/escape.pdf", "relative_pdf"),
        ("relative_pdf", r"C:\escape.pdf", "relative_pdf"),
        ("relative_pdf", r"\\server\share\escape.pdf", "relative_pdf"),
        ("relative_pdf", r"\\?\C:\escape.pdf", "relative_pdf"),
        ("relative_pdf", r"\\.\NUL.pdf", "relative_pdf"),
        ("page_number", 2, "metadata"),
        ("page_size", [True, 200], "page_size"),
        ("page_size", [float("nan"), 200], "page_size"),
        ("page_rotation", True, "page_rotation"),
        ("goals", [""], "goals"),
        ("goals", ["semantic_block", "semantic_block"], "goals"),
        ("goals", ["unknown_goal"], "goals"),
        ("goals", ["x" * 129], "goals"),
    ],
)
def test_manifest_rejects_invalid_closed_metadata(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    lock_path = workspace / "manifest.lock.json"
    sample_path = workspace / "samples/core-03/sample.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["samples"][0][field] = value
    _write_json(lock_path, lock)
    _write_json(sample_path, lock["samples"][0])

    with pytest.raises(ValueError, match=message):
        evaluate_workspace(workspace, candidate_root)


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


def test_byte_identical_source_pdf_cannot_satisfy_translation_evidence(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    candidate = candidate_root / "core-03.pdf"
    candidate.write_bytes(
        (workspace / "samples/core-03/source.pdf").read_bytes()
    )
    _refresh_evidence_hash(
        candidate_root, "candidate_sha256", "core-03.pdf"
    )

    result = evaluate_workspace(workspace, candidate_root)

    assert result["core_score"] < 100
    assert "untranslated_candidate" in result["samples"][0]["hard_failure_ids"]


@pytest.mark.parametrize(
    "candidate_options",
    [
        {"render_mode": 3},
        {"opacity": 0.0},
        {"color": (1, 1, 1)},
        {"overpaint": True},
        {"translation_point": (225, 125)},
    ],
)
def test_invisible_or_off_location_translation_is_a_hard_failure(
    tmp_path: Path, candidate_options: dict
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    candidate = candidate_root / "core-03.pdf"
    candidate.unlink()
    _candidate_page(candidate, **candidate_options)
    _refresh_evidence_hash(
        candidate_root, "candidate_sha256", "core-03.pdf"
    )

    result = evaluate_workspace(workspace, candidate_root)

    assert result["core_score"] < 100
    assert "untranslated_candidate" in result["samples"][0]["hard_failure_ids"]


def test_overpainted_translation_with_dot_in_every_glyph_bbox_is_hard_failure(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    candidate = candidate_root / "core-03.pdf"
    candidate.unlink()
    _candidate_page(candidate, overpaint_with_glyph_dots=True)
    _refresh_evidence_hash(candidate_root, "candidate_sha256", "core-03.pdf")

    result = evaluate_workspace(workspace, candidate_root)

    assert result["core_score"] < 100
    assert "untranslated_candidate" in result["samples"][0]["hard_failure_ids"]


def test_white_image_overpaint_with_sparse_glyph_dots_is_hard_failure(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    candidate = candidate_root / "core-03.pdf"
    candidate.unlink()
    _candidate_page(
        candidate,
        overpaint_with_white_image_and_glyph_dots=True,
    )
    _refresh_evidence_hash(candidate_root, "candidate_sha256", "core-03.pdf")

    result = evaluate_workspace(workspace, candidate_root)

    assert result["core_score"] < 100
    assert "untranslated_candidate" in result["samples"][0]["hard_failure_ids"]


def test_evaluate_rejects_180_degree_candidate_identity_before_writes(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    candidate = candidate_root / "core-03.pdf"
    candidate.unlink()
    _candidate_page(candidate, rotation=180)
    _refresh_evidence_hash(candidate_root, "candidate_sha256", "core-03.pdf")

    with pytest.raises(ValueError, match="candidate page.*rotation"):
        evaluate_workspace(workspace, candidate_root)

    assert not (workspace / "comparisons").exists()
    assert not (workspace / "reports").exists()


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


def _configure_drawn_leader(
    workspace: Path,
    candidate_root: Path,
    path: list[list[float]],
) -> None:
    gold_path = workspace / "samples/core-03/gold.locked.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    gold["blocks"][0]["forbidden_zones"].append([105, 0, 115, 40])
    gold["blocks"][0]["leader"]["allowed"] = True
    _write_json(gold_path, gold)
    regions_path = candidate_root / "core-03.regions.json"
    regions = json.loads(regions_path.read_text(encoding="utf-8"))
    regions["regions"][0]["leader"] = {
        "status": "drawn",
        "color": "dark_blue",
        "width_points": 0.32,
        "route": "orthogonal",
        "arrow": False,
    }
    _write_json(regions_path, regions)
    placement_path = candidate_root / "core-03.inline-placement.json"
    placement = json.loads(placement_path.read_text(encoding="utf-8"))
    placement["placements"][0]["leader"] = {"status": "drawn", "path": path}
    _write_json(placement_path, placement)
    _refresh_evidence_hash(
        candidate_root, "regions_sha256", "core-03.regions.json"
    )
    _refresh_evidence_hash(
        candidate_root,
        "placement_sha256",
        "core-03.inline-placement.json",
    )
    _refresh_evidence_hash(
        candidate_root,
        "locked_gold_sha256",
        str(gold_path),
    )


def test_leader_crossing_gold_obstacle_hard_fails(tmp_path: Path) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    _configure_drawn_leader(
        workspace,
        candidate_root,
        [[100, 25], [120, 25], [120, 20]],
    )

    result = evaluate_workspace(workspace, candidate_root)

    assert "leader_collision" in result["samples"][0]["hard_failure_ids"]


def test_clean_orthogonal_leader_route_passes(tmp_path: Path) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    _configure_drawn_leader(
        workspace,
        candidate_root,
        [[90, 35], [90, 50], [130, 50], [130, 30]],
    )

    result = evaluate_workspace(workspace, candidate_root)

    assert "leader_collision" not in result["samples"][0]["hard_failure_ids"]


def test_leader_that_exits_and_reenters_own_target_is_collision(
    tmp_path: Path,
) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    _configure_drawn_leader(
        workspace,
        candidate_root,
        [[100, 25], [130, 25], [130, 50], [150, 50], [150, 20]],
    )

    result = evaluate_workspace(workspace, candidate_root)

    assert "leader_collision" in result["samples"][0]["hard_failure_ids"]


def test_malformed_diagonal_leader_path_is_rejected(tmp_path: Path) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    _configure_drawn_leader(
        workspace,
        candidate_root,
        [[100, 25], [130, 20]],
    )

    with pytest.raises(ValueError, match="orthogonal"):
        evaluate_workspace(workspace, candidate_root)


def test_leader_crossing_other_candidate_target_is_collision(tmp_path: Path) -> None:
    from services.engineering_drawing.benchmark.runner import _candidate_visual_qa

    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((20, 30), "ROOF SYSTEM")
    page.insert_text((20, 70), "SECOND")
    document.save(source)
    document.close()
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((20, 30), "ROOF SYSTEM")
    page.insert_text((20, 70), "SECOND")
    page.insert_text((125, 25), "屋面系统", fontname="china-s", fontsize=5)
    page.insert_text((106, 28), "第二", fontname="china-s", fontsize=5)
    document.save(candidate)
    document.close()
    gold = [
        {**_gold()["blocks"][0], "leader": {**_gold()["blocks"][0]["leader"], "allowed": True}},
        {
            **_gold()["blocks"][0],
            "block_id": "core-03-b002",
            "source_text": "SECOND",
            "source_bbox": [20, 58, 100, 75],
            "gold_translation": "第二",
            "allowed_regions": [[105, 20, 115, 30]],
            "forbidden_zones": [[20, 58, 100, 75]],
        },
    ]
    regions = [
        {
            **_candidate_region(),
            "leader": {
                "status": "drawn", "color": "dark_blue", "width_points": 0.32,
                "route": "orthogonal", "arrow": False,
            },
        },
        {
            **_candidate_region(),
            "block_id": "core-03-b002",
            "translated_text": "第二",
            "target_bbox": [105, 20, 115, 30],
        },
    ]
    placements = [
        {
            "region_id": "core-03-b001", "page_index": 0,
            "source_bbox": [20, 18, 100, 35], "target_bbox": [120, 10, 180, 30],
            "translated_text": "屋面系统", "status": "inline_near",
            "coverage_status": "translated",
            "leader": {"status": "drawn", "path": [[100, 25], [120, 25]]},
        },
        {
            "region_id": "core-03-b002", "page_index": 0,
            "source_bbox": [20, 58, 100, 75], "target_bbox": [105, 20, 115, 30],
            "translated_text": "第二", "status": "inline_near",
            "coverage_status": "translated",
            "leader": {"status": "not_needed", "path": []},
        },
    ]

    result = _candidate_visual_qa(
        candidate_pdf=candidate,
        source_pdf=source,
        gold_blocks=gold,
        candidate_regions=regions,
        placements=placements,
    )

    assert result["leader_collision_count"] == 1


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


def test_generated_report_round_trips_as_next_baseline(tmp_path: Path) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    evaluate_workspace(workspace, candidate_root)
    baseline = workspace / "reports/benchmark-report.json"

    result = evaluate_workspace(workspace, candidate_root, baseline)

    assert result["promotion"]["promote"] is False
    assert result["promotion"]["reasons"] == ["insufficient_core_gain"]


def test_baseline_sample_universe_mismatch_is_rejected(tmp_path: Path) -> None:
    from services.engineering_drawing.benchmark.runner import evaluate_workspace

    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    evaluate_workspace(workspace, candidate_root)
    baseline = workspace / "reports/benchmark-report.json"
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    payload["samples"][0]["category"] = "other_category"
    payload["category_scores"] = {"other_category": payload["core_score"]}
    _write_json(baseline, payload)

    with pytest.raises(ValueError, match="manifest universe"):
        evaluate_workspace(workspace, candidate_root, baseline)


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


def test_adjudication_rejects_prelabel_for_different_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    sample_dir = workspace / "samples/core-03"
    (sample_dir / "gold.locked.json").unlink()
    record = json.loads(
        (sample_dir / "sample.json").read_text(encoding="utf-8")
    )
    page = {"width": 300, "height": 200, "rotation": 0}
    _write_json(
        sample_dir / "prelabel.json",
        {"sample_id": "core-04", "page": page},
    )
    _write_json(
        sample_dir / "prelabel.evidence.json",
        {
            "schema": "engineering-drawing-prelabel-evidence-v1",
            "sample_id": "core-03",
            "benchmark_version": "test-v1",
            "manifest_record_sha256": canonical_digest(record),
            "source_sha256": record["source_sha256"],
            "preview_sha256": record["preview_sha256"],
            "regions_sha256": "a" * 64,
            "prelabel_sha256": hashlib.sha256(
                (sample_dir / "prelabel.json").read_bytes()
            ).hexdigest(),
            "page": page,
        },
    )
    decisions = tmp_path / "decisions.json"
    _write_json(decisions, {"decisions": []})
    monkeypatch.setattr(
        engineering_cli,
        "apply_adjudication",
        lambda *_args: pytest.fail("identity mismatch must precede adjudication"),
    )

    with pytest.raises(ValueError, match="identity"):
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
    assert not list(sample_dir.glob("gold.*.json"))


@pytest.mark.parametrize(
    "page",
    [
        {"width": 600, "height": 400, "rotation": 0},
        {"width": 300, "height": 200, "rotation": 90},
    ],
)
def test_adjudication_rejects_wrong_prelabel_page_without_gold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, page: dict
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    sample_dir = workspace / "samples/core-03"
    (sample_dir / "gold.locked.json").unlink()
    record = json.loads((sample_dir / "sample.json").read_text(encoding="utf-8"))
    _write_json(sample_dir / "prelabel.json", {"sample_id": "core-03", "page": page})
    _write_json(
        sample_dir / "prelabel.evidence.json",
        {
            "schema": "engineering-drawing-prelabel-evidence-v1",
            "sample_id": "core-03",
            "benchmark_version": "test-v1",
            "manifest_record_sha256": canonical_digest(record),
            "source_sha256": record["source_sha256"],
            "preview_sha256": record["preview_sha256"],
            "regions_sha256": "a" * 64,
            "prelabel_sha256": hashlib.sha256(
                (sample_dir / "prelabel.json").read_bytes()
            ).hexdigest(),
            "page": page,
        },
    )
    decisions = tmp_path / "decisions.json"
    _write_json(decisions, {"decisions": []})
    monkeypatch.setattr(
        engineering_cli,
        "apply_adjudication",
        lambda *_args: pytest.fail("page mismatch must precede adjudication"),
    )

    with pytest.raises(ValueError, match="page"):
        main(
            [
                "benchmark-adjudicate",
                "--workspace", str(workspace),
                "--sample-id", "core-03",
                "--decisions", str(decisions),
                "--decided-at", "2026-07-28T10:00:00+08:00",
            ]
        )
    assert not list(sample_dir.glob("gold.*.json"))


def test_adjudication_publishes_once_then_refuses_different_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    sample_dir = workspace / "samples/core-03"
    (sample_dir / "gold.locked.json").unlink()
    record = json.loads(
        (sample_dir / "sample.json").read_text(encoding="utf-8")
    )
    page = {"width": 300, "height": 200, "rotation": 0}
    _write_json(
        sample_dir / "prelabel.json",
        {"sample_id": "core-03", "page": page},
    )
    _write_json(
        sample_dir / "prelabel.evidence.json",
        {
            "schema": "engineering-drawing-prelabel-evidence-v1",
            "sample_id": "core-03",
            "benchmark_version": "test-v1",
            "manifest_record_sha256": canonical_digest(record),
            "source_sha256": record["source_sha256"],
            "preview_sha256": record["preview_sha256"],
            "regions_sha256": "a" * 64,
            "prelabel_sha256": hashlib.sha256(
                (sample_dir / "prelabel.json").read_bytes()
            ).hexdigest(),
            "page": page,
        },
    )
    decisions = tmp_path / "decisions.json"
    _write_json(decisions, {"decisions": [{"value": "first"}]})
    fake_gold = SimpleNamespace(
        sample_id="core-03",
        status="adjudicated",
        to_dict=lambda: {"schema": "test", "value": "first", "page": page},
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


def test_adjudication_rejects_mismatched_final_gold_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    sample_dir = workspace / "samples/core-03"
    (sample_dir / "gold.locked.json").unlink()
    record = json.loads(
        (sample_dir / "sample.json").read_text(encoding="utf-8")
    )
    page = {"width": 300, "height": 200, "rotation": 0}
    _write_json(
        sample_dir / "prelabel.json",
        {"sample_id": "core-03", "page": page},
    )
    _write_json(
        sample_dir / "prelabel.evidence.json",
        {
            "schema": "engineering-drawing-prelabel-evidence-v1",
            "sample_id": "core-03",
            "benchmark_version": "test-v1",
            "manifest_record_sha256": canonical_digest(record),
            "source_sha256": record["source_sha256"],
            "preview_sha256": record["preview_sha256"],
            "regions_sha256": "a" * 64,
            "prelabel_sha256": hashlib.sha256(
                (sample_dir / "prelabel.json").read_bytes()
            ).hexdigest(),
            "page": page,
        },
    )
    decisions = tmp_path / "decisions.json"
    _write_json(decisions, {"decisions": []})
    monkeypatch.setattr(
        engineering_cli,
        "apply_adjudication",
        lambda *_args: SimpleNamespace(
            sample_id="core-04",
            status="adjudicated",
            to_dict=lambda: {"sample_id": "core-04"},
        ),
    )

    with pytest.raises(ValueError, match="gold identity"):
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
    assert not list(sample_dir.glob("gold.*.json"))


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


def test_visual_review_rejects_180_degree_candidate_before_provider_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "benchmark"
    candidate_root = tmp_path / "candidate"
    _seed_evaluation_tree(workspace, candidate_root)
    (candidate_root / "core-03.subjective.json").unlink()
    (candidate_root / "core-03.evidence.json").unlink()
    candidate = candidate_root / "core-03.pdf"
    candidate.unlink()
    _candidate_page(candidate, rotation=180)
    monkeypatch.setattr(
        engineering_cli,
        "get_api_key",
        lambda: pytest.fail("candidate identity must precede provider access"),
    )

    with pytest.raises(ValueError, match="candidate page.*rotation"):
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

    assert not (candidate_root / "core-03.subjective.json").exists()
    assert not (candidate_root / "core-03.evidence.json").exists()


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
    assert evidence["candidate_page"]["rotation"] == 0
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
