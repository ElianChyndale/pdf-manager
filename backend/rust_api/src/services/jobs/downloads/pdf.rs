use std::path::{Path, PathBuf};

use crate::error::AppError;
use crate::models::JobSnapshot;

use super::paths::job_artifacts_dir;
use super::QueryJobsDeps;

pub(super) fn linearized_pdf_or_original(
    deps: &QueryJobsDeps<'_>,
    job: &JobSnapshot,
    input_pdf: &Path,
    label: &str,
) -> Result<PathBuf, AppError> {
    if !input_pdf.exists() || !input_pdf.is_file() {
        return Ok(input_pdf.to_path_buf());
    }
    let output_dir = job_artifacts_dir(deps, job)?;
    let safe_label = label.replace('/', "_");
    let output_pdf = output_dir.join(format!("{safe_label}.linearized.pdf"));
    let input_meta = std::fs::metadata(input_pdf)?;
    if output_pdf.exists() && output_pdf.is_file() {
        let output_meta = std::fs::metadata(&output_pdf)?;
        if output_meta.modified().ok() >= input_meta.modified().ok() {
            return Ok(output_pdf);
        }
    }
    let tmp_pdf = output_pdf.with_extension("pdf.tmp");
    let linearized = linearize_pdf_with_qpdf(input_pdf, &tmp_pdf)?;
    if !linearized || !tmp_pdf.exists() {
        let _ = std::fs::remove_file(&tmp_pdf);
        return Ok(input_pdf.to_path_buf());
    }
    std::fs::rename(&tmp_pdf, &output_pdf)?;
    Ok(output_pdf)
}

fn linearize_pdf_with_qpdf(input_pdf: &Path, output_pdf: &Path) -> Result<bool, AppError> {
    let Some(qpdf) = find_tool("qpdf") else {
        return Ok(false);
    };
    let status = std::process::Command::new(qpdf)
        .arg("--linearize")
        .arg(input_pdf)
        .arg(output_pdf)
        .status()
        .map_err(|error| AppError::internal(format!("failed to run qpdf: {error}")))?;
    Ok(status.success() && output_pdf.exists())
}

fn find_tool(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|dir| dir.join(name))
        .find(|candidate| candidate.exists() && candidate.is_file())
}
