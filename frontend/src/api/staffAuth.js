import {
  clearStaffAccessToken,
  setStaffAccessToken,
  weaveRequest,
} from './client'

const STAFF_REFRESH_OPERATION_KEY = 'weave.staffRefreshOperationId'
const REFRESH_EARLY_MS = 5 * 60 * 1000
const REFRESH_JITTER_MS = 60 * 1000
const REFRESH_RETRY_MS = 30 * 1000

let refreshTimer = null
let refreshInFlight = null

function normalizeStaffSession(session) {
  return {
    type: 'staff',
    role: session.actor.role,
    name: session.actor.display_name,
    actor: session.actor,
    accessTokenExpiresAt: session.access_token_expires_at,
    sessionExpiresAt: session.session_expires_at,
    cloudAuthState: session.cloud_auth_state,
  }
}

function createOperationId() {
  const bytes = new Uint8Array(16)
  window.crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0'))
  return [
    hex.slice(0, 4).join(''),
    hex.slice(4, 6).join(''),
    hex.slice(6, 8).join(''),
    hex.slice(8, 10).join(''),
    hex.slice(10, 16).join(''),
  ].join('-')
}

function ensureRefreshOperationId() {
  const existing = window.localStorage.getItem(STAFF_REFRESH_OPERATION_KEY)
  if (existing) return existing
  return replaceRefreshOperationId()
}

function replaceRefreshOperationId() {
  const operationId = createOperationId()
  window.localStorage.setItem(STAFF_REFRESH_OPERATION_KEY, operationId)
  return operationId
}

function clearRefreshOperationId() {
  window.localStorage.removeItem(STAFF_REFRESH_OPERATION_KEY)
}

function clearRefreshTimer() {
  if (refreshTimer !== null) {
    window.clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

function expireStaffSession() {
  clearStaffSession()
  window.location.assign('/staff/login')
}

function scheduleStaffRefresh(accessTokenExpiresAt, sessionExpiresAt) {
  clearRefreshTimer()

  const now = Date.now()
  const accessExpiry = Date.parse(accessTokenExpiresAt || '')
  const hardExpiry = Date.parse(sessionExpiresAt || '')
  if (!Number.isFinite(accessExpiry) || !Number.isFinite(hardExpiry)) return

  if (hardExpiry <= now) {
    expireStaffSession()
    return
  }

  // Near the absolute Weave authorization deadline there is no useful refresh
  // left to perform because every new access token is truncated to that same
  // hard deadline. Let the current token finish and require a fresh login.
  if (hardExpiry - now <= REFRESH_EARLY_MS) {
    refreshTimer = window.setTimeout(expireStaffSession, hardExpiry - now)
    return
  }

  const jitter = Math.floor(Math.random() * REFRESH_JITTER_MS)
  const targetAt = accessExpiry - REFRESH_EARLY_MS - jitter
  const delay = Math.max(1000, targetAt - now)

  refreshTimer = window.setTimeout(() => {
    refreshTimer = null
    runScheduledRefresh()
  }, delay)
}

function scheduleRefreshRetry() {
  clearRefreshTimer()
  refreshTimer = window.setTimeout(() => {
    refreshTimer = null
    runScheduledRefresh()
  }, REFRESH_RETRY_MS)
}

async function runScheduledRefresh() {
  try {
    await refreshStaff()
  } catch (error) {
    if (error?.status === 401) {
      expireStaffSession()
      return
    }

    // A transient local-server/coordination failure should not turn into a
    // logout. Keep the same idempotency key and retry shortly.
    scheduleRefreshRetry()
  }
}

export async function loginStaff({ email, password }) {
  const session = await weaveRequest('/auth/login', {
    method: 'POST',
    staffAuth: false,
    body: { email, password },
  })

  // Pre-seed the operation ID for the next rotation. Every tab shares this
  // value through localStorage, so concurrent refreshes of the same HttpOnly
  // cookie identify themselves as the same logical operation.
  replaceRefreshOperationId()
  setStaffAccessToken(session.access_token)
  scheduleStaffRefresh(
    session.access_token_expires_at,
    session.session_expires_at,
  )
  return normalizeStaffSession(session)
}

export async function refreshStaff() {
  if (refreshInFlight) return refreshInFlight

  const operationId = ensureRefreshOperationId()
  refreshInFlight = weaveRequest('/auth/refresh', {
    method: 'POST',
    staffAuth: false,
    headers: { 'Idempotency-Key': operationId },
  })
    .then((session) => {
      setStaffAccessToken(session.access_token)
      replaceRefreshOperationId()
      scheduleStaffRefresh(
        session.access_token_expires_at,
        session.session_expires_at,
      )
      return normalizeStaffSession(session)
    })
    .catch((error) => {
      if (error?.status === 401) {
        clearStaffAccessToken()
        clearRefreshOperationId()
        clearRefreshTimer()
      }
      throw error
    })
    .finally(() => {
      refreshInFlight = null
    })

  return refreshInFlight
}

export async function signOutStaff() {
  try {
    await weaveRequest('/auth/logout', { method: 'POST', staffAuth: false })
  } finally {
    clearStaffSession()
  }
}

export function clearStaffSession() {
  clearRefreshTimer()
  clearRefreshOperationId()
  clearStaffAccessToken()
}
