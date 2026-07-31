"""Integrity verification for immutable multimodal-supervisor run bundles."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import fitz


REQUIRED_FILES = (
    "request.json",
    "model-response.raw.json",
    "normalized-plan.json",
    "source-manifest.json",
    "invocation-receipt.json",
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def create_supervisor_run_bundle(
    *,
    bundle_dir: Path,
    source_pdf_path: Path,
    page_images: list[Path],
    request: dict[str, Any],
    raw_response: dict[str, Any],
    normalized_plan: dict[str, Any],
    invocation_id: str,
    agent_id: str,
    started_at: str,
    completed_at: str,
) -> Path:
    """Freeze one Codex Sol Light multimodal invocation into an auditable bundle."""
    bundle = Path(bundle_dir).resolve()
    if bundle.exists() and any(bundle.iterdir()):
        raise ValueError("supervisor run bundle directory must be empty")
    image_dir = bundle / "page-images"
    image_dir.mkdir(parents=True, exist_ok=True)
    source = Path(source_pdf_path).resolve()
    with fitz.open(source) as document:
        if len(page_images) != len(document):
            raise ValueError("create bundle requires exactly one image per source page")
        page_sizes = [[float(page.rect.width), float(page.rect.height)] for page in document]
    image_records = []
    for page_index, source_image in enumerate(page_images):
        target = image_dir / f"page-{page_index + 1:04d}{Path(source_image).suffix.lower()}"
        shutil.copy2(Path(source_image), target)
        image_records.append({"page_index": page_index, "path": target.relative_to(bundle).as_posix(), "sha256": file_sha256(target)})
    bound_request = {
        **request,
        "model": "gpt-5.6-sol",
        "reasoning_profile": "light",
        "images": [item["path"] for item in image_records],
    }
    manifest = {
        "source_pdf": str(source),
        "source_sha256": file_sha256(source),
        "page_count": len(page_images),
        "page_sizes": page_sizes,
        "page_images": image_records,
    }
    _write_json(bundle / "request.json", bound_request)
    _write_json(bundle / "model-response.raw.json", raw_response)
    _write_json(bundle / "normalized-plan.json", normalized_plan)
    _write_json(bundle / "source-manifest.json", manifest)
    receipt = {
        "invocation_id": invocation_id,
        "agent_id": agent_id,
        "mode": "codex_agent_multimodal",
        "model": "gpt-5.6-sol",
        "reasoning_profile": "light",
        "started_at": started_at,
        "completed_at": completed_at,
        "request_sha256": file_sha256(bundle / "request.json"),
        "response_sha256": file_sha256(bundle / "model-response.raw.json"),
        "plan_sha256": file_sha256(bundle / "normalized-plan.json"),
        "source_manifest_sha256": file_sha256(bundle / "source-manifest.json"),
    }
    _write_json(bundle / "invocation-receipt.json", receipt)
    _write_json(bundle / "hashes.json", {name: file_sha256(bundle / name) for name in REQUIRED_FILES})
    verify_supervisor_run_bundle(bundle, source_pdf_path=source)
    return bundle


def file_sha256(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def verify_supervisor_run_bundle(bundle_dir: Path, *, source_pdf_path: Path) -> dict[str, Any]:
    bundle = Path(bundle_dir).resolve()
    source_pdf = Path(source_pdf_path).resolve()
    for name in (*REQUIRED_FILES, "hashes.json"):
        if not (bundle / name).is_file():
            raise ValueError(f"supervisor run bundle is missing {name}")
    hashes = _json(bundle / "hashes.json")
    for name in REQUIRED_FILES:
        actual = file_sha256(bundle / name)
        if str(hashes.get(name) or "").casefold() != actual:
            field = "response_sha256" if name == "model-response.raw.json" else name
            raise ValueError(f"bundle {field} hash does not match")

    receipt = _json(bundle / "invocation-receipt.json")
    bindings = {
        "request_sha256": "request.json",
        "response_sha256": "model-response.raw.json",
        "plan_sha256": "normalized-plan.json",
        "source_manifest_sha256": "source-manifest.json",
    }
    for field, name in bindings.items():
        if str(receipt.get(field) or "").casefold() != file_sha256(bundle / name):
            raise ValueError(f"invocation receipt {field} does not match {name}")
    if receipt.get("model") != "gpt-5.6-sol" or receipt.get("reasoning_profile") != "light":
        raise ValueError("supervisor run must use Codex gpt-5.6-sol with light reasoning")
    if receipt.get("mode") != "codex_agent_multimodal":
        raise ValueError("supervisor run must be a Codex multimodal agent invocation")
    try:
        started = datetime.fromisoformat(str(receipt["started_at"]).replace("Z", "+00:00"))
        completed = datetime.fromisoformat(str(receipt["completed_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("supervisor invocation timestamps are invalid") from error
    if completed < started:
        raise ValueError("supervisor invocation completed_at precedes started_at")

    manifest = _json(bundle / "source-manifest.json")
    if str(manifest.get("source_pdf")) != str(source_pdf):
        raise ValueError("bundle source path does not match original PDF")
    if str(manifest.get("source_sha256") or "").casefold() != file_sha256(source_pdf):
        raise ValueError("bundle source SHA-256 does not match original PDF")
    with fitz.open(source_pdf) as document:
        if manifest.get("page_count") != len(document):
            raise ValueError("bundle page count does not match original PDF")
        expected_sizes = [[float(page.rect.width), float(page.rect.height)] for page in document]
    if manifest.get("page_sizes") != expected_sizes:
        raise ValueError("bundle page sizes do not match original PDF")
    images = manifest.get("page_images")
    if not isinstance(images, list) or len(images) != manifest["page_count"]:
        raise ValueError("bundle must bind exactly one image for every source page")
    for page_index, item in enumerate(images):
        if not isinstance(item, dict) or item.get("page_index") != page_index:
            raise ValueError("bundle page images must be ordered and page-bound")
        image_path = (bundle / str(item.get("path") or "")).resolve()
        if bundle not in image_path.parents or not image_path.is_file():
            raise ValueError("bundle page image is missing or outside bundle")
        if str(item.get("sha256") or "").casefold() != file_sha256(image_path):
            raise ValueError("bundle page image SHA-256 does not match")
    request = _json(bundle / "request.json")
    if request.get("model") != receipt["model"] or request.get("reasoning_profile") != receipt["reasoning_profile"]:
        raise ValueError("request model configuration does not match invocation receipt")
    requested_images = request.get("images")
    if requested_images != [item["path"] for item in images]:
        raise ValueError("request does not contain the exact bound source page images")
    return {**receipt, "bundle_dir": str(bundle), "source_sha256": manifest["source_sha256"]}


__all__ = ["create_supervisor_run_bundle", "file_sha256", "verify_supervisor_run_bundle"]
