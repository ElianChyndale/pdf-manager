"""V4 orchestration enforcement: stages cannot be bypassed or self-authorized.

The five immutable stages must pass ``validate_handoff`` in order with one run
identity, render modes cannot change between stages, and the renderer can never
publish without a supervisor review or an explicit human acceptance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.engineering_drawing import run_v4
from services.engineering_drawing.orchestration_harness import new_run_identity, validate_handoff
from services.engineering_drawing.run_v4 import RendererOutcome, audit_formal_dir, run_v4_flow


def _stub_renderer(
    *,
    source_pdf: Path,
    output_pdf: Path,
    plan: dict,
    ocr_payload: dict | None,
    work_dir: Path,
    renderer_options: dict | None = None,
) -> RendererOutcome:
    import shutil

    shutil.copy2(source_pdf, output_pdf)
    audit = output_pdf.with_suffix(".inline-placement.json")
    audit.write_text(
        json.dumps(
            {
                "placements": [
                    {
                        "region_id": "b1",
                        "status": "inline_near",
                        "page_index": 0,
                        "font_size": 7.0,  # above the 5.8 body floor
                        "target_bbox": [10, 10, 40, 25],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return RendererOutcome(
        output_pdf_path=output_pdf,
        placement_audit_path=audit,
        planned_ids=["b1"],
        rendered_ids=["b1"],
        failed_block_ids=[],
    )


def _block(render_mode: str = "preserve_source_blue_chinese") -> list[dict]:
    return [
        {
            "block_id": "b1",
            "source_ids": ["s1"],
            "zone": "drawing_body",
            "status": "translated",
            "render_mode": render_mode,
        }
    ]


def test_handoff_rejects_stage_skip_and_reorder() -> None:
    base = new_run_identity(run_id="r1", source_sha256="a" * 64)
    blocks = _block()
    stage1 = {**base, "stage": "supervisor_plan", "blocks": blocks, "literal_only_ids": [], "expected_source_ids": ["s1"]}
    validate_handoff(stage1)
    stage3 = {**base, "stage": "render_contract", "blocks": blocks, "literal_only_ids": [], "expected_source_ids": ["s1"]}
    with pytest.raises(ValueError, match="skipped or reordered"):
        validate_handoff(stage3, previous=stage1)


def test_handoff_rejects_render_mode_change_between_stages() -> None:
    base = new_run_identity(run_id="r1", source_sha256="a" * 64)
    stage1 = {**base, "stage": "supervisor_plan", "blocks": _block("preserve_source_blue_chinese"), "literal_only_ids": [], "expected_source_ids": ["s1"]}
    changed = {**base, "stage": "extraction_ledger", "blocks": _block("opaque_bilingual_reflow"), "literal_only_ids": [], "expected_source_ids": ["s1"]}
    with pytest.raises(ValueError, match="render-mode decision"):
        validate_handoff(changed, previous=stage1)


def test_handoff_rejects_run_identity_drift() -> None:
    base = new_run_identity(run_id="r1", source_sha256="a" * 64)
    other = new_run_identity(run_id="r2", source_sha256="b" * 64)
    stage1 = {**base, "stage": "supervisor_plan", "blocks": _block(), "literal_only_ids": [], "expected_source_ids": ["s1"]}
    drifted = {**other, "stage": "extraction_ledger", "blocks": _block(), "literal_only_ids": [], "expected_source_ids": ["s1"]}
    with pytest.raises(ValueError, match="identity"):
        validate_handoff(drifted, previous=stage1)


def test_runner_refuses_to_publish_without_review_or_acceptance(
    tmp_path: Path, v4_source: Path, v4_plan: dict, v4_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(run_v4.RENDERERS, "stub", _stub_renderer)
    work = tmp_path / "work"
    candidate = tmp_path / "candidates"
    formal = tmp_path / "formal"
    result = run_v4_flow(
        source_pdf=v4_source,
        run_id="no-review-run",
        supervisor_bundle_dir=v4_bundle,
        normalized_plan=v4_plan,
        work_dir=work,
        candidate_dir=candidate,
        formal_dir=formal,
        renderer="stub",
    )
    assert result["published"] is False
    assert result["reason"] == "renderer_may_not_self_authorize"
    assert not list(formal.glob("*.pdf"))
    # A rendered candidate is legitimate; only publication is blocked.
    assert list(candidate.glob("*.pdf"))


def test_runner_refuses_when_bundle_does_not_bind_source_pdf(
    tmp_path: Path, v4_plan: dict, v4_bundle: Path
) -> None:
    from conftest import make_source_pdf

    other_source = make_source_pdf(tmp_path / "other.pdf")
    with pytest.raises(ValueError, match="does not match original PDF"):
        run_v4_flow(
            source_pdf=other_source,
            run_id="wrong-source",
            supervisor_bundle_dir=v4_bundle,
            normalized_plan=v4_plan,
            work_dir=tmp_path / "work",
            candidate_dir=tmp_path / "candidates",
            formal_dir=tmp_path / "formal",
            renderer="stub",
        )


def test_runner_human_acceptance_publishes_compliant_sidecar(
    tmp_path: Path, v4_source: Path, v4_plan: dict, v4_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(run_v4.RENDERERS, "stub", _stub_renderer)
    work = tmp_path / "work"
    candidate = tmp_path / "candidates"
    formal = tmp_path / "formal"
    result = run_v4_flow(
        source_pdf=v4_source,
        run_id="human-run",
        supervisor_bundle_dir=v4_bundle,
        normalized_plan=v4_plan,
        work_dir=work,
        candidate_dir=candidate,
        formal_dir=formal,
        renderer="stub",
        human_acceptance={"accepted_by": "user", "accepted_at": "2026-07-31T00:00:00Z"},
    )
    assert result["published"] is True
    assert result["authorization_kind"] == "human"
    reports = audit_formal_dir(formal)
    assert len(reports) == 1
    assert reports[0]["ok"] is True
    sidecar = list(formal.glob("*.release-authorization.json"))[0]
    auth = json.loads(sidecar.read_text(encoding="utf-8"))
    assert auth["schema"] == "engineering-drawing-human-release-authorization-v1"
    assert len(auth["candidate_sha256"]) == 64
    assert reports[0]["ok"] is True


def test_publish_to_formal_refuses_to_overwrite_a_different_pdf(tmp_path: Path) -> None:
    from services.engineering_drawing.run_v4 import publish_to_formal

    first = tmp_path / "first.pdf"
    first.write_bytes(b"first")
    formal = tmp_path / "formal"
    formal.mkdir()
    publish_to_formal(
        candidate=first,
        formal_dir=formal,
        auth={"schema": "engineering-drawing-human-release-authorization-v1", "candidate_sha256": "0" * 64},
    )
    second = tmp_path / "first.pdf"
    second.write_bytes(b"second-content")
    with pytest.raises(ValueError, match="overwrite a different PDF"):
        publish_to_formal(
            candidate=second,
            formal_dir=formal,
            auth={"schema": "engineering-drawing-human-release-authorization-v1", "candidate_sha256": "1" * 64},
        )
