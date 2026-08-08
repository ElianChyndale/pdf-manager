# Reproducibility

## Backend

```bash
cd backend/rust_api
cargo build --release
cargo test
```

## Frontend

```bash
cd frontend
npm install
npm run build
```

## Document Schema Tests

```bash
python -m pytest backend/scripts/devtools/tests/document_schema
```

## Research Artifacts

- Report: `paper/report.md` and `paper/report.pdf`.
- Sample output: `examples/output_json/sample_extraction.json`.
- Evaluation notebooks: `notebooks/document_extraction_eval.ipynb` and `notebooks/chunking_eval.ipynb`.

Use public, synthetic, or user-owned PDFs only.
