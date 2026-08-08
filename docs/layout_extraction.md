# Layout Extraction

## Goal

Preserve document structure such as sections, tables, reading order, and page references.

## Structured Block Schema

```json
{
  "document_id": "sample",
  "page": 1,
  "block_id": "p1-b3",
  "block_type": "paragraph",
  "section": "Risk Factors",
  "text": "Example extracted text.",
  "bbox": [72, 120, 510, 170]
}
```

## Evaluation

Compare predicted sections, table cells, and reading order against manually checked references.
