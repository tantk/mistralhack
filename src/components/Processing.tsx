import { motion, AnimatePresence } from 'framer-motion'
import { useStore } from '../store/appStore'
import { useSSE } from '../hooks/useSSE'

const PHASES = [
  { id: 'transcribing', label: 'VOXTRAL', sub: 'Speech → Text' },
  { id: 'diarizing', label: 'PYANNOTE + ERES2NET', sub: 'Speaker Separation' },
  { id: 'analyzing', label: 'MISTRAL LARGE 3', sub: 'Decision Intelligence' },
] as const

type PhaseId = typeof PHASES[number]['id']

const PHASE_ORDER: PhaseId[] = ['transcribing', 'diarizing', 'analyzing']

export default function Processing() {
  const { jobId, phase, transcript } = useStore()

  // Connect SSE (or fallback poll) for this job
  useSSE(jobId)

  const currentIndex = phase ? PHASE_ORDER.indexOf(phase) : -1

  return (
    <div className="processing-screen">
      <header className="upload-header">
        <div className="logo-mark">▶</div>
        <span className="logo-text">MEETINGMIND</span>
      </header>

      <main className="processing-main">
        {/* Phase indicators */}
        <div className="phase-track">
          {PHASES.map((p, i) => {
            const status =
              i < currentIndex ? 'done' :
              i === currentIndex ? 'active' :
              'pending'

            return (
              <div key={p.id} className={`phase-box phase-${status}`}>
                <AnimatePresence>
                  {status === 'active' && (
                    <motion.div
                      className="phase-pulse"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                    />
                  )}
                </AnimatePresence>

                <div className="phase-bar-row">
                  {Array.from({ length: 10 }).map((_, j) => (
                    <motion.div
                      key={j}
                      className={`phase-bar-seg ${
                        status === 'done' ? 'seg-done' :
                        status === 'active' ? (j < 4 ? 'seg-fill' : 'seg-empty') :
                        'seg-empty'
                      }`}
                      animate={status === 'active' && j >= 4 ? {
                        opacity: [0.15, 0.4, 0.15],
                      } : {}}
                      transition={{ duration: 1.4, repeat: Infinity, delay: j * 0.12 }}
                    />
                  ))}
                </div>
                <p className="phase-label">{p.label}</p>
                <p className="phase-sub">{p.sub}</p>
              </div>
            )
          })}
        </div>

        {/* Live transcript output */}
        <div className="transcript-window">
          <div className="transcript-chrome">
            <span className="chrome-dot dot-red" />
            <span className="chrome-dot dot-amber" />
            <span className="chrome-dot dot-green" />
            <span className="chrome-title">transcript</span>
          </div>
          <div className="transcript-body">
            <span className="transcript-text">{transcript}</span>
            <span className="cursor-blink" />
          </div>
        </div>

        <p className="processing-hint">
          Pipeline running — this may take a few minutes for long recordings.
        </p>
      </main>
    </div>
  )
}
