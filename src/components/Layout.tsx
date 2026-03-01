import { useState, useEffect, type ReactNode } from 'react'
import { useStore } from '../store/appStore'
import Icon from './ui/Icon'

const NAV_LINKS = [
  { label: 'Dashboard', active: false },
  { label: 'Live Pipeline', active: true },
  { label: 'History', active: false },
  { label: 'Agents', active: false },
] as const

const PIPELINE_STEPS = [
  { id: 'transcribing', label: 'Transcribing', icon: 'mic' },
  { id: 'diarizing', label: 'Diarizing', icon: 'group' },
  { id: 'resolving', label: 'Resolving', icon: 'auto_fix_high' },
  { id: 'analyzing', label: 'Analyzing', icon: 'insights' },
] as const

type PhaseId = typeof PIPELINE_STEPS[number]['id']

const PHASE_ORDER: PhaseId[] = ['transcribing', 'diarizing', 'resolving', 'analyzing']

function normalizePhase(phase: string | null): PhaseId | null {
  if (phase === 'acoustic_matching') return 'diarizing'
  return phase as PhaseId | null
}

function PhaseLabel({ step, status }: { step: typeof PIPELINE_STEPS[number]; status: 'done' | 'active' | 'pending' }) {
  const labelColor = status === 'done' ? 'text-accent' : status === 'active' ? 'text-slate-100' : 'text-slate-500'
  const subColor = status === 'done' ? 'text-accent/60' : status === 'active' ? 'text-slate-500' : 'text-slate-600'
  const subText = status === 'done' ? 'Complete' : status === 'active' ? 'Processing...' : step.id === 'resolving' ? 'Pending' : 'Waiting'

  return (
    <div className="flex flex-col">
      <p className={`text-sm font-bold ${labelColor}`}>{step.label}</p>
      <p className={`text-xs ${subColor}`}>{subText}</p>
    </div>
  )
}

function useElapsed(running: boolean) {
  const [start] = useState(() => Date.now())
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [running])
  const s = Math.floor((now - start) / 1000)
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

function PipelineSidebar() {
  const phase = useStore((s) => s.phase)
  const displayPhase = normalizePhase(phase)
  const currentIndex = displayPhase ? PHASE_ORDER.indexOf(displayPhase) : -1

  const totalSteps = PIPELINE_STEPS.length
  const doneSteps = currentIndex >= 0 ? currentIndex : 0
  const progressPct = Math.round(((doneSteps + (currentIndex >= 0 ? 0.5 : 0)) / totalSteps) * 100)
  const currentStepNum = Math.min(doneSteps + 1, totalSteps)
  const currentStepLabel = displayPhase
    ? PIPELINE_STEPS.find((s) => s.id === displayPhase)?.label ?? ''
    : ''

  const elapsed = useElapsed(currentIndex >= 0)

  return (
    <aside className="w-72 border-r border-accent/10 bg-bg-primary p-6 flex flex-col gap-8 flex-shrink-0">
      {/* Pipeline Steps */}
      <div>
        <h3 className="text-xs font-bold uppercase tracking-widest text-accent mb-6">
          Processing Pipeline
        </h3>
        <div className="flex flex-col gap-0">
          {PIPELINE_STEPS.map((step, i) => {
            const status = i < currentIndex ? 'done' : i === currentIndex ? 'active' : 'pending'
            const isLast = i === totalSteps - 1

            return (
              <div key={step.id} className={`relative flex gap-4 ${isLast ? '' : 'pb-8'}`}>
                {/* Connector line */}
                {!isLast && (
                  <div
                    className={`absolute left-[15px] top-[32px] bottom-0 w-[2px] ${status === 'done'
                      ? 'bg-accent'
                      : status === 'active'
                        ? 'bg-accent/20 pipeline-shimmer'
                        : 'bg-slate-800'
                      }`}
                  />
                )}
                {/* Circle icon */}
                <div
                  className={`z-10 flex h-8 w-8 items-center justify-center rounded-full flex-shrink-0 ${status === 'done'
                    ? 'bg-accent text-bg-primary'
                    : status === 'active'
                      ? 'bg-accent/20 text-accent ring-2 ring-accent'
                      : 'bg-slate-800 text-slate-500'
                    }`}
                >
                  <Icon name={status === 'done' ? 'check' : step.icon} size={18} />
                </div>
                <PhaseLabel step={step} status={status} />
              </div>
            )
          })}
        </div>
      </div>

      {/* Progress indicator */}
      <div className="mt-auto p-4 rounded-xl bg-accent/5 border border-accent/10">
        <div className="flex justify-between items-center mb-1">
          <span className="text-xs font-medium text-slate-300">
            Step {currentStepNum} of {totalSteps}
          </span>
          <span className="text-xs font-bold text-accent">{progressPct}%</span>
        </div>
        {currentStepLabel && (
          <p className="text-[10px] text-slate-500 mb-2">{currentStepLabel}</p>
        )}
        <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden shadow-[inset_0_1px_2px_rgba(0,0,0,0.4)]">
          <div
            className="h-full rounded-full transition-all duration-700 ease-out bg-gradient-to-r from-accent/80 to-accent shadow-[0_0_8px_rgba(6,241,249,0.45)]"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <p className="text-[10px] text-slate-500 mt-3 flex items-center gap-1">
          <Icon name="schedule" size={12} className="text-accent" />
          Elapsed: {elapsed}
        </p>
      </div>
    </aside>
  )
}

export default function Layout({ children }: { children: ReactNode }) {
  const stage = useStore((s) => s.stage)

  // idle/uploading: full-page centered, no chrome
  if (stage === 'idle' || stage === 'uploading') {
    return (
      <div className="min-h-screen bg-bg-primary relative">
        {children}
      </div>
    )
  }

  // processing/results: header + sidebar + main
  return (
    <div className="min-h-screen bg-bg-primary flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between whitespace-nowrap border-b border-accent/20 px-6 py-3 bg-bg-primary flex-shrink-0">
        <div className="flex items-center gap-8">
          {/* Logo */}
          <div className="flex items-center gap-3 text-accent">
            <div className="w-6 h-6">
              <svg fill="currentColor" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
                <path d="M42.4379 44C42.4379 44 36.0744 33.9038 41.1692 24C46.8624 12.9336 42.2078 4 42.2078 4L7.01134 4C7.01134 4 11.6577 12.932 5.96912 23.9969C0.876273 33.9029 7.27094 44 7.27094 44L42.4379 44Z" />
              </svg>
            </div>
            <h2 className="text-slate-100 text-lg font-bold leading-tight tracking-tight">
              Make Meeting Analyses Great Again
            </h2>
          </div>
          {/* Search */}
          <label className="hidden md:flex flex-col min-w-40 h-10 max-w-64">
            <div className="flex w-full flex-1 items-stretch rounded-lg h-full overflow-hidden">
              <div className="text-accent flex border-none bg-accent/10 items-center justify-center pl-4 pr-2">
                <Icon name="search" size={20} />
              </div>
              <input
                className="flex w-full min-w-0 flex-1 border-none bg-accent/10 text-slate-100 focus:outline-none placeholder:text-slate-500 text-sm font-normal px-2"
                placeholder="Search sessions..."
              />
            </div>
          </label>
        </div>
        <div className="flex items-center gap-4">
          {/* Nav */}
          <nav className="hidden lg:flex items-center gap-6 mr-6">
            {NAV_LINKS.map((link) => (
              <a
                key={link.label}
                className={
                  link.active
                    ? 'text-accent text-sm font-medium border-b-2 border-accent pb-1'
                    : 'text-slate-400 hover:text-accent text-sm font-medium transition-colors cursor-pointer'
                }
                href="#"
              >
                {link.label}
              </a>
            ))}
          </nav>
          {/* Actions */}
          <div className="flex gap-2">
            <button className="flex items-center justify-center rounded-lg h-10 w-10 bg-accent/10 text-accent hover:bg-accent/20 transition-all">
              <Icon name="notifications" size={20} />
            </button>
            <div className="h-10 w-10 rounded-full border-2 border-accent p-0.5">
              <div className="h-full w-full rounded-full bg-bg-elevated flex items-center justify-center text-accent text-xs font-bold">
                U
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Body */}
      <main className="flex-1 flex overflow-hidden">
        {stage === 'processing' && <PipelineSidebar />}
        <section className="flex-1 flex flex-col overflow-hidden bg-bg-primary/50">
          {children}
        </section>
      </main>

      {/* Footer */}
      <footer className="h-12 border-t border-accent/10 bg-bg-primary px-6 flex items-center justify-between text-[11px] text-slate-500 font-medium flex-shrink-0">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            System Operational
          </span>
          <span className="flex items-center gap-1 border-l border-slate-800 pl-4">
            v2.4.1-stable
          </span>
        </div>
        <div className="flex items-center gap-6">
          <a className="hover:text-accent transition-colors" href="#">Privacy Policy</a>
          <a className="hover:text-accent transition-colors" href="#">API Status</a>
          <a className="hover:text-accent transition-colors" href="#">Support Center</a>
        </div>
      </footer>
    </div>
  )
}
