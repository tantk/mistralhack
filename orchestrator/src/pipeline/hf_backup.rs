use std::env;
use std::io::Cursor;
use std::path::Path;

const REPO_ID: &str = "mistral-hackaton-2026/meetingmind-voiceprints";

fn hf_api_url(path: &str) -> String {
    format!("https://huggingface.co/api/datasets/{REPO_ID}/{path}")
}

fn resolve_url() -> String {
    format!("https://huggingface.co/datasets/{REPO_ID}/resolve/main/voiceprints.tar")
}

/// Restore voiceprints from HF dataset repo on startup.
///
/// Downloads `voiceprints.tar` and extracts into `store_path`.
/// 404 = first boot (no backup yet). Network errors are logged as warnings.
pub async fn restore_from_hf(store_path: &str) -> anyhow::Result<()> {
    let token = match env::var("HF_TOKEN") {
        Ok(t) if !t.is_empty() => t,
        _ => {
            tracing::info!("HF_TOKEN not set — skipping voiceprint restore");
            return Ok(());
        }
    };

    tracing::info!("Restoring voiceprints from HF dataset repo...");

    let client = reqwest::Client::new();
    let resp = client
        .get(resolve_url())
        .header("Authorization", format!("Bearer {token}"))
        .timeout(std::time::Duration::from_secs(60))
        .send()
        .await;

    let resp = match resp {
        Ok(r) => r,
        Err(e) => {
            tracing::warn!("HF restore request failed: {e}");
            return Ok(());
        }
    };

    if resp.status() == reqwest::StatusCode::NOT_FOUND {
        tracing::info!("No voiceprint backup found (first boot)");
        return Ok(());
    }

    if !resp.status().is_success() {
        tracing::warn!("HF restore returned status {}", resp.status());
        return Ok(());
    }

    let bytes = resp.bytes().await.map_err(|e| {
        tracing::warn!("Failed to read HF restore body: {e}");
        e
    })?;

    // Ensure store_path exists
    std::fs::create_dir_all(store_path)?;

    // Extract tar into store_path
    let cursor = Cursor::new(bytes);
    let mut archive = tar::Archive::new(cursor);
    archive.unpack(store_path)?;

    tracing::info!(path = %store_path, "Voiceprints restored from HF");
    Ok(())
}

/// Backup voiceprints to HF dataset repo.
///
/// Tars `store_path` (excluding LOCK files) and uploads as `voiceprints.tar`.
/// Errors are logged but never propagated.
pub async fn backup_to_hf(store_path: &str) {
    if let Err(e) = backup_inner(store_path).await {
        tracing::warn!("HF backup failed: {e}");
    }
}

async fn backup_inner(store_path: &str) -> anyhow::Result<()> {
    let token = env::var("HF_TOKEN")
        .map_err(|_| anyhow::anyhow!("HF_TOKEN not set — skipping backup"))?;

    if token.is_empty() {
        anyhow::bail!("HF_TOKEN is empty — skipping backup");
    }

    let store = Path::new(store_path);
    if !store.exists() {
        anyhow::bail!("Store path does not exist: {store_path}");
    }

    // Build tar in memory
    let tar_bytes = tokio::task::spawn_blocking({
        let store_path = store_path.to_string();
        move || build_tar(&store_path)
    })
    .await??;

    tracing::info!(bytes = tar_bytes.len(), "Uploading voiceprint backup to HF");

    // Upload via HF Hub commit API (single-file commit)
    let client = reqwest::Client::new();
    let resp = client
        .post(hf_api_url("commit/main"))
        .header("Authorization", format!("Bearer {token}"))
        .header("Content-Type", "application/json")
        .timeout(std::time::Duration::from_secs(60))
        .json(&serde_json::json!({
            "commit_message": "Update voiceprint backup",
            "operations": [{
                "operation": "upload",
                "path_in_repo": "voiceprints.tar",
                "encoding": "base64",
                "content": base64_encode(&tar_bytes),
            }]
        }))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("HF upload failed ({status}): {body}");
    }

    tracing::info!("Voiceprint backup uploaded to HF");
    Ok(())
}

fn build_tar(store_path: &str) -> anyhow::Result<Vec<u8>> {
    let buf = Vec::new();
    let mut ar = tar::Builder::new(buf);

    let store = Path::new(store_path);
    for entry in walkdir(store)? {
        let path = entry;
        let rel = path.strip_prefix(store)?;

        // Skip LOCK files
        if rel
            .to_str()
            .map(|s| s.contains("LOCK"))
            .unwrap_or(false)
        {
            continue;
        }

        if path.is_file() {
            ar.append_path_with_name(&path, rel)?;
        }
    }

    ar.into_inner().map_err(Into::into)
}

/// Simple recursive directory walk (avoids adding walkdir crate).
fn walkdir(dir: &Path) -> anyhow::Result<Vec<std::path::PathBuf>> {
    let mut files = Vec::new();
    if !dir.is_dir() {
        return Ok(files);
    }
    for entry in std::fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            files.extend(walkdir(&path)?);
        } else {
            files.push(path);
        }
    }
    Ok(files)
}

fn base64_encode(data: &[u8]) -> String {
    const CHARS: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut result = String::with_capacity((data.len() + 2) / 3 * 4);
    for chunk in data.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = if chunk.len() > 1 { chunk[1] as u32 } else { 0 };
        let b2 = if chunk.len() > 2 { chunk[2] as u32 } else { 0 };
        let triple = (b0 << 16) | (b1 << 8) | b2;
        result.push(CHARS[((triple >> 18) & 0x3F) as usize] as char);
        result.push(CHARS[((triple >> 12) & 0x3F) as usize] as char);
        if chunk.len() > 1 {
            result.push(CHARS[((triple >> 6) & 0x3F) as usize] as char);
        } else {
            result.push('=');
        }
        if chunk.len() > 2 {
            result.push(CHARS[(triple & 0x3F) as usize] as char);
        } else {
            result.push('=');
        }
    }
    result
}
