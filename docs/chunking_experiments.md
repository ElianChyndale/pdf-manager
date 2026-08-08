# Chunking Experiments

## Baselines

- Fixed-size chunking.
- OCR-only chunks.
- Raw text chunks.

## Proposed Strategy

Metadata-aware chunking groups text by document structure: page, section, heading, block type, and table boundaries.

## Retrieval Evaluation

Ask fixed questions whose supporting evidence is known. Measure retrieval recall@k and citation accuracy for each chunking strategy.
