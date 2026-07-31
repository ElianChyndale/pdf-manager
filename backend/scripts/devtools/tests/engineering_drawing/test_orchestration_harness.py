import pytest

from services.engineering_drawing.orchestration_harness import (
    canonical_policy_fingerprint,
    canonicalize_document_context,
    new_run_identity,
    validate_handoff,
)


DIGEST = "a" * 64


def _stage(name: str) -> dict:
    return {
        **new_run_identity(run_id="sample-06", source_sha256=DIGEST),
        "stage": name,
        "expected_source_ids": ["line-1", "line-2"],
        "literal_only_ids": ["line-2"],
        "blocks": [{"block_id": "b1", "source_ids": ["line-1"], "zone": "company_contact_panel", "status": "translated", "render_mode": "opaque_bilingual_reflow"}],
    }


def test_handoff_preserves_identity_closure_and_render_mode() -> None:
    plan = validate_handoff(_stage("supervisor_plan"))
    ledger = _stage("extraction_ledger")
    assert validate_handoff(ledger, previous=plan)["stage"] == "extraction_ledger"


def test_handoff_rejects_policy_or_mode_weakening() -> None:
    plan = validate_handoff(_stage("supervisor_plan"))
    ledger = _stage("extraction_ledger")
    ledger["blocks"][0]["render_mode"] = "preserve_source_blue_chinese"
    with pytest.raises(ValueError, match="render-mode"):
        validate_handoff(ledger, previous=plan)
    ledger = _stage("extraction_ledger")
    ledger["policy_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="fingerprint"):
        validate_handoff(ledger, previous=plan)


def test_release_requires_all_closures_review_and_no_hard_findings() -> None:
    candidate = _stage("rendered_candidate")
    candidate.update({"whole_page_closure": 1.0, "ink_closure": 1.0, "zone_closure": {"company_contact_panel": 1.0}, "hard_findings": []})
    validate_handoff(candidate)
    release = _stage("release_authorization")
    release.update(candidate)
    release["stage"] = "release_authorization"
    release.update({"render_review_passed": True, "authorization": "release", "candidate_sha256": "b" * 64, "review_evidence_sha256": "c" * 64, "release_separate_from_renderer": True})
    assert validate_handoff(release, previous=candidate)["authorization"] == "release"
    release["hard_findings"] = ["mixed_render_mode"]
    with pytest.raises(ValueError, match="hard findings"):
        validate_handoff(release, previous=candidate)


def test_renderer_cannot_self_authorize_release() -> None:
    release = _stage("release_authorization")
    release.update({"whole_page_closure": 1.0, "ink_closure": 1.0, "zone_closure": {"drawing_body": 1.0}, "hard_findings": [], "render_review_passed": True, "authorization": "release", "candidate_sha256": "b" * 64, "review_evidence_sha256": "c" * 64, "release_separate_from_renderer": False})
    with pytest.raises(ValueError, match="self-authorize"):
        validate_handoff(release)


def test_document_context_is_part_of_run_identity() -> None:
    ctx = {"project_name": "Masjid Tok Muda", "drawing_discipline": "electrical", "units": "metric"}
    identity = new_run_identity(run_id="sample-06", source_sha256=DIGEST, document_context=ctx)
    assert identity["document_context"] == canonicalize_document_context(ctx)
    assert "document_context" not in new_run_identity(run_id="sample-06", source_sha256=DIGEST)


def test_handoff_rejects_document_context_drift() -> None:
    base = _stage("supervisor_plan")
    base["document_context"] = canonicalize_document_context({"units": "metric"})
    validate_handoff(base)
    next_stage = _stage("extraction_ledger")
    next_stage["document_context"] = canonicalize_document_context({"units": "imperial"})
    with pytest.raises(ValueError, match="identity"):
        validate_handoff(next_stage, previous=base)


def test_handoff_accepts_identical_document_context() -> None:
    base = _stage("supervisor_plan")
    base["document_context"] = canonicalize_document_context({"units": "metric"})
    validate_handoff(base)
    next_stage = _stage("extraction_ledger")
    next_stage["document_context"] = canonicalize_document_context({"units": "metric"})
    assert validate_handoff(next_stage, previous=base)["stage"] == "extraction_ledger"


def test_document_context_does_not_change_policy_fingerprint() -> None:
    fingerprint = canonical_policy_fingerprint()
    identity = new_run_identity(run_id="sample-06", source_sha256=DIGEST, document_context={"units": "metric"})
    assert identity["policy_fingerprint"] == fingerprint
    assert identity["document_context"] != fingerprint
