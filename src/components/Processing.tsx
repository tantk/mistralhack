import { motion, AnimatePresence } from 'framer-motion'
import { useStore } from '../store/appStore'
import { useSSE } from '../hooks/useSSE'

const PHASES = [
  { id: 'transcribing', label: 'VOXTRAL', sub: 'Speech -> Text' },
  { id: 'diarizing', label: 'PYANNOTE + ERES2NET', sub: 'Speaker Separation' },
  { id: 'resolving', label: 'MISTRAL AGENT', sub: 'Speaker Resolution' },
  { id: 'analyzing', label: 'MISTRAL LARGE 3', sub: 'Decision Intelligence' },
] as const

type PhaseId = typeof PHASES[number]['id']

const PHASE_ORDER: PhaseId[] = ['transcribing', 'diarizing', 'resolving', 'analyzing']

// acoustic_matching is a sub-phase of diarizing - map it so the UI stays on "diarizing"
function normalizePhase(phase: string | null): PhaseId | null {
  if (phase === 'acoustic_matching') return 'diarizing'
  return phase as PhaseId | null
}

export default function Processing() {
  const {
    jobId,
    phase,
    transcript,
    toolCalls,
    speakerResolutions,
    acousticMatches,
  } = useStore()

  // Connect SSE (or fallback poll) for this job
  useSSE(jobId)

  const displayPhase = normalizePhase(phase)
  const currentIndex = displayPhase ? PHASE_ORDER.indexOf(displayPhase) : -1

  // Show last 5 tool calls for agent activity panel
  const recentToolCalls = toolCalls.slice(-5)

  return (
    <div className="processing-screen">
      <header className="upload-header">
        <div className="logo-mark">&#9654;</div>
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

        {/* Agent activity panel - visible during resolving phase */}
        {phase === 'resolving' && (
          <motion.div
            className="agent-activity-panel"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="agent-activity-header">
              <span className="agent-pulse" />
              AGENT ACTIVITY
            </div>
            <div className="agent-activity-body">
              {recentToolCalls.length === 0 && (
                <p className="agent-waiting">Agent is analyzing speakers...</p>
              )}
              {recentToolCalls.map((tc, i) => (
                <div key={i} className="agent-tool-entry">
                  <span className="agent-tool-name">{tc.tool}</span>
                  <span className="agent-tool-args">
                    {JSON.stringify(tc.args).slice(0, 80)}
                    {JSON.stringify(tc.args).length > 80 ? '...' : ''}
                  </span>
                  {tc.result && (
                    <span className="agent-tool-result">{tc.result.slice(0, 100)}</span>
                  )}
                </div>
              ))}
              {speakerResolutions.length > 0 && (
                <div className="agent-resolutions">
                  {speakerResolutions.map((sr, i) => (
                    <div key={i} className="agent-resolution-entry">
                      <span className="resolution-arrow">
                        {sr.label} -&gt; {sr.name}
                      </span>
                      <span className="resolution-confidence">
                        ({(sr.confidence * 100).toFixed(0)}%)
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}

        {acousticMatches.length > 0 && (
          <div className="acoustic-panel" data-testid="acoustic-matches-panel">
            <p className="acoustic-title">ACOUSTIC MATCH CANDIDATES</p>
            <div className="acoustic-list">
              {acousticMatches.map((m, i) => (
                <div key={`${m.diarization_speaker}-${m.matched_name}-${i}`} className="acoustic-item">
                  <span className="acoustic-map">
                    {m.diarization_speaker} -&gt; {m.matched_name}
                  </span>
                  <span className={`acoustic-confidence ${m.confirmed ? 'acoustic-confirmed' : 'acoustic-tentative'}`}>
                    {(m.cosine_similarity * 100).toFixed(0)}% {m.confirmed ? 'confirmed' : 'tentative'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <p className="processing-hint">
          Pipeline running - this may take a few minutes for long recordings.
        </p>
      </main>
    </div>
  )
}
