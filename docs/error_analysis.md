# Error Analysis

## Failure Categories

- OCR recognition error.
- Table boundary loss.
- Column reading-order mistake.
- Header or footer contamination.
- Section detection error.
- Formula preservation error.
- Chunk boundary breaks citation.
- Provider-specific output mismatch.

## Reporting Format

| Case ID | Failure Type | Document | Page | Expected | Actual | Fix Candidate |
| --- | --- | --- | ---: | --- | --- | --- |
| PM-001 | Column order | sample.pdf | 1 | left column before right column | to be recorded | improve layout ordering |
