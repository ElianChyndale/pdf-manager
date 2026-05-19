use crate::error::AppError;
use crate::job_failure::classify_job_failure;
use crate::models::{
    JobDiagnosticsView, JobFailureInfo, JobResumePlanView, JobSnapshot, WorkflowKind,
};

use super::super::super::presentation::load_supported_job;
use super::super::JobsFacade;

impl<'a> JobsFacade<'a> {
    pub fn job_diagnostics_view(&self, job_id: &str) -> Result<JobDiagnosticsView, AppError> {
        let job = load_supported_job(self.query.db, self.query.data_root, job_id)?;
        Ok(build_job_diagnostics_view(&job))
    }

    pub fn resume_plan_view(&self, job_id: &str) -> Result<JobResumePlanView, AppError> {
        let job = load_supported_job(self.query.db, self.query.data_root, job_id)?;
        Ok(build_resume_plan_view(&job))
    }
}

fn build_job_diagnostics_view(job: &JobSnapshot) -> JobDiagnosticsView {
    let failure = resolved_failure(job);
    let resume_plan = build_resume_plan_view(job);
    match failure {
        Some(failure) => JobDiagnosticsView {
            failed_stage: Some(failure.failed_stage_value().to_string()),
            failed_substage: failure.provider_stage.clone(),
            summary: failure.summary.clone(),
            detail: failure
                .root_cause
                .clone()
                .or_else(|| failure.raw_excerpt.clone())
                .or_else(|| failure.raw_error_excerpt.clone())
                .or_else(|| failure.last_log_line.clone()),
            suggestion: failure.suggestion.clone(),
            retryable: failure.retryable,
            resume_available: resume_plan.can_resume,
        },
        None => JobDiagnosticsView {
            failed_stage: job.stage.clone(),
            failed_substage: None,
            summary: if matches!(job.status, crate::models::JobStatusKind::Failed) {
                job.error
                    .clone()
                    .filter(|value| !value.trim().is_empty())
                    .unwrap_or_else(|| "任务失败，但暂未识别出明确原因".to_string())
            } else {
                "任务当前没有失败诊断".to_string()
            },
            detail: job.error.clone(),
            suggestion: None,
            retryable: false,
            resume_available: resume_plan.can_resume,
        },
    }
}

fn build_resume_plan_view(job: &JobSnapshot) -> JobResumePlanView {
    let Some(artifacts) = job.artifacts.as_ref() else {
        return unavailable_plan(job, "source job has no reusable artifacts");
    };
    if has_text(&artifacts.translations_dir) && has_text(&artifacts.source_pdf) {
        return JobResumePlanView {
            can_resume: true,
            job_id: job.job_id.clone(),
            from_stage: Some("render".to_string()),
            resume_workflow: Some(WorkflowKind::Render),
            reuses_artifacts: vec![
                "source_pdf".to_string(),
                "translations_dir".to_string(),
                "normalized_document_json".to_string(),
            ],
            reruns_stages: vec!["rendering".to_string()],
            reason: None,
        };
    }
    if has_text(&artifacts.normalized_document_json) && has_text(&artifacts.source_pdf) {
        return JobResumePlanView {
            can_resume: true,
            job_id: job.job_id.clone(),
            from_stage: Some("translate".to_string()),
            resume_workflow: Some(WorkflowKind::Book),
            reuses_artifacts: vec![
                "source_pdf".to_string(),
                "normalized_document_json".to_string(),
                "normalization_report_json".to_string(),
            ],
            reruns_stages: vec!["translation".to_string(), "rendering".to_string()],
            reason: None,
        };
    }
    unavailable_plan(
        job,
        "need translations_dir+source_pdf or normalized_document_json+source_pdf",
    )
}

fn unavailable_plan(job: &JobSnapshot, reason: &str) -> JobResumePlanView {
    JobResumePlanView {
        can_resume: false,
        job_id: job.job_id.clone(),
        from_stage: None,
        resume_workflow: None,
        reuses_artifacts: Vec::new(),
        reruns_stages: Vec::new(),
        reason: Some(reason.to_string()),
    }
}

fn resolved_failure(job: &JobSnapshot) -> Option<JobFailureInfo> {
    job.failure
        .clone()
        .map(JobFailureInfo::with_formal_fields)
        .or_else(|| classify_job_failure(job).map(JobFailureInfo::with_formal_fields))
}

fn has_text(value: &Option<String>) -> bool {
    value
        .as_deref()
        .map(str::trim)
        .is_some_and(|item| !item.is_empty())
}
