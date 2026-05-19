use std::path::Path;

use crate::models::{JobProgressView, JobSnapshot};
use crate::services::jobs::presentation::live_stage::load_live_stage_snapshot;

pub(super) struct BookLiveProjection {
    pub stage: Option<String>,
    pub stage_detail: Option<String>,
    pub progress: JobProgressView,
}

pub(super) fn build_live_projection(job: &JobSnapshot, data_root: &Path) -> BookLiveProjection {
    let live_stage = load_live_stage_snapshot(job, data_root);
    let current = live_stage
        .as_ref()
        .and_then(|snapshot| snapshot.progress_current)
        .or(job.progress_current);
    let total = live_stage
        .as_ref()
        .and_then(|snapshot| snapshot.progress_total)
        .or(job.progress_total);
    BookLiveProjection {
        stage: live_stage
            .as_ref()
            .and_then(|snapshot| snapshot.stage.clone())
            .or_else(|| job.stage.clone()),
        stage_detail: live_stage
            .as_ref()
            .and_then(|snapshot| snapshot.stage_detail.clone())
            .or_else(|| job.stage_detail.clone()),
        progress: JobProgressView {
            current,
            total,
            percent: match (current, total) {
                (Some(current), Some(total)) if total > 0 => {
                    Some((current as f64 / total as f64) * 100.0)
                }
                _ => None,
            },
        },
    }
}
