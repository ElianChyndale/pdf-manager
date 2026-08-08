# Methodology

## Baselines

1. Raw PDF text extraction.
2. OCR-only extraction.
3. Fixed-size chunking.

## Proposed Method

Layout-aware extraction preserves page number, block type, reading order, section title, table metadata, and bounding-region context where available. Metadata-aware chunking uses this structure to create retrieval units.

## Evaluation Protocol

1. Select public or synthetic sample PDFs.
2. Produce raw text, OCR-only, fixed chunk, and layout-aware outputs.
3. Compare extraction quality against manually checked references.
4. Evaluate retrieval recall and citation accuracy on fixed questions.
5. Record failure cases in `docs/error_analysis.md`.
