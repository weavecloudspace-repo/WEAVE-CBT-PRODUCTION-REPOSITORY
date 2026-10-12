import { weaveBlobRequest, weaveRequest } from './client'

export const startCurrentAttempt = () => weaveRequest('/student/attempts/current/start', { method: 'POST', staffAuth: false })
export const getCurrentAttempt = () => weaveRequest('/student/attempts/current', { staffAuth: false })
export const getCurrentAttemptResult = () => weaveRequest('/student/attempts/current/result', { staffAuth: false })
export const heartbeatCurrentAttempt = () => weaveRequest('/student/attempts/current/heartbeat', { method: 'POST', staffAuth: false })
export const submitCurrentAttempt = () => weaveRequest('/student/attempts/current/submit', { method: 'POST', staffAuth: false })

export function saveCurrentAnswer(attemptQuestionId, payload) {
  return weaveRequest(`/student/attempts/current/questions/${attemptQuestionId}/answer`, {
    method: 'PUT',
    staffAuth: false,
    body: payload,
  })
}

export const getCurrentQuestionImage = (attemptQuestionId, options = {}) => weaveBlobRequest(
  `/student/attempts/current/questions/${attemptQuestionId}/image`,
  { ...options, staffAuth: false },
)

export const getCurrentOptionImage = (attemptQuestionId, attemptOptionId, options = {}) => weaveBlobRequest(
  `/student/attempts/current/questions/${attemptQuestionId}/options/${attemptOptionId}/image`,
  { ...options, staffAuth: false },
)
