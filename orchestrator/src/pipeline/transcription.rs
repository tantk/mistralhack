use std::time::Duration;
use tokio::sync::broadcast;

use super::types::*;

pub async fn call_mistral_transcribe(
    audio: &[u8],
    tx: &broadcast::Sender<PipelineEvent>,
) -> anyhow::Result<TranscriptionResult> {
    let api_key = mistral_api_key();
    if api_key.is_empty() {
        // Fallback to self-hosted Voxtral (streaming tokens, no word timestamps)
        tracing::info!("No MISTRAL_API_KEY, falling back to self-hosted Voxtral");
        let text = call_voxtral(audio, tx).await?;
        return Ok(TranscriptionResult {
            text,
            words: Vec::new(),
            language: None,
            duration_ms: 0,
        });
    }

    let client = reqwest::Client::new();
    let part = reqwest::multipart::Part::bytes(audio.to_vec())
        .file_name("audio.wav")
        .mime_str("audio/wav")?;
    let form = reqwest::multipart::Form::new()
        .part("file", part)
        .text("model", "voxtral-mini-latest")
        .text("response_format", "verbose_json")
        .text("timestamp_granularities[]", "word");

    let resp = client
        .post("https://api.mistral.ai/v1/audio/transcriptions")
        .header("Authorization", format!("Bearer {api_key}"))
        .multipart(form)
        .timeout(Duration::from_secs(120))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        // Fallback to self-hosted on API error
        tracing::warn!(
            "Mistral transcription API returned {status}: {body}, falling back to Voxtral"
        );
        let text = call_voxtral(audio, tx).await?;
        return Ok(TranscriptionResult {
            text,
            words: Vec::new(),
            language: None,
            duration_ms: 0,
        });
    }

    let data: serde_json::Value = resp.json().await?;

    let text = data["text"].as_str().unwrap_or("").to_string();
    let language = data["language"].as_str().map(|s| s.to_string());
    let duration_ms = data["duration"]
        .as_f64()
        .map(|d| (d * 1000.0) as u64)
        .unwrap_or(0);

    let words: Vec<Word> = data["words"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|w| {
                    Some(Word {
                        word: w["word"].as_str()?.to_string(),
                        start: w["start"].as_f64()?,
                        end: w["end"].as_f64()?,
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    Ok(TranscriptionResult {
        text,
        words,
        language,
        duration_ms,
    })
}

/// Fallback: self-hosted Voxtral with streaming tokens (no word timestamps)
pub async fn call_voxtral(
    audio: &[u8],
    tx: &broadcast::Sender<PipelineEvent>,
) -> anyhow::Result<String> {
    let client = reqwest::Client::new();
    let part = reqwest::multipart::Part::bytes(audio.to_vec())
        .file_name("audio.wav")
        .mime_str("audio/wav")?;
    let form = reqwest::multipart::Form::new().part("audio", part);

    let resp = client
        .post(format!("{}/transcribe/stream", voxtral_url()))
        .multipart(form)
        .timeout(Duration::from_secs(300))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("Voxtral returned {status}: {body}");
    }

    // Parse SSE stream from response
    use futures::StreamExt;
    let mut full_text = String::new();
    let mut current_event = String::new();
    let mut byte_stream = resp.bytes_stream();
    let mut buf = String::new();

    while let Some(chunk) = byte_stream.next().await {
        let chunk = chunk?;
        buf.push_str(&String::from_utf8_lossy(&chunk));

        // Process complete lines from buffer
        while let Some(newline_pos) = buf.find('\n') {
            let line = buf[..newline_pos].trim_end_matches('\r').to_string();
            buf = buf[newline_pos + 1..].to_string();

            if line.starts_with("event: ") {
                current_event = line["event: ".len()..].to_string();
            } else if line.starts_with("data: ") {
                let data = &line["data: ".len()..];
                match current_event.as_str() {
                    "token" => {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(data) {
                            if let Some(token) = parsed["token"].as_str() {
                                full_text.push_str(token);
                                let _ = tx.send(PipelineEvent::TranscriptToken {
                                    token: token.to_string(),
                                });
                            }
                        }
                    }
                    "done" => {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(data) {
                            if let Some(text) = parsed["text"].as_str() {
                                return Ok(text.to_string());
                            }
                        }
                    }
                    _ => {}
                }
                current_event.clear();
            }
        }
    }

    // If we didn't get a done event, return accumulated text
    if !full_text.is_empty() {
        Ok(full_text.trim().to_string())
    } else {
        anyhow::bail!("Voxtral stream ended without producing any text")
    }
}
