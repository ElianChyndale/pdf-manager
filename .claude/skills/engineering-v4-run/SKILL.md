---
name: engineering-v4-run
description: Run a source engineering drawing PDF through the full V4 pipeline (supervisor_plan -> extraction_ledger -> render_contract -> rendered_candidate -> release_authorization) and publish into the formal directory only after explicit authorization. Use when asked to translate or produce a bilingual engineering drawing deliverable.
---

# engineering-v4-run

## Purpose
Drive one source PDF through the five immutable V4 stages via `run_v4.run_v4_flow`
and, with an approved supervisor review or human acceptance, publish the
candidate into `v4.0-readable-zone-complete`. This is the only legitimate
production path; never copy a candidate into the formal dir by hand.

## Prerequisites
- Source PDF + verified supervisor run bundle (`request.json`,
  `model-response.raw.json`, `normalized-plan.json`, `source-manifest.json`,
  `invocation-receipt.json`, `hashes.json`).
- An approved normalized plan JSON passing
  `supervisor_contract.validate_real_supervisor_plan`.
- Machine path: a supervisor final-review JSON bound to `candidate_sha256` /
  `plan_sha256` / `invocation_id`. Human path: an acceptance JSON with
  `accepted_by` + `accepted_at` (V4 spec §8).

## Exact commands
```bash
cd backend/scripts
python -m services.engineering_drawing.cli v4-run \
  --source "<source.pdf>" --run-id "<run_id>" \
  --bundle "<supervisor-bundle-dir>" --plan "<normalized-plan.json>" \
  --renderer inline_plus_opaque \
  --work-dir "<work_dir>" --candidate-dir "<candidate_dir>" \
  --formal-dir "<...>/translated/v4.0-readable-zone-complete" \
  --ocr-json "<ocr.json>" --review-json "<final-review.json>" \
  [--document-context "<context.json>"] \
  [--delivery-id "<delivery_id>"] [--delivery-meta "<meta.json>"]
```

Renderers: `inline_plus_opaque`, `dense_index`, `human_gate_rumah`.

## Inputs / Outputs
- Work dir: `stage1..5` JSON, `render-authorization.json`,
  `release-authorization.json`, `delivery-manifest.json`, `timing.json`,
  `visual-qa.json`, `page-*.png`.
- Formal dir: candidate PDF + `.release-authorization.json` +
  `.delivery-manifest.json`.

## Verification
```bash
python -m services.engineering_drawing.cli v4-run audit-formal --formal-dir "<formal-dir>"
python -m services.engineering_drawing.cli v4-run scorecard --work-root "<work_dir>"
```

## Do NOT
- Never publish without `authorize_release` / `authorize_human_release` routed
  through `publish_to_formal`. No renderer self-authorization.
- Never edit a stage JSON after it is written; re-run the stage.
- Never drop source lines or change a supervisor render_mode downstream.
- Never run without a bundle/plan that binds the exact source PDF SHA-256.
