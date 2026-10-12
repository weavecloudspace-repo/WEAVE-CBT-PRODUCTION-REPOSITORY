import { weaveRequest } from './client'

export function startBatch(examIds) {
  return weaveRequest('/exams/start-batch', { method: 'POST', body: { exam_ids: examIds } })
}

export function getTimetableImpact(examId, options = {}) {
  return weaveRequest(`/exams/${examId}/timetable-impact`, options)
}
