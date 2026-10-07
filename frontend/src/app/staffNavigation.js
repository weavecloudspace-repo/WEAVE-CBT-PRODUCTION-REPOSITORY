const teacherSections = new Set(['overview', 'question-banks', 'bank-detail', 'questions', 'create-question', 'review-ai-questions', 'edit-question', 'preview-question', 'exams', 'exam-history', 'create-exam'])
const adminSections = new Set(['ai-usage', 'ai-credit-requests', 'ai-credit-purchases', 'dashboard', 'question-banks', 'create-bank', 'bank-detail', 'questions', 'create-question', 'review-ai-questions', 'edit-question', 'preview-question', 'exams', 'create-exam', 'exam-history', 'roster', 'roster-history', 'roster-detail', 'timetable', 'operations', 'operation-detail', 'results', 'result-detail', 'makeups', 'makeup-detail', 'students', 'settings'])
const examViews = { history: 'exam-history', edit: 'create-exam', roster: 'roster-detail', operations: 'operation-detail', results: 'result-detail', makeups: 'makeup-detail' }

export function staffSectionForRole(role, section) {
  if (role === 'teacher' && teacherSections.has(section)) return section
  if (role === 'admin' && adminSections.has(section)) return section
  return role === 'admin' ? 'dashboard' : 'overview'
}

export function parseStaffPath(location) {
  const url = new URL(location, 'http://local')
  const parts = url.pathname.split('/').filter(Boolean).map(decodeURIComponent)
  const [role, group, id, action] = parts
  if (role !== 'teacher' && role !== 'admin') return null
  let section = staffSectionForRole(role, group)
  let selectedQuestionId = null
  let selectedExamId = null
  let selectedBankId = url.searchParams.get('bank')
  if (group === 'questions' && id && ['edit', 'preview'].includes(action)) {
    section = action === 'edit' ? 'edit-question' : 'preview-question'
    selectedQuestionId = id
  } else if (group === 'question-banks' && id && !action) {
    section = 'bank-detail'
    selectedBankId = id
  } else if (group === 'exams' && id && examViews[action]) {
    section = staffSectionForRole(role, examViews[action])
    selectedExamId = id
  }
  const timetableLevelId = role === 'admin' && group === 'timetable' ? url.searchParams.get('level') : null
  const origin = url.searchParams.get('from')
  const questionPreviewOrigin = section === 'preview-question' && ['create-exam', 'bank-detail', 'questions'].includes(origin) ? origin : null
  if (questionPreviewOrigin === 'create-exam') selectedExamId = url.searchParams.get('exam')
  const selectedAIDraftId = section === 'review-ai-questions' ? url.searchParams.get('draft') : null
  return { view: 'staff', sessionType: 'staff', role, requiresAuth: true, staffSection: section, selectedQuestionId, selectedExamId, selectedBankId, selectedAIDraftId, questionPreviewOrigin, timetableLevelId }
}

export function pathForStaffState(state) {
  const role = state.session?.role
  if (!['teacher', 'admin'].includes(role)) return null
  const staff = state.staff
  const section = staffSectionForRole(role, staff.section === 'overview' && role === 'admin' ? 'dashboard' : staff.section)
  let path = `/${role}/${section}`
  const params = new URLSearchParams()
  if (section === 'review-ai-questions' && staff.selectedAIDraftId) params.set('draft', staff.selectedAIDraftId)
  if (['edit-question', 'preview-question'].includes(section) && staff.selectedQuestionId) {
    path = `/${role}/questions/${encodeURIComponent(staff.selectedQuestionId)}/${section === 'edit-question' ? 'edit' : 'preview'}`
  } else if (section === 'bank-detail' && staff.selectedBankId) {
    path = `/${role}/question-banks/${encodeURIComponent(staff.selectedBankId)}`
  } else if (staff.selectedExamId && Object.values(examViews).includes(section)) {
    const action = Object.keys(examViews).find((key) => examViews[key] === section)
    path = `/${role}/exams/${encodeURIComponent(staff.selectedExamId)}/${action}`
  }
  if (['create-question', 'questions', 'preview-question'].includes(section) && staff.selectedBankId) params.set('bank', staff.selectedBankId)
  if (section === 'preview-question' && staff.questionPreviewOrigin) {
    params.set('from', staff.questionPreviewOrigin)
    if (staff.questionPreviewOrigin === 'create-exam' && staff.selectedExamId) params.set('exam', staff.selectedExamId)
  }
  if (section === 'timetable' && staff.timetableLevelId) params.set('level', staff.timetableLevelId)
  return params.size ? `${path}?${params}` : path
}

export function staffPatchFromRoute(route) {
  return {
    section: staffSectionForRole(route.role, route.staffSection),
    selectedQuestionId: route.selectedQuestionId || null,
    selectedAIDraftId: route.selectedAIDraftId || null,
    selectedExamId: route.selectedExamId || null,
    selectedBankId: route.selectedBankId || null,
    questionPreviewOrigin: route.questionPreviewOrigin || null,
    timetableLevelId: route.timetableLevelId || null,
  }
}
