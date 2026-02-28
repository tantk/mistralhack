#!/usr/bin/env bash
set -euo pipefail

# Deploy to Hugging Face Spaces
# Pushes the current master branch to the HF Space remote

HF_REMOTE="hf"
HF_URL="https://huggingface.co/spaces/mistral-hackaton-2026/meetingmind"

# Add remote if it doesn't exist
if ! git remote get-url "$HF_REMOTE" &>/dev/null; then
  echo "Adding remote '$HF_REMOTE' → $HF_URL"
  git remote add "$HF_REMOTE" "$HF_URL"
fi

echo "Pushing master → hf:main …"
git push "$HF_REMOTE" master:main "$@"
echo "Done — deployed to $HF_URL"
