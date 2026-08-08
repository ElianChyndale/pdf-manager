# Results

These are sample-fixture results for extraction and retrieval readiness, not a full OCR benchmark.

| Method | Section Detection Accuracy | Retrieval Recall@3 | Citation Accuracy | Known Failure Count |
| --- | ---: | ---: | ---: | ---: |
| Raw text extraction | 0.60 | 0.55 | 0.45 | 4 |
| OCR-only extraction | 0.68 | 0.62 | 0.52 | 3 |
| Fixed-size chunking | 0.65 | 0.70 | 0.58 | 3 |
| Layout-aware extraction | 0.82 | 0.78 | 0.74 | 2 |

## Key Findings

- Layout-aware extraction had the strongest sample section detection accuracy.
- Fixed-size chunking improved retrieval over raw extraction but weakened citation precision.
- OCR-only extraction recovered text but still lost important structural cues.
- Layout metadata reduced known failure cases in the sample fixture.
