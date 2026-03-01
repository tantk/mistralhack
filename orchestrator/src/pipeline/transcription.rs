use std::time::Duration;
use tokio::sync::broadcast;

use super::types::*;

// ─── WAV parsing + chunking helpers ─────────────────────────────────

struct WavInfo {
    sample_rate: u32,
    channels: u16,
    bits_per_sample: u16,
    data_offset: usize,
    data_length: usize,
}

fn parse_wav_header(bytes: &[u8]) -> Option<WavInfo> {
    if bytes.len() < 44 {
        return None;
    }
    // Check RIFF header
    if &bytes[0..4] != b"RIFF" || &bytes[8..12] != b"WAVE" {
        return None;
    }

    // Find fmt chunk
    let mut pos = 12;
    let mut fmt_found = false;
    let mut sample_rate = 0u32;
    let mut channels = 0u16;
    let mut bits_per_sample = 0u16;

    while pos + 8 <= bytes.len() {
        let chunk_id = &bytes[pos..pos + 4];
        let chunk_size = u32::from_le_bytes([bytes[pos + 4], bytes[pos + 5], bytes[pos + 6], bytes[pos + 7]]) as usize;

        if chunk_id == b"fmt " {
            if pos + 8 + chunk_size > bytes.len() || chunk_size < 16 {
                return None;
            }
            let fmt = &bytes[pos + 8..];
            channels = u16::from_le_bytes([fmt[2], fmt[3]]);
            sample_rate = u32::from_le_bytes([fmt[4], fmt[5], fmt[6], fmt[7]]);
            bits_per_sample = u16::from_le_bytes([fmt[14], fmt[15]]);
            fmt_found = true;
        }

        if chunk_id == b"data" {
            if !fmt_found {
                return None;
            }
            return Some(WavInfo {
                sample_rate,
                channels,
                bits_per_sample,
                data_offset: pos + 8,
                data_length: chunk_size.min(bytes.len() - pos - 8),
            });
        }

        pos += 8 + chunk_size;
        // Align to word boundary
        if pos % 2 != 0 {
            pos += 1;
        }
    }

    None
}

fn estimate_duration_secs(audio: &[u8]) -> f64 {
    if let Some(wav) = parse_wav_header(audio) {
        let bytes_per_sample = wav.bits_per_sample as f64 / 8.0;
        let bytes_per_sec = wav.sample_rate as f64 * wav.channels as f64 * bytes_per_sample;
        if bytes_per_sec > 0.0 {
            return wav.data_length as f64 / bytes_per_sec;
        }
    }
    // Heuristic fallback: ~32KB/s for 16kHz 16-bit mono WAV
    audio.len() as f64 / 32_000.0
}

fn build_wav_header(sample_rate: u32, channels: u16, bits_per_sample: u16, data_len: u32) -> Vec<u8> {
    let byte_rate = sample_rate * channels as u32 * bits_per_sample as u32 / 8;
    let block_align = channels * bits_per_sample / 8;
    let file_size = 36 + data_len;

    let mut header = Vec::with_capacity(44);
    header.extend_from_slice(b"RIFF");
    header.extend_from_slice(&file_size.to_le_bytes());
    header.extend_from_slice(b"WAVE");
    // fmt chunk
    header.extend_from_slice(b"fmt ");
    header.extend_from_slice(&16u32.to_le_bytes()); // chunk size
    header.extend_from_slice(&1u16.to_le_bytes()); // PCM format
    header.extend_from_slice(&channels.to_le_bytes());
    header.extend_from_slice(&sample_rate.to_le_bytes());
    header.extend_from_slice(&byte_rate.to_le_bytes());
    header.extend_from_slice(&block_align.to_le_bytes());
    header.extend_from_slice(&bits_per_sample.to_le_bytes());
    // data chunk
    header.extend_from_slice(b"data");
    header.extend_from_slice(&data_len.to_le_bytes());
    header
}

/// Split audio into overlapping WAV chunks. Returns (chunk_bytes, time_offset) pairs.
fn chunk_audio(audio: &[u8], chunk_secs: f64, overlap_secs: f64) -> Vec<(Vec<u8>, f64)> {
    let Some(wav) = parse_wav_header(audio) else {
        // Non-WAV: return as single chunk
        return vec![(audio.to_vec(), 0.0)];
    };

    let bytes_per_sample = wav.bits_per_sample as usize / 8;
    let frame_size = wav.channels as usize * bytes_per_sample;
    let bytes_per_sec = wav.sample_rate as usize * frame_size;

    if bytes_per_sec == 0 {
        return vec![(audio.to_vec(), 0.0)];
    }

    let chunk_bytes = (chunk_secs * bytes_per_sec as f64) as usize;
    let overlap_bytes = (overlap_secs * bytes_per_sec as f64) as usize;
    let step_bytes = chunk_bytes - overlap_bytes;

    let data = &audio[wav.data_offset..wav.data_offset + wav.data_length];
    let mut chunks = Vec::new();
    let mut offset = 0usize;

    while offset < data.len() {
        let end = (offset + chunk_bytes).min(data.len());
        // Align to frame boundary
        let aligned_end = end - (end % frame_size);
        if aligned_end <= offset {
            break;
        }

        let chunk_data = &data[offset..aligned_end];
        let mut wav_chunk = build_wav_header(
            wav.sample_rate,
            wav.channels,
            wav.bits_per_sample,
            chunk_data.len() as u32,
        );
        wav_chunk.extend_from_slice(chunk_data);

        let time_offset = offset as f64 / bytes_per_sec as f64;
        chunks.push((wav_chunk, time_offset));

        if aligned_end >= data.len() {
            break;
        }
        offset += step_bytes;
        // Align to frame boundary
        offset -= offset % frame_size;
    }

    chunks
}

/// Merge word lists from overlapping chunks. For the overlap zone,
/// keep words from the earlier chunk for the first half and later chunk for the second half.
fn merge_chunked_words(chunk_results: Vec<(TranscriptionResult, f64)>) -> TranscriptionResult {
    if chunk_results.is_empty() {
        return TranscriptionResult {
            text: String::new(),
            words: Vec::new(),
            language: None,
            duration_ms: 0,
        };
    }

    if chunk_results.len() == 1 {
        let (mut result, offset) = chunk_results.into_iter().next().unwrap();
        // Offset word timestamps
        for w in &mut result.words {
            w.start += offset;
            w.end += offset;
        }
        return result;
    }

    let mut all_words: Vec<Word> = Vec::new();
    let mut all_text = String::new();
    let mut language = None;
    let mut max_duration_ms = 0u64;

    for (i, (result, offset)) in chunk_results.iter().enumerate() {
        if language.is_none() {
            language = result.language.clone();
        }

        // Offset words
        let mut words: Vec<Word> = result
            .words
            .iter()
            .map(|w| Word {
                word: w.word.clone(),
                start: w.start + offset,
                end: w.end + offset,
            })
            .collect();

        if i > 0 && !all_words.is_empty() {
            // Deduplicate overlap zone: find where previous chunk's words end
            let prev_last = all_words.last().map(|w| w.end).unwrap_or(0.0);
            let overlap_start = *offset; // This chunk starts at offset, overlap begins here
            let overlap_mid = overlap_start + 15.0; // Switch point: 15s into overlap

            // Remove words from this chunk that are in the first half of the overlap
            words.retain(|w| w.start >= overlap_mid || w.start >= prev_last);
            // Remove words from previous chunk that are in the second half of overlap
            all_words.retain(|w| w.end <= overlap_mid);
        }

        all_words.extend(words);

        let chunk_end_ms = (offset * 1000.0) as u64 + result.duration_ms;
        if chunk_end_ms > max_duration_ms {
            max_duration_ms = chunk_end_ms;
        }
    }

    // Build text from words, or concatenate texts if no words
    if !all_words.is_empty() {
        all_text = all_words.iter().map(|w| w.word.as_str()).collect::<Vec<_>>().join(" ");
    } else {
        for (i, (result, _)) in chunk_results.iter().enumerate() {
            if i > 0 {
                all_text.push(' ');
            }
            all_text.push_str(&result.text);
        }
    }

    TranscriptionResult {
        text: all_text,
        words: all_words,
        language,
        duration_ms: max_duration_ms,
    }
}

/// Standalone transcription: GPU → Mistral API → CPU (if fast enough).
/// No broadcast channel needed — suitable for the standalone `/api/transcribe` endpoint.
pub async fn transcribe_audio(audio: &[u8]) -> anyhow::Result<TranscriptionResult> {
    // 1. Try GPU service (self-hosted Voxtral on GPU)
    match call_gpu_transcribe(audio).await {
        Ok(text) => {
            tracing::info!("GPU service transcription succeeded");
            return Ok(TranscriptionResult {
                text,
                words: Vec::new(),
                language: None,
                duration_ms: 0,
            });
        }
        Err(e) => {
            tracing::warn!("GPU service transcription failed: {e}, trying Mistral API");
        }
    }

    // 2. Try Mistral API (with chunking for long audio)
    let api_key = mistral_api_key();
    if !api_key.is_empty() {
        let duration_secs = estimate_duration_secs(audio);
        if duration_secs <= 1800.0 {
            match call_mistral_api(audio, &api_key).await {
                Ok(result) => return Ok(result),
                Err(e) => {
                    tracing::warn!("Mistral API transcription failed: {e}, considering CPU fallback");
                }
            }
        } else {
            tracing::info!(
                duration_secs = duration_secs as u64,
                "Audio exceeds 30min, chunking for standalone transcription"
            );
            let chunks = chunk_audio(audio, 1500.0, 30.0);
            let mut chunk_results: Vec<(TranscriptionResult, f64)> = Vec::new();
            let mut chunking_failed = false;
            for (i, (chunk_bytes, time_offset)) in chunks.iter().enumerate() {
                match call_mistral_api(chunk_bytes, &api_key).await {
                    Ok(result) => chunk_results.push((result, *time_offset)),
                    Err(e) => {
                        tracing::warn!("Chunk {}/{} failed: {e}, falling back", i + 1, chunks.len());
                        chunking_failed = true;
                        break;
                    }
                }
            }
            if !chunking_failed {
                return Ok(merge_chunked_words(chunk_results));
            }
        }
    } else {
        tracing::warn!("No MISTRAL_API_KEY set, considering CPU fallback");
    }

    // 3. CPU fallback — only if estimated processing time <= 1 minute
    // Estimate audio duration from byte size (~32KB/s for 16kHz 16-bit mono WAV)
    // CPU Voxtral processes at ~0.1x real-time → multiply duration by 10
    let estimated_audio_secs = audio.len() as f64 / 32_000.0;
    let estimated_cpu_secs = estimated_audio_secs * 10.0;

    if estimated_cpu_secs > 60.0 {
        anyhow::bail!(
            "GPU service and Mistral API unavailable. CPU transcription estimated at {:.0}s (>{:.0}s audio) — too slow, aborting.",
            estimated_cpu_secs,
            estimated_audio_secs,
        );
    }

    tracing::info!(
        "Falling back to CPU transcription (estimated {:.0}s for {:.0}s audio)",
        estimated_cpu_secs,
        estimated_audio_secs,
    );
    let text = call_voxtral_non_streaming(audio).await?;
    Ok(TranscriptionResult {
        text,
        words: Vec::new(),
        language: None,
        duration_ms: 0,
    })
}

/// Call GPU service /transcribe endpoint (Voxtral on GPU, port 8001).
async fn call_gpu_transcribe(audio: &[u8]) -> anyhow::Result<String> {
    let client = reqwest::Client::new();
    let part = reqwest::multipart::Part::bytes(audio.to_vec())
        .file_name("audio.wav")
        .mime_str("audio/wav")?;
    let form = reqwest::multipart::Form::new().part("audio", part);

    let resp = gpu_auth(client
        .post(format!("{}/transcribe", diarization_url()))
        .multipart(form)
        .timeout(Duration::from_secs(300)))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("GPU /transcribe returned {status}: {body}");
    }

    let data: serde_json::Value = resp.json().await?;
    let text = data["text"].as_str().unwrap_or("").to_string();
    if text.is_empty() {
        anyhow::bail!("GPU /transcribe returned empty text");
    }
    Ok(text)
}

/// Pipeline transcription: tries Mistral API, falls back to Voxtral with token streaming.
pub async fn call_mistral_transcribe(
    audio: &[u8],
    tx: &broadcast::Sender<PipelineEvent>,
) -> anyhow::Result<TranscriptionResult> {
    let api_key = mistral_api_key();
    if api_key.is_empty() {
        tracing::info!("No MISTRAL_API_KEY, falling back to self-hosted Voxtral");
        let text = call_voxtral(audio, tx).await?;
        return Ok(TranscriptionResult {
            text,
            words: Vec::new(),
            language: None,
            duration_ms: 0,
        });
    }

    let duration_secs = estimate_duration_secs(audio);

    if duration_secs <= 1800.0 {
        // ≤ 30 min: single call
        match call_mistral_api(audio, &api_key).await {
            Ok(result) => Ok(result),
            Err(e) => {
                tracing::warn!("Mistral API transcription failed: {e}, falling back to Voxtral");
                let text = call_voxtral(audio, tx).await?;
                Ok(TranscriptionResult {
                    text,
                    words: Vec::new(),
                    language: None,
                    duration_ms: 0,
                })
            }
        }
    } else {
        // > 30 min: chunk into 25-min pieces with 30s overlap
        tracing::info!(
            duration_secs = duration_secs as u64,
            "Audio exceeds 30min, chunking for transcription"
        );
        let chunks = chunk_audio(audio, 1500.0, 30.0);
        tracing::info!(chunks = chunks.len(), "Split audio into chunks");

        let mut chunk_results: Vec<(TranscriptionResult, f64)> = Vec::new();
        for (i, (chunk_bytes, time_offset)) in chunks.iter().enumerate() {
            tracing::info!(
                chunk = i + 1,
                total = chunks.len(),
                offset_secs = *time_offset as u64,
                "Transcribing chunk"
            );
            match call_mistral_api(chunk_bytes, &api_key).await {
                Ok(result) => {
                    chunk_results.push((result, *time_offset));
                }
                Err(e) => {
                    tracing::error!(chunk = i + 1, "Chunk transcription failed: {e}");
                    anyhow::bail!("Chunk {}/{} transcription failed: {e}", i + 1, chunks.len());
                }
            }
        }

        Ok(merge_chunked_words(chunk_results))
    }
}

/// Call Mistral transcription API and parse the response.
async fn call_mistral_api(audio: &[u8], api_key: &str) -> anyhow::Result<TranscriptionResult> {
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
        anyhow::bail!("Mistral transcription API returned {status}: {body}");
    }

    let data: serde_json::Value = resp.json().await?;

    let text = data["text"].as_str().unwrap_or("").to_string();
    let language = data["language"].as_str().map(|s| s.to_string());
    let duration_ms = data["duration"]
        .as_f64()
        .map(|d| (d * 1000.0) as u64)
        .unwrap_or(0);

    // Mistral API returns word timestamps in "segments" (not "words")
    // Each segment: {"text": " word", "start": 0.1, "end": 0.2, ...}
    let words: Vec<Word> = data["segments"]
        .as_array()
        .or_else(|| data["words"].as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|w| {
                    let word_text = w["text"]
                        .as_str()
                        .or_else(|| w["word"].as_str())?
                        .trim()
                        .to_string();
                    if word_text.is_empty() {
                        return None;
                    }
                    Some(Word {
                        word: word_text,
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

    let resp = gpu_auth(client
        .post(format!("{}/transcribe/stream", voxtral_url()))
        .multipart(form)
        .timeout(Duration::from_secs(300)))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        tracing::warn!("Voxtral streaming endpoint returned {status}: {body}, trying non-streaming");
        return call_voxtral_non_streaming(audio).await;
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

/// Non-streaming Voxtral fallback: POST /transcribe, returns {"text": "..."}
pub(super) async fn call_voxtral_non_streaming(audio: &[u8]) -> anyhow::Result<String> {
    let client = reqwest::Client::new();
    let part = reqwest::multipart::Part::bytes(audio.to_vec())
        .file_name("audio.wav")
        .mime_str("audio/wav")?;
    let form = reqwest::multipart::Form::new().part("audio", part);

    let resp = gpu_auth(client
        .post(format!("{}/transcribe", voxtral_url()))
        .multipart(form)
        .timeout(Duration::from_secs(300)))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("Voxtral non-streaming returned {status}: {body}");
    }

    let data: serde_json::Value = resp.json().await?;
    let text = data["text"]
        .as_str()
        .unwrap_or("")
        .to_string();

    if text.is_empty() {
        anyhow::bail!("Voxtral returned empty text");
    }

    Ok(text)
}
