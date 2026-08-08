# Dataset Card: PDF Manager Sample Documents

## Dataset Motivation

The sample dataset supports reproducible OCR, layout extraction, chunking, and retrieval-readiness evaluation.

## Data Source

The current committed sample is synthetic and stored in `examples/output_json/sample_extraction.json` plus result tables under `research/results/`.

Future public-data extensions should use public sustainability reports, annual reports, green bond frameworks, or public ESG disclosures only when redistribution rules are respected. If redistribution is unclear, users should place documents locally and commit only metadata, scripts, and derived non-restricted summaries.

## Data Composition

- One synthetic structured extraction example.
- One sample result table comparing extraction methods.
- Optional public or user-owned PDFs may be placed under `examples/input_pdfs/`.

## Preprocessing Steps

- Normalize blocks into document/page/block structures.
- Preserve page number, block type, section, text, and bounding box where available.
- Store result tables as CSV and summaries as JSON.

## Labeling Method

The sample extraction is manually authored for demonstration. Future benchmarks should use manually checked references.

## Known Biases

- Synthetic data is cleaner than real PDFs.
- Small sample size.
- Layout patterns do not cover all enterprise documents.
- OCR provider behavior is not fully represented.

## Recommended Uses

- Demonstrating the target structured output.
- Smoke testing evaluation reports.
- Explaining layout-aware chunking and citation readiness.

## Not Recommended Uses

- Training OCR models.
- Making accuracy claims for all PDFs.
- Processing copyrighted documents without permission.

## Limitations

The sample data is illustrative. Real evaluation requires public benchmark-like documents or carefully licensed internal data.

## Public-Data Extension Status

- Current state: synthetic fixture and local result summaries.
- Planned extension: public document benchmark for OCR/layout extraction and retrieval-readiness checks.
- Governance rule: do not commit copyrighted, restricted, private, or unclear-rights PDFs.
