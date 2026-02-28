"""Phase D: Agentic speaker resolution via Mistral Large with tool calling.

Builds a prompt from aligned segments + acoustic matches + attendee list,
then runs a multi-turn tool-calling loop (max 5 iterations) to resolve
diarization labels to real speaker names.
"""

from __future__ import annotations

import json
import logging

from mistralai import Mistral

from app.config import MISTRAL_API_KEY
from app.pipeline.agent_tools import TOOL_SCHEMAS, ToolContext, execute_tool
from app.pipeline.models import (
    AgentResolution,
    AlignedSegment,
    Ambiguity,
    SpeakerMatch,
)

log = logging.getLogger(__name__)

MODEL = "mistral-large-latest"
MAX_ITERATIONS = 5

SYSTEM_PROMPT = """\
You are a speaker resolution agent for meeting transcription.

You will receive:
1. Transcript segments with diarization labels (SPEAKER_0, SPEAKER_1, etc.)
2. Acoustic voiceprint matches (cosine similarity scores)
3. An optional attendee list

Your job is to figure out which real person each SPEAKER_N label corresponds to.

Strategy:
- Start with high-confidence acoustic matches (similarity > 0.85)
- Use conversational context clues (people addressing each other by name, self-introductions)
- If acoustic evidence is weak, use request_reanalysis on segments where the speaker talks the most
- Merge labels that clearly refer to the same person
- Flag truly ambiguous cases rather than guessing

Call resolve_speaker for each label you can confidently identify.
Call flag_ambiguity for labels you cannot resolve.
When done resolving all speakers, simply state that you're finished.\
"""


def _build_user_message(
    aligned: list[AlignedSegment],
    matches: list[SpeakerMatch],
    attendees: list[str],
) -> str:
    """Build the initial user message for the agent."""
    parts: list[str] = []

    # Attendee list
    if attendees:
        parts.append("## Known attendees\n" + ", ".join(attendees))

    # Acoustic matches
    if matches:
        parts.append("## Acoustic voiceprint matches")
        for m in matches:
            status = "CONFIRMED" if m.confirmed else "tentative"
            parts.append(
                f"- {m.diarization_speaker} → {m.matched_name} "
                f"(similarity: {m.cosine_similarity:.3f}, {status})"
            )

    # Transcript segments (compact representation)
    parts.append("## Transcript segments")
    for seg in aligned:
        speaker = seg.diarization_speaker or "UNKNOWN"
        conf = f" [conf={seg.confidence:.2f}]" if seg.confidence < 0.8 else ""
        parts.append(f"[{seg.start_time:.1f}–{seg.end_time:.1f}] {speaker}{conf}: {seg.text}")

    # Unique speaker labels for quick reference
    labels = sorted({s.diarization_speaker for s in aligned if s.diarization_speaker})
    if labels:
        parts.append(f"\n## Speaker labels to resolve: {', '.join(labels)}")

    return "\n".join(parts)


async def run_agent(
    aligned: list[AlignedSegment],
    matches: list[SpeakerMatch],
    attendees: list[str],
    audio_path: str | None = None,
) -> tuple[list[AgentResolution], list[Ambiguity]]:
    """Run the Mistral agent loop to resolve speaker identities.

    Returns (resolutions, ambiguities).
    """
    if not MISTRAL_API_KEY:
        log.warning("MISTRAL_API_KEY not set — falling back to threshold matching")
        return _threshold_fallback(matches), []

    client = Mistral(api_key=MISTRAL_API_KEY)
    ctx = ToolContext(audio_path=audio_path)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(aligned, matches, attendees)},
    ]

    for iteration in range(MAX_ITERATIONS):
        log.info("Agent iteration %d/%d", iteration + 1, MAX_ITERATIONS)

        response = await client.chat.complete_async(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )

        choice = response.choices[0]
        message = choice.message

        # Append assistant message to history
        messages.append(message)

        # If no tool calls, the agent is done
        if not message.tool_calls:
            log.info("Agent finished after %d iterations", iteration + 1)
            break

        # Process each tool call
        for tc in message.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            result = await execute_tool(fn_name, fn_args, ctx)

            messages.append({
                "role": "tool",
                "name": fn_name,
                "content": result,
                "tool_call_id": tc.id,
            })

    # Build results from context
    resolutions = [
        AgentResolution(
            diarization_speaker=label,
            resolved_name=info["resolved_name"],
            reasoning=info["reasoning"],
        )
        for label, info in ctx.resolutions.items()
    ]

    # Apply merges: if speaker_b was resolved, propagate to speaker_a
    for a, b in ctx.merges:
        if b in ctx.resolutions and a not in ctx.resolutions:
            info = ctx.resolutions[b]
            resolutions.append(AgentResolution(
                diarization_speaker=a,
                resolved_name=info["resolved_name"],
                reasoning=f"Merged from {b}: {info['reasoning']}",
            ))

    ambiguities = [
        Ambiguity(
            diarization_speaker=a["diarization_speaker"],
            candidates=a["candidates"],
            reason=a["reason"],
        )
        for a in ctx.ambiguities
    ]

    log.info(
        "Agent resolved %d speakers, flagged %d ambiguities",
        len(resolutions), len(ambiguities),
    )
    return resolutions, ambiguities


def _threshold_fallback(matches: list[SpeakerMatch]) -> list[AgentResolution]:
    """Simple fallback: treat high-similarity acoustic matches as confirmed."""
    resolutions = []
    for m in matches:
        if m.cosine_similarity >= 0.85:
            resolutions.append(AgentResolution(
                diarization_speaker=m.diarization_speaker,
                resolved_name=m.matched_name,
                reasoning=f"Acoustic match (cosine={m.cosine_similarity:.3f}, above 0.85 threshold)",
            ))
    return resolutions
