import { weaveRequest, queryString } from './client'

export const getSyncStatus = (options = {}) => weaveRequest('/sync/status', options)

export function reconcileSync({ forceFull = false } = {}) {
  return weaveRequest(`/sync/reconcile${forceFull ? queryString({ force_full: true }) : ''}`, { method: 'POST' })
}
