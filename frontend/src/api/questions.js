import { weaveBlobRequest, weaveRequest, queryString } from './client'

const questionVersions = new Map()

function rememberQuestionVersion(question) {
  if (question?.id && Number.isInteger(question.version)) questionVersions.set(question.id, question.version)
  return question
}

export function createQuestionBank(curriculumSubjectId, payload) {
  return weaveRequest(`/questions/banks/${curriculumSubjectId}`, {
    method: 'POST',
    body: payload,
    successMessage: 'Question bank created.',
  })
}

export const listAuthorableQuestionBanks = () => weaveRequest('/questions/banks/authorable')

export function listAdminQuestionBanks(params = {}, options = {}) {
  return weaveRequest(`/questions/banks${queryString(params)}`, options)
}

export function updateQuestionBank(bankId, payload) {
  return weaveRequest(`/questions/banks/${bankId}`, {
    method: 'PATCH',
    body: payload,
    successMessage: 'Question bank updated.',
  })
}

export const archiveQuestionBank = (bankId) => weaveRequest(`/questions/banks/${bankId}/archive`, {
  method: 'POST',
  successMessage: 'Question bank archived.',
})
export const reactivateQuestionBank = (bankId) => weaveRequest(`/questions/banks/${bankId}/reactivate`, {
  method: 'POST',
  successMessage: 'Question bank reactivated.',
})
export const deleteEmptyQuestionBank = (bankId) => weaveRequest(`/questions/banks/${bankId}`, {
  method: 'DELETE',
  successMessage: 'Empty question bank deleted.',
})

export function createSingleChoiceQuestion(bankId, payload) {
  return weaveRequest(`/questions/banks/${bankId}/single-choice`, {
    method: 'POST',
    body: payload,
    successMessage: 'Question created.',
  }).then(rememberQuestionVersion)
}

export function createMultipleChoiceQuestion(bankId, payload) {
  return weaveRequest(`/questions/banks/${bankId}/multiple-choice`, {
    method: 'POST',
    body: payload,
    successMessage: 'Question created.',
  }).then(rememberQuestionVersion)
}

export function generateAIQuestionDrafts(bankId, payload, options = {}) {
  return weaveRequest(`/questions/banks/${bankId}/ai/generate`, {
    ...options,
    method: 'POST',
    body: payload,
  })
}

export function regenerateAIQuestionDraft(bankId, payload, options = {}) {
  return weaveRequest(`/questions/banks/${bankId}/ai/regenerate`, {
    ...options,
    method: 'POST',
    body: payload,
  })
}

export function regenerateStoredQuestionWithAI(questionId, payload, options = {}) {
  return weaveRequest(`/questions/${questionId}/ai/regenerate`, {
    ...options,
    method: 'POST',
    body: payload,
  })
}

export function saveAIQuestionDrafts(bankId, payload, options = {}) {
  return weaveRequest(`/questions/banks/${bankId}/ai/save`, {
    ...options,
    method: 'POST',
    body: payload,
    successMessage: options.successMessage || 'Generated questions saved.',
  }).then((result) => {
    result?.questions?.forEach(rememberQuestionVersion)
    return result
  })
}

export function listQuestionsForBank(bankId, params = {}, options = {}) {
  return weaveRequest(`/questions/banks/${bankId}/items${queryString(params)}`, options)
}

export function listManageableQuestions(params = {}, options = {}) {
  return weaveRequest(`/questions/manageable${queryString(params)}`, options)
}

export async function getQuestion(questionId) {
  const question = await weaveRequest(`/questions/${questionId}`)
  return rememberQuestionVersion(question)
}

export async function updateQuestion(questionId, payload) {
  const rememberedVersion = questionVersions.get(questionId)
  const expectedVersion = payload.expected_version ?? rememberedVersion
  const guardedPayload = expectedVersion == null
    ? payload
    : { ...payload, expected_version: expectedVersion }
  const question = await weaveRequest(`/questions/${questionId}`, {
    method: 'PATCH',
    body: guardedPayload,
    successMessage: 'Question changes saved.',
  })
  return rememberQuestionVersion(question)
}

export const archiveQuestion = (questionId) => weaveRequest(`/questions/${questionId}/archive`, {
  method: 'POST',
  successMessage: 'Question archived.',
}).then(rememberQuestionVersion)
export const reactivateQuestion = (questionId) => weaveRequest(`/questions/${questionId}/reactivate`, {
  method: 'POST',
  successMessage: 'Question reactivated.',
}).then(rememberQuestionVersion)
export const deleteUnusedQuestion = (questionId) => weaveRequest(`/questions/${questionId}`, {
  method: 'DELETE',
  successMessage: 'Unused question deleted.',
}).then((result) => {
  questionVersions.delete(questionId)
  return result
})

export const getQuestionImage = (questionId, options = {}) => weaveBlobRequest(`/questions/${questionId}/image`, options)

export const getQuestionOptionImage = (questionId, optionId, options = {}) => (
  weaveBlobRequest(`/questions/${questionId}/options/${optionId}/image`, options)
)

export function questionImageUrl(questionId) {
  return `${import.meta.env.VITE_WEAVE_API_BASE_URL || '/api/v1'}/questions/${questionId}/image`
}
