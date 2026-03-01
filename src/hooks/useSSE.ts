import { useEffect, useRef } from 'react'
import { useStore } from '../store/appStore'
import {
  TranscriptCompleteSchema,
  DiarizationCompleteSchema,
  AcousticMatchesCompleteSchema,
  SegmentsResolvedSchema,
  AnalysisCompleteSchema,
  ToolCallSchema,
  ToolResultSchema,
  SpeakerResolvedSchema,
  getApiKey,
  authHeaders,
} from '../api/client'
import { getBackend } from '../api/backend'

/**
 * Connects to GET /api/jobs/:id/events via SSE.
 * Falls back to polling every 500ms if EventSource is unavailable.
 */
export function useSSE(jobId: string | null) {
  const esRef = useRef<EventSource | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const setPhase = useStore((s) => s.setPhase)
  const setTranscript = useStore((s) => s.setTranscript)
  const appendTranscript = useStore((s) => s.appendTranscript)
  const setWords = useStore((s) => s.setWords)
  const setLanguage = useStore((s) => s.setLanguage)
  const setSegments = useStore((s) => s.setSegments)
  const setAcousticMatches = useStore((s) => s.setAcousticMatches)
  const setDecisions = useStore((s) => s.setDecisions)
  const setAmbiguities = useStore((s) => s.setAmbiguities)
  const setActionItems = useStore((s) => s.setActionItems)
  const setMeetingDynamics = useStore((s) => s.setMeetingDynamics)
  const addToolCall = useStore((s) => s.addToolCall)
  const updateLastToolResult = useStore((s) => s.updateLastToolResult)
  const addSpeakerResolution = useStore((s) => s.addSpeakerResolution)
  const setStage = useStore((s) => s.setStage)
  const setJobId = useStore((s) => s.setJobId)
  const setPipelineError = useStore((s) => s.setPipelineError)

  function clearPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  function applyCompleteResult(data: any) {
    if (data.transcript) setTranscript(data.transcript)
    if (data.segments) setSegments(data.segments)
    if (data.decisions) setDecisions(data.decisions)
    if (data.ambiguities) setAmbiguities(data.ambiguities)
    if (data.action_items) setActionItems(data.action_items)
    if (data.meeting_dynamics) setMeetingDynamics(data.meeting_dynamics)
    setPipelineError(null)
    setStage('results')
    setPhase(null)
  }

  function applyPartialResult(data: any) {
    if (typeof data.transcript === 'string') setTranscript(data.transcript)
    if (Array.isArray(data.segments)) setSegments(data.segments)
    if (Array.isArray(data.decisions)) setDecisions(data.decisions)
    if (Array.isArray(data.ambiguities)) setAmbiguities(data.ambiguities)
    if (Array.isArray(data.action_items)) setActionItems(data.action_items)
    if (data.meeting_dynamics) setMeetingDynamics(data.meeting_dynamics)
    if (typeof data.phase === 'string') setPhase(data.phase)
  }

  function applyErrorResult(data: any) {
    const errorMessage = typeof data.error === 'string' && data.error.trim().length > 0
      ? data.error
      : 'Meeting processing failed'
    setPipelineError(errorMessage)
    setStage('idle')
    setPhase(null)
    setJobId(null)
  }

  function startPolling(id: string, base: string) {
    clearPolling()
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${base}/jobs/${id}/result`, {
          headers: authHeaders(),
        })
        if (!res.ok) return
        const data = await res.json()

        if (data.status === 'processing') {
          applyPartialResult(data)
          return
        }

        if (data.status === 'complete') {
          clearPolling()
          applyCompleteResult(data)
          return
        }

        if (data.status === 'error') {
          clearPolling()
          applyErrorResult(data)
          return
        }
      } catch {
        // transient - keep polling
      }
    }, 500)
  }

  async function finalizeFromResult(id: string, base: string) {
    try {
      const res = await fetch(`${base}/jobs/${id}/result`, {
        headers: authHeaders(),
      })
      if (!res.ok) {
        applyErrorResult({ error: `Failed to load job result (HTTP ${res.status})` })
        return
      }
      const data = await res.json()
      if (data.status === 'processing') {
        applyPartialResult(data)
      }
      if (data.status === 'complete') {
        applyCompleteResult(data)
        return
      }
      if (data.status === 'error') {
        applyErrorResult(data)
        return
      }
      startPolling(id, base)
    } catch {
      startPolling(id, base)
    }
  }

  useEffect(() => {
    if (!jobId) return

    const currentJobId = jobId
    let cancelled = false
    setPipelineError(null)

    async function connect() {
      const base = await getBackend()
      if (cancelled) return

      const token = getApiKey()
      const query = token ? `?token=${encodeURIComponent(token)}` : ''
      const es = new EventSource(`${base}/jobs/${currentJobId}/events${query}`)
      esRef.current = es

      es.addEventListener('phase_start', (e) => {
        const { phase } = JSON.parse(e.data)
        setPhase(phase)
      })

      es.addEventListener('transcript_token', (e) => {
        const data = JSON.parse(e.data)
        appendTranscript(data.token)
      })

      es.addEventListener('transcript_complete', (e) => {
        const data = TranscriptCompleteSchema.parse(JSON.parse(e.data))
        setTranscript(data.text)
        setWords(data.words)
        if (data.language) setLanguage(data.language)
      })

      es.addEventListener('diarization_complete', (e) => {
        const data = DiarizationCompleteSchema.parse(JSON.parse(e.data))
        setSegments(data.segments)
      })

      es.addEventListener('acoustic_matches_complete', (e) => {
        const data = AcousticMatchesCompleteSchema.parse(JSON.parse(e.data))
        setAcousticMatches(data.matches)
      })

      es.addEventListener('segments_resolved', (e) => {
        const data = SegmentsResolvedSchema.parse(JSON.parse(e.data))
        setSegments(data.segments)
      })

      es.addEventListener('tool_call', (e) => {
        const data = ToolCallSchema.parse(JSON.parse(e.data))
        addToolCall(data)
      })

      es.addEventListener('tool_result', (e) => {
        const data = ToolResultSchema.parse(JSON.parse(e.data))
        updateLastToolResult(data.tool, data.result)
      })

      es.addEventListener('speaker_resolved', (e) => {
        const data = SpeakerResolvedSchema.parse(JSON.parse(e.data))
        addSpeakerResolution(data)
      })

      es.addEventListener('analysis_complete', (e) => {
        const data = AnalysisCompleteSchema.parse(JSON.parse(e.data))
        setDecisions(data.decisions)
        setAmbiguities(data.ambiguities)
        setActionItems(data.action_items)
        if (data.meeting_dynamics) setMeetingDynamics(data.meeting_dynamics)
      })

      es.addEventListener('done', () => {
        es.close()
        clearPolling()
        void finalizeFromResult(currentJobId, base)
      })

      es.onerror = () => {
        es.close()
        clearPolling()
        startPolling(currentJobId, base)
      }
    }

    connect()

    return () => {
      cancelled = true
      esRef.current?.close()
      clearPolling()
    }
  }, [
    jobId,
    setPhase,
    setTranscript,
    appendTranscript,
    setWords,
    setLanguage,
    setSegments,
    setAcousticMatches,
    setDecisions,
    setAmbiguities,
    setActionItems,
    setMeetingDynamics,
    addToolCall,
    updateLastToolResult,
    addSpeakerResolution,
    setStage,
    setJobId,
    setPipelineError,
  ])
}
