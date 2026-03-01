import { z } from 'zod'
import { getBackend } from './backend'

// ─── Zod schemas (validated at runtime boundaries) ──────────────────────────

export const WordSchema = z.object({
  word: z.string(),
  start: z.number(),
  end: z.number(),
})

export const SegmentSchema = z.object({
  speaker: z.string(),
  start: z.number(),
  end: z.number(),
  text: z.string(),
  is_overlap: z.boolean().optional().default(false),
  confidence: z.number().optional().default(0),
  active_speakers: z.array(z.string()).optional().default([]),
})

export const DecisionSchema = z.object({
  timestamp: z.number(),
  summary: z.string(),
  proposed_by: z.string(),
  seconded_by: z.string().nullable(),
  dissent_by: z.string().nullable(),
  status: z.enum(['locked', 'open', 'contested']),
})

export const AmbiguitySchema = z.object({
  timestamp: z.number(),
  type: z.enum(['attributional', 'commitment', 'temporal', 'scope']),
  quote: z.string(),
  speaker: z.string(),
  confidence: z.number(),
  candidates: z.array(z.string()),
})

export const ActionItemSchema = z.object({
  owner: z.string(),
  task: z.string(),
  deadline_mentioned: z.string().nullable().optional(),
  verbatim_quote: z.string().nullable().optional(),
})

export const MeetingDynamicsSchema = z.object({
  talk_time_pct: z.record(z.string(), z.number()),
  interruption_count: z.number(),
})

export const ToolCallSchema = z.object({
  tool: z.string(),
  args: z.record(z.unknown()),
})

export const ToolResultSchema = z.object({
  tool: z.string(),
  result: z.string(),
})

export const SpeakerResolvedSchema = z.object({
  label: z.string(),
  name: z.string(),
  confidence: z.number(),
  method: z.string(),
})

export const JobCreatedSchema = z.object({ job_id: z.string() })

export const TranscriptCompleteSchema = z.object({
  text: z.string(),
  words: z.array(WordSchema).optional().default([]),
  language: z.string().nullable().optional(),
  duration_ms: z.number(),
})

export const DiarizationCompleteSchema = z.object({
  segments: z.array(SegmentSchema),
})

export const AcousticMatchSchema = z.object({
  diarization_speaker: z.string(),
  matched_name: z.string(),
  cosine_similarity: z.number(),
  confirmed: z.boolean(),
})

export const AcousticMatchesCompleteSchema = z.object({
  matches: z.array(AcousticMatchSchema),
})

export const SegmentsResolvedSchema = z.object({
  segments: z.array(SegmentSchema),
})

export const AnalysisCompleteSchema = z.object({
  decisions: z.array(DecisionSchema),
  ambiguities: z.array(AmbiguitySchema),
  action_items: z.array(ActionItemSchema),
  meeting_dynamics: MeetingDynamicsSchema.optional(),
})

// ─── Inferred types ──────────────────────────────────────────────────────────

export type Word = z.infer<typeof WordSchema>
export type Segment = z.infer<typeof SegmentSchema>
export type Decision = z.infer<typeof DecisionSchema>
export type Ambiguity = z.infer<typeof AmbiguitySchema>
export type ActionItem = z.infer<typeof ActionItemSchema>
export type MeetingDynamics = z.infer<typeof MeetingDynamicsSchema>
export type ToolCallEntry = z.infer<typeof ToolCallSchema>
export type ToolResultEntry = z.infer<typeof ToolResultSchema>
export type SpeakerResolutionEntry = z.infer<typeof SpeakerResolvedSchema>
export type AcousticMatchEntry = z.infer<typeof AcousticMatchSchema>
export type AnalysisResult = z.infer<typeof AnalysisCompleteSchema>

// ─── Auth helpers ───────────────────────────────────────────────────────────

export function getApiKey(): string {
  return localStorage.getItem('apiKey') || ''
}

export function promptApiKey(): string {
  const key = prompt('Enter API key:')
  if (key) localStorage.setItem('apiKey', key)
  return key || ''
}

export function authHeaders(): Record<string, string> {
  const key = getApiKey()
  return key ? { Authorization: `Bearer ${key}` } : {}
}

// ─── API client ──────────────────────────────────────────────────────────────

export async function submitJob(file: File, attendees?: string[]): Promise<string> {
  const base = await getBackend()
  const form = new FormData()
  form.append('audio', file)
  if (attendees && attendees.length > 0) {
    form.append('attendees', JSON.stringify(attendees))
  }
  const res = await fetch(`${base}/jobs`, {
    method: 'POST',
    body: form,
    headers: authHeaders(),
  })
  if (res.status === 401) {
    promptApiKey()
    return submitJob(file, attendees) // retry with new key
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`)
  const data = JobCreatedSchema.parse(await res.json())
  return data.job_id
}
