"""Phase C: Temporal alignment engine.

Enhanced version of the basic merge_diarization() — merges transcript segments
with diarization speaker segments using overlap analysis, confidence scoring,
and orphan recovery.
"""

from __future__ import annotations

import logging

from app.pipeline.models import AlignedSegment

log = logging.getLogger(__name__)

# If no diarization segment overlaps a transcript segment directly,
# expand the search window by this many seconds on each side.
ORPHAN_WINDOW = 0.5


def align_segments(
    transcript_segments: list[dict],
    diarization_segments: list[dict],
) -> list[AlignedSegment]:
    """Align transcript segments with diarization speaker labels.

    Args:
        transcript_segments: rows from transcript_segments table, each with
            id, start_time, end_time, text.
        diarization_segments: from pyannote, each with speaker, start, end.

    Returns:
        List of AlignedSegment with speaker labels and confidence scores.
    """
    aligned: list[AlignedSegment] = []

    for seg in transcript_segments:
        seg_start = seg["start_time"]
        seg_end = seg["end_time"]
        seg_duration = seg_end - seg_start

        if seg_start is None or seg_end is None or seg_duration <= 0:
            aligned.append(AlignedSegment(
                segment_id=seg["id"],
                start_time=seg_start or 0.0,
                end_time=seg_end or 0.0,
                text=seg["text"],
                diarization_speaker=None,
                confidence=0.0,
            ))
            continue

        # Collect all overlapping diarization segments
        overlaps = _compute_overlaps(seg_start, seg_end, diarization_segments)

        if overlaps:
            best_speaker, confidence = _pick_best(overlaps, seg_duration)
            aligned.append(AlignedSegment(
                segment_id=seg["id"],
                start_time=seg_start,
                end_time=seg_end,
                text=seg["text"],
                diarization_speaker=best_speaker,
                confidence=confidence,
            ))
        else:
            # Orphan recovery: expand search window
            overlaps = _compute_overlaps(
                seg_start - ORPHAN_WINDOW,
                seg_end + ORPHAN_WINDOW,
                diarization_segments,
            )
            if overlaps:
                best_speaker, _ = _pick_best(overlaps, seg_duration)
                aligned.append(AlignedSegment(
                    segment_id=seg["id"],
                    start_time=seg_start,
                    end_time=seg_end,
                    text=seg["text"],
                    diarization_speaker=best_speaker,
                    confidence=0.3,  # low confidence for orphan recovery
                ))
            else:
                aligned.append(AlignedSegment(
                    segment_id=seg["id"],
                    start_time=seg_start,
                    end_time=seg_end,
                    text=seg["text"],
                    diarization_speaker=None,
                    confidence=0.0,
                ))

    n_assigned = sum(1 for a in aligned if a.diarization_speaker)
    log.info(
        "Alignment: %d/%d segments assigned speakers (%.0f%%)",
        n_assigned, len(aligned),
        100 * n_assigned / len(aligned) if aligned else 0,
    )
    return aligned


def _compute_overlaps(
    start: float,
    end: float,
    diar_segments: list[dict],
) -> list[tuple[str, float]]:
    """Return (speaker, overlap_duration) for all diarization segments that overlap [start, end]."""
    results = []
    for ds in diar_segments:
        ov_start = max(start, ds["start"])
        ov_end = min(end, ds["end"])
        ov = ov_end - ov_start
        if ov > 0:
            results.append((ds["speaker"], ov))
    return results


def _pick_best(
    overlaps: list[tuple[str, float]],
    seg_duration: float,
) -> tuple[str, float]:
    """Pick the speaker with the greatest total overlap. Return (speaker, confidence).

    Confidence = fraction of segment duration covered by the winning speaker,
    penalized if there are competing speakers.
    """
    # Aggregate overlap by speaker
    totals: dict[str, float] = {}
    for speaker, ov in overlaps:
        totals[speaker] = totals.get(speaker, 0.0) + ov

    best_speaker = max(totals, key=totals.get)
    best_overlap = totals[best_speaker]
    total_overlap = sum(totals.values())

    # Base confidence: how much of the segment the best speaker covers
    coverage = min(best_overlap / seg_duration, 1.0) if seg_duration > 0 else 0.0

    # Dominance: how dominant is the best speaker among all overlapping speakers
    dominance = best_overlap / total_overlap if total_overlap > 0 else 0.0

    confidence = round(coverage * dominance, 3)
    return best_speaker, confidence
