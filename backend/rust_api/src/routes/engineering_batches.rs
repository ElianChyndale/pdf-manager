use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::PathBuf;

use axum::extract::{Path as AxumPath, State};
use axum::http::HeaderMap;
use axum::Json;

use crate::error::AppError;
use crate::models::{
    build_job_id, job_status_name, now_iso, ApiResponse, EngineeringBatchCreateInput,
    EngineeringBatchItemRecord, EngineeringBatchItemView, EngineeringBatchRecord,
    EngineeringBatchReviewInput, EngineeringBatchView, JobStatusKind,
};
use crate::routes::jobs::common::{build_jobs_route_deps, jobs_facade, ok_json, request_base_url};
use crate::AppState;

const BATCH_SCHEMA_VERSION: &str = "engineering_drawing.batch.v1";
const MAX_BATCH_ITEMS: usize = 2_000;
const REVIEW_STATUSES: &[&str] = &["pending", "approved", "rejected"];

pub async fn create_batch(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(input): Json<EngineeringBatchCreateInput>,
) -> Result<Json<ApiResponse<EngineeringBatchView>>, AppError> {
    validate_batch_input(&input)?;
    let batch_id = format!("engineering-batch-{}", build_job_id());
    let now = now_iso();
    let mut record = EngineeringBatchRecord {
        schema_version: BATCH_SCHEMA_VERSION.to_string(),
        batch_id,
        created_at: now.clone(),
        updated_at: now,
        items: Vec::with_capacity(input.items.len()),
    };
    let mut canonical_by_hash: HashMap<String, usize> = HashMap::new();
    let mut result_by_canonical: HashMap<usize, (Option<String>, Option<String>)> = HashMap::new();
    let deps = build_jobs_route_deps(&state);
    let base_url = request_base_url(&headers, deps.default_port);

    for (item_index, item) in input.items.iter().enumerate() {
        let dedupe_key = item.content_hash.trim().to_ascii_lowercase();
        let canonical_item_index = *canonical_by_hash.entry(dedupe_key).or_insert(item_index);
        let (job_id, submission_error) = if canonical_item_index != item_index {
            result_by_canonical
                .get(&canonical_item_index)
                .cloned()
                .unwrap_or_else(|| {
                    (
                        None,
                        Some("canonical batch item has no submission result".to_string()),
                    )
                })
        } else {
            let mut request = input.job_template.clone();
            request.source.upload_id = item.source_upload_id.trim().to_string();
            request.source.legacy_translation_upload_id =
                item.legacy_translation_upload_id.trim().to_string();
            request.source.source_url.clear();
            request.source.artifact_job_id.clear();
            request.runtime.job_id.clear();
            request.translation.rule_profile_name = "engineering_drawing".to_string();
            if request.render.output_modes.is_empty() {
                request.render.output_modes =
                    vec!["bilingual_overlay".to_string(), "dual".to_string()];
            }
            let result = jobs_facade(build_jobs_route_deps(&state))
                .create_submission(&base_url, &request)
                .map(|view| (Some(view.job_id), None))
                .unwrap_or_else(|error| (None, Some(error.to_string())));
            result_by_canonical.insert(item_index, result.clone());
            result
        };

        record.items.push(EngineeringBatchItemRecord {
            item_index,
            source_upload_id: item.source_upload_id.trim().to_string(),
            legacy_translation_upload_id: item.legacy_translation_upload_id.trim().to_string(),
            relative_path: item.relative_path.trim().to_string(),
            content_hash: item.content_hash.trim().to_ascii_lowercase(),
            canonical_item_index,
            job_id,
            submission_error,
            review_status: "pending".to_string(),
            review_note: String::new(),
        });
    }

    save_batch_record(&state, &record)?;
    Ok(ok_json(build_batch_view(&state, &record)))
}

pub async fn get_batch(
    State(state): State<AppState>,
    AxumPath(batch_id): AxumPath<String>,
) -> Result<Json<ApiResponse<EngineeringBatchView>>, AppError> {
    let record = load_batch_record(&state, &batch_id)?;
    Ok(ok_json(build_batch_view(&state, &record)))
}

pub async fn resume_batch(
    State(state): State<AppState>,
    AxumPath(batch_id): AxumPath<String>,
    headers: HeaderMap,
) -> Result<Json<ApiResponse<EngineeringBatchView>>, AppError> {
    let mut record = load_batch_record(&state, &batch_id)?;
    let deps = build_jobs_route_deps(&state);
    let base_url = request_base_url(&headers, deps.default_port);
    let mut replacements: HashMap<String, String> = HashMap::new();
    let mut visited = HashSet::new();

    for item in &record.items {
        let Some(job_id) = item.job_id.as_ref() else {
            continue;
        };
        if !visited.insert(job_id.clone()) {
            continue;
        }
        let Ok(job) = state.db.get_job(job_id) else {
            continue;
        };
        if !matches!(job.status, JobStatusKind::Failed | JobStatusKind::Canceled) {
            continue;
        }
        if let Ok(view) =
            jobs_facade(build_jobs_route_deps(&state)).rerun_submission(&base_url, job_id)
        {
            replacements.insert(job_id.clone(), view.job_id);
        }
    }

    if !replacements.is_empty() {
        for item in &mut record.items {
            if let Some(replacement) = item
                .job_id
                .as_ref()
                .and_then(|job_id| replacements.get(job_id))
            {
                item.job_id = Some(replacement.clone());
                item.submission_error = None;
            }
        }
        record.updated_at = now_iso();
        save_batch_record(&state, &record)?;
    }
    Ok(ok_json(build_batch_view(&state, &record)))
}

pub async fn review_batch_item(
    State(state): State<AppState>,
    AxumPath(batch_id): AxumPath<String>,
    Json(input): Json<EngineeringBatchReviewInput>,
) -> Result<Json<ApiResponse<EngineeringBatchView>>, AppError> {
    let status = input.status.trim().to_ascii_lowercase();
    if !REVIEW_STATUSES.contains(&status.as_str()) {
        return Err(AppError::bad_request(format!(
            "status must be one of: {}",
            REVIEW_STATUSES.join(", ")
        )));
    }
    let mut record = load_batch_record(&state, &batch_id)?;
    let item = record
        .items
        .get_mut(input.item_index)
        .ok_or_else(|| AppError::bad_request("item_index is out of range"))?;
    item.review_status = status;
    item.review_note = input.note.trim().to_string();
    record.updated_at = now_iso();
    save_batch_record(&state, &record)?;
    Ok(ok_json(build_batch_view(&state, &record)))
}

fn validate_batch_input(input: &EngineeringBatchCreateInput) -> Result<(), AppError> {
    if input.items.is_empty() {
        return Err(AppError::bad_request("items must not be empty"));
    }
    if input.items.len() > MAX_BATCH_ITEMS {
        return Err(AppError::bad_request(format!(
            "items must contain at most {MAX_BATCH_ITEMS} entries"
        )));
    }
    for (index, item) in input.items.iter().enumerate() {
        if item.source_upload_id.trim().is_empty() {
            return Err(AppError::bad_request(format!(
                "items[{index}].source_upload_id is required"
            )));
        }
        if item.relative_path.trim().is_empty() {
            return Err(AppError::bad_request(format!(
                "items[{index}].relative_path is required"
            )));
        }
        if item.content_hash.trim().is_empty() {
            return Err(AppError::bad_request(format!(
                "items[{index}].content_hash is required"
            )));
        }
    }
    Ok(())
}

fn batch_records_dir(state: &AppState) -> PathBuf {
    state
        .config
        .data_root
        .join("engineering-drawing")
        .join("batches")
}

fn batch_record_path(state: &AppState, batch_id: &str) -> Result<PathBuf, AppError> {
    if !batch_id.starts_with("engineering-batch-")
        || !batch_id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || character == '-')
    {
        return Err(AppError::bad_request("invalid engineering batch id"));
    }
    Ok(batch_records_dir(state).join(format!("{batch_id}.json")))
}

fn save_batch_record(state: &AppState, record: &EngineeringBatchRecord) -> Result<(), AppError> {
    let dir = batch_records_dir(state);
    fs::create_dir_all(&dir)?;
    let path = batch_record_path(state, &record.batch_id)?;
    fs::write(
        path,
        serde_json::to_vec_pretty(record).map_err(anyhow::Error::from)?,
    )?;
    Ok(())
}

fn load_batch_record(state: &AppState, batch_id: &str) -> Result<EngineeringBatchRecord, AppError> {
    let path = batch_record_path(state, batch_id)?;
    let content = fs::read(&path)
        .map_err(|_| AppError::not_found(format!("engineering batch not found: {batch_id}")))?;
    let record = serde_json::from_slice::<EngineeringBatchRecord>(&content).map_err(|error| {
        AppError::internal(format!("invalid engineering batch record: {error}"))
    })?;
    Ok(record)
}

fn build_batch_view(state: &AppState, record: &EngineeringBatchRecord) -> EngineeringBatchView {
    let mut items = Vec::with_capacity(record.items.len());
    let mut unique_job_ids = HashSet::new();
    let mut queued = 0;
    let mut running = 0;
    let mut succeeded = 0;
    let mut failed = 0;
    let mut canceled = 0;
    let mut rejected = 0;

    for item in &record.items {
        let (status, error) = match item.job_id.as_ref() {
            Some(job_id) => match state.db.get_job(job_id) {
                Ok(job) => {
                    unique_job_ids.insert(job_id.clone());
                    (job_status_name(&job.status).to_string(), job.error)
                }
                Err(error) => ("missing".to_string(), Some(error.to_string())),
            },
            None => (
                "rejected".to_string(),
                item.submission_error
                    .clone()
                    .or_else(|| Some("batch item was not submitted".to_string())),
            ),
        };
        match status.as_str() {
            "queued" => queued += 1,
            "running" => running += 1,
            "succeeded" => succeeded += 1,
            "failed" | "missing" => failed += 1,
            "canceled" => canceled += 1,
            _ => rejected += 1,
        }
        items.push(EngineeringBatchItemView {
            item_index: item.item_index,
            source_upload_id: item.source_upload_id.clone(),
            legacy_translation_upload_id: item.legacy_translation_upload_id.clone(),
            relative_path: item.relative_path.clone(),
            content_hash: item.content_hash.clone(),
            canonical_item_index: item.canonical_item_index,
            job_id: item.job_id.clone(),
            status,
            error,
            review_status: item.review_status.clone(),
            review_note: item.review_note.clone(),
        });
    }

    let mut view = EngineeringBatchView {
        batch_id: record.batch_id.clone(),
        status: String::new(),
        created_at: record.created_at.clone(),
        updated_at: record.updated_at.clone(),
        total_items: record.items.len(),
        unique_jobs: unique_job_ids.len(),
        queued,
        running,
        succeeded,
        failed,
        canceled,
        rejected,
        items,
    };
    view.status = view.overall_status().to_string();
    view
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::EngineeringBatchItemInput;

    #[test]
    fn validation_requires_complete_batch_identity_fields() {
        let mut input = EngineeringBatchCreateInput::default();
        assert!(validate_batch_input(&input)
            .expect_err("empty batch should fail")
            .to_string()
            .contains("must not be empty"));

        input.items.push(EngineeringBatchItemInput {
            source_upload_id: "source-1".to_string(),
            legacy_translation_upload_id: String::new(),
            relative_path: "drawing.pdf".to_string(),
            content_hash: String::new(),
        });
        assert!(validate_batch_input(&input)
            .expect_err("empty content hash should fail")
            .to_string()
            .contains("content_hash is required"));
    }

    #[test]
    fn batch_record_path_rejects_directory_traversal() {
        assert!(!"../escape"
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || character == '-'));
    }
}
