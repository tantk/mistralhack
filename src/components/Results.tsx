import { motion } from 'framer-motion'
import { useStore } from '../store/appStore'
import Timeline from './Timeline'
import Ledger from './Ledger'
import Clarification from './Clarification'
import Button from './ui/Button'
import Icon from './ui/Icon'
import type { ResultTab } from '../store/appStore'

const TABS: { id: ResultTab; label: string; icon: string }[] = [
  { id: 'timeline', label: 'TIMELINE', icon: 'timeline' },
  { id: 'ledger', label: 'LEDGER', icon: 'gavel' },
  { id: 'clarifications', label: 'CLARIFICATIONS', icon: 'help_center' },
]

export default function Results() {
  const { activeTab, setActiveTab, decisions, ambiguities, resolvedAmbiguities, meetingDynamics, reset } = useStore()

  const pendingClarifs = ambiguities.filter((_, i) => !resolvedAmbiguities[i]).length

  return (
    <div className="flex flex-col h-full">
      {/* Stats bar */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-accent/10">
        <div className="flex gap-2 flex-1">
          <span className="font-mono text-[11px] px-2.5 py-0.5 rounded border border-accent/30 bg-accent/10 text-accent">
            {decisions.length} decisions
          </span>
          <span className="font-mono text-[11px] px-2.5 py-0.5 rounded border border-danger/30 bg-danger/10 text-danger">
            {ambiguities.length} ambiguities
          </span>
        </div>
        <Button variant="ghost" className="text-xs px-3 py-1.5" onClick={reset}>
          <span className="flex items-center gap-1.5">
            <Icon name="arrow_back" size={14} />
            New Meeting
          </span>
        </Button>
      </div>

      {/* Meeting Dynamics Bar */}
      {meetingDynamics && (
        <div className="card-surface rounded-none border-x-0 border-t-0 px-6 py-4">
          <div className="space-y-2">
            {Object.entries(meetingDynamics.talk_time_pct)
              .sort(([, a], [, b]) => b - a)
              .map(([speaker, pct]) => (
                <div key={speaker} className="flex items-center gap-3 text-xs">
                  <span className="w-24 text-right font-display text-slate-400 truncate">{speaker}</span>
                  <div className="flex-1 h-1.5 bg-slate-800/50 rounded-full overflow-hidden">
                    <motion.div
                      className="h-full bg-accent rounded-full"
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 0.6, ease: 'easeOut' }}
                    />
                  </div>
                  <span className="w-12 text-right font-mono text-slate-500">{pct.toFixed(1)}%</span>
                </div>
              ))}
          </div>
          {meetingDynamics.interruption_count > 0 && (
            <div className="flex items-center gap-2 mt-3 pt-3 border-t border-accent/10">
              <span className="font-display text-lg font-bold text-danger">
                {meetingDynamics.interruption_count}
              </span>
              <span className="text-xs text-slate-500 font-display uppercase tracking-wider">
                interruptions
              </span>
            </div>
          )}
        </div>
      )}

      {/* Tabs */}
      <nav className="flex px-6 border-b border-accent/10 bg-bg-surface">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`relative px-5 py-3.5 font-display text-xs tracking-widest uppercase transition-colors flex items-center gap-2 cursor-pointer ${activeTab === tab.id ? 'text-slate-100' : 'text-slate-500 hover:text-slate-300'
              }`}
            onClick={() => setActiveTab(tab.id)}
          >
            <Icon name={tab.icon} size={16} />
            {tab.label}
            {tab.id === 'clarifications' && pendingClarifs > 0 && (
              <span className="text-[10px] bg-danger text-white rounded-full px-1.5 py-px font-mono">
                {pendingClarifs}
              </span>
            )}
            {activeTab === tab.id && (
              <motion.div
                className="absolute bottom-[-1px] left-0 right-0 h-0.5 bg-accent rounded-t"
                layoutId="tab-underline"
              />
            )}
          </button>
        ))}
      </nav>

      {/* Tab content */}
      <div className="flex-1 overflow-auto custom-scrollbar">
        {activeTab === 'timeline' && <Timeline />}
        {activeTab === 'ledger' && <Ledger />}
        {activeTab === 'clarifications' && <Clarification />}
      </div>
    </div>
  )
}
