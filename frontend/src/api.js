// Where the FastAPI backend lives. Set VITE_API_URL on Vercel; local default below.
export const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

// The free Render server sleeps after ~15 minutes idle and takes 30-60 s to wake.
// Until the first answer arrives, a slow request tells the app (it shows a banner),
// and a failed one (502/503/504 or no connection while waking) is retried.
const SLOW_AFTER_MS = 2500
const WAKE_RETRIES = 6
const RETRY_DELAY_MS = 5000

let serverAwake = false
let wakeListener = null

// The App registers one function: called with true (waking) or false (awake).
export function onWakeChange(listener) {
  wakeListener = listener
}

function setWaking(waking) {
  if (wakeListener) wakeListener(waking)
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function request(path, options) {
  let slowTimer = null
  if (!serverAwake) {
    slowTimer = setTimeout(() => setWaking(true), SLOW_AFTER_MS)
  }

  let response = null
  try {
    for (let attempt = 0; ; attempt++) {
      try {
        response = await fetch(API_BASE + path, options)
      } catch (networkError) {
        // No connection at all: while the server is waking, try again
        if (serverAwake || attempt >= WAKE_RETRIES) throw networkError
        setWaking(true)
        await wait(RETRY_DELAY_MS)
        continue
      }
      const wakingStatus = response.status === 502 || response.status === 503 || response.status === 504
      if (wakingStatus && !serverAwake && attempt < WAKE_RETRIES) {
        setWaking(true)
        await wait(RETRY_DELAY_MS)
        continue
      }
      break
    }
  } finally {
    if (slowTimer) clearTimeout(slowTimer)
  }

  if (!serverAwake) {
    // Any real answer (even a 400/404) means the server is up; a final 50x doesn't
    if (response.status < 502 || response.status > 504) serverAwake = true
    setWaking(false)
  }

  if (!response.ok) {
    let message = 'Request failed (' + response.status + ')'
    try {
      const body = await response.json()
      if (body.detail) message = body.detail
    } catch {
      // not JSON, keep the generic message
    }
    throw new Error(message)
  }
  return response.json()
}

export function getDigest(hours) {
  return request('/digest?hours=' + hours)
}

export function getDigestRange(from, to) {
  return request('/digest?from=' + from + '&to=' + to)
}

export function getAlerts(days) {
  return request('/alerts?days=' + days)
}

export function getEvent(id) {
  return request('/event/' + encodeURIComponent(id))
}

export function getSettings() {
  return request('/settings')
}

export function saveSettings(changes) {
  return request('/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  })
}
