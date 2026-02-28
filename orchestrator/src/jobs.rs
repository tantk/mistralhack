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
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    convert::Infallible,
    env,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
    time::Duration,
};
use tokio::sync::{broadcast, RwLock};
use uuid::Uuid;

// ─── Config ─────────────────────────────────────────────────────────

fn voxtral_url() -> String {
    env::var("VOXTRAL_URL").unwrap_or_else(|_| "http://192.168.0.105:8080".into())
}

fn diarization_url() -> String {
    env::var("DIARIZATION_URL").unwrap_or_else(|_| "http://192.168.0.105:8001".into())
}

fn mistral_api_key() -> String {
    env::var("MISTRAL_API_KEY").unwrap_or_default()
}

// ─── Types ──────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "event", content = "data")]
pub enum PipelineEvent {
    #[serde(rename = "phase_start")]
    PhaseStart { phase: String },
    #[serde(rename = "transcript_complete")]
    TranscriptComplete { text: String, duration_ms: u64 },
    #[serde(rename = "diarization_complete")]
    DiarizationComplete { segments: Vec<Segment> },
    #[serde(rename = "analysis_complete")]
    AnalysisComplete {
        decisions: Vec<Decision>,
        ambiguities: Vec<Ambiguity>,
        action_items: Vec<String>,
    },
    #[serde(rename = "done")]
    Done,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Segment {
    pub speaker: String,
    pub start: f64,
    pub end: f64,
    pub text: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Decision {
    pub timestamp: f64,
    pub summary: String,
    pub proposed_by: String,
    pub seconded_by: Option<String>,
    pub dissent_by: Option<String>,
    pub status: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
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
    result: Arc<RwLock<JobResult>>,
}

#[derive(Clone, Default, Serialize)]
pub struct JobResult {
    pub status: String,
    pub phase: Option<String>,
    pub transcript: Option<String>,
    pub segments: Option<Vec<Segment>>,
    pub decisions: Option<Vec<Decision>>,
    pub ambiguities: Option<Vec<Ambiguity>>,
    pub action_items: Option<Vec<String>>,
    pub error: Option<String>,
}

type JobStore = Arc<RwLock<HashMap<String, JobHandle>>>;

// ─── Router ─────────────────────────────────────────────────────────

pub fn router() -> Router {
    let store: JobStore = Arc::new(RwLock::new(HashMap::new()));

    Router::new()
        .route("/jobs", post(create_job))
        .route("/jobs/{id}/events", get(stream_job))
        .route("/jobs/{id}/result", get(poll_job))
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
    let (tx, _) = broadcast::channel::<PipelineEvent>(64);
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
                // Register waker and return pending
                let waker = cx.waker().clone();
                let mut rx = self.rx.resubscribe();
                tokio::spawn(async move {
                    let _ = rx.recv().await;
                    waker.wake();
                });
                Poll::Pending
            }
            Err(broadcast::error::TryRecvError::Lagged(_)) => {
                // Skip missed events, keep going
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
        PipelineEvent::TranscriptComplete { text, duration_ms } => (
            "transcript_complete",
            serde_json::json!({ "text": text, "duration_ms": duration_ms }),
        ),
        PipelineEvent::DiarizationComplete { segments } => (
            "diarization_complete",
            serde_json::json!({ "segments": segments }),
        ),
        PipelineEvent::AnalysisComplete {
            decisions,
            ambiguities,
            action_items,
        } => (
            "analysis_complete",
            serde_json::json!({
                "decisions": decisions,
                "ambiguities": ambiguities,
                "action_items": action_items,
            }),
        ),
        PipelineEvent::Done => ("done", serde_json::json!({})),
    }
}

// ─── Pipeline orchestration ─────────────────────────────────────────

async fn run_pipeline(
    tx: broadcast::Sender<PipelineEvent>,
    result: Arc<RwLock<JobResult>>,
    audio_bytes: Vec<u8>,
    job_id: String,
) {
    tracing::info!(job_id = %job_id, "Pipeline starting");

    // ── Phase 1: Transcription ──
    let _ = tx.send(PipelineEvent::PhaseStart {
        phase: "transcribing".into(),
    });
    result.write().await.phase = Some("transcribing".into());

    let transcript = match call_voxtral(&audio_bytes).await {
        Ok(text) => text,
        Err(e) => {
            tracing::error!(job_id = %job_id, "Transcription failed: {e}");
            set_error(&result, &tx, &format!("Transcription failed: {e}")).await;
            return;
        }
    };

    tracing::info!(job_id = %job_id, chars = transcript.len(), "Transcription complete");
    result.write().await.transcript = Some(transcript.clone());
    let _ = tx.send(PipelineEvent::TranscriptComplete {
        text: transcript.clone(),
        duration_ms: 0,
    });

    // ── Phase 2: Diarization ──
    let _ = tx.send(PipelineEvent::PhaseStart {
        phase: "diarizing".into(),
    });
    result.write().await.phase = Some("diarizing".into());

    let diar_segments = match call_diarize(&audio_bytes).await {
        Ok(segs) => segs,
        Err(e) => {
            tracing::error!(job_id = %job_id, "Diarization failed: {e}");
            set_error(&result, &tx, &format!("Diarization failed: {e}")).await;
            return;
        }
    };

    tracing::info!(job_id = %job_id, segments = diar_segments.len(), "Diarization complete");

    // Align transcript text to diarization segments via Mistral
    let segments = match align_transcript(&transcript, &diar_segments).await {
        Ok(segs) => segs,
        Err(e) => {
            tracing::warn!(job_id = %job_id, "Alignment failed, using basic split: {e}");
            basic_align(&transcript, &diar_segments)
        }
    };

    result.write().await.segments = Some(segments.clone());
    let _ = tx.send(PipelineEvent::DiarizationComplete {
        segments: segments.clone(),
    });

    // ── Phase 3: Analysis ──
    let _ = tx.send(PipelineEvent::PhaseStart {
        phase: "analyzing".into(),
    });
    result.write().await.phase = Some("analyzing".into());

    let (decisions, ambiguities, action_items) = match call_analysis(&segments).await {
        Ok(r) => r,
        Err(e) => {
            tracing::error!(job_id = %job_id, "Analysis failed: {e}");
            set_error(&result, &tx, &format!("Analysis failed: {e}")).await;
            return;
        }
    };

    tracing::info!(
        job_id = %job_id,
        decisions = decisions.len(),
        ambiguities = ambiguities.len(),
        action_items = action_items.len(),
        "Analysis complete"
    );

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

    tracing::info!(job_id = %job_id, "Pipeline complete");
}

async fn set_error(
    result: &Arc<RwLock<JobResult>>,
    tx: &broadcast::Sender<PipelineEvent>,
    msg: &str,
) {
    let mut r = result.write().await;
    r.status = "error".into();
    r.error = Some(msg.into());
    r.phase = None;
    let _ = tx.send(PipelineEvent::Done);
}

// ─── Service calls ──────────────────────────────────────────────────

async fn call_voxtral(audio: &[u8]) -> anyhow::Result<String> {
    let client = reqwest::Client::new();
    let part = reqwest::multipart::Part::bytes(audio.to_vec())
        .file_name("audio.wav")
        .mime_str("audio/wav")?;
    let form = reqwest::multipart::Form::new().part("audio", part);

    let resp = client
        .post(format!("{}/transcribe", voxtral_url()))
        .multipart(form)
        .timeout(Duration::from_secs(120))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("Voxtral returned {status}: {body}");
    }

    let data: serde_json::Value = resp.json().await?;
    Ok(data["text"].as_str().unwrap_or("").to_string())
}

#[derive(Deserialize)]
struct DiarSegment {
    speaker: String,
    start: f64,
    end: f64,
}

async fn call_diarize(audio: &[u8]) -> anyhow::Result<Vec<DiarSegment>> {
    let client = reqwest::Client::new();
    let part = reqwest::multipart::Part::bytes(audio.to_vec())
        .file_name("meeting.wav")
        .mime_str("audio/wav")?;
    let form = reqwest::multipart::Form::new().part("audio", part);

    let resp = client
        .post(format!("{}/diarize", diarization_url()))
        .multipart(form)
        .timeout(Duration::from_secs(300))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("Diarization returned {status}: {body}");
    }

    let data: serde_json::Value = resp.json().await?;
    let segments: Vec<DiarSegment> = serde_json::from_value(
        data["segments"].clone(),
    )?;

    Ok(segments)
}

/// Use Mistral to align the full transcript to diarization segments.
async fn align_transcript(
    transcript: &str,
    diar_segments: &[DiarSegment],
) -> anyhow::Result<Vec<Segment>> {
    let api_key = mistral_api_key();
    if api_key.is_empty() {
        anyhow::bail!("MISTRAL_API_KEY not set");
    }

    let segments_json: Vec<serde_json::Value> = diar_segments
        .iter()
        .map(|s| {
            serde_json::json!({
                "speaker": s.speaker,
                "start": s.start,
                "end": s.end,
            })
        })
        .collect();

    let prompt = format!(
        r#"You have a meeting transcript and speaker diarization segments with timestamps.
Assign the transcript text to the correct speaker segments.

TRANSCRIPT:
{transcript}

SPEAKER SEGMENTS (timestamps in seconds):
{segments}

Return a JSON array where each element has: speaker, start, end, text.
Distribute the transcript text among the segments based on their temporal order.
Each segment should get the portion of text that was spoken during that time range.
Return ONLY the JSON array, nothing else."#,
        segments = serde_json::to_string_pretty(&segments_json)?,
    );

    let body = serde_json::json!({
        "model": "mistral-large-latest",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    });

    let client = reqwest::Client::new();
    let resp = client
        .post("https://api.mistral.ai/v1/chat/completions")
        .header("Authorization", format!("Bearer {api_key}"))
        .header("Content-Type", "application/json")
        .json(&body)
        .timeout(Duration::from_secs(60))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("Mistral alignment returned {status}: {body}");
    }

    let data: serde_json::Value = resp.json().await?;
    let content = data["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("[]");

    // Parse — might be wrapped in {"segments": [...]} or just [...]
    let parsed: serde_json::Value = serde_json::from_str(content)?;
    let arr = if parsed.is_array() {
        parsed
    } else if let Some(segs) = parsed.get("segments") {
        segs.clone()
    } else {
        // Try to find any array value
        parsed
            .as_object()
            .and_then(|obj| obj.values().find(|v| v.is_array()))
            .cloned()
            .unwrap_or(serde_json::json!([]))
    };

    let segments: Vec<Segment> = serde_json::from_value(arr)?;
    Ok(segments)
}

/// Fallback: split transcript proportionally across diarization segments.
fn basic_align(transcript: &str, diar_segments: &[DiarSegment]) -> Vec<Segment> {
    if diar_segments.is_empty() {
        return vec![Segment {
            speaker: "SPEAKER_0".into(),
            start: 0.0,
            end: 0.0,
            text: transcript.into(),
        }];
    }

    let words: Vec<&str> = transcript.split_whitespace().collect();
    if words.is_empty() {
        return diar_segments
            .iter()
            .map(|s| Segment {
                speaker: s.speaker.clone(),
                start: s.start,
                end: s.end,
                text: String::new(),
            })
            .collect();
    }

    let total_duration: f64 = diar_segments.iter().map(|s| s.end - s.start).sum();
    let mut result = Vec::new();
    let mut word_idx = 0;

    for seg in diar_segments {
        let seg_duration = seg.end - seg.start;
        let proportion = if total_duration > 0.0 {
            seg_duration / total_duration
        } else {
            1.0 / diar_segments.len() as f64
        };
        let word_count = ((words.len() as f64) * proportion).round() as usize;
        let end_idx = (word_idx + word_count).min(words.len());

        let text = words[word_idx..end_idx].join(" ");
        word_idx = end_idx;

        result.push(Segment {
            speaker: seg.speaker.clone(),
            start: seg.start,
            end: seg.end,
            text,
        });
    }

    // Assign remaining words to last segment
    if word_idx < words.len() {
        if let Some(last) = result.last_mut() {
            if !last.text.is_empty() {
                last.text.push(' ');
            }
            last.text.push_str(&words[word_idx..].join(" "));
        }
    }

    result
}

/// Call Mistral to extract decisions, ambiguities, and action items.
async fn call_analysis(
    segments: &[Segment],
) -> anyhow::Result<(Vec<Decision>, Vec<Ambiguity>, Vec<String>)> {
    let api_key = mistral_api_key();
    if api_key.is_empty() {
        anyhow::bail!("MISTRAL_API_KEY not set");
    }

    let transcript_lines: Vec<String> = segments
        .iter()
        .map(|s| format!("[{:.0}s] {}: {}", s.start, s.speaker, s.text))
        .collect();

    let prompt = format!(
        r#"Analyze this speaker-attributed meeting transcript and extract structured intelligence.

TRANSCRIPT:
{}

Return a JSON object with exactly these fields:
{{
  "decisions": [
    {{
      "timestamp": <number, seconds into meeting>,
      "summary": "<what was decided>",
      "proposed_by": "<speaker name>",
      "seconded_by": "<speaker name or null>",
      "dissent_by": "<speaker name or null>",
      "status": "locked" | "open" | "contested"
    }}
  ],
  "ambiguities": [
    {{
      "timestamp": <number>,
      "type": "attributional" | "commitment" | "temporal" | "scope",
      "quote": "<the ambiguous statement>",
      "speaker": "<who said it>",
      "confidence": <0-1, how confident the attribution is>,
      "candidates": ["<possible interpretations or speakers>"]
    }}
  ],
  "action_items": ["<owner>: <task description>"]
}}

If none are found for a category, return an empty array."#,
        transcript_lines.join("\n"),
    );

    let body = serde_json::json!({
        "model": "mistral-large-latest",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    });

    let client = reqwest::Client::new();
    let resp = client
        .post("https://api.mistral.ai/v1/chat/completions")
        .header("Authorization", format!("Bearer {api_key}"))
        .header("Content-Type", "application/json")
        .json(&body)
        .timeout(Duration::from_secs(90))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("Mistral analysis returned {status}: {body}");
    }

    let data: serde_json::Value = resp.json().await?;
    let content = data["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("{}");

    let parsed: serde_json::Value = serde_json::from_str(content)?;

    let decisions: Vec<Decision> =
        serde_json::from_value(parsed["decisions"].clone()).unwrap_or_default();
    let ambiguities: Vec<Ambiguity> =
        serde_json::from_value(parsed["ambiguities"].clone()).unwrap_or_default();
    let action_items: Vec<String> =
        serde_json::from_value(parsed["action_items"].clone()).unwrap_or_default();

    Ok((decisions, ambiguities, action_items))
}
