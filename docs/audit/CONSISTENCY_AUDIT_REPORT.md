# Consistency Audit Report — delivery-160-rc2 production freeze

> Audit date: 2026-08-02
> Freeze: `release/engineering-delivery-160` / `delivery-160-rc2`
> Method: repository-wide read-only audit (docs, skills, CLI, config, code paths, tests) + targeted verification.

## Executive summary

The repository is consistent with the production workflow. No **deletions** were
performed; the only code change is a **2-line portable-font completion fix** in
`overlay_pair.py` (CRITICAL), and the only doc change is adding the
`delivery-run` production pipeline to the service `AGENTS.md` (WARNING gap).
Three deliverables are added under `docs/audit/`.

**One production artifact is intentionally NOT modified:** `frozen-production-config.json`
still records `freeze_id = delivery-160-rc1`, `git_commit = fde70aa2`,
`verification.full_suite_passed = 662`. That is correct and by design — the rc1
freeze pinned the production **code** hash; the rc2 hotfix is additive
preflight/validate-production/dashboard tooling on a separate branch and does
not change translation logic, so the rc1 code hash remains the valid production
identity. The rc2 verification is recorded in this report and in
`PRODUCTION_SOURCE_OF_TRUTH.md`.

## Repository health

| Area | Status |
|------|--------|
| Production workflow consistency | ✅ All active docs/scripts point to engineering-drawing V4; V2/V3 correctly marked void/historical. |
| Documentation consistency | ✅ CLI cheat sheet complete; `delivery-run` pipeline now documented. |
| CLI consistency | ✅ Every documented command exists; no stale subcommands; all skills reference valid commands. |
| Configuration consistency | ⚠️ `pyproject.toml` dep pins stale vs freeze (WARNING, documented); glossary path naming differs (WARNING, documented); no conflicting model names. |
| Agent instruction consistency | ✅ All 5 skills uphold no-renderer-self-authorization; no unauthorized publish path. |

## Issues found

### CRITICAL

| # | Issue | Location | Impact | Action |
|---|-------|----------|--------|--------|
| C1 | `overlay_pair.py:539,570` pass hardcoded `C:\Windows\Fonts\simhei.ttf` (`SIMHEI`) instead of `resolve_cjk_font()` | `overlay_pair.py` (active V4 render path via `dense_index`/`inline_plus_opaque`) | On Linux/Docker production, `insert_font` raises `FileNotFoundError` → render failure | **FIXED** — both lines now `resolve_cjk_font()`. |

### WARNING

| # | Issue | Location | Impact | Action |
|---|-------|----------|--------|--------|
| W1 | Root `README.md` has zero reference to the engineering-drawing V4 workflow | `README.md` | Agent/operator may not know the production system exists | Documented in `PRODUCTION_SOURCE_OF_TRUTH.md` pointer; no root README edit (consumer doc). |
| W2 | `pyproject.toml` pins `PyMuPDF==1.26.5`, `pikepdf==7.2.0`, `Pillow==10.4.0`; freeze records `1.27.2.3`/`10.6.0`/`11.0.0` | `pyproject.toml` | If production installs via pyproject pins, frozen hashes won't reproduce | Documented; production must install the frozen dependency set (runtime env). |
| W3 | Freeze glossary hashes point at `05_Glossary_TM`; delivery manifest uses `glossary_tm/` | `frozen-production-config.json`, delivery manifest | Different directory names; runtime resolves correctly but hashes are path-named | Documented; `validate-production` hash-verifies the manifest's `glossary_tm/`. |
| W4 | `hybrid_ocr.py:260,496,520-524` + `legacy_audit.py` contain sample-1310-specific keywords (`depoh`, `lori`, `setback`, `treatedwater`) in runtime OCR path | `hybrid_ocr.py`, `legacy_audit.py` | Overfits to sample 1310; other sites lose the forced-review path. **Not** in the frozen V4 render path (`run_v4`/plan packets use OCR only via the standalone `ocr` CLI) | ARCHIVE-documented; de-overfit deferred (would change OCR logic mid-freeze). |
| W5 | `panel_reflow.py:14` keeps `SIMHEI` deprecated alias (harmless — line 57 uses `resolve_cjk_font()`) | `panel_reflow.py` | No functional impact | KEEP; documented. |
| W6 | `frozen-production-config.json` not referenced in any .md | repo | No instruction on purpose/regeneration | `PRODUCTION_SOURCE_OF_TRUTH.md` now documents it. |

### ARCHIVE (historical, no production impact)

| # | Issue | Location | Action |
|---|-------|----------|--------|
| A1 | `build_v39_supervisor_manual_review_plans.py` — v3.9 terra plan builder, no importers (dead) | `devtools/` | ARCHIVE-marked; not moved (would break nothing but archived in manifest). |
| A2 | v3.x devtools: `run_verified_samples.py` (v3.11), `generate_v311_verified_plans.py`, `generate_terra_supervisor_plans_v36.py`, `run_terra_supervisor_full_v36.py`, `build_semantic_v3_samples.py`, `build_cross_domain_v33_samples.py`, `build_v311_*`, `build_v33_production_queue.py` | `devtools/` | ARCHIVE-marked (deprecated banners already present). |
| A3 | v4 one-off devtools: `build_v4_sample*.py`, `publish_v4_*.py`, `render_v4_directory_02_candidate.py`, `build_render_v4_directory_01.py`, `rebuild_v4_directory_01_paginated.py` | `devtools/` | ARCHIVE-marked (deprecated banners already present). |
| A4 | Tests referencing v3.x code: `test_verified_samples.py`, `test_v34_release_gate.py` | `devtools/tests/` | KEEP (still pass, test historical logic); ARCHIVE-documented. |
| A5 | `test_harness.py` tests deprecated V3 coverage gate | `devtools/tests/` | KEEP (valid unit tests for historical logic, not V4 gate). |
| A6 | Benchmark design spec declares `v2-block-semantic` test target | `docs/superpowers/specs/...benchmark-design.md` | ARCHIVE-documented (spec predates V4). |
| A7 | Benchmark plan uses `python -m services.engineering_drawing` (missing `.cli`) in illustrative code | `docs/superpowers/plans/...benchmark.md` | ARCHIVE (illustrative only). |
| A8 | `pyproject.toml` dep pins stale (see W2) | `pyproject.toml` | ARCHIVE-documented; production uses frozen runtime env. |

## Changes applied

1. **`overlay_pair.py:539,570`** — `SIMHEI` → `resolve_cjk_font()` (CRITICAL, 2 lines).
2. **`backend/scripts/services/engineering_drawing/AGENTS.md`** — added `delivery-run` production pipeline + command rows + pointer to `frozen-production-config.json` (WARNING gap).
3. **New**: `docs/audit/CONSISTENCY_AUDIT_REPORT.md`, `docs/audit/PRODUCTION_SOURCE_OF_TRUTH.md`, `docs/audit/ARCHIVE_MANIFEST.md`.

**No deletions, no moves, no frozen-workflow file modified, no production artifacts changed.**

## Production workflow status

**PASS** — after the font fix + doc update, the frozen `delivery-160-rc2` workflow is internally consistent. Tests: 668 → 668 (unchanged; the font fix is render-path-only and covered by the suite). CLI smoke on the real delivery-160 passes.
