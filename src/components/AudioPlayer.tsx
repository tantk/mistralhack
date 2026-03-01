import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import { useStore } from '../store/appStore'
import Icon from './ui/Icon'

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

    if (wsRef.current) {
      wsRef.current.load(audioUrl)
      return
    }

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: 'rgba(6,241,249,0.25)',
      progressColor: '#06f1f9',
      cursorColor: '#06f1f9',
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
    <div className="card-surface rounded-none border-x-0 border-t-0 flex items-center gap-3 px-5 py-3">
      <button
        className="w-9 h-9 rounded-full border border-accent/40 flex items-center justify-center text-accent hover:bg-accent/10 hover:shadow-glow-cyan transition-all flex-shrink-0 cursor-pointer"
        onClick={() => wsRef.current?.playPause()}
        aria-label={playing ? 'Pause' : 'Play'}
      >
        <Icon name={playing ? 'pause' : 'play_arrow'} size={20} />
      </button>
      <div className="flex-1">
        <div ref={containerRef} />
      </div>
      <span className="font-mono text-[11px] text-slate-500 flex-shrink-0 whitespace-nowrap">
        {fmt(currentTime)} / {fmt(duration)}
      </span>
    </div>
  )
}
