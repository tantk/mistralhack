import { useStore } from '../store/appStore'
import GlassCard from './ui/GlassCard'
import Icon from './ui/Icon'
import type { Decision } from '../api/client'

function fmt(s: number) {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
}

const STATUS_STYLE: Record<Decision['status'], string> = {
  locked: 'text-accent border-accent/30 bg-accent/10',
  open: 'text-warning border-warning/30 bg-warning/10',
  contested: 'text-danger border-danger/30 bg-danger/10',
}

export default function Ledger() {
  const { decisions, actionItems } = useStore()

  return (
    <div className="p-7 max-w-3xl font-mono">
      <h2 className="font-display text-xs uppercase tracking-widest text-slate-500 font-semibold">
        Decision Log
      </h2>
      <div className="h-px bg-accent/10 mt-2.5 mb-5" />

      {decisions.length === 0 && (
        <p className="text-slate-600 text-sm">No decisions detected.</p>
      )}

      {decisions.map((d, i) => (
        <GlassCard key={i} className="p-5 mb-3" borderAccent="cyan">
          <div className="flex gap-4 items-baseline">
            <span className="text-xs text-slate-500 flex-shrink-0 font-mono">{fmt(d.timestamp)}</span>
            <span className="text-sm font-medium text-slate-200">{d.summary}</span>
          </div>

          <div className="mt-3 ml-[72px] space-y-1">
            {d.proposed_by && (
              <div className="flex gap-2 text-xs">
                <span className="text-slate-600 w-16">proposed</span>
                <span className="text-slate-400">{d.proposed_by}</span>
              </div>
            )}
            {d.seconded_by && (
              <div className="flex gap-2 text-xs">
                <span className="text-slate-600 w-16">seconded</span>
                <span className="text-slate-400">{d.seconded_by}</span>
              </div>
            )}
            {d.dissent_by && (
              <div className="flex gap-2 text-xs">
                <span className="text-slate-600 w-16">dissent</span>
                <span className="text-danger">{d.dissent_by}</span>
              </div>
            )}
            <div className="flex gap-2 text-xs items-center">
              <span className="text-slate-600 w-16">status</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold tracking-widest uppercase border ${STATUS_STYLE[d.status]}`}>
                {d.status}
              </span>
            </div>
          </div>
        </GlassCard>
      ))}

      {actionItems.length > 0 && (
        <>
          <h2 className="font-display text-xs uppercase tracking-widest text-slate-500 font-semibold mt-8">
            Action Items
          </h2>
          <div className="h-px bg-accent/10 mt-2.5 mb-5" />

          <div className="space-y-3">
            {actionItems.map((item, i) => (
              <GlassCard key={i} className="p-5" borderAccent="yellow">
                <div className="flex items-center gap-2 mb-2">
                  <Icon name="task_alt" size={16} className="text-warning" />
                  <span className="font-display text-sm font-semibold text-slate-300">{item.owner}</span>
                </div>
                <p className="text-sm text-slate-300">{item.task}</p>
                {item.deadline_mentioned && (
                  <div className="flex gap-2 text-xs mt-2">
                    <span className="text-slate-600">deadline</span>
                    <span className="text-warning">{item.deadline_mentioned}</span>
                  </div>
                )}
                {item.verbatim_quote && (
                  <blockquote className="mt-3 border-l-2 border-accent bg-accent/5 px-3 py-2 text-xs text-slate-400 italic">
                    "{item.verbatim_quote}"
                  </blockquote>
                )}
              </GlassCard>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
