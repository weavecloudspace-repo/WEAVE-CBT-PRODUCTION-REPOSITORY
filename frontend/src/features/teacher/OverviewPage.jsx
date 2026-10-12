import { useEffect, useRef, useState } from 'react'
import {
  RiAddLine,
  RiBookOpenLine,
  RiCalendarTodoLine,
  RiFileAddLine,
  RiFileList3Line,
  RiGraduationCapLine,
  RiMoonClearLine,
  RiSunLine,
} from '@remixicon/react'
import { getLocalBrandLogoSrc } from '../../api/branding'
import { Icon } from '../../shared/icons/Icon'
import { Notice } from '../../shared/ui'

function BankStatIcon({ size = 20 }) {
  return <Icon name="bank" size={size} />
}

const statConfig = [
  { key: 'subjects', tone: 'blue', icon: RiBookOpenLine, label: 'My Subjects', caption: 'Assigned subjects', section: null },
  { key: 'banks', tone: 'green', icon: BankStatIcon, label: 'Question Banks', caption: 'Available to author', section: 'question-banks' },
  { key: 'drafts', tone: 'amber', icon: RiFileList3Line, label: 'Draft Exams', caption: 'Need completion', section: 'exams' },
  { key: 'submitted', tone: 'rose', icon: RiCalendarTodoLine, label: 'Submitted Exams', caption: 'Awaiting administration', section: 'exams' },
]

export function OverviewPage({ state, dispatch, teacherData }) {
  const teacherName = state.session?.actor?.display_name || state.session?.name || 'Teacher'
  const firstName = teacherName.split(' ').filter(Boolean)[0] || 'Teacher'
  const greeting = greetingForHour(new Date().getHours())
  const isEvening = greeting === 'evening'
  const GreetingIcon = isEvening ? RiMoonClearLine : RiSunLine
  const schoolName = state.branding?.school_name || state.installation?.status?.tenant_name || 'Weave CBT'
  const schoolLogoSrc = getLocalBrandLogoSrc(state.branding)
  const draftExams = teacherData.exams.filter((exam) => exam.status === 'draft')
  const submittedExams = teacherData.exams.filter((exam) => exam.status === 'submitted')
  const teachingScope = groupAssignments(teacherData.assignments)
  const stats = {
    subjects: teacherData.loading ? '—' : teacherData.subjects.length,
    banks: teacherData.loading ? '—' : teacherData.banks.length,
    drafts: teacherData.loading ? '—' : draftExams.length,
    submitted: teacherData.loading ? '—' : submittedExams.length,
  }

  const goTo = (section, patch = {}) => dispatch({ type: 'staff', patch: { section, ...patch } })
  const sessionName = teacherData.session?.name
  const termName = teacherData.term?.name

  return (
    <div className="teacher-overview-page">
      <header className="teacher-overview-heading">
        <div className="teacher-page-title-line">
          <span className="teacher-page-title-icon"><Icon name="home" size={27} /></span>
          <h1>Teacher&apos;s Dashboard</h1>
        </div>
        <TeacherQuickActions
          banks={teacherData.banks}
          onNavigate={goTo}
        />
      </header>

      <section className="teacher-overview-hero" aria-labelledby="teacher-overview-title">
        <div className="teacher-overview-hero__content">
          <div className="teacher-overview-school">
            <span className="teacher-overview-school__logo">
              {schoolLogoSrc ? <img src={schoolLogoSrc} alt={`${schoolName} logo`} /> : <Icon name="school" size={28} />}
            </span>
            <strong>{schoolName}</strong>
          </div>
          <div className="teacher-overview-greeting">
            <span className="teacher-overview-time-icon" data-time-icon={isEvening ? 'moon' : 'sun'} aria-hidden="true">
              <GreetingIcon size={26} />
            </span>
            <h2 id="teacher-overview-title">Good {greeting}, {firstName}!</h2>
          </div>
          {(sessionName || termName) ? (
            <div className="teacher-overview-context" aria-label="Current academic context">
              {sessionName && <span>{sessionName}</span>}
              {termName && <span>{termName}</span>}
            </div>
          ) : (
            <p>Academic context will appear after the local projection is available.</p>
          )}
        </div>
      </section>

      {teacherData.error && <Notice tone="danger">{teacherData.error}</Notice>}
      {!teacherData.error && teacherData.warning && <Notice tone="warning">Some dashboard data could not be refreshed. Available local data is still shown below.</Notice>}

      <section className="teacher-overview-stats" aria-label="Teacher workspace summary" aria-busy={teacherData.loading}>
        {statConfig.map(({ key, ...stat }) => (
          <OverviewStat
            key={key}
            {...stat}
            value={stats[key]}
            onClick={stat.section ? () => goTo(stat.section) : undefined}
          />
        ))}
      </section>

      <section className="teacher-overview-columns">
        <article className="teacher-reference-panel teacher-reference-panel--work">
          <div className="teacher-reference-panel__head">
            <div>
              <h2>Continue Working</h2>
              <p>Draft examinations that still need your attention.</p>
            </div>
            <button type="button" onClick={() => goTo('exams')}>View all</button>
          </div>

          <div className="teacher-work-list">
            {draftExams.slice(0, 4).map((exam) => (
              <div className="teacher-work-row" key={exam.id}>
                <div>
                  <strong>{exam.title}</strong>
                  <span>{exam.subjectName} · {exam.questionCount} questions · {formatSelectionMode(exam.selectionMode)}</span>
                </div>
                <span className="teacher-mini-status teacher-mini-status--draft">Draft</span>
                <button type="button" onClick={() => goTo('exams', { selectedExamId: exam.id })}>Continue</button>
              </div>
            ))}

            {!teacherData.loading && draftExams.length === 0 && (
              <div className="teacher-reference-empty">
                <RiCalendarTodoLine size={25} aria-hidden="true" />
                <div><strong>No draft exams right now</strong><p>When you create a paper, unfinished drafts will appear here.</p></div>
                <button type="button" onClick={() => goTo('create-exam')}>Create exam</button>
              </div>
            )}
            {teacherData.loading && <div className="teacher-reference-loading">Loading your exam workspace…</div>}
          </div>
        </article>

        <article className="teacher-reference-panel teacher-reference-panel--scope">
          <div className="teacher-reference-panel__head">
            <div>
              <h2>Your Teaching Scope</h2>
              <p>Current Weave assignments available to this CBT server.</p>
            </div>
          </div>

          <div className="teacher-scope-list">
            {teachingScope.slice(0, 5).map((subject) => (
              <div className="teacher-scope-row" key={subject.key}>
                <div><strong>{subject.name}</strong><span>{subject.classes.join(', ')}</span></div>
                <span>{subject.classes.length} {subject.classes.length === 1 ? 'class' : 'classes'}</span>
              </div>
            ))}
            {!teacherData.loading && teachingScope.length === 0 && (
              <div className="teacher-reference-empty teacher-reference-empty--compact">
                <div><strong>No effective assignments</strong><p>Assignments will appear here after they are synced from Weave.</p></div>
              </div>
            )}
          </div>
        </article>
      </section>

    </div>
  )
}

function TeacherQuickActions({ banks, onNavigate }) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined

    const closeOnOutsidePress = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) setOpen(false)
    }
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('pointerdown', closeOnOutsidePress)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePress)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  const selectAction = (section, patch) => {
    setOpen(false)
    onNavigate(section, patch)
  }

  return (
    <div className="teacher-quick-menu" ref={menuRef}>
      <button
        type="button"
        className="teacher-quick-menu__trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="teacher-quick-actions-menu"
        onClick={() => setOpen((current) => !current)}
      >
        <RiAddLine size={18} aria-hidden="true" />
        Quick Actions
      </button>
      {open && (
        <div className="teacher-quick-menu__dropdown" id="teacher-quick-actions-menu" role="menu" aria-label="Teacher quick actions">
          <button type="button" role="menuitem" disabled={banks.length === 0} onClick={() => selectAction('create-question', { selectedBankId: banks[0]?.id })}>
            <RiAddLine size={19} aria-hidden="true" />
            <span><strong>Create Question</strong><small>Add a question to your bank</small></span>
          </button>
          <button type="button" role="menuitem" onClick={() => selectAction('create-exam')}>
            <RiFileAddLine size={19} aria-hidden="true" />
            <span><strong>Create Exam</strong><small>Start a new examination</small></span>
          </button>
          <button type="button" role="menuitem" onClick={() => selectAction('question-banks')}>
            <Icon name="bank" size={19} />
            <span><strong>Question Banks</strong><small>Manage authored questions</small></span>
          </button>
          <button type="button" role="menuitem" onClick={() => selectAction('exams')}>
            <RiGraduationCapLine size={19} aria-hidden="true" />
            <span><strong>View All Exams</strong><small>Open the exam workspace</small></span>
          </button>
        </div>
      )}
    </div>
  )
}

function OverviewStat({ tone, icon: StatIcon, label, caption, value, onClick }) {
  const content = (
    <>
      <span className="teacher-overview-stat__icon"><StatIcon size={23} aria-hidden="true" /></span>
      <strong>{value}</strong>
      <span>{label}</span>
      <small>{caption}</small>
    </>
  )

  if (!onClick) return <article className={`teacher-overview-stat teacher-overview-stat--${tone}`}>{content}</article>
  return <button type="button" className={`teacher-overview-stat teacher-overview-stat--${tone}`} onClick={onClick}>{content}</button>
}

function groupAssignments(assignments) {
  const groups = new Map()
  assignments.forEach((assignment) => {
    const key = assignment.curriculumSubjectId || assignment.subjectId || assignment.subjectName
    if (!groups.has(key)) groups.set(key, { key, name: assignment.subjectName, classes: [] })
    const group = groups.get(key)
    if (assignment.className && !group.classes.includes(assignment.className)) group.classes.push(assignment.className)
  })
  return [...groups.values()]
}

function formatSelectionMode(mode) {
  return String(mode || 'random').toLowerCase() === 'manual' ? 'Manual selection' : 'Random selection'
}

function greetingForHour(hour) {
  if (hour < 12) return 'morning'
  if (hour < 17) return 'afternoon'
  return 'evening'
}
