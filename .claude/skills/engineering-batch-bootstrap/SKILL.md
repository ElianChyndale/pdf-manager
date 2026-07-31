---
name: engineering-batch-bootstrap
description: Create original-PDF page packets for the single multimodal supervisor across a batch of source drawings, so a supervisor can later plan/translate each page. Use when asked to prepare a batch of engineering drawings for V4 production.
---

# engineering-batch-bootstrap

## Purpose
Freeze each source PDF into immutable per-page packets (page image + native
text + reference evidence + knowledge context) that the single `gpt-5.6-sol`
supervisor consumes to author plans. This stage **never** publishes anything.

## Exact command
```bash
cd backend/scripts
python -m services.engineering_drawing.cli agent-bootstrap \
  --root "<source_root>" --output-root "<...>/01_Bilingual_Inline/agent-artifacts" \
  [--dpi 144]
```

## Output
- `<artifact_root>/<slug>/page-<NNNN>/page-packet.json` + `page-<NNNN>-source.png`
- `<artifact_root>/agent-batch-index.json` (batch summary)

## Verification
Confirm each page packet carries the source PDF SHA-256 and a frozen page
image, and that `agent-batch-index.json` reports `awaiting_supervisor_plan`
counts matching the source set.

## Do NOT
- Never publish a PDF from page packets — packets are planning inputs only.
- Never run parallel multimodal supervisors over the same page.
- Never modify a page packet after it is written.
