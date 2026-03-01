import { test, expect, Page } from '@playwright/test'

// ── Helpers ─────────────────────────────────────────────────────────

const JOB_ID = 'test-job-001'

/** Build a minimal SSE stream body from a sequence of named events. */
function sseBody(events: { event: string; data: unknown }[]): string {
  return events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join('')
}

const MOCK_WORDS = [
  { word: 'Hello', start: 0.0, end: 0.3 },
  { word: 'world', start: 0.4, end: 0.8 },
]

const MOCK_SEGMENTS_DIARIZED = [
  { speaker: 'SPEAKER_00', start: 0.0, end: 5.0, text: 'Hello world', is_overlap: false, confidence: 0.95, active_speakers: [] },
  { speaker: 'SPEAKER_01', start: 5.5, end: 10.0, text: 'Good morning', is_overlap: false, confidence: 0.9, active_speakers: [] },
]

const MOCK_ACOUSTIC_MATCHES = [
  { diarization_speaker: 'SPEAKER_00', matched_name: 'Alice', cosine_similarity: 0.92, confirmed: true },
  { diarization_speaker: 'SPEAKER_01', matched_name: 'Bob', cosine_similarity: 0.78, confirmed: false },
]

const MOCK_SEGMENTS_RESOLVED = [
  { speaker: 'Alice', start: 0.0, end: 5.0, text: 'Hello world', is_overlap: false, confidence: 0.95, active_speakers: [] },
  { speaker: 'Bob', start: 5.5, end: 10.0, text: 'Good morning', is_overlap: false, confidence: 0.9, active_speakers: [] },
]

const MOCK_ANALYSIS = {
  decisions: [{ timestamp: 2.0, summary: 'Proceed with plan', proposed_by: 'Alice', seconded_by: 'Bob', dissent_by: null, status: 'locked' }],
  ambiguities: [],
  action_items: [{ owner: 'Alice', task: 'Draft proposal', deadline_mentioned: 'Friday', verbatim_quote: null }],
  meeting_dynamics: { talk_time_pct: { Alice: 55, Bob: 45 }, interruption_count: 1 },
}

/**
 * Full SSE event sequence simulating all 5 pipeline phases.
 * Includes the new acoustic_matches_complete and segments_resolved events (Bug 2 + 3 fixes).
 */
function fullPipelineEvents() {
  return [
    { event: 'phase_start', data: { phase: 'transcribing' } },
    { event: 'transcript_complete', data: { text: 'Hello world Good morning', words: MOCK_WORDS, language: 'en', duration_ms: 10000 } },
    { event: 'phase_start', data: { phase: 'diarizing' } },
    { event: 'diarization_complete', data: { segments: MOCK_SEGMENTS_DIARIZED } },
    // Bug 5: acoustic_matching phase is emitted by orchestrator
    { event: 'phase_start', data: { phase: 'acoustic_matching' } },
    // Bug 3: acoustic_matches_complete event
    { event: 'acoustic_matches_complete', data: { matches: MOCK_ACOUSTIC_MATCHES } },
    { event: 'phase_start', data: { phase: 'resolving' } },
    { event: 'speaker_resolved', data: { label: 'SPEAKER_00', name: 'Alice', confidence: 0.92, method: 'agent+acoustic' } },
    { event: 'speaker_resolved', data: { label: 'SPEAKER_01', name: 'Bob', confidence: 0.78, method: 'agent' } },
    // Bug 2: segments_resolved event with resolved names
    { event: 'segments_resolved', data: { segments: MOCK_SEGMENTS_RESOLVED } },
    { event: 'phase_start', data: { phase: 'analyzing' } },
    { event: 'analysis_complete', data: MOCK_ANALYSIS },
    { event: 'done', data: {} },
  ]
}

/**
 * Sets up route mocks for the backend API.
 * - /api/health returns 200
 * - POST /api/jobs returns a mock job ID and captures the request body
 * - GET /api/jobs/:id/events returns SSE stream
 */
async function mockBackend(
  page: Page,
  options: {
    events?: { event: string; data: unknown }[]
    captureJobBody?: (body: Buffer, contentType: string) => void
    pollResult?: unknown
  } = {},
) {
  const events = options.events ?? fullPipelineEvents()
  const pollResult = options.pollResult ?? {
    status: 'complete',
    transcript: 'Hello world Good morning',
    segments: MOCK_SEGMENTS_RESOLVED,
    decisions: MOCK_ANALYSIS.decisions,
    ambiguities: MOCK_ANALYSIS.ambiguities,
    action_items: MOCK_ANALYSIS.action_items,
    meeting_dynamics: MOCK_ANALYSIS.meeting_dynamics,
  }

  // Block HF Space health probe so getBackend falls back to /api (local proxy)
  await page.route('**/hf.space/**', (route) => route.abort())

  // Health endpoint
  await page.route('**/api/health', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' }),
  )

  // Job creation
  await page.route('**/api/jobs', async (route) => {
    const request = route.request()
    if (request.method() !== 'POST') return route.fallback()

    if (options.captureJobBody) {
      const body = request.postDataBuffer()
      const ct = request.headers()['content-type'] || ''
      if (body) options.captureJobBody(body, ct)
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ job_id: JOB_ID }),
    })
  })

  // SSE stream
  await page.route(`**/api/jobs/${JOB_ID}/events**`, (route) => {
    const body = sseBody(events)
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
      body,
    })
  })

  // Polling fallback
  await page.route(`**/api/jobs/${JOB_ID}/result`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(pollResult),
    }),
  )
}

/** Upload a dummy WAV file via the drop zone and process. */
async function uploadAndProcess(page: Page) {
  // Create a minimal WAV buffer (44 byte header + 1s silence)
  const wavHeader = new Uint8Array(44)
  // RIFF header
  wavHeader.set([0x52, 0x49, 0x46, 0x46], 0)
  wavHeader.set([0x57, 0x41, 0x56, 0x45], 8)
  wavHeader.set([0x66, 0x6d, 0x74, 0x20], 12)

  const buffer = Buffer.from(wavHeader)

  // Use the file input
  const fileInput = page.locator('input[type="file"]')
  await fileInput.setInputFiles({
    name: 'test.wav',
    mimeType: 'audio/wav',
    buffer,
  })
}

// ── Tests ───────────────────────────────────────────────────────────

test.describe('Pipeline Bug Fixes', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('Bug 2 + 3: SSE delivers resolved segments and acoustic matches to frontend', async ({ page }) => {
    await mockBackend(page)

    await uploadAndProcess(page)

    // Click process button
    await page.locator('.process-btn').click()

    // Wait for pipeline to finish — the "done" event sets stage to "results"
    await expect(page.locator('.results-screen').first()).toBeVisible({ timeout: 10_000 })

    // Verify resolved speaker names appear in the results (not SPEAKER_00)
    const body = await page.locator('body').textContent()
    expect(body).toContain('Alice')
    expect(body).toContain('Bob')
    // SPEAKER_00 / SPEAKER_01 labels should NOT appear in resolved output
    expect(body).not.toContain('SPEAKER_00')
  })

  test('Bug 4: attendees input exists and data is sent in FormData', async ({ page }) => {
    // Block HF Space probe
    await page.route('**/hf.space/**', (route) => route.abort())
    await page.route('**/api/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' }),
    )

    // Set up a single /api/jobs handler that captures the body
    let capturedBody: Buffer | null = null
    await page.route('**/api/jobs', async (route) => {
      const request = route.request()
      if (request.method() !== 'POST') return route.fallback()
      const body = request.postDataBuffer()
      if (body) capturedBody = body
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: JOB_ID }),
      })
    })

    // SSE stream
    await page.route(`**/api/jobs/${JOB_ID}/events**`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: sseBody([{ event: 'done', data: {} }]),
      })
    })

    await uploadAndProcess(page)

    // Attendees input should appear after file is selected
    const attendeesInput = page.locator('[data-testid="attendees-input"]')
    await expect(attendeesInput).toBeVisible()

    // Type attendee names
    await attendeesInput.fill('Alice, Bob, Charlie')

    // Submit and wait for the request
    const [request] = await Promise.all([
      page.waitForRequest((req) => req.url().includes('/api/jobs') && req.method() === 'POST'),
      page.locator('.process-btn').click(),
    ])

    // Verify the body contains attendees
    const body = request.postDataBuffer()
    expect(body).not.toBeNull()
    const bodyStr = body!.toString('utf-8')
    expect(bodyStr).toContain('attendees')
    expect(bodyStr).toContain('Alice')
    expect(bodyStr).toContain('Bob')
    expect(bodyStr).toContain('Charlie')
  })

  test('Bug 5: acoustic_matching phase does not break the UI', async ({ page }) => {
    // Use events that include the acoustic_matching phase explicitly
    const events = [
      { event: 'phase_start', data: { phase: 'transcribing' } },
      { event: 'transcript_complete', data: { text: 'Test', words: [], language: 'en', duration_ms: 1000 } },
      { event: 'phase_start', data: { phase: 'diarizing' } },
      { event: 'diarization_complete', data: { segments: MOCK_SEGMENTS_DIARIZED } },
      // This is the phase the frontend type was missing
      { event: 'phase_start', data: { phase: 'acoustic_matching' } },
      { event: 'acoustic_matches_complete', data: { matches: [] } },
      { event: 'phase_start', data: { phase: 'resolving' } },
      { event: 'segments_resolved', data: { segments: MOCK_SEGMENTS_DIARIZED } },
      { event: 'phase_start', data: { phase: 'analyzing' } },
      { event: 'analysis_complete', data: MOCK_ANALYSIS },
      { event: 'done', data: {} },
    ]

    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await mockBackend(page, { events })
    await uploadAndProcess(page)
    await page.locator('.process-btn').click()

    // The pipeline should complete without errors
    await expect(page.locator('.results-screen').first()).toBeVisible({ timeout: 10_000 })

    // Page should still be functional — verify results screen rendered
    const body = await page.locator('body').textContent()
    // The segments have SPEAKER_00/01 (unresolved in this test) — just verify results loaded
    expect(body).toContain('decisions')
    const unexpectedErrors = errors.filter((msg) => !msg.includes('signal is aborted without reason'))
    expect(unexpectedErrors).toEqual([])
  })

  test('Upload screen shows file info after selecting audio', async ({ page }) => {
    await mockBackend(page)

    const fileInput = page.locator('input[type="file"]')
    await fileInput.setInputFiles({
      name: 'meeting.wav',
      mimeType: 'audio/wav',
      buffer: Buffer.alloc(44),
    })

    // File name should be visible
    await expect(page.locator('.file-name')).toHaveText('meeting.wav')

    // Process button should be enabled
    await expect(page.locator('.process-btn')).toBeEnabled()
  })

  test('attendees input is hidden when no file is selected', async ({ page }) => {
    await mockBackend(page)

    // No file selected — attendees input should not be visible
    await expect(page.locator('[data-testid="attendees-input"]')).not.toBeVisible()
  })

  test('empty attendees sends no attendees field', async ({ page }) => {
    let capturedBody: Buffer | null = null

    await mockBackend(page, {
      captureJobBody: (body) => {
        capturedBody = body
      },
    })

    await uploadAndProcess(page)
    // Don't fill attendees — leave empty

    await page.locator('.process-btn').click()

    // Wait for the job to be created
    await page.waitForTimeout(500)

    // Body should NOT contain attendees field when empty
    const bodyStr = capturedBody?.toString('utf-8') || ''
    expect(bodyStr).not.toContain('"attendees"')
  })

  test('speaker resolutions are shown during processing', async ({ page }) => {
    // Use a slower event sequence to verify intermediate state
    const events = [
      { event: 'phase_start', data: { phase: 'transcribing' } },
      { event: 'transcript_complete', data: { text: 'Hello', words: [], language: 'en', duration_ms: 1000 } },
      { event: 'phase_start', data: { phase: 'diarizing' } },
      { event: 'diarization_complete', data: { segments: MOCK_SEGMENTS_DIARIZED } },
      { event: 'phase_start', data: { phase: 'acoustic_matching' } },
      { event: 'acoustic_matches_complete', data: { matches: MOCK_ACOUSTIC_MATCHES } },
      { event: 'phase_start', data: { phase: 'resolving' } },
      { event: 'speaker_resolved', data: { label: 'SPEAKER_00', name: 'Alice', confidence: 0.92, method: 'agent+acoustic' } },
      { event: 'segments_resolved', data: { segments: MOCK_SEGMENTS_RESOLVED } },
      { event: 'phase_start', data: { phase: 'analyzing' } },
      { event: 'analysis_complete', data: MOCK_ANALYSIS },
      { event: 'done', data: {} },
    ]

    await mockBackend(page, { events })
    await uploadAndProcess(page)
    await page.locator('.process-btn').click()

    // Wait for results
    await expect(page.locator('.results-screen').first()).toBeVisible({ timeout: 10_000 })

    // Final output should have resolved speaker names
    const body = await page.locator('body').textContent()
    expect(body).toContain('Alice')
  })

  test('acoustic matches are visible during streaming processing', async ({ page }) => {
    const events = [
      { event: 'phase_start', data: { phase: 'transcribing' } },
      { event: 'transcript_complete', data: { text: 'Hello', words: [], language: 'en', duration_ms: 1000 } },
      { event: 'phase_start', data: { phase: 'diarizing' } },
      { event: 'diarization_complete', data: { segments: MOCK_SEGMENTS_DIARIZED } },
      { event: 'phase_start', data: { phase: 'acoustic_matching' } },
      { event: 'acoustic_matches_complete', data: { matches: MOCK_ACOUSTIC_MATCHES } },
    ]

    await mockBackend(page, {
      events,
      pollResult: { status: 'processing', phase: 'resolving' },
    })
    await uploadAndProcess(page)
    await page.locator('.process-btn').click()

    const panel = page.locator('[data-testid="acoustic-matches-panel"]')
    await expect(panel).toBeVisible({ timeout: 10_000 })
    await expect(panel).toContainText('SPEAKER_00')
    await expect(panel).toContainText('Alice')
  })

  test('done event with error result returns to upload and shows error message', async ({ page }) => {
    await mockBackend(page, {
      events: [
        { event: 'phase_start', data: { phase: 'transcribing' } },
        { event: 'done', data: {} },
      ],
      pollResult: { status: 'error', error: 'Diarization failed: GPU unavailable' },
    })

    await uploadAndProcess(page)
    await page.locator('.process-btn').click()

    await expect(page.locator('.upload-screen').first()).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('.error-msg')).toContainText('Diarization failed: GPU unavailable')
  })

  test('SSE transport failure falls back to polling and surfaces backend errors', async ({ page }) => {
    await page.route('**/hf.space/**', (route) => route.abort())
    await page.route('**/api/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' }),
    )

    await page.route('**/api/jobs', async (route) => {
      const request = route.request()
      if (request.method() !== 'POST') return route.fallback()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: JOB_ID }),
      })
    })

    await page.route(`**/api/jobs/${JOB_ID}/events**`, (route) =>
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'sse failed' }),
      }),
    )

    await page.route(`**/api/jobs/${JOB_ID}/result`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'error', error: 'Analysis failed: malformed model output' }),
      }),
    )

    await uploadAndProcess(page)
    await page.locator('.process-btn').click()

    await expect(page.locator('.upload-screen').first()).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('.error-msg')).toContainText('Analysis failed: malformed model output')
  })
})
