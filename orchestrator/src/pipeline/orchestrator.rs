use std::sync::Arc;
use tokio::sync::{broadcast, RwLock};

use super::agent::run_agent;
use super::alignment::{align_transcript, basic_align};
use super::analysis::{call_analysis, compute_meeting_dynamics};
use super::diarization::{align_words_to_speakers, call_diarize, group_into_segments};
use super::transcription::call_mistral_transcribe;
use super::types::*;

pub async fn run_pipeline(
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

pub async fn set_error(
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
