import { useEffect, useRef } from 'react'
import { useStore } from '../store/appStore'
import {
  TranscriptCompleteSchema,
  DiarizationCompleteSchema,
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

  const setPhase = useStore((s) => s.setPhase)
  const setTranscript = useStore((s) => s.setTranscript)
  const appendTranscript = useStore((s) => s.appendTranscript)
  const setWords = useStore((s) => s.setWords)
  const setLanguage = useStore((s) => s.setLanguage)
  const setSegments = useStore((s) => s.setSegments)
  const setDecisions = useStore((s) => s.setDecisions)
  const setAmbiguities = useStore((s) => s.setAmbiguities)
  const setActionItems = useStore((s) => s.setActionItems)
  const setMeetingDynamics = useStore((s) => s.setMeetingDynamics)
  const addToolCall = useStore((s) => s.addToolCall)
  const updateLastToolResult = useStore((s) => s.updateLastToolResult)
  const addSpeakerResolution = useStore((s) => s.addSpeakerResolution)
  const setStage = useStore((s) => s.setStage)

  useEffect(() => {
    if (!jobId) return

    let cancelled = false

    async function connect() {
      const base = await getBackend()
      if (cancelled) return

      const token = getApiKey()
      const query = token ? `?token=${encodeURIComponent(token)}` : ''
      const es = new EventSource(`${base}/jobs/${jobId}/events${query}`)
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
        setStage('results')
        setPhase(null)
      })

      es.onerror = () => {
        es.close()
        startPolling(jobId!, base)
      }
    }

    connect()

    return () => {
      cancelled = true
      esRef.current?.close()
    }
  }, [
    jobId, setPhase, setTranscript, appendTranscript, setWords, setLanguage, setSegments,
    setDecisions, setAmbiguities, setActionItems, setMeetingDynamics,
    addToolCall, updateLastToolResult, addSpeakerResolution, setStage,
  ])

  function startPolling(id: string, base: string) {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${base}/jobs/${id}/result`, {
          headers: authHeaders(),
        })
        if (!res.ok) return
        const data = await res.json()

        if (data.status === 'processing') {
          if (data.phase) setPhase(data.phase)
          return
        }

        if (data.status === 'complete') {
          clearInterval(interval)
          if (data.transcript) setTranscript(data.transcript)
          if (data.segments) setSegments(data.segments)
          if (data.decisions) setDecisions(data.decisions)
          if (data.ambiguities) setAmbiguities(data.ambiguities)
          if (data.action_items) setActionItems(data.action_items)
          if (data.meeting_dynamics) setMeetingDynamics(data.meeting_dynamics)
          setStage('results')
          setPhase(null)
        }
      } catch {
        // transient — keep polling
      }
    }, 500)
  }
}
