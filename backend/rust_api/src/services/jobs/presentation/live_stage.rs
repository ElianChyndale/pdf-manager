use std::path::Path;

use crate::error::AppError;
use crate::models::{JobEventRecord, JobSnapshot, JobStage};
use crate::storage_paths::resolve_events_jsonl;
use serde_json::{json, Value};

mod pipeline_events;

use pipeline_events::load_pipeline_events_jsonl;

#[derive(Debug, Clone)]
pub struct LiveStageSnapshot {
    pub stage: Option<String>,
    pub stage_detail: Option<String>,
    pub progress_current: Option<i64>,
    pub progress_total: Option<i64>,
}

pub fn load_live_stage_snapshot(job: &JobSnapshot, data_root: &Path) -> Option<LiveStageSnapshot> {
    let items = load_pipeline_event_records(job, data_root, 0);
    select_live_stage_snapshot(&items)
}

pub fn load_pipeline_event_records(
    job: &JobSnapshot,
    data_root: &Path,
    base_seq: i64,
) -> Vec<JobEventRecord> {
    let Some(path) = resolve_events_jsonl(job, data_root) else {
        return Vec::new();
    };
    load_pipeline_events_jsonl(&job.job_id, &path, base_seq)
}

pub fn list_combined_job_events(
    db: &crate::db::Db,
    data_root: &Path,
    job: &JobSnapshot,
) -> Result<Vec<JobEventRecord>, AppError> {
    let mut items = db.list_job_events(&job.job_id, 10_000, 0)?;
    let base_seq = items.iter().map(|item| item.seq).max().unwrap_or(0);
    let mut file_items = load_pipeline_event_records(job, data_root, base_seq);
    items.append(&mut file_items);
    append_ocr_child_events(db, data_root, job, &mut items)?;
    items.sort_by(|left, right| {
        left.ts
            .cmp(&right.ts)
            .then_with(|| left.seq.cmp(&right.seq))
            .then_with(|| left.event.cmp(&right.event))
    });
    for (index, item) in items.iter_mut().enumerate() {
        item.seq = (index + 1) as i64;
    }
    Ok(items)
}

fn append_ocr_child_events(
    db: &crate::db::Db,
    data_root: &Path,
    parent_job: &JobSnapshot,
    items: &mut Vec<JobEventRecord>,
) -> Result<(), AppError> {
    let Some(ocr_job_id) = parent_job
        .artifacts
        .as_ref()
        .and_then(|artifacts| artifacts.ocr_job_id.as_ref())
        .map(String::as_str)
        .filter(|value| !value.trim().is_empty() && *value != parent_job.job_id)
    else {
        return Ok(());
    };
    let Ok(ocr_job) = db.get_job(ocr_job_id) else {
        return Ok(());
    };
    let base_seq = items.iter().map(|item| item.seq).max().unwrap_or(0);
    let mut child_items = db.list_job_events(ocr_job_id, 10_000, 0)?;
    let mut child_file_items =
        load_pipeline_event_records(&ocr_job, data_root, base_seq + child_items.len() as i64);
    child_items.append(&mut child_file_items);
    items.extend(
        child_items
            .into_iter()
            .map(|item| mirror_child_event(parent_job, ocr_job_id, item)),
    );
    Ok(())
}

fn mirror_child_event(
    parent_job: &JobSnapshot,
    source_job_id: &str,
    mut item: JobEventRecord,
) -> JobEventRecord {
    let original_payload = item
        .payload
        .take()
        .unwrap_or(Value::Object(Default::default()));
    item.job_id = parent_job.job_id.clone();
    item.user_stage = item.user_stage.or_else(|| Some("ocr".to_string()));
    item.payload = Some(json!({
        "source_job_id": source_job_id,
        "source_event": original_payload,
    }));
    item
}

fn select_live_stage_snapshot(items: &[JobEventRecord]) -> Option<LiveStageSnapshot> {
    items
        .iter()
        .filter(|item| {
            let event_type = item.event_type.as_deref().map(str::trim).unwrap_or("");
            let stage = item.stage.as_deref().map(str::trim).unwrap_or("");
            event_type != "artifact_published" && !stage.is_empty()
        })
        .max_by(|left, right| {
            user_stage_rank(left.stage.as_deref())
                .cmp(&user_stage_rank(right.stage.as_deref()))
                .then_with(|| left.ts.cmp(&right.ts))
                .then_with(|| left.seq.cmp(&right.seq))
        })
        .map(|item| LiveStageSnapshot {
            stage: item.stage.clone(),
            stage_detail: item.stage_detail.clone(),
            progress_current: item.progress_current,
            progress_total: item.progress_total,
        })
}

fn user_stage_rank(stage: Option<&str>) -> i32 {
    match stage.and_then(JobStage::from_str) {
        Some(JobStage::Queued) => 0,
        Some(JobStage::Rendering | JobStage::Finished) => 3,
        Some(JobStage::Translating) => 2,
        Some(
            JobStage::OcrSubmitting
            | JobStage::OcrUpload
            | JobStage::MineruUpload
            | JobStage::OcrProcessing
            | JobStage::MineruProcessing
            | JobStage::OcrResultReady
            | JobStage::Normalizing,
        ) => 1,
        Some(JobStage::Running) => 0,
        Some(JobStage::Canceled | JobStage::Failed) => 0,
        None => {
            let normalized = stage.unwrap_or_default().trim();
            if normalized.contains("render") {
                return 3;
            }
            if normalized == "succeeded" {
                return 3;
            }
            if normalized.contains("translat")
                || normalized == "domain_inference"
                || normalized == "continuation_review"
                || normalized == "page_policies"
            {
                return 2;
            }
            if normalized.contains("ocr")
                || normalized.contains("mineru")
                || normalized.contains("paddle")
                || normalized.contains("normaliz")
            {
                return 1;
            }
            0
        }
    }
}
