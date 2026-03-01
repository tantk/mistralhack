#!/usr/bin/env python3
"""
Upload Voxtral model to org repo and reorganize HF repos.

Steps:
  1. Create mistral-hackaton-2026/voxtral_model — upload model files + model card
  2. Rename tantk/meetingmind-gpu → tantk/gpu_endpoint
  3. Upload updated code to tantk/gpu_endpoint
  4. Delete stale mistral-hackaton-2026/meetingmind-gpu

Usage:
    export HF_TOKEN=hf_...
    python upload_and_reorganize.py [--skip-model] [--skip-rename] [--skip-code] [--skip-delete]
"""

import argparse
import os
import sys

from huggingface_hub import HfApi


MODEL_REPO = "mistral-hackaton-2026/voxtral_model"
ENDPOINT_REPO_OLD = "tantk/meetingmind-gpu"
ENDPOINT_REPO_NEW = "tantk/gpu_endpoint"
STALE_REPO = "mistral-hackaton-2026/meetingmind-gpu"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), "voxtral.c", "voxtral-model")


def step_upload_model(api: HfApi):
    """Step 1: Create model repo and upload weights + model card."""
    print(f"\n=== Step 1: Upload model to {MODEL_REPO} ===")

    api.create_repo(MODEL_REPO, exist_ok=True)
    print(f"  Repo created/exists: {MODEL_REPO}")

    # Upload model card (MODEL_README.md -> README.md in the repo)
    model_card_path = os.path.join(SCRIPT_DIR, "MODEL_README.md")
    api.upload_file(
        path_or_fileobj=model_card_path,
        path_in_repo="README.md",
        repo_id=MODEL_REPO,
    )
    print("  Uploaded README.md (model card)")

    # Upload params.json (resolve symlink)
    params_path = os.path.realpath(os.path.join(MODEL_DIR, "params.json"))
    api.upload_file(
        path_or_fileobj=params_path,
        path_in_repo="params.json",
        repo_id=MODEL_REPO,
    )
    print("  Uploaded params.json")

    # Upload tekken.json (resolve symlink)
    tekken_path = os.path.realpath(os.path.join(MODEL_DIR, "tekken.json"))
    api.upload_file(
        path_or_fileobj=tekken_path,
        path_in_repo="tekken.json",
        repo_id=MODEL_REPO,
    )
    print("  Uploaded tekken.json")

    # Upload consolidated.safetensors (8.3GB — use upload_file with large file support)
    safetensors_path = os.path.join(MODEL_DIR, "consolidated.safetensors")
    print(f"  Uploading consolidated.safetensors ({os.path.getsize(safetensors_path) / 1e9:.1f} GB)...")
    api.upload_file(
        path_or_fileobj=safetensors_path,
        path_in_repo="consolidated.safetensors",
        repo_id=MODEL_REPO,
    )
    print("  Uploaded consolidated.safetensors")

    print(f"  Done: https://huggingface.co/{MODEL_REPO}")


def step_rename_endpoint(api: HfApi):
    """Step 2: Rename tantk/meetingmind-gpu → tantk/gpu_endpoint."""
    print(f"\n=== Step 2: Rename {ENDPOINT_REPO_OLD} → {ENDPOINT_REPO_NEW} ===")

    try:
        api.move_repo(from_id=ENDPOINT_REPO_OLD, to_id=ENDPOINT_REPO_NEW)
        print(f"  Renamed: {ENDPOINT_REPO_OLD} → {ENDPOINT_REPO_NEW}")
    except Exception as e:
        if "already exists" in str(e).lower() or "404" in str(e):
            print(f"  Skipped (may already be renamed or missing): {e}")
        else:
            raise

    print(f"  Done: https://huggingface.co/{ENDPOINT_REPO_NEW}")


def step_upload_code(api: HfApi):
    """Step 3: Upload updated code files to endpoint repo."""
    print(f"\n=== Step 3: Upload code to {ENDPOINT_REPO_NEW} ===")

    code_files = ["app.py", "voxtral_inference.py", "requirements.txt", "Dockerfile", "README.md"]

    for fname in code_files:
        fpath = os.path.join(SCRIPT_DIR, fname)
        if not os.path.exists(fpath):
            print(f"  WARNING: {fname} not found, skipping")
            continue
        api.upload_file(
            path_or_fileobj=fpath,
            path_in_repo=fname,
            repo_id=ENDPOINT_REPO_NEW,
        )
        print(f"  Uploaded {fname}")

    print(f"  Done: https://huggingface.co/{ENDPOINT_REPO_NEW}")


def step_delete_stale(api: HfApi):
    """Step 4: Delete stale org repo."""
    print(f"\n=== Step 4: Delete stale repo {STALE_REPO} ===")

    try:
        api.delete_repo(STALE_REPO)
        print(f"  Deleted: {STALE_REPO}")
    except Exception as e:
        if "404" in str(e):
            print(f"  Already gone: {STALE_REPO}")
        else:
            raise


def main():
    parser = argparse.ArgumentParser(description="Upload model and reorganize HF repos")
    parser.add_argument("--skip-model", action="store_true", help="Skip model upload")
    parser.add_argument("--skip-rename", action="store_true", help="Skip repo rename")
    parser.add_argument("--skip-code", action="store_true", help="Skip code upload")
    parser.add_argument("--skip-delete", action="store_true", help="Skip stale repo deletion")
    args = parser.parse_args()

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("ERROR: HF_TOKEN environment variable is required")
        sys.exit(1)

    api = HfApi(token=hf_token)

    if not args.skip_model:
        step_upload_model(api)
    if not args.skip_rename:
        step_rename_endpoint(api)
    if not args.skip_code:
        step_upload_code(api)
    if not args.skip_delete:
        step_delete_stale(api)

    print("\n=== All done! ===")
    print(f"  Model: https://huggingface.co/{MODEL_REPO}")
    print(f"  Endpoint: https://huggingface.co/{ENDPOINT_REPO_NEW}")


if __name__ == "__main__":
    main()
