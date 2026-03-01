import { create } from 'zustand'
import type {
  Segment,
  Decision,
  Ambiguity,
  ActionItem,
  MeetingDynamics,
  Word,
  ToolCallEntry,
  SpeakerResolutionEntry,
  AcousticMatchEntry,
} from '../api/client'

export type Phase = 'transcribing' | 'diarizing' | 'acoustic_matching' | 'resolving' | 'analyzing'
export type Stage = 'idle' | 'uploading' | 'processing' | 'results'
export type ResultTab = 'timeline' | 'ledger' | 'clarifications'

interface ToolCallWithResult extends ToolCallEntry {
  result?: string
}

interface AppState {
  stage: Stage
  phase: Phase | null
  jobId: string | null
  pipelineError: string | null
  uploadProgress: number

  transcript: string
  revealedWordCount: number
  audioDuration: number
  words: Word[]
  language: string | null

  segments: Segment[]
  acousticMatches: AcousticMatchEntry[]
  decisions: Decision[]
  ambiguities: Ambiguity[]
  actionItems: ActionItem[]
  meetingDynamics: MeetingDynamics | null

  toolCalls: ToolCallWithResult[]
  speakerResolutions: SpeakerResolutionEntry[]

  activeAmbiguityIndex: number
  resolvedAmbiguities: Record<number, string | 'skipped'>

  audioUrl: string | null
  activeTab: ResultTab

  // actions
  setStage: (s: Stage) => void
  setPhase: (p: Phase | null) => void
  setJobId: (id: string | null) => void
  setPipelineError: (msg: string | null) => void
  setUploadProgress: (p: number) => void
  setTranscript: (t: string) => void
  appendTranscript: (token: string) => void
  setRevealedWordCount: (n: number) => void
  setAudioDuration: (d: number) => void
  setWords: (w: Word[]) => void
  setLanguage: (l: string | null) => void
  setSegments: (s: Segment[]) => void
  setAcousticMatches: (m: AcousticMatchEntry[]) => void
  setDecisions: (d: Decision[]) => void
  setAmbiguities: (a: Ambiguity[]) => void
  setActionItems: (a: ActionItem[]) => void
  setMeetingDynamics: (m: MeetingDynamics | null) => void
  addToolCall: (tc: ToolCallEntry) => void
  updateLastToolResult: (tool: string, result: string) => void
  addSpeakerResolution: (sr: SpeakerResolutionEntry) => void
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
  pipelineError: null as string | null,
  uploadProgress: 0,
  transcript: '',
  revealedWordCount: 0,
  audioDuration: 0,
  words: [] as Word[],
  language: null as string | null,
  segments: [] as Segment[],
  acousticMatches: [] as AcousticMatchEntry[],
  decisions: [] as Decision[],
  ambiguities: [] as Ambiguity[],
  actionItems: [] as ActionItem[],
  meetingDynamics: null as MeetingDynamics | null,
  toolCalls: [] as ToolCallWithResult[],
  speakerResolutions: [] as SpeakerResolutionEntry[],
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
  setPipelineError: (pipelineError) => set({ pipelineError }),
  setUploadProgress: (uploadProgress) => set({ uploadProgress }),
  setTranscript: (transcript) => set({ transcript }),
  appendTranscript: (token) => set((s) => ({ transcript: s.transcript + token })),
  setRevealedWordCount: (revealedWordCount) => set({ revealedWordCount }),
  setAudioDuration: (audioDuration) => set({ audioDuration }),
  setWords: (words) => set({ words }),
  setLanguage: (language) => set({ language }),
  setSegments: (segments) => set({ segments }),
  setAcousticMatches: (acousticMatches) => set({ acousticMatches }),
  setDecisions: (decisions) => set({ decisions }),
  setAmbiguities: (ambiguities) => set({ ambiguities }),
  setActionItems: (actionItems) => set({ actionItems }),
  setMeetingDynamics: (meetingDynamics) => set({ meetingDynamics }),
  addToolCall: (tc) =>
    set((s) => ({ toolCalls: [...s.toolCalls, tc] })),
  updateLastToolResult: (tool, result) =>
    set((s) => {
      const calls = [...s.toolCalls]
      for (let i = calls.length - 1; i >= 0; i--) {
        if (calls[i].tool === tool && !calls[i].result) {
          calls[i] = { ...calls[i], result }
          break
        }
      }
      return { toolCalls: calls }
    }),
  addSpeakerResolution: (sr) =>
    set((s) => ({ speakerResolutions: [...s.speakerResolutions, sr] })),
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
