import { useStore } from '../store/appStore'
import type { Decision } from '../api/client'

function fmt(s: number) {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
}

const STATUS_CLASS: Record<Decision['status'], string> = {
  locked: 'status-locked',
  open: 'status-open',
  contested: 'status-contested',
}

export default function Ledger() {
  const { decisions, actionItems } = useStore()

  return (
    <div className="ledger-panel">
      <div className="ledger-section-header">DECISION LOG</div>
      <div className="ledger-divider" />

      {decisions.length === 0 && (
        <p className="ledger-empty">No decisions detected.</p>
      )}

      {decisions.map((d, i) => (
        <div key={i} className="ledger-entry">
          <div className="ledger-row">
            <span className="ledger-ts">{fmt(d.timestamp)}</span>
            <span className="ledger-summary">{d.summary}</span>
          </div>
          {d.proposed_by && (
            <div className="ledger-detail-row">
              <span className="ledger-key">proposed  </span>
              <span className="ledger-val">{d.proposed_by}</span>
            </div>
          )}
          {d.seconded_by && (
            <div className="ledger-detail-row">
              <span className="ledger-key">seconded  </span>
              <span className="ledger-val">{d.seconded_by}</span>
            </div>
          )}
          {d.dissent_by && (
            <div className="ledger-detail-row">
              <span className="ledger-key">dissent   </span>
              <span className="ledger-val ledger-dissent">{d.dissent_by}</span>
            </div>
          )}
          <div className="ledger-detail-row">
            <span className="ledger-key">status    </span>
            <span className={`ledger-status ${STATUS_CLASS[d.status]}`}>
              {d.status.toUpperCase()}
            </span>
          </div>
          <div className="ledger-divider-thin" />
        </div>
      ))}

      {actionItems.length > 0 && (
        <>
          <div className="ledger-section-header" style={{ marginTop: '2rem' }}>
            ACTION ITEMS
          </div>
          <div className="ledger-divider" />
          <ul className="action-list">
            {actionItems.map((item, i) => (
              <li key={i} className="action-item">
                <span className="action-bullet">▸</span>
                {item}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
