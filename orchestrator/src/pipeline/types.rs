use serde::{Deserialize, Serialize};
use std::{collections::HashMap, env, sync::Arc, time::Duration};
use tokio::sync::{broadcast, RwLock};
use std::time::Instant;

// ─── Config ─────────────────────────────────────────────────────────

pub fn voxtral_url() -> String {
    env::var("VOXTRAL_URL").unwrap_or_else(|_| "http://192.168.0.105:8080".into())
}

pub fn diarization_url() -> String {
    env::var("DIARIZATION_URL").unwrap_or_else(|_| "http://192.168.0.105:8001".into())
}

pub fn gpu_token() -> String {
    env::var("GPU_TOKEN").unwrap_or_default()
}

/// Build a reqwest RequestBuilder with optional GPU auth header.
pub fn gpu_auth(rb: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
    let token = gpu_token();
    if token.is_empty() {
        rb
    } else {
        rb.header("Authorization", format!("Bearer {token}"))
    }
}

pub fn mistral_api_key() -> String {
    env::var("MISTRAL_API_KEY").unwrap_or_default()
}

// ─── GPU Health Cache ───────────────────────────────────────────────

struct GpuHealthInner {
    available: bool,
    last_checked: Instant,
    last_request: Instant,
}

#[derive(Clone)]
pub struct GpuHealthCache {
    inner: Arc<RwLock<GpuHealthInner>>,
}

impl GpuHealthCache {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(RwLock::new(GpuHealthInner {
                available: false,
                last_checked: Instant::now() - Duration::from_secs(120), // force stale
                last_request: Instant::now() - Duration::from_secs(1200),
            })),
        }
    }

    /// Returns cached GPU availability. Spawns background refresh if stale
    /// (>60s since check OR >15min since last request).
    pub async fn is_available(&self) -> bool {
        let mut inner = self.inner.write().await;
        inner.last_request = Instant::now();
        let stale = inner.last_checked.elapsed() > Duration::from_secs(60)
            || inner.last_request.elapsed() > Duration::from_secs(900);
        let cached = inner.available;
        drop(inner);

        if stale {
            let cache = self.clone();
            tokio::spawn(async move { cache.refresh().await });
        }

        cached
    }

    /// Synchronous fresh health check. Calls GPU /health with 5s timeout,
    /// updates cache, returns result.
    pub async fn check_now(&self) -> bool {
        let url = format!("{}/health", diarization_url());
        let result = gpu_auth(reqwest::Client::new()
            .get(&url)
            .timeout(Duration::from_secs(5)))
            .send()
            .await
            .map(|r| r.status().is_success())
            .unwrap_or(false);

        let mut inner = self.inner.write().await;
        inner.available = result;
        inner.last_checked = Instant::now();
        inner.last_request = Instant::now();

        result
    }

    /// Fire-and-forget variant of check_now.
    pub async fn refresh(&self) {
        let _ = self.check_now().await;
    }

    /// One-shot refresh for startup.
    pub async fn warm(&self) {
        self.refresh().await;
    }
}

// ─── Types ──────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AcousticMatch {
    pub diarization_speaker: String,
    pub matched_name: String,
    pub cosine_similarity: f64,
    pub confirmed: bool, // similarity >= 0.85
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SpeakerInfo {
    pub id: String,
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
    pub acoustic_confidence: Option<f64>,
    pub resolution_method: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MeetingMetadata {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub date: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub language: Option<String>,
}

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
    #[serde(rename = "acoustic_matches_complete")]
    AcousticMatchesComplete {
        matches: Vec<AcousticMatch>,
    },
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
pub struct JobHandle {
    pub tx: broadcast::Sender<PipelineEvent>,
    pub result: Arc<RwLock<JobResult>>,
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
    pub speakers: Option<Vec<SpeakerInfo>>,
    pub meeting_metadata: Option<MeetingMetadata>,
    pub error: Option<String>,
}

pub type JobStore = Arc<RwLock<HashMap<String, JobHandle>>>;

// ─── Tool context for agentic loop ─────────────────────────────────

pub struct ToolContext {
    pub audio_bytes: Vec<u8>,
    pub resolutions: HashMap<String, SpeakerResolution>,
    pub merges: Vec<(String, String)>,
    pub ambiguities: Vec<AgentAmbiguity>,
    pub action_items: Vec<ActionItemRich>,
    pub diarization_url: String,
    pub voiceprint_store: super::voiceprint::SharedVoiceprintStore,
    pub gpu_available: bool,
}
