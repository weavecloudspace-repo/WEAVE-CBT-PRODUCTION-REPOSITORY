import { createDefaultBranding, normalizeBranding } from '../theme/branding'

const defaultTenant = {
  schoolName: 'Weave CBT',
  nodeName: 'Local CBT node',
  initials: 'WC',
}

export const initialExam = {
  index: 0,
  answers: {},
  review: {},
  saveState: 'Saved',
  stage: 'lobby',
  submittedAt: null,
  lightbox: false,
  confirmSubmit: false,
}

export const initialStaff = {
  section: 'overview',
  selectedBankId: '',
  timetableLevelId: null,
  selectedQuestionId: null,
  selectedAIDraftId: null,
  editingQuestion: null,
  teacher: {
    name: 'Teacher',
    shortName: 'Teacher',
    role: 'Teacher',
    schoolName: 'Weave CBT',
    schoolLocation: 'Local node',
  },
  teacherBanks: [],
  teacherQuestions: [],
  teacherExams: [],
  filters: { examStatus: 'all', subject: 'all', level: 'all', attempt: 'all', sync: 'all' },
  makeups: [],
  candidates: [],
  attempts: [],
  results: [],
}

export function createInitialState() {
  return {
    view: 'boot',
    authLoading: false,
    authError: '',
    bootError: '',
    syncError: '',
    syncStatus: null,
    connectivity: 'online',
    installation: { loading: true, configured: false, status: null },
    branding: createDefaultBranding(),
    session: null,
    studentResolution: null,
    exam: initialExam,
    staff: initialStaff,
  }
}

export function getTenant(state) {
  const brandingName = state.branding?.school_name
  const tenantName = state.installation?.status?.tenant_name
  const serverName = state.installation?.status?.server_name
  const schoolName = brandingName || tenantName || defaultTenant.schoolName

  return {
    ...defaultTenant,
    schoolName,
    nodeName: serverName || defaultTenant.nodeName,
    initials: initials(schoolName),
  }
}

export function appReducer(state, action) {
  switch (action.type) {
    case 'bootStart':
      return { ...state, view: 'boot', bootError: '', installation: { ...state.installation, loading: true } }
    case 'bootSuccess':
      return {
        ...state,
        view: action.view || (action.status.configured ? 'landing' : 'welcome'),
        bootError: '',
        installation: { loading: false, configured: action.status.configured, status: action.status },
      }
    case 'bootFailure':
      return { ...state, view: 'boot', bootError: action.message, installation: { ...state.installation, loading: false } }
    case 'brandingSuccess':
      return { ...state, branding: normalizeBranding(action.branding) }
    case 'setupStart':
      return { ...state, view: 'pairing', authLoading: true, authError: '' }
    case 'setupSuccess':
      return {
        ...state,
        view: 'paired-success',
        authLoading: false,
        authError: '',
        installation: { loading: false, configured: true, status: action.status },
      }
    case 'setupFailure':
      return { ...state, view: 'pairing', authLoading: false, authError: action.message }
    case 'signOut':
      return { ...state, view: 'landing', authError: '', session: null, studentResolution: null, exam: initialExam }
    case 'authStart':
      return { ...state, authLoading: true, authError: '' }
    case 'authFailure':
      return { ...state, authLoading: false, authError: action.message }
    case 'authSuccess':
      return {
        ...state,
        authLoading: false,
        authError: '',
        session: action.session,
        view: action.view,
        exam: { ...initialExam, stage: action.examStage || initialExam.stage },
      }
    case 'syncChecking':
      return { ...state, view: 'sync-check', syncError: '' }
    case 'syncStatus':
      return {
        ...state,
        syncStatus: action.status,
        syncError: action.status.last_error || '',
        view: action.status.bootstrap_completed_at ? 'staff' : 'initial-sync',
      }
    case 'syncFailure':
      return { ...state, view: 'initial-sync', syncError: action.message }
    case 'studentResolution':
      return { ...state, studentResolution: action.resolution, view: 'student' }
    case 'view':
      return { ...state, view: action.view, authLoading: false, authError: '' }
    case 'staff':
      return { ...state, staff: { ...state.staff, ...action.patch } }
    case 'exam':
      return { ...state, exam: { ...state.exam, ...action.patch } }
    case 'answer':
      return {
        ...state,
        exam: {
          ...state.exam,
          answers: { ...state.exam.answers, [action.questionId]: [action.optionId] },
          saveState: 'Saved',
        },
      }
    default:
      return state
  }
}

function initials(value) {
  return String(value)
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}
