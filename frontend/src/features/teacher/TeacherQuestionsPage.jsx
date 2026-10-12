import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { RiArchiveLine, RiDeleteBinLine, RiEdit2Line, RiImageAddLine, RiMore2Line, RiRefreshLine, RiSearchLine } from '@remixicon/react'
import { Icon } from '../../shared/icons/Icon'
import { getAnchoredPopoverPosition } from '../../shared/ui/anchoredPopover'
import { Notice, SelectControl, StatusBadge } from '../../shared/ui'
import './questions-page.css'
import './question-lifecycle-modal.css'

const PAGE_SIZE = 10

export function TeacherQuestionsPage(props) {
  return <TeacherQuestionsContent key={props.state.staff.selectedBankId || 'all'} {...props} />
}

function TeacherQuestionsContent({ state, dispatch, teacherData, gateway }) {
  const [query, setQuery] = useState('')
  const [bankId, setBankId] = useState(state.staff.selectedBankId || 'all')
  const [tab, setTab] = useState('all')
  const [requestedPage, setPage] = useState(1)
  const [lifecycleQuestionId, setLifecycleQuestionId] = useState(null)
  const [lifecyclePosition, setLifecyclePosition] = useState(null)
  const [lifecycleBusyId, setLifecycleBusyId] = useState(null)
  const [pendingLifecycleAction, setPendingLifecycleAction] = useState(null)
  const [lifecycleModalError, setLifecycleModalError] = useState('')
  const lifecycleRef = useRef(null)


  const scopedQuestions = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return teacherData.questions.filter((question) => {
      if (bankId !== 'all' && question.bankId !== bankId) return false
      return !needle || `${question.prompt} ${question.bankName} ${question.type}`.toLowerCase().includes(needle)
    })
  }, [bankId, query, teacherData.questions])

  const counts = useMemo(() => ({
    all: scopedQuestions.length,
    single: scopedQuestions.filter((question) => question.type === 'Single choice' && question.status !== 'Archived').length,
    multiple: scopedQuestions.filter((question) => question.type === 'Multiple choice' && question.status !== 'Archived').length,
    archived: scopedQuestions.filter((question) => question.status === 'Archived').length,
  }), [scopedQuestions])

  const filtered = useMemo(() => scopedQuestions.filter((question) => {
    if (tab === 'single') return question.type === 'Single choice' && question.status !== 'Archived'
    if (tab === 'multiple') return question.type === 'Multiple choice' && question.status !== 'Archived'
    if (tab === 'archived') return question.status === 'Archived'
    return true
  }), [scopedQuestions, tab])

  const bankQuestionCounts = useMemo(() => {
    const totals = new Map()
    for (const question of teacherData.questions) {
      totals.set(question.bankId, (totals.get(question.bankId) || 0) + 1)
    }
    return totals
  }, [teacherData.questions])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const page = Math.min(requestedPage, pageCount)
  const visibleQuestions = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)


  const closeLifecycle = () => {
    setLifecycleQuestionId(null)
    setLifecyclePosition(null)
  }

  const closeLifecycleConfirmation = () => {
    if (lifecycleBusyId) return
    setPendingLifecycleAction(null)
    setLifecycleModalError('')
  }

  useEffect(() => {
    if (!lifecycleQuestionId) return undefined
    const closeOnOutsideClick = (event) => {
      if (!lifecycleRef.current?.contains(event.target) && !event.target.closest?.('.teacher-question-lifecycle__trigger')) closeLifecycle()
    }
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') closeLifecycle()
    }
    const closeOnViewportChange = () => closeLifecycle()
    document.addEventListener('pointerdown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    window.addEventListener('resize', closeOnViewportChange)
    window.addEventListener('scroll', closeOnViewportChange, true)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
      window.removeEventListener('resize', closeOnViewportChange)
      window.removeEventListener('scroll', closeOnViewportChange, true)
    }
  }, [lifecycleQuestionId])

  useEffect(() => {
    if (!pendingLifecycleAction) return undefined
    const closeOnEscape = (event) => {
      if (event.key === 'Escape' && !lifecycleBusyId) { setPendingLifecycleAction(null); setLifecycleModalError('') }
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [pendingLifecycleAction, lifecycleBusyId])

  const setFilter = (setter) => (value) => {
    setter(value)
    setPage(1)
  }

  const editQuestion = (question) => {
    dispatch({
      type: 'staff',
      patch: {
        section: 'edit-question',
        selectedBankId: question.bankId,
        selectedQuestionId: question.id,
        editingQuestion: question,
      },
    })
  }

  const previewQuestion = (question) => {
    dispatch({
      type: 'staff',
      patch: {
        section: 'preview-question',
        selectedBankId: question.bankId,
        selectedQuestionId: question.id,
        editingQuestion: null,
      },
    })
  }

  const createQuestion = () => {
    const selectedBankId = bankId === 'all' ? teacherData.banks[0]?.id : bankId
    dispatch({ type: 'staff', patch: { section: 'create-question', selectedBankId, selectedQuestionId: null, editingQuestion: null } })
  }

  const requestLifecycleAction = (question, action) => {
    if (action === 'delete' && question.canDelete !== true) return
    closeLifecycle()
    setLifecycleModalError('')
    setPendingLifecycleAction({ question, action })
  }

  const confirmLifecycleAction = async () => {
    if (!pendingLifecycleAction) return
    const { question, action } = pendingLifecycleAction
    setLifecycleModalError('')
    setLifecycleBusyId(question.id)
    try {
      if (action === 'archive') await gateway.questions.archiveQuestion(question.id)
      if (action === 'reactivate') await gateway.questions.reactivateQuestion(question.id)
      if (action === 'delete') await gateway.questions.deleteUnusedQuestion(question.id)
      await teacherData.refresh()
      setPendingLifecycleAction(null)
    } catch (error) {
      setLifecycleModalError(error.userMessage || `Weave could not ${action} this question.`)
    } finally {
      setLifecycleBusyId(null)
    }
  }

  const toggleLifecycle = (question, trigger) => {
    if (lifecycleQuestionId === question.id) return closeLifecycle()
    setLifecyclePosition(getAnchoredPopoverPosition(trigger, { width: 320, maxHeight: 330 }))
    setLifecycleQuestionId(question.id)
  }

  const lifecycleConfirmation = pendingLifecycleAction ? getLifecycleConfirmationCopy(pendingLifecycleAction.action) : null
  const bankOptions = [{ value: 'all', label: 'All question banks' }, ...teacherData.banks.map((bank) => ({ value: bank.id, label: bank.name, description: `${bankQuestionCounts.get(bank.id) || 0} questions` }))]

  return (
    <div className="teacher-reference-page teacher-questions-page">
      <div className="teacher-page-heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="fileText" size={27} /></span>
            <h1>Questions</h1>
          </div>
          <p>Browse and author questions inside the banks available to your current teaching scope.</p>
        </div>
        <button className="teacher-primary-action" type="button" disabled={teacherData.banks.length === 0} onClick={createQuestion}>
          <Icon name="plus" size={18} /> Add Question
        </button>
      </div>

      {teacherData.error && <Notice tone="danger">{teacherData.error}</Notice>}

      <div className="teacher-question-toolbar">
        <SelectControl label="Question bank filter" value={bankId} options={bankOptions} onChange={setFilter(setBankId)} />
        <label className="teacher-search-control teacher-search-control--grow">
          <RiSearchLine size={19} aria-hidden="true" />
          <input aria-label="Search questions" type="search" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1) }} placeholder="Search questions..." />
        </label>
      </div>

      <nav className="teacher-tab-row" aria-label="Question filters">
        <TabButton label="All" value="all" current={tab} count={counts.all} onClick={setFilter(setTab)} />
        <TabButton label="Single Choice" value="single" current={tab} count={counts.single} onClick={setFilter(setTab)} />
        <TabButton label="Multiple Choice" value="multiple" current={tab} count={counts.multiple} onClick={setFilter(setTab)} />
        <TabButton label="Archived" value="archived" current={tab} count={counts.archived} onClick={setFilter(setTab)} />
      </nav>

      <section className="teacher-question-list" aria-busy={teacherData.loading} aria-label="Questions">
        <div className="teacher-question-list__header" aria-hidden="true">
          <span>Question</span><span>Bank</span><span>Type</span><span>Status</span><span>Version</span><span>Actions</span>
        </div>

        {visibleQuestions.map((question, index) => (
          <article className="teacher-question-row" key={question.id}>
            <button className="teacher-question-row__preview" type="button" aria-label={`Preview question: ${question.prompt}`} onClick={() => previewQuestion(question)} />
            <div className="teacher-question-row__question">
              <span className="teacher-question-row__number">{(page - 1) * PAGE_SIZE + index + 1}</span>
              <div>
                <h2>{question.prompt}</h2>
                {(question.image || question.options?.some((option) => option.image_asset_id)) && <small><RiImageAddLine size={15} aria-hidden="true" /> Includes media</small>}
              </div>
            </div>
            <span className="teacher-question-row__bank" title={question.bankName}>{question.bankName}</span>
            <span><span className="teacher-type-pill">{question.type}</span></span>
            <span><StatusBadge tone={question.status === 'Ready' ? 'success' : 'warning'}>{question.status}</StatusBadge></span>
            <span className="teacher-question-row__version">v{question.version}</span>
            <div className="teacher-question-row__actions">
              <button type="button" className="teacher-question-edit" disabled={question.status === 'Archived'} onClick={() => editQuestion(question)}>
                <RiEdit2Line size={15} /> Edit
              </button>
              <div className="teacher-question-lifecycle">
                <button type="button" className="teacher-question-lifecycle__trigger" aria-label={`Question lifecycle for ${question.prompt}`} aria-haspopup="dialog" aria-expanded={lifecycleQuestionId === question.id} onClick={(event) => toggleLifecycle(question, event.currentTarget)}>
                  <RiMore2Line size={20} aria-hidden="true" />
                </button>
                {lifecycleQuestionId === question.id && lifecyclePosition && typeof document !== 'undefined' && createPortal(
                  <div ref={lifecycleRef} className="teacher-question-lifecycle__card" role="dialog" aria-label={`Lifecycle for ${question.prompt}`} data-placement={lifecyclePosition.placement} style={lifecyclePosition.style}>
                    <div className="teacher-question-lifecycle__heading"><strong>Question lifecycle</strong><span>{question.status}</span></div>
                    <p>{question.status === 'Archived' ? 'Reactivate this question to return it to active authoring.' : 'Archive this question without deleting its history or exam references.'}</p>
                    <button type="button" onClick={() => requestLifecycleAction(question, question.status === 'Archived' ? 'reactivate' : 'archive')}>
                      {question.status === 'Archived' ? <RiRefreshLine size={18} /> : <RiArchiveLine size={18} />}
                      <span><strong>{question.status === 'Archived' ? 'Reactivate question' : 'Archive question'}</strong><small>{question.status === 'Archived' ? 'Make it available for authoring again.' : 'Hide it from active authoring.'}</small></span>
                    </button>
                    {question.canDelete === true && (<button type="button" className="teacher-question-lifecycle__delete" onClick={() => requestLifecycleAction(question, 'delete')}>
                      <RiDeleteBinLine size={18} /><span><strong>Delete permanently</strong><small>Only unused questions can be deleted. Used questions must be archived.</small></span>
                    </button>)}
                  </div>,
                  document.body,
                )}
              </div>
            </div>
          </article>
        ))}

        {!teacherData.loading && visibleQuestions.length === 0 && <div className="teacher-question-list__empty"><strong>No matching questions</strong><p>Try another bank, filter, or search term.</p></div>}
        {teacherData.loading && <div className="teacher-question-list__empty">Loading questions…</div>}
      </section>

      <div className="teacher-question-pagination">
        <span>{filtered.length === 0 ? '0 questions' : `Showing ${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, filtered.length)} of ${filtered.length} questions`}</span>
        <div>
          <button type="button" disabled={page === 1} onClick={() => setPage((current) => current - 1)} aria-label="Previous page">‹</button>
          <span>{page} / {pageCount}</span>
          <button type="button" disabled={page === pageCount} onClick={() => setPage((current) => current + 1)} aria-label="Next page">›</button>
        </div>
      </div>

      {pendingLifecycleAction && lifecycleConfirmation && typeof document !== 'undefined' && createPortal(
        <div className="teacher-lifecycle-confirm-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) closeLifecycleConfirmation() }}>
          <section className={`teacher-lifecycle-confirm-modal${pendingLifecycleAction.action === 'delete' ? ' teacher-lifecycle-confirm-modal--danger' : ''}`} role="alertdialog" aria-modal="true" aria-labelledby="teacher-lifecycle-confirm-title" aria-describedby="teacher-lifecycle-confirm-description">
            <div className="teacher-lifecycle-confirm-modal__heading">
              <span className="teacher-lifecycle-confirm-modal__icon" aria-hidden="true">{pendingLifecycleAction.action === 'delete' ? <RiDeleteBinLine size={22} /> : pendingLifecycleAction.action === 'reactivate' ? <RiRefreshLine size={22} /> : <RiArchiveLine size={22} />}</span>
              <div><h2 id="teacher-lifecycle-confirm-title">{lifecycleConfirmation.title}</h2><p id="teacher-lifecycle-confirm-description">{lifecycleConfirmation.subtitle}</p></div>
            </div>
            <div className="teacher-lifecycle-confirm-modal__question"><span>Question</span><strong>{pendingLifecycleAction.question.prompt}</strong></div>
            <p className="teacher-lifecycle-confirm-modal__warning">{lifecycleConfirmation.warning}</p>
            {lifecycleModalError && <Notice tone="danger">{lifecycleModalError}</Notice>}
            <div className="teacher-lifecycle-confirm-modal__actions">
              <button type="button" className="teacher-lifecycle-confirm-modal__cancel" disabled={lifecycleBusyId === pendingLifecycleAction.question.id} onClick={closeLifecycleConfirmation}>Cancel</button>
              <button type="button" className={`teacher-lifecycle-confirm-modal__confirm${pendingLifecycleAction.action === 'delete' ? ' teacher-lifecycle-confirm-modal__confirm--danger' : ''}`} disabled={lifecycleBusyId === pendingLifecycleAction.question.id} onClick={confirmLifecycleAction}>{lifecycleBusyId === pendingLifecycleAction.question.id ? lifecycleConfirmation.busyLabel : lifecycleConfirmation.confirmLabel}</button>
            </div>
          </section>
        </div>,
        document.body,
      )}
    </div>
  )
}

function TabButton({ label, value, current, count, onClick }) {
  return <button type="button" className={current === value ? 'active' : ''} onClick={() => onClick(value)}>{label} <span>{count}</span></button>
}

function getLifecycleConfirmationCopy(action) {
  if (action === 'delete') return { title: 'Delete this question permanently?', subtitle: 'This action is only allowed for questions that have never been used by an exam.', warning: 'Permanent deletion cannot be undone. If this question has exam history, the backend will reject the deletion and you should archive it instead.', confirmLabel: 'Confirm delete', busyLabel: 'Deleting…' }
  if (action === 'reactivate') return { title: 'Reactivate this question?', subtitle: 'The question will return to active authoring.', warning: 'After reactivation, the question can be selected for future exam papers again, provided its question bank is active.', confirmLabel: 'Confirm reactivate', busyLabel: 'Reactivating…' }
  return { title: 'Archive this question?', subtitle: 'The question will be removed from active authoring without deleting its history.', warning: 'Existing exam references are preserved. You can reactivate the question later if the containing question bank remains active.', confirmLabel: 'Confirm archive', busyLabel: 'Archiving…' }
}
