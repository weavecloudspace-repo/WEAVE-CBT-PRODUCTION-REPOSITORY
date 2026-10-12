import { buildAcademicLevels } from '../../../shared/academics/authoringScope'
import { ExamLifecycleFilter } from '../../../shared/exams/ExamLifecycleFilter'
import { examStatuses } from '../../../shared/exams/examPermissions'
import { useAuthoringResultReviews } from '../../../shared/exams/useAuthoringResultReviews'
import { currentExamRevisions } from '../../../shared/exams/examLineage'
import { getAnchoredPopoverPosition } from '../../../shared/ui/anchoredPopover'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  RiAddLine,
  RiArrowGoBackLine,
  RiDeleteBinLine,
  RiEdit2Line,
  RiRefreshLine,
  RiSearchLine,
  RiSendPlaneLine,
  RiShieldCheckLine,
} from '@remixicon/react'
import { ExamCard, ExamViewToggle } from '../../../shared/exams/ExamCard'
import '../../../shared/exams/exam-workspace.css'
import { Icon } from '../../../shared/icons/Icon'
import { Notice, SelectControl } from '../../../shared/ui'

const PAGE_SIZE = 12
const OPERATIONS_STATUSES = new Set(['sealed', 'active', 'suspended', 'closing', 'cancelling', 'closed', 'cancelled'])

export function AdminExamsPage({ adminData, gateway, onNavigate }) {
  const [view, setView] = useState('grid')
  const [query, setQuery] = useState('')
  const [phase, setPhase] = useState('all')
  const [levelId, setLevelId] = useState('all')
  const [subjectId, setSubjectId] = useState('all')
  const [componentId, setComponentId] = useState('all')
  const [requestedPage, setPage] = useState(1)
  const [menuExamId, setMenuExamId] = useState(null)
  const [menuPosition, setMenuPosition] = useState(null)
  const [pending, setPending] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const resultReviews = useAuthoringResultReviews(gateway, adminData.exams)
  const currentExams = useMemo(() => {
    const dispositions = new Map(resultReviews.reviews.map((review) => [review.exam_id, review.result_disposition]))
    return currentExamRevisions(adminData.exams).map((exam) => ({ ...exam, resultDisposition: dispositions.get(exam.id) }))
  }, [adminData.exams, resultReviews.reviews])
  const menuRef = useRef(null)

  const closeMenu = () => {
    setMenuExamId(null)
    setMenuPosition(null)
  }

  useEffect(() => {
    if (!menuExamId) return undefined
    const closeOutside = (event) => {
      if (!menuRef.current?.contains(event.target) && !event.target.closest?.('.teacher-exam-lifecycle__trigger')) closeMenu()
    }
    const closeEscape = (event) => { if (event.key === 'Escape') closeMenu() }
    const closeViewport = (event) => {
      if (!menuRef.current?.contains(event.target) && !event.target.closest?.('.teacher-exam-lifecycle__trigger')) closeMenu()
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('keydown', closeEscape)
    window.addEventListener('resize', closeViewport)
    window.addEventListener('scroll', closeViewport, true)
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('keydown', closeEscape)
      window.removeEventListener('resize', closeViewport)
      window.removeEventListener('scroll', closeViewport, true)
    }
  }, [menuExamId])

  useEffect(() => {
    if (!pending) return undefined
    const closeEscape = (event) => {
      if (event.key === 'Escape' && !busy) {
        setPending(null)
        setError('')
      }
    }
    document.addEventListener('keydown', closeEscape)
    return () => document.removeEventListener('keydown', closeEscape)
  }, [pending, busy])

  const counts = useMemo(() => {
    const result = Object.fromEntries(examStatuses.map((key) => [key, 0]))
    result.all = currentExams.length
    currentExams.forEach((exam) => {
      const examPhase = exam.status
      if (result[examPhase] !== undefined) result[examPhase] += 1
    })
    return result
  }, [currentExams])

  const levels = useMemo(() => buildAcademicLevels(adminData.subjects), [adminData.subjects])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return currentExams.filter((exam) => {
      if (levelId !== 'all' && exam.academicLevelId !== levelId) return false
      if (phase !== 'all' && exam.status !== phase) return false
      if (subjectId !== 'all' && exam.curriculumSubjectId !== subjectId) return false
      if (componentId !== 'all' && exam.assessmentComponentId !== componentId) return false
      if (!needle) return true
      return `${exam.title} ${exam.academicLevelName} ${exam.subjectName} ${exam.assessmentName}`.toLowerCase().includes(needle)
    })
  }, [currentExams, componentId, phase, query, subjectId, levelId])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const page = Math.min(requestedPage, pageCount)
  const visible = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const setFilter = (setter) => (value) => {
    setter(value)
    setPage(1)
  }

  const toggleMenu = (exam, trigger) => {
    if (menuExamId === exam.id) {
      closeMenu()
      return
    }
    setMenuPosition(getAnchoredPopoverPosition(trigger, { width: 330, maxHeight: 440 }).style)
    setMenuExamId(exam.id)
  }

  const request = (exam, action) => {
    closeMenu()
    setPending({ exam, action })
    setError('')
  }

  const cancelPending = () => {
    if (busy) return
    setPending(null)
    setError('')
  }

  const confirm = async () => {
    if (!pending) return
    setBusy(true)
    setError('')
    const { exam, action } = pending
    try {
      if (action === 'submit') await gateway.exams.submitExam(exam.id, exam.authoringVersion || 1)
      if (action === 'delete') await gateway.exams.deleteDraftExam(exam.id, exam.authoringVersion || 1)
      if (action === 'return-draft') await gateway.exams.returnExamToDraft(exam.id)
      if (action === 'seal') await gateway.exams.sealExam(exam.id)
      const revision = action === 'revision' ? await gateway.exams.createRevision(exam.id) : null
      await adminData.refresh()
      setPending(null)
      if (revision) onNavigate('create-exam', { selectedExamId: revision.id })
    } catch (requestError) {
      setError(requestError.userMessage || `Weave could not ${action.replace('-', ' ')} this examination.`)
    } finally {
      setBusy(false)
    }
  }

  const subjectOptions = [
    { value: 'all', label: 'All subjects' },
    ...adminData.subjects.filter((subject) => levelId === 'all' || subject.academicLevelId === levelId).map((subject) => ({ value: subject.id, label: subject.name, description: levelId === 'all' ? [subject.academicLevelName, subject.code].filter(Boolean).join(' / ') : subject.code || undefined })),
  ]
  const componentOptions = [
    { value: 'all', label: 'All components' },
    ...adminData.assessmentComponents.map((component) => ({
      value: component.id,
      label: component.name,
      description: `${component.maximumScore} marks`,
    })),
  ]

  return (
    <div className="teacher-reference-page teacher-exams-page admin-exams-page">
      <div className="teacher-page-heading teacher-exams-heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="calendar" size={27} /></span>
            <h1>Examinations</h1>
          </div>
          <p>Create, review and seal examination papers before they move into day-of operations.</p>
        </div>
        <div className="exam-heading-actions">
          <ExamLifecycleFilter value={phase} counts={counts} onChange={setFilter(setPhase)} />
        <button className="teacher-primary-action" type="button" onClick={() => onNavigate('create-exam', { selectedExamId: null })}>
          <RiAddLine size={18} /> Create Exam
        </button>
        </div>
      </div>

      {resultReviews.error && <p className="exam-authoring-recovery" role="status">{resultReviews.error}</p>}
      {adminData.error && <Notice tone="danger">{adminData.error}</Notice>}
      {adminData.warning && <Notice tone="warning">{adminData.warning}</Notice>}

      <div className="teacher-exam-filters teacher-exam-filters--refined exam-filters">
        <label className="teacher-search-control teacher-search-control--grow">
          <RiSearchLine size={18} aria-hidden="true" />
          <input aria-label="Search examinations" type="search" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1) }} placeholder="Search by title, level, subject, or assessment..." />
        </label>
        <SelectControl label="Academic level filter" value={levelId}
          options={[{ value: 'all', label: 'All levels' }, ...levels.map((level) => ({ value: level.id, label: level.name }))]}
          onChange={(value) => { setLevelId(value); setSubjectId('all'); setPage(1) }} />
        <SelectControl label="Exam subject filter" value={subjectId} options={subjectOptions} onChange={setFilter(setSubjectId)} />
        <SelectControl label="Assessment component filter" value={componentId} options={componentOptions} onChange={setFilter(setComponentId)} />
        <ExamViewToggle value={view} onChange={setView} />
      </div>

      <section className={`exam-collection exam-collection--${view}`} aria-label="School examination papers" aria-busy={adminData.loading}>
        {visible.map((exam) => (
          <ExamCard
            key={exam.id}
            exam={exam}
            onOpen={() => onNavigate('exam-history', { selectedExamId: exam.id })}
            onEdit={exam.status === 'draft' ? () => onNavigate('create-exam', { selectedExamId: exam.id }) : undefined}
          >
            <div className="teacher-exam-lifecycle">
              <button
                className="teacher-exam-lifecycle__trigger"
                type="button"
                aria-label={`Paper actions for ${exam.title}`}
                aria-haspopup="dialog"
                aria-expanded={menuExamId === exam.id}
                onClick={(event) => toggleMenu(exam, event.currentTarget)}
              >
                <Icon name="moreVertical" size={19} />
              </button>
              {menuExamId === exam.id && menuPosition && (
                <AdminPaperMenu
                  exam={exam}
                  style={menuPosition}
                  menuRef={menuRef}
                  onOpen={() => { closeMenu(); onNavigate('exam-history', { selectedExamId: exam.id }) }}
                  onEdit={() => { closeMenu(); onNavigate('create-exam', { selectedExamId: exam.id }) }}
                  onOperations={() => { closeMenu(); onNavigate('operation-detail', { selectedExamId: exam.id }) }}
                  onAction={(action) => request(exam, action)}
                />
              )}
            </div>
          </ExamCard>
        ))}

        {!adminData.loading && visible.length === 0 && (
          <div className="teacher-exam-collection__empty">
            <span><Icon name="calendar" size={24} /></span>
            <strong>{currentExams.length ? 'No examination papers match these filters' : 'No examination papers yet'}</strong>
            <p>{currentExams.length ? 'Adjust the search or preparation filters.' : 'Create the first draft examination for this school.'}</p>
          </div>
        )}
        {adminData.loading && <div className="teacher-exam-collection__empty"><strong>Loading examination papers…</strong></div>}

        <div className="teacher-exam-pagination teacher-exam-pagination--refined">
          <span>{filtered.length === 0 ? '0 exams' : `Showing ${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, filtered.length)} of ${filtered.length} exams`}</span>
          <div>
            <button type="button" aria-label="Previous page" disabled={page === 1} onClick={() => setPage(page - 1)}>‹</button>
            <span>{page} / {pageCount}</span>
            <button type="button" aria-label="Next page" disabled={page === pageCount} onClick={() => setPage(page + 1)}>›</button>
          </div>
        </div>
      </section>

      {pending && <PaperConfirmModal pending={pending} error={error} busy={busy} onCancel={cancelPending} onConfirm={confirm} />}
    </div>
  )
}

function AdminPaperMenu({ exam, style, menuRef, onOpen, onEdit, onOperations, onAction }) {
  const actions = authoringActions(exam)
  return createPortal(
    <div ref={menuRef} className="teacher-exam-lifecycle__menu admin-exam-lifecycle__menu" role="dialog" aria-label={`Paper actions for ${exam.title}`} style={style}>
      <div className="teacher-exam-lifecycle__heading">
        <div><strong>Paper preparation</strong><span>{preparationLabel(exam.status)}</span></div>
        <small>v{exam.authoringVersion || 1}</small>
      </div>
      <button type="button" onClick={onOpen}><Icon name="exam" size={18} /><span><strong>View examination</strong><small>Open the paper and its current preparation record.</small></span></button>
      {exam.status === 'draft' && (
        <button type="button" onClick={onEdit}><RiEdit2Line size={18} /><span><strong>Edit draft</strong><small>Update metadata, timing and delivery settings.</small></span></button>
      )}
      {exam.status === 'draft' && (
        <button type="button" onClick={onEdit}><Icon name="users" size={18} /><span><strong>Change lead</strong><small>Manage authoring ownership on the editable paper.</small></span></button>
      )}
      {actions.map((action) => {
        const ActionIcon = action.Icon
        return (
          <button key={action.key} type="button" className={action.danger ? 'teacher-exam-lifecycle__danger' : ''} onClick={() => onAction(action.key)}>
            <ActionIcon size={18} />
            <span><strong>{action.label}</strong><small>{action.copy}</small></span>
          </button>
        )
      })}
      {OPERATIONS_STATUSES.has(exam.status) && (
        <button type="button" onClick={onOperations}>
          <Icon name="operations" size={18} />
          <span><strong>Open Exam Operations</strong><small>{exam.status === 'sealed' ? 'Prepare and activate this sitting.' : 'Manage or review this examination sitting.'}</small></span>
        </button>
      )}
      {!actions.length && !OPERATIONS_STATUSES.has(exam.status) && exam.status !== 'draft' && (
        <div className="teacher-exam-lifecycle__info"><Icon name="info" size={18} /><p>This paper is read-only in the preparation workspace.</p></div>
      )}
    </div>,
    document.body,
  )
}

function authoringActions(exam) {
  if (exam.status === 'draft') return [
    { key: 'submit', label: 'Advance to review', copy: 'Validate the paper and move it into the review stage before sealing.', Icon: RiSendPlaneLine },
    { key: 'delete', label: 'Delete draft', copy: 'Permanently remove this draft.', Icon: RiDeleteBinLine, danger: true },
  ]
  if (exam.status === 'submitted') return [
    { key: 'return-draft', label: 'Return to draft', copy: 'Reopen authoring before the paper is sealed.', Icon: RiArrowGoBackLine },
    { key: 'seal', label: 'Seal examination', copy: 'Freeze questions, options and eligible target classes.', Icon: RiShieldCheckLine },
  ]
  if (exam.status === 'sealed') return [
    { key: 'revision', label: 'Create revision', copy: 'Start a new editable revision without changing this sealed paper.', Icon: RiRefreshLine },
  ]
  if (exam.status === 'closed' && exam.resultDisposition === 'voided') return [
    { key: 'revision', label: 'Create revision / Reconduct examination', copy: 'Create a draft from this voided sitting; the closed revision stays unchanged.', Icon: RiRefreshLine },
  ]
  if (exam.status === 'cancelled') return [
    { key: 'revision', label: 'Create revision', copy: 'Start a clean editable revision from the cancelled paper.', Icon: RiRefreshLine },
  ]
  return []
}

function PaperConfirmModal({ pending, error, busy, onCancel, onConfirm }) {
  const copy = authoringCopy(pending.action)
  const ModalIcon = copy.Icon
  return createPortal(
    <div className="teacher-exam-confirm-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !busy) onCancel() }}>
      <section className={`teacher-exam-confirm-modal${copy.danger ? ' is-danger' : ''}`} role="alertdialog" aria-modal="true" aria-labelledby="admin-exam-confirm-title" aria-describedby="admin-exam-confirm-description">
        <div className="teacher-exam-confirm-modal__heading">
          <span><ModalIcon size={22} /></span>
          <div><h2 id="admin-exam-confirm-title">{copy.title}</h2><p id="admin-exam-confirm-description">{copy.description}</p></div>
        </div>
        <div className="teacher-exam-confirm-modal__exam"><span>Examination</span><strong>{pending.exam.title}</strong><small>{pending.exam.subjectName} · {pending.exam.assessmentName}</small></div>
        <p className="teacher-exam-confirm-modal__warning">{copy.warning}</p>
        {error && <Notice tone="danger">{error}</Notice>}
        <div className="teacher-exam-confirm-modal__actions">
          <button type="button" className="teacher-exam-confirm-modal__cancel" disabled={busy} onClick={onCancel}>Cancel</button>
          <button type="button" className={`teacher-exam-confirm-modal__confirm${copy.danger ? ' is-danger' : ''}`} disabled={busy} onClick={onConfirm}>{busy ? 'Working…' : copy.confirm}</button>
        </div>
      </section>
    </div>,
    document.body,
  )
}

function authoringCopy(action) {
  const entries = {
    submit: ['Advance this examination to review?', 'The paper will be validated and moved into the review stage before sealing.', 'Advance to review', RiSendPlaneLine, false],
    delete: ['Delete this draft examination?', 'This permanently removes the draft paper.', 'Delete draft', RiDeleteBinLine, true],
    'return-draft': ['Return this examination to draft?', 'Authoring will reopen for this submitted paper.', 'Return to draft', RiArrowGoBackLine, false],
    seal: ['Seal this examination?', 'Questions, options, component score and target classes will be frozen.', 'Seal examination', RiShieldCheckLine, false],
    revision: ['Create a new examination revision?', 'A new editable revision will be created without changing the historical revision.', 'Create revision', RiRefreshLine, false],
  }
  const [title, description, confirm, IconComponent, danger] = entries[action]
  const warnings = {
    seal: 'Sealing freezes the executable paper and hands the sitting into roster preparation and Exam Operations.',
    revision: 'The current revision remains unchanged as historical examination evidence.',
    delete: 'Deleted drafts cannot be recovered.',
  }
  return {
    title,
    description,
    confirm,
    Icon: IconComponent,
    danger,
    warning: warnings[action] || 'Weave will enforce the backend authoring lifecycle and reject stale or invalid transitions.',
  }
}

function preparationLabel(status) {
  return titleCase(status)
}

function titleCase(value) {
  return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}
