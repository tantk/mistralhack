use axum::{
    extract::{Multipart, Path, State},
    http::StatusCode,
    response::{
        sse::{Event, KeepAlive, Sse},
        IntoResponse, Json,
    },
    routing::{get, post},
    Router,
};
use futures::stream::Stream;
use std::{
    convert::Infallible,
    pin::Pin,
    task::{Context, Poll},
    time::Duration,
};
use tokio::sync::broadcast;
use uuid::Uuid;

use super::orchestrator::run_pipeline;
use super::transcription::transcribe_audio;
use super::types::*;
use super::voiceprint::SharedVoiceprintStore;
use std::sync::Arc;
use tokio::sync::RwLock;

use reqwest;

// ─── App state ──────────────────────────────────────────────────────

#[derive(Clone)]
pub struct AppState {
    pub jobs: JobStore,
    pub voiceprints: SharedVoiceprintStore,
    pub gpu_health: GpuHealthCache,
}

// ─── Router ─────────────────────────────────────────────────────────

pub fn router(voiceprint_store: SharedVoiceprintStore) -> Router {
    let gpu_health = GpuHealthCache::new();
    {
        let gh = gpu_health.clone();
        tokio::spawn(async move { gh.warm().await });
    }

    let state = AppState {
        jobs: Arc::new(RwLock::new(std::collections::HashMap::new())),
        voiceprints: voiceprint_store,
        gpu_health,
    };

    Router::new()
        .route("/api/transcribe", post(transcribe))
        .route("/api/jobs", post(create_job))
        .route("/api/jobs/{id}/events", get(stream_job))
        .route("/api/jobs/{id}/result", get(poll_job))
        .route("/api/speakers/enroll", post(enroll_speaker))
        .route("/api/speakers", get(list_speakers))
        .with_state(state)
}

// ─── Handlers ───────────────────────────────────────────────────────

async fn create_job(
    State(state): State<AppState>,
    mut multipart: Multipart,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let mut audio_bytes = Vec::new();
    let mut attendees: Vec<String> = Vec::new();

    while let Ok(Some(field)) = multipart.next_field().await {
        match field.name() {
            Some("audio") => {
                audio_bytes = field
                    .bytes()
                    .await
                    .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?
                    .to_vec();
            }
            Some("attendees") => {
                let text = field
                    .text()
                    .await
                    .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;
                // Parse as JSON array of strings
                if let Ok(parsed) = serde_json::from_str::<Vec<String>>(&text) {
                    attendees = parsed;
                } else {
                    tracing::warn!("Failed to parse attendees field as JSON array, ignoring");
                }
            }
            _ => {}
        }
    }

    if audio_bytes.is_empty() {
        return Err((StatusCode::BAD_REQUEST, "No audio field".into()));
    }

    let job_id = Uuid::new_v4().to_string();
    let (tx, _) = broadcast::channel::<PipelineEvent>(256);
    let result = Arc::new(RwLock::new(JobResult {
        status: "processing".into(),
        phase: Some("transcribing".into()),
        ..Default::default()
    }));

    let handle = JobHandle {
        tx: tx.clone(),
        result: result.clone(),
    };
    state.jobs.write().await.insert(job_id.clone(), handle);

    tracing::info!(job_id = %job_id, bytes = audio_bytes.len(), attendees = attendees.len(), "Job created");

    let voiceprints = state.voiceprints.clone();
    let gpu_health = state.gpu_health.clone();
    tokio::spawn(run_pipeline(tx, result, audio_bytes, job_id.clone(), attendees, voiceprints, gpu_health));

    Ok(Json(serde_json::json!({ "job_id": job_id })))
}

async fn stream_job(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    let rx = state.jobs.read().await.get(&id).map(|h| h.tx.subscribe());

    match rx {
        Some(rx) => {
            let stream = BroadcastEventStream::new(rx);
            Sse::new(stream)
                .keep_alive(KeepAlive::new().interval(Duration::from_secs(15)))
                .into_response()
        }
        None => StatusCode::NOT_FOUND.into_response(),
    }
}

async fn poll_job(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    match state.jobs.read().await.get(&id) {
        Some(h) => Json(h.result.read().await.clone()).into_response(),
        None => StatusCode::NOT_FOUND.into_response(),
    }
}

// ─── Speaker enrollment proxy endpoints ─────────────────────────────

async fn enroll_speaker(
    State(state): State<AppState>,
    mut multipart: Multipart,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    if !state.gpu_health.is_available().await {
        return Err((
            StatusCode::SERVICE_UNAVAILABLE,
            serde_json::json!({
                "error": "GPU service unavailable — speaker enrollment requires GPU for embedding extraction"
            }).to_string(),
        ));
    }

    let mut audio_bytes: Option<Vec<u8>> = None;
    let mut name: Option<String> = None;

    while let Ok(Some(field)) = multipart.next_field().await {
        match field.name() {
            Some("audio") => {
                audio_bytes = Some(
                    field
                        .bytes()
                        .await
                        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?
                        .to_vec(),
                );
            }
            Some("name") => {
                name = Some(
                    field
                        .text()
                        .await
                        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?,
                );
            }
            _ => {}
        }
    }

    let audio_bytes =
        audio_bytes.ok_or((StatusCode::BAD_REQUEST, "No audio field".to_string()))?;
    let name = name.ok_or((StatusCode::BAD_REQUEST, "No name field".to_string()))?;

    // Step 1: Call GPU /embed to extract embedding
    let gpu_url = embedding_url();
    let client = reqwest::Client::new();

    let part = reqwest::multipart::Part::bytes(audio_bytes)
        .file_name("enroll.wav")
        .mime_str("audio/wav")
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    let form = reqwest::multipart::Form::new().part("audio", part);

    let resp = gpu_auth(client
        .post(format!("{}/embed", gpu_url))
        .multipart(form)
        .timeout(Duration::from_secs(60)))
        .send()
        .await
        .map_err(|e| (StatusCode::BAD_GATEWAY, format!("GPU service unreachable: {e}")))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err((
            StatusCode::BAD_GATEWAY,
            format!("GPU /embed returned {status}: {body}"),
        ));
    }

    let embed_data: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| (StatusCode::BAD_GATEWAY, format!("Invalid GPU response: {e}")))?;

    let embedding: Vec<f32> = embed_data["embedding"]
        .as_array()
        .ok_or((StatusCode::BAD_GATEWAY, "No embedding in response".to_string()))?
        .iter()
        .filter_map(|v| v.as_f64().map(|f| f as f32))
        .collect();

    // Step 2: Store in local voiceprint store
    let speaker_id = state
        .voiceprints
        .enroll(&name, &embedding)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, format!("Voiceprint enroll failed: {e}")))?;

    Ok(Json(serde_json::json!({
        "speaker_id": speaker_id,
        "name": name,
    })))
}

async fn list_speakers(
    State(state): State<AppState>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let speakers = state
        .voiceprints
        .list_speakers()
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, format!("Voiceprint list failed: {e}")))?;

    Ok(Json(serde_json::json!({ "speakers": speakers })))
}

// ─── Standalone transcription ───────────────────────────────────────

async fn transcribe(
    mut multipart: Multipart,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let mut audio_bytes = Vec::new();

    while let Ok(Some(field)) = multipart.next_field().await {
        if field.name() == Some("audio") {
            audio_bytes = field
                .bytes()
                .await
                .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?
                .to_vec();
        }
    }

    if audio_bytes.is_empty() {
        return Err((StatusCode::BAD_REQUEST, "No audio field".into()));
    }

    let result = transcribe_audio(&audio_bytes)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    Ok(Json(serde_json::json!({
        "text": result.text,
        "words": result.words,
        "language": result.language,
        "duration_ms": result.duration_ms,
    })))
}

// ─── SSE stream adapter ────────────────────────────────────────────

struct BroadcastEventStream {
    rx: broadcast::Receiver<PipelineEvent>,
}

impl BroadcastEventStream {
    fn new(rx: broadcast::Receiver<PipelineEvent>) -> Self {
        Self { rx }
    }
}

impl Stream for BroadcastEventStream {
    type Item = Result<Event, Infallible>;

    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        match self.rx.try_recv() {
            Ok(ev) => {
                let (event_name, data) = event_to_sse(&ev);
                let sse = Event::default()
                    .event(event_name)
                    .data(serde_json::to_string(&data).unwrap_or_default());
                Poll::Ready(Some(Ok(sse)))
            }
            Err(broadcast::error::TryRecvError::Empty) => {
                let waker = cx.waker().clone();
                let mut rx = self.rx.resubscribe();
                tokio::spawn(async move {
                    let _ = rx.recv().await;
                    waker.wake();
                });
                Poll::Pending
            }
            Err(broadcast::error::TryRecvError::Lagged(_)) => {
                cx.waker().wake_by_ref();
                Poll::Pending
            }
            Err(broadcast::error::TryRecvError::Closed) => Poll::Ready(None),
        }
    }
}

fn event_to_sse(ev: &PipelineEvent) -> (&'static str, serde_json::Value) {
    match ev {
        PipelineEvent::PhaseStart { phase } => {
            ("phase_start", serde_json::json!({ "phase": phase }))
        }
        PipelineEvent::TranscriptToken { token } => {
            ("transcript_token", serde_json::json!({ "token": token }))
        }
        PipelineEvent::TranscriptComplete {
            text,
            words,
            language,
            duration_ms,
        } => (
            "transcript_complete",
            serde_json::json!({
                "text": text,
                "words": words,
                "language": language,
                "duration_ms": duration_ms,
            }),
        ),
        PipelineEvent::DiarizationComplete { segments } => (
            "diarization_complete",
            serde_json::json!({ "segments": segments }),
        ),
        PipelineEvent::AcousticMatchesComplete { matches } => (
            "acoustic_matches_complete",
            serde_json::json!({ "matches": matches }),
        ),
        PipelineEvent::SegmentsResolved { segments } => (
            "segments_resolved",
            serde_json::json!({ "segments": segments }),
        ),
        PipelineEvent::ToolCall { tool, args } => (
            "tool_call",
            serde_json::json!({ "tool": tool, "args": args }),
        ),
        PipelineEvent::ToolResult { tool, result } => (
            "tool_result",
            serde_json::json!({ "tool": tool, "result": result }),
        ),
        PipelineEvent::SpeakerResolved {
            label,
            name,
            confidence,
            method,
        } => (
            "speaker_resolved",
            serde_json::json!({
                "label": label,
                "name": name,
                "confidence": confidence,
                "method": method,
            }),
        ),
        PipelineEvent::AnalysisComplete {
            decisions,
            ambiguities,
            action_items,
            meeting_dynamics,
        } => (
            "analysis_complete",
            serde_json::json!({
                "decisions": decisions,
                "ambiguities": ambiguities,
                "action_items": action_items,
                "meeting_dynamics": meeting_dynamics,
            }),
        ),
        PipelineEvent::Done => ("done", serde_json::json!({})),
    }
}
