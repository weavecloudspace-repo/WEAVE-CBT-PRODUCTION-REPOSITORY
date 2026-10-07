import { weaveRequest, queryString } from './client'

export function listResultReviewSets(options = {}) {
  return weaveRequest('/results/review-sets', options)
}

export function listExamResults(examId, params = {}, options = {}) {
  return weaveRequest(`/exams/${examId}/results${queryString(params)}`, options)
}

export function getResult(resultId, options = {}) {
  return weaveRequest(`/results/${resultId}`, options)
}

export function getExamResultControl(examId, options = {}) {
  return weaveRequest(`/exams/${examId}/execution-control`, options)
}

export function approveExamResults(examId, options = {}) {
  return weaveRequest(`/exams/${examId}/results/approve`, {
    ...options,
    method: 'POST',
    successMessage: options.successMessage || 'Examination results approved for Weave synchronization.',
  })
}

export function voidExamResults(examId, reason, options = {}) {
  return weaveRequest(`/exams/${examId}/results/void`, {
    ...options,
    method: 'POST',
    body: { reason },
    successMessage: options.successMessage || 'Examination result set voided.',
  })
}

export function voidResult(resultId, reason, options = {}) {
  return weaveRequest(`/results/${resultId}/void`, {
    ...options,
    method: 'POST',
    body: { reason },
    successMessage: options.successMessage || 'Candidate result voided.',
  })
}

export function restoreResult(resultId, reason, options = {}) {
  return weaveRequest(`/results/${resultId}/restore`, {
    ...options,
    method: 'POST',
    body: { reason },
    successMessage: options.successMessage || 'Candidate result restored.',
  })
}

export function retryExamResultSync(examId, options = {}) {
  return weaveRequest(`/exams/${examId}/results/retry-sync`, {
    ...options,
    method: 'POST',
    successMessage: options.successMessage || 'Failed result synchronization queued for retry.',
  })
}
