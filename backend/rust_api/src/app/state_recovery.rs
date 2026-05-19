use anyhow::Result;
use tracing::warn;

use crate::config::AppConfig;
use crate::db::Db;
use crate::job_events::persist_job_with_resources;
use crate::job_runner::worker_process_exists;
use crate::models::{now_iso, JobFailureInfo, JobStatusKind};

pub(super) fn reconcile_stale_running_jobs(config: &AppConfig, db: &Db) -> Result<usize> {
    let running_jobs = db.list_job_process_records_with_status(&JobStatusKind::Running)?;
    let mut reconciled = 0usize;
    for job_record in running_jobs {
        let detail = match job_record.pid {
            Some(pid) if worker_process_exists(pid) => continue,
            Some(pid) => format!("后端启动时发现遗留 running 任务，但 worker 进程 {pid} 已不存在"),
            None => "后端启动时发现遗留 running 任务，但未记录 worker pid".to_string(),
        };
        let timestamp = now_iso();
        match db.get_job(&job_record.job_id) {
            Ok(mut job) => {
                job.append_log(&format!("ERROR: {detail}"));
                job.status = JobStatusKind::Failed;
                job.stage = Some("failed".to_string());
                job.stage_detail = Some("startup stale running job recovered".to_string());
                job.error = Some(detail.clone());
                job.updated_at = timestamp.clone();
                job.finished_at = Some(timestamp.clone());
                job.pid = None;
                job.sync_runtime_state();
                job.replace_failure_info(Some(JobFailureInfo {
                    stage: "startup_recovery".to_string(),
                    category: "worker_process_missing".to_string(),
                    code: None,
                    failed_stage: Some("startup_recovery".to_string()),
                    failure_code: Some("worker_process_missing".to_string()),
                    failure_category: Some("internal".to_string()),
                    provider_stage: None,
                    provider_code: None,
                    summary: "后端启动时回收了遗留 running 任务".to_string(),
                    root_cause: Some(detail.clone()),
                    retryable: true,
                    upstream_host: None,
                    provider: None,
                    suggestion: Some(
                        "该任务对应的 worker 已不在运行；请重新提交或手动重试".to_string(),
                    ),
                    last_log_line: Some(detail.clone()),
                    raw_excerpt: Some(detail.clone()),
                    raw_error_excerpt: Some(detail.clone()),
                    raw_diagnostic: None,
                    ai_diagnostic: None,
                }));
                persist_job_with_resources(db, &config.data_root, &config.output_root, &job)?;
            }
            Err(error) => {
                warn!(
                    "startup reconciliation fell back to raw DB recovery for {}: {}",
                    job_record.job_id, error
                );
                db.recover_stale_running_job(&job_record.job_id, &detail, &timestamp)?;
            }
        }
        reconciled += 1;
        warn!(
            "recovered stale running job during startup: {}",
            job_record.job_id
        );
    }
    if reconciled > 0 {
        warn!("startup reconciliation recovered {reconciled} stale running job(s)");
    }
    Ok(reconciled)
}
