use std::env;
use std::path::PathBuf;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use uuid::Uuid;
use zvec_bindings::{
    CollectionSchema, Doc, FieldSchema, IndexParams, MetricType, QuantizeType, SharedCollection,
    VectorQuery, VectorSchema,
};

const EMBEDDING_DIM: u32 = 192;

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

/// Sidecar entry for speaker listing (zvec has no scan-all API).
#[derive(Clone, Debug, Serialize, Deserialize)]
struct SpeakerEntry {
    id: String,
    name: String,
}

/// Voiceprint store backed by zvec (in-process vector database).
/// Uses FLAT index with cosine similarity for small speaker collections.
pub struct VoiceprintStore {
    collection: SharedCollection,
    sidecar_path: PathBuf,
    sidecar: std::sync::RwLock<Vec<SpeakerEntry>>,
}

impl VoiceprintStore {
    /// Open or create a voiceprint store at `store_path`.
    pub fn init(store_path: &str) -> anyhow::Result<Self> {
        std::fs::create_dir_all(store_path)?;

        zvec_bindings::init().map_err(|e| anyhow::anyhow!("zvec init failed: {e}"))?;

        let collection = match zvec_bindings::open_shared(store_path) {
            Ok(c) => c,
            Err(_) => {
                // zvec requires the path to not exist for create_and_open_shared
                if std::path::Path::new(store_path).exists() {
                    std::fs::remove_dir_all(store_path)?;
                }
                let mut schema = CollectionSchema::new("voiceprints");
                schema
                    .add_field(VectorSchema::fp32("embedding", EMBEDDING_DIM).into())
                    .map_err(|e| anyhow::anyhow!("schema add embedding: {e}"))?;
                schema
                    .add_field(FieldSchema::string("name"))
                    .map_err(|e| anyhow::anyhow!("schema add name: {e}"))?;

                let c = zvec_bindings::create_and_open_shared(store_path, schema)
                    .map_err(|e| anyhow::anyhow!("create collection: {e}"))?;

                c.create_index(
                    "embedding",
                    IndexParams::flat(MetricType::Cosine, QuantizeType::Undefined),
                )
                .map_err(|e| anyhow::anyhow!("create index: {e}"))?;

                c
            }
        };

        let sidecar_path = PathBuf::from(store_path).join("speakers.json");
        let sidecar: Vec<SpeakerEntry> = if sidecar_path.exists() {
            let data = std::fs::read_to_string(&sidecar_path)?;
            serde_json::from_str(&data).unwrap_or_default()
        } else {
            Vec::new()
        };

        tracing::info!(path = %store_path, speakers = sidecar.len(), "Voiceprint store ready (zvec)");
        Ok(Self {
            collection,
            sidecar_path,
            sidecar: std::sync::RwLock::new(sidecar),
        })
    }

    /// Enroll a speaker: store embedding + name, return generated speaker ID.
    pub fn enroll(&self, name: &str, embedding: &[f32]) -> anyhow::Result<String> {
        let speaker_id = Uuid::new_v4().to_string();

        let doc = Doc::id(&speaker_id)
            .with_vector("embedding", embedding)
            .map_err(|e| anyhow::anyhow!("doc vector: {e}"))?
            .with_string("name", name)
            .map_err(|e| anyhow::anyhow!("doc name: {e}"))?;

        self.collection
            .insert(&[doc])
            .map_err(|e| anyhow::anyhow!("insert: {e}"))?;

        {
            let mut sidecar = self
                .sidecar
                .write()
                .map_err(|e| anyhow::anyhow!("lock poisoned: {e}"))?;
            sidecar.push(SpeakerEntry {
                id: speaker_id.clone(),
                name: name.to_string(),
            });
            self.persist_sidecar(&sidecar)?;
        }

        tracing::info!(id = %speaker_id, name = %name, "Enrolled speaker");
        Ok(speaker_id)
    }

    /// Identify: find top-k nearest voiceprints by cosine similarity.
    pub fn identify(
        &self,
        embedding: &[f32],
        top_k: usize,
    ) -> anyhow::Result<Vec<VoiceprintMatch>> {
        let query = VectorQuery::new("embedding")
            .topk(top_k)
            .output_fields(&["name"])
            .vector(embedding)
            .map_err(|e| anyhow::anyhow!("query build: {e}"))?;

        let results = self
            .collection
            .query(query)
            .map_err(|e| anyhow::anyhow!("query: {e}"))?;

        let matches: Vec<VoiceprintMatch> = results
            .iter()
            .map(|doc| VoiceprintMatch {
                id: doc.pk().to_string(),
                name: doc.get_string("name").unwrap_or("unknown").to_string(),
                similarity: doc.score() as f64,
            })
            .collect();

        Ok(matches)
    }

    /// List all enrolled speakers.
    pub fn list_speakers(&self) -> anyhow::Result<Vec<Speaker>> {
        let sidecar = self
            .sidecar
            .read()
            .map_err(|e| anyhow::anyhow!("lock poisoned: {e}"))?;
        Ok(sidecar
            .iter()
            .map(|e| Speaker {
                id: e.id.clone(),
                name: e.name.clone(),
            })
            .collect())
    }

    fn persist_sidecar(&self, entries: &[SpeakerEntry]) -> anyhow::Result<()> {
        let data = serde_json::to_string(entries)?;
        std::fs::write(&self.sidecar_path, data)?;
        Ok(())
    }
}

/// Default store path, configurable via `VOICEPRINT_STORE_PATH` env var.
pub fn store_path() -> String {
    env::var("VOICEPRINT_STORE_PATH").unwrap_or_else(|_| "data/voiceprints".into())
}

/// Shared handle for Axum state.
pub type SharedVoiceprintStore = Arc<VoiceprintStore>;
