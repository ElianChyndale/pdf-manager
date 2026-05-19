# PDF Manager — AGENTS.md

## Project Overview

PDF Manager is a PDF retain-layout translation and toolkit application. It extracts text via OCR, translates it via LLM, renders it back into the PDF while preserving the original layout — and includes a built-in PDF toolbox (merge, split, compress, rotate, metadata, encrypt/decrypt).

## Build / Test / Lint Commands

```bash
# Frontend
cd frontend && npm run build              # Tailwind CSS build
cd frontend && npm run smoke:status       # Frontend smoke test

# Desktop (Electron)
cd desktop && npm run prepare-app         # Prep frontend + backend for packaging
cd desktop && npm run dist:win32          # Build Windows portable
cd desktop && npm run dist:win32-installer # Build Windows installer

# Python backend (scripts/)
cd backend/scripts && python -m pytest <path>   # Run tests
cd backend/scripts && python -m services.rendering.workflow.render_only <args>

# Docker
cd docker/delivery && docker compose up -d
```

## Architecture Layers

```
frontend/  →  Rust API (Axum)  →  Python backend (pipeline orchestration)
                                        → OCR (MinerU / Paddle)
                                        → LLM Translation (DeepSeek)
                                        → PDF Rendering (Typst / PyMuPDF / pikepdf)
```

## PDF Functions Reference

### Frontend (JavaScript)

| Function | File | Library | Description |
|----------|------|---------|-------------|
| PDF display & reader | [frontend/src/js/reader-pdf.js](frontend/src/js/reader-pdf.js) | pdfjs-dist 4.8.69 | Side-by-side source/translated PDF canvas rendering with synced scrolling |
| PDF page count | [frontend/src/js/main-helpers.js](frontend/src/js/main-helpers.js) | pdfjs-dist | `countPdfPages()` — count pages in uploaded file |
| Merge side-by-side PDF | [frontend/src/js/features/reader-dialog/controller.js](frontend/src/js/features/reader-dialog/controller.js) | pdf-lib 1.17.1 | `buildMergedComparePdf()` — merge source + translated PDFs page-by-page into single side-by-side PDF |
| Upload with page range | [frontend/src/js/features/upload/controller.js](frontend/src/js/features/upload/controller.js) | — | File upload with page range selection dialog |
| Reader initialization | [frontend/src/js/reader.js](frontend/src/js/reader.js) | — | Loads both PDFs, mounts viewers, binds region overlays |
| API calls | [frontend/src/js/network.js](frontend/src/js/network.js) | — | All PDF upload/download API calls |

### Backend Python — PDF Rendering Pipeline

#### Document Operations
| Function | File | Description |
|----------|------|-------------|
| `save_optimized_pdf()` | [backend/scripts/services/rendering/document/pdf_ops.py](backend/scripts/services/rendering/document/pdf_ops.py) | Save PDF with font subsetting, GC, deflate compression, object streams |
| `save_fast_pdf()` | Same file | Simple no-optimization save |
| `strip_page_links()` | Same file | Remove hyperlinks from PDF pages |
| `extract_pages_with_pikepdf()` | [backend/scripts/services/rendering/document/pikepdf_pages.py](backend/scripts/services/rendering/document/pikepdf_pages.py) | Extract page range from source PDF into new PDF |
| `optimize_pdf_file_with_pikepdf()` | Same file | Re-save PDF with pikepdf compression |
| `copy_pdf_with_pikepdf()` | Same file | Copy PDF through pikepdf with recompression |
| `extract_single_page_pdf()` | [backend/scripts/services/rendering/source/document_ops.py](backend/scripts/services/rendering/source/document_ops.py) | Extract single page as PDF |
| `page_word_count()` | Same file | Count words on a PDF page |
| `page_has_editable_text()` | Same file | Check if page has selectable text |
| `copy_toc()` | [backend/scripts/services/rendering/document/metadata.py](backend/scripts/services/rendering/document/metadata.py) | Copy TOC from source to target PDF with page offset |
| `copy_toc_for_page_map()` | Same file | Remap TOC using RenderPageMap for reordered pages |

#### Overlay & Redaction
| Function | File | Description |
|----------|------|-------------|
| `overlay_pdf_pages_with_pikepdf()` | [backend/scripts/services/rendering/document/pikepdf_overlay.py](backend/scripts/services/rendering/document/pikepdf_overlay.py) | Overlay one PDF onto another page-by-page |
| `overlay_page_pdfs_with_pikepdf()` | Same file | Per-page overlay variant |
| `redact_source_text_areas()` | [backend/scripts/services/rendering/source/redaction.py](backend/scripts/services/rendering/source/redaction.py) | Redact translated text areas from source PDF. Dispatch to: standard, cover-only, visual-cover, text-extraction strategies |

#### Image Extraction & Compression
| Function | File | Description |
|----------|------|-------------|
| `extract_image_rgb()` | [backend/scripts/services/rendering/source/background/extract.py](backend/scripts/services/rendering/source/background/extract.py) | Extract images by xref, return PIL Image |
| `extract_raw_stream_image()` | Same file | Read raw compressed stream, decode via PIL |
| `raw_stream_image_meta()` | Same file | Read PDF image metadata (Filter, Width, Height, ColorSpace, etc.) |
| `image_prefers_solid_fill()` | Same file | Check if image is bitonal/image-mask/JBIG2/CCITT |
| `compress_pdf_images_only_impl()` | [backend/scripts/services/rendering/source/compression/image_pipeline.py](backend/scripts/services/rendering/source/compression/image_pipeline.py) | Recompress all PDF images to JPEG at target DPI, replace in-place via pikepdf |
| `encode_image()` | [backend/scripts/services/rendering/source/compression/image_ops.py](backend/scripts/services/rendering/source/compression/image_ops.py) | JPEG encode RGB/Grayscale/CMYK images |
| `encode_soft_mask()` | Same file | Flate-encode soft mask |
| `resize_to_target()` | Same file | Resize image to target dimensions |

#### Page Analysis & Classification
| Function | File | Description |
|----------|------|-------------|
| `classify_render_page()` | [backend/scripts/services/rendering/analysis/classifier.py](backend/scripts/services/rendering/analysis/classifier.py) | Classify page into kind (text, image, scan, mixed) with route assignment |
| `build_render_page_profile()` | Same file | Build profile: vector graphics, text layer, images, geometry, rotation |
| `is_editable_pdf()` | Same file | Sample pages to detect editable vs scanned PDF |
| `source_pdf_has_vector_graphics()` | Same file | Detect vector graphics presence |

#### Text Preparation & Cleanup
| Module | File | Description |
|--------|------|-------------|
| Hidden text stripping | [backend/scripts/services/rendering/source/preparation/hidden_text_strip.py](backend/scripts/services/rendering/source/preparation/hidden_text_strip.py) | Remove invisible/overlay text via pikepdf + fitz |
| BBox text stripping | [backend/scripts/services/rendering/source/preparation/bbox_text_strip_*.py](backend/scripts/services/rendering/source/preparation/bbox_text_strip_*.py) | Geometry-based text removal engine |
| Text redaction (standard) | [backend/scripts/services/rendering/source/cleanup/standard_execution.py](backend/scripts/services/rendering/source/cleanup/standard_execution.py) | Standard redaction strategy |
| Text redaction (cover-only) | [backend/scripts/services/rendering/source/cleanup/cover_only.py](backend/scripts/services/rendering/source/cleanup/cover_only.py) | Cover-only redaction strategy |
| Text redaction (visual) | [backend/scripts/services/rendering/source/cleanup/visual_cover.py](backend/scripts/services/rendering/source/cleanup/visual_cover.py) | Visual-aware cover redaction |
| Vector cleanup | [backend/scripts/services/rendering/source/cleanup/vector_cleanup.py](backend/scripts/services/rendering/source/cleanup/vector_cleanup.py) | Clean up vector graphics artifacts |
| Math intrusion | [backend/scripts/services/rendering/source/cleanup/math_intrusion.py](backend/scripts/services/rendering/source/cleanup/math_intrusion.py) | Handle math formula overlap with text |

#### Rendering Modes
| Mode | File | Description |
|------|------|-------------|
| `typst` | [backend/scripts/services/rendering/output/typst/](backend/scripts/services/rendering/output/typst/) | Render translated text via Typst on cleaned PDF background |
| `typst_visual` | Same | Typst render with visual-aware cover redaction for scanned PDFs |
| `overlay` | [backend/scripts/services/rendering/document/pikepdf_overlay.py](backend/scripts/services/rendering/document/pikepdf_overlay.py) | Place translated text as overlay on source PDF |
| `dual` | [backend/scripts/services/rendering/workflow/modes.py](backend/scripts/services/rendering/workflow/modes.py) | Source + translated side-by-side PDF output |
| `auto` | Same | Auto-detect best mode based on PDF analysis |

### Rust API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/uploads` | Upload PDF file |
| `POST /api/v1/ocr/jobs` | Create OCR job from uploaded PDF |
| `POST /api/v1/jobs` | Create full pipeline job (OCR + translate + render) |
| `GET /api/v1/jobs/:id/pdf` | Download translated PDF |
| `GET /api/v1/jobs/:id/cover` | Download cover image |
| `GET /api/v1/jobs/:id/thumbnail` | Download thumbnail |
| `GET /api/v1/jobs/:id/preview/pages/:page` | Download page preview image |
| `GET /api/v1/jobs/:id/download` | Download full job bundle |
| `GET /api/v1/jobs/:id/markdown` | Download markdown export |
| `GET /api/v1/jobs/:id/reader/regions` | Get reader region data |
| `GET /api/v1/jobs/:id/reader/metadata` | Get reader page metadata |
| `GET /api/v1/library/books` | List completed books |
| `DELETE /api/v1/library/books/:id` | Delete a book |

### Key Libraries

| Library | Layer | Usage |
|---------|-------|-------|
| PyMuPDF (fitz) 1.26.5 | Backend Python | Primary PDF I/O: read, write, text extraction, image extraction, optimization |
| pikepdf 7.2.0 | Backend Python | Low-level PDF structure: page extraction, overlay, image replacement, compression |
| Pillow 10.4.0 | Backend Python | Image decode/encode/recompress |
| Typst (external binary) | Backend Render | Typesetting translated text onto cleaned PDF backgrounds |
| pdfjs-dist 4.8.69 | Frontend | PDF canvas rendering in reader |
| pdf-lib 1.17.1 | Frontend | Side-by-side merged PDF generation |

## Pipeline Flow (High-Level)

```
Source PDF → Upload → OCR (MinerU/Paddle) → Normalize → Translate (LLM)
  → Render (auto/typst/overlay/dual) → Translated PDF + artifacts
```

### Full Rendering Pipeline Detail

```
Source PDF
  │
  ├── Render Mode Selection (auto → typst / overlay / dual / typst_visual)
  │     auto detects based on: editability, vector graphics, removable text ratio
  │
  ├── Page Classification & Profiling
  │     Text layer analysis, vector graphics detection, background coverage,
  │     image detection, rotation, geometry, drawing count
  │
  ├── Typst Background Mode (typst / typst_visual)
  │   │
  │   ├── 1. Copy source PDF → working PDF (via pikepdf)
  │   ├── 2. Build RenderPageSpecs (layout blocks + payload preparation)
  │   ├── 3. Build Clean Background PDF
  │   │     ├── Collect valid translated items (skip items w/o translated text)
  │   │     ├── Protect formula regions from redaction
  │   │     ├── Classify redaction route per page (auto/standard/visual_cover/...)
  │   │     ├── For each page:
  │   │     │   ├── Text matching (3 tiers):
  │   │     │   │   ├── Tier 1: Safe direct redaction (IoU ≥ 0.8, single span)
  │   │     │   │   ├── Tier 2: Text block matching (requires source_text)
  │   │     │   │   └── Tier 3: Word-level matching (requires source_text)
  │   │     │   ├── Ownership test (center-point inside item bbox)
  │   │     │   ├── Decide: text removal vs visual cover
  │   │     │   │   ├── Text removal: PyMuPDF redact (removes content stream)
  │   │     │   │   └── Visual cover: draw filled rect over text (masks only)
  │   │     │   └── Handle edge cases: formulas, vectors, images, margins
  │   │     └── Output: cleaned background PDF (original text removed/covered)
  │   │
  │   ├── 4. Prepare Translated Pages (indent detection, bbox adjustment)
  │   ├── 5. Compile Typst Pages (typeset translated text atop cleaned backgrounds)
  │   ├── 6. Resilient Compile (sanitize + retry on failure)
  │   └── 7. Merge Background + Typst Output → Final PDF
  │
  ├── Overlay Mode (overlay)
  │   ├── 1. Open source PDF as base doc
  │   ├── 2. Classify redaction strategy per page
  │   ├── 3. For each page:
  │   │     ├── Text matching → removable rects
  │   │     ├── Redact source text from page
  │   │     └── Compile Typst overlay page (translated text only)
  │   ├── 4. Overlay translated pages onto source doc (via pikepdf / fitz)
  │   ├── 5. Image compression pass (optional)
  │   └── 6. Save optimized PDF
  │
  ├── Dual Mode (dual)
  │   ├── 1. Run overlay pipeline on translated copy
  │   ├── 2. Build dual pages: source left + translated right side-by-side
  │   ├── 3. Copy TOC with page offset (dual doubles page count)
  │   └── 4. Save optimized PDF
  │
  └── Final Post-Processing
        ├── Image recompression (compress images to target DPI via JPEG)
        ├── Font subsetting + garbage collection + object streams
        └── Output PDF

```

### English Text Residue — Root Causes

If the translated PDF contains leftover original English text (一行一行的英文残留), the issue originates in the **Text Redaction / Cleanup** stage. Known root causes:

| Priority | Root Cause | Details | Key File(s) |
|----------|-----------|---------|-------------|
| **HIGH** | Items without translated text are skipped entirely | If the translation pipeline failed for some items, `iter_valid_translated_items()` drops them. Their English text is never touched. | `items.py:28` |
| **HIGH** | Visual cover leaves text layer intact | Many code paths (formula neighbors, continuation groups, render blocks, vector-heavy pages) use visual covers instead of text removal. Covers are rectangles drawn *over* the text — the original text still exists in the content stream beneath. Any rendering discrepancy exposes it. | `visual_cover_execution.py`, `cleanup_policy.py` |
| **HIGH** | Text matching requires `source_text` | Block and word matching both return empty rects when `source_text` is missing. The item falls back to cover-only (or is skipped). | `text_matching.py:41-42` |
| **MEDIUM** | Ownership center-point test misses partial overlaps | Text whose geometric center falls just outside the item bbox is excluded, even if most of it overlaps. Caused by coordinate mismatches between OCR output and PDF content stream. | `text_ownership.py:45-53` |
| **MEDIUM** | Word overlap threshold not met | Ligatures, hyphenation, encoding differences, or tokenization mismatches between source text and PDF-extracted words can cause the overlap check to fail. | `text_matching.py:101-113` |
| **MEDIUM** | Safe direct redaction is too strict | Requires IoU ≥ 0.8, size error ≤ 5%, exactly 1 matching span — any failure cascades to slower paths that may also fail. | `text_safe_direct.py:62-71` |
| **MEDIUM** | Text in scanned/image PDFs is unredactable | Text rasterized into image pixels cannot be removed by `PDF_REDACT_TEXT_REMOVE`. The visual cover approach only masks it. | `image_page.py` |
| **LOW** | Items with `render_block` / `continuation_group` are always cover-only | These items' text layer is never removed (by design for layout preservation). | `auto.py:30-33` |

**How to diagnose:** Check the render diagnostics output for per-page stats: `raw_removable_rects`, `merged_removable_rects`, `cover_rects`, `fast_page_cover_pages`, `legacy_pymupdf_redaction_pages`. Compare with the item count to see how many items fell through to cover-only or were skipped entirely.

## Key Directories

```
frontend/                           Browser UI + Electron shell
  src/js/reader-pdf.js              Core PDF viewer with regions
  vendor/pdfjs-dist/                Vendored PDF.js 4.8.69
  vendor/pdf-lib/                   Vendored pdf-lib 1.17.1

backend/
  rust_api/                         Axum HTTP server
  scripts/
    services/rendering/             PDF rendering pipeline
      analysis/                     Page classification & profiling
      document/                     Low-level PDF ops (PyMuPDF + pikepdf)
      layout/                       Typst layout specs & payload
      output/typst/                 Typst PDF generation
      source/                       Source PDF processing (extract, cleanup, compress, prepare)
      workflow/                     Render orchestration & modes
    services/ocr_provider/          OCR provider integration
    services/translation/           LLM translation
    runtime/pipeline/               Pipeline orchestration
    entrypoints/                    CLI entry points
```

## Planned / Roadmap PDF Functions

These functions are not yet implemented but are natural extensions for the project. Each lists the suggested approach and target layer.

### PDF Merge (端到端拼接)

Merge multiple PDF files into a single PDF by concatenating pages end-to-end (not side-by-side). The output PDF appends all pages from file1, then all pages from file2, etc.

| Aspect | Detail |
|--------|--------|
| **Target layer** | Backend Python (new service module: `backend/scripts/services/merge/`) |
| **Core algorithm** | `pikepdf.Pdf.new()` → for each input PDF → `output.pages.extend(input.pages)`. PyMuPDF `Document.insert_pdf()` is also viable but pikepdf handles duplicate object IDs across files better. |
| **Frontend** | New multi-file upload UI with drag-and-drop reorder. Progress bar during merge. Download single merged result. |
| **Rust API** | `POST /api/v1/merge` — accept list of `{ upload_id, page_range? }` objects, return merged PDF. `GET /api/v1/merge/:job_id/status` for long merges. |
| **Pipeline integration** | Allow merging translated PDFs from multiple jobs, or merging several source PDFs before submitting a single translation job. |

**Quality considerations for clean output (no English residue):**
- Each input PDF should be independently optimized before merging (font subsetting, object stream compression)
- When merging translated PDFs, verify that text redaction/cleanup was already applied at the individual PDF level (not post-merge)
- Post-merge compression pass: `compress_pdf_images_only_impl()` on the final merged result to normalize image quality
- Mixed-source TOC handling: collect TOC from each input, rebuild unified TOC with accumulated page offsets
- Mixed page sizes: each page retains its original dimensions; no resizing/scaling
- Orientation mismatch: portrait + landscape pages in the same document are allowed (PDF spec)
- If any input PDF is encrypted, decrypt first. If any has form fields / annotations, flatten them before merge to avoid object ID conflicts.

**Suggested architecture:**
```
backend/scripts/services/merge/
  __init__.py
  merger.py          # Core merge logic (pikepdf)
  toc_merge.py       # TOC remapping across multiple source PDFs
  preflight.py       # Validate inputs (not encrypted, not damaged)
  postprocess.py     # Compression pass, font subsetting, metadata rewrite
```

### PDF Split

Split a PDF into separate files by page range (e.g., "pages 1-10", "pages 11-20").

| Aspect | Detail |
|--------|--------|
| **Backend** | Reuse `extract_pages_with_pikepdf()` from [pikepdf_pages.py](backend/scripts/services/rendering/document/pikepdf_pages.py). Accept page range expressions like `"1-10,15-20"`. |
| **Frontend** | Page range input UI with preview. Batch download or individual downloads. |
| **Rust API** | `POST /api/v1/split` — accept upload_id + list of `{ start, end, label? }` ranges, return list of split PDFs. |
| **Edge cases** | Overlapping ranges, out-of-bounds pages, splitting on page boundaries (preserve TOC). |

### PDF Watermark

Stamp text or image watermark across all or selected pages.

| Aspect | Detail |
|--------|--------|
| **Backend** | Reuse `overlay_pdf_pages_with_pikepdf()` from [pikepdf_overlay.py](backend/scripts/services/rendering/document/pikepdf_overlay.py). Generate a single-page watermark PDF, overlay onto each page. |
| **Options** | Text watermark (content, font, size, color, opacity, rotation, position) or image watermark (image path, scale, position, opacity). |
| **Frontend** | Watermark configuration dialog: text input, font selector, opacity slider, position picker, preview. |
| **Rust API** | `POST /api/v1/watermark` — accept upload_id + watermark config JSON. |
| **Note** | Watermark should be applied AFTER translation (not before), otherwise OCR might pick up the watermark as text. |

### PDF Encryption / Decrypt

Add password protection and permissions to a PDF, or remove password protection.

| Aspect | Detail |
|--------|--------|
| **Backend** | PyMuPDF: `pdf.save(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=..., user_pw=..., perms=...)`. Decrypt: `fitz.open(filepath) → doc.authenticate(password)`. |
| **Permission flags** | Print, modify, copy, annotate, fill forms, accessibility, assemble, print high-res. |
| **Frontend** | Password input with strength indicator. Permission checkboxes. Separate owner/user password fields. |
| **Rust API** | `POST /api/v1/encrypt` / `POST /api/v1/decrypt`. |

### PDF Meta Editor

Edit PDF metadata (title, author, subject, keywords).

| Aspect | Detail |
|--------|--------|
| **Backend** | PyMuPDF: `pdf.metadata["title"] = new_title`. Metadata dict keys: title, author, subject, keywords, creator, producer. |
| **Frontend** | Simple form with text fields. Show current metadata on load. |
| **Rust API** | `GET /api/v1/metadata/:upload_id` (read), `PUT /api/v1/metadata/:upload_id` (update). |

### PDF Page Reorder

Drag-and-drop page reordering before merge or export.

| Aspect | Detail |
|--------|--------|
| **Backend** | pikepdf: `output.pages.extend([pdf.pages[i] for i in new_order])`. PyMuPDF: `pdf.select(new_page_indices_list)`. |
| **Frontend** | Thumbnail grid with drag-and-drop reorder. Show page number overlay. |
| **Rust API** | `POST /api/v1/reorder` — accept upload_id + ordered list of page indices. |
| **Integration** | Useful as a pre-processing step before translation (reorder pages, then submit the reordered PDF for OCR/translation). |

### PDF to Images

Render PDF pages as PNG/JPEG images at specified DPI.

| Aspect | Detail |
|--------|--------|
| **Backend** | PyMuPDF: `page.get_pixmap(dpi=300) → pixmap.tobytes("png")`. Partial foundation exists in `devtools/word_export/backgrounds.py`. |
| **Options** | Page range, DPI (72/150/300/600), format (PNG/JPEG), color space (RGB/Grayscale). |
| **Frontend** | Page range selection, DPI selector, download as ZIP. |
| **Rust API** | `POST /api/v1/export/images` — return ZIP of rendered pages. |
| **Use case** | Preview pages without a PDF viewer, feed pages to external tools, create thumbnails. |

### Images to PDF

Create a PDF from a list of image files (one page per image).

| Aspect | Detail |
|--------|--------|
| **Backend** | PyMuPDF: `doc.new_page(width, height) → page.insert_image(rect, stream=image_bytes)`. Pillow to read input images. |
| **Options** | Page size (auto-detect from image dimensions, or force A4/Letter), fit mode (fit/fill/stretch), JPEG compression quality. |
| **Frontend** | Multi-file upload with drag-and-drop reorder. Preview thumbnails. |
| **Rust API** | `POST /api/v1/export/pdf-from-images` — upload images, return PDF. |

### PDF Page Numbering

Insert page numbers into PDF pages (position, font, format configurable).

| Aspect | Detail |
|--------|--------|
| **Backend** | PyMuPDF: `page.insert_text(point, "1", fontsize=10, fontname="helv")`. Or insert as overlay via pikepdf for better font support. |
| **Options** | Position (bottom-center, bottom-right, top-center, etc.), format ("1", "Page 1 of N", "1/10"), start number, font, size, color, skip first page. |
| **Frontend** | Preview overlay showing page number position. Config panel with position presets. |
| **Rust API** | `POST /api/v1/page-numbers` — accept upload_id + numbering config. |
| **Note** | Apply AFTER rendering (or watermark) so page numbers don't interfere with translation. |

### PDF Rotation

Rotate individual pages 0/90/180/270 degrees.

| Aspect | Detail |
|--------|--------|
| **Backend** | PyMuPDF: `page.set_rotation(90)`. pikepdf: `page.Rotate = 90`. |
| **Options** | Apply to all pages, page range, or per-page. Clockwise/counter-clockwise. |
| **Frontend** | Thumbnail grid with rotation controls per page. Batch rotate option. |
| **Rust API** | `POST /api/v1/rotate` — accept upload_id + `{ pages: "*" | [1,3,5], degrees: 90 }`. |
| **Use case** | Fix scanned PDFs with wrong orientation before OCR. |

### PDF Crop

Crop pages to specified bounding box — useful for trimming scanned PDF margins.

| Aspect | Detail |
|--------|--------|
| **Backend** | PyMuPDF: `page.set_cropbox(fitz.Rect(left, top, right, bottom))`. |
| **Options** | Predefined crops (2mm margin trim, title-only, content-only), custom rect input, same crop for all pages or per-page. |
| **Frontend** | Visual crop tool on page thumbnail (drag handles). Preset buttons (trim 5% each side, etc.). |
| **Rust API** | `POST /api/v1/crop` — accept upload_id + crop rect (or per-page rects). |
| **Note** | Crop before OCR to remove scan borders, binder margins, page numbers that shouldn't be translated. |

### PDF Compress (Standalone)

Expose existing image recompression as a standalone endpoint, not just embedded in the rendering pipeline.

| Aspect | Detail |
|--------|--------|
| **Backend** | Reuse `compress_pdf_images_only_impl()` from [image_pipeline.py](backend/scripts/services/rendering/source/compression/image_pipeline.py). Recompress all images to JPEG at target DPI. |
| **Options** | Target DPI (72/96/150/200/300), quality (1-100), skip images smaller than threshold. |
| **Frontend** | DPI selector with size estimate preview. Show before/after file size. |
| **Rust API** | `POST /api/v1/compress` — accept upload_id + DPI/quality params. |
| **Use case** | Reduce translated PDF file size for sharing or storage. |

### PDF Digital Signature

Draw a signature image/name onto a specific page location.

| Aspect | Detail |
|--------|--------|
| **Backend** | PyMuPDF: insert signature image onto page via `page.insert_image()` or draw signature text via `page.insert_text()`. For PKCS#7 digital signatures, use a library like `endesive` or `pypdf2` (requires research). |
| **Frontend** | Signature pad (mouse/touch drawing) or image upload + positioning on page preview. |
| **Tiers** | **Basic**: overlay signature image onto page (visual only). **Advanced**: PKCS#7 digital signature with certificate (cryptographic verification). |
| **Rust API** | `POST /api/v1/sign` — upload signature image + position + page number. |

### PDF Annotations

Highlight, underline, sticky-note annotations on PDF pages, saved into the file.

| Aspect | Detail |
|--------|--------|
| **Backend** | PyMuPDF: `page.add_highlight_annot(rect)`, `page.add_underline_annot(rect)`, `page.add_text_annot(point, "note")`. |
| **Options** | Annotation type (highlight/underline/strikethrough/note/freetext), color, opacity, author, date. |
| **Frontend** | Reader integration: text selection → context menu → "Highlight" / "Add Note". |
| **Rust API** | `POST /api/v1/annotations` — add annotations; `GET /api/v1/annotations/:upload_id` — list; `DELETE /api/v1/annotations/:id` — remove. |
| **Use case** | Highlight important passages in translated PDF, add review notes. |

### PDF Diff / Compare

Side-by-side visual diff of two PDFs (page count, text content, image changes).

| Aspect | Detail |
|--------|--------|
| **Backend** | PyMuPDF: extract text per page via `page.get_text("text")`, compare line-by-line. For visual diff: render both pages to images `page.get_pixmap()`, compute pixel difference. |
| **Options** | Text-only diff (fast), visual diff (slow but catches layout/image changes). |
| **Frontend** | Split viewer with diff highlighting (red for removed, green for added). Page-level match/mismatch overview. |
| **Rust API** | `POST /api/v1/diff` — accept two upload_ids, return diff report JSON + overlay PNGs. |
| **Use case** | Compare source vs translated PDF to verify nothing was lost; compare two translation runs to evaluate quality. |

### PDF Batch Processing

Run any operation (compress, watermark, encrypt, etc.) across multiple PDFs in one request.

| Aspect | Detail |
|--------|--------|
| **Backend** | New orchestrator: accept a manifest of {input_id, operations[]}, iterate sequentially. |
| **Frontend** | Batch operation queue with progress per file. |
| **Rust API** | `POST /api/v1/batch` — accept manifest + operation sequence, return batch job ID with per-file status. |
| **Use case** | Apply same watermark + compression + encryption to a folder of translated PDFs before distribution. |

## Development Notes

- Python 3.11 only (see pyproject.toml)
- External binary required: `typst`
- All four render modes should be tested when modifying rendering code
- Image compression pipeline uses JPEG encoding — target DPI is configurable
- TOC remapping must account for page offset when pages are reordered
- The Rust API spec is documented in [backend/rust_api/API_SPEC.md](backend/rust_api/API_SPEC.md)
- Architecture decisions are in [doc/adr/](doc/adr/)
