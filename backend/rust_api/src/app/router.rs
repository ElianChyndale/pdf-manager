use axum::extract::DefaultBodyLimit;
use axum::middleware;
use axum::routing::{get, post};
use axum::Router;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;

use crate::app::AppState;
use crate::auth;
use crate::routes::glossaries;
use crate::routes::health;
use crate::routes::jobs;
use crate::routes::library;
use crate::routes::pdf_tools;
use crate::routes::providers;
use crate::routes::uploads;

pub fn build_app(state: AppState) -> Router {
    let api_routes = Router::new()
        .route(
            "/api/v1/ocr/jobs",
            post(jobs::create_ocr_job)
                .get(jobs::list_ocr_jobs)
                .layer(DefaultBodyLimit::disable()),
        )
        .route("/api/v1/ocr/jobs/:job_id", get(jobs::get_ocr_job))
        .route(
            "/api/v1/ocr/jobs/:job_id/events",
            get(jobs::get_ocr_job_events),
        )
        .route(
            "/api/v1/ocr/jobs/:job_id/artifacts",
            get(jobs::get_ocr_job_artifacts),
        )
        .route(
            "/api/v1/ocr/jobs/:job_id/artifacts-manifest",
            get(jobs::get_ocr_job_artifacts_manifest),
        )
        .route(
            "/api/v1/ocr/jobs/:job_id/artifacts/:artifact_key",
            get(jobs::download_ocr_artifact_by_key),
        )
        .route(
            "/api/v1/ocr/jobs/:job_id/normalized-document",
            get(jobs::download_ocr_normalized_document),
        )
        .route(
            "/api/v1/ocr/jobs/:job_id/normalization-report",
            get(jobs::download_ocr_normalization_report),
        )
        .route(
            "/api/v1/ocr/jobs/:job_id/cancel",
            post(jobs::cancel_ocr_job),
        )
        .route(
            "/api/v1/uploads",
            post(uploads::upload_pdf).layer(DefaultBodyLimit::disable()),
        )
        .route(
            "/api/v1/glossaries/parse-csv",
            post(glossaries::parse_glossary_csv_route),
        )
        .route(
            "/api/v1/glossaries",
            post(glossaries::create_glossary_route).get(glossaries::list_glossaries_route),
        )
        .route(
            "/api/v1/glossaries/:glossary_id",
            get(glossaries::get_glossary_route)
                .put(glossaries::update_glossary_route)
                .delete(glossaries::delete_glossary_route),
        )
        .route("/api/v1/library/books", get(library::list_books))
        .route("/api/v1/library/books/delete", post(library::delete_books))
        .route(
            "/api/v1/library/books/:job_id",
            get(library::get_book).delete(library::delete_book),
        )
        .route(
            "/api/v1/library/books/:job_id/cover",
            get(library::download_book_cover),
        )
        .route(
            "/api/v1/library/books/:job_id/thumbnail",
            get(library::download_book_thumbnail),
        )
        // ── PDF Tools ──
        .route("/api/v1/pdf-tools/merge", post(pdf_tools::merge_pdfs))
        .route("/api/v1/pdf-tools/split", post(pdf_tools::split_pdf))
        .route("/api/v1/pdf-tools/compress", post(pdf_tools::compress_pdf))
        .route("/api/v1/pdf-tools/rotate", post(pdf_tools::rotate_pdf))
        .route("/api/v1/pdf-tools/metadata", get(pdf_tools::read_metadata).post(pdf_tools::write_metadata))
        .route("/api/v1/pdf-tools/encrypt", post(pdf_tools::encrypt_pdf))
        .route("/api/v1/pdf-tools/decrypt", post(pdf_tools::decrypt_pdf))
        .route("/api/v1/pdf-tools/result/:result_id", get(pdf_tools::download_result))
        // ── Jobs ──
        .route("/api/v1/jobs", post(jobs::create_job).get(jobs::list_jobs))
        .route("/api/v1/jobs/:job_id", get(jobs::get_job))
        .route("/api/v1/jobs/:job_id/events", get(jobs::get_job_events))
        .route(
            "/api/v1/jobs/:job_id/reader/regions",
            get(jobs::get_reader_regions),
        )
        .route(
            "/api/v1/jobs/:job_id/reader/metadata",
            get(jobs::get_reader_metadata),
        )
        .route(
            "/api/v1/jobs/:job_id/diagnostics",
            get(jobs::get_job_diagnostics),
        )
        .route(
            "/api/v1/jobs/:job_id/resume-plan",
            get(jobs::get_resume_plan),
        )
        .route("/api/v1/jobs/:job_id/resume", post(jobs::resume_job))
        .route(
            "/api/v1/jobs/:job_id/translation/diagnostics",
            get(jobs::get_translation_diagnostics),
        )
        .route(
            "/api/v1/jobs/:job_id/translation/items",
            get(jobs::list_translation_items),
        )
        .route(
            "/api/v1/jobs/:job_id/translation/items/:item_id",
            get(jobs::get_translation_item),
        )
        .route(
            "/api/v1/jobs/:job_id/translation/items/:item_id/replay",
            post(jobs::replay_translation_item_route),
        )
        .route(
            "/api/v1/jobs/:job_id/artifacts",
            get(jobs::get_job_artifacts),
        )
        .route(
            "/api/v1/jobs/:job_id/artifacts-manifest",
            get(jobs::get_job_artifacts_manifest),
        )
        .route(
            "/api/v1/jobs/:job_id/artifacts/:artifact_key",
            get(jobs::download_artifact_by_key),
        )
        .route("/api/v1/jobs/:job_id/pdf", get(jobs::download_pdf))
        .route("/api/v1/jobs/:job_id/cover", get(jobs::download_cover))
        .route(
            "/api/v1/jobs/:job_id/thumbnail",
            get(jobs::download_thumbnail),
        )
        .route(
            "/api/v1/jobs/:job_id/preview/pages/:page",
            get(jobs::download_page_preview),
        )
        .route(
            "/api/v1/jobs/:job_id/normalized-document",
            get(jobs::download_normalized_document),
        )
        .route(
            "/api/v1/jobs/:job_id/normalization-report",
            get(jobs::download_normalization_report),
        )
        .route(
            "/api/v1/jobs/:job_id/markdown",
            get(jobs::download_markdown),
        )
        .route(
            "/api/v1/jobs/:job_id/markdown/images/*path",
            get(jobs::download_markdown_image),
        )
        .route("/api/v1/jobs/:job_id/download", get(jobs::download_bundle))
        .route("/api/v1/jobs/:job_id/cancel", post(jobs::cancel_job))
        .route("/api/v1/jobs/:job_id/rerun", post(jobs::rerun_job))
        .route(
            "/api/v1/providers/mineru/validate-token",
            post(providers::validate_mineru_token),
        )
        .route(
            "/api/v1/providers/paddle/validate-token",
            post(providers::validate_paddle_token),
        )
        .route(
            "/api/v1/providers/deepseek/validate-token",
            post(providers::validate_deepseek_token),
        )
        .route(
            "/api/v1/providers/deepseek/balance",
            post(providers::query_deepseek_balance),
        )
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            auth::require_api_key,
        ));

    Router::new()
        .route("/health", get(health::health))
        .merge(api_routes)
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state)
}

pub fn build_simple_app(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health::health))
        .route(
            "/api/v1/translate/bundle",
            post(jobs::translate_bundle).layer(DefaultBodyLimit::disable()),
        )
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            auth::require_api_key,
        ))
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state)
}
