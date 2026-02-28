import { z } from 'zod'

// ─── Zod schemas (validated at runtime boundaries) ──────────────────────────

export const SegmentSchema = z.object({
  speaker: z.string(),
  start: z.number(),
  end: z.number(),
  text: z.string(),
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

export const JobCreatedSchema = z.object({ job_id: z.string() })

export const TranscriptCompleteSchema = z.object({
  text: z.string(),
  duration_ms: z.number(),
})

export const DiarizationCompleteSchema = z.object({
  segments: z.array(SegmentSchema),
})

export const AnalysisCompleteSchema = z.object({
  decisions: z.array(DecisionSchema),
  ambiguities: z.array(AmbiguitySchema),
  action_items: z.array(z.string()),
})

// ─── Inferred types ──────────────────────────────────────────────────────────

export type Segment = z.infer<typeof SegmentSchema>
export type Decision = z.infer<typeof DecisionSchema>
export type Ambiguity = z.infer<typeof AmbiguitySchema>
export type AnalysisResult = z.infer<typeof AnalysisCompleteSchema>

// ─── API client ──────────────────────────────────────────────────────────────

const BASE = '/api'

export async function submitJob(file: File): Promise<string> {
  const form = new FormData()
  form.append('audio', file)
  const res = await fetch(`${BASE}/jobs`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`)
  const data = JobCreatedSchema.parse(await res.json())
  return data.job_id
}

