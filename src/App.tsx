import { AnimatePresence, motion } from 'framer-motion'
import { useStore } from './store/appStore'
import Upload from './components/Upload'
import Processing from './components/Processing'
import Results from './components/Results'

const PAGE_VARIANTS = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -12 },
}

export default function App() {
  const stage = useStore((s) => s.stage)

  return (
    <div className="app-root">
      <AnimatePresence mode="wait">
        {(stage === 'idle' || stage === 'uploading') && (
          <motion.div key="upload" {...PAGE_VARIANTS} transition={{ duration: 0.25 }}>
            <Upload />
          </motion.div>
        )}
        {stage === 'processing' && (
          <motion.div key="processing" {...PAGE_VARIANTS} transition={{ duration: 0.25 }}>
            <Processing />
          </motion.div>
        )}
        {stage === 'results' && (
          <motion.div key="results" {...PAGE_VARIANTS} transition={{ duration: 0.25 }}>
            <Results />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
