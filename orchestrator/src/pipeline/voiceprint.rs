use std::env;
use std::sync::Arc;

use serde::{Deserialize, Serialize};

/// A single voiceprint match from similarity search.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct VoiceprintMatch {
    pub name: String,
    pub id: String,
    pub similarity: f64,
}

/// Enrolled speaker metadata.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Speaker {
    pub id: String,
    pub name: String,
}

/// Voiceprint store backed by a remote vectordb microservice.
pub struct VoiceprintStore {
    client: reqwest::Client,
    base_url: String,
}

impl VoiceprintStore {
    pub fn new() -> Self {
        let base_url = env::var("VOICEPRINT_SERVICE_URL")
            .unwrap_or_else(|_| "https://tantk-meetingmind-vectordb.hf.space".into());
        tracing::info!(url = %base_url, "Voiceprint store (remote HTTP)");
        Self {
            client: reqwest::Client::new(),
            base_url,
        }
    }

    /// Enroll a speaker: store embedding + name, return generated speaker ID.
    pub async fn enroll(&self, name: &str, embedding: &[f32]) -> anyhow::Result<String> {
        let resp = self
            .client
            .post(format!("{}/enroll", self.base_url))
            .json(&serde_json::json!({
                "name": name,
                "embedding": embedding,
            }))
            .timeout(std::time::Duration::from_secs(10))
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("Voiceprint enroll failed ({status}): {body}");
        }

        let data: serde_json::Value = resp.json().await?;
        let speaker_id = data["speaker_id"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("No speaker_id in response"))?
            .to_string();

        tracing::info!(id = %speaker_id, name = %name, "Enrolled speaker");
        Ok(speaker_id)
    }

    /// Identify: find top-k nearest voiceprints by cosine similarity.
    pub async fn identify(
        &self,
        embedding: &[f32],
        top_k: usize,
    ) -> anyhow::Result<Vec<VoiceprintMatch>> {
        let resp = self
            .client
            .post(format!("{}/identify", self.base_url))
            .json(&serde_json::json!({
                "embedding": embedding,
                "top_k": top_k,
            }))
            .timeout(std::time::Duration::from_secs(10))
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("Voiceprint identify failed ({status}): {body}");
        }

        #[derive(Deserialize)]
        struct Resp {
            matches: Vec<VoiceprintMatch>,
        }
        let data: Resp = resp.json().await?;
        Ok(data.matches)
    }

    /// List all enrolled speakers.
    pub async fn list_speakers(&self) -> anyhow::Result<Vec<Speaker>> {
        let resp = self
            .client
            .get(format!("{}/speakers", self.base_url))
            .timeout(std::time::Duration::from_secs(10))
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("Voiceprint list_speakers failed ({status}): {body}");
        }

        #[derive(Deserialize)]
        struct Resp {
            speakers: Vec<Speaker>,
        }
        let data: Resp = resp.json().await?;
        Ok(data.speakers)
    }
}

/// Shared handle for Axum state.
pub type SharedVoiceprintStore = Arc<VoiceprintStore>;
