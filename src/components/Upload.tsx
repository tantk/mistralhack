import { useCallback, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useStore } from '../store/appStore'
import { submitJob } from '../api/client'
import Icon from './ui/Icon'
import Button from './ui/Button'

const ACCEPTED = ['audio/wav', 'audio/mpeg', 'audio/mp4', 'video/mp4', 'audio/x-m4a']
const ACCEPTED_EXT = ['.wav', '.mp3', '.mp4', '.m4a']

function formatBytes(b: number) {
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / (1024 * 1024)).toFixed(1)} MB`
}

export default function Upload() {
  const [dragOver, setDragOver] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attendeesStr, setAttendeesStr] = useState('')
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const store = useStore()
  const pipelineError = useStore((s) => s.pipelineError)

  const validate = (f: File) => {
    if (!ACCEPTED.includes(f.type) && !ACCEPTED_EXT.some(e => f.name.endsWith(e))) {
      setError('Unsupported format. Use WAV, MP3, or MP4.')
      return false
    }
    if (f.size > 500 * 1024 * 1024) {
      setError('File too large (max 500 MB).')
      return false
    }
    setError(null)
    return true
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f && validate(f)) {
      setFile(f)
      store.setAudioUrl(URL.createObjectURL(f))
    }
  }, [])

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f && validate(f)) {
      setFile(f)
      store.setAudioUrl(URL.createObjectURL(f))
    }
  }

  const process = async () => {
    if (!file || loading) return
    console.log('[Upload] process() called, file:', file.name, file.size)
    setLoading(true)
    setError(null)
    store.setPipelineError(null)
    store.setStage('uploading')
    try {
      const attendees = attendeesStr
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      console.log('[Upload] calling submitJob...')
      const jobId = await submitJob(file, attendees)
      console.log('[Upload] job created:', jobId)
      store.setJobId(jobId)
      store.setStage('processing')
      store.setPhase('transcribing')
    } catch (e) {
      console.error('[Upload] error:', e)
      store.setStage('idle')
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="upload-screen min-h-screen flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-lg flex flex-col items-center gap-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-8 h-8 text-accent">
            <svg fill="currentColor" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
              <path d="M42.4379 44C42.4379 44 36.0744 33.9038 41.1692 24C46.8624 12.9336 42.2078 4 42.2078 4L7.01134 4C7.01134 4 11.6577 12.932 5.96912 23.9969C0.876273 33.9029 7.27094 44 7.27094 44L42.4379 44Z" />
            </svg>
          </div>
          <span className="font-display font-bold text-xl tracking-tight text-slate-100">
            Make Meeting Analyses Great Again
          </span>
        </div>

        <div
          className={`w-full card-surface transition-all duration-200 cursor-pointer ${dragOver
              ? 'border-accent shadow-glow-cyan'
              : file
                ? 'cursor-default'
                : 'border-dashed hover:border-accent/40'
            } ${file ? 'p-5' : 'p-12'}`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => !file && inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && !file && inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_EXT.join(',')}
            onChange={onFileChange}
            style={{ display: 'none' }}
          />

          <AnimatePresence mode="wait">
            {!file ? (
              <motion.div
                key="empty"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="flex flex-col items-center gap-4"
              >
                <Icon name="cloud_upload" size={48} className="text-slate-600" />
                <p className="font-display text-sm text-slate-200">
                  Drop audio or video file here
                </p>
                <p className="text-xs tracking-widest text-slate-600 uppercase">
                  WAV  MP3  MP4  M4A
                </p>
              </motion.div>
            ) : (
              <motion.div
                key="file"
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center gap-4"
              >
                <Icon name="music_note" size={24} className="text-accent flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="font-mono text-sm text-slate-200 truncate">{file.name}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{formatBytes(file.size)}</p>
                </div>
                <button
                  className="text-slate-600 hover:text-danger transition-colors flex-shrink-0 cursor-pointer"
                  onClick={(e) => { e.stopPropagation(); setFile(null); store.setAudioUrl(null) }}
                  aria-label="Remove file"
                >
                  <Icon name="close" size={18} />
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <AnimatePresence>
          {(error || pipelineError) && (
            <motion.p
              className="font-mono text-xs text-danger text-center overflow-hidden"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
            >
              {error || pipelineError}
            </motion.p>
          )}
        </AnimatePresence>

        <Button
          variant="primary"
          className="process-btn w-full py-3.5 text-sm"
          disabled={!file || loading}
          onClick={process}
        >
          {loading ? 'UPLOADING...' : 'PROCESS MEETING'}
        </Button>

        {file && (
          <input
            type="text"
            className="w-full card-surface px-3 py-2.5 text-xs font-mono text-slate-200 placeholder:text-slate-600 outline-none border border-slate-800 focus:border-accent"
            placeholder="Attendees (comma-separated, optional)"
            value={attendeesStr}
            onChange={(e) => setAttendeesStr(e.target.value)}
            data-testid="attendees-input"
          />
        )}

        <p className="text-xs text-slate-600 text-center">
          Audio stays on your server. Nothing leaves your infrastructure.
        </p>
      </div>
    </div>
  )
}
