# Evaluation

## Metrics

| Metric | Purpose |
| --- | --- |
| Character error rate | Measures OCR character accuracy. |
| Word error rate | Measures OCR word accuracy. |
| Table extraction accuracy | Measures whether table cells are preserved. |
| Section detection accuracy | Measures heading and section boundary quality. |
| Retrieval recall@k | Measures whether relevant chunks are retrieved. |
| Citation accuracy | Measures whether answer citations point to supporting chunks. |
| Processing latency | Measures runtime cost. |

## Commands

```bash
cd backend/rust_api
cargo test

cd ../../
python -m pytest backend/scripts/devtools/tests/document_schema
```

Run commands in an environment with the required OCR and rendering dependencies installed.
