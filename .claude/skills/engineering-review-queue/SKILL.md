---
name: engineering-review-queue
description: Generate a risk-ranked HTML review sheet with 4x zoom crops for a V4 candidate run, so a human can review the highest-risk translated regions first. Use when asked to produce a human review sheet or prioritize manual review of an engineering drawing run.
---

# engineering-review-queue

## Purpose
Turn a V4 candidate run's work-dir artifacts into a ranked review queue. Risk
factors: residual English, model-QA disagreement, low OCR confidence, unseen
terminology, microtext, rotated text, title-block/company zones, and
translation length growth. The sheet is a **static export** — it posts nowhere;
decisions must be recorded manually.

## Exact command
```bash
cd backend/scripts
python -m services.engineering_drawing.cli v4-run review-queue \
  --work-dir "<work_dir>" \
  [--candidate-pdf "<candidate.pdf>"] \
  [--translation-qa-json "<report.json>"] \
  [--glossary-csv "<05_Glossary_TM/engineering-glossary-v1.csv>"] \
  [--translation-memory-json "<05_Glossary_TM/translation-memory-v1.json>"] \
  [--output-dir "<output>"]
```

## Inputs / Outputs
- Inputs read from `--work-dir`: `stage4-rendered-candidate.json`,
  `inline-placement.json`, `visual-qa.json`, `page-*.png`.
- Outputs: `review-queue.json` (ranked), `review-queue.html` (decision sheet),
  `crops/page-*.png` (4× zoom crops).

## Verification
Open `review-queue.html` in a browser; confirm crops render and the banner
"Static export — this sheet posts nowhere" is visible.

## Do NOT
- Do not treat the queue as approval — it only prioritizes review.
- Do not modify the candidate or work dir while generating the queue.
- Do not submit data through the sheet (it has no backend).
