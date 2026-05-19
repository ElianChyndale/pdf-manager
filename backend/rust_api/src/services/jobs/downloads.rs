use std::path::{Path, PathBuf};

use crate::error::AppError;
use crate::models::{JobSnapshot, JobStatusKind, PagePreviewQuery};
use crate::services::artifacts::{
    artifact_is_direct_downloadable, build_bundle_for_job, build_markdown_bundle_for_job,
    resolve_registry_artifact,
};
use crate::storage_paths::{
    resolve_markdown_images_dir, resolve_markdown_path, resolve_output_pdf, resolve_source_pdf,
    ARTIFACT_KEY_MARKDOWN_BUNDLE_ZIP, ARTIFACT_KEY_SOURCE_PDF, ARTIFACT_KEY_TRANSLATED_PDF,
};

use super::creation::context::QueryJobsDeps;
use super::presentation::load_supported_job;

mod paths;
mod pdf;
mod previews;

use paths::{job_artifacts_dir, safe_markdown_image_path};
use pdf::linearized_pdf_or_original;
use previews::{
    preview_kind, render_book_image, render_pdf_page_preview, BookImageKind, PagePreviewKind,
};

#[derive(Debug)]
pub struct FileDownload {
    pub path: PathBuf,
    pub content_type: String,
    pub download_name: Option<String>,
    pub job_id_header: Option<String>,
}

impl FileDownload {
    pub fn new(
        path: PathBuf,
        content_type: impl Into<String>,
        download_name: Option<String>,
    ) -> Self {
        Self {
            path,
            content_type: content_type.into(),
            download_name,
            job_id_header: None,
        }
    }

    pub fn with_job_id_header(mut self, job_id: impl Into<String>) -> Self {
        self.job_id_header = Some(job_id.into());
        self
    }
}

#[derive(Debug)]
pub struct MarkdownDownload {
    pub job_id: String,
    pub content: String,
}

pub fn document_download(
    deps: &QueryJobsDeps<'_>,
    job: &JobSnapshot,
    resolve_path: impl Fn(&JobSnapshot, &Path) -> Option<PathBuf>,
    not_ready_label: &str,
    content_type: &str,
) -> Result<FileDownload, AppError> {
    let path = resolve_path(job, deps.data_root)
        .ok_or_else(|| AppError::not_found(format!("{not_ready_label}: {}", job.job_id)))?;
    let path = if content_type == "application/pdf" {
        linearized_pdf_or_original(deps, job, &path, "output")?
    } else {
        path
    };
    Ok(FileDownload::new(path, content_type, None))
}

pub fn page_preview_download(
    deps: &QueryJobsDeps<'_>,
    job_id: &str,
    page: u32,
    query: &PagePreviewQuery,
) -> Result<FileDownload, AppError> {
    let job = load_supported_job(deps.db, deps.data_root, job_id)?;
    let source_pdf = match preview_kind(&query.kind)? {
        PagePreviewKind::Source => resolve_source_pdf(&job, deps.data_root)
            .ok_or_else(|| AppError::not_found(format!("source pdf not ready: {}", job.job_id)))?,
        PagePreviewKind::Translated => {
            resolve_output_pdf(&job, deps.data_root).ok_or_else(|| {
                AppError::not_found(format!("translated pdf not ready: {}", job.job_id))
            })?
        }
    };
    let page_index = page
        .checked_sub(1)
        .ok_or_else(|| AppError::bad_request("page must be 1-based"))?;
    let width_px = query.width.unwrap_or(1200).clamp(240, 2400);
    let dpi = query.dpi.unwrap_or(0).min(300);
    let output_dir = job_artifacts_dir(deps, &job)?;
    let output_path = output_dir.join(format!(
        "preview-{}-p{:04}-w{}-d{}.jpg",
        preview_kind(&query.kind)?.as_str(),
        page,
        width_px,
        dpi
    ));
    if output_path.exists() && output_path.is_file() {
        return Ok(FileDownload::new(output_path, "image/jpeg", None));
    }
    render_pdf_page_preview(
        deps.replay.python_bin,
        &source_pdf,
        &output_path,
        page_index,
        width_px,
        dpi,
    )?;
    Ok(FileDownload::new(output_path, "image/jpeg", None))
}

pub fn cover_download(deps: &QueryJobsDeps<'_>, job_id: &str) -> Result<FileDownload, AppError> {
    let path = render_book_image(deps, job_id, BookImageKind::Cover)?;
    Ok(FileDownload::new(path, "image/jpeg", None))
}

pub fn thumbnail_download(
    deps: &QueryJobsDeps<'_>,
    job_id: &str,
) -> Result<FileDownload, AppError> {
    let path = render_book_image(deps, job_id, BookImageKind::Thumbnail)?;
    Ok(FileDownload::new(path, "image/jpeg", None))
}

pub async fn markdown_download(
    deps: &QueryJobsDeps<'_>,
    job_id: String,
) -> Result<MarkdownDownload, AppError> {
    let job = load_supported_job(deps.db, deps.data_root, &job_id)?;
    let markdown_path = resolve_markdown_path(&job, deps.data_root)
        .ok_or_else(|| AppError::not_found(format!("markdown not found: {job_id}")))?;
    let content = tokio::fs::read_to_string(&markdown_path).await?;
    Ok(MarkdownDownload {
        job_id: job.job_id.clone(),
        content,
    })
}

pub fn markdown_image_download(
    deps: &QueryJobsDeps<'_>,
    job_id: &str,
    path: &str,
) -> Result<FileDownload, AppError> {
    let job = load_supported_job(deps.db, deps.data_root, job_id)?;
    let images_dir = resolve_markdown_images_dir(&job, deps.data_root)
        .ok_or_else(|| AppError::not_found(format!("markdown images not found: {job_id}")))?;
    let relative_path = safe_markdown_image_path(path)?;
    let file_path = images_dir.join(relative_path);
    if !file_path.exists() || !file_path.is_file() {
        return Err(AppError::not_found(format!(
            "markdown image not found: {path}"
        )));
    }
    let mime = mime_guess::from_path(&file_path).first_or_octet_stream();
    Ok(FileDownload::new(file_path, mime.as_ref(), None))
}

pub fn bundle_download(deps: &QueryJobsDeps<'_>, job_id: &str) -> Result<FileDownload, AppError> {
    let job = load_supported_job(deps.db, deps.data_root, job_id)?;
    if !matches!(job.status, JobStatusKind::Succeeded) {
        return Err(AppError::conflict("job is not finished successfully"));
    }
    let zip_path = build_bundle_for_job(deps.db, deps.data_root, deps.downloads_dir, &job)?;
    Ok(
        FileDownload::new(zip_path, "application/zip", Some(format!("{job_id}.zip")))
            .with_job_id_header(job_id),
    )
}

pub fn registered_artifact_download(
    deps: &QueryJobsDeps<'_>,
    job: &JobSnapshot,
    artifact_key: &str,
    include_job_dir: bool,
) -> Result<FileDownload, AppError> {
    if artifact_key == ARTIFACT_KEY_MARKDOWN_BUNDLE_ZIP {
        let (item, path) =
            build_markdown_bundle_for_job(deps.db, deps.data_root, job, include_job_dir)?;
        return Ok(FileDownload::new(path, item.content_type, item.file_name));
    }
    let Some((item, path)) = resolve_registry_artifact(deps.db, deps.data_root, job, artifact_key)?
    else {
        return Err(AppError::not_found(format!(
            "artifact not found: {}/{artifact_key}",
            job.job_id
        )));
    };
    if !artifact_is_direct_downloadable(&item) {
        return Err(AppError::conflict(format!(
            "artifact is a directory and cannot be streamed directly: {artifact_key}"
        )));
    }
    if !item.ready || !path.exists() || !path.is_file() {
        return Err(AppError::not_found(format!(
            "artifact not ready: {}/{artifact_key}",
            job.job_id
        )));
    }
    let path = if item.content_type == "application/pdf"
        && matches!(
            artifact_key,
            ARTIFACT_KEY_SOURCE_PDF | ARTIFACT_KEY_TRANSLATED_PDF
        ) {
        linearized_pdf_or_original(deps, job, &path, artifact_key)?
    } else {
        path
    };
    Ok(FileDownload::new(path, item.content_type, item.file_name))
}
