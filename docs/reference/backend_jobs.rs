// ============================================================
// backend/src/jobs.rs
// Add this module to your Rust backend.
// Cargo.toml additions required:
//   tokio = { features = ["sync", "rt-multi-thread"] }
//   tower-http = { features = ["cors"] }
//   axum = { features = ["multipart"] }
//   uuid = { features = ["v4"] }
//   serde_json = "1"
// ============================================================

use axum::{
    extract::{Multipart, Path, State},
    http::StatusCode,
    response::{
        sse::{Event, Sse},
        IntoResponse, Json,
    },
    routing::{get, post},
    Router,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    convert::Infallible,
    sync::Arc,
    time::Duration,
};
use tokio::sync::{broadcast, RwLock};
use tokio_stream::{wrappers::BroadcastStream, StreamExt};
use tower_http::cors::{Any, CorsLayer};
use uuid::Uuid;

// ─── Types ───────────────────────────────────────────────────

#[derive(Clone, Serialize)]
#[serde(tag = "event", content = "data", rename_all = "snake_case")]
pub enum PipelineEvent {
    PhaseStart { phase: String },
    TranscriptComplete { text: String, duration_ms: u64 },
    DiarizationComplete { segments: Vec<Segment> },
    AnalysisComplete { decisions: Vec<Decision>, ambiguities: Vec<Ambiguity>, action_items: Vec<String> },
    Done,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Segment {
    pub speaker: String,
    pub start: f64,
    pub end: f64,
    pub text: String,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Decision {
    pub timestamp: f64,
    pub summary: String,
    pub proposed_by: String,
    pub seconded_by: Option<String>,
    pub dissent_by: Option<String>,
    pub status: String, // "locked" | "open" | "contested"
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Ambiguity {
    pub timestamp: f64,
    #[serde(rename = "type")]
    pub kind: String,
    pub quote: String,
    pub speaker: String,
    pub confidence: f64,
    pub candidates: Vec<String>,
}

#[derive(Clone)]
struct JobHandle {
    tx: broadcast::Sender<PipelineEvent>,
    // Latest polled result (for polling fallback)
    result: Arc<RwLock<JobResult>>,
}

#[derive(Clone, Default, Serialize)]
struct JobResult {
    status: String,           // "processing" | "complete" | "error"
    phase: Option<String>,
    transcript: Option<String>,
    segments: Option<Vec<Segment>>,
    decisions: Option<Vec<Decision>>,
    ambiguities: Option<Vec<Ambiguity>>,
    action_items: Option<Vec<String>>,
}

type JobStore = Arc<RwLock<HashMap<String, JobHandle>>>;

// ─── Router ──────────────────────────────────────────────────

/// Call this from main.rs to build the job routes.
/// Mount at "/" or merge into your existing router.
pub fn job_router() -> Router {
    let store: JobStore = Arc::new(RwLock::new(HashMap::new()));

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    Router::new()
        .route("/jobs", post(create_job))
        .route("/jobs/:id/events", get(stream_job))
        .route("/jobs/:id/result", get(poll_job))
        .with_state(store)
        .layer(cors)
}

// ─── Handlers ─────────────────────────────────────────────────

/// POST /jobs  →  { job_id: "..." }
async fn create_job(
    State(store): State<JobStore>,
    mut multipart: Multipart,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    // Read audio bytes from multipart field "audio"
    let mut audio_bytes = Vec::new();
    while let Some(field) = multipart.next_field().await.unwrap_or(None) {
        if field.name() == Some("audio") {
            audio_bytes = field.bytes().await
                .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?
                .to_vec();
            break;
        }
    }

    if audio_bytes.is_empty() {
        return Err((StatusCode::BAD_REQUEST, "No audio field".into()));
    }

    let job_id = Uuid::new_v4().to_string();
    let (tx, _) = broadcast::channel(64);
    let result = Arc::new(RwLock::new(JobResult {
        status: "processing".into(),
        phase: Some("transcribing".into()),
        ..Default::default()
    }));

    let handle = JobHandle { tx: tx.clone(), result: result.clone() };
    store.write().await.insert(job_id.clone(), handle);

    // Spawn background pipeline
    let jid = job_id.clone();
    tokio::spawn(async move {
        run_pipeline(tx, result, audio_bytes, jid).await;
    });

    Ok(Json(serde_json::json!({ "job_id": job_id })))
}

/// GET /jobs/:id/events  →  SSE stream
async fn stream_job(
    State(store): State<JobStore>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    let rx = store.read().await
        .get(&id)
        .map(|h| h.tx.subscribe());

    let Some(rx) = rx else {
        return Sse::new(futures::stream::empty()).into_response();
    };

    let stream = BroadcastStream::new(rx)
        .filter_map(|msg| async move {
            let ev = msg.ok()?;
            let (event_name, data) = match &ev {
                PipelineEvent::PhaseStart { phase } =>
                    ("phase_start", serde_json::json!({ "phase": phase })),
                PipelineEvent::TranscriptComplete { text, duration_ms } =>
                    ("transcript_complete", serde_json::json!({ "text": text, "duration_ms": duration_ms })),
                PipelineEvent::DiarizationComplete { segments } =>
                    ("diarization_complete", serde_json::json!({ "segments": segments })),
                PipelineEvent::AnalysisComplete { decisions, ambiguities, action_items } =>
                    ("analysis_complete", serde_json::json!({
                        "decisions": decisions,
                        "ambiguities": ambiguities,
                        "action_items": action_items
                    })),
                PipelineEvent::Done =>
                    ("done", serde_json::json!({})),
            };
            Some(Ok::<Event, Infallible>(
                Event::default()
                    .event(event_name)
                    .data(serde_json::to_string(&data).unwrap_or_default())
            ))
        });

    Sse::new(stream)
        .keep_alive(
            axum::response::sse::KeepAlive::new()
                .interval(Duration::from_secs(15))
                .text("keep-alive")
        )
        .into_response()
}

/// GET /jobs/:id/result  →  polling fallback for clients without SSE support
async fn poll_job(
    State(store): State<JobStore>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    match store.read().await.get(&id) {
        Some(h) => Json(h.result.read().await.clone()).into_response(),
        None => StatusCode::NOT_FOUND.into_response(),
    }
}

// ─── Pipeline orchestration ────────────────────────────────────
// NOTE: Replace the HTTP calls below with your actual Voxtral/Pyannote client calls.

async fn run_pipeline(
    tx: broadcast::Sender<PipelineEvent>,
    result: Arc<RwLock<JobResult>>,
    audio_bytes: Vec<u8>,
    _job_id: String,
) {
    // ── Phase 1: Transcription (Voxtral, same process or HTTP to Rust endpoint) ──
    let _ = tx.send(PipelineEvent::PhaseStart { phase: "transcribing".into() });
    result.write().await.phase = Some("transcribing".into());

    // TODO: Call your existing Voxtral transcription logic here.
    // Example (if transcriber is a separate function):
    //   let transcript_result = transcribe(audio_bytes.clone()).await;
    let transcript_text = call_voxtral(&audio_bytes).await;

    result.write().await.transcript = Some(transcript_text.clone());
    let _ = tx.send(PipelineEvent::TranscriptComplete {
        text: transcript_text.clone(),
        duration_ms: 0, // fill from actual timing
    });

    // ── Phase 2: Diarization (Python GPU service) ──
    let _ = tx.send(PipelineEvent::PhaseStart { phase: "diarizing".into() });
    result.write().await.phase = Some("diarizing".into());

    // IMPORTANT: The Python GPU service exposes /diarize and /embed separately.
    // Rust orchestrates both calls; the frontend sees only one logical "diarizing" phase.
    let segments = call_python_diarize(&audio_bytes).await;
    let _embeddings = call_python_embed(&audio_bytes).await; // used internally for speaker ID

    result.write().await.segments = Some(segments.clone());
    let _ = tx.send(PipelineEvent::DiarizationComplete { segments: segments.clone() });

    // ── Phase 3: Analysis (Mistral Large 3) ──
    let _ = tx.send(PipelineEvent::PhaseStart { phase: "analyzing".into() });
    result.write().await.phase = Some("analyzing".into());

    let (decisions, ambiguities, action_items) =
        call_mistral_analysis(&transcript_text, &segments).await;

    result.write().await.decisions = Some(decisions.clone());
    result.write().await.ambiguities = Some(ambiguities.clone());
    result.write().await.action_items = Some(action_items.clone());

    let _ = tx.send(PipelineEvent::AnalysisComplete {
        decisions,
        ambiguities,
        action_items,
    });

    // ── Done ──
    result.write().await.status = "complete".into();
    result.write().await.phase = None;
    let _ = tx.send(PipelineEvent::Done);
}

// ─── Stub functions — replace with real implementations ───────

async fn call_voxtral(_audio: &[u8]) -> String {
    // POST http://localhost:8081/transcribe  (your existing Rust/Voxtral endpoint)
    // For same-process: call the transcription function directly.
    "Placeholder transcript text.".into()
}

async fn call_python_diarize(_audio: &[u8]) -> Vec<Segment> {
    // POST http://localhost:8082/diarize  (Python GPU service)
    vec![]
}

async fn call_python_embed(_audio: &[u8]) -> Vec<f32> {
    // POST http://localhost:8082/embed  (Python GPU service)
    vec![]
}

async fn call_mistral_analysis(_transcript: &str, _segments: &[Segment]) -> (Vec<Decision>, Vec<Ambiguity>, Vec<String>) {
    (vec![], vec![], vec![])
}
