# VOICEGRAPH: Hybrid Speaker Intelligence Pipeline
## Mistral Worldwide Hackathon — Updated Architecture Plan

---

## Executive Summary

**One-liner:** An agentic meeting intelligence system that fuses world-class ASR, acoustic voiceprints, and LLM reasoning to produce speaker-attributed minutes no single model can achieve alone.

**Track:** Mistral AI Track (build anything with the Mistral API)  
**Challenge:** Hugging Face — Best Use of Agent Skills  
**Why both:** Pyannote is a HuggingFace model. The agentic feedback loop (Mistral calling back into the acoustic pipeline) is a textbook demonstration of agent skills. Competing in both gives two shots at winning.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AUDIO INPUT (.wav/.mp3)                      │
└──────────────┬──────────────────────────────┬───────────────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────┐   ┌──────────────────────────────────────┐
│   PHASE A: TRANSCRIPTION │   │   PHASE B: DIARIZATION & IDENTITY   │
│                          │   │                                      │
│  Voxtral Transcribe V2   │   │  1. Pyannote 4 (HuggingFace)      │
│  ┌────────────────────┐  │   │     → Speaker segments [start, end]  │
│  │ • Full transcript   │  │   │     → Handles overlap & crosstalk   │
│  │ • Word timestamps   │  │   │                                      │
│  │ • Language detect   │  │   │  2. Per-cluster embedding extraction │
│  │ • Ignore speaker_N  │  │   │     → Pick best segment per speaker  │
│  └────────────────────┘  │   │     → ERes2NetV2 via FunASR           │
│                          │   │     → 3-6 embeddings total            │
└──────────┬───────────────┘   │                                      │
           │                   │  3. Vector lookup                     │
           │                   │     → Zvec (primary) / FAISS (fallback│
           │                   │     → Cosine similarity vs enrolled   │
           │                   │       voiceprints                     │
           │                   └──────────────┬───────────────────────┘
           │                                  │
           ▼                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  PHASE C: TEMPORAL ALIGNMENT ENGINE                  │
│                                                                     │
│  For each Voxtral word (with timestamp), find the Pyannote segment  │
│  it falls into. Assign speaker label. Handle edge cases:            │
│    • Words spanning segment boundaries → majority overlap wins      │
│    • Overlap zones (2+ speakers) → flag for agent review            │
│    • Orphan words (no segment match) → expand search window ±200ms  │
│                                                                     │
│  OUTPUT: Aligned transcript where every word has:                   │
│    { text, start, end, pyannote_speaker, confidence }               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│           PHASE D: AGENTIC RESOLUTION (Mistral Large 3)             │
│                                                                     │
│  TOOL-USING AGENT with function calling:                            │
│                                                                     │
│  Available tools:                                                   │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ resolve_speaker(speaker_id, transcript_ctx, acoustic_score, │    │
│  │                  calendar_ctx) → confirmed identity          │    │
│  │                                                             │    │
│  │ request_reanalysis(speaker_id, segment_range, reason)       │    │
│  │   → re-extracts embedding with different/longer segment     │    │
│  │                                                             │    │
│  │ flag_ambiguity(speaker_id, candidates, evidence)            │    │
│  │   → marks unresolvable cases for human review               │    │
│  │                                                             │    │
│  │ merge_speakers(speaker_a, speaker_b, evidence)              │    │
│  │   → Pyannote sometimes fragments one person into two        │    │
│  │                                                             │    │
│  │ extract_action_items(resolved_transcript) → structured JSON │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  Agent loop:                                                        │
│  1. Receives aligned transcript + acoustic scores + calendar        │
│  2. For each unresolved speaker, reasons about evidence             │
│  3. Can CALL BACK into pipeline (request_reanalysis, merge)         │
│  4. Produces final resolved output only when confident              │
│  5. Flags genuinely ambiguous cases rather than guessing             │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PHASE E: STRUCTURED OUTPUT                       │
│                                                                     │
│  Mistral Large 3 (JSON mode) produces:                              │
│  {                                                                  │
│    "meeting_metadata": { title, date, duration, language },         │
│    "speakers": [                                                    │
│      { id, name, role, acoustic_confidence, resolution_method }     │
│    ],                                                               │
│    "transcript": [                                                  │
│      { speaker, text, start, end }                                  │
│    ],                                                               │
│    "action_items": [                                                │
│      { owner, task, deadline_mentioned, verbatim_quote }            │
│    ],                                                               │
│    "decisions": [ ... ],                                            │
│    "ambiguities": [                                                 │
│      { segment, reason, candidates, agent_recommendation }          │
│    ],                                                               │
│    "meeting_dynamics": {                                            │
│      "talk_time_pct": { "Alice": 42, "Bob": 31, ... },             │
│      "interruption_count": { ... }                                  │
│    }                                                                │
│  }                                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Phase Breakdown

### Phase A: Transcription — Voxtral Transcribe V2

**What it does:** Pure ASR. Best-in-class text output with word-level timestamps.

**Implementation:**
```python
# Pseudocode — actual API call
response = mistral_client.audio.transcribe(
    model="voxtral-v2",
    file=audio_bytes,
    response_format="verbose_json",  # word-level timestamps
    language_detection=True
)

# Output shape we care about:
# {
#   "text": "As the PM, I'll take ownership of this...",
#   "words": [
#     {"word": "As", "start": 12.34, "end": 12.52},
#     {"word": "the", "start": 12.53, "end": 12.61},
#     ...
#   ],
#   "language": "en"
# }
```

**Key decisions:**
- Ignore Voxtral's internal `speaker_0` / `speaker_1` labels entirely. They exist but are unreliable for overlapping speech. We use Voxtral purely as an ASR engine.
- Keep the full `words[]` array with timestamps — this is the raw material for Phase C alignment.
- If audio is long (>30 min), chunk into overlapping windows (25 min chunks, 30s overlap) and stitch transcripts. Voxtral handles this well.

---

### Phase B: Diarization & Acoustic Identity

**Step B1: Pyannote 4 — Speaker Segmentation**

```python
from pyannote.audio import Pipeline

pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-4",
    use_auth_token=HF_TOKEN
)

diarization = pipeline(audio_file)

# Output: timeline of speaker turns
# SPEAKER_00: [0.5s → 4.2s]
# SPEAKER_01: [3.8s → 7.1s]   ← note overlap with SPEAKER_00
# SPEAKER_00: [7.0s → 12.3s]
```

**Why Pyannote specifically:**
- Handles overlapping speech natively (critical for meetings where people talk over each other)
- Produces clean speaker clusters (SPEAKER_00, SPEAKER_01, etc.) — these are consistent *within* a single audio file
- HuggingFace-native → directly relevant to the HF challenge
- Battle-tested, well-documented, reliable for a weekend build

**Step B2: Representative Segment Selection**

This is where you're right — we do NOT run ERes2NetV2 on every segment. Instead:

```python
def select_representative_segments(diarization, target_duration=5.0):
    """
    For each speaker cluster Pyannote identifies, pick the single
    best segment for embedding extraction.

    Selection criteria (in priority order):
    1. Non-overlapping (no other speaker active)
    2. Duration closest to 5 seconds (sweet spot for speaker embeddings)
    3. If no single segment ≥ 3s, concatenate adjacent segments from
       same speaker up to 5s total
    """
    speakers = {}
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        if speaker not in speakers:
            speakers[speaker] = []
        speakers[speaker].append((turn.start, turn.end))

    representative = {}
    for speaker, segments in speakers.items():
        # Filter to non-overlapping, sort by duration descending
        best = select_best_non_overlapping(segments, diarization, target_duration)
        representative[speaker] = best

    return representative  # {SPEAKER_00: (start, end), SPEAKER_01: (start, end), ...}
```

**Why this matters:** Embedding quality degrades on short utterances (<2s) and on segments with background speakers bleeding in. Careful segment selection for embedding extraction is a cheap optimization that dramatically improves downstream accuracy. This is one of those details that separates a hackathon project that *works* from one that *kinda works*.

**Step B3: ERes2NetV2 Embedding Extraction**

```python
from funasr import AutoModel

sv_model = AutoModel(model="iic/speech_eres2netv2_sv_zh-cn_16k-common")

def extract_embedding(audio_chunk):
    """
    Input: audio numpy array (16kHz, mono) for one representative segment
    Output: 192-dim speaker embedding vector
    """
    result = sv_model.generate(input=audio_chunk)
    return result[0]["spk_embedding"]  # np.array, shape (192,)
```

**Per-meeting flow:**
- Pyannote finds N speakers (typically 2-6 in a meeting)
- We extract N embeddings — one per speaker cluster
- Total ERes2NetV2 calls: **3-6**, not 80-120
- Wall-clock time: ~2-5 seconds total on CPU, sub-second on GPU

**Step B4: Vector Lookup — Zvec (Primary) / FAISS (Fallback)**

```python
# === Zvec path (primary — try this first) ===
import zvec

db = zvec.Database("voiceprints.zvec")

# Enrollment (one-time, before the meeting):
db.upsert("alice_chen", alice_embedding, metadata={"name": "Alice Chen", "role": "PM"})
db.upsert("bob_kumar", bob_embedding, metadata={"name": "Bob Kumar", "role": "Eng Lead"})

# Query (per meeting):
for speaker_id, embedding in meeting_embeddings.items():
    results = db.search(embedding, top_k=3)
    # results[0] = {"id": "alice_chen", "score": 0.94, "metadata": {...}}

# === FAISS fallback (if Zvec has issues) ===
import faiss
import numpy as np

index = faiss.IndexFlatIP(192)  # inner product ≈ cosine on normalized vectors
enrolled = np.stack([alice_emb, bob_emb, ...])  # (N, 192)
faiss.normalize_L2(enrolled)
index.add(enrolled)

query = meeting_embeddings["SPEAKER_00"].reshape(1, -1)
faiss.normalize_L2(query)
scores, indices = index.search(query, k=3)
```

**Decision framework for Zvec vs FAISS:**
- Start with Zvec in the first 2-3 hours of hacking
- If Zvec's API is stable, docs are clear, and search works → keep it. It's a better story for judges ("purpose-built lightweight vector DB from Alibaba")
- If you hit undocumented behavior, missing features, or setup issues → switch to FAISS immediately. Don't debug an alpha-stage library during a hackathon
- Either way, abstract behind an interface so the swap is trivial:

```python
class VoiceprintStore:
    def enroll(self, person_id: str, embedding: np.ndarray, metadata: dict): ...
    def identify(self, embedding: np.ndarray, top_k: int = 3) -> list[Match]: ...

class ZvecStore(VoiceprintStore): ...
class FAISSStore(VoiceprintStore): ...
```

---

### Phase C: Temporal Alignment Engine — THE CRITICAL LAYER

This is the hardest engineering in the entire pipeline. It's also invisible to users, which means teams skip it and get broken output. Don't skip it.

**The problem:** Voxtral and Pyannote process audio independently. They produce different temporal boundaries. You need to merge them.

```
Voxtral words:   |"As"|"the"|"PM"|","|"I'll"|"take"|"this"|
Voxtral times:   12.3 12.5  12.7 12.9  13.0   13.2   13.5

Pyannote:        |-------- SPEAKER_00 --------|--- SPEAKER_01 ---|
Pyannote times:  12.2                    13.1  13.1          14.8
```

**Alignment algorithm:**

```python
def align_words_to_speakers(voxtral_words, pyannote_diarization):
    """
    For each word from Voxtral, determine which Pyannote speaker
    segment it belongs to based on timestamp overlap.

    Returns list of aligned word objects.
    """
    aligned = []
    segments = list(pyannote_diarization.itertracks(yield_label=True))

    for word in voxtral_words:
        w_start, w_end = word["start"], word["end"]
        w_mid = (w_start + w_end) / 2  # midpoint heuristic

        best_speaker = None
        best_overlap = 0
        is_overlap_zone = False
        active_speakers = []

        for turn, _, speaker in segments:
            s_start, s_end = turn.start, turn.end

            # Calculate overlap between word span and segment span
            overlap_start = max(w_start, s_start)
            overlap_end = min(w_end, s_end)
            overlap = max(0, overlap_end - overlap_start)

            if overlap > 0:
                active_speakers.append(speaker)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = speaker

        # Flag overlap zones where multiple speakers are active
        if len(active_speakers) > 1:
            is_overlap_zone = True

        # Orphan handling: no segment matched this word
        if best_speaker is None:
            best_speaker = find_nearest_segment(w_mid, segments, max_gap=0.3)

        aligned.append({
            "text": word["word"],
            "start": w_start,
            "end": w_end,
            "speaker": best_speaker,
            "confidence": best_overlap / (w_end - w_start) if (w_end - w_start) > 0 else 0,
            "is_overlap": is_overlap_zone,
            "active_speakers": active_speakers if is_overlap_zone else None
        })

    return aligned
```

**Edge cases you MUST handle:**
1. **Overlap zones** — two speakers talking simultaneously. Mark these explicitly; the agent in Phase D can reason about them ("the words 'no, I disagree' in the overlap zone are more consistent with Bob's argumentative pattern").
2. **Orphan words** — Voxtral detects a word but Pyannote has a gap at that timestamp. Usually caused by very short utterances (backchannels like "mm-hmm", "right"). Expand the search window ±200-300ms.
3. **Segment boundary words** — a word straddles two Pyannote segments. Use majority overlap (which segment covers more of the word's duration).
4. **Timestamp drift** — Voxtral and Pyannote may have slight systematic offsets (~50-100ms). If you notice consistent misalignment, apply a global offset correction.

**Testing this layer:** Create a 2-minute test clip where you *know* who's speaking. Run alignment. Manually verify 20 words. This takes 15 minutes and will save you hours of debugging downstream.

---

### Phase D: Agentic Resolution — Mistral Large 3

**This is what makes the project "agentic" rather than "a pipeline with an LLM at the end."**

The key insight: Mistral doesn't just *consume* the pipeline output — it can *call back into it*. This feedback loop is the difference between a linear DAG and a genuine agent, and it's exactly what the HuggingFace "best use of agent skills" challenge is looking for.

**Tool definitions for Mistral function calling:**

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "resolve_speaker",
            "description": "Confirm a speaker's identity based on combined evidence. Call this when acoustic match + semantic context converge on a single candidate with high confidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pyannote_label": {"type": "string", "description": "e.g. SPEAKER_00"},
                    "resolved_name": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "string", "description": "Brief justification combining acoustic + semantic signals"}
                },
                "required": ["pyannote_label", "resolved_name", "confidence", "evidence"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_reanalysis",
            "description": "Request re-extraction of a speaker embedding using a different or longer audio segment. Use when acoustic confidence is low (<0.75) and you believe a better sample exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pyannote_label": {"type": "string"},
                    "reason": {"type": "string"},
                    "preferred_time_range": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "number"},
                            "end": {"type": "number"}
                        },
                        "description": "Optional: suggest a specific time range from the transcript where this speaker had a longer, clearer turn."
                    }
                },
                "required": ["pyannote_label", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "merge_speakers",
            "description": "Merge two Pyannote speaker labels that you believe are the same person. Common when Pyannote fragments a speaker who changes vocal register (e.g., presenting vs. casual discussion).",
            "parameters": {
                "type": "object",
                "properties": {
                    "speaker_a": {"type": "string"},
                    "speaker_b": {"type": "string"},
                    "evidence": {"type": "string"}
                },
                "required": ["speaker_a", "speaker_b", "evidence"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "flag_ambiguity",
            "description": "Flag a speaker identification that cannot be confidently resolved. Honest uncertainty is better than wrong attribution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pyannote_label": {"type": "string"},
                    "candidates": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "reason": {"type": "string"}
                },
                "required": ["pyannote_label", "candidates", "reason"]
            }
        }
    }
]
```

**The agent system prompt:**

```
You are the Speaker Resolution Agent for VoiceGraph. You have three sources of evidence:

1. ACOUSTIC EVIDENCE: Cosine similarity scores from our speaker embedding
   database (ERes2NetV2 + Zvec). Scores above 0.85 are strong matches.
   Scores 0.70-0.85 are suggestive. Below 0.70 is unreliable.

2. SEMANTIC EVIDENCE: The meeting transcript with speaker labels. Look for:
   - Self-identification ("I'm Alice, the PM on this")
   - Role references ("As the engineering lead, I think...")
   - Name mentions by others ("Bob, can you take that?")
   - Speaking patterns consistent with known roles

3. CALENDAR CONTEXT: Meeting attendee list with names and roles.

Your job: For each Pyannote speaker label, determine the real identity.

RULES:
- High acoustic match (>0.85) + consistent semantic context → resolve_speaker
- Low acoustic match (<0.75) → request_reanalysis with a better segment before deciding
- Two Pyannote labels that seem to be the same person → merge_speakers with evidence
- Genuinely unresolvable → flag_ambiguity (never guess; wrong attribution is worse than unknown)
- Always show your reasoning in the evidence field
```

**Agent execution loop (Python orchestrator):**

```python
async def run_resolution_agent(aligned_transcript, acoustic_matches, calendar):
    """
    Runs the Mistral agent loop. The agent can make tool calls
    that feed back into the acoustic pipeline.
    Max iterations: 5 (prevent infinite loops)
    """
    payload = build_agent_payload(aligned_transcript, acoustic_matches, calendar)

    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload)}
    ]

    max_iterations = 5
    for i in range(max_iterations):
        response = await mistral_client.chat.complete(
            model="mistral-large-latest",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )

        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append(msg)
            for tool_call in msg.tool_calls:
                result = await execute_tool(tool_call)  # This is where the magic is
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                })
        else:
            # Agent is done — final text response with summary
            return parse_final_resolution(msg.content)

    return timeout_resolution(messages)  # Graceful degradation


async def execute_tool(tool_call):
    """
    THIS IS THE AGENTIC FEEDBACK LOOP.
    When Mistral calls request_reanalysis, we actually go back
    to the audio, re-extract an embedding, and return the new score.
    """
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)

    if name == "resolve_speaker":
        # Store the resolution
        return {"status": "confirmed", **args}

    elif name == "request_reanalysis":
        # ACTUALLY re-extract embedding from a different segment
        speaker = args["pyannote_label"]
        time_range = args.get("preferred_time_range")
        new_embedding = extract_embedding_for_range(speaker, time_range)
        new_matches = voiceprint_store.identify(new_embedding, top_k=3)
        return {
            "status": "reanalyzed",
            "new_matches": [
                {"name": m.id, "score": m.score} for m in new_matches
            ]
        }

    elif name == "merge_speakers":
        # Merge in the aligned transcript
        merge_in_transcript(args["speaker_a"], args["speaker_b"])
        return {"status": "merged", **args}

    elif name == "flag_ambiguity":
        return {"status": "flagged", **args}
```

---

### Phase E: Final Output Generation

After the agent resolves speakers, a second Mistral call (separate from the agent) generates the structured meeting output:

```python
final_output = await mistral_client.chat.complete(
    model="mistral-large-latest",
    messages=[{
        "role": "user",
        "content": f"""Given this resolved, speaker-attributed transcript:
{json.dumps(resolved_transcript)}

Generate structured meeting minutes in JSON with:
- meeting_metadata (title, date, duration, detected language)
- speakers (name, role, talk_time_percentage)
- key_discussions (topic, summary, speakers_involved)
- action_items (owner, task, deadline_if_mentioned, verbatim_quote)
- decisions (what was decided, who decided, dissenters)
- meeting_dynamics (talk_time distribution, interruption patterns)
"""
    }],
    response_format={"type": "json_object"}
)
```

---

## Build Order & Time Budget (24-hour hackathon)

| Hours  | Task                                           | Deliverable                           | Risk  |
|--------|------------------------------------------------|---------------------------------------|-------|
| 0-1    | Environment setup, API keys, deps              | Working dev environment               | Low   |
| 1-3    | Phase A: Voxtral integration                   | Audio → transcript with timestamps    | Low   |
| 3-5    | Phase B1: Pyannote diarization                 | Audio → speaker segments              | Low   |
| 5-8    | Phase C: Temporal alignment engine             | Merged transcript with speaker labels | HIGH  |
| 8-9    | Phase B2-B4: ERes2NetV2 + Zvec/FAISS           | Speaker embeddings + vector lookup    | Med   |
| 9-12   | Phase D: Mistral agent with tool calling        | Working resolution loop               | Med   |
| 12-14  | Phase E: Structured output + action items       | Complete JSON output                  | Low   |
| 14-17  | Frontend / demo dashboard                       | Visual demo                           | Low   |
| 17-19  | Integration testing with real meeting audio     | End-to-end working pipeline           | Med   |
| 19-21  | Demo prep: script, record video, polish         | 2-min demo video                      | Low   |
| 21-24  | Buffer for debugging + submission               | Submitted project                     | —     |

**Critical path:** Phase C (alignment) is the riskiest. If it slips, everything downstream breaks. Allocate 3 hours and start with the simplest correct algorithm (midpoint heuristic), then optimize only if time allows.

---

## Degraded Mode Strategy

Your demo MUST work. Plan for component failures:

| Component fails          | Degraded behavior                                                           |
|--------------------------|-----------------------------------------------------------------------------|
| Zvec won't install       | Swap to FAISS (behind VoiceprintStore interface). 5-minute fix.             |
| ERes2NetV2 model issues  | Skip acoustic matching entirely. Agent resolves using semantic-only.        |
| Pyannote GPU issues      | Run with `device="cpu"` — slower but functional for demo-length audio.      |
| Alignment has edge cases | Show only non-overlapping segments in demo. Flag overlaps as "under review."|
| Agent loop hangs         | Set max_iterations=3 and hard timeout at 30s. Partial resolution > none.    |

**Golden rule:** At hour 14, you must have a working end-to-end demo, even if degraded. Optimize from 14-19. Never be in a state where nothing works.

---

## Demo Strategy (2-minute video)

### Structure:
```
0:00-0:15  HOOK — Play 5 seconds of chaotic meeting audio (crosstalk, interruptions).
           Text overlay: "Who said what? Current tools get this wrong 30% of the time."

0:15-0:45  SHOW THE PIPELINE — Architecture diagram (animated if possible).
           "We built VoiceGraph: Voxtral hears the words. Pyannote separates the voices.
            Alibaba ERes2NetV2 recognizes who's speaking. And Mistral Large 3 acts as
            an intelligent agent that fuses all three signals."

0:45-1:30  LIVE DEMO — Upload a meeting recording. Show:
           1. Transcript appearing (Voxtral)
           2. Speaker segments visualized (Pyannote)
           3. Acoustic match scores (ERes2NetV2)
           4. Agent reasoning in real-time ("SPEAKER_02 acoustic match to Bob: 0.72.
              Requesting reanalysis... New match: 0.91. Confirmed.")
           5. Final output: speaker-attributed minutes with action items

1:30-1:50  THE AGENTIC MOMENT — Highlight ONE specific case where:
           - Acoustic match was ambiguous
           - The agent requested reanalysis or used semantic context
           - And got the right answer
           "This is what makes VoiceGraph different. It doesn't just match vectors—
            it reasons about identity the way a human would."

1:50-2:00  CLOSE — "VoiceGraph: the ears, the memory, the brain."
           Show GitHub + team.
```

### Demo audio selection:
- Use a 3-5 minute recording (not too long for demo processing time)
- Ensure it has 3-4 speakers with at least one instance of overlapping speech
- Pre-enroll the speakers' voiceprints so the identity matching actually works
- Have a BACKUP pre-processed result ready in case live processing is slow

---

## Judging Criteria Alignment

| Criterion               | How VoiceGraph scores                                                                                     |
|--------------------------|----------------------------------------------------------------------------------------------------------|
| **Technicality**         | Multi-model pipeline with temporal alignment, speaker embeddings, vector search, and an LLM agent with tool calling and a feedback loop. This is not "prompt engineering." |
| **Creativity**           | Hybrid architecture that treats each component as a specialist. The agentic feedback loop (LLM calling back into acoustic pipeline) is novel and unexpected.              |
| **Usefulness**           | Meeting transcription with speaker attribution is a $2B+ market. Every company with remote meetings needs this. Actionable minutes with owner-attributed action items.    |
| **Demo**                 | Visual pipeline, real-time processing, specific "agentic moment" highlight. Scripted for 2 minutes.                                                                       |
| **Track alignment**      | Voxtral (core ASR) + Mistral Large 3 (core agent). Both are central, not bolted on. HuggingFace challenge via Pyannote + agent skills.                                   |

---

## Pitch One-Liner Options

Pick one for the presentation:

1. "We let Voxtral be the ears, Alibaba be the acoustic memory, and Mistral be the brain—an agent that doesn't just transcribe meetings, but *understands who's in the room*."

2. "Most meeting tools guess who's speaking. VoiceGraph *knows*—and when it doesn't know, its Mistral agent asks for better evidence instead of guessing."

3. "We built a system where an LLM agent can call back into an acoustic pipeline to request better data. It's not just AI transcription—it's AI that reasons about its own uncertainty."

---

## File Structure

```
voicegraph/
├── README.md
├── requirements.txt
├── config.py                    # API keys, model paths, thresholds
├── main.py                      # CLI entry point: audio → final output
│
├── pipeline/
│   ├── __init__.py
│   ├── transcribe.py            # Phase A: Voxtral wrapper
│   ├── diarize.py               # Phase B1: Pyannote wrapper
│   ├── embeddings.py            # Phase B2-B3: ERes2NetV2 extraction
│   ├── voiceprint_store.py      # Phase B4: VoiceprintStore interface + Zvec/FAISS
│   ├── align.py                 # Phase C: Temporal alignment engine
│   ├── agent.py                 # Phase D: Mistral agent + tool definitions
│   └── output.py                # Phase E: Structured output generation
│
├── enrollment/
│   ├── enroll.py                # CLI to enroll a speaker voiceprint
│   └── voiceprints.zvec         # (or voiceprints.faiss)
│
├── frontend/                    # Demo dashboard (optional, time permitting)
│   ├── app.py                   # Streamlit/Gradio app
│   └── ...
│
├── tests/
│   ├── test_alignment.py        # CRITICAL: test Phase C with known audio
│   └── test_agent.py            # Test agent tool calling with mock data
│
└── demo/
    ├── sample_meeting.wav       # Pre-selected demo audio
    ├── precomputed_output.json  # Backup for live demo
    └── architecture_diagram.png
```
