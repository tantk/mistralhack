use std::convert::Infallible;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use axum::extract::{Multipart, State};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::routing::{get, post};
use axum::{Json, Router};
use clap::{Parser, Subcommand};
use futures::{Stream, StreamExt};
use mistralrs::{
    AudioInput, AutoDeviceMapParams, ChatCompletionChunkResponse, ChunkChoice, Delta,
    DeviceMapSetting, IsqType, Response, TextMessageRole, VisionModelBuilder, VisionMessages,
};
use serde::Serialize;
use tokio_stream::wrappers::ReceiverStream;

#[derive(Parser)]
#[command(name = "mistralhack", about = "Voxtral speech-to-text via mistral.rs")]
struct Args {
    /// Local HF cache directory containing model files
    #[arg(short, long)]
    model_path: Option<PathBuf>,

    /// Path to tokenizer file (e.g. tekken.json)
    #[arg(long)]
    tokenizer: Option<PathBuf>,

    /// HuggingFace model ID
    #[arg(long, default_value = "mistralai/Voxtral-Mini-4B-Realtime-2602")]
    model_id: String,

    /// Use GPU (CUDA) for inference
    #[arg(long)]
    gpu: bool,

    /// Quantization level: q4k, q5k, q8k, or none
    #[arg(long, default_value = "q4k")]
    quant: String,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Transcribe a single WAV file
    Transcribe {
        /// Path to a WAV file
        #[arg(short, long)]
        audio: PathBuf,

        /// Custom transcription prompt
        #[arg(long, default_value = "Transcribe this audio.")]
        prompt: String,
    },
    /// Start an HTTP server
    Serve {
        /// Host to bind to
        #[arg(long, default_value = "0.0.0.0")]
        host: String,

        /// Port to listen on
        #[arg(long, default_value_t = 8080)]
        port: u16,
    },
}

#[derive(Serialize)]
struct TranscribeResponse {
    text: String,
}

#[derive(Serialize)]
struct ErrorResponse {
    error: String,
}

#[derive(Serialize)]
struct HealthResponse {
    status: String,
    model: String,
}

struct AppState {
    model: mistralrs::Model,
    model_id: String,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    println!("Loading model...");
    let model = build_model(&args).await?;
    println!("Model ready.");

    match args.command {
        Command::Transcribe { audio, prompt } => {
            let audio_bytes = std::fs::read(&audio)
                .with_context(|| format!("Failed to read audio file: {}", audio.display()))?;
            println!("Loaded {} bytes from {:?}", audio_bytes.len(), audio);
            let text = transcribe_bytes(&model, &audio_bytes, &prompt).await?;
            println!("\n--- Transcription ---\n{text}");
        }
        Command::Serve { host, port } => {
            let state = Arc::new(AppState {
                model,
                model_id: args.model_id.clone(),
            });

            let app = Router::new()
                .route("/health", get(health))
                .route("/transcribe", post(transcribe_handler))
                .route("/transcribe/stream", post(transcribe_stream_handler))
                .with_state(state);

            let addr = format!("{host}:{port}");
            println!("Server listening on http://{addr}");
            println!();
            println!("Usage:");
            println!("  curl -X POST http://{addr}/transcribe -F audio=@file.wav");
            println!("  curl -X POST http://{addr}/transcribe -F audio=@file.wav -F prompt=\"Transcribe this audio.\"");

            let listener = tokio::net::TcpListener::bind(&addr).await?;
            axum::serve(listener, app).await?;
        }
    }

    Ok(())
}

async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".into(),
        model: state.model_id.clone(),
    })
}

async fn transcribe_handler(
    State(state): State<Arc<AppState>>,
    mut multipart: Multipart,
) -> Result<Json<TranscribeResponse>, (axum::http::StatusCode, Json<ErrorResponse>)> {
    let mut audio_bytes: Option<Vec<u8>> = None;
    let mut prompt = "Transcribe this audio.".to_string();

    while let Ok(Some(field)) = multipart.next_field().await {
        let name = field.name().unwrap_or("").to_string();
        match name.as_str() {
            "audio" => {
                audio_bytes = Some(field.bytes().await.map_err(|e| bad_request(e.to_string()))?.to_vec());
            }
            "prompt" => {
                prompt = field.text().await.map_err(|e| bad_request(e.to_string()))?;
            }
            _ => {}
        }
    }

    let audio_bytes = audio_bytes.ok_or_else(|| bad_request("Missing 'audio' field".into()))?;

    let text = transcribe_bytes(&state.model, &audio_bytes, &prompt)
        .await
        .map_err(|e| {
            (
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                Json(ErrorResponse {
                    error: e.to_string(),
                }),
            )
        })?;

    Ok(Json(TranscribeResponse { text }))
}

fn bad_request(msg: String) -> (axum::http::StatusCode, Json<ErrorResponse>) {
    (
        axum::http::StatusCode::BAD_REQUEST,
        Json(ErrorResponse { error: msg }),
    )
}

async fn transcribe_stream_handler(
    State(state): State<Arc<AppState>>,
    mut multipart: Multipart,
) -> Result<Sse<impl Stream<Item = Result<Event, Infallible>>>, (axum::http::StatusCode, Json<ErrorResponse>)>
{
    let mut audio_bytes: Option<Vec<u8>> = None;
    let mut prompt = "Transcribe this audio.".to_string();

    while let Ok(Some(field)) = multipart.next_field().await {
        let name = field.name().unwrap_or("").to_string();
        match name.as_str() {
            "audio" => {
                audio_bytes =
                    Some(field.bytes().await.map_err(|e| bad_request(e.to_string()))?.to_vec());
            }
            "prompt" => {
                prompt = field.text().await.map_err(|e| bad_request(e.to_string()))?;
            }
            _ => {}
        }
    }

    let audio_bytes = audio_bytes.ok_or_else(|| bad_request("Missing 'audio' field".into()))?;

    let (tx, rx) = tokio::sync::mpsc::channel::<Event>(32);

    tokio::spawn(async move {
        let audio = match AudioInput::from_bytes(&audio_bytes) {
            Ok(a) => a,
            Err(e) => {
                let _ = tx
                    .send(
                        Event::default()
                            .event("error")
                            .data(serde_json::json!({"error": e.to_string()}).to_string()),
                    )
                    .await;
                return;
            }
        };

        let messages = VisionMessages::new().add_multimodal_message(
            TextMessageRole::User,
            &prompt,
            vec![],
            vec![audio],
        );

        let mut stream = match state.model.stream_chat_request(messages).await {
            Ok(s) => s,
            Err(e) => {
                let _ = tx
                    .send(
                        Event::default()
                            .event("error")
                            .data(serde_json::json!({"error": e.to_string()}).to_string()),
                    )
                    .await;
                return;
            }
        };

        let mut full_text = String::new();

        while let Some(chunk) = stream.next().await {
            match chunk {
                Response::Chunk(ChatCompletionChunkResponse { choices, .. }) => {
                    if let Some(ChunkChoice {
                        delta: Delta {
                            content: Some(text),
                            ..
                        },
                        ..
                    }) = choices.first()
                    {
                        let clean = text
                            .replace("[STREAMING_PAD]", "")
                            .replace("[STREAMING_WORD]", "");
                        if !clean.is_empty() {
                            full_text.push_str(&clean);
                            let _ = tx
                                .send(
                                    Event::default()
                                        .event("token")
                                        .data(
                                            serde_json::json!({"token": clean}).to_string(),
                                        ),
                                )
                                .await;
                        }
                    }
                }
                Response::Done(_) => break,
                _ => {}
            }
        }

        let final_text = full_text.trim().to_string();
        let _ = tx
            .send(
                Event::default()
                    .event("done")
                    .data(serde_json::json!({"text": final_text}).to_string()),
            )
            .await;
    });

    let stream = ReceiverStream::new(rx).map(|event| Ok::<_, Infallible>(event));

    Ok(Sse::new(stream).keep_alive(KeepAlive::new().interval(Duration::from_secs(15))))
}

// ---- core inference ----

async fn build_model(args: &Args) -> Result<mistralrs::Model> {
    let isq = match args.quant.to_lowercase().as_str() {
        "q4k" => Some(IsqType::Q4K),
        "q5k" => Some(IsqType::Q5K),
        "q8k" => Some(IsqType::Q8K),
        "none" => None,
        other => anyhow::bail!("Unknown quantization: {other}. Use q4k, q5k, q8k, or none"),
    };

    let model_id = if let Some(ref path) = args.model_path {
        anyhow::ensure!(path.exists(), "Model path does not exist: {}", path.display());
        path.to_string_lossy().to_string()
    } else {
        args.model_id.clone()
    };

    let mut builder = VisionModelBuilder::new(&model_id).with_logging();

    if let Some(ref tok) = args.tokenizer {
        anyhow::ensure!(tok.exists(), "Tokenizer file does not exist: {}", tok.display());
        builder = builder.with_tokenizer_json(tok.to_string_lossy());
    }

    if let Some(isq) = isq {
        builder = builder.with_isq(isq);
    }

    if args.gpu {
        builder = builder.with_device_mapping(DeviceMapSetting::Auto(
            AutoDeviceMapParams::default_vision(),
        ));
    }

    let model = builder.build().await.context("Failed to load Voxtral model")?;
    Ok(model)
}

async fn transcribe_bytes(model: &mistralrs::Model, wav_bytes: &[u8], prompt: &str) -> Result<String> {
    let audio = AudioInput::from_bytes(wav_bytes)
        .map_err(|e| anyhow::anyhow!("Failed to decode audio: {e}"))?;

    let messages = VisionMessages::new().add_multimodal_message(
        TextMessageRole::User,
        prompt,
        vec![],
        vec![audio],
    );

    let response = model
        .send_chat_request(messages)
        .await
        .map_err(|e| anyhow::anyhow!("{e}"))?;

    eprintln!("Response: {:?}", serde_json::to_string_pretty(&response));

    let text = response
        .choices
        .first()
        .and_then(|c| c.message.content.as_ref())
        .map(|c: &String| {
            c.replace("[STREAMING_PAD]", "")
                .replace("[STREAMING_WORD]", "")
                .trim()
                .to_string()
        })
        .unwrap_or_else(|| "[No transcription]".to_string());

    Ok(text)
}

