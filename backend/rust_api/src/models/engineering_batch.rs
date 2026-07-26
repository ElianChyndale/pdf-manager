use serde::{Deserialize, Serialize};

use super::{CreateJobInput, JobStatusKind};

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct EngineeringBatchItemInput {
    pub source_upload_id: String,
    #[serde(default)]
    pub legacy_translation_upload_id: String,
    pub relative_path: String,
    pub content_hash: String,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
#[serde(deny_unknown_fields)]
pub struct EngineeringBatchCreateInput {
    #[serde(default)]
    pub job_template: CreateJobInput,
    #[serde(default)]
    pub items: Vec<EngineeringBatchItemInput>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct EngineeringBatchReviewInput {
    pub item_index: usize,
    pub status: String,
    #[serde(default)]
    pub note: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EngineeringBatchRecord {
    pub schema_version: String,
    pub batch_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub items: Vec<EngineeringBatchItemRecord>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EngineeringBatchItemRecord {
    pub item_index: usize,
    pub source_upload_id: String,
    pub legacy_translation_upload_id: String,
    pub relative_path: String,
    pub content_hash: String,
    pub canonical_item_index: usize,
    pub job_id: Option<String>,
    pub submission_error: Option<String>,
    pub review_status: String,
    pub review_note: String,
}

#[derive(Debug, Serialize)]
pub struct EngineeringBatchView {
    pub batch_id: String,
    pub status: String,
    pub created_at: String,
    pub updated_at: String,
    pub total_items: usize,
    pub unique_jobs: usize,
    pub queued: usize,
    pub running: usize,
    pub succeeded: usize,
    pub failed: usize,
    pub canceled: usize,
    pub rejected: usize,
    pub items: Vec<EngineeringBatchItemView>,
}

#[derive(Debug, Serialize)]
pub struct EngineeringBatchItemView {
    pub item_index: usize,
    pub source_upload_id: String,
    pub legacy_translation_upload_id: String,
    pub relative_path: String,
    pub content_hash: String,
    pub canonical_item_index: usize,
    pub job_id: Option<String>,
    pub status: String,
    pub error: Option<String>,
    pub review_status: String,
    pub review_note: String,
}

impl EngineeringBatchView {
    pub fn overall_status(&self) -> &'static str {
        if self.running > 0 {
            "running"
        } else if self.queued > 0 {
            "queued"
        } else if self.failed > 0 || self.rejected > 0 {
            "needs_attention"
        } else if self.canceled > 0 {
            "canceled"
        } else {
            "succeeded"
        }
    }
}

pub fn job_status_name(status: &JobStatusKind) -> &'static str {
    match status {
        JobStatusKind::Queued => "queued",
        JobStatusKind::Running => "running",
        JobStatusKind::Succeeded => "succeeded",
        JobStatusKind::Failed => "failed",
        JobStatusKind::Canceled => "canceled",
    }
}
