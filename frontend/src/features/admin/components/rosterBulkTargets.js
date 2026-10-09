export function bulkTargetId(action, candidate) {
  if (!action) return null
  if (action === 'block') {
    return candidate.status === 'eligible' && !candidate.attempt ? candidate.id : null
  }
  if (action === 'late-start') {
    return candidate.status === 'eligible' && !candidate.attempt && candidate.late_start_required
      ? candidate.id
      : null
  }
  if (action === 'interrupt') {
    return candidate.attempt?.status === 'in_progress' ? candidate.attempt.id : null
  }
  return null
}
