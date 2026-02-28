import { useEffect, useRef } from 'react'
import { useStore } from '../store/appStore'
import {
  TranscriptCompleteSchema,
  DiarizationCompleteSchema,
  AnalysisCompleteSchema,
} from '../api/client'

/**
 * Connects to GET /api/jobs/:id/events via SSE.
 * Falls back to polling every 500ms if EventSource is unavailable
 * (no backend SSE support yet) — the UI appearance is identical.
 */
export function useSSE(jobId: string | null) {
  const esRef = useRef<EventSource | null>(null)

  // Stable selectors — these never change identity, so this hook
  // won't re-run when unrelated store state changes.
  const setPhase = useStore((s) => s.setPhase)
  const setTranscript = useStore((s) => s.setTranscript)
  const setSegments = useStore((s) => s.setSegments)
  const setDecisions = useStore((s) => s.setDecisions)
  const setAmbiguities = useStore((s) => s.setAmbiguities)
  const setActionItems = useStore((s) => s.setActionItems)
  const setStage = useStore((s) => s.setStage)

  useEffect(() => {
    if (!jobId) return

    const es = new EventSource(`/api/jobs/${jobId}/events`)
    esRef.current = es

    es.addEventListener('phase_start', (e) => {
      const { phase } = JSON.parse(e.data)
      setPhase(phase)
    })

    es.addEventListener('transcript_complete', (e) => {
      const data = TranscriptCompleteSchema.parse(JSON.parse(e.data))
      setTranscript(data.text)
    })

    es.addEventListener('diarization_complete', (e) => {
      const data = DiarizationCompleteSchema.parse(JSON.parse(e.data))
      setSegments(data.segments)
    })

    es.addEventListener('analysis_complete', (e) => {
      const data = AnalysisCompleteSchema.parse(JSON.parse(e.data))
      setDecisions(data.decisions)
      setAmbiguities(data.ambiguities)
      setActionItems(data.action_items)
    })

    es.addEventListener('done', () => {
      es.close()
      setStage('results')
      setPhase(null)
    })

    es.onerror = () => {
      // SSE failed — start polling fallback
      es.close()
      startPolling(jobId)
    }

    return () => {
      es.close()
    }
  }, [jobId, setPhase, setTranscript, setSegments, setDecisions, setAmbiguities, setActionItems, setStage])

  function startPolling(id: string) {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${id}/result`)
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
          setStage('results')
          setPhase(null)
        }
      } catch {
        // transient — keep polling
      }
    }, 500)
  }
}
