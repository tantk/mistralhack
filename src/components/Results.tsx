import { motion } from 'framer-motion'
import { useStore } from '../store/appStore'
import Timeline from './Timeline'
import Ledger from './Ledger'
import Clarification from './Clarification'
import type { ResultTab } from '../store/appStore'

const TABS: { id: ResultTab; label: string }[] = [
  { id: 'timeline', label: 'TIMELINE' },
  { id: 'ledger', label: 'LEDGER' },
  { id: 'clarifications', label: 'CLARIFICATIONS' },
]

export default function Results() {
  const { activeTab, setActiveTab, decisions, ambiguities, resolvedAmbiguities, meetingDynamics, reset } = useStore()

  const pendingClarifs = ambiguities.filter((_, i) => !resolvedAmbiguities[i]).length

  return (
    <div className="results-screen">
      <header className="results-header">
        <div className="logo-mark-sm">▶</div>
        <span className="logo-text-sm">MEETINGMIND</span>
        <div className="results-stats">
          <span className="stat-chip">{decisions.length} decisions</span>
          <span className="stat-chip stat-chip-red">{ambiguities.length} ambiguities</span>
        </div>
        <button className="new-meeting-btn" onClick={reset}>
          ← New Meeting
        </button>
      </header>

      {/* Meeting Dynamics Bar */}
      {meetingDynamics && (
        <div className="dynamics-bar">
          <div className="dynamics-talk-time">
            {Object.entries(meetingDynamics.talk_time_pct)
              .sort(([, a], [, b]) => b - a)
              .map(([speaker, pct]) => (
                <div key={speaker} className="dynamics-speaker">
                  <span className="dynamics-speaker-name">{speaker}</span>
                  <div className="dynamics-bar-track">
                    <motion.div
                      className="dynamics-bar-fill"
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 0.6, ease: 'easeOut' }}
                    />
                  </div>
                  <span className="dynamics-pct">{pct.toFixed(1)}%</span>
                </div>
              ))}
          </div>
          {meetingDynamics.interruption_count > 0 && (
            <div className="dynamics-interruptions">
              <span className="dynamics-int-count">{meetingDynamics.interruption_count}</span>
              <span className="dynamics-int-label">interruptions</span>
            </div>
          )}
        </div>
      )}

      <nav className="tab-nav">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? 'tab-active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
            {tab.id === 'clarifications' && pendingClarifs > 0 && (
              <span className="tab-badge">{pendingClarifs}</span>
            )}
            {activeTab === tab.id && (
              <motion.div className="tab-underline" layoutId="tab-underline" />
            )}
          </button>
        ))}
      </nav>

      <div className="tab-content">
        {activeTab === 'timeline' && <Timeline />}
        {activeTab === 'ledger' && <Ledger />}
        {activeTab === 'clarifications' && <Clarification />}
      </div>
    </div>
  )
}
