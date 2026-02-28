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
use super::types::*;
use std::sync::Arc;
use tokio::sync::RwLock;

// ─── Router ─────────────────────────────────────────────────────────

pub fn router() -> Router {
    let store: JobStore = Arc::new(RwLock::new(std::collections::HashMap::new()));

    Router::new()
        .route("/api/jobs", post(create_job))
        .route("/api/jobs/{id}/events", get(stream_job))
        .route("/api/jobs/{id}/result", get(poll_job))
        .with_state(store)
}

// ─── Handlers ───────────────────────────────────────────────────────

async fn create_job(
    State(store): State<JobStore>,
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
            break;
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
    store.write().await.insert(job_id.clone(), handle);

    tracing::info!(job_id = %job_id, bytes = audio_bytes.len(), "Job created");

    tokio::spawn(run_pipeline(tx, result, audio_bytes, job_id.clone()));

    Ok(Json(serde_json::json!({ "job_id": job_id })))
}

async fn stream_job(
    State(store): State<JobStore>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    let rx = store.read().await.get(&id).map(|h| h.tx.subscribe());

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
    State(store): State<JobStore>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    match store.read().await.get(&id) {
        Some(h) => Json(h.result.read().await.clone()).into_response(),
        None => StatusCode::NOT_FOUND.into_response(),
    }
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
