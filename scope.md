Phase A: Transcription (Mistral's Voxtral)

Send the meeting audio to Voxtral Transcribe V2.
​

Goal: Get the highest quality text, word-level timestamps, and language detection. Ignore Voxtral's internal speaker_0 labels, relying on it purely for world-class ASR text.

Phase B: Diarization & Acoustic Identity (Pyannote + Alibaba)

Pass the same audio to Pyannote. Pyannote handles the overlapping speech and generates precise [start, end] segments for each speaker turn.

For each segment Pyannote finds, pass that exact audio chunk into Alibaba's ERes2NetV2 (via ModelScope/FunASR) to extract the speaker embedding.

Upsert these embeddings into Zvec, Alibaba's newly open-sourced lightweight vector database (the "SQLite of Vector DBs").

Goal: Query Zvec for cross-meeting identity (e.g., "This vector matches Alice's enrolled voiceprint with 0.94 cosine similarity").

Phase C: Agentic Resolution & Intelligence (Mistral LLM)

This is the crown jewel. You pass Mistral Large 3 a rich JSON payload:

The transcript (from Voxtral).

The acoustic speaker matches (from Alibaba ERes2Net + Zvec).

The calendar context (attendees, roles).

The Prompt: "You are the Speaker Resolution Agent. You have acoustic matches from our vector database indicating Speaker A is Alice (85% confidence). You also have the transcript showing Speaker A saying 'As the PM, I'll take this.' Alice is the PM in the calendar. Confirm and lock the identity of Speaker A as Alice Chen."

Goal: Mistral does the "thinking" to fuse the acoustic vector math with semantic context, producing the final structured minutes and ambiguity detection.

3. How to pitch this to the Hackathon Judges
When presenting, use this framing to show you deeply understand the AI landscape:

"We love Voxtral for its blazing transcription speed and quality, but meeting diarization with overlapping speech is notoriously hard for any ASR-first model. Instead of fighting it, we built a hybrid intelligence pipeline.

We use Voxtral for perfect text. We use Pyannote to isolate the overlapping audio segments. We feed those segments through Alibaba’s open-source ERes2NetV2 to extract acoustic embeddings, matching them via Alibaba Zvec.

But acoustic matching isn't perfect. So we feed both the acoustic vector scores AND the Voxtral transcript into Mistral Large 3. Mistral acts as an agentic referee, combining the vector-database match with semantic meeting context to flawlessly identify speakers. We let Voxtral be the ears, Alibaba be the acoustic memory, and Mistral be the brain."

Why this specific stack wins
It respects the constraints: You are heavily utilizing Voxtral and Mistral Large 3 for the core value props (Transcription, Resolution, Minutes, Ambiguity).

It uses the right tool for the right job: Using ERes2NetV2 solves the "short utterance" problem better than generic embeddings, and Zvec is perfect for a local, hackathon-friendly vector store without needing a heavy Milvus/Pinecone setup.

It looks technically sophisticated: Piping audio through Pyannote → FunASR/ERes2Net → Zvec → Mistral JSON mode is a highly impressive DAG (Directed Acyclic Graph) for a weekend build.
