"""Delivery manifest for V4 engineering-drawing formal releases.

A delivery manifest freezes the full provenance of one published PDF into a
hash-chained record, following the same immutable-bundle pattern as
``supervisor_bundle.py``: the manifest is bound to the release-authorization
sidecar via ``release_authorization_sha256`` and to the source/candidate PDFs
and review evidence via the ``hashes`` block.  It lets a future consumer answer
"which code, OCR model, LLM model, glossary version, prompt version, renderer
and operator produced this deliverable?" for every file in the formal
``v4.0-readable-zone-complete`` directory.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from .supervisor_bundle import file_sha256

DELIVERY_MANIFEST_SCHEMA = "engineering-drawing-delivery-manifest-v1"
# Fields that MUST be present as 64-char SHA-256 digests and are re-verified.
BINDING_FIELDS = frozenset(
    {
        "source_sha256",
        "candidate_sha256",
        "review_evidence_sha256",
        "release_authorization_sha256",
    }
)

GLOSSARY_TM_FILES = (
    "engineering-glossary-v1.csv",
    "translation-memory-v1.json",
    "translation-qa-cache.json",
    "geographic-entity-cache.json",
)
PROMPT_FILES = (
    "rule_profile_engineering_drawing.txt",
    "engineering_drawing_supervisor_v37.txt",
)


def _file_record(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {"path": str(path.resolve()), "sha256": None, "present": False}
    return {"path": str(path.resolve()), "sha256": file_sha256(path), "present": True}


def default_prompt_files() -> dict[str, Path]:
    """Resolve the supervisor prompt files under backend/scripts/foundation/prompts/."""
    prompts_dir = Path(__file__).resolve().parents[2] / "foundation" / "prompts"
    return {name: prompts_dir / name for name in PROMPT_FILES}


def build_delivery_manifest(
    *,
    delivery_id: str,
    run_id: str,
    workflow_version: str,
    policy_fingerprint: str,
    supervisor: Mapping[str, Any],
    renderer: str,
    render_authorization: Mapping[str, Any],
    source_pdf: Path,
    source_sha256: str,
    candidate_pdf: Path,
    candidate_sha256: str,
    review_evidence_sha256: str,
    auth: Mapping[str, Any],
    document_context: Mapping[str, Any] | None,
    glossary_tm_dir: Path | None,
    prompt_files: Mapping[str, Path] | None,
    operator: Mapping[str, Any] | None,
    started_at: str,
    completed_at: str,
    released_at: str,
) -> dict[str, Any]:
    """Assemble the delivery manifest dict (does not write anything)."""
    release_auth_sha256 = file_sha256(Path(candidate_pdf).with_suffix(".release-authorization.json"))
    glossary_dir = Path(glossary_tm_dir) if glossary_tm_dir else None
    glossary_records: dict[str, dict[str, Any]] = {}
    if glossary_dir is not None and glossary_dir.is_dir():
        for name in GLOSSARY_TM_FILES:
            glossary_records[name] = _file_record(glossary_dir / name)
    prompt_records = {
        name: _file_record(path) for name, path in (prompt_files or {}).items()
    }
    from .fonts.resolve import font_identity

    font_record = font_identity()
    page_count = _pdf_page_count(Path(candidate_pdf))
    hashes: dict[str, Any] = {
        "source_pdf": source_sha256,
        "candidate_pdf": candidate_sha256,
        "review_evidence": review_evidence_sha256,
        "release_authorization": release_auth_sha256,
    }
    for name, record in glossary_records.items():
        if record.get("sha256"):
            hashes[f"glossary_{name}"] = record["sha256"]
    for name, record in prompt_records.items():
        if record.get("sha256"):
            hashes[f"prompt_{name}"] = record["sha256"]

    release: dict[str, Any] = {
        "schema": str(auth.get("schema") or ""),
        "authorization_kind": str(auth.get("authorization_kind") or "machine_supervisor"),
        "authorization": str(auth.get("authorization") or ""),
        "release_separate_from_renderer": bool(auth.get("release_separate_from_renderer")),
    }
    if auth.get("accepted_by"):
        release["accepted_by"] = str(auth["accepted_by"])
    if auth.get("accepted_at"):
        release["accepted_at"] = str(auth["accepted_at"])

    return {
        "schema": DELIVERY_MANIFEST_SCHEMA,
        "delivery_id": delivery_id,
        "run_id": run_id,
        "workflow_version": workflow_version,
        "policy_fingerprint": policy_fingerprint,
        "source_sha256": source_sha256,
        "candidate_sha256": candidate_sha256,
        "supervisor": {
            "model": str(supervisor.get("model") or ""),
            "reasoning_profile": str(supervisor.get("reasoning_profile") or ""),
            "invocation_id": str(render_authorization.get("invocation_id") or ""),
            "bundle_dir": str(render_authorization.get("bundle_dir") or ""),
            "plan_sha256": str(render_authorization.get("plan_sha256") or ""),
        },
        "renderer": {
            "name": renderer,
            "authorization_schema": str(render_authorization.get("schema") or ""),
        },
        "source": {
            "pdf": str(Path(source_pdf).resolve()),
            "sha256": source_sha256,
            "page_count": _pdf_page_count(Path(source_pdf)),
        },
        "candidate": {
            "pdf": str(Path(candidate_pdf).resolve()),
            "sha256": candidate_sha256,
            "page_count": page_count,
        },
        "review_evidence_sha256": review_evidence_sha256,
        "release_authorization": release,
        "document_context": dict(document_context) if document_context else None,
        "glossary_tm": glossary_records,
        "prompt_versions": prompt_records,
        "fonts": font_record,
        "operator": dict(operator or {}),
        "timestamps": {
            "started_at": started_at,
            "completed_at": completed_at,
            "released_at": released_at,
        },
        "release_authorization_sha256": release_auth_sha256,
        "hashes": hashes,
    }


def _pdf_page_count(path: Path) -> int:
    try:
        import fitz

        with fitz.open(path) as document:
            return document.page_count
    except Exception:
        return 0


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_delivery_manifest(*, formal_dir: Path, stem: str, payload: Mapping[str, Any]) -> Path:
    """Write ``<stem>.delivery-manifest.json`` next to the formal PDF.

    Idempotent when identical content already exists; refuses to overwrite a
    different manifest for the same stem (immutability).
    """
    formal_dir = Path(formal_dir).resolve()
    target = formal_dir / f"{stem}.delivery-manifest.json"
    canonical = _canonical(payload) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != canonical:
            raise ValueError(f"refusing to overwrite a different delivery manifest at {target.name}")
        return target
    target.write_text(canonical, encoding="utf-8")
    return target


def verify_delivery_manifest(*, formal_dir: Path, stem: str) -> dict[str, Any]:
    """Recompute every hash from the actual files; raise on any mismatch."""
    formal_dir = Path(formal_dir).resolve()
    manifest_path = formal_dir / f"{stem}.delivery-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema") != DELIVERY_MANIFEST_SCHEMA:
        raise ValueError("delivery manifest has an unexpected schema")
    for field in BINDING_FIELDS:
        value = str(payload.get(field) or "")
        if len(value) != 64:
            raise ValueError(f"delivery manifest requires a valid {field}")
    pdf = formal_dir / f"{stem}.pdf"
    sidecar = formal_dir / f"{stem}.release-authorization.json"
    # source_pdf is an absolute path; verify its bytes against the hashes block.
    source_record = payload.get("source") or {}
    source_path = Path(str(source_record.get("pdf") or ""))
    if source_path.is_file() and str(payload.get("hashes", {}).get("source_pdf") or "") != file_sha256(source_path):
        raise ValueError("delivery manifest source_pdf hash does not match")
    candidate_record = payload.get("candidate") or {}
    candidate_path = Path(str(candidate_record.get("pdf") or ""))
    if str(payload.get("hashes", {}).get("candidate_pdf") or "") != file_sha256(pdf):
        raise ValueError("delivery manifest candidate_pdf hash does not match")
    if str(payload.get("hashes", {}).get("release_authorization") or "") != file_sha256(sidecar):
        raise ValueError("delivery manifest release_authorization hash does not match")
    if str(payload.get("release_authorization_sha256") or "") != file_sha256(sidecar):
        raise ValueError("delivery manifest release_authorization_sha256 does not match sidecar")
    return {"schema": DELIVERY_MANIFEST_SCHEMA, "stem": stem, "verified": True, "delivery_id": payload.get("delivery_id")}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "BINDING_FIELDS",
    "DELIVERY_MANIFEST_SCHEMA",
    "GLOSSARY_TM_FILES",
    "PROMPT_FILES",
    "build_delivery_manifest",
    "default_prompt_files",
    "now_iso",
    "verify_delivery_manifest",
    "write_delivery_manifest",
]
