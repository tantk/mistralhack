use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{broadcast, RwLock};

use super::agent::run_agent;
use super::alignment::{align_transcript, basic_align};
use super::analysis::{call_analysis, compute_meeting_dynamics};
use super::diarization::{align_words_to_speakers, call_diarize, group_into_segments, DiarSegment};
use super::transcription::call_mistral_transcribe;
use super::types::*;
use super::voiceprint::SharedVoiceprintStore;

pub async fn run_pipeline(
    tx: broadcast::Sender<PipelineEvent>,
    result: Arc<RwLock<JobResult>>,
    audio_bytes: Vec<u8>,
    job_id: String,
    attendees: Vec<String>,
    voiceprint_store: SharedVoiceprintStore,
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

    // ── Phase 2.5: Proactive Acoustic Matching ──
    let _ = tx.send(PipelineEvent::PhaseStart {
        phase: "acoustic_matching".into(),
    });
    result.write().await.phase = Some("acoustic_matching".into());

    let acoustic_matches =
        match proactive_acoustic_match(&audio_bytes, &diar_segments, &job_id, &voiceprint_store).await {
            Ok(matches) => {
                tracing::info!(
                    job_id = %job_id,
                    matches = matches.len(),
                    "Acoustic matching complete"
                );
                matches
            }
            Err(e) => {
                tracing::warn!(
                    job_id = %job_id,
                    "Acoustic matching failed, continuing without: {e}"
                );
                Vec::new()
            }
        };

    let _ = tx.send(PipelineEvent::AcousticMatchesComplete {
        matches: acoustic_matches.clone(),
    });

    // ── Phase 3: Agent-based Speaker Resolution ──
    let _ = tx.send(PipelineEvent::PhaseStart {
        phase: "resolving".into(),
    });
    result.write().await.phase = Some("resolving".into());

    let (resolved_segments, agent_action_items) =
        match run_agent(&tx, &segments, &audio_bytes, &acoustic_matches, &attendees, &voiceprint_store).await {
            Ok((segs, items)) => (segs, items),
            Err(e) => {
                tracing::warn!(job_id = %job_id, "Agent resolution failed, applying threshold fallback: {e}");
                // Threshold fallback: apply acoustic matches with similarity >= 0.85
                let fallback_segments =
                    apply_threshold_fallback(&segments, &acoustic_matches, &tx);
                (fallback_segments, Vec::new())
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

    // Build speakers array from resolved segments + acoustic matches
    let speakers = build_speakers_array(&resolved_segments, &acoustic_matches);

    // Build meeting metadata
    let meeting_metadata = MeetingMetadata {
        title: None,
        date: None,
        duration: Some(format!("{:.1}s", transcription.duration_ms as f64 / 1000.0)),
        language: transcription.language.clone(),
    };

    tracing::info!(
        job_id = %job_id,
        decisions = decisions.len(),
        ambiguities = ambiguities.len(),
        action_items = action_items.len(),
        "Analysis complete"
    );

    {
        let mut r = result.write().await;
        r.decisions = Some(decisions.clone());
        r.ambiguities = Some(ambiguities.clone());
        r.action_items = Some(action_items.clone());
        r.meeting_dynamics = Some(meeting_dynamics.clone());
        r.speakers = Some(speakers);
        r.meeting_metadata = Some(meeting_metadata);
    }
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

/// Proactive acoustic matching: for each unique diarization speaker, pick the
/// longest segment as representative, call GPU /embed, and look up in local Zvec.
async fn proactive_acoustic_match(
    audio_bytes: &[u8],
    diar_segments: &[DiarSegment],
    job_id: &str,
    voiceprint_store: &SharedVoiceprintStore,
) -> anyhow::Result<Vec<AcousticMatch>> {
    let gpu_base = diarization_url();

    // Group diarization segments by speaker, pick the longest for each
    let mut speaker_best: HashMap<String, &DiarSegment> = HashMap::new();
    for seg in diar_segments {
        let dur = seg.end - seg.start;
        let is_longer = speaker_best
            .get(&seg.speaker)
            .map(|best| dur > (best.end - best.start))
            .unwrap_or(true);
        if is_longer {
            speaker_best.insert(seg.speaker.clone(), seg);
        }
    }

    let client = reqwest::Client::new();
    let mut matches = Vec::new();

    for (speaker_label, best_seg) in &speaker_best {
        let duration_ms = ((best_seg.end - best_seg.start) * 1000.0) as i64;
        if duration_ms < 500 {
            tracing::debug!(
                job_id = %job_id,
                speaker = %speaker_label,
                "Segment too short for embedding ({duration_ms}ms), skipping"
            );
            continue;
        }

        // Step 1: Call GPU /embed with start_time/end_time to get embedding vector
        let part = reqwest::multipart::Part::bytes(audio_bytes.to_vec())
            .file_name("audio.wav")
            .mime_str("audio/wav")?;
        let form = reqwest::multipart::Form::new()
            .part("audio", part)
            .text("start_time", best_seg.start.to_string())
            .text("end_time", best_seg.end.to_string());

        let embed_result = client
            .post(format!("{}/embed", gpu_base))
            .multipart(form)
            .timeout(Duration::from_secs(30))
            .send()
            .await;

        match embed_result {
            Ok(resp) if resp.status().is_success() => {
                if let Ok(data) = resp.json::<serde_json::Value>().await {
                    let embedding: Vec<f32> = data["embedding"]
                        .as_array()
                        .map(|arr| arr.iter().filter_map(|v| v.as_f64().map(|f| f as f32)).collect())
                        .unwrap_or_default();

                    if embedding.is_empty() {
                        tracing::warn!(job_id = %job_id, speaker = %speaker_label, "Empty embedding from GPU");
                        continue;
                    }

                    // Step 2: Local voiceprint store lookup
                    match voiceprint_store.identify(&embedding, 3) {
                        Ok(vp_matches) => {
                            if let Some(best) = vp_matches.first() {
                                matches.push(AcousticMatch {
                                    diarization_speaker: speaker_label.clone(),
                                    matched_name: best.name.clone(),
                                    cosine_similarity: best.similarity,
                                    confirmed: best.similarity >= 0.85,
                                });
                            }
                        }
                        Err(e) => {
                            tracing::warn!(
                                job_id = %job_id,
                                speaker = %speaker_label,
                                "Zvec identify failed: {e}"
                            );
                        }
                    }
                }
            }
            Ok(resp) => {
                let status = resp.status();
                tracing::warn!(
                    job_id = %job_id,
                    speaker = %speaker_label,
                    "GPU /embed returned {status}"
                );
            }
            Err(e) => {
                tracing::warn!(
                    job_id = %job_id,
                    speaker = %speaker_label,
                    "GPU /embed failed: {e}"
                );
            }
        }
    }

    Ok(matches)
}

/// Threshold fallback: when the agent fails, apply acoustic matches with
/// cosine similarity >= 0.85 as automatic speaker resolutions.
fn apply_threshold_fallback(
    segments: &[Segment],
    acoustic_matches: &[AcousticMatch],
    tx: &broadcast::Sender<PipelineEvent>,
) -> Vec<Segment> {
    let mut fallback_map: HashMap<String, &AcousticMatch> = HashMap::new();
    for m in acoustic_matches {
        if m.cosine_similarity >= 0.85 {
            fallback_map.insert(m.diarization_speaker.clone(), m);
        }
    }

    if fallback_map.is_empty() {
        return segments.to_vec();
    }

    tracing::info!(
        resolved = fallback_map.len(),
        "Applying threshold fallback for {} speakers",
        fallback_map.len()
    );

    for m in fallback_map.values() {
        let _ = tx.send(PipelineEvent::SpeakerResolved {
            label: m.diarization_speaker.clone(),
            name: m.matched_name.clone(),
            confidence: m.cosine_similarity,
            method: "threshold_fallback".to_string(),
        });
    }

    segments
        .iter()
        .map(|seg| {
            let speaker = if let Some(m) = fallback_map.get(&seg.speaker) {
                m.matched_name.clone()
            } else {
                seg.speaker.clone()
            };
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

/// Build a speakers array from resolved segments and acoustic match data.
fn build_speakers_array(
    segments: &[Segment],
    acoustic_matches: &[AcousticMatch],
) -> Vec<SpeakerInfo> {
    let mut seen: HashMap<String, SpeakerInfo> = HashMap::new();

    // Build acoustic lookup
    let acoustic_map: HashMap<String, &AcousticMatch> = acoustic_matches
        .iter()
        .map(|m| (m.diarization_speaker.clone(), m))
        .collect();

    for seg in segments {
        if seen.contains_key(&seg.speaker) {
            continue;
        }

        // Determine resolution method and acoustic confidence
        let (acoustic_confidence, resolution_method) =
            if let Some(m) = acoustic_map.get(&seg.speaker) {
                (Some(m.cosine_similarity), "agent+acoustic".to_string())
            } else {
                // Check if speaker name looks resolved (not SPEAKER_XX pattern)
                if seg.speaker.starts_with("SPEAKER_") {
                    (None, "unresolved".to_string())
                } else {
                    (None, "agent".to_string())
                }
            };

        seen.insert(
            seg.speaker.clone(),
            SpeakerInfo {
                id: seg.speaker.clone(),
                name: seg.speaker.clone(),
                role: None,
                acoustic_confidence,
                resolution_method,
            },
        );
    }

    let mut speakers: Vec<SpeakerInfo> = seen.into_values().collect();
    speakers.sort_by(|a, b| a.id.cmp(&b.id));
    speakers
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
