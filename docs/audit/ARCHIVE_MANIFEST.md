# Archive Manifest — delivery-160-rc2

> Records all material classified as ARCHIVE during the production-consistency
> audit. **Archived items are historical reference only and are NOT part of the
> production workflow.** They are left in place (marked deprecated) rather than
> moved or deleted, so imports and historical evidence remain intact. For any
> item the replacement reference is the unified production path.

| # | Original path | Archive status | Reason | Date | Replacement reference |
|---|---------------|----------------|--------|------|-----------------------|
| A1 | `backend/scripts/devtools/build_v39_supervisor_manual_review_plans.py` | Marked DEPRECATED (in-place) | v3.9 terra plan builder; no importers (dead code) | 2026-08-02 | `run_v4.run_v4_flow` |
| A2 | `backend/scripts/devtools/run_verified_samples.py` (RUN_VERSION v3.11) | Marked DEPRECATED (in-place) | Historical v3.11 verified-samples runner | 2026-08-02 | `delivery-run` |
| A3 | `backend/scripts/devtools/generate_v311_verified_plans.py` | Marked DEPRECATED (in-place) | v3.11 plan generator | 2026-08-02 | `delivery-run export-plan-packets` |
| A4 | `backend/scripts/devtools/generate_terra_supervisor_plans_v36.py` | Marked DEPRECATED (in-place) | v3.6 terra plans | 2026-08-02 | `delivery-run export-plan-packets` |
| A5 | `backend/scripts/devtools/run_terra_supervisor_full_v36.py` | Marked DEPRECATED (in-place) | v3.6 terra runner | 2026-08-02 | `delivery-run start` |
| A6 | `backend/scripts/devtools/build_semantic_v3_samples.py` | Marked DEPRECATED (in-place) | v3.x sample builder | 2026-08-02 | `v4-run` |
| A7 | `backend/scripts/devtools/build_cross_domain_v33_samples.py` | Marked DEPRECATED (in-place) | v3.3 sample builder | 2026-08-02 | `v4-run` |
| A8 | `backend/scripts/devtools/build_v311_*.py`, `build_v33_production_queue.py` | Marked DEPRECATED (in-place) | v3.1x helpers | 2026-08-02 | `v4-run` |
| A9 | `backend/scripts/devtools/build_v4_sample{06..10}*.py`, `publish_v4_*.py`, `render_v4_directory_02_candidate.py`, `build_render_v4_directory_01.py`, `rebuild_v4_directory_01_paginated.py` | Marked DEPRECATED (in-place, banners present) | One-off v4 sample/publish scripts; must not write release auth or copy to formal dir | 2026-08-02 | `run_v4.run_v4_flow` + `publish_to_formal` |
| A10 | `backend/scripts/devtools/tests/engineering_drawing/test_verified_samples.py` | KEEP (tests pass) | Tests obsolete v3.11 sample set; harmless but historical | 2026-08-02 | n/a (historical coverage) |
| A11 | `backend/scripts/devtools/tests/engineering_drawing/test_v34_release_gate.py` | KEEP (tests pass) | Tests v3.3/v3.4 release-gate devtools functions | 2026-08-02 | n/a (historical coverage) |
| A12 | `backend/scripts/devtools/tests/engineering_drawing/test_harness.py` | KEEP (tests pass) | Tests deprecated V3 coverage gate; not the V4 gate | 2026-08-02 | `orchestration_harness.validate_handoff` |
| A13 | `docs/superpowers/specs/2026-07-28-engineering-drawing-benchmark-design.md` | ARCHIVE-documented (in place) | Declares `v2-block-semantic` benchmark target; predates V4 freeze | 2026-08-02 | `benchmark/` V4 implementation |
| A14 | `docs/superpowers/plans/2026-07-28-engineering-drawing-benchmark.md` | ARCHIVE-documented (in place) | Illustrative CLI uses `python -m services.engineering_drawing` (missing `.cli`); plan predates implementation | 2026-08-02 | `benchmark-*` CLI |
| A15 | `pyproject.toml` (dependency pins) | ARCHIVE-documented | Pins `PyMuPDF==1.26.5` etc., stale vs frozen runtime set | 2026-08-02 | `frozen-production-config.json` dependency_versions |

## Rules

- **Never use archived items for production execution.**
- **Never move/delete archived items without evidence** — they are left in place
  so imports and historical evidence remain intact.
- The single production source of truth is
  `frozen-production-config.json` + the delivery manifest + the runtime
  environment. See `PRODUCTION_SOURCE_OF_TRUTH.md`.
