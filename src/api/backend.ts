const DEFAULT_HF_URL = 'https://mistral-hackaton-2026-meetingmind.hf.space'

const HF_SPACE_URL = import.meta.env.VITE_HF_SPACE_URL || DEFAULT_HF_URL

function isOnHfSpace(): boolean {
  return location.hostname.endsWith('.hf.space')
}

async function resolve(): Promise<string> {
  // Already running on HF Space — use same-origin
  if (isOnHfSpace()) {
    console.log('[backend] Running on HF Space, using /api')
    return '/api'
  }

  // Local dev: probe remote HF Space
  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 3000)
    const res = await fetch(`${HF_SPACE_URL}/api/health`, {
      signal: controller.signal,
    })
    clearTimeout(timeout)
    if (res.ok) {
      console.log(`[backend] Using remote: ${HF_SPACE_URL}/api`)
      return `${HF_SPACE_URL}/api`
    }
  } catch {
    // unreachable — fall through
  }

  console.log('[backend] HF Space unreachable, falling back to local /api')
  return '/api'
}

// Singleton promise — resolves once, all callers share it
const backendPromise: Promise<string> = resolve()

export function getBackend(): Promise<string> {
  return backendPromise
}
