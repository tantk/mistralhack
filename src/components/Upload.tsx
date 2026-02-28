import { useCallback, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useStore } from '../store/appStore'
import { submitJob } from '../api/client'

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
  const inputRef = useRef<HTMLInputElement>(null)
  const store = useStore()

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
    if (!file) return
    store.setStage('uploading')
    try {
      const jobId = await submitJob(file)
      store.setJobId(jobId)
      store.setStage('processing')
      store.setPhase('transcribing')
    } catch (e) {
      store.setStage('idle')
      setError(e instanceof Error ? e.message : 'Upload failed')
    }
  }

  return (
    <div className="upload-screen">
      <header className="upload-header">
        <div className="logo-mark">▶</div>
        <span className="logo-text">MEETINGMIND</span>
      </header>

      <main className="upload-main">
        <div
          className={`drop-zone ${dragOver ? 'drag-over' : ''} ${file ? 'has-file' : ''}`}
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
                className="drop-content"
              >
                <div className="drop-icon">
                  <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
                    <path d="M20 8v16M12 16l8-8 8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    <path d="M6 28h28" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.4"/>
                    <path d="M6 32h28" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.2"/>
                  </svg>
                </div>
                <p className="drop-label">Drop audio or video file here</p>
                <p className="drop-sub">WAV · MP3 · MP4 · M4A</p>
              </motion.div>
            ) : (
              <motion.div
                key="file"
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                className="file-info"
              >
                <div className="file-icon">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                    <path d="M9 19V6l12-3v13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                    <circle cx="6" cy="19" r="3" stroke="currentColor" strokeWidth="1.5"/>
                    <circle cx="18" cy="16" r="3" stroke="currentColor" strokeWidth="1.5"/>
                  </svg>
                </div>
                <div className="file-meta">
                  <p className="file-name">{file.name}</p>
                  <p className="file-size">{formatBytes(file.size)}</p>
                </div>
                <button
                  className="file-remove"
                  onClick={(e) => { e.stopPropagation(); setFile(null); store.setAudioUrl(null) }}
                  aria-label="Remove file"
                >
                  ✕
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <AnimatePresence>
          {error && (
            <motion.p
              className="error-msg"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
            >
              {error}
            </motion.p>
          )}
        </AnimatePresence>

        <motion.button
          className="process-btn"
          disabled={!file}
          onClick={process}
          whileHover={{ scale: file ? 1.02 : 1 }}
          whileTap={{ scale: file ? 0.98 : 1 }}
        >
          PROCESS MEETING
        </motion.button>

        <p className="upload-footer-note">
          Audio stays on your server. Nothing leaves your infrastructure.
        </p>
      </main>
    </div>
  )
}
