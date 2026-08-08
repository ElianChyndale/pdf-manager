# Failure Cases And Negative Results

## Failure Case 1: Column Order Mistake

Multi-column pages can be read in the wrong order, which breaks downstream chunk meaning.

## Failure Case 2: Table Boundary Loss

Tables may be flattened into paragraphs, losing row and column relationships.

## Failure Case 3: Header And Footer Contamination

Repeated headers or footers can pollute retrieval chunks and cause irrelevant citations.

## Failure Case 4: Formula Handling Error

Mathematical notation may be extracted as broken text or omitted by OCR.

## Failure Case 5: Citation Boundary Error

A chunk can contain the answer plus unrelated neighboring text, making the citation less precise.
