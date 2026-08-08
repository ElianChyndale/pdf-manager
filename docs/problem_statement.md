# Problem Statement

PDF Manager studies how OCR, layout-aware extraction, and structured output can make PDF-heavy workflows more searchable and auditable.

The problem is that raw PDF text often loses document structure, while OCR can introduce recognition errors. For downstream retrieval and citation-grounded QA, the system must preserve text, tables, sections, page references, and layout metadata.

## Research Questions

- How accurately can text, tables, and sections be extracted?
- Does layout-aware extraction improve retrieval compared with plain extraction?
- What are the main OCR and layout failure modes?
