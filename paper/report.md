# Layout-Aware Document Intelligence for Citation-Grounded Retrieval from Financial PDFs

## Abstract

PDF Manager is a document intelligence toolkit for OCR, layout preservation, PDF operations, and structured extraction. This report adds a deterministic document-intelligence benchmark with 24 synthetic financial-document pages and 40 retrieval questions. It compares raw extraction, OCR-only extraction, layout-aware extraction, and layout-aware extraction with metadata to evaluate extraction quality, downstream retrieval, citation accuracy, and failure taxonomy coverage.

## 1. Introduction

Enterprise and financial AI systems often begin with messy PDFs. If extraction loses sections, tables, page references, or reading order, downstream RAG systems become less trustworthy. PDF Manager’s benchmark measures not only extraction quality, but also downstream retrieval and citation impact.

## 2. Problem Statement

- RQ1: How does layout-aware extraction compare with raw and OCR-only extraction?
- RQ2: Does metadata-aware chunking improve downstream retrieval and citation behavior?
- RQ3: Which document-processing failures are most important for financial PDFs?

## 3. Research Contribution

This project contributes a layout-aware document processing benchmark that evaluates how extraction quality affects downstream retrieval and citation-grounded QA in financial documents.

## 4. Methodology

The benchmark generates 24 deterministic synthetic financial-document pages and 40 retrieval questions. It compares raw text extraction, OCR-only extraction, layout-aware extraction, and layout-aware + metadata chunking. Metrics include word error rate, table extraction accuracy, section detection accuracy, retrieval recall@5, MRR, citation accuracy, citation faithfulness, latency, and failure taxonomy coverage.

## 5. Results

Generated outputs:

- `research/results/extraction_quality.csv`
- `research/results/retrieval_benchmark.csv`
- `research/results/citation_accuracy.csv`
- `research/results/failure_taxonomy.csv`

Extraction quality:

| Method | WER | Table Accuracy | Section Accuracy | Latency/Page |
| --- | ---: | ---: | ---: | ---: |
| Raw text | 0.122 | 1.000 | 0.000 | 12.0 ms |
| OCR-only | 0.014 | 0.917 | 1.000 | 19.0 ms |
| Layout-aware | 0.000 | 1.000 | 1.000 | 26.0 ms |
| Layout-aware + metadata | 0.000 | 1.000 | 1.000 | 33.0 ms |

Retrieval and citation:

| Method | Recall@5 | MRR | Citation Accuracy | Citation Faithfulness |
| --- | ---: | ---: | ---: | ---: |
| Raw text | 0.775 | 0.557 | 0.350 | 0.350 |
| OCR-only | 1.000 | 1.000 | 1.000 | 1.000 |
| Layout-aware | 1.000 | 1.000 | 1.000 | 1.000 |
| Layout-aware + metadata | 1.000 | 1.000 | 1.000 | 1.000 |

The failure taxonomy includes table boundary failure, two-column reading order failure, OCR numeric error, lost footnote, incorrect page citation, and merged section heading.

## 6. Key Findings

- Raw extraction lost section structure in this benchmark, producing 0.000 section detection accuracy and weak citation accuracy.
- OCR-only recovered text but introduced numeric/table risk, with table accuracy of 0.917.
- Layout-aware methods preserved section and table structure in the deterministic benchmark.
- Metadata-aware extraction increased latency in the fixture but provides the clearest audit trail for downstream RAG.

## 7. Error Analysis

The most important failure classes are table boundary failure, two-column reading order failure, OCR numeric error, lost footnote, incorrect page citation, and merged section heading.

## 8. Limitations

The current benchmark uses synthetic pages. It is a reproducible harness and metric demonstration, not a full OCR benchmark. A stronger evaluation should use redistributable annual reports, sustainability reports, bond factsheets, tables, and scanned pages.

## 9. Future Work

Future work includes public PDF fixtures, table-specific scoring, layout-aware retrieval ablations, and direct use of extracted chunks in EcoQuant’s KG-RAG pipeline.

## 10. References

References are listed in `references.bib`.
