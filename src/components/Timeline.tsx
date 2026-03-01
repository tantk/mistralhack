import { useState } from 'react'
import { motion } from 'framer-motion'
import { useStore } from '../store/appStore'
import AudioPlayer from './AudioPlayer'
import Icon from './ui/Icon'
import type { Segment, Decision, Ambiguity } from '../api/client'

const SPEAKER_COLORS = ['#06f1f9', '#FF003C', '#FFD600', '#8b5cf6', '#22c55e']

function speakerColor(name: string, allSpeakers: string[]): string {
  const idx = allSpeakers.indexOf(name)
  return SPEAKER_COLORS[idx % SPEAKER_COLORS.length]
}

function fmt(s: number) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

export default function Timeline() {
  const { segments, decisions, ambiguities, audioDuration } = useStore()
  const [seekTo, setSeekTo] = useState<number | undefined>()

  const total = audioDuration || (segments[segments.length - 1]?.end ?? 1)
  const speakers = [...new Set(segments.map((s) => s.speaker))].sort()

  const segsBySpk: Record<string, Segment[]> = {}
  for (const spk of speakers) {
    segsBySpk[spk] = segments.filter((s) => s.speaker === spk)
  }

  const pct = (t: number) => `${((t / total) * 100).toFixed(3)}%`

  const handleSegmentClick = (start: number) => setSeekTo(start)

  const tickInterval = total > 1800 ? 600 : total > 600 ? 300 : 60
  const ticks = Array.from(
    { length: Math.floor(total / tickInterval) + 1 },
    (_, i) => i * tickInterval
  )

  return (
    <div className="flex flex-col h-full">
      <AudioPlayer seekTo={seekTo} />

      {/* Time axis */}
      <div className="relative h-7 border-b border-accent/10 bg-bg-surface ml-[150px] mr-5">
        {ticks.map((t) => (
          <div
            key={t}
            className="absolute top-0 bottom-0 w-px bg-accent/10 -translate-x-1/2"
            style={{ left: pct(t) }}
          >
            <span className="absolute top-1.5 left-1 font-mono text-[10px] text-slate-600 whitespace-nowrap">
              {fmt(t)}
            </span>
          </div>
        ))}
        <div className="absolute right-1 top-1.5 font-mono text-[10px] text-slate-500">
          {fmt(total)}
        </div>
      </div>

      {/* Speaker lanes */}
      <div className="py-2 pr-5 flex flex-col gap-1">
        {speakers.map((spk) => {
          const color = speakerColor(spk, speakers)
          return (
            <div key={spk} className="flex items-center h-8">
              <div
                className="w-[150px] flex-shrink-0 font-display text-xs font-semibold tracking-wide pr-3 text-right whitespace-nowrap overflow-hidden text-ellipsis"
                style={{ color }}
              >
                {spk}
              </div>
              <div className="flex-1 relative h-6 bg-white/[0.02] rounded-sm">
                {segsBySpk[spk].map((seg, i) => (
                  <motion.button
                    key={i}
                    className="absolute top-0 h-full rounded-sm opacity-85 hover:opacity-100 hover:z-10 transition-opacity cursor-pointer"
                    style={{
                      left: pct(seg.start),
                      width: `calc(${pct(seg.end - seg.start)} - 1px)`,
                      background: color,
                    }}
                    title={`${seg.speaker}: ${seg.text} [${fmt(seg.start)}]`}
                    onClick={() => handleSegmentClick(seg.start)}
                    initial={{ scaleY: 0 }}
                    animate={{ scaleY: 1 }}
                    transition={{ duration: 0.15, delay: i * 0.005 }}
                  />
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {/* Decision + ambiguity markers */}
      <div className="relative h-7 ml-[150px] mr-5 mt-1 overflow-visible">
        {decisions.map((d: Decision, i) => (
          <button
            key={`d${i}`}
            className="absolute top-0 -translate-x-1/2 font-mono text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap cursor-pointer transition-opacity hover:opacity-80 bg-warning/15 text-warning border border-warning/30"
            style={{ left: pct(d.timestamp) }}
            title={d.summary}
            onClick={() => handleSegmentClick(d.timestamp)}
          >
            <span className="flex items-center gap-1">
              <Icon name="gavel" size={12} />
              {fmt(d.timestamp)}
            </span>
          </button>
        ))}
        {ambiguities.map((a: Ambiguity, i) => (
          <button
            key={`a${i}`}
            className="absolute top-0 -translate-x-1/2 font-mono text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap cursor-pointer transition-opacity hover:opacity-80 bg-danger/12 text-danger border border-danger/25 animate-glow-pulse"
            style={{ left: pct(a.timestamp) }}
            title={a.quote}
            onClick={() => handleSegmentClick(a.timestamp)}
          >
            <span className="flex items-center gap-1">
              <Icon name="help" size={12} />
              {fmt(a.timestamp)}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
