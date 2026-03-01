import { motion, AnimatePresence } from 'framer-motion'
import { useStore } from '../store/appStore'
import GlassCard from './ui/GlassCard'
import Button from './ui/Button'
import Icon from './ui/Icon'

function fmt(s: number) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
}

export default function Clarification() {
  const { ambiguities, resolvedAmbiguities, resolveAmbiguity, advanceAmbiguity } = useStore()

  const totalCount = ambiguities.length
  const doneCount = Object.keys(resolvedAmbiguities).length

  if (ambiguities.length === 0) {
    return (
      <div className="p-8 max-w-xl mx-auto">
        <p className="text-slate-600 text-sm font-mono">No ambiguities detected.</p>
      </div>
    )
  }

  if (doneCount >= totalCount) {
    return (
      <div className="p-8 max-w-xl mx-auto">
        <div className="flex flex-col items-center gap-3 py-12 font-mono text-slate-500">
          <Icon name="check_circle" size={40} className="text-success" />
          <p>All {totalCount} ambiguities resolved.</p>
        </div>
      </div>
    )
  }

  const idx = ambiguities.findIndex((_, i) => !resolvedAmbiguities[i])
  const amb = ambiguities[idx]

  const assign = (candidate: string) => {
    resolveAmbiguity(idx, candidate)
    advanceAmbiguity()
  }
  const skip = () => {
    resolveAmbiguity(idx, 'skipped')
    advanceAmbiguity()
  }

  return (
    <div className="p-8 max-w-xl mx-auto">
      {/* Progress */}
      <div className="flex items-center gap-4 mb-7">
        <span className="font-mono text-xs text-slate-500 flex-shrink-0">
          {doneCount + 1} of {totalCount}
        </span>
        <div className="flex-1 h-0.5 bg-slate-800 rounded overflow-hidden">
          <div
            className="h-full bg-accent rounded transition-all duration-400"
            style={{ width: `${((doneCount) / totalCount) * 100}%` }}
          />
        </div>
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={idx}
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -24 }}
          transition={{ duration: 0.2 }}
        >
          <GlassCard className="p-7 flex flex-col gap-5" borderAccent="magenta">
            {/* Meta row */}
            <div className="flex gap-2.5 items-center">
              <span className="font-mono text-[10px] tracking-widest bg-danger/12 text-danger border border-danger/25 px-2 py-0.5 rounded uppercase">
                Ambiguity
              </span>
              <span className="font-display text-xs text-slate-600 tracking-widest uppercase">
                {amb.type}
              </span>
            </div>

            {/* Detail grid */}
            <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono">
              <span className="text-xs text-slate-600 tracking-wide uppercase">Timestamp</span>
              <span className="text-xs text-slate-400">{fmt(amb.timestamp)}</span>
              <span className="text-xs text-slate-600 tracking-wide uppercase">Confidence</span>
              <span className="text-xs">
                <span
                  className="font-semibold"
                  style={{
                    color: amb.confidence < 0.6 ? '#FF003C' : amb.confidence < 0.8 ? '#FFD600' : '#22c55e',
                  }}
                >
                  {(amb.confidence * 100).toFixed(0)}%
                </span>
              </span>
            </div>

            {/* Quote */}
            <blockquote className="border-l-2 border-accent bg-accent/5 px-4 py-3.5 rounded-r font-mono text-sm text-slate-200 leading-relaxed flex flex-col gap-2">
              &ldquo;{amb.quote}&rdquo;
              <cite className="not-italic text-xs text-slate-600">— {amb.speaker}</cite>
            </blockquote>

            {/* Actions */}
            <div className="flex flex-wrap gap-2">
              {amb.candidates.map((c) => (
                <Button
                  key={c}
                  variant="secondary"
                  className="text-xs px-4 py-2"
                  onClick={() => assign(c)}
                >
                  Assign: {c}
                </Button>
              ))}
              <Button
                variant="ghost"
                className="text-xs px-3 py-2"
                onClick={skip}
              >
                Skip
              </Button>
            </div>
          </GlassCard>
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
