import { motion, AnimatePresence } from 'framer-motion'
import { useStore } from '../store/appStore'

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
      <div className="clarification-panel">
        <p className="ledger-empty">No ambiguities detected.</p>
      </div>
    )
  }

  if (doneCount >= totalCount) {
    return (
      <div className="clarification-panel">
        <div className="clarif-done">
          <div className="clarif-done-icon">✓</div>
          <p>All {totalCount} ambiguities resolved.</p>
        </div>
      </div>
    )
  }

  // Find next unresolved index
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
    <div className="clarification-panel">
      <div className="clarif-header">
        <span className="clarif-progress">{doneCount + 1} of {totalCount}</span>
        <div className="clarif-progress-bar">
          <div
            className="clarif-progress-fill"
            style={{ width: `${((doneCount) / totalCount) * 100}%` }}
          />
        </div>
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={idx}
          className="clarif-card"
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -24 }}
          transition={{ duration: 0.2 }}
        >
          <div className="clarif-meta-row">
            <span className="clarif-badge">AMBIGUITY</span>
            <span className="clarif-type">{amb.type.toUpperCase()}</span>
          </div>

          <div className="clarif-detail-grid">
            <span className="clarif-key">TIMESTAMP</span>
            <span className="clarif-val">{fmt(amb.timestamp)}</span>
            <span className="clarif-key">CONFIDENCE</span>
            <span className="clarif-val">
              <span
                className="conf-badge"
                style={{
                  color: amb.confidence < 0.6 ? '#ef4444' : amb.confidence < 0.8 ? '#f59e0b' : '#22c55e',
                }}
              >
                {(amb.confidence * 100).toFixed(0)}%
              </span>
            </span>
          </div>

          <blockquote className="clarif-quote">
            &ldquo;{amb.quote}&rdquo;
            <cite className="clarif-cite">— {amb.speaker}</cite>
          </blockquote>

          <div className="clarif-actions">
            {amb.candidates.map((c) => (
              <button
                key={c}
                className="clarif-assign-btn"
                onClick={() => assign(c)}
              >
                ASSIGN: {c.toUpperCase()}
              </button>
            ))}
            <button className="clarif-skip-btn" onClick={skip}>
              SKIP
            </button>
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
