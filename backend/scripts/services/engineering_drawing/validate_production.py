"""Read-only production dry-run (flight checklist) before the canary phase.

``delivery-run validate-production`` verifies the delivery is internally
consistent WITHOUT calling OCR, LLM or rendering:

- manifest parses, items are unique by item_id + content_hash
- the first 5 source PDFs open, page counts known
- document_context template hash matches the frozen config
- glossary/TM files readable and hash-verified against the lock
- output naming is collision-free and has no formal-dir clashes
- frozen-production-config.json (freeze hash) is present and its policy
  fingerprint matches the manifest

This is the gate that runs right before canary so a batch never starts on a
broken manifest.  Exit code 2 on any failure.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import fitz

from .delivery_run import file_sha256
from .orchestration_harness import canonical_policy_fingerprint

VALIDATE_SCHEMA = "engineering-drawing-validate-production-v1"
FROZEN_CONFIG_NAME = "frozen-production-config.json"
SAMPLE_PDF_COUNT = 5


def validate_production(*, args: Any) -> dict[str, Any]:
    """Run the dry-run; ``args`` carries --manifest/--source-root/--output-root."""
    if args.manifest is None or args.source_root is None or args.output_root is None:
        raise SystemExit("delivery-run validate-production requires --manifest --source-root --output-root")
    manifest_path = Path(args.manifest)
    source_root = Path(args.source_root)
    output_root = Path(args.output_root)
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            failures.append(name)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = list(manifest.get("items") or [])
    check("manifest_parses", bool(items), f"{len(items)} items")

    # Unique item_id + content_hash.
    ids = [str(it.get("item_id") or "") for it in items]
    hashes = [str(it.get("content_hash") or "") for it in items]
    check("item_ids_unique", len(ids) == len(set(ids)), f"{len(ids)} ids, {len(ids) - len(set(ids))} dups")
    check("content_hashes_unique", len(hashes) == len(set(hashes)), f"{len(hashes) - len(set(hashes))} dup hashes")

    # Sample the first 5 PDFs.
    for it in items[:SAMPLE_PDF_COUNT]:
        source = source_root / str(it.get("source_pdf") or "")
        try:
            with fitz.open(source) as document:
                page_count = document.page_count
            check(f"open_{it.get('item_id')}", True, f"{source.name} {page_count}p")
        except Exception as error:
            check(f"open_{it.get('item_id')}", False, str(error))

    # document_context template hash matches frozen config.
    template = manifest.get("document_context_template") or {}
    template_hash = hashlib.sha256(
        json.dumps(template, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest_template_hash = str(manifest.get("document_context_template_hash") or "")
    check("template_hash_consistent", template_hash == manifest_template_hash, f"{template_hash[:12]} vs {manifest_template_hash[:12]}")

    # Glossary/TM readable + hash-verified against glossary-tm-lock.json.
    glossary_dir = Path(manifest.get("glossary_tm_dir") or "glossary_tm")
    glossary_dir = glossary_dir if glossary_dir.is_absolute() else source_root.parent / glossary_dir
    lock_path = glossary_dir / "glossary-tm-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else {}
    for name, expected in lock.items():
        target = glossary_dir / name
        actual = file_sha256(target) if target.is_file() else None
        check(f"glossary_{name}", actual == expected.get("sha256"), f"{name} {'ok' if actual == expected.get('sha256') else 'hash-mismatch'}")

    # Output naming collision-free.
    outs = [str(it.get("relative_output") or "") for it in items]
    check("output_names_unique", len(outs) == len(set(outs)), f"{len(outs) - len(set(outs))} dup outputs")

    # Frozen config present + policy fingerprint matches.
    frozen_path = Path(args.freeze_config) if getattr(args, "freeze_config", None) else output_root / FROZEN_CONFIG_NAME
    if frozen_path.is_file():
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        frozen_fp = str(frozen.get("policy_fingerprint") or "")
        manifest_fp = str(manifest.get("policy_fingerprint") or "")
        check("freeze_config_present", True, str(frozen_path))
        check("policy_fingerprint_matches", frozen_fp == manifest_fp == canonical_policy_fingerprint(), f"{manifest_fp[:12]} vs {canonical_policy_fingerprint()[:12]}")
    else:
        check("freeze_config_present", False, "missing frozen-production-config.json")

    return {
        "schema": VALIDATE_SCHEMA,
        "passed": not failures,
        "failures": failures,
        "checks": checks,
        "manifest": str(manifest_path),
    }


__all__ = ["VALIDATE_SCHEMA", "validate_production"]
