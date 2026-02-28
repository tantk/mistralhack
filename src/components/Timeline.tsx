import { useState } from 'react'
import { motion } from 'framer-motion'
import { useStore } from '../store/appStore'
import AudioPlayer from './AudioPlayer'
import type { Segment, Decision, Ambiguity } from '../api/client'

const SPEAKER_COLORS = ['#3b82f6', '#8b5cf6', '#06b6d4', '#f59e0b', '#ec4899']

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

  // Tick marks every ~5 min
  const tickInterval = total > 1800 ? 600 : total > 600 ? 300 : 60
  const ticks = Array.from(
    { length: Math.floor(total / tickInterval) + 1 },
    (_, i) => i * tickInterval
  )

  return (
    <div className="timeline-panel">
      <AudioPlayer seekTo={seekTo} />

      {/* Time axis */}
      <div className="time-axis">
        {ticks.map((t) => (
          <div
            key={t}
            className="time-tick"
            style={{ left: pct(t) }}
          >
            <span className="tick-label">{fmt(t)}</span>
          </div>
        ))}
        <div className="time-total">{fmt(total)}</div>
      </div>

      {/* Speaker lanes */}
      <div className="speaker-lanes">
        {speakers.map((spk) => {
          const color = speakerColor(spk, speakers)
          return (
            <div key={spk} className="lane-row">
              <div className="lane-label" style={{ color }}>
                {spk}
              </div>
              <div className="lane-track">
                {segsBySpk[spk].map((seg, i) => (
                  <motion.button
                    key={i}
                    className="lane-segment"
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

      {/* Decision + ambiguity markers overlay */}
      <div className="marker-layer">
        {decisions.map((d: Decision, i) => (
          <button
            key={i}
            className="marker marker-decision"
            style={{ left: pct(d.timestamp) }}
            title={d.summary}
            onClick={() => handleSegmentClick(d.timestamp)}
          >
            <span className="marker-label">{fmt(d.timestamp)} DECISION</span>
          </button>
        ))}
        {ambiguities.map((a: Ambiguity, i) => (
          <button
            key={i}
            className="marker marker-ambiguity"
            style={{ left: pct(a.timestamp) }}
            title={a.quote}
            onClick={() => handleSegmentClick(a.timestamp)}
          >
            <span className="marker-label">{fmt(a.timestamp)} AMBIGUOUS</span>
          </button>
        ))}
      </div>
    </div>
  )
}
