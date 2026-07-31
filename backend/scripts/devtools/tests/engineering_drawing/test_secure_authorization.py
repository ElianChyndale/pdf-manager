from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import fitz
import pytest

from services.engineering_drawing.authorization import (
    authorize_release,
    authorize_render,
)
from services.engineering_drawing.placement_scoring import score_candidates
from services.engineering_drawing.supervisor_bundle import create_supervisor_run_bundle, verify_supervisor_run_bundle
from services.engineering_drawing.workflow_policy import (
    DEFAULT_MULTIMODAL_MODEL,
    DEFAULT_SUPERVISOR_ADAPTER,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((10, 20), "ROOF", fontsize=8)
    document.save(path)
    document.close()
    return path


def _bundle(tmp_path: Path) -> tuple[Path, Path, dict]:
    source = _source(tmp_path / "source.pdf")
    bundle = tmp_path / "run"
    images = bundle / "page-images"
    images.mkdir(parents=True)
    with fitz.open(source) as document:
        document[0].get_pixmap(alpha=False).save(images / "page-0001.png")
    request = {"model": "gpt-5.6-sol", "reasoning_profile": "light", "images": ["page-images/page-0001.png"]}
    response = {"schema": "engineering-drawing-multimodal-plan-v3", "status": "approved"}
    plan = {
        **response,
        "planning_authority": "real_multimodal_supervisor",
        "model_name": "gpt-5.6-sol",
        "reasoning_profile": "light",
    }
    _write_json(bundle / "request.json", request)
    _write_json(bundle / "model-response.raw.json", response)
    _write_json(bundle / "normalized-plan.json", plan)
    source_manifest = {
        "source_pdf": str(source.resolve()),
        "source_sha256": _sha(source),
        "page_count": 1,
        "page_sizes": [[200.0, 120.0]],
        "page_images": [{"page_index": 0, "path": "page-images/page-0001.png", "sha256": _sha(images / "page-0001.png")}],
    }
    _write_json(bundle / "source-manifest.json", source_manifest)
    receipt = {
        "invocation_id": "run-1",
        "agent_id": "/root/sol-supervisor",
        "mode": "codex_agent_multimodal",
        "model": "gpt-5.6-sol",
        "reasoning_profile": "light",
        "started_at": "2026-07-30T00:00:00+00:00",
        "completed_at": "2026-07-30T00:00:01+00:00",
        "request_sha256": _sha(bundle / "request.json"),
        "response_sha256": _sha(bundle / "model-response.raw.json"),
        "plan_sha256": _sha(bundle / "normalized-plan.json"),
        "source_manifest_sha256": _sha(bundle / "source-manifest.json"),
    }
    _write_json(bundle / "invocation-receipt.json", receipt)
    _write_json(bundle / "hashes.json", {name: _sha(bundle / name) for name in (
        "request.json", "model-response.raw.json", "normalized-plan.json",
        "source-manifest.json", "invocation-receipt.json",
    )})
    return source, bundle, plan


def test_default_supervisor_is_codex_sol_light() -> None:
    assert DEFAULT_MULTIMODAL_MODEL == "gpt-5.6-sol"
    assert DEFAULT_SUPERVISOR_ADAPTER["alias"] == "codex-sol-light"
    assert DEFAULT_SUPERVISOR_ADAPTER["reasoning_profile"] == "light"


def test_supervisor_bundle_recomputes_hashes_and_rejects_tampering(tmp_path: Path) -> None:
    source, bundle, _ = _bundle(tmp_path)
    verified = verify_supervisor_run_bundle(bundle, source_pdf_path=source)
    assert verified["invocation_id"] == "run-1"
    (bundle / "model-response.raw.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="response_sha256"):
        verify_supervisor_run_bundle(bundle, source_pdf_path=source)


def test_create_bundle_freezes_sol_light_request_response_plan_and_page_images(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.pdf")
    image = tmp_path / "page.png"
    with fitz.open(source) as document:
        document[0].get_pixmap(alpha=False).save(image)
    plan = {"schema": "engineering-drawing-multimodal-plan-v3", "status": "approved"}
    bundle = create_supervisor_run_bundle(
        bundle_dir=tmp_path / "created-run",
        source_pdf_path=source,
        page_images=[image],
        request={"task": "inspect and plan"},
        raw_response={"output": plan},
        normalized_plan=plan,
        invocation_id="created-1",
        agent_id="/root/sol-supervisor",
        started_at="2026-07-30T00:00:00+00:00",
        completed_at="2026-07-30T00:00:02+00:00",
    )
    verified = verify_supervisor_run_bundle(bundle, source_pdf_path=source)
    assert verified["model"] == "gpt-5.6-sol"


def test_dynamic_scores_are_recomputed_and_select_highest_legal_candidate() -> None:
    candidates = [
        {"candidate_id": "near-overlap", "bbox": [10, 10, 50, 25], "features": {
            "source_overlap_ratio": 0.30, "distance_pt": 2, "protected_object_overlap_ratio": 0,
            "translation_overlap_ratio": 0, "engineering_ink_ratio": 0.01,
            "semantic_association": 1, "whitespace_utilization": 0.8, "font_fit": 0.9,
        }},
        {"candidate_id": "clear", "bbox": [55, 10, 95, 25], "features": {
            "source_overlap_ratio": 0, "distance_pt": 20, "protected_object_overlap_ratio": 0,
            "translation_overlap_ratio": 0, "engineering_ink_ratio": 0.02,
            "semantic_association": 0.9, "whitespace_utilization": 0.8, "font_fit": 0.9,
        }},
    ]
    audit = score_candidates("drawing_body", candidates, search_radius_pt=24)
    assert next(item for item in audit if item["selected"])["candidate_id"] == "clear"
    assert all(item["total_score"] == pytest.approx(sum(item["contributions"].values())) for item in audit)


def test_dynamic_scores_reject_weight_and_hard_constraint_bypasses() -> None:
    candidate = {"candidate_id": "bad", "bbox": [10, 10, 30, 20], "features": {
        "source_overlap_ratio": 0, "distance_pt": 5, "protected_object_overlap_ratio": 0.1,
        "translation_overlap_ratio": 0, "engineering_ink_ratio": 0,
        "semantic_association": 1, "whitespace_utilization": 1, "font_fit": 1,
    }}
    audit = score_candidates("drawing_body", [candidate], search_radius_pt=24)
    assert audit[0]["legal"] is False
    with pytest.raises(ValueError, match="source_overlap weight"):
        score_candidates("drawing_body", [candidate], search_radius_pt=24, weights={
            "source_overlap": 0.05, "distance": 0.40, "engineering_ink": 0.05,
            "semantic_association": 0.20, "whitespace": 0.15, "font_fit": 0.15,
        })


def test_render_and_release_authorization_bind_exact_artifacts(tmp_path: Path) -> None:
    source, bundle, plan = _bundle(tmp_path)
    render_auth = authorize_render(bundle_dir=bundle, source_pdf_path=source, plan=plan)
    candidate = tmp_path / "candidate.pdf"
    candidate.write_bytes(source.read_bytes())
    review = {
        "same_supervisor": True,
        "invocation_id": "run-1",
        "candidate_sha256": _sha(candidate),
        "plan_sha256": _sha(bundle / "normalized-plan.json"),
        "status": "accepted",
        "questions": {"chinese_understandable": True, "association_clear": True, "no_omission_or_damage": True},
        "findings": [],
    }
    release_auth = authorize_release(
        render_authorization=render_auth,
        candidate_pdf_path=candidate,
        review=review,
        deterministic_visual_qa={"passed": True, "manual_review_count": 0},
    )
    assert release_auth["candidate_sha256"] == _sha(candidate)
    candidate.write_bytes(b"changed")
    with pytest.raises(ValueError, match="candidate_sha256"):
        authorize_release(
            render_authorization=render_auth,
            candidate_pdf_path=candidate,
            review=review,
            deterministic_visual_qa={"passed": True, "manual_review_count": 0},
        )
