# PDF Manager

<p align="center">
  <strong>Document-intelligence support infrastructure for EcoQuant Pro</strong>
</p>

PDF Manager is a standalone PDF retain-layout translation and toolkit project. In this portfolio, it is positioned as supporting infrastructure for EcoQuant Pro rather than as a fourth flagship project.

Used by EcoQuant Pro for OCR/layout-aware extraction and structured evidence generation.

## Public Readiness Summary

| Area | Summary |
| --- | --- |
| Problem | EcoQuant-style financial AI needs PDF-heavy ESG/RWA documents converted into structured evidence with layout context. |
| Method | PDF Manager provides OCR/layout-aware extraction, block metadata, chunking support, and PDF workflow utilities. |
| Evaluation | Research artifacts live under `research/results/`, with document-intelligence documentation under `docs/`. |
| Limitations | Public fixtures are small and synthetic; real benchmarks require public or user-owned documents with clear redistribution rights. |
| Application relevance | In this portfolio, PDF Manager supports EcoQuant Pro rather than acting as a fourth flagship project. |

## Features

### Document Intelligence Support
- **Layout-aware extraction** - OCR and document parsing patterns for PDF-heavy evidence workflows
- **Structured evidence generation** - page, section, and block metadata that can feed retrieval systems
- **Failure analysis** - notes on OCR/layout limits that help downstream systems report uncertainty
- **EcoQuant support path** - ESG/RWA reports can become evidence chunks for retrieval and citation checks

### Translation Pipeline
- **Layout-preserving translation** - OCR to LLM translation to Typst rendering, keeping formulas, tables, and page structure visible
- **Scanned/image PDF support** - Handles both editable and scanned PDFs
- **Inline formula rendering** - Complex math formulas are preserved and rendered in the output
- **Glossary support** - Customizable terminology tables for consistent translation
- **Side-by-side reader** - Compare source and translated pages with interactive region highlighting

### PDF Toolkit
- **Merge PDFs** — Concatenate multiple PDFs end-to-end
- **Split PDF** — Extract pages by range
- **Compress** — Reduce file size via image recompression
- **Rotate** — Rotate pages 90/180/270 degrees
- **Metadata editor** — View and edit title, author, subject, keywords
- **Encrypt/Decrypt** — AES-256 password protection

## Quick Start

### Desktop App
Download the latest release for your platform from [GitHub Releases](https://github.com/ElianChyndale/pdf-manager/releases).

### Docker
```bash
git clone https://github.com/ElianChyndale/pdf-manager.git
cd pdf-manager/docker/delivery
docker compose up -d
```
Open http://127.0.0.1:40001

### Development
```bash
# Frontend
cd frontend && npm run build

# Backend API
cd backend/rust_api && cargo build --release

# Start API
export RUST_API_PROJECT_ROOT=/path/to/pdf-manager
export RUST_API_KEYS="your-api-key"
./target/release/rust_api
```

## Secret Safety Before GitHub Push

```bash
# 1) Use templates only
cp .env.example .env

# 2) Enable repository git hooks (blocks secrets in commits)
git config core.hooksPath .githooks

# 3) If a secret file was tracked before, untrack it
git rm --cached docker/delivery/docker/app.env docker/delivery/docker/web.env docker/delivery/docker/auth.local.json
```

Never commit real values from `.env`, `docker/delivery/docker/*.env`, or `docker/delivery/docker/auth.local.json`.

## Architecture

```
Frontend (HTML/Tailwind/JS)  →  Rust API (Axum)  →  Python backend
                                                         → OCR (Paddle/MinerU)
                                                         → LLM Translation
                                                         → PDF Rendering (Typst/PyMuPDF)
```

## Portfolio Role

PDF Manager remains useful as a standalone repository, but the portfolio narrative treats it as EcoQuant support:

- EcoQuant Pro is the flagship financial AI system.
- PDF Manager provides OCR/layout-aware extraction and structured document evidence.
- AI Research Engineering Lab is the fourth flagship project.

## License

MIT License. See [LICENSE](LICENSE) for details.
