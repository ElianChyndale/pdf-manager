use std::path::{Path, PathBuf};

use axum::extract::{Path as AxumPath, Query, State};
use axum::Json;
use serde::{Deserialize, Serialize};
use tokio::process::Command;

use crate::error::AppError;
use crate::models::ApiResponse;
use crate::AppState;

// ── Request models ──

#[derive(Deserialize)]
pub struct MergeRequest {
    pub upload_ids: Vec<String>,
}

#[derive(Deserialize)]
pub struct SplitRequest {
    pub upload_id: String,
    pub ranges: Vec<SplitRange>,
}

#[derive(Deserialize, Serialize)]
pub struct SplitRange {
    pub start: u32,
    pub end: u32,
    #[serde(default)]
    pub label: String,
}

#[derive(Deserialize)]
pub struct CompressRequest {
    pub upload_id: String,
    #[serde(default = "default_dpi")]
    pub dpi: u32,
}

fn default_dpi() -> u32 {
    150
}

#[derive(Deserialize)]
pub struct RotateRequest {
    pub upload_id: String,
    #[serde(default = "default_degrees")]
    pub degrees: u32,
    #[serde(default = "default_pages")]
    pub pages: String,
}

fn default_degrees() -> u32 {
    90
}
fn default_pages() -> String {
    "all".to_string()
}

#[derive(Deserialize)]
pub struct MetadataReadRequest {
    pub upload_id: String,
}

#[derive(Deserialize)]
pub struct MetadataWriteRequest {
    pub upload_id: String,
    pub title: Option<String>,
    pub author: Option<String>,
    pub subject: Option<String>,
    pub keywords: Option<String>,
}

#[derive(Deserialize)]
pub struct EncryptRequest {
    pub upload_id: String,
    pub user_password: Option<String>,
    pub owner_password: Option<String>,
}

#[derive(Deserialize)]
pub struct DecryptRequest {
    pub upload_id: String,
    pub password: String,
}

// ── Response models ──

#[derive(Serialize)]
pub struct PdfToolResult {
    pub download_url: String,
    pub file_name: String,
    pub file_size: u64,
    pub page_count: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<serde_json::Value>,
}

#[derive(Serialize)]
pub struct MetadataView {
    pub title: String,
    pub author: String,
    pub subject: String,
    pub keywords: String,
    pub creator: String,
    pub producer: String,
}

// ── Helpers ──

fn get_upload_path(state: &AppState, upload_id: &str) -> Result<PathBuf, AppError> {
    let upload = state
        .db
        .get_upload(upload_id)
        .map_err(|_| AppError::not_found(format!("Upload not found: {upload_id}")))?;
    Ok(Path::new(&upload.stored_path).to_path_buf())
}

async fn run_python_tool(
    state: &AppState,
    tool_name: &str,
    args: &[&str],
) -> Result<serde_json::Value, AppError> {
    let scripts_dir = &state.config.scripts_dir;
    let pdf_tools_cli = scripts_dir
        .join("services")
        .join("pdf_tools")
        .join("cli.py");

    let output = Command::new(&state.config.python_bin)
        .arg(&pdf_tools_cli)
        .arg(tool_name)
        .args(args)
        .output()
        .await
        .map_err(|e| AppError::internal(format!("Failed to run PDF tool: {e}")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(AppError::internal(if stderr.is_empty() {
            format!("PDF tool '{tool_name}' failed with status: {}", output.status)
        } else {
            stderr
        }));
    }

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    serde_json::from_str(&stdout)
        .map_err(|e| AppError::internal(format!("Failed to parse PDF tool output: {e}")))
}

fn extract_page_count(result: &serde_json::Value) -> u32 {
    result
        .get("page_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32
}

fn extract_file_size(result: &serde_json::Value) -> u64 {
    result
        .get("file_size")
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
}

fn extract_file_name(result: &serde_json::Value) -> String {
    result
        .get("file_name")
        .and_then(|v| v.as_str())
        .unwrap_or("output.pdf")
        .to_string()
}

fn make_result_download_path(result_id: &str) -> String {
    format!("/api/v1/pdf-tools/result/{result_id}")
}

fn generate_result_id() -> String {
    let ts = chrono::Utc::now().format("%Y%m%d%H%M%S").to_string();
    let rand = format!("{:06x}", fastrand::u32(..=0xFFFFFF));
    format!("{ts}-{rand}")
}

// ── Handlers ──

pub async fn merge_pdfs(
    State(state): State<AppState>,
    Json(req): Json<MergeRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    if req.upload_ids.len() < 2 {
        return Err(AppError::bad_request(
            "At least two PDFs are required to merge",
        ));
    }

    let mut input_paths: Vec<String> = Vec::new();
    for upload_id in &req.upload_ids {
        let path = get_upload_path(&state, upload_id)?;
        input_paths.push(path.to_string_lossy().to_string());
    }

    // Create temp output path
    let output_dir = state.config.data_root.join("pdf-tools-tmp");
    tokio::fs::create_dir_all(&output_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let output_path = output_dir.join("merged.pdf");

    let input_paths_json = serde_json::to_string(&input_paths)
        .map_err(|e| AppError::internal(format!("Failed to encode merge input paths: {e}")))?;
    let result = run_python_tool(
        &state,
        "merge",
        &[&input_paths_json, &output_path.to_string_lossy()],
    )
    .await?;

    let page_count = extract_page_count(&result);
    let file_size = extract_file_size(&result);
    let file_name = extract_file_name(&result);

    // Read output bytes and store in result store
    let pdf_bytes = tokio::fs::read(&output_path)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;

    // Store result in a simple temp directory with the file
    let result_dir = state.config.data_root.join("pdf-tools-results");
    tokio::fs::create_dir_all(&result_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_id = generate_result_id();
    let store_dir = result_dir.join(&result_id);
    tokio::fs::create_dir_all(&store_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    tokio::fs::write(store_dir.join(&file_name), &pdf_bytes)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;

    // Cleanup temp
    let _ = tokio::fs::remove_file(&output_path).await;

    Ok(Json(ApiResponse::ok(PdfToolResult {
        download_url: make_result_download_path(&result_id),
        file_name,
        file_size,
        page_count,
        details: None,
    })))
}

pub async fn split_pdf(
    State(state): State<AppState>,
    Json(req): Json<SplitRequest>,
) -> Result<Json<ApiResponse<Vec<PdfToolResult>>>, AppError> {
    if req.ranges.is_empty() {
        return Err(AppError::bad_request("At least one range is required"));
    }
    let input_path = get_upload_path(&state, &req.upload_id)?;
    let ranges_json = serde_json::to_string(&req.ranges)
        .map_err(|e| AppError::internal(e.to_string()))?;

    let result = run_python_tool(
        &state,
        "split",
        &[
            &input_path.to_string_lossy(),
            &ranges_json,
        ],
    )
    .await?;

    // Parse result as array of split results
    let results_array = result
        .as_array()
        .ok_or_else(|| AppError::internal("Expected array from split tool"))?;

    let mut tool_results = Vec::new();
    for item in results_array {
        tool_results.push(PdfToolResult {
            download_url: String::new(),
            file_name: extract_file_name(item),
            file_size: extract_file_size(item),
            page_count: extract_page_count(item),
            details: Some(item.clone()),
        });
    }

    Ok(Json(ApiResponse::ok(tool_results)))
}

pub async fn compress_pdf(
    State(state): State<AppState>,
    Json(req): Json<CompressRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    let input_path = get_upload_path(&state, &req.upload_id)?;
    let output_dir = state.config.data_root.join("pdf-tools-tmp");
    tokio::fs::create_dir_all(&output_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let output_path = output_dir.join("compressed.pdf");

    let result = run_python_tool(
        &state,
        "compress",
        &[
            &input_path.to_string_lossy(),
            &output_path.to_string_lossy(),
            &req.dpi.to_string(),
        ],
    )
    .await?;

    let page_count = extract_page_count(&result);
    let file_size = extract_file_size(&result);

    let pdf_bytes = tokio::fs::read(&output_path)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_dir = state.config.data_root.join("pdf-tools-results");
    tokio::fs::create_dir_all(&result_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_id = generate_result_id();
    let store_dir = result_dir.join(&result_id);
    tokio::fs::create_dir_all(&store_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let file_name = format!("compressed-{}.pdf", req.upload_id);
    tokio::fs::write(store_dir.join(&file_name), &pdf_bytes)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let _ = tokio::fs::remove_file(&output_path).await;

    Ok(Json(ApiResponse::ok(PdfToolResult {
        download_url: make_result_download_path(&result_id),
        file_name,
        file_size,
        page_count,
        details: Some(result),
    })))
}

pub async fn rotate_pdf(
    State(state): State<AppState>,
    Json(req): Json<RotateRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    let input_path = get_upload_path(&state, &req.upload_id)?;
    let output_dir = state.config.data_root.join("pdf-tools-tmp");
    tokio::fs::create_dir_all(&output_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let output_path = output_dir.join("rotated.pdf");

    let result = run_python_tool(
        &state,
        "rotate",
        &[
            &input_path.to_string_lossy(),
            &output_path.to_string_lossy(),
            &req.degrees.to_string(),
            &req.pages,
        ],
    )
    .await?;

    let page_count = extract_page_count(&result);
    let file_size = extract_file_size(&result);

    let pdf_bytes = tokio::fs::read(&output_path)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_dir = state.config.data_root.join("pdf-tools-results");
    tokio::fs::create_dir_all(&result_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_id = generate_result_id();
    let store_dir = result_dir.join(&result_id);
    tokio::fs::create_dir_all(&store_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let file_name = format!("rotated-{}.pdf", req.upload_id);
    tokio::fs::write(store_dir.join(&file_name), &pdf_bytes)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let _ = tokio::fs::remove_file(&output_path).await;

    Ok(Json(ApiResponse::ok(PdfToolResult {
        download_url: make_result_download_path(&result_id),
        file_name,
        page_count,
        file_size,
        details: Some(result),
    })))
}

pub async fn read_metadata(
    State(state): State<AppState>,
    Query(req): Query<MetadataReadRequest>,
) -> Result<Json<ApiResponse<MetadataView>>, AppError> {
    let input_path = get_upload_path(&state, &req.upload_id)?;

    let result = run_python_tool(
        &state,
        "read-metadata",
        &[&input_path.to_string_lossy()],
    )
    .await?;

    Ok(Json(ApiResponse::ok(MetadataView {
        title: result.get("title").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        author: result.get("author").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        subject: result.get("subject").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        keywords: result.get("keywords").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        creator: result.get("creator").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        producer: result.get("producer").and_then(|v| v.as_str()).unwrap_or("").to_string(),
    })))
}

pub async fn write_metadata(
    State(state): State<AppState>,
    Json(req): Json<MetadataWriteRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    let input_path = get_upload_path(&state, &req.upload_id)?;
    let output_dir = state.config.data_root.join("pdf-tools-tmp");
    tokio::fs::create_dir_all(&output_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let output_path = output_dir.join("metadata.pdf");

    let mut updates = serde_json::Map::new();
    if let Some(v) = &req.title { updates.insert("title".into(), serde_json::Value::String(v.clone())); }
    if let Some(v) = &req.author { updates.insert("author".into(), serde_json::Value::String(v.clone())); }
    if let Some(v) = &req.subject { updates.insert("subject".into(), serde_json::Value::String(v.clone())); }
    if let Some(v) = &req.keywords { updates.insert("keywords".into(), serde_json::Value::String(v.clone())); }
    let updates_json = serde_json::to_string(&updates)
        .map_err(|e| AppError::internal(e.to_string()))?;

    let result = run_python_tool(
        &state,
        "write-metadata",
        &[
            &input_path.to_string_lossy(),
            &output_path.to_string_lossy(),
            &updates_json,
        ],
    )
    .await?;

    let page_count = extract_page_count(&result);
    let file_size = extract_file_size(&result);

    let pdf_bytes = tokio::fs::read(&output_path)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_dir = state.config.data_root.join("pdf-tools-results");
    tokio::fs::create_dir_all(&result_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_id = generate_result_id();
    let store_dir = result_dir.join(&result_id);
    tokio::fs::create_dir_all(&store_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let file_name = format!("metadata-{}.pdf", req.upload_id);
    tokio::fs::write(store_dir.join(&file_name), &pdf_bytes)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let _ = tokio::fs::remove_file(&output_path).await;

    Ok(Json(ApiResponse::ok(PdfToolResult {
        download_url: make_result_download_path(&result_id),
        file_name,
        page_count,
        file_size,
        details: Some(result),
    })))
}

pub async fn encrypt_pdf(
    State(state): State<AppState>,
    Json(req): Json<EncryptRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    let input_path = get_upload_path(&state, &req.upload_id)?;
    let output_dir = state.config.data_root.join("pdf-tools-tmp");
    tokio::fs::create_dir_all(&output_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let output_path = output_dir.join("encrypted.pdf");

    let mut params = serde_json::Map::new();
    if let Some(pw) = &req.user_password {
        params.insert("user_pw".into(), serde_json::Value::String(pw.clone()));
    }
    if let Some(pw) = &req.owner_password {
        params.insert("owner_pw".into(), serde_json::Value::String(pw.clone()));
    }
    let params_json = serde_json::to_string(&params)
        .map_err(|e| AppError::internal(e.to_string()))?;

    let result = run_python_tool(
        &state,
        "encrypt",
        &[
            &input_path.to_string_lossy(),
            &output_path.to_string_lossy(),
            &params_json,
        ],
    )
    .await?;

    let page_count = extract_page_count(&result);
    let file_size = extract_file_size(&result);

    let pdf_bytes = tokio::fs::read(&output_path)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_dir = state.config.data_root.join("pdf-tools-results");
    tokio::fs::create_dir_all(&result_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_id = generate_result_id();
    let store_dir = result_dir.join(&result_id);
    tokio::fs::create_dir_all(&store_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let file_name = format!("encrypted-{}.pdf", req.upload_id);
    tokio::fs::write(store_dir.join(&file_name), &pdf_bytes)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let _ = tokio::fs::remove_file(&output_path).await;

    Ok(Json(ApiResponse::ok(PdfToolResult {
        download_url: make_result_download_path(&result_id),
        file_name,
        page_count,
        file_size,
        details: Some(result),
    })))
}

pub async fn decrypt_pdf(
    State(state): State<AppState>,
    Json(req): Json<DecryptRequest>,
) -> Result<Json<ApiResponse<PdfToolResult>>, AppError> {
    let input_path = get_upload_path(&state, &req.upload_id)?;
    let output_dir = state.config.data_root.join("pdf-tools-tmp");
    tokio::fs::create_dir_all(&output_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let output_path = output_dir.join("decrypted.pdf");

    let result = run_python_tool(
        &state,
        "decrypt",
        &[
            &input_path.to_string_lossy(),
            &output_path.to_string_lossy(),
            &req.password,
        ],
    )
    .await?;

    let page_count = extract_page_count(&result);
    let file_size = extract_file_size(&result);

    let pdf_bytes = tokio::fs::read(&output_path)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_dir = state.config.data_root.join("pdf-tools-results");
    tokio::fs::create_dir_all(&result_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let result_id = generate_result_id();
    let store_dir = result_dir.join(&result_id);
    tokio::fs::create_dir_all(&store_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let file_name = format!("decrypted-{}.pdf", req.upload_id);
    tokio::fs::write(store_dir.join(&file_name), &pdf_bytes)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let _ = tokio::fs::remove_file(&output_path).await;

    Ok(Json(ApiResponse::ok(PdfToolResult {
        download_url: make_result_download_path(&result_id),
        file_name,
        page_count,
        file_size,
        details: Some(result),
    })))
}

pub async fn download_result(
    State(state): State<AppState>,
    AxumPath(result_id): AxumPath<String>,
) -> Result<axum::response::Response, AppError> {
    use axum::body::Body;
    use axum::http::header;

    let result_dir = state.config.data_root.join("pdf-tools-results").join(&result_id);
    if !result_dir.exists() {
        return Err(AppError::not_found("Result not found or expired"));
    }

    let mut dir = tokio::fs::read_dir(&result_dir)
        .await
        .map_err(|e| AppError::internal(e.to_string()))?;
    let mut file_path = None;
    while let Some(entry) = dir.next_entry().await.map_err(|e| AppError::internal(e.to_string()))? {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) == Some("pdf") {
            file_path = Some(path);
            break;
        }
    }

    match file_path {
        Some(path) => {
            let file_name = path.file_name().and_then(|n| n.to_str()).unwrap_or("result.pdf").to_string();
            let data = tokio::fs::read(&path)
                .await
                .map_err(|e| AppError::internal(e.to_string()))?;
            Ok(axum::response::Response::builder()
                .status(200)
                .header(header::CONTENT_TYPE, "application/pdf")
                .header(header::CONTENT_DISPOSITION, format!("attachment; filename=\"{file_name}\""))
                .body(Body::from(data))
                .unwrap())
        }
        None => Err(AppError::not_found("Result file not found")),
    }
}
