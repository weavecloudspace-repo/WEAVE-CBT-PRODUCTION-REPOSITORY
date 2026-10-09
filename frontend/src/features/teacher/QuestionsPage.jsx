import { useImagePreview } from '../../shared/useImagePreview'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { RiArchiveLine, RiCloseLine, RiDeleteBinLine, RiImageAddLine, RiMore2Line, RiRefreshLine, RiSearchLine } from '@remixicon/react'
import { Icon } from '../../shared/icons/Icon'
import { Notice, PageTitle, Panel, SegmentedControl, StatusBadge } from '../../shared/ui'
import './questions-page.css'
import './question-lifecycle-modal.css'

const MAX_QUESTION_IMAGE_SIZE = 5 * 1024 * 1024
const QUESTION_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])
const PAGE_SIZE = 10
const LIFECYCLE_POPOVER_WIDTH = 320
const LIFECYCLE_POPOVER_GAP = 8
const LIFECYCLE_VIEWPORT_PADDING = 12

export function QuestionsPage({ dispatch, teacherData, gateway }) {
  const [query, setQuery] = useState('')
  const [bankId, setBankId] = useState('all')
  const [tab, setTab] = useState('all')
  const [requestedPage, setPage] = useState(1)
  const [lifecycleQuestionId, setLifecycleQuestionId] = useState(null)
  const [lifecyclePosition, setLifecyclePosition] = useState(null)
  const [lifecycleBusyId, setLifecycleBusyId] = useState(null)
  const [pendingLifecycleAction, setPendingLifecycleAction] = useState(null)
  const [lifecycleModalError, setLifecycleModalError] = useState('')
  const lifecycleRef = useRef(null)

  const counts = useMemo(() => ({
    all: teacherData.questions.length,
    single: teacherData.questions.filter((question) => question.type === 'Single choice').length,
    multiple: teacherData.questions.filter((question) => question.type === 'Multiple choice').length,
    archived: teacherData.questions.filter((question) => question.status === 'Archived').length,
  }), [teacherData.questions])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return teacherData.questions.filter((question) => {
      if (bankId !== 'all' && question.bankId !== bankId) return false
      if (tab === 'single' && question.type !== 'Single choice') return false
      if (tab === 'multiple' && question.type !== 'Multiple choice') return false
      if (tab === 'archived' && question.status !== 'Archived') return false
      if (tab !== 'archived' && tab !== 'all' && question.status === 'Archived') return false
      if (!needle) return true
      return `${question.prompt} ${question.bankName} ${question.type}`.toLowerCase().includes(needle)
    })
  }, [bankId, query, tab, teacherData.questions])

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
      if (!lifecycleRef.current?.contains(event.target)) closeLifecycle()
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

  const changeFilter = (setter) => (eventOrValue) => {
    const value = eventOrValue?.target ? eventOrValue.target.value : eventOrValue
    setter(value)
    setPage(1)
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
      const fallback = action === 'delete'
        ? 'Weave could not delete this question. Questions already used by an exam must be archived instead.'
        : `Weave could not ${action} this question.`
      setLifecycleModalError(error.userMessage || fallback)
    } finally {
      setLifecycleBusyId(null)
    }
  }

  const startQuestion = () => {
    const selectedBankId = bankId === 'all' ? teacherData.banks[0]?.id : bankId
    dispatch({ type: 'staff', patch: { section: 'create-question', selectedBankId, editingQuestion: null } })
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

  const toggleLifecycle = (question, trigger) => {
    if (lifecycleQuestionId === question.id) {
      closeLifecycle()
      return
    }
    setLifecyclePosition(getLifecyclePopoverPosition(trigger))
    setLifecycleQuestionId(question.id)
  }

  const lifecycleConfirmation = pendingLifecycleAction
    ? getLifecycleConfirmationCopy(pendingLifecycleAction.action)
    : null

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
        <button
          className="teacher-primary-action"
          type="button"
          disabled={teacherData.banks.length === 0}
          onClick={startQuestion}
        >
          <Icon name="plus" size={18} /> Add Question
        </button>
      </div>

      {teacherData.error && <Notice tone="danger">{teacherData.error}</Notice>}

      <div className="teacher-question-toolbar">
        <select aria-label="Question bank filter" value={bankId} onChange={changeFilter(setBankId)}>
          <option value="all">All question banks</option>
          {teacherData.banks.map((bank) => <option key={bank.id} value={bank.id}>{bank.name}</option>)}
        </select>
        <label className="teacher-search-control teacher-search-control--grow">
          <RiSearchLine size={19} aria-hidden="true" />
          <input aria-label="Search questions" type="search" value={query} onChange={changeFilter(setQuery)} placeholder="Search questions..." />
        </label>
      </div>

      <nav className="teacher-tab-row" aria-label="Question filters">
        <TabButton label="All" value="all" current={tab} count={counts.all} onClick={changeFilter(setTab)} />
        <TabButton label="Single Choice" value="single" current={tab} count={counts.single} onClick={changeFilter(setTab)} />
        <TabButton label="Multiple Choice" value="multiple" current={tab} count={counts.multiple} onClick={changeFilter(setTab)} />
        <TabButton label="Archived" value="archived" current={tab} count={counts.archived} onClick={changeFilter(setTab)} />
      </nav>

      <section className="teacher-question-list" aria-busy={teacherData.loading} aria-label="Questions">
        <div className="teacher-question-list__header" aria-hidden="true">
          <span>Question</span>
          <span>Bank</span>
          <span>Type</span>
          <span>Status</span>
          <span>Version</span>
          <span>Actions</span>
        </div>

        {visibleQuestions.map((question, index) => (
          <article className="teacher-question-row" key={question.id}>
            <div className="teacher-question-row__question">
              <span className="teacher-question-row__number">{(page - 1) * PAGE_SIZE + index + 1}</span>
              <div>
                <h2>{question.prompt}</h2>
                {question.image && <small><RiImageAddLine size={15} aria-hidden="true" /> Includes an image</small>}
              </div>
            </div>

            <span className="teacher-question-row__bank" title={question.bankName}>{question.bankName}</span>
            <span><span className="teacher-type-pill">{question.type}</span></span>
            <span><StatusBadge tone={question.status === 'Ready' ? 'success' : 'warning'}>{question.status}</StatusBadge></span>
            <span className="teacher-question-row__version">v{question.version}</span>

            <div className="teacher-question-row__actions">
              <button
                type="button"
                className="teacher-question-edit"
                disabled={question.status === 'Archived'}
                title={question.status === 'Archived' ? 'Reactivate this question before editing it.' : undefined}
                onClick={() => editQuestion(question)}
              >
                Edit
              </button>

              <div ref={lifecycleQuestionId === question.id ? lifecycleRef : undefined} className="teacher-question-lifecycle">
                <button
                  type="button"
                  className="teacher-question-lifecycle__trigger"
                  aria-label={`Question lifecycle for ${question.prompt}`}
                  aria-haspopup="dialog"
                  aria-expanded={lifecycleQuestionId === question.id}
                  onClick={(event) => toggleLifecycle(question, event.currentTarget)}
                >
                  <RiMore2Line size={20} aria-hidden="true" />
                </button>

                {lifecycleQuestionId === question.id && lifecyclePosition && (
                  <div
                    className="teacher-question-lifecycle__card"
                    role="dialog"
                    aria-label={`Lifecycle for ${question.prompt}`}
                    data-placement={lifecyclePosition.placement}
                    style={lifecyclePosition.style}
                  >
                    <div className="teacher-question-lifecycle__heading">
                      <strong>Question lifecycle</strong>
                      <span>{question.status}</span>
                    </div>
                    <p>{question.status === 'Archived' ? 'Reactivate this question to return it to active authoring.' : 'Archive this question without deleting its history or exam references.'}</p>
                    <button
                      type="button"
                      onClick={() => requestLifecycleAction(question, question.status === 'Archived' ? 'reactivate' : 'archive')}
                    >
                      {question.status === 'Archived' ? <RiRefreshLine size={18} aria-hidden="true" /> : <RiArchiveLine size={18} aria-hidden="true" />}
                      <span>
                        <strong>{question.status === 'Archived' ? 'Reactivate question' : 'Archive question'}</strong>
                        <small>{question.status === 'Archived' ? 'Make it available for authoring again.' : 'Hide it from active authoring.'}</small>
                      </span>
                    </button>
                    {question.canDelete === true && (<button
                      type="button"
                      className="teacher-question-lifecycle__delete"
                      onClick={() => requestLifecycleAction(question, 'delete')}
                    >
                      <RiDeleteBinLine size={18} aria-hidden="true" />
                      <span>
                        <strong>Delete permanently</strong>
                        <small>Only unused questions can be deleted. Used questions must be archived.</small>
                      </span>
                    </button>)}
                  </div>
                )}
              </div>
            </div>
          </article>
        ))}

        {!teacherData.loading && visibleQuestions.length === 0 && (
          <div className="teacher-question-list__empty">
            <strong>No matching questions</strong>
            <p>Try another bank, filter, or search term.</p>
          </div>
        )}
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
        <div
          className="teacher-lifecycle-confirm-backdrop"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) closeLifecycleConfirmation()
          }}
        >
          <section
            className={`teacher-lifecycle-confirm-modal${pendingLifecycleAction.action === 'delete' ? ' teacher-lifecycle-confirm-modal--danger' : ''}`}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="teacher-lifecycle-confirm-title"
            aria-describedby="teacher-lifecycle-confirm-description"
          >
            <div className="teacher-lifecycle-confirm-modal__heading">
              <span className="teacher-lifecycle-confirm-modal__icon" aria-hidden="true">
                {pendingLifecycleAction.action === 'delete'
                  ? <RiDeleteBinLine size={22} />
                  : pendingLifecycleAction.action === 'reactivate'
                    ? <RiRefreshLine size={22} />
                    : <RiArchiveLine size={22} />}
              </span>
              <div>
                <h2 id="teacher-lifecycle-confirm-title">{lifecycleConfirmation.title}</h2>
                <p id="teacher-lifecycle-confirm-description">{lifecycleConfirmation.subtitle}</p>
              </div>
            </div>

            <div className="teacher-lifecycle-confirm-modal__question">
              <span>Question</span>
              <strong>{pendingLifecycleAction.question.prompt}</strong>
            </div>

            <p className="teacher-lifecycle-confirm-modal__warning">{lifecycleConfirmation.warning}</p>
            {lifecycleModalError && <Notice tone="danger">{lifecycleModalError}</Notice>}

            <div className="teacher-lifecycle-confirm-modal__actions">
              <button
                type="button"
                className="teacher-lifecycle-confirm-modal__cancel"
                disabled={lifecycleBusyId === pendingLifecycleAction.question.id}
                onClick={closeLifecycleConfirmation}
              >
                Cancel
              </button>
              <button
                type="button"
                className={`teacher-lifecycle-confirm-modal__confirm${pendingLifecycleAction.action === 'delete' ? ' teacher-lifecycle-confirm-modal__confirm--danger' : ''}`}
                disabled={lifecycleBusyId === pendingLifecycleAction.question.id}
                onClick={confirmLifecycleAction}
              >
                {lifecycleBusyId === pendingLifecycleAction.question.id ? lifecycleConfirmation.busyLabel : lifecycleConfirmation.confirmLabel}
              </button>
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
  if (action === 'delete') {
    return {
      title: 'Delete this question permanently?',
      subtitle: 'This action is only allowed for questions that have never been used by an exam.',
      warning: 'Permanent deletion cannot be undone. If this question has exam history, the backend will reject the deletion and you should archive it instead.',
      confirmLabel: 'Confirm delete',
      busyLabel: 'Deleting…',
    }
  }

  if (action === 'reactivate') {
    return {
      title: 'Reactivate this question?',
      subtitle: 'The question will return to active authoring.',
      warning: 'After reactivation, the question can be selected for future exam papers again, provided its question bank is active.',
      confirmLabel: 'Confirm reactivate',
      busyLabel: 'Reactivating…',
    }
  }

  return {
    title: 'Archive this question?',
    subtitle: 'The question will be removed from active authoring without deleting its history.',
    warning: 'Existing exam references are preserved. You can reactivate the question later if the containing question bank remains active.',
    confirmLabel: 'Confirm archive',
    busyLabel: 'Archiving…',
  }
}

function getLifecyclePopoverPosition(trigger) {
  const viewportWidth = typeof window === 'undefined' ? 1280 : window.innerWidth
  const viewportHeight = typeof window === 'undefined' ? 800 : window.innerHeight
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(LIFECYCLE_POPOVER_WIDTH, Math.max(240, viewportWidth - (LIFECYCLE_VIEWPORT_PADDING * 2)))
  const left = Math.max(
    LIFECYCLE_VIEWPORT_PADDING,
    Math.min(rect.right - width, viewportWidth - width - LIFECYCLE_VIEWPORT_PADDING),
  )
  const availableBelow = Math.max(0, viewportHeight - rect.bottom - LIFECYCLE_POPOVER_GAP - LIFECYCLE_VIEWPORT_PADDING)
  const availableAbove = Math.max(0, rect.top - LIFECYCLE_POPOVER_GAP - LIFECYCLE_VIEWPORT_PADDING)
  const placement = availableBelow < 230 && availableAbove > availableBelow ? 'top' : 'bottom'
  const maxHeight = Math.max(150, Math.min(320, placement === 'top' ? availableAbove : availableBelow))

  if (placement === 'top') {
    return {
      placement,
      style: {
        left,
        width,
        maxHeight,
        bottom: viewportHeight - rect.top + LIFECYCLE_POPOVER_GAP,
        top: 'auto',
      },
    }
  }

  return {
    placement,
    style: {
      left,
      width,
      maxHeight,
      top: rect.bottom + LIFECYCLE_POPOVER_GAP,
      bottom: 'auto',
    },
  }
}

export function CreateQuestionPage({ state, dispatch, teacherData, gateway }) {
  const selectedQuestion = state.staff.editingQuestion || teacherData.questions?.find((question) => question.id === state.staff.selectedQuestionId)
  const isEditing = state.staff.section === 'edit-question'
  const selectedBankId = selectedQuestion?.bankId || state.staff.selectedBankId
  const selectedBank = teacherData.banks.find((bank) => bank.id === selectedBankId) || teacherData.banks[0]
  const [bankId, setBankId] = useState(selectedBank?.id || '')
  const [type, setType] = useState(selectedQuestion?.type === 'Multiple choice' ? 'multiple' : 'single')
  const initialOptions = selectedQuestion?.options?.length
    ? selectedQuestion.options.map((option, index) => [String.fromCharCode(65 + index), option.text])
    : [['A', ''], ['B', ''], ['C', ''], ['D', '']]
  const [correct, setCorrect] = useState(() => selectedQuestion?.options?.length
    ? selectedQuestion.options.flatMap((option, index) => option.is_correct ? [String.fromCharCode(65 + index)] : [])
    : ['A'])
  const [prompt, setPrompt] = useState(selectedQuestion?.prompt || '')
  const [instruction, setInstruction] = useState(selectedQuestion?.instruction || '')
  const [options, setOptions] = useState(initialOptions)
  const [imageFile, imagePreviewUrl, setImageFile] = useImagePreview()
  const [removeExistingImage, setRemoveExistingImage] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveStage, setSaveStage] = useState('')
  const imageInputRef = useRef(null)


  const toggleCorrect = (id) => {
    setCorrect((current) => type === 'single' ? [id] : current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  }

  const selectImage = (event) => {
    const file = event.target.files?.[0]
    setError('')
    if (!file) return
    if (!QUESTION_IMAGE_TYPES.has(file.type)) {
      setImageFile(null)
      setError('Choose a PNG, JPEG, or WebP image.')
      event.target.value = ''
      return
    }
    if (file.size > MAX_QUESTION_IMAGE_SIZE) {
      setImageFile(null)
      setError('Question images must be 5 MB or smaller.')
      event.target.value = ''
      return
    }
    setImageFile(file)
  }

  const removeImage = () => {
    setImageFile(null)
    if (imageInputRef.current) imageInputRef.current.value = ''
  }

  const leaveEditor = () => dispatch({ type: 'staff', patch: { section: 'questions', selectedQuestionId: null, editingQuestion: null } })

  const saveQuestion = async () => {
    setError('')
    if (!bankId) { setError('Select a question bank.'); return }
    if (!prompt.trim()) { setError('Question prompt is required.'); return }
    const payload = {
      prompt,
      instruction: instruction || null,
      options: options.filter(([, text]) => text.trim()).map(([id, text]) => ({ text, is_correct: correct.includes(id) })),
    }
    if (payload.options.length < 2) { setError('At least two options are required.'); return }

    setSaving(true)
    try {
      if (imageFile) {
        setSaveStage('Uploading image…')
        const asset = await gateway.media.uploadQuestionImage(imageFile)
        payload.image_asset_id = asset.id
      } else if (isEditing && selectedQuestion.image && removeExistingImage) {
        payload.image_asset_id = null
      }
      setSaveStage('Saving question…')
      if (isEditing) await gateway.questions.updateQuestion(selectedQuestion.id, payload)
      else if (type === 'single') await gateway.questions.createSingleChoiceQuestion(bankId, payload)
      else await gateway.questions.createMultipleChoiceQuestion(bankId, payload)
      await teacherData.refresh()
      dispatch({ type: 'staff', patch: isEditing ? { section: 'questions', selectedQuestionId: null, editingQuestion: null } : { section: 'bank-detail', selectedBankId: bankId, editingQuestion: null } })
    } catch (error) {
      setError(error.userMessage || 'Weave could not save this question.')
    } finally {
      setSaving(false)
      setSaveStage('')
    }
  }

  if (!selectedBank || (isEditing && !selectedQuestion)) {
    return (
      <div className="teacher-reference-page">
        <PageTitle title={isEditing ? 'Edit Question' : 'Create Question'} subtitle="The question editor could not be opened." />
        <Notice tone="warning">The selected question is no longer available in your current teaching scope.</Notice>
        <div><button className="button button--secondary" type="button" onClick={leaveEditor}>Back to Questions</button></div>
      </div>
    )
  }

  return (
    <div className="teacher-reference-page teacher-question-editor">
      <div className="teacher-page-head">
        <div><button className="text-button" type="button" onClick={leaveEditor}>Back to questions</button><PageTitle title={isEditing ? 'Edit Question' : 'Create Question'} subtitle={isEditing ? `Editing ${selectedQuestion.bankName || selectedBank.name}. Saving a change creates the next version.` : 'Save directly to the selected backend question bank.'} /></div>
        <div className="toolbar"><button className="button button--primary" type="button" disabled={saving} onClick={saveQuestion}>{saving ? saveStage || 'Saving…' : isEditing ? 'Save Changes' : 'Save Question'}</button></div>
      </div>
      {error && <Notice tone="danger">{error}</Notice>}
      <div className="authoring-grid">
        <Panel title="Question content">
          <label className="field-stack"><span>Question Bank</span><select aria-label="Question Bank" value={bankId} disabled={isEditing} onChange={(event) => setBankId(event.target.value)}>{teacherData.banks.map((bank) => <option key={bank.id} value={bank.id}>{bank.name}</option>)}</select></label>
          <label className="field-stack"><span>Prompt</span><textarea aria-label="Question prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} /></label>
          <label className="field-stack"><span>Instruction</span><textarea aria-label="Question instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} /></label>
          <div className="field-stack">
            <span>Question image <small>(optional)</small></span>
            <div className="upload-zone question-image-upload">
              {imagePreviewUrl ? <img src={imagePreviewUrl} alt="Selected question" /> : <span className="question-image-placeholder"><RiImageAddLine size={30} aria-hidden="true" /></span>}
              <div className="question-image-upload__copy">
                <strong>{imageFile ? imageFile.name : isEditing && selectedQuestion.image && !removeExistingImage ? 'Current question image' : 'Add a diagram or reference image'}</strong>
                <p>{imageFile ? formatFileSize(imageFile.size) : isEditing && selectedQuestion.image && !removeExistingImage ? 'Choose a new image to replace it, or remove it.' : 'PNG, JPEG, or WebP. Maximum 5 MB.'}</p>
                <div className="toolbar">
                  <label className="button button--secondary" htmlFor="question-image-upload">{imageFile ? 'Replace image' : 'Choose image'}</label>
                  {imageFile && <button className="button button--ghost" type="button" onClick={removeImage}><RiCloseLine size={16} /> Remove</button>}
                  {!imageFile && isEditing && selectedQuestion.image && !removeExistingImage && <button className="button button--ghost" type="button" onClick={() => setRemoveExistingImage(true)}><RiCloseLine size={16} /> Remove current image</button>}
                </div>
                <input ref={imageInputRef} id="question-image-upload" className="question-image-input" type="file" accept="image/png,image/jpeg,image/webp" onChange={selectImage} />
              </div>
            </div>
          </div>
        </Panel>
        <Panel title="Question settings">
          {isEditing ? (
            <div className="teacher-question-type-lock">
              <span>Question Type</span>
              <strong>{selectedQuestion.type}</strong>
              <small>The question type is fixed after creation. You can still update the prompt, answers, instruction and image.</small>
            </div>
          ) : (
            <SegmentedControl label="Question Type" value={type} options={[["single", "Single Choice"], ["multiple", "Multiple Choice"]]} onChange={setType} />
          )}
          <div className="answer-options">
            {options.map(([id, text], index) => (
              <label key={id} className="answer-option-row">
                <input type={type === 'single' ? 'radio' : 'checkbox'} checked={correct.includes(id)} onChange={() => toggleCorrect(id)} />
                <span>{id}</span>
                <input aria-label={`Option ${id}`} value={text} onChange={(event) => setOptions((current) => current.map((item, itemIndex) => itemIndex === index ? [id, event.target.value] : item))} />
                <button type="button" aria-label={`Delete option ${id}`} onClick={() => setOptions((current) => current.filter((item) => item[0] !== id))}><Icon name="trash" size={16} /></button>
              </label>
            ))}
            <button className="button button--secondary" type="button" onClick={() => setOptions((current) => [...current, [String.fromCharCode(65 + current.length), '']])}><Icon name="plus" size={16} /> Add Option</button>
          </div>
          <Notice tone="success">{type === 'single' ? 'Exactly one answer may be correct.' : 'More than one answer may be marked correct.'}</Notice>
        </Panel>
      </div>
    </div>
  )
}

function formatFileSize(size) {
  if (size < 1024) return `${size} bytes`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
