use serde::{Deserialize, Serialize};
use std::{collections::HashMap, env, sync::Arc};
use tokio::sync::{broadcast, RwLock};

// ─── Config ─────────────────────────────────────────────────────────

pub fn voxtral_url() -> String {
    env::var("VOXTRAL_URL").unwrap_or_else(|_| "http://192.168.0.105:8080".into())
}

pub fn diarization_url() -> String {
    env::var("DIARIZATION_URL").unwrap_or_else(|_| "http://192.168.0.105:8001".into())
}

pub fn mistral_api_key() -> String {
    env::var("MISTRAL_API_KEY").unwrap_or_default()
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
}
