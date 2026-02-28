"""Phase E: Structured meeting minutes generation via Mistral JSON mode."""

from __future__ import annotations

import json
import logging

from mistralai import Mistral

from app.config import MISTRAL_API_KEY
from app.pipeline.models import AlignedSegment, MeetingMinutes

log = logging.getLogger(__name__)

MODEL = "mistral-large-latest"

SYSTEM_PROMPT = """\
You are a meeting minutes generator. Given a transcript with speaker names and timestamps, \
produce structured meeting minutes in JSON format.

Output exactly this JSON structure:
{
  "meeting_metadata": {
    "title": "string — inferred meeting topic",
    "duration_seconds": number,
    "num_speakers": number,
    "summary": "string — 2-3 sentence summary"
  },
  "speakers": [
    {
      "name": "string",
      "speaking_time_seconds": number,
      "segment_count": number
    }
  ],
  "transcript": [
    {
      "speaker": "string",
      "start_time": number,
      "end_time": number,
      "text": "string"
    }
  ],
  "action_items": [
    {
      "description": "string",
      "assignee": "string or null"
    }
  ],
  "decisions": ["string"],
  "meeting_dynamics": {
    "most_active_speaker": "string",
    "topics_discussed": ["string"],
    "tone": "string — e.g. collaborative, contentious, informational"
  }
}

Be concise. Extract real action items and decisions from the conversation content. \
If there are no action items or decisions, return empty lists.\
"""


async def generate_minutes(
    segments: list[AlignedSegment],
    meeting_title: str = "",
) -> MeetingMinutes:
    """Generate structured meeting minutes from resolved transcript segments."""
    if not MISTRAL_API_KEY:
        log.warning("MISTRAL_API_KEY not set — generating basic minutes")
        return _basic_minutes(segments, meeting_title)

    # Build transcript text for the model
    lines = []
    for seg in segments:
        speaker = seg.resolved_speaker or seg.diarization_speaker or "Unknown"
        lines.append(f"[{seg.start_time:.1f}–{seg.end_time:.1f}] {speaker}: {seg.text}")

    transcript_text = "\n".join(lines)
    if meeting_title:
        transcript_text = f"Meeting: {meeting_title}\n\n{transcript_text}"

    client = Mistral(api_key=MISTRAL_API_KEY)

    response = await client.chat.complete_async(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript_text},
        ],
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content

    try:
        data = json.loads(raw)
        return MeetingMinutes.model_validate(data)
    except Exception as e:
        log.error("Failed to parse minutes JSON: %s", e)
        return _basic_minutes(segments, meeting_title)


def _basic_minutes(
    segments: list[AlignedSegment],
    meeting_title: str,
) -> MeetingMinutes:
    """Fallback: generate minimal minutes without LLM."""
    from app.pipeline.models import (
        ActionItem,
        MeetingDynamics,
        MeetingMetadata,
        SpeakerInfo,
        TranscriptEntry,
    )

    speakers: dict[str, dict] = {}
    transcript = []

    for seg in segments:
        name = seg.resolved_speaker or seg.diarization_speaker or "Unknown"
        duration = seg.end_time - seg.start_time

        if name not in speakers:
            speakers[name] = {"time": 0.0, "count": 0}
        speakers[name]["time"] += duration
        speakers[name]["count"] += 1

        transcript.append(TranscriptEntry(
            speaker=name,
            start_time=seg.start_time,
            end_time=seg.end_time,
            text=seg.text,
        ))

    total_duration = segments[-1].end_time - segments[0].start_time if segments else 0.0
    most_active = max(speakers, key=lambda k: speakers[k]["time"]) if speakers else ""

    return MeetingMinutes(
        meeting_metadata=MeetingMetadata(
            title=meeting_title or "Untitled Meeting",
            duration_seconds=total_duration,
            num_speakers=len(speakers),
            summary="Meeting minutes generated without LLM (no API key configured).",
        ),
        speakers=[
            SpeakerInfo(name=name, speaking_time_seconds=info["time"], segment_count=info["count"])
            for name, info in speakers.items()
        ],
        transcript=transcript,
        action_items=[],
        decisions=[],
        meeting_dynamics=MeetingDynamics(
            most_active_speaker=most_active,
            topics_discussed=[],
            tone="",
        ),
    )
