use std::time::Duration;

use super::diarization::DiarSegment;
use super::types::*;

/// Use Mistral to align the full transcript to diarization segments.
pub async fn align_transcript(
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
pub fn basic_align(transcript: &str, diar_segments: &[DiarSegment]) -> Vec<Segment> {
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
