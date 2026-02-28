use std::collections::HashMap;
use std::time::Duration;

use super::types::*;

pub async fn call_analysis(
    segments: &[Segment],
) -> anyhow::Result<(Vec<Decision>, Vec<Ambiguity>, Vec<ActionItemRich>, Option<String>, Option<String>)> {
    let api_key = mistral_api_key();
    if api_key.is_empty() {
        anyhow::bail!("MISTRAL_API_KEY not set");
    }

    let transcript_lines: Vec<String> = segments
        .iter()
        .map(|s| format!("[{:.0}s] {}: {}", s.start, s.speaker, s.text))
        .collect();

    let prompt = format!(
        r#"Analyze this speaker-attributed meeting transcript and extract structured intelligence.

TRANSCRIPT:
{}

Return a JSON object with exactly these fields:
{{
  "decisions": [
    {{
      "timestamp": <number, seconds into meeting>,
      "summary": "<what was decided>",
      "proposed_by": "<speaker name>",
      "seconded_by": "<speaker name or null>",
      "dissent_by": "<speaker name or null>",
      "status": "locked" | "open" | "contested"
    }}
  ],
  "ambiguities": [
    {{
      "timestamp": <number>,
      "type": "attributional" | "commitment" | "temporal" | "scope",
      "quote": "<the ambiguous statement>",
      "speaker": "<who said it>",
      "confidence": <0-1, how confident the attribution is>,
      "candidates": ["<possible interpretations or speakers>"]
    }}
  ],
  "action_items": [
    {{
      "owner": "<person responsible>",
      "task": "<task description>",
      "deadline_mentioned": "<deadline if mentioned, or null>",
      "verbatim_quote": "<exact quote from transcript>"
    }}
  ],
  "meeting_title": "<inferred topic or title of the meeting, or null if unclear>",
  "meeting_date": "<ISO 8601 date if mentioned or inferrable, e.g. 2025-03-15, or null>"
}}

If none are found for a category, return an empty array. meeting_title and meeting_date may be null."#,
        transcript_lines.join("\n"),
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
        .timeout(Duration::from_secs(90))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("Mistral analysis returned {status}: {body}");
    }

    let data: serde_json::Value = resp.json().await?;
    let content = data["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("{}");

    let parsed: serde_json::Value = serde_json::from_str(content)?;

    let decisions: Vec<Decision> =
        serde_json::from_value(parsed["decisions"].clone()).unwrap_or_default();
    let ambiguities: Vec<Ambiguity> =
        serde_json::from_value(parsed["ambiguities"].clone()).unwrap_or_default();
    let action_items: Vec<ActionItemRich> =
        serde_json::from_value(parsed["action_items"].clone()).unwrap_or_default();

    let meeting_title = parsed["meeting_title"].as_str().map(|s| s.to_string());
    let meeting_date = parsed["meeting_date"].as_str().map(|s| s.to_string());

    Ok((decisions, ambiguities, action_items, meeting_title, meeting_date))
}

pub fn compute_meeting_dynamics(segments: &[Segment]) -> MeetingDynamics {
    let mut talk_time: HashMap<String, f64> = HashMap::new();
    let mut total_time = 0.0;

    for seg in segments {
        let dur = (seg.end - seg.start).max(0.0);
        *talk_time.entry(seg.speaker.clone()).or_insert(0.0) += dur;
        total_time += dur;
    }

    let talk_time_pct: HashMap<String, f64> = talk_time
        .into_iter()
        .map(|(speaker, time)| {
            let pct = if total_time > 0.0 {
                (time / total_time) * 100.0
            } else {
                0.0
            };
            (speaker, (pct * 10.0).round() / 10.0)
        })
        .collect();

    let mut interruption_count: u32 = 0;
    for i in 1..segments.len() {
        if segments[i].speaker != segments[i - 1].speaker
            && segments[i].start < segments[i - 1].end
        {
            interruption_count += 1;
        }
    }

    MeetingDynamics {
        talk_time_pct,
        interruption_count,
    }
}
