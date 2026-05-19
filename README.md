# PDF Manager

<p align="center">
  <strong>PDF retain-layout translation & toolkit</strong>
</p>

PDF Manager is an all-in-one PDF tool that combines AI-powered layout-preserving translation with a built-in PDF toolbox. Translate PDFs while keeping the original formatting — and use the built-in tools to merge, split, compress, rotate, edit metadata, and encrypt PDFs.

## Features

### Translation Pipeline
- **Layout-preserving translation** — OCR → LLM translation → Typst rendering, keeping formulas, tables, and page structure intact
- **Scanned/image PDF support** — Handles both editable and scanned PDFs
- **Inline formula rendering** — Complex math formulas are preserved and rendered correctly
- **Glossary support** — Customizable terminology tables for consistent translation
- **Side-by-side reader** — Compare source and translated pages with interactive region highlighting

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

## Architecture

```
Frontend (HTML/Tailwind/JS)  →  Rust API (Axum)  →  Python backend
                                                         → OCR (Paddle/MinerU)
                                                         → LLM Translation
                                                         → PDF Rendering (Typst/PyMuPDF)
```

## Features

- **PDF Translation** — Retain-layout translation via OCR + LLM pipeline
- **PDF Toolkit** — Merge, split, compress, rotate, metadata editing, and encrypt/decrypt functionality

## License

MIT License. See [LICENSE](LICENSE) for details.
