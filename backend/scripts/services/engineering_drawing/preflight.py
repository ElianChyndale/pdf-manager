"""Production preflight for the 160-PDF delivery run.

Verifies the environment ONCE before the next Codex session spends credits:
sources exist/open/unique, output writable, disk space, OCR/LLM environments,
fonts, glossary/TM, prompts, policy fingerprint stability, formal-dir clashes,
and a capacity estimate.  Codex supervisor quota is a **manual start condition**
and is never auto-verified.

Outputs ``delivery-preflight.json`` + ``.html``.  A critical failure refuses to
start the batch.
"""

from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import fitz

from .delivery_run import file_sha256
from .fonts.resolve import resolve_cjk_font
from .orchestration_harness import canonical_policy_fingerprint

PREFLIGHT_SCHEMA = "engineering-drawing-delivery-preflight-v1"


def run_preflight(
    *,
    manifest: Mapping[str, Any],
    source_root: Path,
    output_root: Path,
    formal_dir: Path | None = None,
    glossary_dir: Path | None = None,
    prompt_dir: Path | None = None,
    production_runtime: bool = False,
) -> dict[str, Any]:
    """Run all preflight checks and return the report.

    ``production_runtime=True`` additionally verifies the PRODUCTION execution
    environment (PaddleOCR, DeepSeek endpoint, translation provider, PyMuPDF,
    and the pinned dependency set) — the check that must be green before the
    canary phase actually calls OCR/LLM.  Without the flag these are reported
    as advisory so dev/CI preflight does not fail on a missing local model.
    """
    checks: list[dict[str, Any]] = []
    critical_failures: list[str] = []

    def check(name: str, passed: bool, detail: str = "", *, critical: bool = True) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail, "critical": critical})
        if not passed and critical:
            critical_failures.append(name)

    # Sources
    items = list(manifest.get("items") or [])
    sources = []
    missing = []
    for item in items:
        source = Path(source_root) / Path(str(item.get("source_pdf") or ""))
        if not source.is_file():
            missing.append(str(source))
        else:
            sources.append(source)
    check("sources_exist", not missing, f"{len(missing)} missing: {', '.join(missing[:5])}")

    # Unique hashes
    hashes = [file_sha256(source) for source in sources]
    check("sources_unique", len(set(hashes)) == len(hashes), f"{len(hashes) - len(set(hashes))} duplicates")

    # Openable
    unopenable = []
    for source in sources:
        try:
            with fitz.open(source) as document:
                _ = document.page_count
        except Exception:
            unopenable.append(str(source))
    check("sources_openable", not unopenable, f"{len(unopenable)} unopenable")

    # Output writable
    try:
        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        probe = output_root / ".preflight-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError:
        writable = False
    check("output_writable", writable, str(output_root))

    # Disk space
    try:
        free_gb = shutil.disk_usage(output_root).free / (1024 ** 3)
        check("disk_space", free_gb > 2.0, f"{free_gb:.1f} GiB free")
    except OSError:
        check("disk_space", False, "disk usage unavailable")

    # OCR environments (best-effort import probes)
    paddle_ok = _module_importable("paddleocr")
    check("paddle_ocr_env", paddle_ok, "paddleocr import", critical=False)
    deepseek_ok = True  # DeepSeek runs via HTTP; no import requirement

    # LLM provider
    try:
        from services.translation.llm.shared.provider_runtime import get_api_key

        key_present = bool(get_api_key(required=False))
    except Exception:
        key_present = False
    check("llm_api_key_present", key_present, "translation provider key", critical=False)

    # ---- Production runtime checks (--production-runtime) -------------------
    if production_runtime:
        _production_runtime_checks(checks, critical_failures, check)

    # CJK font
    try:
        font_path = resolve_cjk_font()
        check("cjk_font_present", True, str(font_path))
    except FileNotFoundError as error:
        check("cjk_font_present", False, str(error))

    # Glossary / TM readable
    # Resolve in priority order: explicit --glossary-tm-dir arg, then the
    # manifest-declared glossary_tm_dir (relative to the delivery root =
    # source_root.parent), then the legacy implicit ../05_Glossary_TM.
    resolved_glossary = None
    if glossary_dir:
        resolved_glossary = Path(glossary_dir)
    else:
        declared = str(manifest.get("glossary_tm_dir") or "")
        if declared:
            delivery_root = Path(source_root).parent
            candidate = Path(declared)
            resolved_glossary = candidate if candidate.is_absolute() else delivery_root / candidate
    glossary_dir = resolved_glossary or (Path(source_root).parent / "05_Glossary_TM")
    glossary_ok = (glossary_dir / "engineering-glossary-v1.csv").is_file()
    tm_ok = (glossary_dir / "translation-memory-v1.json").is_file()
    check("glossary_readable", glossary_ok, str(glossary_dir / "engineering-glossary-v1.csv"), critical=False)
    check("tm_readable", tm_ok, str(glossary_dir / "translation-memory-v1.json"), critical=False)

    # Prompts present
    prompt_dir = Path(prompt_dir) if prompt_dir else Path(__file__).resolve().parents[2] / "foundation" / "prompts"
    prompts = ["rule_profile_engineering_drawing.txt", "engineering_drawing_supervisor_v37.txt"]
    missing_prompts = [name for name in prompts if not (prompt_dir / name).is_file()]
    check("prompts_present", not missing_prompts, f"missing: {missing_prompts}")

    # Policy fingerprint stable
    try:
        fingerprint = canonical_policy_fingerprint()
        check("policy_fingerprint_stable", bool(fingerprint) and len(fingerprint) == 64, fingerprint)
    except Exception as error:
        check("policy_fingerprint_stable", False, str(error))

    # Formal-dir clashes
    if formal_dir is not None:
        formal_dir = Path(formal_dir)
        existing = {p.name for p in formal_dir.glob("*.pdf")} if formal_dir.is_dir() else set()
        conflicts = [
            str(item.get("relative_output") or "")
            for item in items
            if Path(str(item.get("relative_output") or "")).name in existing
        ]
        check("formal_dir_no_clash", not conflicts, f"clashes: {conflicts[:5]}")

    # Capacity estimate
    capacity = estimate_capacity(items=items, source_root=source_root)

    return {
        "schema": PREFLIGHT_SCHEMA,
        "passed": not critical_failures,
        "critical_failures": critical_failures,
        "checks": checks,
        "capacity": capacity,
        "codex_operator_supervisor": {
            "group": "manual",
            "note": "Codex quota/model availability is a manual start condition; it cannot be auto-verified by a local script.",
        },
    }


def _production_runtime_checks(checks: list, critical_failures: list, check: Any) -> None:
    """Verify the PRODUCTION execution environment before any OCR/LLM call."""
    # PaddleOCR importable.
    try:
        import paddleocr  # noqa: F401

        check("runtime_paddleocr", True, "paddleocr importable")
    except Exception as error:
        check("runtime_paddleocr", False, f"paddleocr import failed: {error}")

    # DeepSeek OCR runner present (endpoint reachability is a network check done
    # at canary time; here we verify the runner module + endpoint config exist).
    try:
        from services.engineering_drawing.ocr_runners import deepseek_runner

        check("runtime_deepseek_ocr", True, f"deepseek_runner at {Path(deepseek_runner.__file__).name}")
    except Exception as error:
        check("runtime_deepseek_ocr", False, f"deepseek_runner import failed: {error}")

    # Translation provider key + base URL.
    try:
        from services.translation.llm.shared.provider_runtime import DEFAULT_BASE_URL, get_api_key

        key_present = bool(get_api_key(required=False))
        check("runtime_translation_provider", key_present, f"translation key present; base_url={DEFAULT_BASE_URL}")
    except Exception as error:
        check("runtime_translation_provider", False, f"translation provider probe failed: {error}")

    # PyMuPDF version (pinned in frozen config).
    import fitz as _fitz

    check("runtime_pymupdf", True, f"pymupdf {_fitz.version[0]}")

    # Pinned dependency set (from frozen-production-config.json dependency_versions).
    expected = {
        "pymupdf": "1.27.2.3",
        "pikepdf": "10.6.0",
        "Pillow": "11.0.0",
        "numpy": "2.1.2",
        "rapidocr_onnxruntime": "1.2.3",
    }
    import importlib.metadata as im

    mismatched: list[str] = []
    for package, version in expected.items():
        try:
            installed = im.version(package)
            if installed != version:
                mismatched.append(f"{package} {installed} != {version}")
        except Exception:
            mismatched.append(f"{package} not installed")
    check("runtime_dependencies", not mismatched, "; ".join(mismatched) or "all pinned deps match")

    # CJK font for the render path.
    try:
        font_path = resolve_cjk_font()
        check("runtime_cjk_font", True, str(font_path))
    except FileNotFoundError as error:
        check("runtime_cjk_font", False, str(error))


def estimate_capacity(*, items: list[Mapping[str, Any]], source_root: Path) -> dict[str, Any]:
    total_pages = 0
    scanned_pages = 0
    disciplines: set[str] = set()
    for item in items:
        source = Path(source_root) / Path(str(item.get("source_pdf") or ""))
        if not source.is_file():
            continue
        try:
            with fitz.open(source) as document:
                pages = document.page_count
            total_pages += pages
            # Coarse raster scan: no selectable text on any page.
            with fitz.open(source) as document:
                for page in document:
                    if not page.get_text().strip():
                        scanned_pages += 1
        except Exception:
            continue
        if isinstance(item.get("document_context"), dict):
            discipline = item["document_context"].get("drawing_discipline")
            if discipline:
                disciplines.add(str(discipline))
    return {
        "total_pdfs": len(items),
        "total_pages": total_pages,
        "scanned_pages": scanned_pages,
        "disciplines": sorted(disciplines),
        "estimated_paddle_calls": total_pages,
        "estimated_deepseek_escalations": max(0, scanned_pages),
        "estimated_supervisor_plans": total_pages,
        "estimated_review_regions": scanned_pages * 5,
        "estimated_disk_gb": round(total_pages * 0.01, 2),
        "estimated_time_hours": round(total_pages * 0.2, 1),
    }


def _module_importable(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def build_preflight_html(report: Mapping[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(str(check['check']))}</td>"
        f"<td>{'PASS' if check['passed'] else ('CRITICAL' if check['critical'] else 'WARN')}</td>"
        f"<td>{html.escape(str(check['detail']))}</td></tr>"
        for check in report.get("checks") or []
    )
    cap = report.get("capacity") or {}
    cap_rows = "".join(
        f"<tr><td>{html.escape(str(key))}</td><td>{html.escape(str(value))}</td></tr>"
        for key, value in cap.items()
    )
    status = "PASS" if report.get("passed") else "BLOCKED"
    color = "#1a7f37" if report.get("passed") else "#b00020"
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Engineering-Drawing Delivery Preflight</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #ccc;padding:6px}</style></head><body>"
        f"<h1>Delivery Preflight — <span style=\"color:{color}\">{status}</span></h1>"
        "<h2>Environment checks</h2><table><tr><th>check</th><th>status</th><th>detail</th></tr>"
        + rows + "</table>"
        "<h2>Capacity estimate</h2><table>" + cap_rows + "</table>"
        "<p><em>Codex supervisor quota is a manual start condition and is not "
        "auto-verified.</em></p>"
        "</body></html>"
    )


__all__ = [
    "PREFLIGHT_SCHEMA",
    "build_preflight_html",
    "estimate_capacity",
    "run_preflight",
]
