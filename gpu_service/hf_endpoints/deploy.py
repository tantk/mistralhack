#!/usr/bin/env python3
"""
Build, push, and deploy the meetingmind-gpu Docker image to HF Inference Endpoints.

Usage:
    export HF_TOKEN=hf_...
    python deploy.py
"""

import os
import subprocess
import sys

from huggingface_hub import HfApi

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DOCKER_IMAGE = "tantk/meetingmind-gpu:latest"
REPO_ID = "mistral-hackaton-2026/meetingmind-gpu"
ENDPOINT_NAME = "meetingmind-gpu"
NAMESPACE = "mistral-hackaton-2026"


def run(cmd: list[str], **kwargs) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def main() -> None:
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("ERROR: HF_TOKEN environment variable is required")
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # ── Step 1: Build & push Docker image ──
    print("\n=== Building Docker image ===")
    run(["docker", "build", "-t", DOCKER_IMAGE, "--platform", "linux/amd64", "."], cwd=script_dir)

    print("\n=== Pushing Docker image ===")
    run(["docker", "push", DOCKER_IMAGE])

    # ── Step 2: Create model repo & upload files ──
    print("\n=== Creating/updating HF model repo ===")
    api = HfApi(token=hf_token)
    api.create_repo(REPO_ID, exist_ok=True)
    api.upload_folder(
        folder_path=script_dir,
        repo_id=REPO_ID,
        allow_patterns=["app.py", "Dockerfile", "requirements.txt", "README.md"],
    )
    print(f"Repo updated: https://huggingface.co/{REPO_ID}")

    # ── Step 3: Create inference endpoint ──
    print("\n=== Creating inference endpoint ===")
    endpoint = api.create_inference_endpoint(
        name=ENDPOINT_NAME,
        namespace=NAMESPACE,
        repository=REPO_ID,
        framework="custom",
        task="custom",
        accelerator="gpu",
        vendor="aws",
        region="us-east-1",
        type="protected",
        instance_size="x1",
        instance_type="nvidia-t4",
        custom_image={
            "health_route": "/health",
            "url": DOCKER_IMAGE,
            "port": 80,
        },
        secrets={"HF_TOKEN": hf_token},
        min_replica=0,
        max_replica=1,
        scale_to_zero_timeout=15,
    )

    # ── Step 4: Wait for endpoint to be ready ──
    print("\n=== Waiting for endpoint (up to 10 min) ===")
    endpoint.wait(timeout=600)
    print(f"\nEndpoint ready: {endpoint.url}")
    print(f"Test with:")
    print(f"  curl -H 'Authorization: Bearer $HF_TOKEN' {endpoint.url}/health")


if __name__ == "__main__":
    main()
