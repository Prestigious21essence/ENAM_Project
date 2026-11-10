// Where the FastAPI backend lives. Set VITE_API_URL on Vercel; local default below.
export const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

async function request(path, options) {
  const response = await fetch(API_BASE + path, options)
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
