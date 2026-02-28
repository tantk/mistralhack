"""Shared Pydantic models for the VoiceGraph pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AlignedSegment(BaseModel):
    """A transcript segment aligned with a diarization speaker label."""

    segment_id: int
    start_time: float
    end_time: float
    text: str
    diarization_speaker: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    resolved_speaker: str | None = None


class SpeakerMatch(BaseModel):
    """Acoustic match between a diarization label and a known voiceprint."""

    diarization_speaker: str
    matched_name: str
    cosine_similarity: float
    confirmed: bool = False


class PipelineInput(BaseModel):
    """Input to the pipeline orchestrator."""

    meeting_id: int
    attendees: list[str] = Field(default_factory=list)


class AgentResolution(BaseModel):
    """A single speaker resolution decision from the agent."""

    diarization_speaker: str
    resolved_name: str
    reasoning: str


class Ambiguity(BaseModel):
    """A flagged ambiguity the agent couldn't resolve."""

    diarization_speaker: str
    candidates: list[str]
    reason: str


class MeetingMinutes(BaseModel):
    """Structured meeting minutes output from Phase E."""

    meeting_metadata: MeetingMetadata
    speakers: list[SpeakerInfo]
    transcript: list[TranscriptEntry]
    action_items: list[ActionItem]
    decisions: list[str]
    meeting_dynamics: MeetingDynamics | None = None


class MeetingMetadata(BaseModel):
    title: str = ""
    duration_seconds: float = 0.0
    num_speakers: int = 0
    summary: str = ""


class SpeakerInfo(BaseModel):
    name: str
    speaking_time_seconds: float = 0.0
    segment_count: int = 0


class TranscriptEntry(BaseModel):
    speaker: str
    start_time: float
    end_time: float
    text: str


class ActionItem(BaseModel):
    description: str
    assignee: str | None = None


class MeetingDynamics(BaseModel):
    most_active_speaker: str = ""
    topics_discussed: list[str] = Field(default_factory=list)
    tone: str = ""


class PipelineResult(BaseModel):
    """Full pipeline output."""

    meeting_id: int
    status: str = "success"
    aligned_segments: list[AlignedSegment] = Field(default_factory=list)
    acoustic_matches: list[SpeakerMatch] = Field(default_factory=list)
    resolutions: list[AgentResolution] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    minutes: MeetingMinutes | None = None
    error: str | None = None


# Rebuild forward refs now that all models are defined
MeetingMinutes.model_rebuild()
