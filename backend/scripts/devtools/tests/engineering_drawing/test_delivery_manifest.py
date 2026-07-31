"""Delivery manifest build/verify + audit-formal advisory warnings."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from services.engineering_drawing.delivery_manifest import (
    DELIVERY_MANIFEST_SCHEMA,
    build_delivery_manifest,
    verify_delivery_manifest,
    write_delivery_manifest,
)
from services.engineering_drawing.orchestration_harness import canonical_policy_fingerprint
from services.engineering_drawing.run_v4 import audit_formal_dir, publish_to_formal
from services.engineering_drawing.workflow_policy import WORKFLOW_VERSION


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _formal_with_pdf(tmp_path: Path, stem: str = "01_drawing") -> Path:
    formal = tmp_path / "formal"
    formal.mkdir(parents=True, exist_ok=True)
    pdf = formal / f"{stem}.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake drawing")
    return formal


def _build_payload(*, formal: Path, stem: str = "01_drawing", document_context=None) -> dict:
    pdf = formal / f"{stem}.pdf"
    # publish_to_formal writes a compliant sidecar we can hash.
    candidate = formal / "candidate.pdf"
    candidate.write_bytes(pdf.read_bytes())
    publish_to_formal(
        candidate=candidate,
        formal_dir=formal,
        auth={
            "schema": "engineering-drawing-human-release-authorization-v1",
            "workflow_version": WORKFLOW_VERSION,
            "authorization": "release",
            "authorization_kind": "human",
            "release_separate_from_renderer": True,
            "candidate_sha256": _sha(candidate),
            "accepted_by": "reviewer",
            "accepted_at": "2026-07-31T00:00:00Z",
        },
    )
    auth = json.loads((candidate.with_suffix(".release-authorization.json")).read_text(encoding="utf-8")) if (candidate.with_suffix(".release-authorization.json")).exists() else {}
    # publish_to_formal copies candidate -> formal/<candidate.name>, not the stem pdf.
    # Build the payload against the published PDF.
    published = formal / "candidate.pdf"
    return build_delivery_manifest(
        delivery_id=f"dlv-run-1-{stem}",
        run_id="run-1",
        workflow_version=WORKFLOW_VERSION,
        policy_fingerprint=canonical_policy_fingerprint(),
        supervisor={"model": "gpt-5.6-sol", "reasoning_profile": "light"},
        renderer="inline_plus_opaque",
        render_authorization={
            "schema": "engineering-drawing-render-authorization-v1",
            "invocation_id": "inv-1",
            "plan_sha256": "b" * 64,
        },
        source_pdf=published,
        source_sha256=_sha(published),
        candidate_pdf=published,
        candidate_sha256=_sha(published),
        review_evidence_sha256="c" * 64,
        auth=auth,
        document_context=document_context,
        glossary_tm_dir=None,
        prompt_files=None,
        operator={"name": "op", "qa_status": "reviewed", "notes": ""},
        started_at="2026-07-31T00:00:00Z",
        completed_at="2026-07-31T00:00:01Z",
        released_at="2026-07-31T00:00:02Z",
    )


def test_build_and_verify_roundtrip(tmp_path: Path) -> None:
    formal = _formal_with_pdf(tmp_path)
    payload = _build_payload(formal=formal)
    assert payload["schema"] == DELIVERY_MANIFEST_SCHEMA
    assert len(payload["release_authorization_sha256"]) == 64
    assert payload["source"]["sha256"] == payload["hashes"]["source_pdf"]
    write_delivery_manifest(formal_dir=formal, stem="candidate", payload=payload)
    result = verify_delivery_manifest(formal_dir=formal, stem="candidate")
    assert result["verified"] is True


def test_verify_detects_hash_tampering(tmp_path: Path) -> None:
    formal = _formal_with_pdf(tmp_path)
    payload = _build_payload(formal=formal)
    write_delivery_manifest(formal_dir=formal, stem="candidate", payload=payload)
    manifest_path = formal / "candidate.delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hashes"]["candidate_pdf"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate_pdf hash"):
        verify_delivery_manifest(formal_dir=formal, stem="candidate")


def test_write_manifest_is_idempotent_and_refuses_different(tmp_path: Path) -> None:
    formal = _formal_with_pdf(tmp_path)
    payload = _build_payload(formal=formal)
    path = write_delivery_manifest(formal_dir=formal, stem="candidate", payload=payload)
    again = write_delivery_manifest(formal_dir=formal, stem="candidate", payload=payload)
    assert path == again
    altered = dict(payload)
    altered["operator"] = {"name": "other"}
    with pytest.raises(ValueError, match="overwrite a different delivery manifest"):
        write_delivery_manifest(formal_dir=formal, stem="candidate", payload=altered)


def test_audit_formal_dir_warns_on_missing_manifest_but_stays_ok(tmp_path: Path) -> None:
    formal = tmp_path / "formal"
    formal.mkdir(parents=True, exist_ok=True)
    candidate = tmp_path / "c.pdf"
    candidate.write_bytes(b"%PDF-1.4 fake drawing")
    publish_to_formal(
        candidate=candidate,
        formal_dir=formal,
        auth={
            "schema": "engineering-drawing-human-release-authorization-v1",
            "workflow_version": WORKFLOW_VERSION,
            "authorization": "release",
            "authorization_kind": "human",
            "release_separate_from_renderer": True,
            "candidate_sha256": _sha(candidate),
        },
    )
    reports = audit_formal_dir(formal)
    assert len(reports) == 1
    assert "missing_delivery_manifest" in reports[0].get("warnings", [])
    assert reports[0]["ok"] is True


def test_audit_formal_dir_verifies_present_manifest(tmp_path: Path) -> None:
    formal = _formal_with_pdf(tmp_path)
    payload = _build_payload(formal=formal)
    write_delivery_manifest(formal_dir=formal, stem="candidate", payload=payload)
    reports = audit_formal_dir(formal)
    candidate_report = next(report for report in reports if report["pdf"] == "candidate.pdf")
    assert candidate_report["delivery_manifest_ok"] is True
