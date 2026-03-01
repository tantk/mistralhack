import type { ReactNode } from 'react'
import { useStore } from '../store/appStore'
import Icon from './ui/Icon'

const NAV_ITEMS = [
  { icon: 'dashboard', label: 'Dashboard' },
  { icon: 'library_music', label: 'Library' },
  { icon: 'task_alt', label: 'Action Items' },
  { icon: 'gavel', label: 'Decisions' },
] as const

export default function Layout({ children }: { children: ReactNode }) {
  const stage = useStore((s) => s.stage)

  // idle/uploading: full-page centered, no sidebar
  if (stage === 'idle' || stage === 'uploading') {
    return (
      <div className="min-h-screen bg-void grid-bg relative">
        <div className="scanline-overlay" />
        {children}
      </div>
    )
  }

  // processing/results: sidebar + header + main
  return (
    <div className="min-h-screen bg-void grid-bg flex">
      {/* Sidebar */}
      <aside className="w-64 flex-shrink-0 glass-panel rounded-none border-t-0 border-b-0 border-l-0 flex flex-col">
        {/* Logo */}
        <div className="p-5 border-b border-glass-border flex items-center gap-3">
          <span className="neon-text-cyan text-xl">▶</span>
          <span className="font-hud font-bold text-base tracking-[0.15em] text-zinc-100 uppercase">
            MeetingMind
          </span>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 px-3 flex flex-col gap-1">
          {NAV_ITEMS.map((item, i) => (
            <button
              key={item.label}
              className={`flex items-center gap-3 px-3 py-2.5 rounded text-sm font-hud tracking-wide transition-colors cursor-default ${
                i === 0
                  ? 'text-neon-cyan bg-neon-cyan/5 border border-neon-cyan/20'
                  : 'text-zinc-500 hover:text-zinc-300 border border-transparent'
              }`}
            >
              <Icon name={item.icon} size={20} />
              {item.label}
            </button>
          ))}
        </nav>

        {/* Bottom section */}
        <div className="p-4 border-t border-glass-border">
          <div className="flex items-center gap-2 text-zinc-600 text-xs font-code">
            <Icon name="shield" size={16} />
            <span>Secure · On-Prem</span>
          </div>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-16 flex-shrink-0 glass-panel rounded-none border-t-0 border-r-0 border-l-0 flex items-center px-6 gap-4">
          <div className="flex-1">
            <span className="font-hud text-sm text-zinc-500 uppercase tracking-wider">
              {stage === 'processing' ? 'Processing Session' : 'Analysis Complete'}
            </span>
          </div>
          <button className="flex items-center gap-1.5 text-zinc-500 hover:text-zinc-300 transition-colors">
            <Icon name="search" size={20} />
          </button>
          <button className="flex items-center gap-1.5 text-zinc-500 hover:text-zinc-300 transition-colors relative">
            <Icon name="notifications" size={20} />
          </button>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-auto cyber-scrollbar">
          {children}
        </main>
      </div>
    </div>
  )
}
