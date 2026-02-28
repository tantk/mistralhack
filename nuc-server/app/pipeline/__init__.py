"""VoiceGraph Pipeline Orchestrator.

run_pipeline(meeting_id) executes the full intelligence pipeline:
  1. Diarize (pyannote via titan)
  2. Align (merge transcript segments with diarization)
  3. Extract speaker embeddings & match against voiceprints
  4. Agent-resolve speaker identities (Mistral Large)
  5. Generate structured meeting minutes (Mistral JSON mode)
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

import httpx
import numpy as np
from pydub import AudioSegment

from app.config import DIARIZATION_URL
from app.database import get_db
from app.pipeline.agent import run_agent
from app.pipeline.alignment import align_segments
from app.pipeline.models import (
    AlignedSegment,
    PipelineResult,
    SpeakerMatch,
)
from app.pipeline.output import generate_minutes
from app.pipeline.voiceprint_store import get_voiceprint_store
from app.services.diarization import run_diarization

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


async def run_pipeline(
    meeting_id: int,
    attendees: list[str] | None = None,
) -> PipelineResult:
    """Execute the full VoiceGraph pipeline for a meeting."""
    attendees = attendees or []

    # ── Load meeting data ──────────────────────────────────────────────
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT audio_path, title, status FROM meetings WHERE id = ?",
            (meeting_id,),
        )
        if not rows:
            return PipelineResult(meeting_id=meeting_id, status="error", error="Meeting not found")
        meeting = dict(rows[0])

        segments = await db.execute_fetchall(
            "SELECT id, start_time, end_time, text, speaker "
            "FROM transcript_segments WHERE meeting_id = ? ORDER BY start_time",
            (meeting_id,),
        )
        transcript_segments = [dict(s) for s in segments]
    finally:
        await db.close()

    audio_path = meeting.get("audio_path")
    if not audio_path:
        return PipelineResult(
            meeting_id=meeting_id, status="error",
            error="No audio file for this meeting",
        )

    if not transcript_segments:
        return PipelineResult(
            meeting_id=meeting_id, status="error",
            error="No transcript segments found",
        )

    # ── Step 1: Diarize ───────────────────────────────────────────────
    log.info("Pipeline [%d] Step 1: Diarization", meeting_id)
    try:
        diarization_segments = await run_diarization(audio_path)
    except Exception as e:
        log.error("Diarization failed: %s", e)
        return PipelineResult(
            meeting_id=meeting_id, status="error",
            error=f"Diarization failed: {e}",
        )

    # ── Step 2: Align ─────────────────────────────────────────────────
    log.info("Pipeline [%d] Step 2: Alignment", meeting_id)
    aligned = align_segments(transcript_segments, diarization_segments)

    # ── Step 3: Acoustic matching ─────────────────────────────────────
    log.info("Pipeline [%d] Step 3: Speaker embedding + voiceprint matching", meeting_id)
    acoustic_matches = await _match_speakers(aligned, diarization_segments, audio_path)

    # ── Step 4: Agent resolution ──────────────────────────────────────
    log.info("Pipeline [%d] Step 4: Agent speaker resolution", meeting_id)
    try:
        resolutions, ambiguities = await run_agent(
            aligned, acoustic_matches, attendees, audio_path=audio_path,
        )
    except Exception as e:
        log.error("Agent failed, using threshold fallback: %s", e)
        resolutions = []
        ambiguities = []

    # Apply resolutions to aligned segments
    resolution_map = {r.diarization_speaker: r.resolved_name for r in resolutions}
    for seg in aligned:
        if seg.diarization_speaker and seg.diarization_speaker in resolution_map:
            seg.resolved_speaker = resolution_map[seg.diarization_speaker]

    # If agent failed / no resolutions, apply threshold fallback from acoustic matches
    if not resolutions:
        for m in acoustic_matches:
            if m.cosine_similarity >= 0.85:
                for seg in aligned:
                    if seg.diarization_speaker == m.diarization_speaker and not seg.resolved_speaker:
                        seg.resolved_speaker = m.matched_name

    # ── Step 5: Generate minutes ──────────────────────────────────────
    log.info("Pipeline [%d] Step 5: Generating structured minutes", meeting_id)
    try:
        minutes = await generate_minutes(aligned, meeting_title=meeting.get("title", ""))
    except Exception as e:
        log.error("Minutes generation failed: %s", e)
        minutes = None

    # ── Persist results ───────────────────────────────────────────────
    result = PipelineResult(
        meeting_id=meeting_id,
        status="success",
        aligned_segments=aligned,
        acoustic_matches=acoustic_matches,
        resolutions=resolutions,
        ambiguities=ambiguities,
        minutes=minutes,
    )

    await _save_results(meeting_id, result)

    # Update speaker labels in transcript_segments table
    db = await get_db()
    try:
        for seg in aligned:
            speaker = seg.resolved_speaker or seg.diarization_speaker
            if speaker:
                await db.execute(
                    "UPDATE transcript_segments SET speaker = ? WHERE id = ?",
                    (speaker, seg.segment_id),
                )
        await db.execute(
            "UPDATE meetings SET status = 'processed' WHERE id = ?",
            (meeting_id,),
        )
        await db.commit()
    finally:
        await db.close()

    log.info("Pipeline [%d] completed successfully", meeting_id)
    return result


async def _match_speakers(
    aligned: list[AlignedSegment],
    diarization_segments: list[dict],
    audio_path: str,
) -> list[SpeakerMatch]:
    """Extract embeddings for each unique diarization speaker and match against voiceprints."""
    store = get_voiceprint_store()
    if not store.list_speakers():
        log.info("No enrolled speakers — skipping acoustic matching")
        return []

    # Group diarization segments by speaker, pick the longest for embedding
    speaker_segments: dict[str, dict] = {}
    for ds in diarization_segments:
        spk = ds["speaker"]
        dur = ds["end"] - ds["start"]
        if spk not in speaker_segments or dur > (speaker_segments[spk]["end"] - speaker_segments[spk]["start"]):
            speaker_segments[spk] = ds

    matches: list[SpeakerMatch] = []

    for speaker_label, best_seg in speaker_segments.items():
        try:
            audio = AudioSegment.from_file(audio_path, format="wav")
            chunk = audio[int(best_seg["start"] * 1000) : int(best_seg["end"] * 1000)]

            if len(chunk) < 500:
                continue

            import io
            buf = io.BytesIO()
            chunk.set_frame_rate(16000).set_channels(1).set_sample_width(2).export(buf, format="wav")

            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{DIARIZATION_URL}/embed",
                    files={"audio": ("chunk.wav", buf.getvalue(), "audio/wav")},
                )
                resp.raise_for_status()

            embedding = np.array(resp.json()["embedding"], dtype=np.float32)
            results = store.identify(embedding, top_k=1)

            if results:
                best = results[0]
                matches.append(SpeakerMatch(
                    diarization_speaker=speaker_label,
                    matched_name=best["name"],
                    cosine_similarity=best["similarity"],
                    confirmed=best["similarity"] >= 0.85,
                ))
        except Exception as e:
            log.warning("Embedding extraction failed for %s: %s", speaker_label, e)

    return matches


async def _save_results(meeting_id: int, result: PipelineResult):
    """Persist pipeline results to the meeting_minutes table."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO meeting_minutes (meeting_id, result_json) VALUES (?, ?)",
            (meeting_id, result.model_dump_json()),
        )
        await db.commit()
    finally:
        await db.close()
