// Client-only scheduling helpers; server timestamps and examination state remain durable.
const HEARTBEAT_JITTER_MS = 2_000
const FIRST_HEARTBEAT_SPREAD_MS = 20_000

// Stagger the initial request when a room starts its exam at the same moment.
export function initialHeartbeatDelayMs(random = Math.random) {
  return Math.floor(random() * FIRST_HEARTBEAT_SPREAD_MS)
}

// Keep the 20-second recommended mean without synchronizing all students.
export function jitteredHeartbeatDelayMs(baseMs, random = Math.random) {
  return Math.max(5_000, Math.round(baseMs + (random() - 0.5) * 2 * HEARTBEAT_JITTER_MS))
}

// Visibility changes may request a heartbeat during an outstanding HTTP call.
export function singleFlight(task) {
  let inFlight = false
  return async (...args) => {
    if (inFlight) return undefined
    inFlight = true
    try {
      return await task(...args)
    } finally {
      inFlight = false
    }
  }
}
