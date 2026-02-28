use std::env;
use std::path::PathBuf;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tokio::sync::RwLock;
use uuid::Uuid;

/// A single voiceprint match from similarity search.
#[derive(Clone, Debug, Serialize)]
pub struct VoiceprintMatch {
    pub name: String,
    pub id: String,
    pub similarity: f64,
}

/// Enrolled speaker metadata.
#[derive(Clone, Debug, Serialize)]
pub struct Speaker {
    pub id: String,
    pub name: String,
}

/// Persisted voiceprint entry.
#[derive(Clone, Debug, Serialize, Deserialize)]
struct VoiceprintEntry {
    id: String,
    name: String,
    embedding: Vec<f32>,
}

/// In-memory voiceprint store with JSON file persistence and cosine similarity search.
/// Same API surface as the planned Zvec backend — swap in later when C++ build is resolved.
pub struct VoiceprintStore {
    entries: RwLock<Vec<VoiceprintEntry>>,
    persist_path: PathBuf,
}

impl VoiceprintStore {
    /// Open or create a voiceprint store at `store_path`.
    pub fn init(store_path: &str) -> anyhow::Result<Self> {
        std::fs::create_dir_all(store_path)?;

        let persist_path = PathBuf::from(store_path).join("voiceprints.json");
        let entries = if persist_path.exists() {
            let data = std::fs::read_to_string(&persist_path)?;
            serde_json::from_str(&data).unwrap_or_default()
        } else {
            Vec::new()
        };

        tracing::info!(path = %store_path, speakers = entries.len(), "Voiceprint store ready");
        Ok(Self {
            entries: RwLock::new(entries),
            persist_path,
        })
    }

    /// Enroll a speaker: store embedding + name, return generated speaker ID.
    pub async fn enroll(&self, name: &str, embedding: &[f32]) -> anyhow::Result<String> {
        let speaker_id = Uuid::new_v4().to_string();

        let entry = VoiceprintEntry {
            id: speaker_id.clone(),
            name: name.to_string(),
            embedding: embedding.to_vec(),
        };

        {
            let mut entries = self.entries.write().await;
            entries.push(entry);
            self.persist(&entries)?;
        }

        tracing::info!(id = %speaker_id, name = %name, "Enrolled speaker");
        Ok(speaker_id)
    }

    /// Identify: find top-k nearest voiceprints by cosine similarity.
    pub async fn identify(
        &self,
        embedding: &[f32],
        top_k: usize,
    ) -> anyhow::Result<Vec<VoiceprintMatch>> {
        let entries = self.entries.read().await;

        let mut scored: Vec<VoiceprintMatch> = entries
            .iter()
            .map(|entry| VoiceprintMatch {
                name: entry.name.clone(),
                id: entry.id.clone(),
                similarity: cosine_similarity(embedding, &entry.embedding),
            })
            .collect();

        // Sort descending by similarity
        scored.sort_by(|a, b| b.similarity.partial_cmp(&a.similarity).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(top_k);

        Ok(scored)
    }

    /// List all enrolled speakers.
    pub async fn list_speakers(&self) -> anyhow::Result<Vec<Speaker>> {
        let entries = self.entries.read().await;
        Ok(entries
            .iter()
            .map(|e| Speaker {
                id: e.id.clone(),
                name: e.name.clone(),
            })
            .collect())
    }

    fn persist(&self, entries: &[VoiceprintEntry]) -> anyhow::Result<()> {
        let data = serde_json::to_string(entries)?;
        std::fs::write(&self.persist_path, data)?;
        Ok(())
    }
}

fn cosine_similarity(a: &[f32], b: &[f32]) -> f64 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let mut dot = 0.0f64;
    let mut norm_a = 0.0f64;
    let mut norm_b = 0.0f64;
    for (x, y) in a.iter().zip(b.iter()) {
        let x = *x as f64;
        let y = *y as f64;
        dot += x * y;
        norm_a += x * x;
        norm_b += y * y;
    }
    let denom = norm_a.sqrt() * norm_b.sqrt();
    if denom == 0.0 {
        0.0
    } else {
        dot / denom
    }
}

/// Default store path, configurable via `VOICEPRINT_STORE_PATH` env var.
pub fn store_path() -> String {
    env::var("VOICEPRINT_STORE_PATH").unwrap_or_else(|_| "data/voiceprints".into())
}

/// Shared handle for Axum state.
pub type SharedVoiceprintStore = Arc<VoiceprintStore>;
