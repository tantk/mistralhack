"""Phase D: Tool definitions and dispatcher for the Mistral speaker-resolution agent.

Tools:
- resolve_speaker: Assign a known name to a diarization label
- request_reanalysis: Extract audio segment, get embedding, query voiceprints
- merge_speakers: Merge two diarization labels into one identity
- flag_ambiguity: Flag a speaker that can't be confidently resolved
"""

from __future__ import annotations

import io
import logging
from typing import Any

import httpx
import numpy as np
from pydub import AudioSegment

from app.config import DIARIZATION_URL
from app.pipeline.voiceprint_store import get_voiceprint_store

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

# ── Tool schemas for Mistral function calling ──────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "resolve_speaker",
            "description": (
                "Assign a resolved real name to a diarization speaker label. "
                "Call this when you are confident about a speaker's identity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "diarization_speaker": {
                        "type": "string",
                        "description": "The diarization label, e.g. SPEAKER_0",
                    },
                    "resolved_name": {
                        "type": "string",
                        "description": "The real name to assign",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Brief explanation of why this assignment is correct",
                    },
                },
                "required": ["diarization_speaker", "resolved_name", "reasoning"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_reanalysis",
            "description": (
                "Request acoustic re-analysis of a specific time range. "
                "Extracts audio, computes speaker embedding, and returns voiceprint matches. "
                "Use when acoustic evidence could help disambiguate a speaker."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_time": {
                        "type": "number",
                        "description": "Start of audio range in seconds",
                    },
                    "end_time": {
                        "type": "number",
                        "description": "End of audio range in seconds",
                    },
                },
                "required": ["start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_speakers",
            "description": (
                "Merge two diarization labels that refer to the same person. "
                "All segments from speaker_b will be reassigned to speaker_a."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "speaker_a": {
                        "type": "string",
                        "description": "The primary speaker label to keep",
                    },
                    "speaker_b": {
                        "type": "string",
                        "description": "The secondary speaker label to merge into speaker_a",
                    },
                },
                "required": ["speaker_a", "speaker_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flag_ambiguity",
            "description": (
                "Flag a speaker that cannot be confidently resolved. "
                "Use when evidence is conflicting or insufficient."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "diarization_speaker": {
                        "type": "string",
                        "description": "The diarization label that is ambiguous",
                    },
                    "candidates": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Possible names this speaker could be",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why the speaker cannot be resolved",
                    },
                },
                "required": ["diarization_speaker", "candidates", "reason"],
            },
        },
    },
]


# ── Tool execution ─────────────────────────────────────────────────────

class ToolContext:
    """Mutable state shared across tool calls within one agent run."""

    def __init__(self, audio_path: str | None = None):
        self.audio_path = audio_path
        self.resolutions: dict[str, dict] = {}  # speaker_label → {resolved_name, reasoning}
        self.merges: list[tuple[str, str]] = []  # [(speaker_a, speaker_b), ...]
        self.ambiguities: list[dict] = []  # [{diarization_speaker, candidates, reason}]


async def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    ctx: ToolContext,
) -> str:
    """Dispatch a tool call and return a string result for the agent."""
    log.info("Executing tool: %s(%s)", tool_name, args)

    if tool_name == "resolve_speaker":
        return _resolve_speaker(args, ctx)
    elif tool_name == "request_reanalysis":
        return await _request_reanalysis(args, ctx)
    elif tool_name == "merge_speakers":
        return _merge_speakers(args, ctx)
    elif tool_name == "flag_ambiguity":
        return _flag_ambiguity(args, ctx)
    else:
        return f"Unknown tool: {tool_name}"


def _resolve_speaker(args: dict, ctx: ToolContext) -> str:
    label = args["diarization_speaker"]
    name = args["resolved_name"]
    reasoning = args["reasoning"]
    ctx.resolutions[label] = {"resolved_name": name, "reasoning": reasoning}
    return f"Resolved {label} → {name}"


async def _request_reanalysis(args: dict, ctx: ToolContext) -> str:
    start = args["start_time"]
    end = args["end_time"]

    if not ctx.audio_path:
        return "No audio file available for reanalysis"

    try:
        audio = AudioSegment.from_file(ctx.audio_path, format="wav")
        segment = audio[int(start * 1000) : int(end * 1000)]

        if len(segment) < 500:  # less than 0.5s
            return "Audio segment too short for embedding extraction"

        buf = io.BytesIO()
        segment.set_frame_rate(16000).set_channels(1).set_sample_width(2).export(buf, format="wav")
        wav_bytes = buf.getvalue()
    except Exception as e:
        return f"Audio extraction failed: {e}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{DIARIZATION_URL}/embed",
                files={"audio": ("segment.wav", wav_bytes, "audio/wav")},
            )
            resp.raise_for_status()
        embedding = np.array(resp.json()["embedding"], dtype=np.float32)
    except Exception as e:
        return f"Embedding extraction failed: {e}"

    store = get_voiceprint_store()
    matches = store.identify(embedding, top_k=3)

    if not matches:
        return f"No voiceprint matches found for segment {start:.1f}s–{end:.1f}s"

    lines = [f"Voiceprint matches for {start:.1f}s–{end:.1f}s:"]
    for m in matches:
        lines.append(f"  {m['name']}: {m['similarity']:.3f}")
    return "\n".join(lines)


def _merge_speakers(args: dict, ctx: ToolContext) -> str:
    a, b = args["speaker_a"], args["speaker_b"]
    ctx.merges.append((a, b))
    return f"Merged {b} into {a}"


def _flag_ambiguity(args: dict, ctx: ToolContext) -> str:
    ctx.ambiguities.append({
        "diarization_speaker": args["diarization_speaker"],
        "candidates": args["candidates"],
        "reason": args["reason"],
    })
    return f"Flagged {args['diarization_speaker']} as ambiguous"
