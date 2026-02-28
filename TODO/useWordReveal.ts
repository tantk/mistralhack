import { useEffect, useRef } from 'react'
import { useStore } from '../store/appStore'

const WORDS_PER_SECOND = 8 // ~natural reading speed, faster than speech

/**
 * When transcript is set, reveals words via requestAnimationFrame.
 * Writes directly to a DOM ref to avoid per-word React re-renders.
 */
export function useWordReveal(containerRef: React.RefObject<HTMLElement>) {
  const transcript = useStore((s) => s.transcript)
  const setRevealedWordCount = useStore((s) => s.setRevealedWordCount)
  const rafRef = useRef<number>(0)
  const startTimeRef = useRef<number>(0)
  const lastReportedRef = useRef<number>(0)

  useEffect(() => {
    if (!transcript || !containerRef.current) return

    const words = transcript.split(/\s+/).filter(Boolean)

    cancelAnimationFrame(rafRef.current)
    containerRef.current.textContent = ''
    startTimeRef.current = performance.now()
    lastReportedRef.current = 0

    const tick = (now: number) => {
      const elapsed = (now - startTimeRef.current) / 1000
      const targetCount = Math.min(
        Math.floor(elapsed * WORDS_PER_SECOND),
        words.length
      )

      if (containerRef.current) {
        containerRef.current.textContent = words.slice(0, targetCount).join(' ')
      }

      // Only push to store every 20 words to avoid 60fps state updates
      if (targetCount - lastReportedRef.current >= 20 || targetCount === words.length) {
        lastReportedRef.current = targetCount
        setRevealedWordCount(targetCount)
      }

      if (targetCount < words.length) {
        rafRef.current = requestAnimationFrame(tick)
      }
    }

    rafRef.current = requestAnimationFrame(tick)

    return () => cancelAnimationFrame(rafRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcript])
}
