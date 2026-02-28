import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import { useStore } from '../store/appStore'

interface Props {
  onSeek?: (time: number) => void
  seekTo?: number
}

export default function AudioPlayer({ onSeek, seekTo }: Props) {
  const audioUrl = useStore((s) => s.audioUrl)
  const setAudioDuration = useStore((s) => s.setAudioDuration)
  const containerRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WaveSurfer | null>(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)

  useEffect(() => {
    if (!containerRef.current || !audioUrl) return

    // Reuse instance if already created
    if (wsRef.current) {
      wsRef.current.load(audioUrl)
      return
    }

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: '#3f3f46',
      progressColor: '#f59e0b',
      cursorColor: '#f59e0b',
      barWidth: 2,
      barGap: 1,
      height: 48,
      normalize: true,
      interact: true,
    })

    ws.load(audioUrl)

    ws.on('ready', () => {
      const d = ws.getDuration()
      setDuration(d)
      setAudioDuration(d)
    })

    ws.on('timeupdate', (t) => setCurrentTime(t))
    ws.on('play', () => setPlaying(true))
    ws.on('pause', () => setPlaying(false))
    ws.on('seeking', (progress) => {
      onSeek?.(progress * ws.getDuration())
    })

    wsRef.current = ws

    return () => {
      ws.destroy()
      wsRef.current = null
    }
  }, [audioUrl])

  // External seek (from timeline click)
  useEffect(() => {
    if (seekTo !== undefined && wsRef.current && duration > 0) {
      wsRef.current.seekTo(seekTo / duration)
    }
  }, [seekTo, duration])

  const fmt = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = Math.floor(s % 60)
    return `${m}:${sec.toString().padStart(2, '0')}`
  }

  if (!audioUrl) return null

  return (
    <div className="audio-player">
      <button
        className="play-btn"
        onClick={() => wsRef.current?.playPause()}
        aria-label={playing ? 'Pause' : 'Play'}
      >
        {playing ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <rect x="3" y="2" width="4" height="12" rx="1" />
            <rect x="9" y="2" width="4" height="12" rx="1" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M4 2l10 6-10 6V2z" />
          </svg>
        )}
      </button>
      <div className="waveform-wrap">
        <div ref={containerRef} />
      </div>
      <span className="time-display">
        {fmt(currentTime)} / {fmt(duration)}
      </span>
    </div>
  )
}
