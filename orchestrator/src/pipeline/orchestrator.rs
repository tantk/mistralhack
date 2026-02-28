use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{broadcast, RwLock};

use super::agent::run_agent;
use super::alignment::{align_transcript, basic_align};
use super::analysis::{call_analysis, compute_meeting_dynamics};
use super::diarization::{align_words_to_speakers, call_diarize, call_mistral_diarize, group_into_segments, DiarSegment};
use super::transcription::call_mistral_transcribe;
use super::types::*;
use super::types::GpuHealthCache;
use super::voiceprint::SharedVoiceprintStore;

pub async fn run_pipeline(
    tx: broadcast::Sender<PipelineEvent>,
    result: Arc<RwLock<JobResult>>,
    audio_bytes: Vec<u8>,
    job_id: String,
    attendees: Vec<String>,
    voiceprint_store: SharedVoiceprintStore,
    gpu_health: GpuHealthCache,
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
            tracing::warn!(job_id = %job_id, "GPU diarization failed: {e}, trying Mistral API fallback");
            let api_key = mistral_api_key();
            if api_key.is_empty() {
                set_error(&result, &tx, &format!("Diarization failed: GPU unavailable, no MISTRAL_API_KEY for fallback")).await;
                return;
            }
            match call_mistral_diarize(&audio_bytes, &api_key).await {
                Ok(segs) => segs,
                Err(e2) => {
                    set_error(&result, &tx, &format!("Diarization failed: GPU ({e}) and Mistral API ({e2}) both failed")).await;
                    return;
                }
            }
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

    let gpu_available = gpu_health.check_now().await;
    let acoustic_matches = if gpu_available {
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
        }
    } else {
        tracing::info!(job_id = %job_id, "Skipping acoustic matching (GPU unavailable)");
        Vec::new()
    };

    let _ = tx.send(PipelineEvent::AcousticMatchesComplete {
        matches: acoustic_matches.clone(),
    });

    // ── Phase 3: Agent-based Speaker Resolution ──
    let _ = tx.send(PipelineEvent::PhaseStart {
        phase: "resolving".into(),
    });
    result.write().await.phase = Some("resolving".into());

    let gpu_available = gpu_health.check_now().await;
    let (resolved_segments, agent_action_items) =
        match run_agent(&tx, &segments, &audio_bytes, &acoustic_matches, &attendees, &voiceprint_store, gpu_available).await {
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

    let (decisions, ambiguities, analysis_action_items, extracted_title, extracted_date) =
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
        title: extracted_title,
        date: extracted_date,
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

    // Group diarization segments by speaker, pick the best for each
    let unique_speakers: Vec<String> = {
        let mut seen = std::collections::HashSet::new();
        diar_segments.iter().filter_map(|s| {
            if seen.insert(s.speaker.clone()) { Some(s.speaker.clone()) } else { None }
        }).collect()
    };

    let client = reqwest::Client::new();
    let mut matches = Vec::new();

    for speaker_label in &unique_speakers {
        let Some((seg_start, seg_end)) = select_best_segment(speaker_label, diar_segments) else {
            tracing::debug!(
                job_id = %job_id,
                speaker = %speaker_label,
                "No suitable segment for embedding, skipping"
            );
            continue;
        };

        let duration_ms = ((seg_end - seg_start) * 1000.0) as i64;
        tracing::debug!(
            job_id = %job_id,
            speaker = %speaker_label,
            duration_ms = duration_ms,
            "Selected segment {:.2}s-{:.2}s for embedding",
            seg_start, seg_end
        );

        // Step 1: Call GPU /embed with start_time/end_time to get embedding vector
        let part = reqwest::multipart::Part::bytes(audio_bytes.to_vec())
            .file_name("audio.wav")
            .mime_str("audio/wav")?;
        let form = reqwest::multipart::Form::new()
            .part("audio", part)
            .text("start_time", seg_start.to_string())
            .text("end_time", seg_end.to_string());

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

/// Select the best audio segment for a speaker's voiceprint embedding.
/// Prefers: non-overlapping segments, ~5s duration, concatenation of adjacent segments if needed.
fn select_best_segment(speaker: &str, diar_segments: &[DiarSegment]) -> Option<(f64, f64)> {
    let mine: Vec<&DiarSegment> = diar_segments
        .iter()
        .filter(|s| s.speaker == speaker)
        .collect();

    if mine.is_empty() {
        return None;
    }

    // Identify non-overlapping segments (no other speaker's segment overlaps temporally)
    let non_overlapping: Vec<&DiarSegment> = mine
        .iter()
        .filter(|seg| {
            !diar_segments.iter().any(|other| {
                other.speaker != speaker
                    && other.start < seg.end
                    && other.end > seg.start
            })
        })
        .copied()
        .collect();

    // Use non-overlapping if available, otherwise fall back to all
    let candidates = if non_overlapping.is_empty() { &mine } else { &non_overlapping };

    // Find single segment closest to 5.0s (minimum 500ms)
    let best_single = candidates
        .iter()
        .filter(|s| (s.end - s.start) >= 0.5)
        .min_by(|a, b| {
            let da = ((a.end - a.start) - 5.0_f64).abs();
            let db = ((b.end - b.start) - 5.0_f64).abs();
            da.partial_cmp(&db).unwrap_or(std::cmp::Ordering::Equal)
        });

    if let Some(seg) = best_single {
        if (seg.end - seg.start) >= 3.0 {
            return Some((seg.start, seg.end));
        }
    }

    // Try concatenating adjacent same-speaker segments (gap ≤ 0.5s, total ≤ 6s)
    let mut sorted: Vec<&DiarSegment> = mine.clone();
    sorted.sort_by(|a, b| a.start.partial_cmp(&b.start).unwrap_or(std::cmp::Ordering::Equal));

    let mut best_concat: Option<(f64, f64, f64)> = None; // (start, end, distance_from_5s)
    for i in 0..sorted.len() {
        let mut end = sorted[i].end;
        let start = sorted[i].start;
        let mut total = end - start;

        if total >= 0.5 && total <= 6.0 {
            let dist = (total - 5.0).abs();
            if best_concat.as_ref().map_or(true, |b| dist < b.2) {
                best_concat = Some((start, end, dist));
            }
        }

        for j in (i + 1)..sorted.len() {
            let gap = sorted[j].start - end;
            if gap > 0.5 {
                break;
            }
            end = sorted[j].end;
            total = end - start;
            if total > 6.0 {
                break;
            }
            if total >= 0.5 {
                let dist = (total - 5.0).abs();
                if best_concat.as_ref().map_or(true, |b| dist < b.2) {
                    best_concat = Some((start, end, dist));
                }
            }
        }
    }

    if let Some((start, end, _)) = best_concat {
        if (end - start) >= 3.0 {
            return Some((start, end));
        }
    }

    // Final fallback: use the best single segment regardless of duration (if ≥ 500ms)
    if let Some(seg) = best_single {
        return Some((seg.start, seg.end));
    }

    // Absolute fallback: any segment ≥ 500ms
    mine.iter()
        .filter(|s| (s.end - s.start) >= 0.5)
        .max_by(|a, b| {
            (a.end - a.start).partial_cmp(&(b.end - b.start)).unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(|s| (s.start, s.end))
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
