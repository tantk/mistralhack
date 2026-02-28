import { create } from 'zustand'
import type { Segment, Decision, Ambiguity } from '../api/client'

export type Phase = 'transcribing' | 'diarizing' | 'analyzing'
export type Stage = 'idle' | 'uploading' | 'processing' | 'results'
export type ResultTab = 'timeline' | 'ledger' | 'clarifications'

interface AppState {
  stage: Stage
  phase: Phase | null
  jobId: string | null
  uploadProgress: number

  transcript: string
  revealedWordCount: number
  audioDuration: number

  segments: Segment[]
  decisions: Decision[]
  ambiguities: Ambiguity[]
  actionItems: string[]

  activeAmbiguityIndex: number
  resolvedAmbiguities: Record<number, string | 'skipped'>

  audioUrl: string | null
  activeTab: ResultTab

  // actions
  setStage: (s: Stage) => void
  setPhase: (p: Phase | null) => void
  setJobId: (id: string) => void
  setUploadProgress: (p: number) => void
  setTranscript: (t: string) => void
  setRevealedWordCount: (n: number) => void
  setAudioDuration: (d: number) => void
  setSegments: (s: Segment[]) => void
  setDecisions: (d: Decision[]) => void
  setAmbiguities: (a: Ambiguity[]) => void
  setActionItems: (a: string[]) => void
  setAudioUrl: (u: string | null) => void
  setActiveTab: (t: ResultTab) => void
  resolveAmbiguity: (idx: number, resolution: string | 'skipped') => void
  advanceAmbiguity: () => void
  reset: () => void
}

const initial = {
  stage: 'idle' as Stage,
  phase: null as Phase | null,
  jobId: null as string | null,
  uploadProgress: 0,
  transcript: '',
  revealedWordCount: 0,
  audioDuration: 0,
  segments: [] as Segment[],
  decisions: [] as Decision[],
  ambiguities: [] as Ambiguity[],
  actionItems: [] as string[],
  activeAmbiguityIndex: 0,
  resolvedAmbiguities: {} as Record<number, string | 'skipped'>,
  audioUrl: null as string | null,
  activeTab: 'timeline' as ResultTab,
}

export const useStore = create<AppState>((set) => ({
  ...initial,
  setStage: (stage) => set({ stage }),
  setPhase: (phase) => set({ phase }),
  setJobId: (jobId) => set({ jobId }),
  setUploadProgress: (uploadProgress) => set({ uploadProgress }),
  setTranscript: (transcript) => set({ transcript }),
  setRevealedWordCount: (revealedWordCount) => set({ revealedWordCount }),
  setAudioDuration: (audioDuration) => set({ audioDuration }),
  setSegments: (segments) => set({ segments }),
  setDecisions: (decisions) => set({ decisions }),
  setAmbiguities: (ambiguities) => set({ ambiguities }),
  setActionItems: (actionItems) => set({ actionItems }),
  setAudioUrl: (audioUrl) => set({ audioUrl }),
  setActiveTab: (activeTab) => set({ activeTab }),
  resolveAmbiguity: (idx, resolution) =>
    set((s) => ({
      resolvedAmbiguities: { ...s.resolvedAmbiguities, [idx]: resolution },
    })),
  advanceAmbiguity: () =>
    set((s) => ({ activeAmbiguityIndex: s.activeAmbiguityIndex + 1 })),
  reset: () => set(initial),
}))
