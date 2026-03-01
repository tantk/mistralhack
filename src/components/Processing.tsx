import { motion, AnimatePresence } from 'framer-motion'
import { useStore } from '../store/appStore'
import { useSSE } from '../hooks/useSSE'
import GlassCard from './ui/GlassCard'
import Icon from './ui/Icon'

const PHASES = [
  { id: 'transcribing', label: 'VOXTRAL', sub: 'Speech → Text', icon: 'mic' },
  { id: 'diarizing', label: 'PYANNOTE + ERES2NET', sub: 'Speaker Separation', icon: 'group' },
  { id: 'resolving', label: 'MISTRAL AGENT', sub: 'Speaker Resolution', icon: 'smart_toy' },
  { id: 'analyzing', label: 'MISTRAL LARGE 3', sub: 'Decision Intelligence', icon: 'psychology' },
] as const

type PhaseId = typeof PHASES[number]['id']

const PHASE_ORDER: PhaseId[] = ['transcribing', 'diarizing', 'resolving', 'analyzing']

function normalizePhase(phase: string | null): PhaseId | null {
  if (phase === 'acoustic_matching') return 'diarizing'
  return phase as PhaseId | null
}

export default function Processing() {
  const { jobId, phase, transcript, toolCalls, speakerResolutions } = useStore()

  useSSE(jobId)

  const displayPhase = normalizePhase(phase)
  const currentIndex = displayPhase ? PHASE_ORDER.indexOf(displayPhase) : -1

  const recentToolCalls = toolCalls.slice(-5)

  return (
    <div className="flex flex-col gap-6 p-6 max-w-4xl mx-auto w-full">
      {/* Phase indicators */}
      <div className="grid grid-cols-4 gap-3">
        {PHASES.map((p, i) => {
          const status =
            i < currentIndex ? 'done' :
            i === currentIndex ? 'active' :
            'pending'

          return (
            <GlassCard
              key={p.id}
              className={`p-4 transition-all duration-300 ${
                status === 'active'
                  ? 'border-l-2 border-l-neon-cyan shadow-glow-cyan'
                  : status === 'done'
                    ? 'border-l-2 border-l-green-500'
                    : 'opacity-40'
              }`}
            >
              <AnimatePresence>
                {status === 'active' && (
                  <motion.div
                    className="absolute inset-0 bg-gradient-radial from-neon-cyan/5 to-transparent"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: [0.4, 0.8, 0.4] }}
                    transition={{ duration: 2, repeat: Infinity }}
                    exit={{ opacity: 0 }}
                  />
                )}
              </AnimatePresence>

              {/* Progress segments */}
              <div className="flex gap-0.5 mb-3 relative z-10">
                {Array.from({ length: 10 }).map((_, j) => (
                  <motion.div
                    key={j}
                    className={`h-1 flex-1 rounded-sm ${
                      status === 'done' ? 'bg-green-500' :
                      status === 'active' ? (j < 4 ? 'bg-neon-cyan' : 'bg-zinc-800') :
                      'bg-zinc-800'
                    }`}
                    animate={status === 'active' && j >= 4 ? {
                      opacity: [0.15, 0.4, 0.15],
                    } : {}}
                    transition={{ duration: 1.4, repeat: Infinity, delay: j * 0.12 }}
                  />
                ))}
              </div>

              <div className="relative z-10 flex items-center gap-2 mb-1">
                <Icon
                  name={status === 'done' ? 'check_circle' : p.icon}
                  size={16}
                  className={
                    status === 'done' ? 'text-green-500' :
                    status === 'active' ? 'text-neon-cyan' :
                    'text-zinc-600'
                  }
                />
                <p className="font-hud text-[10px] font-semibold tracking-[0.1em] text-zinc-200 uppercase">
                  {p.label}
                </p>
              </div>
              <p className="relative z-10 text-xs text-zinc-500 ml-7">{p.sub}</p>
            </GlassCard>
          )
        })}
      </div>

      {/* Live transcript */}
      <GlassCard className="flex-1 flex flex-col overflow-hidden">
        {/* Terminal chrome */}
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-glass-border bg-white/[0.02]">
          <span className="w-2.5 h-2.5 rounded-full bg-neon-magenta/70" />
          <span className="w-2.5 h-2.5 rounded-full bg-neon-yellow/70" />
          <span className="w-2.5 h-2.5 rounded-full bg-green-500/70" />
          <span className="font-code text-[11px] text-zinc-600 ml-2">transcript</span>
        </div>
        <div className="flex-1 p-5 overflow-y-auto min-h-[180px] max-h-[300px] cyber-scrollbar grid-bg">
          <span className="font-code text-sm leading-relaxed text-neon-cyan/90 whitespace-pre-wrap break-words">
            {transcript}
          </span>
          <span className="inline-block w-2 h-3.5 bg-neon-cyan ml-0.5 align-text-bottom animate-blink" />
        </div>
      </GlassCard>

      {/* Agent activity panel */}
      {phase === 'resolving' && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <GlassCard className="p-5" borderAccent="cyan">
            <div className="flex items-center gap-2 mb-4 relative z-10">
              <span className="w-2 h-2 rounded-full bg-neon-cyan animate-glow-pulse" />
              <span className="font-hud text-xs font-semibold tracking-[0.12em] text-neon-cyan uppercase">
                Agent Activity
              </span>
            </div>

            <div className="space-y-2 relative z-10">
              {recentToolCalls.length === 0 && (
                <p className="text-xs text-zinc-500 font-code">Agent is analyzing speakers...</p>
              )}
              {recentToolCalls.map((tc, i) => (
                <div key={i} className="flex flex-wrap gap-2 text-xs font-code">
                  <span className="text-neon-cyan font-semibold">{tc.tool}</span>
                  <span className="text-zinc-500 truncate max-w-[300px]">
                    {JSON.stringify(tc.args).slice(0, 80)}
                    {JSON.stringify(tc.args).length > 80 ? '...' : ''}
                  </span>
                  {tc.result && (
                    <span className="text-zinc-400 truncate max-w-[400px]">{tc.result.slice(0, 100)}</span>
                  )}
                </div>
              ))}
              {speakerResolutions.length > 0 && (
                <div className="mt-3 pt-3 border-t border-glass-border space-y-1">
                  {speakerResolutions.map((sr, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs font-code">
                      <span className="text-zinc-400">{sr.label}</span>
                      <Icon name="arrow_forward" size={14} className="text-neon-cyan" />
                      <span className="text-zinc-200">{sr.name}</span>
                      <span className="text-zinc-600">({(sr.confidence * 100).toFixed(0)}%)</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </GlassCard>
        </motion.div>
      )}

      <p className="text-xs text-zinc-600 text-center font-code">
        Pipeline running — this may take a few minutes for long recordings.
      </p>
    </div>
  )
}
