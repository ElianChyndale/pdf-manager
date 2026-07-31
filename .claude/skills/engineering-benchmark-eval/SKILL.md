---
name: engineering-benchmark-eval
description: Evaluate a candidate engineering drawing pipeline against the frozen benchmark corpus with held-out validation discipline. Refuses to score heldout samples unless --use-heldout is passed. Use when asked to evaluate or compare translation pipeline versions.
---

# engineering-benchmark-eval

## Purpose
Run the benchmark evaluation (`benchmark-seed` → `benchmark-prelabel` →
`benchmark-adjudicate` → `benchmark-visual-review` → `benchmark-evaluate`) over
the frozen core corpus, honoring the dev/regression/validation/heldout split
manifest so the pipeline cannot silently tune against heldout samples.

## Held-out discipline
- `benchmark/split-manifest.json` (or a workspace-local copy) maps samples:
  regression = core-01..08, validation = core-09..10, heldout = core-11..12.
- `benchmark-evaluate` and the per-sample `benchmark-*` commands **refuse**
  (exit 3) when they would touch a heldout sample without `--use-heldout`.
- Pass `--use-heldout` only to explicitly run the heldout set.

## Exact commands
```bash
cd backend/scripts
# Inspect / write the split manifest
python -m services.engineering_drawing.cli benchmark-split --workspace "<workspace>" [--assign core-05=validation] [--force]

# Seed the workspace (once)
python -m services.engineering_drawing.cli benchmark-seed --source-root "<sources>" --workspace "<workspace>"

# Evaluate a candidate pipeline
python -m services.engineering_drawing.cli benchmark-evaluate \
  --workspace "<workspace>" --candidate-root "<candidate_root>" \
  [--baseline-report "<baseline.json>"] [--use-heldout]
```

## Output
`reports/benchmark-report.json` + `.html` with per-sample scores (5 dimensions,
max 100), `core_score`, `manual_review_rate`, `promotion_decision` when a
baseline is supplied. Exit code 2 on hard failures, 3 on heldout refusal.

## Do NOT
- Do not score heldout samples without `--use-heldout` (the discipline exists
  to prevent overfitting).
- Do not edit `core-set.v1.json` to add splits — its schema is closed; use the
  separate split manifest.
- Do not treat the core score as a deliverable gate — check hard failures and
  critical-error metrics too.
