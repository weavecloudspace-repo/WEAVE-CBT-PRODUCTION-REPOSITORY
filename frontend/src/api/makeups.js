import { weaveRequest, queryString } from './client'

export function listMissedCandidates(examId, params = {}, options = {}) {
  return weaveRequest(`/exams/${examId}/missed-candidates${queryString(params)}`, options)
}

export function listMakeupReviewSets(options = {}) {
  return weaveRequest('/makeups/exams', options)
}

export function getMakeupReview(examId, params = {}, options = {}) {
  return weaveRequest(`/exams/${examId}/makeup-review${queryString(params)}`, options)
}

export function approveMakeup(candidateId, reason, options = {}) {
  return weaveRequest(`/candidates/${candidateId}/makeup-authorizations`, {
    method: 'POST',
    body: { reason },
    successMessage: options.successMessage ?? 'Make-up examination authorization granted.',
  })
}

export function listMakeupAuthorizations(candidateId, options = {}) {
  return weaveRequest(`/candidates/${candidateId}/makeup-authorizations`, options)
}

export function revokeMakeup(authorizationId, reason) {
  return weaveRequest(`/makeup-authorizations/${authorizationId}/revoke`, {
    method: 'POST',
    body: { reason },
    successMessage: 'Make-up examination authorization revoked.',
  })
}
