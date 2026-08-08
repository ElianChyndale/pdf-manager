# Reproducibility Checklist

## Environment

- OS: Windows local development environment used for artifact generation.
- Python version: Python 3.11 recommended.
- Node version: use the version compatible with frontend lockfiles.
- Required API keys: not required for sample extraction output.
- Can run without private keys: Yes, for sample proof artifacts.

## Data

- Sample data included: Yes, `examples/output_json/sample_extraction.json` and `research/results/`.
- Data source explained: Yes, synthetic extraction sample.
- Dataset card included: Yes, `docs/dataset_card.md`.

## Experiments

- Baselines included: Yes.
- Metrics defined: Yes.
- Random seeds fixed: Not applicable to deterministic sample table.
- Expected outputs included: Yes.

## Code

- Quick start documented: Yes, `docs/reproducibility.md`.
- Tests pass: Not claimed unless run separately.
- Docker available: Yes, existing Docker delivery docs are present in the repo.
