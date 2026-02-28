mod pipeline;

use std::{env, net::SocketAddr};

use axum::{
    body::Body,
    http::{Request, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Json},
    Router,
};
use tower_http::cors::{Any, CorsLayer};
use tower_http::services::{ServeDir, ServeFile};
use tracing_subscriber::EnvFilter;

async fn auth(req: Request<Body>, next: Next) -> impl IntoResponse {
    let api_key = env::var("API_KEY").unwrap_or_default();

    // Dev mode: no key configured, allow everything
    if api_key.is_empty() {
        return next.run(req).await.into_response();
    }

    // Check Authorization header first, then fall back to ?token= query param
    // (EventSource/SSE can't send custom headers)
    let token = req
        .headers()
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .unwrap_or("")
        .to_string();

    let token = if token.is_empty() {
        req.uri()
            .query()
            .unwrap_or("")
            .split('&')
            .find_map(|pair| pair.strip_prefix("token="))
            .unwrap_or("")
            .to_string()
    } else {
        token
    };

    if subtle_eq(&token, &api_key) {
        next.run(req).await.into_response()
    } else {
        (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({"detail": "Invalid or missing API key"})),
        )
            .into_response()
    }
}

fn subtle_eq(a: &str, b: &str) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.bytes().zip(b.bytes()).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    dotenvy::dotenv().ok();

    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    // Auth only gates /api/ routes (not static files)
    let api = pipeline::router()
        .layer(middleware::from_fn(auth));

    // Static file serving for frontend (SPA fallback to index.html)
    let static_service = ServeDir::new("static")
        .not_found_service(ServeFile::new("static/index.html"));

    let app = Router::new()
        .merge(api)
        .fallback_service(static_service)
        .layer(cors);

    let api_key = env::var("API_KEY").unwrap_or_default();
    if api_key.is_empty() {
        tracing::warn!("API_KEY not set — auth disabled (dev mode)");
    } else {
        tracing::info!("API key auth enabled");
    }

    let addr = SocketAddr::from(([0, 0, 0, 0], 8000));
    tracing::info!("Orchestrator listening on http://{addr}");

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
