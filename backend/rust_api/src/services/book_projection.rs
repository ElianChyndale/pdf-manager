use std::path::Path;

use crate::db::Db;
use crate::error::AppError;
use crate::models::{
    to_absolute_url, JobSnapshot, LibraryBookDetailView, LibraryBookListItemView,
    LibraryBookListView, ListJobsQuery, WorkflowKind,
};
use crate::storage_paths::{resolve_markdown_path, resolve_output_pdf, resolve_source_pdf};

use crate::models::build_artifact_links;
use crate::services::jobs::readiness;

mod artifacts;
mod live;
mod metadata;

pub(crate) use artifacts::build_artifacts_display;
use live::build_live_projection;
use metadata::{build_book_summary, derive_display_name, page_count_for_library, source_file_name};

pub(crate) fn build_library_book_list_view(
    db: &Db,
    data_root: &Path,
    query: &ListJobsQuery,
    base_url: &str,
) -> Result<LibraryBookListView, AppError> {
    let mut query = query.clone();
    query.workflow = None;
    let items = list_books_filtered(db, &query)?
        .iter()
        .filter(|job| job.workflow != WorkflowKind::Ocr)
        .map(|job| build_library_book_list_item(db, data_root, job, base_url))
        .collect();
    Ok(LibraryBookListView { items })
}

pub(crate) fn build_library_book_detail_view(
    db: &Db,
    data_root: &Path,
    job: &JobSnapshot,
    base_url: &str,
) -> LibraryBookDetailView {
    let display_name = derive_display_name(db, job);
    let summary = build_book_summary(db, job, data_root, base_url, &display_name)
        .with_cover_url(library_image_url(job, data_root, base_url, "cover"));
    let live = build_live_projection(job, data_root);
    let (pdf_ready, markdown_ready, bundle_ready) =
        readiness(job, data_root, resolve_output_pdf, resolve_markdown_path);
    let artifacts = build_artifact_links(
        job,
        base_url,
        data_root,
        pdf_ready,
        markdown_ready,
        bundle_ready,
    );
    LibraryBookDetailView {
        id: job.job_id.clone(),
        job_id: job.job_id.clone(),
        title: summary.title,
        authors: summary.authors,
        source_file_name: summary.source_file_name,
        page_count: summary.page_count,
        source_language: summary.source_language,
        target_language: summary.target_language,
        file_size_bytes: summary.file_size_bytes,
        status: job.status.clone(),
        stage: live.stage,
        progress: live.progress,
        cover_url: summary.cover_url,
        thumbnail_url: library_image_url(job, data_root, base_url, "thumbnail"),
        artifacts: build_artifacts_display(&artifacts),
    }
}

fn build_library_book_list_item(
    db: &Db,
    data_root: &Path,
    job: &JobSnapshot,
    base_url: &str,
) -> LibraryBookListItemView {
    let display_name = derive_display_name(db, job);
    let live = build_live_projection(job, data_root);
    let (output_pdf_ready, markdown_ready, bundle_ready) =
        readiness(job, data_root, resolve_output_pdf, resolve_markdown_path);
    LibraryBookListItemView {
        id: job.job_id.clone(),
        job_id: job.job_id.clone(),
        title: display_name.clone(),
        display_name,
        source_file_name: source_file_name(db, job),
        authors: None,
        page_count: page_count_for_library(db, job, data_root),
        status: job.status.clone(),
        stage: live.stage,
        stage_detail: live.stage_detail,
        progress: live.progress,
        cover_url: library_image_url(job, data_root, base_url, "cover"),
        thumbnail_url: library_image_url(job, data_root, base_url, "thumbnail"),
        output_pdf_ready,
        markdown_ready,
        bundle_ready,
        created_at: job.created_at.clone(),
        updated_at: job.updated_at.clone(),
    }
}

fn library_image_url(
    job: &JobSnapshot,
    data_root: &Path,
    base_url: &str,
    kind: &str,
) -> Option<String> {
    resolve_source_pdf(job, data_root).map(|_| {
        to_absolute_url(
            base_url,
            &format!("/api/v1/library/books/{}/{kind}", job.job_id),
        )
    })
}

fn list_books_filtered(db: &Db, query: &ListJobsQuery) -> Result<Vec<JobSnapshot>, AppError> {
    let jobs = db.list_jobs(
        query.limit,
        query.offset,
        query.status.as_ref(),
        query.workflow.as_ref(),
    )?;
    Ok(jobs
        .into_iter()
        .filter(|job| {
            query
                .provider
                .as_deref()
                .map(|provider| {
                    job.artifacts
                        .as_ref()
                        .and_then(|artifacts| artifacts.ocr_provider_diagnostics.as_ref())
                        .map(|diag| {
                            format!("{:?}", diag.provider).to_ascii_lowercase()
                                == provider.to_ascii_lowercase()
                        })
                        .unwrap_or(false)
                })
                .unwrap_or(true)
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use super::*;
    use crate::models::{CreateJobInput, JobArtifacts, JobSnapshot};

    #[test]
    fn library_projection_uses_library_media_urls() {
        let data_root = PathBuf::from("/tmp/pdf-manager-data");
        let mut job = JobSnapshot::new(
            "job-library-projection".to_string(),
            CreateJobInput::default(),
            Vec::new(),
        );
        job.artifacts = Some(JobArtifacts {
            source_pdf: Some("jobs/job-library-projection/source/input.pdf".to_string()),
            ..JobArtifacts::default()
        });

        let url = library_image_url(&job, &data_root, "https://api.example", "cover");

        assert_eq!(
            url.as_deref(),
            Some("https://api.example/api/v1/library/books/job-library-projection/cover")
        );
    }
}
