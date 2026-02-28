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

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Word {
    pub word: String,
    pub start: f64,
    pub end: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TranscriptionResult {
    pub text: String,
    pub words: Vec<Word>,
    pub language: Option<String>,
    pub duration_ms: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AlignedWord {
    pub word: String,
    pub start: f64,
    pub end: f64,
    pub speaker: Option<String>,
    pub confidence: f64,
    pub is_overlap: bool,
    pub active_speakers: Option<Vec<String>>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Segment {
    pub speaker: String,
    pub start: f64,
    pub end: f64,
    pub text: String,
    #[serde(default)]
    pub is_overlap: bool,
    #[serde(default)]
    pub confidence: f64,
    #[serde(default)]
    pub active_speakers: Vec<String>,
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

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ActionItemRich {
    pub owner: String,
    pub task: String,
    #[serde(default)]
    pub deadline_mentioned: Option<String>,
    #[serde(default)]
    pub verbatim_quote: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SpeakerResolution {
    pub diarization_speaker: String,
    pub resolved_name: String,
    pub confidence: f64,
    pub evidence: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AgentAmbiguity {
    pub diarization_speaker: String,
    pub candidates: Vec<String>,
    pub reason: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MeetingDynamics {
    pub talk_time_pct: HashMap<String, f64>,
    pub interruption_count: u32,
}

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "event", content = "data")]
pub enum PipelineEvent {
    #[serde(rename = "phase_start")]
    PhaseStart { phase: String },
    #[serde(rename = "transcript_token")]
    TranscriptToken { token: String },
    #[serde(rename = "transcript_complete")]
    TranscriptComplete {
        text: String,
        words: Vec<Word>,
        language: Option<String>,
        duration_ms: u64,
    },
    #[serde(rename = "diarization_complete")]
    DiarizationComplete { segments: Vec<Segment> },
    #[serde(rename = "tool_call")]
    ToolCall {
        tool: String,
        args: serde_json::Value,
    },
    #[serde(rename = "tool_result")]
    ToolResult { tool: String, result: String },
    #[serde(rename = "speaker_resolved")]
    SpeakerResolved {
        label: String,
        name: String,
        confidence: f64,
        method: String,
    },
    #[serde(rename = "analysis_complete")]
    AnalysisComplete {
        decisions: Vec<Decision>,
        ambiguities: Vec<Ambiguity>,
        action_items: Vec<ActionItemRich>,
        meeting_dynamics: MeetingDynamics,
    },
    #[serde(rename = "done")]
    Done,
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
    pub action_items: Option<Vec<ActionItemRich>>,
    pub meeting_dynamics: Option<MeetingDynamics>,
    pub error: Option<String>,
}

type JobStore = Arc<RwLock<HashMap<String, JobHandle>>>;

// ─── Tool context for agentic loop ─────────────────────────────────

struct ToolContext {
    audio_bytes: Vec<u8>,
    resolutions: HashMap<String, SpeakerResolution>,
    merges: Vec<(String, String)>,
    ambiguities: Vec<AgentAmbiguity>,
    action_items: Vec<ActionItemRich>,
    diarization_url: String,
}

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

    let transcription = match call_mistral_transcribe(&audio_bytes, &tx).await {
        Ok(t) => t,
        Err(e) => {
            tracing::error!(job_id = %job_id, "Transcription failed: {e}");
            set_error(&result, &tx, &format!("Transcription failed: {e}")).await;
            return;
        }
    };

    tracing::info!(job_id = %job_id, chars = transcription.text.len(), words = transcription.words.len(), "Transcription complete");
    result.write().await.transcript = Some(transcription.text.clone());
    let _ = tx.send(PipelineEvent::TranscriptComplete {
        text: transcription.text.clone(),
        words: transcription.words.clone(),
        language: transcription.language.clone(),
        duration_ms: transcription.duration_ms,
    });

    // ── Phase 2: Diarization + Word Alignment ──
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

    // Word-level alignment if we have words; otherwise fall back
    let segments = if !transcription.words.is_empty() {
        let aligned = align_words_to_speakers(&transcription.words, &diar_segments);
        group_into_segments(&aligned)
    } else {
        match align_transcript(&transcription.text, &diar_segments).await {
            Ok(segs) => segs,
            Err(e) => {
                tracing::warn!(job_id = %job_id, "Alignment failed, using basic split: {e}");
                basic_align(&transcription.text, &diar_segments)
            }
        }
    };

    result.write().await.segments = Some(segments.clone());
    let _ = tx.send(PipelineEvent::DiarizationComplete {
        segments: segments.clone(),
    });

    // ── Phase 3: Agent-based Speaker Resolution ──
    let _ = tx.send(PipelineEvent::PhaseStart {
        phase: "resolving".into(),
    });
    result.write().await.phase = Some("resolving".into());

    let (resolved_segments, agent_action_items) =
        match run_agent(&tx, &segments, &audio_bytes).await {
            Ok((segs, items)) => (segs, items),
            Err(e) => {
                tracing::warn!(job_id = %job_id, "Agent resolution failed, using segments as-is: {e}");
                (segments.clone(), Vec::new())
            }
        };

    result.write().await.segments = Some(resolved_segments.clone());

    // ── Phase 4: Analysis ──
    let _ = tx.send(PipelineEvent::PhaseStart {
        phase: "analyzing".into(),
    });
    result.write().await.phase = Some("analyzing".into());

    let (decisions, ambiguities, analysis_action_items) =
        match call_analysis(&resolved_segments).await {
            Ok(r) => r,
            Err(e) => {
                tracing::error!(job_id = %job_id, "Analysis failed: {e}");
                set_error(&result, &tx, &format!("Analysis failed: {e}")).await;
                return;
            }
        };

    // Merge action items from agent + analysis
    let mut action_items = agent_action_items;
    action_items.extend(analysis_action_items);

    // Compute meeting dynamics
    let meeting_dynamics = compute_meeting_dynamics(&resolved_segments);

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
    result.write().await.meeting_dynamics = Some(meeting_dynamics.clone());
    let _ = tx.send(PipelineEvent::AnalysisComplete {
        decisions,
        ambiguities,
        action_items,
        meeting_dynamics,
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

// ─── Transcription (Mistral API with word timestamps) ───────────────

async fn call_mistral_transcribe(
    audio: &[u8],
    tx: &broadcast::Sender<PipelineEvent>,
) -> anyhow::Result<TranscriptionResult> {
    let api_key = mistral_api_key();
    if api_key.is_empty() {
        // Fallback to self-hosted Voxtral (streaming tokens, no word timestamps)
        tracing::info!("No MISTRAL_API_KEY, falling back to self-hosted Voxtral");
        let text = call_voxtral(audio, tx).await?;
        return Ok(TranscriptionResult {
            text,
            words: Vec::new(),
            language: None,
            duration_ms: 0,
        });
    }

    let client = reqwest::Client::new();
    let part = reqwest::multipart::Part::bytes(audio.to_vec())
        .file_name("audio.wav")
        .mime_str("audio/wav")?;
    let form = reqwest::multipart::Form::new()
        .part("file", part)
        .text("model", "voxtral-mini-latest")
        .text("response_format", "verbose_json")
        .text("timestamp_granularities[]", "word");

    let resp = client
        .post("https://api.mistral.ai/v1/audio/transcriptions")
        .header("Authorization", format!("Bearer {api_key}"))
        .multipart(form)
        .timeout(Duration::from_secs(120))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        // Fallback to self-hosted on API error
        tracing::warn!("Mistral transcription API returned {status}: {body}, falling back to Voxtral");
        let text = call_voxtral(audio, tx).await?;
        return Ok(TranscriptionResult {
            text,
            words: Vec::new(),
            language: None,
            duration_ms: 0,
        });
    }

    let data: serde_json::Value = resp.json().await?;

    let text = data["text"].as_str().unwrap_or("").to_string();
    let language = data["language"].as_str().map(|s| s.to_string());
    let duration_ms = data["duration"]
        .as_f64()
        .map(|d| (d * 1000.0) as u64)
        .unwrap_or(0);

    let words: Vec<Word> = data["words"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|w| {
                    Some(Word {
                        word: w["word"].as_str()?.to_string(),
                        start: w["start"].as_f64()?,
                        end: w["end"].as_f64()?,
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    Ok(TranscriptionResult {
        text,
        words,
        language,
        duration_ms,
    })
}

/// Fallback: self-hosted Voxtral with streaming tokens (no word timestamps)
async fn call_voxtral(
    audio: &[u8],
    tx: &broadcast::Sender<PipelineEvent>,
) -> anyhow::Result<String> {
    let client = reqwest::Client::new();
    let part = reqwest::multipart::Part::bytes(audio.to_vec())
        .file_name("audio.wav")
        .mime_str("audio/wav")?;
    let form = reqwest::multipart::Form::new().part("audio", part);

    let resp = client
        .post(format!("{}/transcribe/stream", voxtral_url()))
        .multipart(form)
        .timeout(Duration::from_secs(300))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("Voxtral returned {status}: {body}");
    }

    // Parse SSE stream from response
    use futures::StreamExt;
    let mut full_text = String::new();
    let mut current_event = String::new();
    let mut byte_stream = resp.bytes_stream();
    let mut buf = String::new();

    while let Some(chunk) = byte_stream.next().await {
        let chunk = chunk?;
        buf.push_str(&String::from_utf8_lossy(&chunk));

        // Process complete lines from buffer
        while let Some(newline_pos) = buf.find('\n') {
            let line = buf[..newline_pos].trim_end_matches('\r').to_string();
            buf = buf[newline_pos + 1..].to_string();

            if line.starts_with("event: ") {
                current_event = line["event: ".len()..].to_string();
            } else if line.starts_with("data: ") {
                let data = &line["data: ".len()..];
                match current_event.as_str() {
                    "token" => {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(data) {
                            if let Some(token) = parsed["token"].as_str() {
                                full_text.push_str(token);
                                let _ = tx.send(PipelineEvent::TranscriptToken {
                                    token: token.to_string(),
                                });
                            }
                        }
                    }
                    "done" => {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(data) {
                            if let Some(text) = parsed["text"].as_str() {
                                return Ok(text.to_string());
                            }
                        }
                    }
                    _ => {}
                }
                current_event.clear();
            }
        }
    }

    // If we didn't get a done event, return accumulated text
    if !full_text.is_empty() {
        Ok(full_text.trim().to_string())
    } else {
        anyhow::bail!("Voxtral stream ended without producing any text")
    }
}

// ─── Diarization ────────────────────────────────────────────────────

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
    let segments: Vec<DiarSegment> = serde_json::from_value(data["segments"].clone())?;

    Ok(segments)
}

// ─── Word-level alignment ──────────────────────────────────────────

fn align_words_to_speakers(words: &[Word], diar_segments: &[DiarSegment]) -> Vec<AlignedWord> {
    let mut aligned = Vec::with_capacity(words.len());

    for w in words {
        let word_dur = (w.end - w.start).max(0.001);
        let mut best_speaker: Option<String> = None;
        let mut best_overlap: f64 = 0.0;
        let mut is_overlap = false;
        let mut active: Vec<String> = Vec::new();

        for seg in diar_segments {
            let overlap_start = w.start.max(seg.start);
            let overlap_end = w.end.min(seg.end);
            let overlap = (overlap_end - overlap_start).max(0.0);

            if overlap > 0.0 {
                active.push(seg.speaker.clone());
                if overlap > best_overlap {
                    best_overlap = overlap;
                    best_speaker = Some(seg.speaker.clone());
                }
            }
        }

        if active.len() > 1 {
            is_overlap = true;
        }

        // Orphan recovery: if no overlap, find nearest segment within ±300ms
        if best_speaker.is_none() {
            let mut min_dist = f64::MAX;
            for seg in diar_segments {
                let dist = if w.end < seg.start {
                    seg.start - w.end
                } else if w.start > seg.end {
                    w.start - seg.end
                } else {
                    0.0
                };
                if dist < min_dist && dist <= 0.3 {
                    min_dist = dist;
                    best_speaker = Some(seg.speaker.clone());
                }
            }
        }

        let confidence = if best_overlap > 0.0 {
            best_overlap / word_dur
        } else {
            0.0
        };

        aligned.push(AlignedWord {
            word: w.word.clone(),
            start: w.start,
            end: w.end,
            speaker: best_speaker,
            confidence: confidence.min(1.0),
            is_overlap,
            active_speakers: if is_overlap { Some(active) } else { None },
        });
    }

    aligned
}

fn group_into_segments(aligned: &[AlignedWord]) -> Vec<Segment> {
    if aligned.is_empty() {
        return Vec::new();
    }

    let mut segments: Vec<Segment> = Vec::new();
    let mut current_speaker = aligned[0].speaker.clone().unwrap_or_else(|| "UNKNOWN".into());
    let mut current_start = aligned[0].start;
    let mut current_words: Vec<String> = vec![aligned[0].word.clone()];
    let mut current_end = aligned[0].end;
    let mut overlap_any = aligned[0].is_overlap;
    let mut confidence_sum = aligned[0].confidence;
    let mut word_count = 1usize;
    let mut all_active: Vec<String> = aligned[0]
        .active_speakers
        .clone()
        .unwrap_or_default();

    for aw in &aligned[1..] {
        let speaker = aw.speaker.clone().unwrap_or_else(|| "UNKNOWN".into());

        if speaker == current_speaker {
            current_words.push(aw.word.clone());
            current_end = aw.end;
            if aw.is_overlap {
                overlap_any = true;
            }
            confidence_sum += aw.confidence;
            word_count += 1;
            if let Some(ref active) = aw.active_speakers {
                for s in active {
                    if !all_active.contains(s) {
                        all_active.push(s.clone());
                    }
                }
            }
        } else {
            segments.push(Segment {
                speaker: current_speaker,
                start: current_start,
                end: current_end,
                text: current_words.join(" "),
                is_overlap: overlap_any,
                confidence: if word_count > 0 {
                    confidence_sum / word_count as f64
                } else {
                    0.0
                },
                active_speakers: if overlap_any {
                    all_active.clone()
                } else {
                    Vec::new()
                },
            });

            current_speaker = speaker;
            current_start = aw.start;
            current_words = vec![aw.word.clone()];
            current_end = aw.end;
            overlap_any = aw.is_overlap;
            confidence_sum = aw.confidence;
            word_count = 1;
            all_active = aw.active_speakers.clone().unwrap_or_default();
        }
    }

    segments.push(Segment {
        speaker: current_speaker,
        start: current_start,
        end: current_end,
        text: current_words.join(" "),
        is_overlap: overlap_any,
        confidence: if word_count > 0 {
            confidence_sum / word_count as f64
        } else {
            0.0
        },
        active_speakers: if overlap_any {
            all_active
        } else {
            Vec::new()
        },
    });

    segments
}

// ─── LLM-based alignment fallback ──────────────────────────────────

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

    let parsed: serde_json::Value = serde_json::from_str(content)?;
    let arr = if parsed.is_array() {
        parsed
    } else if let Some(segs) = parsed.get("segments") {
        segs.clone()
    } else {
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
            is_overlap: false,
            confidence: 0.0,
            active_speakers: Vec::new(),
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
                is_overlap: false,
                confidence: 0.0,
                active_speakers: Vec::new(),
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
            is_overlap: false,
            confidence: 0.0,
            active_speakers: Vec::new(),
        });
    }

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

// ─── Agentic Tool-Calling Loop ─────────────────────────────────────

fn build_tool_schemas() -> serde_json::Value {
    serde_json::json!([
        {
            "type": "function",
            "function": {
                "name": "resolve_speaker",
                "description": "Assign a real name to a diarization speaker label based on evidence.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "diarization_speaker": { "type": "string", "description": "The speaker label (e.g., SPEAKER_00)" },
                        "resolved_name": { "type": "string", "description": "The resolved real name" },
                        "confidence": { "type": "number", "description": "Confidence 0-1" },
                        "evidence": { "type": "string", "description": "Evidence for the resolution" }
                    },
                    "required": ["diarization_speaker", "resolved_name", "confidence", "evidence"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "request_reanalysis",
                "description": "Request voiceprint identification for an audio segment to help identify a speaker.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_time": { "type": "number", "description": "Start time in seconds" },
                        "end_time": { "type": "number", "description": "End time in seconds" }
                    },
                    "required": ["start_time", "end_time"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "merge_speakers",
                "description": "Merge two diarization speaker labels that are the same person.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "speaker_a": { "type": "string", "description": "First speaker label" },
                        "speaker_b": { "type": "string", "description": "Second speaker label to merge into first" },
                        "evidence": { "type": "string", "description": "Evidence for the merge" }
                    },
                    "required": ["speaker_a", "speaker_b", "evidence"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "flag_ambiguity",
                "description": "Flag a speaker label as ambiguous when identity cannot be determined with confidence.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "diarization_speaker": { "type": "string", "description": "The ambiguous speaker label" },
                        "candidates": { "type": "array", "items": { "type": "string" }, "description": "Possible identity candidates" },
                        "reason": { "type": "string", "description": "Reason for ambiguity" }
                    },
                    "required": ["diarization_speaker", "candidates", "reason"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "extract_action_items",
                "description": "Extract structured action items found in the transcript.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "owner": { "type": "string", "description": "Person responsible" },
                                    "task": { "type": "string", "description": "Task description" },
                                    "deadline_mentioned": { "type": "string", "description": "Deadline if mentioned, or null" },
                                    "verbatim_quote": { "type": "string", "description": "Exact quote from transcript" }
                                },
                                "required": ["owner", "task"]
                            },
                            "description": "List of action items"
                        }
                    },
                    "required": ["items"]
                }
            }
        }
    ])
}

fn build_agent_system_prompt() -> String {
    r#"You are a meeting analysis agent. Your job is to resolve diarization speaker labels (SPEAKER_00, SPEAKER_01, etc.) to real names, and extract action items.

## Evidence Thresholds
- Acoustic evidence (voiceprint similarity):
  - >0.85: Strong match — use as primary evidence
  - 0.70-0.85: Suggestive — combine with semantic evidence
  - <0.70: Unreliable — do not use alone

- Semantic evidence patterns:
  - Self-introduction: "Hi, I'm [Name]" or "This is [Name]"
  - Direct address: "[Name], what do you think?"
  - Role references: "As the PM..." → correlate with known team
  - Calendar context: meeting organizer, attendee list

## Instructions
1. Analyze the transcript segments for speaker identity clues
2. Use resolve_speaker when you have sufficient evidence (confidence > 0.7)
3. Use request_reanalysis to get voiceprint matches for uncertain speakers
4. Use merge_speakers if diarization split one person into multiple labels
5. Use flag_ambiguity when you cannot confidently resolve a speaker
6. Use extract_action_items to capture commitments, tasks, and follow-ups
7. Stop when all speakers are resolved or flagged, and all action items are extracted"#.to_string()
}

async fn execute_tool(
    tool_name: &str,
    args: &serde_json::Value,
    ctx: &mut ToolContext,
    tx: &broadcast::Sender<PipelineEvent>,
) -> String {
    match tool_name {
        "resolve_speaker" => {
            let speaker = args["diarization_speaker"].as_str().unwrap_or("");
            let name = args["resolved_name"].as_str().unwrap_or("");
            let confidence = args["confidence"].as_f64().unwrap_or(0.0);
            let evidence = args["evidence"].as_str().unwrap_or("");

            ctx.resolutions.insert(
                speaker.to_string(),
                SpeakerResolution {
                    diarization_speaker: speaker.to_string(),
                    resolved_name: name.to_string(),
                    confidence,
                    evidence: evidence.to_string(),
                },
            );

            let _ = tx.send(PipelineEvent::SpeakerResolved {
                label: speaker.to_string(),
                name: name.to_string(),
                confidence,
                method: "agent".to_string(),
            });

            format!("Resolved {speaker} → {name} (confidence: {confidence:.2})")
        }

        "request_reanalysis" => {
            let start = args["start_time"].as_f64().unwrap_or(0.0);
            let end = args["end_time"].as_f64().unwrap_or(0.0);

            match call_voiceprint_identify(&ctx.audio_bytes, start, end, &ctx.diarization_url)
                .await
            {
                Ok(matches) => {
                    let result = serde_json::to_string(&matches).unwrap_or_else(|_| "[]".into());
                    format!("Voiceprint matches for {start:.1}s-{end:.1}s: {result}")
                }
                Err(e) => format!("Voiceprint identification failed: {e}"),
            }
        }

        "merge_speakers" => {
            let a = args["speaker_a"].as_str().unwrap_or("");
            let b = args["speaker_b"].as_str().unwrap_or("");
            let evidence = args["evidence"].as_str().unwrap_or("");

            ctx.merges.push((a.to_string(), b.to_string()));
            format!("Merged {b} into {a} (evidence: {evidence})")
        }

        "flag_ambiguity" => {
            let speaker = args["diarization_speaker"].as_str().unwrap_or("");
            let candidates: Vec<String> = args["candidates"]
                .as_array()
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(|s| s.to_string()))
                        .collect()
                })
                .unwrap_or_default();
            let reason = args["reason"].as_str().unwrap_or("");

            ctx.ambiguities.push(AgentAmbiguity {
                diarization_speaker: speaker.to_string(),
                candidates: candidates.clone(),
                reason: reason.to_string(),
            });

            format!(
                "Flagged {speaker} as ambiguous: candidates={}, reason={reason}",
                candidates.join(", ")
            )
        }

        "extract_action_items" => {
            let items: Vec<ActionItemRich> = args["items"]
                .as_array()
                .map(|arr| {
                    arr.iter()
                        .filter_map(|item| {
                            Some(ActionItemRich {
                                owner: item["owner"].as_str()?.to_string(),
                                task: item["task"].as_str()?.to_string(),
                                deadline_mentioned: item["deadline_mentioned"]
                                    .as_str()
                                    .map(|s| s.to_string()),
                                verbatim_quote: item["verbatim_quote"]
                                    .as_str()
                                    .map(|s| s.to_string()),
                            })
                        })
                        .collect()
                })
                .unwrap_or_default();

            let count = items.len();
            ctx.action_items.extend(items);
            format!("Extracted {count} action items")
        }

        _ => format!("Unknown tool: {tool_name}"),
    }
}

async fn call_voiceprint_identify(
    audio: &[u8],
    start: f64,
    end: f64,
    diarization_url: &str,
) -> anyhow::Result<serde_json::Value> {
    let client = reqwest::Client::new();
    let part = reqwest::multipart::Part::bytes(audio.to_vec())
        .file_name("audio.wav")
        .mime_str("audio/wav")?;
    let form = reqwest::multipart::Form::new()
        .part("audio", part)
        .text("start_time", start.to_string())
        .text("end_time", end.to_string());

    let resp = client
        .post(format!("{}/voiceprint/identify", diarization_url))
        .multipart(form)
        .timeout(Duration::from_secs(30))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("Voiceprint identify returned {status}: {body}");
    }

    let data: serde_json::Value = resp.json().await?;
    Ok(data["matches"].clone())
}

async fn run_agent(
    tx: &broadcast::Sender<PipelineEvent>,
    segments: &[Segment],
    audio_bytes: &[u8],
) -> anyhow::Result<(Vec<Segment>, Vec<ActionItemRich>)> {
    let api_key = mistral_api_key();
    if api_key.is_empty() {
        tracing::info!("No MISTRAL_API_KEY, skipping agent — using threshold matching fallback");
        return Ok((segments.to_vec(), Vec::new()));
    }

    let mut ctx = ToolContext {
        audio_bytes: audio_bytes.to_vec(),
        resolutions: HashMap::new(),
        merges: Vec::new(),
        ambiguities: Vec::new(),
        action_items: Vec::new(),
        diarization_url: diarization_url(),
    };

    let segment_text: Vec<String> = segments
        .iter()
        .map(|s| {
            let overlap_marker = if s.is_overlap { " [OVERLAP]" } else { "" };
            format!(
                "[{:.1}s-{:.1}s] {} (confidence: {:.2}){}: {}",
                s.start, s.end, s.speaker, s.confidence, overlap_marker, s.text
            )
        })
        .collect();

    let user_message = format!(
        "Analyze this speaker-attributed meeting transcript. Resolve speaker labels to real names and extract action items.\n\nSEGMENTS:\n{}",
        segment_text.join("\n")
    );

    let tools = build_tool_schemas();
    let system_prompt = build_agent_system_prompt();

    let mut messages = vec![
        serde_json::json!({"role": "system", "content": system_prompt}),
        serde_json::json!({"role": "user", "content": user_message}),
    ];

    let client = reqwest::Client::new();
    let max_iterations = 5;

    for iteration in 0..max_iterations {
        tracing::info!(iteration, "Agent iteration");

        let body = serde_json::json!({
            "model": "mistral-large-latest",
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        });

        let resp = client
            .post("https://api.mistral.ai/v1/chat/completions")
            .header("Authorization", format!("Bearer {api_key}"))
            .header("Content-Type", "application/json")
            .json(&body)
            .timeout(Duration::from_secs(30))
            .send()
            .await;

        let resp = match resp {
            Ok(r) => r,
            Err(e) => {
                tracing::warn!("Agent API call failed at iteration {iteration}: {e}");
                break;
            }
        };

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            tracing::warn!("Agent API returned {status}: {body}");
            break;
        }

        let data: serde_json::Value = resp.json().await?;
        let message = &data["choices"][0]["message"];

        let tool_calls = message["tool_calls"].as_array();

        if tool_calls.is_none() || tool_calls.unwrap().is_empty() {
            tracing::info!(iteration, "Agent finished (no tool calls)");
            break;
        }

        let tool_calls = tool_calls.unwrap();

        messages.push(message.clone());

        for tc in tool_calls {
            let tool_name = tc["function"]["name"].as_str().unwrap_or("");
            let args_str = tc["function"]["arguments"].as_str().unwrap_or("{}");
            let tool_call_id = tc["id"].as_str().unwrap_or("");
            let args: serde_json::Value =
                serde_json::from_str(args_str).unwrap_or(serde_json::json!({}));

            let _ = tx.send(PipelineEvent::ToolCall {
                tool: tool_name.to_string(),
                args: args.clone(),
            });

            let result = execute_tool(tool_name, &args, &mut ctx, tx).await;

            let _ = tx.send(PipelineEvent::ToolResult {
                tool: tool_name.to_string(),
                result: result.clone(),
            });

            messages.push(serde_json::json!({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": result,
            }));
        }
    }

    let resolved_segments = apply_resolutions(segments, &ctx);

    Ok((resolved_segments, ctx.action_items))
}

fn apply_resolutions(segments: &[Segment], ctx: &ToolContext) -> Vec<Segment> {
    let mut merge_map: HashMap<String, String> = HashMap::new();
    for (a, b) in &ctx.merges {
        merge_map.insert(b.clone(), a.clone());
    }

    segments
        .iter()
        .map(|seg| {
            let mut speaker = seg.speaker.clone();

            if let Some(merged_into) = merge_map.get(&speaker) {
                speaker = merged_into.clone();
            }

            if let Some(resolution) = ctx.resolutions.get(&speaker) {
                speaker = resolution.resolved_name.clone();
            }

            Segment {
                speaker,
                start: seg.start,
                end: seg.end,
                text: seg.text.clone(),
                is_overlap: seg.is_overlap,
                confidence: seg.confidence,
                active_speakers: seg.active_speakers.clone(),
            }
        })
        .collect()
}

// ─── Analysis ───────────────────────────────────────────────────────

async fn call_analysis(
    segments: &[Segment],
) -> anyhow::Result<(Vec<Decision>, Vec<Ambiguity>, Vec<ActionItemRich>)> {
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
  "action_items": [
    {{
      "owner": "<person responsible>",
      "task": "<task description>",
      "deadline_mentioned": "<deadline if mentioned, or null>",
      "verbatim_quote": "<exact quote from transcript>"
    }}
  ]
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
    let action_items: Vec<ActionItemRich> =
        serde_json::from_value(parsed["action_items"].clone()).unwrap_or_default();

    Ok((decisions, ambiguities, action_items))
}

// ─── Meeting Dynamics ──────────────────────────────────────────────

fn compute_meeting_dynamics(segments: &[Segment]) -> MeetingDynamics {
    let mut talk_time: HashMap<String, f64> = HashMap::new();
    let mut total_time = 0.0;

    for seg in segments {
        let dur = (seg.end - seg.start).max(0.0);
        *talk_time.entry(seg.speaker.clone()).or_insert(0.0) += dur;
        total_time += dur;
    }

    let talk_time_pct: HashMap<String, f64> = talk_time
        .into_iter()
        .map(|(speaker, time)| {
            let pct = if total_time > 0.0 {
                (time / total_time) * 100.0
            } else {
                0.0
            };
            (speaker, (pct * 10.0).round() / 10.0)
        })
        .collect();

    let mut interruption_count: u32 = 0;
    for i in 1..segments.len() {
        if segments[i].speaker != segments[i - 1].speaker
            && segments[i].start < segments[i - 1].end
        {
            interruption_count += 1;
        }
    }

    MeetingDynamics {
        talk_time_pct,
        interruption_count,
    }
}
