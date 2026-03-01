import { motion } from 'framer-motion'
import { useStore } from '../store/appStore'
import { useSSE } from '../hooks/useSSE'
import Icon from './ui/Icon'

/** Parse transcript into speaker-attributed segments for display */
function parseTranscriptBlocks(transcript: string) {
  // Try to parse "[Speaker]: text" lines
  const lines = transcript.split('\n').filter(Boolean)
  const blocks: { speaker: string; text: string; time?: string }[] = []

  for (const line of lines) {
    const match = line.match(/^\[?(Speaker\s*\d+|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\]?:\s*(.+)/i)
    if (match) {
      blocks.push({ speaker: match[1], text: match[2] })
    } else if (blocks.length > 0) {
      blocks[blocks.length - 1].text += ' ' + line
    } else {
      blocks.push({ speaker: 'Transcript', text: line })
    }
  }

  return blocks
}

function LiveTranscriptStream() {
  const transcript = useStore((s) => s.transcript)
  const blocks = transcript ? parseTranscriptBlocks(transcript) : []
  const hasContent = blocks.length > 0 || transcript.length > 0

  return (
    <div className="flex-1 card-surface flex flex-col overflow-hidden shadow-glow-cyan">
      {/* Header bar */}
      <div className="p-4 border-b border-accent/10 bg-accent/5 flex justify-between items-center">
        <h3 className="text-sm font-bold text-accent flex items-center gap-2">
          <Icon name="stream" size={18} />
          Live Transcript Stream
        </h3>
        <span className="text-[10px] px-2 py-0.5 rounded bg-accent/20 text-accent border border-accent/30 uppercase tracking-wider font-bold">
          Real-Time
        </span>
      </div>

      {/* Transcript content */}
      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar flex flex-col gap-4">
        {!hasContent && (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-sm text-slate-500">Waiting for transcript data...</p>
          </div>
        )}

        {blocks.length > 0 ? (
          blocks.map((block, i) => (
            <motion.div
              key={i}
              className="flex gap-4"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: i * 0.03 }}
            >
              <div className="w-10 h-10 rounded bg-slate-800 flex items-center justify-center text-xs font-bold text-slate-400 shrink-0">
                {block.speaker.slice(0, 2).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-bold text-slate-300">{block.speaker}</span>
                  {block.time && (
                    <span className="text-[10px] text-slate-500 font-mono">{block.time}</span>
                  )}
                </div>
                <p className="text-sm leading-relaxed text-slate-400">{block.text}</p>
              </div>
            </motion.div>
          ))
        ) : transcript ? (
          <div className="flex gap-4">
            <div className="w-10 h-10 rounded bg-accent/20 border border-accent/30 flex items-center justify-center shrink-0">
              <Icon name="mic" size={18} className="text-accent" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm leading-relaxed text-slate-300 whitespace-pre-wrap break-words">
                {transcript}
              </p>
              <span className="inline-block w-2 h-3.5 bg-accent ml-0.5 align-text-bottom animate-blink" />
            </div>
          </div>
        ) : null}

        {/* Audio capture indicator */}
        <div className="mt-auto pt-4 flex items-center gap-2 text-accent animate-pulse">
          <Icon name="keyboard_voice" size={16} />
          <span className="text-xs font-medium">Capturing audio stream...</span>
          <div className="flex gap-0.5 items-end h-3">
            {[1, 3, 2, 4].map((h, i) => (
              <div key={i} className="w-0.5 bg-accent" style={{ height: `${h * 3}px` }} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function LiveAgentActivity() {
  const { toolCalls, speakerResolutions, phase } = useStore()
  const recentToolCalls = toolCalls.slice(-8)

  return (
    <div className="flex flex-col h-full card-surface overflow-hidden shadow-glow-cyan">
      {/* Header */}
      <div className="p-4 border-b border-accent/10 bg-slate-900/50 flex items-center gap-2">
        <Icon name="smart_toy" size={20} className="text-accent" />
        <h3 className="text-sm font-bold text-slate-100">Live Agent Activity</h3>
      </div>

      {/* Activity cards */}
      <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-3">
        {/* Speaker Resolutions */}
        {speakerResolutions.map((sr, i) => (
          <motion.div
            key={`sr-${i}`}
            className="p-3 rounded-lg bg-accent/5 border border-accent/10 flex flex-col gap-2"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.2 }}
          >
            <div className="flex justify-between items-center">
              <span className="text-[10px] font-bold text-accent uppercase">Speaker Resolution</span>
              <span className="text-[10px] font-mono text-accent/60">
                {(sr.confidence * 100).toFixed(0)}% confidence
              </span>
            </div>
            <p className="text-xs text-slate-300">
              {sr.label} → <span className="text-slate-100 font-medium">{sr.name}</span>
            </p>
            <div className="flex items-center gap-3">
              <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-accent rounded-full transition-all duration-500"
                  style={{ width: `${sr.confidence * 100}%` }}
                />
              </div>
            </div>
          </motion.div>
        ))}

        {/* Tool calls as agent activities */}
        {recentToolCalls.map((tc, i) => {
          const isRecent = i >= recentToolCalls.length - 2
          return (
            <motion.div
              key={`tc-${i}`}
              className={`p-3 rounded-lg flex flex-col gap-2 ${isRecent
                ? 'bg-accent/5 border border-accent/10'
                : 'bg-slate-900 border border-slate-800'
                } ${!isRecent && i < recentToolCalls.length - 3 ? 'opacity-60' : ''}`}
              initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2 }}
            >
              <div className="flex justify-between items-center">
                <span className={`text-[10px] font-bold uppercase ${isRecent ? 'text-accent' : 'text-slate-400'}`}>
                  {tc.tool.replace(/_/g, ' ')}
                </span>
              </div>
              <p className={`text-xs ${isRecent ? 'text-slate-300' : 'text-slate-500'}`}>
                {JSON.stringify(tc.args).slice(0, 100)}
                {JSON.stringify(tc.args).length > 100 ? '...' : ''}
              </p>
              {tc.result && (
                <p className="text-xs text-slate-400 truncate">→ {tc.result.slice(0, 80)}</p>
              )}
              {isRecent && !tc.result && (
                <div className="flex gap-2">
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-accent/10 text-accent border border-accent/20">
                    Processing...
                  </span>
                </div>
              )}
            </motion.div>
          )
        })}

        {/* Empty state */}
        {recentToolCalls.length === 0 && speakerResolutions.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <Icon name="smart_toy" size={32} className="mb-3 opacity-30" />
            <p className="text-xs">
              {phase === 'resolving' ? 'Agent is analyzing speakers...' : 'Waiting for agent activity...'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Processing() {
  const { jobId } = useStore()

  useSSE(jobId)

  return (
    <div className="flex flex-col h-full">
      {/* Session header */}
      <div className="p-6 border-b border-accent/10 flex justify-between items-center bg-bg-primary">
        <div>
          <div className="flex items-center gap-3">
            <div className="h-2 w-2 rounded-full bg-accent animate-pulse" />
            <h1 className="text-xl font-bold tracking-tight text-slate-100">
              Live Processing Session
            </h1>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Session ID: <span className="text-slate-300 font-mono">{jobId?.slice(0, 12) ?? '—'}</span>
          </p>
        </div>
        <div className="flex gap-3">
          <button className="px-4 py-2 rounded-lg bg-slate-800 text-slate-200 text-sm font-bold flex items-center gap-2 hover:bg-slate-700 transition-all">
            <Icon name="pause" size={20} />
            Pause Session
          </button>
          <button className="px-4 py-2 rounded-lg bg-accent text-bg-primary text-sm font-bold flex items-center gap-2 hover:opacity-90 transition-all">
            <Icon name="stop" size={20} />
            Finish & Export
          </button>
        </div>
      </div>

      {/* Two-column content */}
      <div className="flex-1 grid grid-cols-12 gap-6 p-6 overflow-hidden">
        <div className="col-span-12 lg:col-span-7 flex flex-col overflow-hidden">
          <LiveTranscriptStream />
        </div>
        <div className="col-span-12 lg:col-span-5 flex flex-col overflow-hidden">
          <LiveAgentActivity />
        </div>
      </div>
    </div>
  )
}
