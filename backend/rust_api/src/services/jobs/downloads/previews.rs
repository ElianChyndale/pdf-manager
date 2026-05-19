use std::path::{Path, PathBuf};

use crate::error::AppError;

use super::QueryJobsDeps;
use crate::services::jobs::presentation::load_supported_job;

#[derive(Clone, Copy)]
pub(super) enum PagePreviewKind {
    Source,
    Translated,
}

impl PagePreviewKind {
    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::Source => "source",
            Self::Translated => "translated",
        }
    }
}

pub(super) fn preview_kind(kind: &str) -> Result<PagePreviewKind, AppError> {
    match kind.trim().to_ascii_lowercase().as_str() {
        "source" => Ok(PagePreviewKind::Source),
        "translated" => Ok(PagePreviewKind::Translated),
        _ => Err(AppError::bad_request(
            "preview kind must be source or translated",
        )),
    }
}

#[derive(Clone, Copy)]
pub(super) enum BookImageKind {
    Cover,
    Thumbnail,
}

impl BookImageKind {
    fn file_name(self) -> &'static str {
        match self {
            Self::Cover => "cover.jpg",
            Self::Thumbnail => "thumbnail.jpg",
        }
    }

    fn width_px(self) -> u32 {
        match self {
            Self::Cover => 900,
            Self::Thumbnail => 360,
        }
    }
}

pub(super) fn render_book_image(
    deps: &QueryJobsDeps<'_>,
    job_id: &str,
    kind: BookImageKind,
) -> Result<PathBuf, AppError> {
    let job = load_supported_job(deps.db, deps.data_root, job_id)?;
    let source_pdf = crate::storage_paths::resolve_source_pdf(&job, deps.data_root)
        .ok_or_else(|| AppError::not_found(format!("source pdf not ready: {}", job.job_id)))?;
    let output_dir = super::paths::job_artifacts_dir(deps, &job)?;
    let output_path = output_dir.join(kind.file_name());
    if output_path.exists() && output_path.is_file() {
        return Ok(output_path);
    }

    let script = r#"
import sys
from pathlib import Path
import fitz

source = Path(sys.argv[1])
output = Path(sys.argv[2])
width_px = int(sys.argv[3])

with fitz.open(source) as doc:
    if doc.page_count < 1:
        raise RuntimeError("source pdf has no pages")
    page = doc[0]
    scale = width_px / max(float(page.rect.width), 1.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    pix.save(output)
"#;
    let status = std::process::Command::new(deps.replay.python_bin)
        .arg("-c")
        .arg(script)
        .arg(&source_pdf)
        .arg(&output_path)
        .arg(kind.width_px().to_string())
        .status()
        .map_err(|error| AppError::internal(format!("failed to render book image: {error}")))?;
    if !status.success() || !output_path.exists() {
        return Err(AppError::internal(format!(
            "failed to render book image for {}",
            job.job_id
        )));
    }
    Ok(output_path)
}

pub(super) fn render_pdf_page_preview(
    python_bin: &str,
    source_pdf: &Path,
    output_path: &Path,
    page_index: u32,
    width_px: u32,
    dpi: u32,
) -> Result<(), AppError> {
    let script = r#"
import sys
from pathlib import Path
import fitz

source = Path(sys.argv[1])
output = Path(sys.argv[2])
page_index = int(sys.argv[3])
width_px = int(sys.argv[4])
dpi = int(sys.argv[5])

with fitz.open(source) as doc:
    if page_index < 0 or page_index >= doc.page_count:
        raise RuntimeError(f"page out of range: {page_index + 1}/{doc.page_count}")
    page = doc[page_index]
    if dpi > 0:
        scale = dpi / 72.0
    else:
        scale = width_px / max(float(page.rect.width), 1.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    pix.save(output, jpg_quality=82)
"#;
    let status = std::process::Command::new(python_bin)
        .arg("-c")
        .arg(script)
        .arg(source_pdf)
        .arg(output_path)
        .arg(page_index.to_string())
        .arg(width_px.to_string())
        .arg(dpi.to_string())
        .status()
        .map_err(|error| AppError::internal(format!("failed to render page preview: {error}")))?;
    if !status.success() || !output_path.exists() {
        return Err(AppError::internal("failed to render page preview"));
    }
    Ok(())
}
