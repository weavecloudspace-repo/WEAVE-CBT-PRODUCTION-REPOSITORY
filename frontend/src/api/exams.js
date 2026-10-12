import { queryString, weaveRequest } from './client'

const DEFAULT_NORMAL_ENTRY_GRACE_MS = 10 * 60 * 1000

function withDefaultNormalEntryDeadline(payload) {
  if (!payload?.scheduled_start_at || payload.latest_normal_start_at !== undefined) return payload
  const scheduled = new Date(payload.scheduled_start_at)
  if (Number.isNaN(scheduled.getTime())) return payload
  return {
    ...payload,
    latest_normal_start_at: new Date(scheduled.getTime() + DEFAULT_NORMAL_ENTRY_GRACE_MS).toISOString(),
  }
}

export function listExams(params = {}, options = {}) {
  return weaveRequest(`/exams${queryString(params)}`, options)
}

export function listExamAttempts(examId, params = {}, options = {}) {
  return weaveRequest(`/exams/${examId}/attempts${queryString(params)}`, options)
}

export function getExam(examId, options = {}) {
  return weaveRequest(`/exams/${examId}`, options)
}

export function listLeadCandidates(params, options = {}) {
  return weaveRequest(`/exams/lead-candidates${queryString(params)}`, options)
}

export function assignExamLead(examId, leadTeacherId, expectedAuthoringVersion) {
  return weaveRequest(`/exams/${examId}/lead`, {
    method: 'PUT',
    body: { lead_teacher_id: leadTeacherId || null, expected_authoring_version: expectedAuthoringVersion },
    successMessage: 'Examination lead updated.',
  })
}

export function createExam(payload) {
  return weaveRequest('/exams', {
    method: 'POST',
    body: withDefaultNormalEntryDeadline(payload),
    successMessage: 'Examination draft created.',
  })
}

export function updateExam(examId, payload) {
  return weaveRequest(`/exams/${examId}`, {
    method: 'PATCH',
    body: withDefaultNormalEntryDeadline(payload),
    successMessage: 'Examination changes saved.',
  })
}

export function configureExamQuestions(examId, payload) {
  return weaveRequest(`/exams/${examId}/questions/configuration`, {
    method: 'PUT',
    body: payload,
    successMessage: 'Question configuration updated.',
  })
}

export function saveExamQuestionAuthoring(examId, payload) {
  return weaveRequest(`/exams/${examId}/questions/authoring`, {
    method: 'PUT',
    body: payload,
    successMessage: 'Question setup saved.',
  })
}

export function submitExam(examId, expectedAuthoringVersion = 1) {
  return weaveRequest(`/exams/${examId}/submit`, {
    method: 'POST',
    body: { expected_authoring_version: expectedAuthoringVersion },
    successMessage: 'Examination submitted for review.',
  })
}

export const returnExamToDraft = (examId) => weaveRequest(`/exams/${examId}/return-to-draft`, {
  method: 'POST',
  successMessage: 'Examination returned to draft.',
})

export function deleteDraftExam(examId, expectedAuthoringVersion = 1) {
  return weaveRequest(`/exams/${examId}${queryString({ expected_authoring_version: expectedAuthoringVersion })}`, {
    method: 'DELETE',
    successMessage: 'Draft examination deleted.',
  })
}

export const sealExam = (examId) => weaveRequest(`/exams/${examId}/seal`, {
  method: 'POST',
  successMessage: 'Examination sealed. Candidate roster preparation has started.',
})

export const createRevision = (examId) => weaveRequest(`/exams/${examId}/revisions`, {
  method: 'POST',
  successMessage: 'New examination revision created.',
})

export const activateExam = (examId) => weaveRequest(`/exams/${examId}/activate`, {
  method: 'POST',
  successMessage: 'Examination activated.',
})

export const activationPreflight = (examId) => weaveRequest(`/exams/${examId}/activation-preflight`, {
  method: 'POST',
})

export const batchExamOperation = (operation, examIds, reason) => weaveRequest('/exams/operations-batch', {
  method: 'POST',
  body: { operation, exam_ids: examIds, ...(reason ? { reason } : {}) },
})

export const rescheduleActivationImpact = (examId, changes, reason) => weaveRequest(`/exams/${examId}/activation-reschedule`, {
  method: 'POST',
  body: { changes, reason },
  successMessage: 'Affected examinations rescheduled. Review activation to continue.',
})

export const closeExam = (examId) => weaveRequest(`/exams/${examId}/close`, {
  method: 'POST',
  successMessage: 'Examination closed.',
})

export function suspendExam(examId, reason) {
  return weaveRequest(`/exams/${examId}/suspend`, {
    method: 'POST',
    body: { reason },
    successMessage: 'Examination suspended.',
  })
}

export function resumeExam(examId, reason) {
  return weaveRequest(`/exams/${examId}/resume`, {
    method: 'POST',
    body: reason ? { reason } : {},
    successMessage: 'Examination resumed.',
  })
}

export function cancelExam(examId, reason) {
  return weaveRequest(`/exams/${examId}/cancel`, {
    method: 'POST',
    body: { reason },
    successMessage: 'Examination sitting cancelled.',
  })
}

export const listAvailableInvigilators = () => weaveRequest('/exams/invigilators/available')
export const listExamInvigilators = (examId) => weaveRequest(`/exams/${examId}/invigilators`)

export function assignExamInvigilators(examId, teacherIds) {
  return weaveRequest(`/exams/${examId}/invigilators`, {
    method: 'POST',
    body: { teacher_ids: teacherIds },
    successMessage: 'Invigilator assignments updated.',
  })
}

export function removeExamInvigilators(examId, teacherIds) {
  return weaveRequest(`/exams/${examId}/invigilators/remove`, {
    method: 'POST',
    body: { teacher_ids: teacherIds },
    successMessage: 'Invigilator assignments updated.',
  })
}

export function listManualQuestions(examId, options = {}) {
  return weaveRequest(`/exams/${examId}/manual-questions`, options)
}

export function addManualQuestions(examId, questionIds, expectedAuthoringVersion = 1) {
  return weaveRequest(`/exams/${examId}/manual-questions`, {
    method: 'POST',
    body: { question_ids: questionIds, expected_authoring_version: expectedAuthoringVersion },
    successMessage: 'Questions added to the examination.',
  })
}

export function removeManualQuestion(examId, questionId, expectedAuthoringVersion = 1) {
  return weaveRequest(`/exams/${examId}/manual-questions/remove`, {
    method: 'POST',
    body: { question_id: questionId, expected_authoring_version: expectedAuthoringVersion },
    successMessage: 'Question removed from the examination.',
  })
}

export function reorderManualQuestions(examId, questionIds, expectedAuthoringVersion = 1) {
  return weaveRequest(`/exams/${examId}/manual-questions/reorder`, {
    method: 'POST',
    body: { question_ids: questionIds, expected_authoring_version: expectedAuthoringVersion },
    successMessage: 'Examination question order updated.',
  })
}
