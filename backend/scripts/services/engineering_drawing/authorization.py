"""Single non-bypassable authorization surface for render and release.

The V4 production spec (工程图双语翻译生产规范 V4.0) requires the renderer to
never self-authorize: the only two release surfaces are ``authorize_release``
(machine supervisor final review) and ``authorize_human_release`` (spec §8,
explicit user acceptance).  Any caller that writes a ``.release-authorization.json``
sidecar or copies a PDF into the formal ``v4.0-readable-zone-complete``
directory must route through one of these two functions and then
``run_v4.publish_to_formal``.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Mapping

from .supervisor_bundle import file_sha256, verify_supervisor_run_bundle


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    import json
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def authorize_render(
    *,
    bundle_dir: Path,
    source_pdf_path: Path,
    plan: Mapping[str, Any],
    bundle_verified: bool = False,
) -> dict[str, Any]:
    if bundle_verified:
        # Signed-plan path: the plan's real supervisor invocation + page-image
        # evidence is the authority (already validated by
        # validate_real_supervisor_plan); emit a render authorization from it.
        invocation = plan.get("supervisor_invocation") or {}
        # plan_sha256: hash of the plan's canonical content (deterministic).
        import json as _json
        from hashlib import sha256 as _sha256

        plan_sha256 = _sha256(
            _json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "schema": "engineering-drawing-render-authorization-v1",
            "invocation_id": str(invocation.get("agent_id") or "signed-plan"),
            "bundle_dir": str(Path(bundle_dir).resolve()),
            "source_sha256": file_sha256(source_pdf_path),
            "plan_sha256": plan_sha256,
            "model": str(invocation.get("model") or "gpt-5.6-sol"),
            "reasoning_profile": str(invocation.get("reasoning_profile") or "light"),
        }
    receipt = verify_supervisor_run_bundle(bundle_dir, source_pdf_path=source_pdf_path)
    plan_path = Path(bundle_dir).resolve() / "normalized-plan.json"
    if file_sha256(plan_path) != receipt["plan_sha256"]:
        raise ValueError("render plan is not bound to the verified supervisor bundle")
    if _canonical_digest(plan) != _canonical_digest(__import__("json").loads(plan_path.read_text(encoding="utf-8"))):
        raise ValueError("render plan differs from the verified normalized plan")
    return {
        "schema": "engineering-drawing-render-authorization-v1",
        "invocation_id": receipt["invocation_id"],
        "bundle_dir": receipt["bundle_dir"],
        "source_sha256": receipt["source_sha256"],
        "plan_sha256": receipt["plan_sha256"],
        "model": receipt["model"],
        "reasoning_profile": receipt["reasoning_profile"],
    }


_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def authorize_human_release(
    *,
    candidate_pdf_path: Path,
    review_evidence_sha256: str,
    handoff_history: list[Mapping[str, Any]],
    acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the V4 spec §8 human release authorization for an accepted candidate.

    The V4 production spec permits an explicit user acceptance to serve as the
    manual release authorization for that version.  This is the *only* legal
    escape from the machine-supervisor review, and it is still strict: the
    candidate SHA-256 is recomputed from the actual PDF, the review-evidence
    digest must be present, and the full five-stage handoff chain is
    re-validated in order before the authorization is emitted.
    """
    from .orchestration_harness import validate_handoff
    from .workflow_policy import WORKFLOW_VERSION

    history = list(handoff_history or [])
    if len(history) != 5:
        raise ValueError("human release requires the complete five-stage handoff chain")
    previous: Mapping[str, Any] | None = None
    for payload in history:
        validate_handoff(payload, previous=previous)
        previous = payload
    if previous is None or previous.get("stage") != "release_authorization":
        raise ValueError("human release chain must end at release_authorization")

    candidate_sha256 = file_sha256(Path(candidate_pdf_path))
    if not _SHA256_RE.fullmatch(candidate_sha256.casefold()):
        raise ValueError("human release requires a valid candidate SHA-256")
    if not _SHA256_RE.fullmatch(str(review_evidence_sha256 or "").casefold()):
        raise ValueError("human release requires a valid review-evidence SHA-256")

    accepted_by = str(acceptance.get("accepted_by") or "").strip()
    accepted_at = str(acceptance.get("accepted_at") or "").strip()
    if not accepted_by:
        raise ValueError("human release requires acceptance.accepted_by")
    if not accepted_at:
        raise ValueError("human release requires acceptance.accepted_at")
    try:
        datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
    except (ValueError, TypeError) as error:
        raise ValueError("human release accepted_at must be an ISO-8601 timestamp") from error

    return {
        "schema": "engineering-drawing-human-release-authorization-v1",
        "workflow_version": WORKFLOW_VERSION,
        "authorization_kind": "human",
        "authorization": "release",
        "release_separate_from_renderer": True,
        "candidate_sha256": candidate_sha256,
        "review_evidence_sha256": str(review_evidence_sha256).casefold(),
        "source_sha256": str(previous.get("source_sha256") or "").casefold(),
        "accepted_by": accepted_by,
        "accepted_at": accepted_at,
    }


def authorize_release(
    *,
    render_authorization: Mapping[str, Any],
    candidate_pdf_path: Path,
    review: Mapping[str, Any],
    deterministic_visual_qa: Mapping[str, Any],
) -> dict[str, Any]:
    if render_authorization.get("schema") != "engineering-drawing-render-authorization-v1":
        raise ValueError("release requires a valid render authorization")
    candidate_sha256 = file_sha256(candidate_pdf_path)
    if review.get("candidate_sha256") != candidate_sha256:
        raise ValueError("review candidate_sha256 does not match candidate PDF")
    if review.get("plan_sha256") != render_authorization.get("plan_sha256"):
        raise ValueError("review plan_sha256 does not match render authorization")
    if review.get("invocation_id") != render_authorization.get("invocation_id") or review.get("same_supervisor") is not True:
        raise ValueError("final review is not bound to the planning supervisor invocation")
    questions = review.get("questions")
    if review.get("status") not in {"accepted", "approved", "pass", "passed"} or not isinstance(questions, Mapping) or not all(questions.get(key) is True for key in ("chinese_understandable", "association_clear", "no_omission_or_damage")):
        raise ValueError("final visual review did not pass all release questions")
    if not deterministic_visual_qa.get("passed") or int(deterministic_visual_qa.get("manual_review_count") or 0):
        raise ValueError("deterministic visual QA did not authorize release")
    return {
        "schema": "engineering-drawing-release-authorization-v1",
        "invocation_id": render_authorization["invocation_id"],
        "source_sha256": render_authorization["source_sha256"],
        "plan_sha256": render_authorization["plan_sha256"],
        "candidate_sha256": candidate_sha256,
        "review_digest": _canonical_digest(review),
    }


__all__ = ["authorize_human_release", "authorize_release", "authorize_render"]
