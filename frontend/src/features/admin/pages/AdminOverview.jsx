import { useEffect, useRef, useState } from 'react'
import {
  RiAddLine,
  RiCalendarTodoLine,
  RiFileAddLine,
  RiFileList3Line,
  RiMoonClearLine,
  RiSunLine,
} from '@remixicon/react'
import { getLocalBrandLogoSrc } from '../../../api/branding'
import { Icon } from '../../../shared/icons/Icon'
import { Notice } from '../../../shared/ui'

const statConfig = [
  { key: 'banks', tone: 'green', icon: BankIcon, label: 'Question Banks', caption: 'Across the school', section: 'question-banks' },
  { key: 'questions', tone: 'blue', icon: QuestionIcon, label: 'Questions', caption: 'Active and archived', section: 'questions' },
  { key: 'drafts', tone: 'amber', icon: RiFileList3Line, label: 'Draft Exams', caption: 'Still being authored', section: 'exams' },
  { key: 'submitted', tone: 'rose', icon: RiCalendarTodoLine, label: 'Submitted Exams', caption: 'Awaiting admin action', section: 'exams' },
]

function BankIcon({ size = 20 }) { return <Icon name="bank" size={size} /> }
function QuestionIcon({ size = 20 }) { return <Icon name="fileText" size={size} /> }

export function AdminOverview({ state, adminData, onNavigate }) {
  const greeting = greetingForHour(new Date().getHours())
  const isEvening = greeting === 'evening'
  const GreetingIcon = isEvening ? RiMoonClearLine : RiSunLine
  const schoolName = state.branding?.school_name || state.installation?.status?.tenant_name || 'Weave CBT'
  const schoolLogoSrc = getLocalBrandLogoSrc(state.branding)
  const draftExams = adminData.exams.filter((exam) => exam.status === 'draft')
  const submittedExams = adminData.exams.filter((exam) => exam.status === 'submitted')
  const stats = {
    banks: adminData.loading ? '—' : adminData.banks.length,
    questions: adminData.loading ? '—' : adminData.questions.length,
    drafts: adminData.loading ? '—' : draftExams.length,
    submitted: adminData.loading ? '—' : submittedExams.length,
  }

  return (
    <div className="teacher-overview-page admin-overview-page">
      <header className="teacher-overview-heading">
        <div className="teacher-page-title-line">
          <span className="teacher-page-title-icon"><Icon name="home" size={27} /></span>
          <h1>Administrator Dashboard</h1>
        </div>
        <AdminQuickActions banks={adminData.banks} onNavigate={onNavigate} />
      </header>

      <section className="teacher-overview-hero" aria-labelledby="admin-overview-title">
        <div className="teacher-overview-hero__content">
          <div className="teacher-overview-school">
            <span className="teacher-overview-school__logo">
              {schoolLogoSrc ? <img src={schoolLogoSrc} alt={`${schoolName} logo`} /> : <Icon name="school" size={28} />}
            </span>
            <strong>{schoolName}</strong>
          </div>
          <div className="teacher-overview-greeting">
            <span className="teacher-overview-time-icon" data-time-icon={isEvening ? 'moon' : 'sun'} aria-hidden="true"><GreetingIcon size={26} /></span>
            <h2 id="admin-overview-title">Good {greeting}, Admin!</h2>
          </div>
          {(adminData.session?.name || adminData.term?.name) ? (
            <div className="teacher-overview-context" aria-label="Current academic context">
              {adminData.session?.name && <span>{adminData.session.name}</span>}
              {adminData.term?.name && <span>{adminData.term.name}</span>}
            </div>
          ) : <p>Academic context will appear after the local projection is available.</p>}
        </div>
      </section>

      {adminData.error && <Notice tone="danger">{adminData.error}</Notice>}
      {!adminData.error && adminData.warning && <Notice tone="warning">Some administrator data could not be refreshed. Available local data is still shown.</Notice>}

      <section className="teacher-overview-stats" aria-label="Administrator workspace summary" aria-busy={adminData.loading}>
        {statConfig.map(({ key, ...stat }) => <OverviewStat key={key} {...stat} value={stats[key]} onClick={() => onNavigate(stat.section)} />)}
      </section>

      <section className="teacher-overview-columns">
        <article className="teacher-reference-panel teacher-reference-panel--work">
          <div className="teacher-reference-panel__head">
            <div><h2>Exams Requiring Attention</h2><p>Submitted papers and drafts that still need administrative follow-through.</p></div>
            <button type="button" onClick={() => onNavigate('exams')}>View all</button>
          </div>
          <div className="teacher-work-list">
            {[...submittedExams, ...draftExams].slice(0, 5).map((exam) => (
              <div className="teacher-work-row" key={exam.id}>
                <div><strong>{exam.title}</strong><span>{exam.subjectName} · {exam.assessmentName} · {exam.questionCount} questions</span></div>
                <span className={`teacher-mini-status teacher-mini-status--${exam.status === 'submitted' ? 'submitted' : 'draft'}`}>{exam.statusLabel}</span>
                <button type="button" onClick={() => onNavigate('exams', { selectedExamId: exam.id })}>Open</button>
              </div>
            ))}
            {!adminData.loading && submittedExams.length + draftExams.length === 0 && (
              <div className="teacher-reference-empty">
                <RiCalendarTodoLine size={25} aria-hidden="true" />
                <div><strong>No exams need attention</strong><p>New drafts and submitted papers will appear here.</p></div>
                <button type="button" onClick={() => onNavigate('create-exam')}>Create exam</button>
              </div>
            )}
          </div>
        </article>

        <article className="teacher-reference-panel teacher-reference-panel--scope">
          <div className="teacher-reference-panel__head">
            <div><h2>Question Bank Overview</h2><p>Recently available banks across the synchronized school curriculum.</p></div>
            <button type="button" onClick={() => onNavigate('question-banks')}>Manage banks</button>
          </div>
          <div className="teacher-scope-list">
            {adminData.banks.slice(0, 5).map((bank) => (
              <button className="admin-overview-bank-row" type="button" key={bank.id} onClick={() => onNavigate('bank-detail', { selectedBankId: bank.id })}>
                <div><strong>{bank.name}</strong><span>{bank.subjectName} · {bank.activeQuestionCount} active questions</span></div>
                <span>{bank.status}</span>
              </button>
            ))}
            {!adminData.loading && adminData.banks.length === 0 && (
              <div className="teacher-reference-empty teacher-reference-empty--compact"><div><strong>No question banks</strong><p>Create the first school question bank to begin authoring.</p></div></div>
            )}
          </div>
        </article>
      </section>
    </div>
  )
}

function AdminQuickActions({ banks, onNavigate }) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const close = (event) => {
      if (event.type === 'keydown' && event.key === 'Escape') setOpen(false)
      if (event.type === 'pointerdown' && menuRef.current && !menuRef.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  const go = (section, patch) => { setOpen(false); onNavigate(section, patch) }
  const firstActiveBank = banks.find((bank) => bank.status === 'Ready')

  return (
    <div className="teacher-quick-menu" ref={menuRef}>
      <button type="button" className="teacher-quick-menu__trigger" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((value) => !value)}><RiAddLine size={18} /> Quick Actions</button>
      {open && (
        <div className="teacher-quick-menu__dropdown" role="menu" aria-label="Administrator quick actions">
          <button type="button" role="menuitem" onClick={() => go('create-bank')}><Icon name="bank" size={19} /><span><strong>Create Question Bank</strong><small>Add a bank for a curriculum subject</small></span></button>
          <button type="button" role="menuitem" disabled={!firstActiveBank} onClick={() => go('create-question', { selectedBankId: firstActiveBank?.id })}><RiAddLine size={19} /><span><strong>Create Question</strong><small>Add a question to any active bank</small></span></button>
          <button type="button" role="menuitem" onClick={() => go('create-exam')}><RiFileAddLine size={19} /><span><strong>Create Exam</strong><small>Start a new draft examination</small></span></button>
          <button type="button" role="menuitem" onClick={() => go('operations')}><Icon name="operations" size={19} /><span><strong>Exam Operations</strong><small>Open the day-of examination command centre</small></span></button>
        </div>
      )}
    </div>
  )
}

function OverviewStat({ tone, icon: StatIcon, label, caption, value, onClick }) {
  return <button type="button" className={`teacher-overview-stat teacher-overview-stat--${tone}`} onClick={onClick}><span className="teacher-overview-stat__icon"><StatIcon size={23} aria-hidden="true" /></span><strong>{value}</strong><span>{label}</span><small>{caption}</small></button>
}

function greetingForHour(hour) {
  if (hour < 12) return 'morning'
  if (hour < 17) return 'afternoon'
  return 'evening'
}
