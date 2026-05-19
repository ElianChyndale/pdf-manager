# PDF 工具箱 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase 1 of the PDF Tools feature — 6 core utilities (Merge, Split, Compress, Rotate, Meta Editor, Encrypt/Decrypt) integrated into the existing PDF Manager single-page app.

**Architecture:** Add a "PDF 工具箱" panel below the existing upload/workflow area on index.html. Each tool opens a slide-over panel. Backend processing runs in Python (reusing existing PyMuPDF/pikepdf utilities). Rust API provides proxy endpoints. Results stored temporarily and auto-cleaned after 1 hour.

**Tech Stack:** Frontend: vanilla JS modules + Tailwind CSS. Backend: Rust Axum (routes) + Python 3.11 (processing with fitz/pikepdf).

---

## File Structure

### New Files to Create

```
backend/scripts/services/pdf_tools/
  __init__.py
  merger.py              # Merge multiple PDFs (pikepdf)
  splitter.py            # Split PDF by page range (pikepdf)
  compressor.py          # Compress PDF images (reuse image_pipeline)
  rotator.py             # Rotate PDF pages (PyMuPDF)
  metadata_editor.py     # Read/write PDF metadata (PyMuPDF)
  encryptor.py           # Encrypt/decrypt PDF (PyMuPDF)
  result_store.py        # Temp result file management (1hr cleanup)

backend/rust_api/src/routes/
  pdf_tools.rs           # All /api/v1/pdf-tools/* endpoints

frontend/src/js/features/pdf-tools/
  controller.js          # Main controller: mount toolbox panel, dispatch tools
  panels.js              # Slide-over panel builder (reusable)
  api.js                 # API calls for all tools
  panel-merge.js         # Merge tool: multi-upload, drag-reorder, execute, download
  panel-split.js         # Split tool: upload, range input, execute, download
  panel-compress.js      # Compress tool: upload, DPI slider, execute, download
  panel-rotate.js        # Rotate tool: upload, angle/range select, execute, download
  panel-metadata.js      # Meta tool: upload, show/edit fields, save
  panel-encrypt.js       # Encrypt tool: upload, password/permissions, execute, download
```

### Existing Files to Modify

```
backend/rust_api/src/routes/mod.rs          # add pub mod pdf_tools
backend/rust_api/src/app/router.rs          # register new routes
backend/rust_api/src/models.rs              # add PdfToolResultView model (if needed)

frontend/index.html                         # add toolbox HTML section after workflow area
frontend/src/js/main.js                     # import and mount pdf-tools feature
frontend/src/js/network.js                  # add API client calls (if not in pdf-tools/api.js)
```

---

## Task 1: Backend Python — Result Store

**Files:**
- Create: `backend/scripts/services/pdf_tools/__init__.py`
- Create: `backend/scripts/services/pdf_tools/result_store.py`

A simple temp file manager that stores tool results with auto-cleanup.

- [ ] **Step 1: Create `__init__.py`**

```python
# __init__.py
```

- [ ] **Step 2: Create `result_store.py`**

```python
import os
import time
import threading
from pathlib import Path


_RESULTS_DIR: Path | None = None
_LOCK = threading.Lock()
_CLEANUP_INTERVAL = 3600  # 1 hour
_TTL_SECONDS = 3600


def init_result_store(base_dir: str | Path) -> None:
    global _RESULTS_DIR
    _RESULTS_DIR = Path(base_dir) / "pdf-tools-results"
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _start_cleanup_worker()


def store_result(file_name: str, data: bytes) -> str:
    result_id = f"{int(time.time())}_{os.urandom(4).hex()}"
    result_dir = _RESULTS_DIR / result_id
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / file_name).write_bytes(data)
    (result_dir / ".meta").write_text(
        f"file_name={file_name}\ncreated_at={time.time()}\n"
    )
    return result_id


def get_result(result_id: str) -> tuple[str, bytes] | None:
    result_dir = _RESULTS_DIR / result_id
    if not result_dir.exists():
        return None
    meta_text = (result_dir / ".meta").read_text()
    file_name = ""
    for line in meta_text.strip().splitlines():
        if line.startswith("file_name="):
            file_name = line.split("=", 1)[1]
            break
    data = (result_dir / file_name).read_bytes()
    return file_name, data


def _cleanup_expired() -> None:
    now = time.time()
    if not _RESULTS_DIR or not _RESULTS_DIR.exists():
        return
    for entry in _RESULTS_DIR.iterdir():
        if not entry.is_dir():
            continue
        meta_path = entry / ".meta"
        if not meta_path.exists():
            continue
        for line in meta_path.read_text().strip().splitlines():
            if line.startswith("created_at="):
                created = float(line.split("=", 1)[1])
                if now - created > _TTL_SECONDS:
                    import shutil
                    shutil.rmtree(entry, ignore_errors=True)
                break


def _start_cleanup_worker() -> None:
    def _worker():
        while True:
            time.sleep(_CLEANUP_INTERVAL)
            try:
                _cleanup_expired()
            except Exception:
                pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
```

---

## Task 2: Backend Python — Merge PDFs

**Files:**
- Create: `backend/scripts/services/pdf_tools/merger.py`

**Test:**
- After creation, run: `python -c "from services.pdf_tools.merger import merge_pdfs; print('ok')"`

- [ ] **Step 1: Implement merger.py**

```python
import pikepdf
from pathlib import Path


def merge_pdfs(input_paths: list[Path], output_path: Path) -> dict:
    """
    Merge multiple PDFs end-to-end. Returns {page_count, file_size, file_name}.
    """
    total_pages = 0
    with pikepdf.Pdf.new() as pdf:
        for input_path in input_paths:
            with pikepdf.Pdf.open(input_path) as src:
                pdf.pages.extend(src.pages)
                total_pages += len(src.pages)
        pdf.save(output_path, compress_streams=True)

    return {
        "page_count": total_pages,
        "file_size": output_path.stat().st_size,
        "file_name": output_path.name,
    }


def merge_pdfs_with_metadata(input_paths: list[Path], output_path: Path, toc_entries: list[dict] | None = None) -> dict:
    """
    Merge with optional TOC remapping.
    toc_entries: [{"title": "Ch1", "page": 1, "file_index": 0}, ...]
    """
    result = merge_pdfs(input_paths, output_path)
    if toc_entries:
        import fitz
        doc = fitz.open(output_path)
        toc = []
        for entry in toc_entries:
            toc.append([1, entry["title"], entry["page"]])
        doc.set_toc(toc)
        doc.save(output_path, incremental=False, deflate=True, garbage=4)
        doc.close()
        result["toc_count"] = len(toc)
    return result
```

---

## Task 3: Backend Python — Split PDF

**Files:**
- Create: `backend/scripts/services/pdf_tools/splitter.py`

- [ ] **Step 1: Implement splitter.py**

```python
from pathlib import Path
import pikepdf


def split_pdf(input_path: Path, ranges: list[dict], output_dir: Path) -> list[dict]:
    """
    Split PDF by page ranges.
    ranges: [{"start": 1, "end": 10, "label": "part1"}, ...]
    Returns list of {file_name, page_count, file_size, label}
    """
    results = []
    with pikepdf.Pdf.open(input_path) as pdf:
        total_pages = len(pdf.pages)
        for i, rng in enumerate(ranges):
            start = max(1, int(rng.get("start", 1)))
            end = min(total_pages, int(rng.get("end", total_pages)))
            label = rng.get("label", f"part-{i + 1}")
            out_name = f"{Path(input_path).stem}-{label}.pdf"
            out_path = output_dir / out_name

            with pikepdf.Pdf.new() as out:
                for page_idx in range(start - 1, end):
                    out.pages.append(pdf.pages[page_idx])
                out.save(out_path)

            results.append({
                "file_name": out_name,
                "page_count": end - start + 1,
                "file_size": out_path.stat().st_size,
                "label": label,
            })
    return results
```

---

## Task 4: Backend Python — Compress PDF

**Files:**
- Create: `backend/scripts/services/pdf_tools/compressor.py`

- [ ] **Step 1: Implement compressor.py**

```python
import shutil
from pathlib import Path
from services.rendering.source.compression.image_pipeline import compress_pdf_images_only_impl


def compress_pdf(input_path: Path, output_path: Path, dpi: int = 150) -> dict:
    """
    Compress PDF images to target DPI. Returns {original_size, compressed_size, page_count}.
    """
    original_size = input_path.stat().st_size
    compress_pdf_images_only_impl(input_path, output_path, dpi=dpi)
    compressed_size = output_path.stat().st_size

    import fitz
    doc = fitz.open(output_path)
    page_count = len(doc)
    doc.close()

    return {
        "original_size": original_size,
        "compressed_size": compressed_size,
        "saved_bytes": original_size - compressed_size,
        "page_count": page_count,
    }
```

---

## Task 5: Backend Python — Rotate PDF

**Files:**
- Create: `backend/scripts/services/pdf_tools/rotator.py`

- [ ] **Step 1: Implement rotator.py**

```python
from pathlib import Path
import fitz


def rotate_pdf(input_path: Path, output_path: Path, degrees: int = 90, pages: str = "all") -> dict:
    """
    Rotate PDF pages.
    degrees: 0, 90, 180, 270 (clockwise)
    pages: "all" or comma-separated 1-based indices like "1,3,5"
    """
    doc = fitz.open(input_path)
    total = len(doc)

    target_indices = list(range(total))
    if pages != "all":
        target_indices = [int(p.strip()) - 1 for p in pages.split(",") if p.strip().isdigit()]
        target_indices = [i for i in target_indices if 0 <= i < total]

    for i in target_indices:
        current = doc[i].rotation or 0
        doc[i].set_rotation((current + degrees) % 360)

    doc.save(output_path, deflate=True, garbage=4)
    doc.close()

    return {
        "rotated_pages": len(target_indices),
        "total_pages": total,
    }
```

---

## Task 6: Backend Python — Metadata Editor

**Files:**
- Create: `backend/scripts/services/pdf_tools/metadata_editor.py`

- [ ] **Step 1: Implement metadata_editor.py**

```python
from pathlib import Path
import fitz


ALL_META_KEYS = ["title", "author", "subject", "keywords", "creator", "producer"]


def read_metadata(input_path: Path) -> dict:
    """Read PDF metadata. Returns dict with available fields."""
    doc = fitz.open(input_path)
    meta = doc.metadata or {}
    doc.close()
    return {k: meta.get(k, "") for k in ALL_META_KEYS}


def write_metadata(input_path: Path, output_path: Path, updates: dict) -> dict:
    """Update PDF metadata fields. Only non-empty values are applied."""
    doc = fitz.open(input_path)
    meta = doc.metadata or {}
    for k in ALL_META_KEYS:
        if k in updates and updates[k]:
            meta[k] = str(updates[k])
    doc.set_metadata(meta)
    doc.save(output_path, deflate=True, garbage=4)
    doc.close()
    return {"updated_fields": [k for k in updates if k in ALL_META_KEYS and updates[k]]}
```

---

## Task 7: Backend Python — Encrypt/Decrypt PDF

**Files:**
- Create: `backend/scripts/services/pdf_tools/encryptor.py`

- [ ] **Step 1: Implement encryptor.py**

```python
from pathlib import Path
import fitz


def encrypt_pdf(input_path: Path, output_path: Path, user_pw: str = "", owner_pw: str = "", permissions: int = -1) -> dict:
    """
    Encrypt PDF with AES-256.
    permissions: -1 = all allowed, or bitwise OR of fitz.PDF_PERM_* flags.
    """
    doc = fitz.open(input_path)
    encrypt_kw = {
        "encryption": fitz.PDF_ENCRYPT_AES_256,
        "owner_pw": owner_pw or user_pw or "default",
        "permissions": permissions,
    }
    if user_pw:
        encrypt_kw["user_pw"] = user_pw
    doc.save(output_path, **encrypt_kw)
    doc.close()
    return {"encrypted": True, "has_user_pw": bool(user_pw)}


def decrypt_pdf(input_path: Path, output_path: Path, password: str = "") -> dict:
    """Decrypt password-protected PDF."""
    doc = fitz.open(input_path)
    if doc.is_encrypted:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("Incorrect password")
    doc.save(output_path, deflate=True, garbage=4)
    doc.close()
    return {"decrypted": True}


def is_encrypted(input_path: Path) -> bool:
    """Check if PDF is encrypted."""
    doc = fitz.open(input_path)
    encrypted = doc.is_encrypted
    doc.close()
    return encrypted
```

---

## Task 8: Rust API — Add pdf_tools route module

**Files:**
- Create: `backend/rust_api/src/routes/pdf_tools.rs`
- Modify: `backend/rust_api/src/routes/mod.rs`

- [ ] **Step 1: Add `pub mod pdf_tools` to mod.rs**

Edit `backend/rust_api/src/routes/mod.rs`:
```rust
pub mod pdf_tools;
```

- [ ] **Step 2: Create core route structure in pdf_tools.rs**

```rust
use axum::extract::State;
use axum::Json;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Arc;

use crate::error::AppError;
use crate::models::ApiResponse;
use crate::AppState;

// ── Models ──

#[derive(Deserialize)]
pub struct MergeRequest {
    pub upload_ids: Vec<String>,
}

#[derive(Deserialize)]
pub struct SplitRequest {
    pub upload_id: String,
    pub ranges: Vec<SplitRange>,
}

#[derive(Deserialize)]
pub struct SplitRange {
    pub start: u32,
    pub end: u32,
    #[serde(default)]
    pub label: String,
}

#[derive(Deserialize)]
pub struct CompressRequest {
    pub upload_id: String,
    #[serde(default = "default_dpi")]
    pub dpi: u32,
}

fn default_dpi() -> u32 { 150 }

#[derive(Deserialize)]
pub struct RotateRequest {
    pub upload_id: String,
    #[serde(default = "default_degrees")]
    pub degrees: u32,
    #[serde(default = "default_pages")]
    pub pages: String,
}

fn default_degrees() -> u32 { 90 }
fn default_pages() -> String { "all".to_string() }

#[derive(Deserialize)]
pub struct MetadataRequest {
    pub upload_id: String,
    pub title: Option<String>,
    pub author: Option<String>,
    pub subject: Option<String>,
    pub keywords: Option<String>,
}

#[derive(Deserialize)]
pub struct EncryptRequest {
    pub upload_id: String,
    pub user_password: Option<String>,
    pub owner_password: Option<String>,
}

#[derive(Deserialize)]
pub struct DecryptRequest {
    pub upload_id: String,
    pub password: String,
}

#[derive(Serialize)]
pub struct PdfToolResult {
    pub download_url: String,
    pub file_name: String,
    pub file_size: u64,
    pub page_count: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<serde_json::Value>,
}

#[derive(Serialize)]
pub struct MetadataView {
    pub title: String,
    pub author: String,
    pub subject: String,
    pub keywords: String,
    pub creator: String,
    pub producer: String,
}

// ── Handlers ──

pub async fn merge_pdfs(
    State(state): State<AppState>,
    Json(req): Json<MergeRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    // TODO: implement
    Err(AppError::not_implemented("merge"))
}

pub async fn split_pdf(
    State(state): State<AppState>,
    Json(req): Json<SplitRequest>,
) -> Result<Json<ApiResponse<Vec<PdfToolResult>>>, AppError> {
    Err(AppError::not_implemented("split"))
}

pub async fn compress_pdf(
    State(state): State<AppState>,
    Json(req): Json<CompressRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    Err(AppError::not_implemented("compress"))
}

pub async fn rotate_pdf(
    State(state): State<AppState>,
    Json(req): Json<RotateRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    Err(AppError::not_implemented("rotate"))
}

pub async fn get_metadata(
    State(state): State<AppState>,
    Json(req): Json<MetadataRequest>,
) -> Result<Json<ApiResponse<MetadataView>>, AppError> {
    Err(AppError::not_implemented("get_metadata"))
}

pub async fn update_metadata(
    State(state): State<AppState>,
    Json(req): Json<MetadataRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    Err(AppError::not_implemented("update_metadata"))
}

pub async fn encrypt_pdf(
    State(state): State<AppState>,
    Json(req): Json<EncryptRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    Err(AppError::not_implemented("encrypt"))
}

pub async fn decrypt_pdf(
    State(state): State<AppState>,
    Json(req): Json<DecryptRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    Err(AppError::not_implemented("decrypt"))
}
```

- [ ] **Step 3: Add `not_implemented` helper to error.rs** (if not present)

Check `backend/rust_api/src/error.rs` for existing error constructors. Add if missing:

```rust
// In error.rs
impl AppError {
    // ... existing constructors ...

    pub fn not_implemented(feature: &str) -> Self {
        AppError::bad_request(format!("PDF tool '{feature}' not yet implemented"))
    }
}
```

---

## Task 9: Rust API — Register routes in router.rs

**Files:**
- Modify: `backend/rust_api/src/app/router.rs`

- [ ] **Step 1: Add `use` import and route registrations**

In `router.rs`, find the router builder and add after existing routes:

```rust
use crate::routes::pdf_tools;

// Inside the route builder, after library routes:
        .route("/api/v1/pdf-tools/merge", post(pdf_tools::merge_pdfs))
        .route("/api/v1/pdf-tools/split", post(pdf_tools::split_pdf))
        .route("/api/v1/pdf-tools/compress", post(pdf_tools::compress_pdf))
        .route("/api/v1/pdf-tools/rotate", post(pdf_tools::rotate_pdf))
        .route("/api/v1/pdf-tools/metadata", get(pdf_tools::get_metadata).put(pdf_tools::update_metadata))
        .route("/api/v1/pdf-tools/encrypt", post(pdf_tools::encrypt_pdf))
        .route("/api/v1/pdf-tools/decrypt", post(pdf_tools::decrypt_pdf))
        .route("/api/v1/pdf-tools/result/{result_id}", get(pdf_tools::download_result))
```

- [ ] **Step 2: Add `download_result` handler to pdf_tools.rs**

```rust
use axum::extract::Path;
use axum::body::Body;
use axum::response::Response;

pub async fn download_result(
    State(state): State<AppState>,
    Path(result_id): Path<String>,
) -> Result<Response<Body>, AppError> {
    // TODO: lookup result from result_store and stream file
    Err(AppError::not_implemented("download_result"))
}
```

---

## Task 10: Rust API — Implement merge handler with Python bridge

**Files:**
- Modify: `backend/rust_api/src/routes/pdf_tools.rs`

- [ ] **Step 1: Implement full merge handler**

```rust
use std::path::PathBuf;
use crate::services::upload_api::find_upload_path;

pub async fn merge_pdfs(
    State(state): State<AppState>,
    Json(req): Json<MergeRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    if req.upload_ids.is_empty() {
        return Err(AppError::bad_request("At least one upload_id is required"));
    }
    if req.upload_ids.len() < 2 {
        return Err(AppError::bad_request("At least two PDFs are required to merge"));
    }

    // Collect upload file paths
    let uploads_dir = &state.config.uploads_dir;
    let mut input_paths: Vec<PathBuf> = Vec::new();
    for upload_id in &req.upload_ids {
        let path = find_upload_path(uploads_dir, upload_id)
            .ok_or_else(|| AppError::bad_request(format!("Upload not found: {upload_id}")))?;
        input_paths.push(path);
    }

    // Call Python merge script
    let python_bin = &state.config.python_bin;
    let result = run_python_pdf_tool(python_bin, "merger", &[
        "--inputs", &input_paths.iter().map(|p| p.to_string_lossy().to_string()).collect::<Vec<_>>().join(","),
    ]).await?;

    // Parse result and return
    // ...
    Err(AppError::not_implemented("merge - python bridge"))
}
```

Note: The Python bridge pattern follows the existing `worker_command` infra. Check `backend/rust_api/src/worker_command/` for the established pattern of calling Python from Rust.

---

## Task 11: Frontend — PDF Tools Panel Component

**Files:**
- Create: `frontend/src/js/features/pdf-tools/panels.js`
- Create: `frontend/src/js/features/pdf-tools/api.js`

- [ ] **Step 1: Create reusable slide-over panel builder**

Create `frontend/src/js/features/pdf-tools/panels.js`:

```javascript
import { $ } from "../../dom.js";

export function openSlidePanel({ title, contentHtml, onClose }) {
  const overlay = document.createElement("div");
  overlay.className = "slide-overlay";
  overlay.innerHTML = `
    <div class="slide-panel">
      <div class="slide-panel-header">
        <h3>${title}</h3>
        <button class="slide-panel-close" aria-label="关闭">&times;</button>
      </div>
      <div class="slide-panel-body">${contentHtml}</div>
    </div>
  `;

  const close = () => {
    overlay.classList.remove("active");
    setTimeout(() => overlay.remove(), 300);
    onClose?.();
  };

  overlay.querySelector(".slide-panel-close").onclick = close;
  overlay.onclick = (e) => { if (e.target === overlay) close(); };
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("active"));
  return { overlay, close };
}

export function showProgress(container, percent, text) {
  const bar = container.querySelector(".progress-bar") || (() => {
    const div = document.createElement("div");
    div.className = "progress-bar-container";
    div.innerHTML = '<div class="progress-bar"><span class="progress-fill"></span><span class="progress-text">0%</span></div>';
    container.appendChild(div);
    return div.querySelector(".progress-bar");
  })();
  bar.querySelector(".progress-fill").style.width = `${percent}%`;
  bar.querySelector(".progress-text").textContent = `${percent}% ${text || ""}`;
}
```

- [ ] **Step 2: Create API client module**

Create `frontend/src/js/features/pdf-tools/api.js`:

```javascript
import { apiBase, buildApiHeaders } from "../../config.js";

async function postTool(action, payload) {
  const url = `${apiBase}/api/v1/pdf-tools/${action}`;
  const res = await fetch(url, {
    method: "POST",
    headers: buildApiHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(err.message || `请求失败: ${res.status}`);
  }
  return res.json();
}

async function getTool(action, payload) {
  const url = `${apiBase}/api/v1/pdf-tools/${action}`;
  const res = await fetch(url, {
    method: "GET",
    headers: buildApiHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(err.message || `请求失败: ${res.status}`);
  }
  return res.json();
}

export async function mergePdfs(uploadIds) {
  return postTool("merge", { upload_ids: uploadIds });
}

export async function splitPdf(uploadId, ranges) {
  return postTool("split", { upload_id: uploadId, ranges });
}

export async function compressPdf(uploadId, dpi = 150) {
  return postTool("compress", { upload_id: uploadId, dpi });
}

export async function rotatePdf(uploadId, degrees = 90, pages = "all") {
  return postTool("rotate", { upload_id: uploadId, degrees, pages });
}

export async function getMetadata(uploadId) {
  return getTool("metadata", { upload_id: uploadId });
}

export async function updateMetadata(uploadId, fields) {
  return postTool("metadata", { upload_id: uploadId, ...fields });
}

export async function encryptPdf(uploadId, userPassword, ownerPassword) {
  return postTool("encrypt", { upload_id: uploadId, user_password: userPassword, owner_password: ownerPassword });
}

export async function decryptPdf(uploadId, password) {
  return postTool("decrypt", { upload_id: uploadId, password });
}

export function getResultDownloadUrl(resultId, fileName) {
  return `${apiBase}/api/v1/pdf-tools/result/${resultId}`;
}
```

---

## Task 12: Frontend — Tool Panels (Merge, Split, Compress)

**Files:**
- Create: `frontend/src/js/features/pdf-tools/panel-merge.js`
- Create: `frontend/src/js/features/pdf-tools/panel-split.js`
- Create: `frontend/src/js/features/pdf-tools/panel-compress.js`

- [ ] **Step 1: Create merge panel**

```javascript
import { openSlidePanel } from "./panels.js";
import { mergePdfs, getResultDownloadUrl } from "./api.js";

export function openMergePanel(uploadFeature) {
  const panel = openSlidePanel({
    title: "合并 PDF",
    contentHtml: `
      <p class="slide-panel-desc">选择多个 PDF 文件，按顺序合并为一个文件。</p>
      <div class="slide-upload-area">
        <input type="file" accept=".pdf" multiple id="merge-file-input" />
        <div id="merge-file-list" class="slide-file-list"></div>
      </div>
      <button id="merge-execute-btn" class="button-link primary disabled" disabled>合并</button>
      <div id="merge-result" class="slide-result"></div>
    `,
  });

  const fileInput = panel.overlay.querySelector("#merge-file-input");
  const fileList = panel.overlay.querySelector("#merge-file-list");
  const execBtn = panel.overlay.querySelector("#merge-execute-btn");
  const resultDiv = panel.overlay.querySelector("#merge-result");
  const files = [];

  fileInput.onchange = () => {
    fileList.innerHTML = "";
    files.length = 0;
    for (const f of fileInput.files) {
      files.push(f);
      const item = document.createElement("div");
      item.className = "slide-file-item";
      item.textContent = `${f.name} (${(f.size / 1024).toFixed(0)} KB)`;
      fileList.appendChild(item);
    }
    execBtn.disabled = files.length < 2;
    execBtn.classList.toggle("disabled", files.length < 2);
  };

  execBtn.onclick = async () => {
    execBtn.disabled = true;
    execBtn.textContent = "上传中...";
    try {
      // Upload each file
      const uploadIds = [];
      for (const f of files) {
        const formData = new FormData();
        formData.append("file", f);
        const res = await fetch("/api/v1/uploads", { method: "POST", body: formData });
        const data = await res.json();
        if (data.code === 0) uploadIds.push(data.data.upload_id);
        else throw new Error(data.message || "上传失败");
      }
      execBtn.textContent = "合并中...";
      const result = await mergePdfs(uploadIds);
      const d = result.data;
      resultDiv.innerHTML = `
        <div class="slide-result-success">
          <p>✅ 合并完成！共 ${d.page_count} 页，${(d.file_size / 1024 / 1024).toFixed(1)} MB</p>
          <a href="${getResultDownloadUrl(d.result_id, d.file_name)}" class="button-link primary" download>下载</a>
        </div>
      `;
    } catch (err) {
      resultDiv.innerHTML = `<p class="slide-error">❌ ${err.message}</p>`;
    } finally {
      execBtn.disabled = false;
      execBtn.textContent = "合并";
    }
  };
}
```

- [ ] **Step 2: Create split panel**

```javascript
import { openSlidePanel } from "./panels.js";

export function openSplitPanel() {
  const panel = openSlidePanel({
    title: "拆分 PDF",
    contentHtml: `
      <p class="slide-panel-desc">选择一个 PDF 并按页码范围拆分为多个文件。</p>
      <input type="file" accept=".pdf" id="split-file-input" />
      <div id="split-range-list">
        <div class="split-range-row">
          <label>范围 1:</label>
          <input type="number" class="split-start" min="1" placeholder="起始页" />
          <span>-</span>
          <input type="number" class="split-end" min="1" placeholder="结束页" />
          <button class="split-remove-btn hidden">&times;</button>
        </div>
      </div>
      <button id="split-add-range" class="button-link secondary">+ 添加范围</button>
      <button id="split-execute-btn" class="button-link primary disabled" disabled>拆分</button>
      <div id="split-result" class="slide-result"></div>
    `,
  });
  // ... (range add/remove logic, execute with upload+API call)
}
```

- [ ] **Step 3: Create compress panel**

```javascript
import { openSlidePanel } from "./panels.js";

export function openCompressPanel() {
  const panel = openSlidePanel({
    title: "压缩 PDF",
    contentHtml: `
      <p class="slide-panel-desc">压缩 PDF 中的图片来减小文件体积。</p>
      <input type="file" accept=".pdf" id="compress-file-input" />
      <div class="slide-config-row">
        <label>目标 DPI:</label>
        <select id="compress-dpi">
          <option value="72">72 DPI (最小体积)</option>
          <option value="96">96 DPI (屏幕阅读)</option>
          <option value="150" selected>150 DPI (推荐)</option>
          <option value="200">200 DPI (高质量)</option>
          <option value="300">300 DPI (印刷级)</option>
        </select>
      </div>
      <button id="compress-execute-btn" class="button-link primary disabled" disabled>压缩</button>
      <div id="compress-result" class="slide-result"></div>
    `,
  });
  // ... (file select → upload → call compress API → download)
}
```

---

## Task 13: Frontend — Tool Panels (Rotate, Metadata, Encrypt)

**Files:**
- Create: `frontend/src/js/features/pdf-tools/panel-rotate.js`
- Create: `frontend/src/js/features/pdf-tools/panel-metadata.js`
- Create: `frontend/src/js/features/pdf-tools/panel-encrypt.js`

- [ ] **Step 1: Create rotate panel**

```javascript
import { openSlidePanel } from "./panels.js";
import { rotatePdf, getResultDownloadUrl } from "./api.js";

export function openRotatePanel() {
  const panel = openSlidePanel({
    title: "旋转 PDF",
    contentHtml: `
      <p class="slide-panel-desc">旋转 PDF 页面方向。</p>
      <input type="file" accept=".pdf" id="rotate-file-input" />
      <div class="slide-config-row">
        <label>角度:</label>
        <select id="rotate-degrees">
          <option value="90">顺时针 90°</option>
          <option value="180">180°</option>
          <option value="270">逆时针 90°</option>
        </select>
      </div>
      <div class="slide-config-row">
        <label>范围:</label>
        <select id="rotate-pages">
          <option value="all">全部页面</option>
          <option value="odd">奇数页</option>
          <option value="even">偶数页</option>
        </select>
      </div>
      <button id="rotate-execute-btn" class="button-link primary disabled" disabled>旋转</button>
      <div id="rotate-result" class="slide-result"></div>
    `,
  });
  // ... (file upload + execute logic)
}
```

- [ ] **Step 2: Create metadata panel**

```javascript
import { openSlidePanel } from "./panels.js";
import { getMetadata, updateMetadata, getResultDownloadUrl } from "./api.js";

export function openMetadataPanel() {
  const panel = openSlidePanel({
    title: "元数据编辑",
    contentHtml: `
      <p class="slide-panel-desc">查看和编辑 PDF 文档信息。</p>
      <input type="file" accept=".pdf" id="meta-file-input" />
      <div id="meta-fields" class="slide-form">
        <div class="slide-config-row"><label>标题:</label><input type="text" id="meta-title" /></div>
        <div class="slide-config-row"><label>作者:</label><input type="text" id="meta-author" /></div>
        <div class="slide-config-row"><label>主题:</label><input type="text" id="meta-subject" /></div>
        <div class="slide-config-row"><label>关键词:</label><input type="text" id="meta-keywords" /></div>
      </div>
      <div class="slide-actions">
        <button id="meta-load-btn" class="button-link secondary">读取元数据</button>
        <button id="meta-save-btn" class="button-link primary disabled" disabled>保存</button>
      </div>
      <div id="meta-result" class="slide-result"></div>
    `,
  });
  // ... (load existing metadata → edit → upload + save)
}
```

- [ ] **Step 3: Create encrypt panel**

```javascript
export function openEncryptPanel() {
  const panel = openSlidePanel({
    title: "加密 / 解密 PDF",
    contentHtml: `
      <p class="slide-panel-desc">为 PDF 添加密码保护，或移除密码。</p>
      <input type="file" accept=".pdf" id="encrypt-file-input" />
      <div class="slide-tabs">
        <button class="slide-tab active" data-tab="encrypt">加密</button>
        <button class="slide-tab" data-tab="decrypt">解密</button>
      </div>
      <div id="encrypt-tab-content">
        <div class="slide-config-row"><label>打开密码:</label><input type="password" id="encrypt-user-pw" /></div>
        <div class="slide-config-row"><label>所有者密码:</label><input type="password" id="encrypt-owner-pw" /></div>
      </div>
      <div id="decrypt-tab-content" class="hidden">
        <div class="slide-config-row"><label>密码:</label><input type="password" id="decrypt-pw" /></div>
      </div>
      <button id="encrypt-execute-btn" class="button-link primary disabled" disabled>执行</button>
      <div id="encrypt-result" class="slide-result"></div>
    `,
  });
  // ... (tab toggle + execute logic)
}
```

---

## Task 14: Frontend — Main Controller + HTML Integration

**Files:**
- Create: `frontend/src/js/features/pdf-tools/controller.js`
- Modify: `frontend/index.html` — add toolbox HTML
- Modify: `frontend/src/js/main.js` — mount pdf-tools feature

- [ ] **Step 1: Create main controller**

Create `frontend/src/js/features/pdf-tools/controller.js`:

```javascript
import { openMergePanel } from "./panel-merge.js";
import { openSplitPanel } from "./panel-split.js";
import { openCompressPanel } from "./panel-compress.js";
import { openRotatePanel } from "./panel-rotate.js";
import { openMetadataPanel } from "./panel-metadata.js";
import { openEncryptPanel } from "./panel-encrypt.js";

export function mountPdfToolsFeature({ uploadFeature }) {
  const toolbox = document.getElementById("pdf-toolbox");
  if (!toolbox) return;

  const toolMap = {
    "tool-merge": () => openMergePanel(uploadFeature),
    "tool-split": () => openSplitPanel(),
    "tool-compress": () => openCompressPanel(),
    "tool-rotate": () => openRotatePanel(),
    "tool-metadata": () => openMetadataPanel(),
    "tool-encrypt": () => openEncryptPanel(),
  };

  toolbox.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tool]");
    if (btn) {
      const tool = btn.dataset.tool;
      toolMap[tool]?.();
    }
  });
}
```

- [ ] **Step 2: Add toolbox HTML to index.html**

Insert after the workflow section and before the recent jobs section in `frontend/index.html`:

```html
<section id="pdf-toolbox" class="pdf-toolbox">
  <h2 class="section-title">
    <span class="section-title-icon">📦</span> PDF 工具箱
  </h2>
  <div class="tool-grid">
    <button data-tool="tool-merge" class="tool-btn">
      <span class="tool-icon">⊞</span>
      <span class="tool-label">合并 PDF</span>
    </button>
    <button data-tool="tool-split" class="tool-btn">
      <span class="tool-icon">⊞</span>
      <span class="tool-label">拆分 PDF</span>
    </button>
    <button data-tool="tool-compress" class="tool-btn">
      <span class="tool-icon">▾</span>
      <span class="tool-label">压缩</span>
    </button>
    <button data-tool="tool-rotate" class="tool-btn">
      <span class="tool-icon">↻</span>
      <span class="tool-label">旋转</span>
    </button>
    <button data-tool="tool-metadata" class="tool-btn">
      <span class="tool-icon">ℹ</span>
      <span class="tool-label">元数据</span>
    </button>
    <button data-tool="tool-encrypt" class="tool-btn">
      <span class="tool-icon">🔒</span>
      <span class="tool-label">加密</span>
    </button>
    <button data-tool="tool-more" class="tool-btn tool-btn-more">
      <span class="tool-icon">⋯</span>
      <span class="tool-label">更多</span>
    </button>
  </div>
</section>
```

- [ ] **Step 3: Mount feature in main.js**

Edit `frontend/src/js/main.js` — add import and mount call:

```javascript
// Add import at top:
import { mountPdfToolsFeature } from "./features/pdf-tools/controller.js";

// Add after mountUploadWorkflowFeatures() or in initializePage():
mountPdfToolsFeature({
  uploadFeature,
});
```

- [ ] **Step 4: Add toolbox CSS**

Add to `frontend/src/input.css` or as a new stylesheet:

```css
.pdf-toolbox {
  margin: 1.5rem 0;
  padding: 1rem;
  background: var(--surface);
  border-radius: 8px;
  border: 1px solid var(--border);
}

.tool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 0.75rem;
  margin-top: 0.75rem;
}

.tool-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  padding: 0.75rem 0.5rem;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}
.tool-btn:hover {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 8%, var(--bg));
}
.tool-icon {
  font-size: 1.4rem;
  line-height: 1;
}
.tool-label {
  font-size: 0.8rem;
  white-space: nowrap;
}
```

---

## Task 15: CSS for Slide-over Panel

- [ ] **Step 1: Add slide-over panel styles**

Add to `frontend/src/input.css`:

```css
.slide-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  z-index: 1000;
  opacity: 0;
  transition: opacity 0.2s;
}
.slide-overlay.active { opacity: 1; }

.slide-panel {
  position: fixed;
  top: 0;
  right: -480px;
  width: 480px;
  max-width: 100vw;
  height: 100vh;
  background: var(--surface);
  box-shadow: -4px 0 24px rgba(0,0,0,0.15);
  transition: right 0.25s ease;
  display: flex;
  flex-direction: column;
  z-index: 1001;
}
.slide-overlay.active .slide-panel { right: 0; }

.slide-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border);
}
.slide-panel-header h3 { margin: 0; }
.slide-panel-close {
  font-size: 1.5rem;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.25rem;
  line-height: 1;
}
.slide-panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem;
}
```

---

## Plan Summary: Phase 1 Tasks

| Task | Description | Files | Est. Effort |
|------|-------------|-------|-------------|
| 1 | Python result store | 2 create | Small |
| 2 | Python merge PDFs | 1 create | Small |
| 3 | Python split PDF | 1 create | Small |
| 4 | Python compress PDF | 1 create | Small (reuses existing) |
| 5 | Python rotate PDF | 1 create | Small |
| 6 | Python metadata editor | 1 create | Small |
| 7 | Python encrypt/decrypt | 1 create | Small |
| 8 | Rust API routes (scaffold) | 1 create, 1 modify | Medium |
| 9 | Register routes in router | 1 modify | Small |
| 10 | Implement merge with Python bridge | 1 modify | Medium |
| 11 | Frontend panels + API module | 2 create | Medium |
| 12 | Tool panels (merge/split/compress) | 3 create | Medium |
| 13 | Tool panels (rotate/metadata/encrypt) | 3 create | Medium |
| 14 | Main controller + HTML integration | 1 create, 2 modify | Medium |
| 15 | CSS styles | 1 modify | Small |

---

## Spec Coverage Check

- [x] Merge PDFs (end-to-end splice) — Task 2, 10, 12
- [x] Split PDF — Task 3, 8, 12
- [x] Compress PDF — Task 4, 8, 12
- [x] Rotate PDF — Task 5, 8, 13
- [x] Metadata editor — Task 6, 8, 13
- [x] Encrypt/Decrypt — Task 7, 8, 13
- [x] UI integration (existing page) — Task 14
- [x] Slide-over panels — Task 11, 15
- [x] Result store with 1hr cleanup — Task 1
- [x] File upload → process → download flow — Task 11 (api.js)
