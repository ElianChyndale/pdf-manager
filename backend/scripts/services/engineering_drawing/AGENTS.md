# Engineering Drawing Bilingual Translation — Agent Operating Manual

> This manual is written for an AI agent (Claude, Codex, …) working in this
> directory. It tells you what the system is, how the stages are organized, which
> command does which job, and the invariants you must never break.

## What this is

`services/engineering_drawing/` implements the **V4 engineering-drawing
bilingual translation production workflow**: a source engineering PDF is
zones/classified, every visible natural-language region is inventoried and
bound to a stable ID, translations + placements are designed by a single
multimodal supervisor, a deterministic renderer draws the Chinese, and a
release gate proves that nothing was omitted before the PDF may enter the
formal delivery directory.

The **sole normative spec** is [`WORKFLOW_SPEC_V4.md`](WORKFLOW_SPEC_V4.md)
(Chinese; renamed from `WORKFLOW_SPEC_V2_BLOCK.md`). It declares itself the only
valid production spec and voids all V2/V3.x semantics. The executable policy is
[`workflow_policy.py`](workflow_policy.py) (`WORKFLOW_VERSION =
"v4.0-readable-zone-complete"`).

Everything is driven from the CLI: `python -m services.engineering_drawing.cli
<subcommand>`. The top-level Python entrypoints under
`backend/scripts/entrypoints/` (`run_document_flow.py`, `run_translate_only.py`,
…) are for the general book/document pipeline, **not** this workflow.

## The 5-stage immutable state machine

Every production run goes through exactly these stages, in order, each
validated by `orchestration_harness.validate_handoff` before the next may run.
All stage payloads share one immutable run identity: `run_id`, `source_sha256`,
`workflow_version`, `policy_fingerprint`, and (when provided) `document_context`.

| # | Stage | Purpose | Immutable input | Validated output |
|---|-------|---------|-----------------|------------------|
| 1 | `supervisor_plan` | The single multimodal supervisor (`gpt-5.6-sol` / light) inspects the page image, partitions zones, inventories every text region, translates and designs placement. | verified supervisor run bundle + normalized plan | plan + blocks (render_mode per block) |
| 2 | `extraction_ledger` | OCR/native/reference evidence fills the supervisor's stable IDs. Cannot invent zones or downgrade prose to literal. | stage 1 + OCR evidence | ledger (closure = 1.0) |
| 3 | `render_contract` | Locks typography, masks, placement and render mode. | stage 2 + `authorize_render` | render authorization |
| 4 | `rendered_candidate` | Deterministic renderer draws the candidate; whole-page / per-zone / ink closure must be 1.0. | stage 3 | candidate PDF + placement audit + page images |
| 5 | `release_authorization` | Same-supervisor final review or explicit user acceptance, then `authorize_release` / `authorize_human_release`. | stage 4 + review | release authorization + formal publish |

The orchestrator is [`run_v4.py`](run_v4.py) (`run_v4_flow`). **Without a
review or human acceptance the run stops after stage 4 and never publishes.**

## Stage → tool/script mapping

| Stage | Code |
|-------|------|
| 1 | `supervisor_contract.validate_real_supervisor_plan`, `supervisor_bundle.verify_supervisor_run_bundle` |
| 2 | `post_ocr_supervision.build_post_ocr_supervision_package`, `legacy_transfer.extract_legacy_translation_regions` |
| 3 | `authorization.authorize_render`, `supervisor_contract.build_review_gate` |
| 4 | `overlay_pair.render_planned_opaque_blocks` / `render_opaque_translation_companion`, `services/rendering/output/engineering/bilingual.render_bilingual_inline_only`, `visual_qa.analyze_visual_qa` |
| 5 | `authorization.authorize_release` / `authorize_human_release`, `run_v4.publish_to_formal` |

## CLI cheat sheet

Run from `backend/scripts` as `python -m services.engineering_drawing.cli <cmd>`.

| Command | What it does |
|---------|--------------|
| `inventory` / `audit` / `all` | Scan a directory of bilingual drawings; build a manifest; audit coverage (optionally with screenshots). |
| `samples` | Build translated samples from an audit manifest (legacy sample builder). |
| `ocr` | Run hybrid OCR (Paddle + DeepSeek) on a PDF, optionally with a supervisor plan. |
| `harness` / `legacy-harness` | Historical V3.x full-coverage audit. Deprecated; V4 release authority is `v4-run`. |
| `legacy-transfer` | Extract legacy translation regions from an old translated PDF and render a bilingual inline PDF. |
| `v3-render` / `v3-overlay-render` | V3 compatibility renderers (inline or opaque directory index). Require a supervisor bundle. |
| `v3-supervisor-handoff` | Validate a V3 multimodal plan and emit OCR/translation handoff files. |
| `v3-post-ocr-supervision` | Build the image + OCR + knowledge package for the second supervisor pass. |
| `sol-review-package` | Export source + draft + placement audit as a Codex Sol review package. |
| `batch-translate` / `agent-bootstrap` | Create original-PDF page packets for the single multimodal supervisor. Never publishes without plans. |
| `benchmark-seed` | Freeze the core/challenge source pages into an isolated benchmark workspace. |
| `benchmark-prelabel` | Ask Sol for semantic blocks/translations/layout constraints for one sample. |
| `benchmark-adjudicate` | Apply human adjudication to a prelabel, optionally lock into gold. |
| `benchmark-visual-review` | Multimodal visual review of a candidate against the source. |
| `benchmark-evaluate` | Hard gates + weighted scoring + promotion. Exits 2 on hard failures, 3 on heldout without `--use-heldout`. |
| `benchmark-split` | Write/inspect the immutable dev/regression/validation/heldout split manifest. |
| `v4-run` | **Unified V4 orchestration**: run all five stages and publish via authorization. |
| `v4-run audit-formal` | Read-only compliance report of a formal dir (sidecar + delivery manifest). |
| `v4-run scorecard` | Aggregate per-run KPIs into a batch scorecard (JSON + HTML). |
| `v4-run review-queue` | Generate a risk-ranked HTML review sheet with 4× zoom crops. |

## Invariants — never break these

1. **No renderer self-authorization.** A candidate may enter
   `v4.0-readable-zone-complete` only through `publish_to_formal`, and only with
   an authorization produced by `authorize_release` (machine review) or
   `authorize_human_release` (spec §8 explicit user acceptance). Never hand-write
   a `.release-authorization.json` or copy a PDF into the formal dir.
2. **Single supervisor.** `gpt-5.6-sol` with `light` reasoning; parallel
   multimodal agents are forbidden. OCR/native text are evidence, not decisions.
3. **Closures = 1.0.** Whole-page, per-zone and rendered-ink closure must all be
   1.0 at stages 4–5.
4. **Exactly one render mode per translated block:** `preserve_source_blue_chinese`
   or `opaque_bilingual_reflow`. Modes never mix or weaken between stages.
5. **Directory masks** may only cover verified natural-language glyph unions —
   zero intersection with row-number/drawing-number/size columns and table
   rules, ≥ 1.5 pt clearance. Every source row number stays visible.
6. **Run identity is immutable.** `run_id`, `source_sha256`, `workflow_version`,
   `policy_fingerprint` (and `document_context` when set) must not drift between
   stages. Editing `workflow_policy.py` changes the policy fingerprint and
   invalidates in-flight handoffs.
7. **Typography hard minimums:** directory ≥ 6.8 pt (preferred 7.2), company ≥
   6.4 pt (preferred 6.8), drawing body ≥ 5.8 pt and ≥ 85% of source visual size.

## Which command for which job

- Produce one bilingual deliverable from a source PDF → `v4-run`.
- Verify a formal dir's release evidence → `v4-run audit-formal`.
- See batch-level quality numbers for a set of runs → `v4-run scorecard`.
- Rank the risky regions of a candidate for a human to review → `v4-run review-queue`.
- Build the benchmark and evaluate a candidate pipeline → `benchmark-seed` … `benchmark-evaluate`.
- Inspect/adjust which benchmark samples are dev/regression/validation/heldout → `benchmark-split`.
- Create supervisor page packets for a batch → `agent-bootstrap`.

## Pointers

- Spec: [`WORKFLOW_SPEC_V4.md`](WORKFLOW_SPEC_V4.md)
- Executable policy: [`workflow_policy.py`](workflow_policy.py)
- Harness: [`orchestration_harness.py`](orchestration_harness.py)
- Orchestrator: [`run_v4.py`](run_v4.py)
- Delivery manifest: [`delivery_manifest.py`](delivery_manifest.py)
- Scorecard: [`batch_scorecard.py`](batch_scorecard.py)
- Review queue: [`review_queue.py`](review_queue.py)
- Tests: `backend/scripts/devtools/tests/engineering_drawing/`
  (`python -m pytest devtools/tests/engineering_drawing -q`)
