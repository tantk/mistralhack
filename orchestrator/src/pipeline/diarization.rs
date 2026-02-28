use serde::Deserialize;
use std::time::Duration;

use super::types::*;

#[derive(Deserialize)]
pub struct DiarSegment {
    pub speaker: String,
    pub start: f64,
    pub end: f64,
}

pub async fn call_diarize(audio: &[u8]) -> anyhow::Result<Vec<DiarSegment>> {
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

pub fn align_words_to_speakers(words: &[Word], diar_segments: &[DiarSegment]) -> Vec<AlignedWord> {
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

pub fn group_into_segments(aligned: &[AlignedWord]) -> Vec<Segment> {
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
