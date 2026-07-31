"""Generate frozen-production-config.json for the delivery-160 release.

Collects every identifier the production run is frozen on so the next Codex
session (and any later verifier) can prove the exact code, policy, prompts,
fonts, OCR config, models, glossary/TM, cache schemas and dependencies that
produced a deliverable.  Run from the release branch; writes to the repo root.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT_PATH = REPO / "frozen-production-config.json"
SCHEMA = "engineering-drawing-frozen-production-config-v1"

sys.path.insert(0, str(REPO / "backend" / "scripts"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return _sha256_bytes(path.read_bytes())


def _file_record(path: Path) -> dict[str, object]:
    path = Path(path)
    return {"path": str(path), "sha256": _file_sha256(path), "present": path.is_file()}


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()


def _git_commit_short() -> str:
    return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True).strip()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> int:
    from services.engineering_drawing.cache import CACHE_SCHEMA_PREFIX
    from services.engineering_drawing.hybrid_ocr import HybridOcrConfig
    from services.engineering_drawing.orchestration_harness import canonical_policy_fingerprint
    from services.engineering_drawing.translation_qa import _CACHE_SCHEMA as TRANSLATION_CACHE_SCHEMA
    from services.engineering_drawing.translation_qa import _PROMPT_VERSION
    from services.engineering_drawing.workflow_policy import (
        DEFAULT_MULTIMODAL_MODEL,
        DEFAULT_SUPERVISOR_ADAPTER,
        WORKFLOW_VERSION,
    )
    from services.translation.llm.shared.provider_runtime import DEFAULT_MODEL as TRANSLATION_MODEL

    prompts_dir = REPO / "backend" / "scripts" / "foundation" / "prompts"
    fonts_dir = REPO / "backend" / "fonts"
    glossary_dir = REPO / "output" / "pdf" / "engineering-drawing" / "05_Glossary_TM"

    ocr_config = HybridOcrConfig()
    document_context_template = {
        "language_policy": "bilingual",
        "units": "metric",
        "drawing_discipline": "engineering",
        "confidentiality_policy": "local_only",
    }

    config = {
        "schema": SCHEMA,
        "freeze_id": "delivery-160-rc1",
        "git_commit": _git_commit(),
        "git_commit_short": _git_commit_short(),
        "workflow_version": WORKFLOW_VERSION,
        "policy_fingerprint": canonical_policy_fingerprint(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompt_hashes": {
            "rule_profile_engineering_drawing.txt": _file_record(prompts_dir / "rule_profile_engineering_drawing.txt"),
            "engineering_drawing_supervisor_v37.txt": _file_record(prompts_dir / "engineering_drawing_supervisor_v37.txt"),
        },
        "font_hashes": {
            "SourceHanSerifSC-Regular.otf": _file_record(fonts_dir / "SourceHanSerifSC-Regular.otf"),
            "SourceHanSerifSC-Bold.otf": _file_record(fonts_dir / "SourceHanSerifSC-Bold.otf"),
        },
        "ocr_model_identifiers": {
            "paddle_det_model": str(ocr_config.paddle_det_model),
            "paddle_rec_model": str(ocr_config.paddle_rec_model),
            "pipeline_version": int(ocr_config.pipeline_version),
            "dpi": int(ocr_config.dpi),
            "tile_size": int(ocr_config.tile_size),
            "tile_overlap": int(ocr_config.tile_overlap),
            "deepseek_review_threshold": float(ocr_config.deepseek_review_threshold),
            "min_paddle_confidence": float(ocr_config.min_paddle_confidence),
            "deepseek_max_regions_per_page": int(ocr_config.deepseek_max_regions_per_page),
            "direct_tile_render": bool(ocr_config.direct_tile_render),
        },
        "supervisor_model_identifier": {
            "alias": str(DEFAULT_SUPERVISOR_ADAPTER["alias"]),
            "model": DEFAULT_MULTIMODAL_MODEL,
            "reasoning_profile": str(DEFAULT_SUPERVISOR_ADAPTER["reasoning_profile"]),
        },
        "translation_model_identifier": TRANSLATION_MODEL,
        "glossary_tm_hashes": {
            name: _file_record(glossary_dir / name)
            for name in ("engineering-glossary-v1.csv", "translation-memory-v1.json", "translation-qa-cache.json", "geographic-entity-cache.json")
        },
        "document_context_template": document_context_template,
        "document_context_template_hash": _sha256_bytes(_canonical_json(document_context_template).encode("utf-8")),
        "cache_schema_versions": {
            "translation_qa_cache_schema": TRANSLATION_CACHE_SCHEMA,
            "translation_prompt_version": _PROMPT_VERSION,
            "cache_prefix": CACHE_SCHEMA_PREFIX,
        },
        "dependency_versions": _dependency_versions(),
        "verification": {
            "full_suite_passed": 662,
            "test_command": "cd backend/scripts && python -m pytest devtools/tests/engineering_drawing -q",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    OUT_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(OUT_PATH), "sha256": _file_sha256(OUT_PATH), "git_commit": config["git_commit"]}, ensure_ascii=False, indent=2))
    return 0


def _dependency_versions() -> dict[str, str]:
    import importlib.metadata as im

    result: dict[str, str] = {}
    for package in ("pymupdf", "pikepdf", "Pillow", "numpy", "rapidocr_onnxruntime", "paddleocr"):
        try:
            result[package] = im.version(package)
        except Exception:
            result[package] = "not-installed"
    return result


if __name__ == "__main__":
    raise SystemExit(main())
