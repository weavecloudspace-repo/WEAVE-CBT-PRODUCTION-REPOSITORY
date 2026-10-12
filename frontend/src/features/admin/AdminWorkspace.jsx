import { ExamHistoryPage } from '../../shared/exams/ExamHistoryPage'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getLocalBrandLogoSrc } from '../../api/branding'
import { Icon } from '../../shared/icons/Icon'
import { DashboardAccountMenu, DashboardSchoolIdentity } from '../../shared/ui'
import { QuestionBuilder } from '../teacher/QuestionBuilder'
import { TeacherAIReviewPage } from '../teacher/TeacherAIReviewPage'
import { ExamAuthoringPage } from '../../shared/exams/ExamAuthoringPage'
import { TeacherQuestionPreviewPage } from '../teacher/TeacherQuestionPreviewPage'
import { AdminExamsPage } from './pages/AdminExamsPage'
import { AdminTimetablePage } from './pages/AdminTimetablePage'
import { ExamOperations, ExamOperationsDetail } from './pages/ExamOperations'
import { AdminOverview } from './pages/AdminOverview'
import { AdminBankDetailPage, AdminQuestionBanksPage } from './pages/AdminQuestionBanks'
import { AdminQuestionsPage } from './pages/AdminQuestionsPage'
import { AdminResultDetailPage, AdminResultsPage } from './pages/AdminResultsPage'
import { AdminMakeupsPage } from './pages/AdminMakeupsPage'
import { AdminRosterDetailPage } from './pages/AdminRostersPage'
import { AdminCurrentRostersPage, AdminRosterHistoryPage } from './pages/AdminRosterViews'
import { useAdminData } from './useAdminData'
import { AdminAIPage } from './pages/AdminAIPage'
import '../teacher/teacher-dashboard.css'
import '../teacher/teacher-selects.css'
import '../teacher/teacher-exams.css'
import './admin.css'
import './admin-sidebar.css'

const bankViews = new Set(['question-banks', 'create-bank', 'bank-detail', 'questions', 'create-question', 'review-ai-questions', 'edit-question', 'preview-question'])
const examViews = new Set(['exams', 'create-exam', 'exam-history'])
const rosterViews = new Set(['roster', 'roster-history', 'roster-detail'])
const operationViews = new Set(['operations', 'operation-detail'])
const resultViews = new Set(['results', 'result-detail'])

const questionGroupViews = new Set([...bankViews])
const examinationGroupViews = new Set([
  ...examViews,
  ...rosterViews,
  ...operationViews,
  ...resultViews,
  'makeups', 'makeup-detail',
  'timetable',
])

const adminNav = [
  { type: 'link', section: 'dashboard', icon: 'home', label: 'Dashboard' },
  { type: 'link', section: 'ai-usage', icon: 'ai', label: 'AI Usage' },
  {
    type: 'group',
    id: 'questions',
    icon: 'questions',
    label: 'Questions',
    items: [
      ['question-banks', 'bank', 'Question Banks'],
      ['questions', 'fileText', 'Question Library'],
    ],
  },
  {
    type: 'group',
    id: 'examinations',
    icon: 'exam',
    label: 'Examinations',
    items: [
      ['exams', 'calendar', 'Exams'],
      ['timetable', 'clock', 'Timetable'],
      ['roster', 'roster', 'Roster'],
      ['operations', 'operations', 'Exam Operations'],
      ['results', 'results', 'Results'],
      ['makeups', 'clock', 'Makeups'],
    ],
  },
]

export function AdminWorkspace({ state, dispatch, signOut, gateway }) {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const workspaceView = topLevelView(state.staff.section)
  const [previousView, setPreviousView] = useState(workspaceView)
  const [openGroup, setOpenGroup] = useState(() => groupForView(workspaceView))
  if (previousView !== workspaceView) {
    setPreviousView(workspaceView)
    setOpenGroup(groupForView(workspaceView))
  }
  const adminData = useAdminData(gateway)
  const activeAuthoringData = useMemo(() => ({
    ...adminData,
    banks: adminData.banks.filter((bank) => bank.status === 'Ready'),
  }), [adminData])
  const examFormData = state.staff.selectedExamId ? adminData : activeAuthoringData
  const actor = state.session?.actor
  const adminName = actor?.display_name || state.session?.name || 'Administrator'
  const schoolName = state.branding?.school_name || state.installation?.status?.tenant_name || 'Weave CBT'
  const serverName = state.installation?.status?.server_name || 'Local CBT server'
  const schoolLogoSrc = getLocalBrandLogoSrc(state.branding)

  useEffect(() => {
    const className = 'teacher-dashboard-active'
    document.documentElement.classList.add(className)
    document.body.classList.add(className)
    return () => {
      document.documentElement.classList.remove(className)
      document.body.classList.remove(className)
    }
  }, [])


  const navigate = useCallback((view, patch = {}) => {
    const previewPatch = view === 'preview-question'
      ? { questionPreviewOrigin: workspaceView === 'create-exam' ? 'create-exam' : workspaceView === 'bank-detail' ? 'bank-detail' : 'questions' }
      : {}
    dispatch({ type: 'staff', patch: { section: view, timetableLevelId: null, ...previewPatch, ...patch } })
  }, [dispatch, workspaceView])

  const workspaceDispatch = useCallback((action) => {
    if (action?.type === 'staff' && action.patch?.section) {
      const { section, ...patch } = action.patch
      navigate(section, patch)
      return
    }
    dispatch(action)
  }, [dispatch, navigate])

  const navActive = (section) => {
    if (section === 'question-banks') return workspaceView === 'question-banks' || workspaceView === 'create-bank' || workspaceView === 'bank-detail'
    if (section === 'questions') return workspaceView === 'questions' || workspaceView === 'create-question' || workspaceView === 'review-ai-questions' || workspaceView === 'edit-question' || workspaceView === 'preview-question'
    if (section === 'exams') return examViews.has(workspaceView)
    if (section === 'roster') return rosterViews.has(workspaceView)
    if (section === 'operations') return operationViews.has(workspaceView)
    if (section === 'results') return resultViews.has(workspaceView)
    if (section === 'makeups') return ['makeups', 'makeup-detail'].includes(workspaceView)
    if (section === 'ai-usage') return ['ai-usage', 'ai-credit-requests', 'ai-credit-purchases'].includes(workspaceView)
    return workspaceView === section
  }

  const groupActive = (groupId) => {
    if (groupId === 'questions') return questionGroupViews.has(workspaceView)
    if (groupId === 'examinations') return examinationGroupViews.has(workspaceView)
    return false
  }

  const toggleGroup = (groupId) => {
    if (!sidebarOpen) {
      setSidebarOpen(true)
      setOpenGroup(groupId)
      return
    }
    setOpenGroup((current) => current === groupId ? null : groupId)
  }

  return (
    <main className={`teacher-shell admin-shell${sidebarOpen ? '' : ' teacher-shell--collapsed admin-shell--collapsed'}${workspaceView === 'create-question' ? ' teacher-shell--authoring' : ''}`}>
      <aside className="teacher-sidebar admin-sidebar">
        <div className="teacher-sidebar__header">
          <div className="school-card">
            <span>{schoolLogoSrc ? <img className="school-brand-logo" src={schoolLogoSrc} alt="School logo" /> : <Icon name="school" size={20} />}</span>
            <div><strong>{schoolName}</strong></div>
          </div>
        </div>
        <nav className="admin-sidebar-nav" aria-label="Administrator navigation">
          {adminNav.map((item) => {
            if (item.type === 'link') {
              return (
                <button
                  key={item.section}
                  type="button"
                  className={`admin-nav-link${navActive(item.section) ? ' active' : ''}`}
                  onClick={() => navigate(item.section)}
                  title={sidebarOpen ? undefined : item.label}
                  aria-current={navActive(item.section) ? 'page' : undefined}
                >
                  <Icon name={item.icon} size={17} /><span>{item.label}</span>
                </button>
              )
            }

            const expanded = openGroup === item.id
            const active = groupActive(item.id)
            const groupId = `admin-nav-group-${item.id}`
            return (
              <div key={item.id} className={`admin-nav-group${expanded ? ' is-open' : ''}${active ? ' is-active' : ''}`}>
                <button
                  type="button"
                  className={`admin-nav-group__trigger${active ? ' active' : ''}`}
                  onClick={() => toggleGroup(item.id)}
                  aria-expanded={expanded}
                  aria-controls={groupId}
                  title={sidebarOpen ? undefined : item.label}
                >
                  <Icon name={item.icon} size={17} />
                  <span className="admin-nav-group__label">{item.label}</span>
                  <Icon name="chevronDown" size={15} />
                </button>
                <div id={groupId} className="admin-nav-group__children" hidden={!expanded}>
                  {item.items.map(([section, icon, label]) => (
                    <button
                      key={section}
                      type="button"
                      className={`admin-nav-child${navActive(section) ? ' active' : ''}`}
                      onClick={() => navigate(section)}
                      aria-current={navActive(section) ? 'page' : undefined}
                    >
                      <span className="admin-nav-child__rail" aria-hidden="true" />
                      <Icon name={icon} size={16} />
                      <span>{label}</span>
                    </button>
                  ))}
                </div>
              </div>
            )
          })}
        </nav>
      </aside>

      <section className="teacher-main admin-main">
        <header className="teacher-topbar">
          <div className="teacher-topbar__brand">
            <button className="dashboard-sidebar-toggle" type="button" aria-label={sidebarOpen ? 'Collapse sidebar' : 'Open sidebar'} aria-expanded={sidebarOpen} onClick={() => setSidebarOpen((open) => !open)}>
              <Icon name={sidebarOpen ? 'back' : 'menu'} size={18} />
            </button>
            <DashboardSchoolIdentity schoolName={schoolName} logoSrc={schoolLogoSrc} />
          </div>

          <div className="dashboard-server-identity" title={serverName}>
            <span className="dashboard-server-identity__icon"><Icon name="database" size={15} /></span>
            <span className="dashboard-server-identity__copy">
              <small>CBT server</small>
              <strong>{serverName}</strong>
            </span>
          </div>

          <div className="teacher-topbar__actions"><DashboardAccountMenu actor={actor} fallbackName={adminName} roleLabel="Administrator" onSignOut={signOut} /></div>
        </header>
        <div className="teacher-content admin-content">
          {workspaceView === 'dashboard' && <AdminOverview state={state} adminData={adminData} onNavigate={navigate} />}
          {['ai-usage', 'ai-credit-requests', 'ai-credit-purchases'].includes(workspaceView) && <AdminAIPage api={gateway.ai} requestsPage={workspaceView === 'ai-credit-requests'} purchasesPage={workspaceView === 'ai-credit-purchases'} onNavigate={navigate} />}
          {(workspaceView === 'question-banks' || workspaceView === 'create-bank') && (
            <AdminQuestionBanksPage adminData={adminData} gateway={gateway} onNavigate={navigate} createRequested={workspaceView === 'create-bank'} onCreateHandled={() => navigate('question-banks')} />
          )}
          {workspaceView === 'bank-detail' && <AdminBankDetailPage state={state} adminData={adminData} onNavigate={navigate} />}
          {workspaceView === 'questions' && <AdminQuestionsPage state={state} dispatch={workspaceDispatch} adminData={adminData} gateway={gateway} onNavigate={navigate} />}
          {workspaceView === 'preview-question' && <TeacherQuestionPreviewPage state={state} dispatch={workspaceDispatch} teacherData={adminData} gateway={gateway} />}
          {['create-question', 'review-ai-questions'].includes(workspaceView) && (
            <div className="teacher-question-create-host" hidden={workspaceView !== 'create-question'}>
              <QuestionBuilder enableAI mode="create" state={state} dispatch={workspaceDispatch} teacherData={activeAuthoringData} gateway={gateway} />
            </div>
          )}
          {workspaceView === 'review-ai-questions' && <TeacherAIReviewPage key={state.staff.selectedAIDraftId} state={state} dispatch={workspaceDispatch} teacherData={activeAuthoringData} gateway={gateway} />}
          {workspaceView === 'edit-question' && <QuestionBuilder key={state.staff.selectedQuestionId || 'admin-question-editor'} mode="edit" state={state} dispatch={workspaceDispatch} teacherData={adminData} gateway={gateway} />}
          {workspaceView === 'exams' && <AdminExamsPage state={state} adminData={adminData} gateway={gateway} onNavigate={navigate} />}
          {workspaceView === 'timetable' && <AdminTimetablePage adminData={adminData} levelId={state.staff.timetableLevelId} onSelectLevel={(timetableLevelId) => navigate('timetable', { timetableLevelId })} />}
          {workspaceView === 'exam-history' && <ExamHistoryPage state={state} dispatch={workspaceDispatch} teacherData={adminData} gateway={gateway} />}
          {(workspaceView === 'create-exam' || (workspaceView === 'preview-question' && state.staff.questionPreviewOrigin === 'create-exam')) && (
            <div hidden={workspaceView !== 'create-exam'}>
              <ExamAuthoringPage active={workspaceView === 'create-exam'} state={state} dispatch={workspaceDispatch} teacherData={examFormData} gateway={gateway} />
            </div>
          )}
          {workspaceView === 'roster' && <AdminCurrentRostersPage adminData={adminData} onNavigate={navigate} />}
          {workspaceView === 'roster-history' && <AdminRosterHistoryPage adminData={adminData} onNavigate={navigate} />}
          {workspaceView === 'roster-detail' && <AdminRosterDetailPage state={state} adminData={adminData} gateway={gateway} onNavigate={navigate} />}
          {workspaceView === 'operations' && <ExamOperations adminData={adminData} gateway={gateway} onNavigate={navigate} />}
          {workspaceView === 'operation-detail' && <ExamOperationsDetail state={state} adminData={adminData} gateway={gateway} onNavigate={navigate} />}
          {workspaceView === 'results' && <AdminResultsPage adminData={adminData} gateway={gateway} onNavigate={navigate} />}
          {['makeups', 'makeup-detail'].includes(workspaceView) && <AdminMakeupsPage key={workspaceView === 'makeup-detail' ? state.staff.selectedExamId : 'overview'} examId={workspaceView === 'makeup-detail' ? state.staff.selectedExamId : null} adminData={adminData} gateway={gateway} onNavigate={navigate} />}
          {workspaceView === 'result-detail' && <AdminResultDetailPage state={state} adminData={adminData} gateway={gateway} onNavigate={navigate} />}
        </div>
      </section>
    </main>
  )
}

function groupForView(view) {
  if (questionGroupViews.has(view)) return 'questions'
  if (examinationGroupViews.has(view)) return 'examinations'
  return null
}

function topLevelView(section) {
  if (section === 'overview' || section === 'invigilators' || section === 'reports') return 'dashboard'
  if (section === 'students') return 'roster'
  if (section === 'exam-operations') return 'operations'
  return section || 'dashboard'
}
