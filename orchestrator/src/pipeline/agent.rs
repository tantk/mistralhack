use std::collections::HashMap;
use std::time::Duration;
use tokio::sync::broadcast;

use super::types::*;
use super::voiceprint::SharedVoiceprintStore;

fn build_tool_schemas() -> serde_json::Value {
    serde_json::json!([
        {
            "type": "function",
            "function": {
                "name": "resolve_speaker",
                "description": "Assign a real name to a diarization speaker label based on evidence.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "diarization_speaker": { "type": "string", "description": "The speaker label (e.g., SPEAKER_00)" },
                        "resolved_name": { "type": "string", "description": "The resolved real name" },
                        "confidence": { "type": "number", "description": "Confidence 0-1" },
                        "evidence": { "type": "string", "description": "Evidence for the resolution" }
                    },
                    "required": ["diarization_speaker", "resolved_name", "confidence", "evidence"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "request_reanalysis",
                "description": "Request voiceprint identification for an audio segment to help identify a speaker.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_time": { "type": "number", "description": "Start time in seconds" },
                        "end_time": { "type": "number", "description": "End time in seconds" }
                    },
                    "required": ["start_time", "end_time"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "merge_speakers",
                "description": "Merge two diarization speaker labels that are the same person.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "speaker_a": { "type": "string", "description": "First speaker label" },
                        "speaker_b": { "type": "string", "description": "Second speaker label to merge into first" },
                        "evidence": { "type": "string", "description": "Evidence for the merge" }
                    },
                    "required": ["speaker_a", "speaker_b", "evidence"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "flag_ambiguity",
                "description": "Flag a speaker label as ambiguous when identity cannot be determined with confidence.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "diarization_speaker": { "type": "string", "description": "The ambiguous speaker label" },
                        "candidates": { "type": "array", "items": { "type": "string" }, "description": "Possible identity candidates" },
                        "reason": { "type": "string", "description": "Reason for ambiguity" }
                    },
                    "required": ["diarization_speaker", "candidates", "reason"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "extract_action_items",
                "description": "Extract structured action items found in the transcript.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "owner": { "type": "string", "description": "Person responsible" },
                                    "task": { "type": "string", "description": "Task description" },
                                    "deadline_mentioned": { "type": "string", "description": "Deadline if mentioned, or null" },
                                    "verbatim_quote": { "type": "string", "description": "Exact quote from transcript" }
                                },
                                "required": ["owner", "task"]
                            },
                            "description": "List of action items"
                        }
                    },
                    "required": ["items"]
                }
            }
        }
    ])
}

fn build_agent_system_prompt() -> String {
    r#"You are a meeting analysis agent. Your job is to resolve diarization speaker labels (SPEAKER_00, SPEAKER_01, etc.) to real names, and extract action items.

## Evidence Thresholds
- Acoustic evidence (voiceprint similarity):
  - >0.85: Strong match — use as primary evidence
  - 0.70-0.85: Suggestive — combine with semantic evidence
  - <0.70: Unreliable — do not use alone

- Semantic evidence patterns:
  - Self-introduction: "Hi, I'm [Name]" or "This is [Name]"
  - Direct address: "[Name], what do you think?"
  - Role references: "As the PM..." → correlate with known team
  - Calendar context: meeting organizer, attendee list

## Instructions
1. Analyze the transcript segments for speaker identity clues
2. Use resolve_speaker when you have sufficient evidence (confidence > 0.7)
3. Use request_reanalysis to get voiceprint matches for uncertain speakers
4. Use merge_speakers if diarization split one person into multiple labels
5. Use flag_ambiguity when you cannot confidently resolve a speaker
6. Use extract_action_items to capture commitments, tasks, and follow-ups
7. Stop when all speakers are resolved or flagged, and all action items are extracted"#.to_string()
}

fn build_user_message(
    segments: &[Segment],
    acoustic_matches: &[AcousticMatch],
    attendees: &[String],
    gpu_available: bool,
) -> String {
    let mut parts: Vec<String> = Vec::new();

    if !gpu_available {
        parts.push("## Note\nGPU service is unavailable. The `request_reanalysis` tool will not work. Rely on semantic evidence only (self-introductions, direct address, role references, attendee list).".to_string());
    }

    // Known attendees
    if !attendees.is_empty() {
        parts.push(format!("## Known attendees\n{}", attendees.join(", ")));
    }

    // Acoustic voiceprint matches
    if !acoustic_matches.is_empty() {
        parts.push("## Acoustic voiceprint matches".to_string());
        for m in acoustic_matches {
            let status = if m.confirmed { "CONFIRMED" } else { "tentative" };
            parts.push(format!(
                "- {} → {} (similarity: {:.3}, {})",
                m.diarization_speaker, m.matched_name, m.cosine_similarity, status
            ));
        }
    }

    // Transcript segments
    parts.push("## Transcript segments".to_string());
    for s in segments {
        let overlap_marker = if s.is_overlap { " [OVERLAP]" } else { "" };
        let conf = if s.confidence < 0.8 {
            format!(" [conf={:.2}]", s.confidence)
        } else {
            String::new()
        };
        parts.push(format!(
            "[{:.1}s-{:.1}s] {}{}{}: {}",
            s.start, s.end, s.speaker, conf, overlap_marker, s.text
        ));
    }

    // Unique speaker labels summary
    let mut labels: Vec<String> = segments
        .iter()
        .map(|s| s.speaker.clone())
        .collect::<std::collections::HashSet<_>>()
        .into_iter()
        .collect();
    labels.sort();
    if !labels.is_empty() {
        parts.push(format!(
            "\n## Speaker labels to resolve: {}",
            labels.join(", ")
        ));
    }

    parts.join("\n")
}

async fn execute_tool(
    tool_name: &str,
    args: &serde_json::Value,
    ctx: &mut ToolContext,
    tx: &broadcast::Sender<PipelineEvent>,
) -> String {
    match tool_name {
        "resolve_speaker" => {
            let speaker = args["diarization_speaker"].as_str().unwrap_or("");
            let name = args["resolved_name"].as_str().unwrap_or("");
            let confidence = args["confidence"].as_f64().unwrap_or(0.0);
            let evidence = args["evidence"].as_str().unwrap_or("");

            ctx.resolutions.insert(
                speaker.to_string(),
                SpeakerResolution {
                    diarization_speaker: speaker.to_string(),
                    resolved_name: name.to_string(),
                    confidence,
                    evidence: evidence.to_string(),
                },
            );

            let _ = tx.send(PipelineEvent::SpeakerResolved {
                label: speaker.to_string(),
                name: name.to_string(),
                confidence,
                method: "agent".to_string(),
            });

            format!("Resolved {speaker} → {name} (confidence: {confidence:.2})")
        }

        "request_reanalysis" => {
            if !ctx.gpu_available {
                return "Voiceprint identification unavailable: GPU service is down. Use semantic evidence (self-introductions, direct address, role references) to resolve speakers.".to_string();
            }

            let start = args["start_time"].as_f64().unwrap_or(0.0);
            let end = args["end_time"].as_f64().unwrap_or(0.0);

            match call_embed_and_identify(
                &ctx.audio_bytes,
                start,
                end,
                &ctx.diarization_url,
                &ctx.voiceprint_store,
            )
            .await
            {
                Ok(matches) => {
                    let result = serde_json::to_string(&matches).unwrap_or_else(|_| "[]".into());
                    format!("Voiceprint matches for {start:.1}s-{end:.1}s: {result}")
                }
                Err(e) => format!("Voiceprint identification failed: {e}"),
            }
        }

        "merge_speakers" => {
            let a = args["speaker_a"].as_str().unwrap_or("");
            let b = args["speaker_b"].as_str().unwrap_or("");
            let evidence = args["evidence"].as_str().unwrap_or("");

            ctx.merges.push((a.to_string(), b.to_string()));
            format!("Merged {b} into {a} (evidence: {evidence})")
        }

        "flag_ambiguity" => {
            let speaker = args["diarization_speaker"].as_str().unwrap_or("");
            let candidates: Vec<String> = args["candidates"]
                .as_array()
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(|s| s.to_string()))
                        .collect()
                })
                .unwrap_or_default();
            let reason = args["reason"].as_str().unwrap_or("");

            ctx.ambiguities.push(AgentAmbiguity {
                diarization_speaker: speaker.to_string(),
                candidates: candidates.clone(),
                reason: reason.to_string(),
            });

            format!(
                "Flagged {speaker} as ambiguous: candidates={}, reason={reason}",
                candidates.join(", ")
            )
        }

        "extract_action_items" => {
            let items: Vec<ActionItemRich> = args["items"]
                .as_array()
                .map(|arr| {
                    arr.iter()
                        .filter_map(|item| {
                            Some(ActionItemRich {
                                owner: item["owner"].as_str()?.to_string(),
                                task: item["task"].as_str()?.to_string(),
                                deadline_mentioned: item["deadline_mentioned"]
                                    .as_str()
                                    .map(|s| s.to_string()),
                                verbatim_quote: item["verbatim_quote"]
                                    .as_str()
                                    .map(|s| s.to_string()),
                            })
                        })
                        .collect()
                })
                .unwrap_or_default();

            let count = items.len();
            ctx.action_items.extend(items);
            format!("Extracted {count} action items")
        }

        _ => format!("Unknown tool: {tool_name}"),
    }
}

/// Call GPU /embed to extract embedding, then look up in local Zvec store.
async fn call_embed_and_identify(
    audio: &[u8],
    start: f64,
    end: f64,
    diarization_url: &str,
    voiceprint_store: &SharedVoiceprintStore,
) -> anyhow::Result<serde_json::Value> {
    let client = reqwest::Client::new();
    let part = reqwest::multipart::Part::bytes(audio.to_vec())
        .file_name("audio.wav")
        .mime_str("audio/wav")?;
    let form = reqwest::multipart::Form::new()
        .part("audio", part)
        .text("start_time", start.to_string())
        .text("end_time", end.to_string());

    let resp = gpu_auth(client
        .post(format!("{}/embed", diarization_url))
        .multipart(form)
        .timeout(Duration::from_secs(30)))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("GPU /embed returned {status}: {body}");
    }

    let data: serde_json::Value = resp.json().await?;
    let embedding: Vec<f32> = data["embedding"]
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("No embedding in GPU response"))?
        .iter()
        .filter_map(|v| v.as_f64().map(|f| f as f32))
        .collect();

    let matches = voiceprint_store.identify(&embedding, 3)?;
    let matches_json: Vec<serde_json::Value> = matches
        .iter()
        .map(|m| {
            serde_json::json!({
                "name": m.name,
                "id": m.id,
                "similarity": m.similarity,
            })
        })
        .collect();

    Ok(serde_json::Value::Array(matches_json))
}

pub async fn run_agent(
    tx: &broadcast::Sender<PipelineEvent>,
    segments: &[Segment],
    audio_bytes: &[u8],
    acoustic_matches: &[AcousticMatch],
    attendees: &[String],
    voiceprint_store: &SharedVoiceprintStore,
    gpu_available: bool,
) -> anyhow::Result<(Vec<Segment>, Vec<ActionItemRich>, HashMap<String, String>)> {
    let api_key = mistral_api_key();
    if api_key.is_empty() {
        anyhow::bail!("MISTRAL_API_KEY missing");
    }

    let mut ctx = ToolContext {
        audio_bytes: audio_bytes.to_vec(),
        resolutions: HashMap::new(),
        merges: Vec::new(),
        ambiguities: Vec::new(),
        action_items: Vec::new(),
        diarization_url: diarization_url(),
        voiceprint_store: voiceprint_store.clone(),
        gpu_available,
    };

    let user_message = build_user_message(segments, acoustic_matches, attendees, gpu_available);

    let tools = build_tool_schemas();
    let system_prompt = build_agent_system_prompt();

    let mut messages = vec![
        serde_json::json!({"role": "system", "content": system_prompt}),
        serde_json::json!({"role": "user", "content": user_message}),
    ];

    let client = reqwest::Client::new();
    let max_iterations = 5;

    for iteration in 0..max_iterations {
        tracing::info!(iteration, "Agent iteration");

        let body = serde_json::json!({
            "model": "mistral-large-latest",
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        });

        let resp = client
            .post("https://api.mistral.ai/v1/chat/completions")
            .header("Authorization", format!("Bearer {api_key}"))
            .header("Content-Type", "application/json")
            .json(&body)
            .timeout(Duration::from_secs(30))
            .send()
            .await;

        let resp = match resp {
            Ok(r) => r,
            Err(e) => {
                tracing::warn!("Agent API call failed at iteration {iteration}: {e}");
                break;
            }
        };

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            tracing::warn!("Agent API returned {status}: {body}");
            break;
        }

        let data: serde_json::Value = resp.json().await?;
        let message = &data["choices"][0]["message"];

        let tool_calls = message["tool_calls"].as_array();

        if tool_calls.is_none() || tool_calls.unwrap().is_empty() {
            tracing::info!(iteration, "Agent finished (no tool calls)");
            break;
        }

        let tool_calls = tool_calls.unwrap();

        messages.push(message.clone());

        for tc in tool_calls {
            let tool_name = tc["function"]["name"].as_str().unwrap_or("");
            let args_str = tc["function"]["arguments"].as_str().unwrap_or("{}");
            let tool_call_id = tc["id"].as_str().unwrap_or("");
            let args: serde_json::Value =
                serde_json::from_str(args_str).unwrap_or(serde_json::json!({}));

            let _ = tx.send(PipelineEvent::ToolCall {
                tool: tool_name.to_string(),
                args: args.clone(),
            });

            let result = execute_tool(tool_name, &args, &mut ctx, tx).await;

            let _ = tx.send(PipelineEvent::ToolResult {
                tool: tool_name.to_string(),
                result: result.clone(),
            });

            messages.push(serde_json::json!({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": result,
            }));
        }
    }

    let resolved_segments = apply_resolutions(segments, &ctx);
    let resolution_map = build_resolution_map(&ctx);

    Ok((resolved_segments, ctx.action_items, resolution_map))
}

fn build_resolution_map(ctx: &ToolContext) -> HashMap<String, String> {
    let mut merge_map: HashMap<String, String> = HashMap::new();
    for (a, b) in &ctx.merges {
        merge_map.insert(b.clone(), a.clone());
    }

    // Keep behavior aligned with apply_resolutions: propagate resolutions through merges.
    let mut effective_resolutions = ctx.resolutions.clone();
    for (a, b) in &ctx.merges {
        if effective_resolutions.contains_key(b) && !effective_resolutions.contains_key(a) {
            let mut res = effective_resolutions[b].clone();
            res.diarization_speaker = a.clone();
            res.evidence = format!("Propagated from merged {}: {}", b, res.evidence);
            effective_resolutions.insert(a.clone(), res);
        } else if effective_resolutions.contains_key(a) && !effective_resolutions.contains_key(b) {
            let mut res = effective_resolutions[a].clone();
            res.diarization_speaker = b.clone();
            res.evidence = format!("Propagated from merge target {}: {}", a, res.evidence);
            effective_resolutions.insert(b.clone(), res);
        }
    }

    let mut map = HashMap::new();
    for (label, resolution) in effective_resolutions {
        // If this label was merged into another one, record the final target label.
        let canonical = merge_map.get(&label).cloned().unwrap_or(label);
        map.insert(canonical, resolution.resolved_name);
    }
    map
}

fn apply_resolutions(segments: &[Segment], ctx: &ToolContext) -> Vec<Segment> {
    let mut merge_map: HashMap<String, String> = HashMap::new();
    for (a, b) in &ctx.merges {
        merge_map.insert(b.clone(), a.clone());
    }

    // Propagate resolutions through merges:
    // If B is merged into A, and B has a resolution but A doesn't, copy B's resolution to A.
    // If A is merged into B (reverse), same logic applies.
    let mut effective_resolutions = ctx.resolutions.clone();
    for (a, b) in &ctx.merges {
        // b merges into a
        if effective_resolutions.contains_key(b) && !effective_resolutions.contains_key(a) {
            let mut res = effective_resolutions[b].clone();
            res.diarization_speaker = a.clone();
            res.evidence = format!("Propagated from merged {}: {}", b, res.evidence);
            effective_resolutions.insert(a.clone(), res);
        } else if effective_resolutions.contains_key(a) && !effective_resolutions.contains_key(b) {
            let mut res = effective_resolutions[a].clone();
            res.diarization_speaker = b.clone();
            res.evidence = format!("Propagated from merge target {}: {}", a, res.evidence);
            effective_resolutions.insert(b.clone(), res);
        }
    }

    segments
        .iter()
        .map(|seg| {
            let mut speaker = seg.speaker.clone();

            if let Some(merged_into) = merge_map.get(&speaker) {
                speaker = merged_into.clone();
            }

            if let Some(resolution) = effective_resolutions.get(&speaker) {
                speaker = resolution.resolved_name.clone();
            }

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
